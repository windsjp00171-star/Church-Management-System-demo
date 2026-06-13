-- 禱讀本 QR 簽收欄位
ALTER TABLE devotional_registrations
    ADD COLUMN IF NOT EXISTS confirmed_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS confirmed_by  UUID REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS pickup_note   TEXT;
