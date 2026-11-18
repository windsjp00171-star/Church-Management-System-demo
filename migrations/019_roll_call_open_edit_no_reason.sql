-- 019：點名單還沒鎖定時，改打勾不用填原因
--
-- 為什麼：點名單是紙本那樣的表格——用鉛筆打勾，點錯了擦掉重打就好。012 的規則是
-- 「修改已存在的紀錄必須填原因」，結果點名單上「取消打勾」會被擋下來（要先填一段原因），
-- 一個手滑就卡住，而現場沒有人會停下來寫原因。
--
-- 新規則：場次還沒鎖定（open）時，改打勾不用原因，但**每一次修改仍然完整寫進稽核**
-- （誰、什麼時候、原本是什麼、改成什麼）；場次鎖定後，任何寫入仍必須附原因。
--
-- 影響：只是 rc_save_record 少一道檢查，不動任何資料表與既有資料。可重複執行。
-- 還原：重新執行 012_roll_call.sql 裡的 rc_save_record（CREATE OR REPLACE）。
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
