-- 009 聚會點名模塊（roll_call）
-- 設計原則：點名自成一塊，與 users / LINE 帳號完全脫鉤。
--   * 被點名的人 = rc_members（點名名冊），不引用 users.id
--   * 操作者（點名者／修改者）只存 id 與姓名快照，不設外鍵，帳號合併或刪除不影響稽核
--   * rc_audit 只許追加（觸發器擋 UPDATE / DELETE / TRUNCATE）
--   * 點名寫入一律走 rc_save_record()，同一個交易內完成「寫紀錄＋寫稽核」
--   * 所有表開 RLS 且不設政策（伺服器用服務端金鑰；公開金鑰直連什麼都讀不到）
--   * 時間一律 timestamptz（UTC）
-- 可還原：本檔只新增 rc_* 物件，回復方式見檔尾「還原」段落（不影響既有資料表）。
-- 執行方式：Supabase > SQL Editor > 貼上執行（可重複執行）

-- ── 聚會類型 ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rc_meeting_types (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name               TEXT NOT NULL,
    record_mode        TEXT NOT NULL CHECK (record_mode IN ('individual', 'headcount')),
    counts_toward_rate BOOLEAN NOT NULL DEFAULT TRUE,
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 點名名冊（與 users 無關）─────────────────────────────
CREATE TABLE IF NOT EXISTS rc_members (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'left')),
    joined_on   DATE,
    left_on     DATE,
    source      TEXT NOT NULL DEFAULT 'manual',   -- manual / import
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rc_members_status_idx ON rc_members (status, name);

-- ── 場次 ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rc_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type_id     UUID NOT NULL REFERENCES rc_meeting_types(id),
    starts_at   TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'locked')),
    headcount   INTEGER CHECK (headcount IS NULL OR headcount >= 0),  -- 僅「人數」模式使用；NULL＝尚未填，不是 0
    created_by  UUID,
    created_by_name TEXT,
    locked_at   TIMESTAMPTZ,
    locked_by   UUID,
    locked_by_name TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rc_sessions_type_time_idx ON rc_sessions (type_id, starts_at DESC);

-- ── 點名紀錄（個人）─────────────────────────────────────
CREATE TABLE IF NOT EXISTS rc_records (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID NOT NULL REFERENCES rc_sessions(id),
    member_id        UUID NOT NULL REFERENCES rc_members(id),
    status           TEXT NOT NULL CHECK (status IN ('present', 'absent', 'leave', 'late')),
    marked_by        UUID,
    marked_by_name   TEXT,
    marked_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    modified_by      UUID,
    modified_by_name TEXT,
    modified_at      TIMESTAMPTZ,
    is_backfill      BOOLEAN NOT NULL DEFAULT FALSE,   -- 事後補登（紙本）
    UNIQUE (session_id, member_id)
);

