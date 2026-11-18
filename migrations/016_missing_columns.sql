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
