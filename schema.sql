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

CREATE TABLE IF NOT EXISTS groups (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    is_primary  BOOLEAN NOT NULL DEFAULT false,
    is_staff    BOOLEAN NOT NULL DEFAULT false,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
    is_blocked     BOOLEAN NOT NULL DEFAULT false,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
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

CREATE TABLE IF NOT EXISTS course_attendance (
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
    title      TEXT NOT NULL,
    content    TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active  BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gospel_inquiries (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID REFERENCES users(id),
    name       TEXT,
    content    TEXT NOT NULL,
    is_read    BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id          UUID NOT NULL REFERENCES cell_groups(id),
    week_date         DATE NOT NULL,
    attendance_count  INTEGER NOT NULL DEFAULT 0,
    member_count      INTEGER NOT NULL DEFAULT 0,
    status_worship    TEXT,
    status_prayer     TEXT,
    status_word       TEXT,
    status_service    TEXT,
    newcomer_raw      TEXT,
    coworker_note     TEXT,
    no_meeting        BOOLEAN NOT NULL DEFAULT false,
    no_meeting_reason TEXT,
    is_complete       BOOLEAN NOT NULL DEFAULT false,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (group_id, week_date)
);

-- 出席紀錄
CREATE TABLE IF NOT EXISTS cell_attendance (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id  UUID NOT NULL REFERENCES cell_reports(id) ON DELETE CASCADE,
    member_id  UUID NOT NULL REFERENCES cell_members(id) ON DELETE CASCADE,
    status     TEXT NOT NULL DEFAULT 'present'
                   CHECK (status IN ('present','absent','leave','visitor')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (report_id, member_id)
);

-- 成人主日聚會人數
CREATE TABLE IF NOT EXISTS sunday_reports (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_date          DATE NOT NULL UNIQUE,
    first_service_count  INTEGER NOT NULL DEFAULT 0,
    second_service_count INTEGER NOT NULL DEFAULT 0,
    topic                TEXT,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 兒童主日聚會人數
CREATE TABLE IF NOT EXISTS children_sunday_reports (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_date      DATE NOT NULL UNIQUE,
    attendance_count INTEGER NOT NULL DEFAULT 0,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 禱告會人數
CREATE TABLE IF NOT EXISTS prayer_reports (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_date      DATE NOT NULL UNIQUE,
    attendance_count INTEGER NOT NULL DEFAULT 0,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 晨禱人數
CREATE TABLE IF NOT EXISTS morning_prayer_reports (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_date      DATE NOT NULL UNIQUE,
    attendance_count INTEGER NOT NULL DEFAULT 0,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