-- ── 名冊外訪客人數（不建人）──────────────────────────────
CREATE TABLE IF NOT EXISTS rc_guest_counts (
    session_id     UUID PRIMARY KEY REFERENCES rc_sessions(id),
    guest_count    INTEGER NOT NULL CHECK (guest_count >= 0),
    filled_by      UUID,
    filled_by_name TEXT,
    filled_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 稽核（只追加）──────────────────────────────────────
CREATE TABLE IF NOT EXISTS rc_audit (
    id          BIGSERIAL PRIMARY KEY,
    session_id  UUID,
    member_id   UUID,
    action      TEXT NOT NULL,        -- mark / modify / backfill / lock / headcount / guest_count
    old_value   JSONB,
    new_value   JSONB,
    reason      TEXT,
    actor_id    UUID,
    actor_name  TEXT NOT NULL,        -- 姓名快照，不因帳號刪除而變空
    at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rc_audit_session_idx ON rc_audit (session_id, at);

CREATE OR REPLACE FUNCTION rc_audit_block_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'rc_audit 只許追加，不可更新或刪除';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS rc_audit_no_update_delete ON rc_audit;
CREATE TRIGGER rc_audit_no_update_delete
    BEFORE UPDATE OR DELETE ON rc_audit
    FOR EACH ROW EXECUTE FUNCTION rc_audit_block_change();

DROP TRIGGER IF EXISTS rc_audit_no_truncate ON rc_audit;
CREATE TRIGGER rc_audit_no_truncate
    BEFORE TRUNCATE ON rc_audit
    FOR EACH STATEMENT EXECUTE FUNCTION rc_audit_block_change();

-- ── 出席率規則（不可改，要改就新增版本）─────────────────────
-- 分母、請假、遲到、中途加入／離開的算法由教會決定，問卷回收前不預設。
CREATE TABLE IF NOT EXISTS rc_rate_rules (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                      TEXT NOT NULL,
    version                   INTEGER NOT NULL,
    type_ids                  UUID[] NOT NULL,                 -- 納入分母的聚會類型
    range_start               DATE NOT NULL,
    range_end                 DATE NOT NULL,
    leave_mode                TEXT NOT NULL CHECK (leave_mode IN ('exclude', 'absent', 'present')),
    late_mode                 TEXT NOT NULL CHECK (late_mode IN ('present', 'absent', 'half')),
    respect_membership_window BOOLEAN NOT NULL,               -- 只算 joined_on～left_on 之間的場次
    note                      TEXT,
    created_by                UUID,
    created_by_name           TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, version),
    CHECK (range_end >= range_start)
);

-- ── 點名寫入：同一交易內寫紀錄與稽核 ──────────────────────
-- 規則（資料庫層守住，不只靠程式）：
--   1. 狀態必須合法；聚會類型必須是「個人」模式；被點名者必須是在籍名冊成員
--   2. 修改既有紀錄（狀態不同）必須附原因
--   3. 場次已鎖定時，任何寫入都必須附原因
--   4. 每次寫入必有一筆稽核
CREATE OR REPLACE FUNCTION rc_save_record(
    p_session    UUID,
    p_member     UUID,
    p_status     TEXT,
    p_actor      UUID,
    p_actor_name TEXT,
    p_reason     TEXT DEFAULT NULL,
    p_backfill   BOOLEAN DEFAULT FALSE
) RETURNS JSONB AS $$
DECLARE
    v_sess   rc_sessions%ROWTYPE;
    v_mode   TEXT;
    v_mstat  TEXT;
    v_old    rc_records%ROWTYPE;
    v_reason TEXT := NULLIF(btrim(COALESCE(p_reason, '')), '');
    v_action TEXT;
BEGIN
    IF p_status NOT IN ('present', 'absent', 'leave', 'late') THEN
        RAISE EXCEPTION '無效的點名狀態：%', p_status;
    END IF;
    IF COALESCE(btrim(p_actor_name), '') = '' THEN
        RAISE EXCEPTION '操作者姓名不可為空';
    END IF;

    SELECT * INTO v_sess FROM rc_sessions WHERE id = p_session FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION '找不到場次'; END IF;

    SELECT record_mode INTO v_mode FROM rc_meeting_types WHERE id = v_sess.type_id;
    IF v_mode <> 'individual' THEN
        RAISE EXCEPTION '此聚會類型不是個人點名';
    END IF;

    SELECT status INTO v_mstat FROM rc_members WHERE id = p_member;
    IF NOT FOUND THEN RAISE EXCEPTION '找不到名冊成員'; END IF;

    SELECT * INTO v_old FROM rc_records WHERE session_id = p_session AND member_id = p_member;

    IF v_old.id IS NULL AND v_mstat <> 'active' THEN
        RAISE EXCEPTION '已離開的成員不能新增點名';
    END IF;
    IF v_sess.status = 'locked' AND v_reason IS NULL THEN
        RAISE EXCEPTION '場次已鎖定，修改必須填寫原因';
    END IF;
    IF v_old.id IS NOT NULL AND v_old.status <> p_status AND v_reason IS NULL THEN
        RAISE EXCEPTION '修改點名必須填寫原因';
    END IF;

    IF v_old.id IS NULL THEN
        INSERT INTO rc_records (session_id, member_id, status, marked_by, marked_by_name, is_backfill)
        VALUES (p_session, p_member, p_status, p_actor, p_actor_name, p_backfill);
        v_action := CASE WHEN p_backfill THEN 'backfill' ELSE 'mark' END;
    ELSE
        IF v_old.status = p_status THEN
            RETURN jsonb_build_object('changed', false);
        END IF;
        UPDATE rc_records
           SET status = p_status, modified_by = p_actor, modified_by_name = p_actor_name,
               modified_at = now(), is_backfill = (is_backfill OR p_backfill)
         WHERE id = v_old.id;
        v_action := 'modify';
    END IF;

    INSERT INTO rc_audit (session_id, member_id, action, old_value, new_value, reason, actor_id, actor_name)
    VALUES (p_session, p_member, v_action,
            CASE WHEN v_old.id IS NULL THEN NULL ELSE jsonb_build_object('status', v_old.status) END,
            jsonb_build_object('status', p_status), v_reason, p_actor, p_actor_name);

    RETURN jsonb_build_object('changed', true, 'action', v_action);
END;
$$ LANGUAGE plpgsql;

-- ── 鎖定場次（同交易寫稽核）────────────────────────────────
CREATE OR REPLACE FUNCTION rc_lock_session(
    p_session UUID, p_actor UUID, p_actor_name TEXT
) RETURNS JSONB AS $$
DECLARE v_sess rc_sessions%ROWTYPE;
BEGIN
    SELECT * INTO v_sess FROM rc_sessions WHERE id = p_session FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION '找不到場次'; END IF;
    IF v_sess.status = 'locked' THEN RETURN jsonb_build_object('changed', false); END IF;
    UPDATE rc_sessions SET status = 'locked', locked_at = now(), locked_by = p_actor,
                           locked_by_name = p_actor_name WHERE id = p_session;
    INSERT INTO rc_audit (session_id, action, old_value, new_value, actor_id, actor_name)
    VALUES (p_session, 'lock', jsonb_build_object('status', 'open'), jsonb_build_object('status', 'locked'),
            p_actor, p_actor_name);
    RETURN jsonb_build_object('changed', true);
END;
$$ LANGUAGE plpgsql;

-- ── 人數／訪客人數（空白一律退回，不得當 0）──────────────────
CREATE OR REPLACE FUNCTION rc_set_count(
    p_session UUID, p_kind TEXT, p_count INTEGER,
    p_actor UUID, p_actor_name TEXT, p_reason TEXT DEFAULT NULL
) RETURNS JSONB AS $$
DECLARE
    v_sess   rc_sessions%ROWTYPE;
    v_mode   TEXT;
    v_old    INTEGER;
    v_reason TEXT := NULLIF(btrim(COALESCE(p_reason, '')), '');
BEGIN
    IF p_count IS NULL THEN RAISE EXCEPTION '人數不可空白'; END IF;
    IF p_count < 0 THEN RAISE EXCEPTION '人數不可為負數'; END IF;
    IF p_kind NOT IN ('headcount', 'guest_count') THEN RAISE EXCEPTION '無效的人數種類'; END IF;

    SELECT * INTO v_sess FROM rc_sessions WHERE id = p_session FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION '找不到場次'; END IF;
    IF v_sess.status = 'locked' AND v_reason IS NULL THEN
        RAISE EXCEPTION '場次已鎖定，修改必須填寫原因';
    END IF;

    IF p_kind = 'headcount' THEN
        SELECT record_mode INTO v_mode FROM rc_meeting_types WHERE id = v_sess.type_id;
        IF v_mode <> 'headcount' THEN RAISE EXCEPTION '此聚會類型不是人數模式'; END IF;
        v_old := v_sess.headcount;
        IF v_old IS NOT NULL AND v_old <> p_count AND v_reason IS NULL THEN
            RAISE EXCEPTION '修改人數必須填寫原因';
        END IF;
        UPDATE rc_sessions SET headcount = p_count WHERE id = p_session;
    ELSE
        SELECT guest_count INTO v_old FROM rc_guest_counts WHERE session_id = p_session;
        IF v_old IS NOT NULL AND v_old <> p_count AND v_reason IS NULL THEN
            RAISE EXCEPTION '修改訪客人數必須填寫原因';
        END IF;
        INSERT INTO rc_guest_counts (session_id, guest_count, filled_by, filled_by_name)
        VALUES (p_session, p_count, p_actor, p_actor_name)
        ON CONFLICT (session_id) DO UPDATE
           SET guest_count = EXCLUDED.guest_count, filled_by = EXCLUDED.filled_by,
               filled_by_name = EXCLUDED.filled_by_name, filled_at = now();
    END IF;

    INSERT INTO rc_audit (session_id, action, old_value, new_value, reason, actor_id, actor_name)
    VALUES (p_session, p_kind,
            CASE WHEN v_old IS NULL THEN NULL ELSE jsonb_build_object('count', v_old) END,
            jsonb_build_object('count', p_count), v_reason, p_actor, p_actor_name);
    RETURN jsonb_build_object('changed', true);
END;
$$ LANGUAGE plpgsql;

-- ── RLS：全部開啟，不設政策 ───────────────────────────────
ALTER TABLE rc_meeting_types      ENABLE ROW LEVEL SECURITY;
ALTER TABLE rc_members            ENABLE ROW LEVEL SECURITY;
ALTER TABLE rc_sessions           ENABLE ROW LEVEL SECURITY;
ALTER TABLE rc_records            ENABLE ROW LEVEL SECURITY;
ALTER TABLE rc_guest_counts       ENABLE ROW LEVEL SECURITY;
ALTER TABLE rc_audit              ENABLE ROW LEVEL SECURITY;
ALTER TABLE rc_rate_rules         ENABLE ROW LEVEL SECURITY;

-- ── 還原（需要時手動執行；會刪除點名資料，請先匯出）─────────────
-- DROP FUNCTION IF EXISTS rc_set_count(UUID, TEXT, INTEGER, UUID, TEXT, TEXT);
-- DROP FUNCTION IF EXISTS rc_lock_session(UUID, UUID, TEXT);
-- DROP FUNCTION IF EXISTS rc_save_record(UUID, UUID, TEXT, UUID, TEXT, TEXT, BOOLEAN);
-- DROP TABLE IF EXISTS rc_rate_rules, rc_audit, rc_guest_counts, rc_records,
--                      rc_sessions, rc_members, rc_meeting_types;
-- DROP FUNCTION IF EXISTS rc_audit_block_change();
