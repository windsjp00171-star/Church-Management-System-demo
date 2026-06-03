-- 天父日記後台管理員白名單
-- 執行方式：Supabase > SQL Editor > 貼上執行

CREATE TABLE IF NOT EXISTS admin_whitelist (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    line_user_id   TEXT NOT NULL UNIQUE,
    note           TEXT,
    is_active      BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS admin_whitelist_uid_idx ON admin_whitelist (line_user_id);
CREATE INDEX IF NOT EXISTS admin_whitelist_active_idx ON admin_whitelist (is_active);
