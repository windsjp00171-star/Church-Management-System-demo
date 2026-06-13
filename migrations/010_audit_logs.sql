-- 009: 稽核日誌表（帳號整合、權限異動等關鍵操作記錄）
-- 在 Supabase > SQL Editor 執行，可重複執行。

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

NOTIFY pgrst, 'reload schema';
