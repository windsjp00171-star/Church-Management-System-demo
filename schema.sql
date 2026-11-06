-- ============================================================
-- 整合型教會行政系統 — 完整資料庫建表 SQL
-- 適用：Supabase PostgreSQL
-- 使用方式：在 Supabase SQL Editor 貼上全部執行一次
-- 整合來源：event-registration-、church-data-hub、tianfu-diary、cell_reporter
-- ============================================================

-- 啟用 UUID 擴充
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 基礎設定表
-- ============================================================

-- 服事角色標籤（敬拜團、招待、兒主等）— 不再用於週間小組分組，小組改用 cell_groups
-- is_primary 欄位保留以維持向下相容，UI 不再顯示主/副標籤切換
CREATE TABLE IF NOT EXISTS groups (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    is_primary  BOOLEAN NOT NULL DEFAULT false,
    is_staff    BOOLEAN NOT NULL DEFAULT false,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    -- 後台權限矩陣：此副標籤可進入的後台功能模塊 key 陣列（migration 014）
    admin_modules JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE groups ADD COLUMN IF NOT EXISTS admin_modules JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS portal_links (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title         TEXT NOT NULL,
    subtitle      TEXT,
    url           TEXT NOT NULL,
    emoji         TEXT,
    border_color  TEXT,
    is_staff_only BOOLEAN NOT NULL DEFAULT false,
    member_only   BOOLEAN NOT NULL DEFAULT false,
    is_external   BOOLEAN NOT NULL DEFAULT false,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS portal_card_settings (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key        TEXT NOT NULL UNIQUE,
    is_visible BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 使用者
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    line_user_id   TEXT UNIQUE NOT NULL,
    display_name   TEXT,
    real_name      TEXT,
    picture_url    TEXT,
    member_type    TEXT NOT NULL DEFAULT 'visitor'
                       CHECK (member_type IN ('member', 'visitor')),
    group_tags     TEXT[] NOT NULL DEFAULT '{}',
    is_admin       BOOLEAN NOT NULL DEFAULT false,
    is_super_admin BOOLEAN NOT NULL DEFAULT false,
    -- 整合欄位（church-data-hub / cell_reporter）
    is_pastor      BOOLEAN NOT NULL DEFAULT false,
    is_staff       BOOLEAN NOT NULL DEFAULT false,
    role           TEXT NOT NULL DEFAULT 'pending',
    line_id        TEXT,                   -- church-data-hub 相容欄位
    is_blocked              BOOLEAN NOT NULL DEFAULT false,
    last_seen_changelog_at  TIMESTAMPTZ,     -- 更新日誌已讀時間戳
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 活動模組
-- ============================================================

CREATE TABLE IF NOT EXISTS events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title               TEXT NOT NULL,
    description         TEXT,
    location            TEXT,
    event_start         TIMESTAMPTZ,
    event_end           TIMESTAMPTZ,
    reg_start           TIMESTAMPTZ,
    reg_end             TIMESTAMPTZ,
    capacity            INTEGER,
    fee                 INTEGER NOT NULL DEFAULT 0,
    is_open             BOOLEAN NOT NULL DEFAULT false,
    poster_url          TEXT,
    allow_multiple      BOOLEAN NOT NULL DEFAULT false,
    allow_external_reg  BOOLEAN NOT NULL DEFAULT false,
    whitelist_enabled   BOOLEAN NOT NULL DEFAULT false,
    waitlist_enabled    BOOLEAN NOT NULL DEFAULT false,
    waitlist_deadline   TIMESTAMPTZ,
    checkin_enabled     BOOLEAN NOT NULL DEFAULT false,
    checkin_mode        TEXT NOT NULL DEFAULT 'registered_only'
                            CHECK (checkin_mode IN ('registered_only', 'open')),
    allow_open_checkin  BOOLEAN NOT NULL DEFAULT false,
    checkin_token       TEXT,
    party_animation     BOOLEAN NOT NULL DEFAULT true,
    meal_options        JSONB,
    reminder_days       INTEGER,
    created_by          UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_fields (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id       UUID NOT NULL REFERENCES events(id),
    label          TEXT NOT NULL,
    field_type     TEXT NOT NULL CHECK (field_type IN
                       ('text','textarea','select','checkbox','radio','number','date')),
    options        TEXT,
    is_required    BOOLEAN NOT NULL DEFAULT false,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    condition_json JSONB,
    is_archived    BOOLEAN NOT NULL DEFAULT false,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS registrations (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id       UUID NOT NULL REFERENCES events(id),
    user_id        UUID REFERENCES users(id),
    status         TEXT NOT NULL DEFAULT 'registered'
                       CHECK (status IN ('registered','waitlisted','cancelled','walk_in')),
    checked_in     BOOLEAN NOT NULL DEFAULT false,
    checked_in_at  TIMESTAMPTZ,
    guest_name     TEXT,
    guest_phone    TEXT,
    payment_status TEXT NOT NULL DEFAULT 'unpaid'
                       CHECK (payment_status IN ('unpaid','paid','waived')),
    payment_note   TEXT,  -- 金流交易編號（ecpay:交易碼 / linepay:交易碼）
    source         TEXT NOT NULL DEFAULT 'line'
                       CHECK (source IN ('line','external','import','proxy')),
    meal_selections TEXT[],
    meal_total     INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS registration_answers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    registration_id UUID NOT NULL REFERENCES registrations(id),
    field_id        UUID NOT NULL REFERENCES event_fields(id),
    answer          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS registration_whitelist (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ref_type   TEXT NOT NULL CHECK (ref_type IN ('event', 'course')),
    ref_id     UUID NOT NULL,
    user_id    UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ref_type, ref_id, user_id)
);

-- ============================================================
-- 門訓學程模組
-- ============================================================

CREATE TABLE IF NOT EXISTS course_categories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS courses (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title                    TEXT NOT NULL,
    description              TEXT,
    location                 TEXT,
    notes                    TEXT,
    period                   TEXT,
    total_sessions           INTEGER NOT NULL DEFAULT 1,
    absence_limit            INTEGER,
    material_fee             INTEGER NOT NULL DEFAULT 0,
    reg_deadline             TIMESTAMPTZ,
    reminder_days            INTEGER,
    prerequisite_course_id   UUID REFERENCES courses(id),
    category_id              UUID REFERENCES course_categories(id),
    prerequisite_category_id UUID REFERENCES course_categories(id),
    is_open                  BOOLEAN NOT NULL DEFAULT false,
    has_material             BOOLEAN NOT NULL DEFAULT false,
    whitelist_enabled        BOOLEAN NOT NULL DEFAULT false,
    auto_complete_on_checkin BOOLEAN NOT NULL DEFAULT false,
    shared_checkin_token     TEXT,
    meal_options             JSONB,
    created_by               UUID REFERENCES users(id),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS course_sessions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id      UUID NOT NULL REFERENCES courses(id),
    session_number INTEGER NOT NULL DEFAULT 1,
    title          TEXT,
    scheduled_at   TIMESTAMPTZ,
    end_time       TIMESTAMPTZ,
    checkin_token  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS course_enrollments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id       UUID NOT NULL REFERENCES courses(id),
    user_id         UUID NOT NULL REFERENCES users(id),
    status          TEXT NOT NULL DEFAULT 'enrolled'
                        CHECK (status IN ('enrolled','completed','absent','dropped')),
    completed_at    TIMESTAMPTZ,
    needs_material  BOOLEAN NOT NULL DEFAULT false,
    meal_selections TEXT[],
    meal_total      INTEGER NOT NULL DEFAULT 0,
    payment_status  TEXT NOT NULL DEFAULT 'unpaid'
                        CHECK (payment_status IN ('unpaid','paid','waived')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (course_id, user_id)
);

CREATE TABLE IF NOT EXISTS session_attendance (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES course_sessions(id),
    user_id     UUID NOT NULL REFERENCES users(id),
    attended_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    method      TEXT NOT NULL DEFAULT 'qr' CHECK (method IN ('qr','manual')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, user_id)
);

CREATE TABLE IF NOT EXISTS course_certificates (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id),
    category_id  UUID NOT NULL REFERENCES course_categories(id),
    certified_at DATE NOT NULL DEFAULT CURRENT_DATE,
    note         TEXT,
    created_by   UUID REFERENCES users(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, category_id)
);

-- ============================================================
-- 行事曆
-- ============================================================

CREATE TABLE IF NOT EXISTS church_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    event_date  DATE NOT NULL,
    end_date    DATE,
    description TEXT,
    color       TEXT NOT NULL DEFAULT '#6bcb77',
    created_by  UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS personal_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    title       TEXT NOT NULL,
    event_date  DATE NOT NULL,
    description TEXT,
    color       TEXT NOT NULL DEFAULT '#4d96ff',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 週報
-- ============================================================

CREATE TABLE IF NOT EXISTS weekly_bulletins (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title         TEXT NOT NULL,
    bulletin_date DATE NOT NULL,
    pdf_url       TEXT NOT NULL,
    created_by    UUID REFERENCES users(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 每日經文
-- ============================================================

CREATE TABLE IF NOT EXISTS daily_verses (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    text       TEXT NOT NULL,
    ref        TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active  BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS daily_verse_draws (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    drawn_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    verse_index INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, drawn_date)
);

-- ============================================================
-- 代禱麥田
-- ============================================================

CREATE TABLE IF NOT EXISTS prayers (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id),
    title          TEXT NOT NULL,
    content        TEXT NOT NULL,
    category       TEXT NOT NULL DEFAULT 'other'
                       CHECK (category IN ('health','family','work','spiritual','other')),
    is_anonymous   BOOLEAN NOT NULL DEFAULT false,
    status         TEXT NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active','answered','archived')),
    reaction_count INTEGER NOT NULL DEFAULT 0,
    comment_count  INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS prayer_reactions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prayer_id  UUID NOT NULL REFERENCES prayers(id),
    user_id    UUID NOT NULL REFERENCES users(id),
    emoji      TEXT NOT NULL DEFAULT '🙏',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (prayer_id, user_id)
);

CREATE TABLE IF NOT EXISTS prayer_comments (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prayer_id  UUID NOT NULL REFERENCES prayers(id),
    user_id    UUID NOT NULL REFERENCES users(id),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 小組討論
-- ============================================================

CREATE TABLE IF NOT EXISTS group_discussions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title         TEXT NOT NULL,
    youtube_url   TEXT,
    questions     JSONB,
    display_start DATE,
    display_end   DATE,
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 通知
-- ============================================================

CREATE TABLE IF NOT EXISTS notifications (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id),
    title      TEXT NOT NULL,
    body       TEXT,
    type       TEXT,
    ref_type   TEXT,
    ref_id     UUID,
    link       TEXT,
    is_read    BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications(user_id, created_at DESC);

-- ============================================================
-- 福音探索
-- ============================================================

CREATE TABLE IF NOT EXISTS gospel_cards (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    icon       TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active  BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gospel_form_questions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label       TEXT NOT NULL,
    placeholder TEXT,
    is_textarea BOOLEAN NOT NULL DEFAULT false,
    is_required BOOLEAN NOT NULL DEFAULT false,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gospel_inquiries (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT,
    contact       TEXT,
    message       TEXT,
    extra_answers JSONB,
    status        TEXT NOT NULL DEFAULT 'pending',
    assigned_to   TEXT,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 檔案分享（church-data-hub）
-- ============================================================

CREATE TABLE IF NOT EXISTS folders (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    parent_id     UUID REFERENCES folders(id) ON DELETE CASCADE,
    created_by    UUID REFERENCES users(id),
    visibility    TEXT NOT NULL DEFAULT 'private',
    allowed_roles TEXT[],
    allowed_users UUID[],
    allowed_groups UUID[],
    protection    TEXT NOT NULL DEFAULT 'none',
    password_hash TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS files (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    file_key      TEXT NOT NULL,
    content_type  TEXT,
    file_size     BIGINT,
    folder_id     UUID REFERENCES folders(id) ON DELETE SET NULL,
    owner_id      UUID REFERENCES users(id),
    visibility    TEXT NOT NULL DEFAULT 'private',
    allowed_roles TEXT[],
    allowed_users UUID[],
    allowed_groups UUID[],
    protection    TEXT NOT NULL DEFAULT 'none',
    password_hash TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 系統設定（key-value）
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO settings (key, value) VALUES ('max_storage_gb', '10')
ON CONFLICT (key) DO NOTHING;

-- 使用者自訂分組（church-data-hub）
CREATE TABLE IF NOT EXISTS user_groups (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT NOT NULL,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id UUID NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
    user_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, user_id)
);

-- ============================================================
-- 天父日記（tianfu-diary）
-- ============================================================

-- 讀經進度表（DB 優先，優於 plan.xlsx）
CREATE TABLE IF NOT EXISTS diary_plan (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date       DATE NOT NULL UNIQUE,      -- 程式與 CLAUDE.md 都用 date（migration 016 會把舊的 plan_date 改名）
    book       TEXT NOT NULL,
    range      TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS diary_plan_date_idx ON diary_plan (date);

-- 牧者白名單（可查閱已授權會友日記）
CREATE TABLE IF NOT EXISTS pastor_whitelist (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    line_user_id   TEXT NOT NULL UNIQUE,
    display_name   TEXT,
    picture_url    TEXT,
    active         BOOLEAN NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS diary_entries (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    line_user_id   TEXT NOT NULL,
    entry_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    content        TEXT NOT NULL,
    locked         BOOLEAN NOT NULL DEFAULT false,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (line_user_id, entry_date)
);

CREATE INDEX IF NOT EXISTS diary_entries_user_idx ON diary_entries(line_user_id, entry_date DESC);

CREATE TABLE IF NOT EXISTS diary_share_grants (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_line_user_id   TEXT NOT NULL,
    pastor_line_user_id  TEXT NOT NULL,
    granted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at        TIMESTAMPTZ,
    UNIQUE (owner_line_user_id, pastor_line_user_id)
);

-- ============================================================
-- 小組回報（cell_reporter）
-- ============================================================

-- 小組
CREATE TABLE IF NOT EXISTS cell_groups (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              TEXT NOT NULL,
    leader_name       TEXT,
    weekly_gather_day TEXT,
    is_children_group BOOLEAN NOT NULL DEFAULT false,
    is_active         BOOLEAN NOT NULL DEFAULT true,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 組員
CREATE TABLE IF NOT EXISTS cell_members (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id     UUID NOT NULL REFERENCES cell_groups(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    contact_info TEXT,
    is_active    BOOLEAN NOT NULL DEFAULT true,
    user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
    is_confirmed BOOLEAN NOT NULL DEFAULT true,  -- false = 使用者自選待管理員確認
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 組長對應（user ↔ cell_group）
CREATE TABLE IF NOT EXISTS cell_group_leaders (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id   UUID NOT NULL REFERENCES cell_groups(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, group_id)
);

-- 週報主表
CREATE TABLE IF NOT EXISTS cell_reports (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id            UUID NOT NULL REFERENCES cell_groups(id),
    week_date           DATE NOT NULL,
    attendance_count    INTEGER,
    no_meeting          BOOLEAN NOT NULL DEFAULT false,
    no_meeting_reason   TEXT,
    is_complete         BOOLEAN NOT NULL DEFAULT false,
    -- 小組長自評四大面向
    spiritual_status    TEXT,
    spiritual_note      TEXT,
    family_status       TEXT,
    family_note         TEXT,
    work_status         TEXT,
    work_note           TEXT,
    health_status       TEXT,
    health_note         TEXT,
    -- 整體狀況與建議
    group_status        TEXT,
    coworker_suggestion TEXT,
    newcomer_raw        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (group_id, week_date)
);

-- 出席紀錄
CREATE TABLE IF NOT EXISTS cell_attendance (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id     UUID NOT NULL REFERENCES cell_reports(id) ON DELETE CASCADE,
    member_id     UUID NOT NULL REFERENCES cell_members(id) ON DELETE CASCADE,
    cell_status   TEXT,   -- 小組聚會出席狀態: full/late/leave/absent
    sunday_status TEXT,   -- 主日出席狀態: full/late/leave/absent
    rpg_status    TEXT,   -- 靈修狀態: full/late/leave/absent
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (report_id, member_id)
);

-- 成人主日聚會人數
CREATE TABLE IF NOT EXISTS sunday_reports (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date                 DATE NOT NULL UNIQUE,
    first_service_count  INTEGER NOT NULL DEFAULT 0,
    second_service_count INTEGER NOT NULL DEFAULT 0,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 兒童主日聚會人數
CREATE TABLE IF NOT EXISTS children_sunday_reports (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date             DATE NOT NULL UNIQUE,
    attendance_count INTEGER NOT NULL DEFAULT 0,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 禱告會人數
CREATE TABLE IF NOT EXISTS prayer_reports (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date             DATE NOT NULL UNIQUE,
    attendance_count INTEGER NOT NULL DEFAULT 0,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 晨禱人數
CREATE TABLE IF NOT EXISTS morning_prayer_reports (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date             DATE NOT NULL UNIQUE,
    attendance_count INTEGER NOT NULL DEFAULT 0,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 自訂聚會人數（由管理員在聚會設定中新增的聚會類型）
CREATE TABLE IF NOT EXISTS custom_meeting_reports (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date             DATE NOT NULL,
    meeting_key      TEXT NOT NULL,
    attendance_count INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (date, meeting_key)
);

CREATE INDEX IF NOT EXISTS idx_custom_meeting_reports_date ON custom_meeting_reports (date);
CREATE INDEX IF NOT EXISTS idx_custom_meeting_reports_key  ON custom_meeting_reports (meeting_key);

-- 週記事
CREATE TABLE IF NOT EXISTS week_notes (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    week       DATE NOT NULL,
    note       TEXT NOT NULL,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (week)
);

-- ============================================================
-- 預設資料
-- ============================================================

INSERT INTO portal_card_settings (key, is_visible) VALUES
    ('events',    true),
    ('courses',   true),
    ('checkin',   true),
    ('verse',     true),
    ('prayer',    true),
    ('bulletin',  true),
    ('calendar',  true),
    ('gospel',    true)
ON CONFLICT (key) DO NOTHING;

-- ============================================================
-- 補充資料表（課程認證、教材庫存、留名單、每日經文自訂主題、門戶卡片）
-- ============================================================

-- 完訓認證記錄
CREATE TABLE IF NOT EXISTS course_certifications (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category_id  UUID NOT NULL REFERENCES course_categories(id) ON DELETE CASCADE,
    course_id    UUID REFERENCES courses(id) ON DELETE SET NULL,
    certified_at DATE NOT NULL DEFAULT CURRENT_DATE,
    note         TEXT,
    created_by   UUID REFERENCES users(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, category_id)
);

-- 教材主表
CREATE TABLE IF NOT EXISTS materials (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    description   TEXT,
    unit          TEXT NOT NULL DEFAULT '本',
    selling_price INTEGER NOT NULL DEFAULT 0,
    category_id   UUID REFERENCES course_categories(id) ON DELETE SET NULL,
    stock         INTEGER NOT NULL DEFAULT 0,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- material_stock 是 materials 的視圖別名
CREATE OR REPLACE VIEW material_stock AS
    SELECT id, name, description, unit, selling_price, category_id, stock, is_active, created_at
    FROM materials WHERE is_active = TRUE;

-- 教材進出記錄
CREATE TABLE IF NOT EXISTS material_transactions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_id      UUID NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    type             TEXT NOT NULL CHECK (type IN ('in','out','adjust')),
    quantity         INTEGER NOT NULL,
    unit_cost        INTEGER NOT NULL DEFAULT 0,
    total_cost       INTEGER NOT NULL DEFAULT 0,
    course_id        UUID REFERENCES courses(id) ON DELETE SET NULL,
    enrollment_id    UUID REFERENCES course_enrollments(id) ON DELETE SET NULL,
    notes            TEXT,
    transaction_date DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 洽詢（示範站的洽詢表單）
CREATE TABLE IF NOT EXISTS contact_leads (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT,
    church       TEXT,
    contact_info TEXT,
    message      TEXT,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 留名單照片
CREATE TABLE IF NOT EXISTS visitor_forms (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_path TEXT NOT NULL,
    notes      TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 每日經文自訂主題
CREATE TABLE IF NOT EXISTS verse_custom_themes (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT NOT NULL,
    image_url  TEXT,
    symbol     TEXT NOT NULL DEFAULT '✝',
    text_mode  TEXT NOT NULL DEFAULT 'light',
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 門戶卡片設定（新系統）
CREATE TABLE IF NOT EXISTS portal_cards (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key        TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL,
    emoji      TEXT DEFAULT '🔗',
    subtitle   TEXT DEFAULT '',
    url        TEXT NOT NULL,
    visible_to TEXT DEFAULT 'all',
    is_active  BOOLEAN DEFAULT TRUE,
    sort_order INTEGER DEFAULT 0,
    is_system  BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO portal_cards (key, name, emoji, subtitle, url, visible_to, sort_order) VALUES
  ('events',        '活動報名', '🎉', '查看並報名教會活動',     '/events',                       'all',         10),
  ('calendar',      '行事曆',   '📅', '教會行事曆與個人行程',   '/calendar',                     'member',      20),
  ('bulletin',      '每週週報', '📰', '最新週報與公告',         '/bulletins',                    'all',         30),
  ('prayer',        '代禱牆',   '🙏', '分享需求，互相代禱',     '/prayer',                       'all',         40),
  ('gospel',        '福音探索', '✝️', '認識信仰的第一步',       '/gospel',                       'all',         50),
  ('diary',         '天父日記', '📖', '記錄每日與神的對話',     '/diary',                        'member',      60),
  ('my_history',    '電子簽到', '🗂️', '我的活動出席紀錄',       '/my-history',                   'member',      70),
  ('courses',       '門訓學程', '📚', '報名及追蹤進度',         '/courses',                      'member',      80),
  ('cell_report',   '小組回報', '👥', '填寫本週小組聚會回報',   '/cell-report/portal',           'cell_leader', 90),
  ('pastor_report', '牧者週報', '📊', '查看各小組回報與統計',   '/cell-report/pastor-dashboard', 'pastor',      100),
  ('staff_report',  '同工週報', '📋', '各區小組回報總覽',       '/cell-report/staff-dashboard',  'staff',       110),
  ('pastor_diary',  '查閱日記', '🔍', '已授權的會友日記',       '/diary/pastor',                 'pastor',      120),
  ('files',         '檔案管理', '📁', '教會資料夾與檔案',       '/files',                        'admin',       130),
  ('admin',         '後台管理', '⚙️', '使用者、活動、系統設定', '/admin',                        'admin',       140)
ON CONFLICT (key) DO NOTHING;


-- 供部署精靈用：繞過 PostgREST schema cache，直接查 information_schema
CREATE OR REPLACE FUNCTION public.check_table_exists(tbl_name TEXT)
RETURNS BOOLEAN
LANGUAGE SQL
SECURITY DEFINER
STABLE
AS $$
  SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = tbl_name
  );
$$;

GRANT EXECUTE ON FUNCTION public.check_table_exists(TEXT) TO anon, authenticated;

-- ============================================================
-- 禱讀本訂購（devotional）
-- ============================================================

CREATE TABLE IF NOT EXISTS devotional_orders (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scripture   TEXT NOT NULL,
    author      TEXT,
    price       INTEGER DEFAULT 0,
    deadline    DATE,
    cover_url   TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS devotional_registrations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID REFERENCES devotional_orders(id) ON DELETE CASCADE,
    group_name      TEXT NOT NULL,
    quantity        INTEGER DEFAULT 0,
    notes           TEXT,
    is_delivered    BOOLEAN DEFAULT FALSE,
    registered_by   UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(order_id, group_name)
);

CREATE TABLE IF NOT EXISTS devotional_registration_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    UUID REFERENCES devotional_orders(id) ON DELETE CASCADE,
    group_name  TEXT,
    quantity    INTEGER,
    notes       TEXT,
    changed_by  UUID REFERENCES users(id),
    changed_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS devotional_regs_order_idx ON devotional_registrations (order_id);
CREATE INDEX IF NOT EXISTS devotional_logs_order_idx ON devotional_registration_logs (order_id);

-- ============================================================
-- 天父日記後台管理員白名單
-- ============================================================

CREATE TABLE IF NOT EXISTS admin_whitelist (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    line_user_id   TEXT NOT NULL UNIQUE,
    note           TEXT,
    is_active      BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS admin_whitelist_uid_idx    ON admin_whitelist (line_user_id);
CREATE INDEX IF NOT EXISTS admin_whitelist_active_idx ON admin_whitelist (is_active);

-- ============================================================
-- 差勤系統
-- ============================================================

CREATE TABLE IF NOT EXISTS staff_profiles (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    hire_date            DATE NOT NULL,
    leave_cycle          TEXT NOT NULL DEFAULT 'anniversary'
                             CHECK (leave_cycle IN ('anniversary', 'calendar')),
    initial_leave_hours  NUMERIC(6,2) NOT NULL DEFAULT 0,
    initial_comp_hours   NUMERIC(6,2) NOT NULL DEFAULT 0,
    is_active            BOOLEAN NOT NULL DEFAULT true,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS leave_requests (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    leave_type   TEXT NOT NULL CHECK (leave_type IN ('annual','comp','personal','sick','other')),
    start_date   DATE NOT NULL,
    end_date     DATE NOT NULL,
    hours        NUMERIC(5,2) NOT NULL,
    reason       TEXT,
    status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','rejected')),
    reviewed_by  UUID REFERENCES users(id),
    reviewed_at  TIMESTAMPTZ,
    review_note  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS overtime_records (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date         DATE NOT NULL,
    hours        NUMERIC(5,2) NOT NULL,
    reason       TEXT,
    status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','rejected')),
    reviewed_by  UUID REFERENCES users(id),
    reviewed_at  TIMESTAMPTZ,
    review_note  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT ALL ON staff_profiles TO anon, authenticated;
GRANT ALL ON leave_requests TO anon, authenticated;
GRANT ALL ON overtime_records TO anon, authenticated;

-- ============================================================
-- ============================================================
-- 稽核日誌（帳號整合、權限異動等關鍵操作記錄）
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id    UUID,          -- 操作者（不設 FK，帳號刪除後記錄仍保留）
    actor_name  TEXT,
    action      TEXT NOT NULL, -- 例：user.block / user.merge_line_admin
    target_type TEXT,
    target_id   TEXT,
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action  ON audit_logs (action);

-- Migrations（補欄位，安全可重複執行）
-- 若資料庫是以舊版 schema.sql 建立，執行以下 ALTER TABLE 補上缺少的欄位。
-- ============================================================

-- 2026-05 church_events / personal_events 新增 remind_days（提前幾天通知）
ALTER TABLE church_events
  ADD COLUMN IF NOT EXISTS remind_days INT NOT NULL DEFAULT 3;

ALTER TABLE personal_events
  ADD COLUMN IF NOT EXISTS remind_days INT NOT NULL DEFAULT 1;

-- 2026-05 cell_members 新增 user_id（連結系統帳號）與 is_confirmed（待審核旗標）
ALTER TABLE cell_members
  ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE cell_members
  ADD COLUMN IF NOT EXISTS is_confirmed BOOLEAN NOT NULL DEFAULT true;

-- 2026-06 registrations 新增 payment_note（金流交易編號，金流對帳報表使用）
ALTER TABLE registrations
  ADD COLUMN IF NOT EXISTS payment_note TEXT;

-- 重新載入 PostgREST schema 快取（讓 API 立即看到新欄位）
NOTIFY pgrst, 'reload schema';

-- 2026-06 devotional_registrations 新增 QR 簽收欄位（migration 009）
ALTER TABLE devotional_registrations
    ADD COLUMN IF NOT EXISTS confirmed_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS confirmed_by  UUID REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS pickup_note   TEXT;

-- ════════════════════════════════════════════════════════
-- 聚會點名模塊（migrations/012_roll_call.sql 的完整內容）
-- ════════════════════════════════════════════════════════
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

NOTIFY pgrst, 'reload schema';

-- ════════════════════════════════════════════════════════
-- 聚會回報提交者欄位（migrations/015_report_submitter_columns.sql）
-- ════════════════════════════════════════════════════════
-- 015 聚會回報「誰填的／何時更新」與留名單「誰上傳」欄位
-- 程式（routes/cell_report.py、routes/visitor_forms.py）一直在寫這幾個欄位，但 schema.sql 沒有；
-- 新專案只跑 schema.sql 的話，成人主日／兒童主日／禱告會／晨禱／自訂聚會的人數回報與留名單上傳會失敗。
-- 影響：只新增可為空的欄位，既有資料與功能不變。可重複執行。
-- 還原：ALTER TABLE <表> DROP COLUMN submitted_by, DROP COLUMN updated_at;（visitor_forms 只有 uploaded_by）
ALTER TABLE sunday_reports          ADD COLUMN IF NOT EXISTS submitted_by UUID REFERENCES users(id),
                                    ADD COLUMN IF NOT EXISTS updated_at   TIMESTAMPTZ;
ALTER TABLE children_sunday_reports ADD COLUMN IF NOT EXISTS submitted_by UUID REFERENCES users(id),
                                    ADD COLUMN IF NOT EXISTS updated_at   TIMESTAMPTZ;
ALTER TABLE prayer_reports          ADD COLUMN IF NOT EXISTS submitted_by UUID REFERENCES users(id),
                                    ADD COLUMN IF NOT EXISTS updated_at   TIMESTAMPTZ;
ALTER TABLE morning_prayer_reports  ADD COLUMN IF NOT EXISTS submitted_by UUID REFERENCES users(id),
                                    ADD COLUMN IF NOT EXISTS updated_at   TIMESTAMPTZ;
ALTER TABLE custom_meeting_reports  ADD COLUMN IF NOT EXISTS submitted_by UUID REFERENCES users(id),
                                    ADD COLUMN IF NOT EXISTS updated_at   TIMESTAMPTZ;
ALTER TABLE visitor_forms           ADD COLUMN IF NOT EXISTS uploaded_by  UUID REFERENCES users(id);

-- ════════════════════════════════════════════════════════
-- 補上程式一直在讀寫的欄位（migrations/016_missing_columns.sql）
-- ════════════════════════════════════════════════════════
-- 016 補上程式一直在讀寫、但 schema.sql 沒有的欄位
-- 新專案只跑 schema.sql 時，下列功能會在存檔或查詢時失敗：
--   禱讀本收費（paid_at／paid_quantity）、教材封面（cover_url）、代禱留言匿名（is_anonymous）、
--   代禱標記蒙應允／封存（answered_at／archived_at）、天父日記登入寫入（provider／provider_user_id）、
--   天父日記讀經進度（程式用 diary_plan.date，schema 原本寫成 plan_date）。
-- 影響：新增的欄位都可為空或有預設值，既有資料與功能不變；只有 diary_plan 的欄位改名（plan_date → date），
--       而且只在「有 plan_date、沒有 date」時才改（天父日記的程式一直用 date，所以多半不需要改）。
-- 可重複執行。還原：ALTER TABLE <表> DROP COLUMN <欄位>;（diary_plan 改名則反向 RENAME）
ALTER TABLE devotional_registrations ADD COLUMN IF NOT EXISTS paid_at       TIMESTAMPTZ,
                                     ADD COLUMN IF NOT EXISTS paid_quantity INTEGER;
ALTER TABLE materials                ADD COLUMN IF NOT EXISTS cover_url     TEXT;
ALTER TABLE prayer_comments          ADD COLUMN IF NOT EXISTS is_anonymous  BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE prayers                  ADD COLUMN IF NOT EXISTS answered_at   TIMESTAMPTZ,
                                     ADD COLUMN IF NOT EXISTS archived_at   TIMESTAMPTZ;
ALTER TABLE users                    ADD COLUMN IF NOT EXISTS provider      TEXT DEFAULT 'line',
                                     ADD COLUMN IF NOT EXISTS provider_user_id TEXT;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = 'diary_plan' AND column_name = 'plan_date')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = 'diary_plan' AND column_name = 'date') THEN
        ALTER TABLE diary_plan RENAME COLUMN plan_date TO date;
    END IF;
END $$;

-- ════════════════════════════════════════════════════════
-- 安全強化（migrations/013_security_hardening.sql）：必須放在所有建表語句之後
-- ════════════════════════════════════════════════════════
-- 010 安全強化：每張表開 RLS（不設任何政策）、函式不開放給公開角色
--
-- 目的：就算有人拿到「公開金鑰（anon / publishable key）」，直接連 Supabase 也什麼都讀不到、寫不進、呼叫不了。
-- 前提：伺服器（Render）使用的是「服務端金鑰（service_role / secret key）」——它繞過 RLS，所以網站照常運作。
--       若 Render 的 SUPABASE_KEY 填的是公開金鑰，執行後網站會讀不到任何資料（請先確認金鑰種類）。
-- 可重複執行。新增資料表後請再執行一次（或在建表時自己加 ENABLE ROW LEVEL SECURITY）。
-- 還原（不建議）：ALTER TABLE <表名> DISABLE ROW LEVEL SECURITY;
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.tablename);
    END LOOP;

    -- Supabase 才有這些角色；一般 Postgres（本機測試）略過
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated;
        GRANT  EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT  EXECUTE ON FUNCTIONS TO service_role;
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';
