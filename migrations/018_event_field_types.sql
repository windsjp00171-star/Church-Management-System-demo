-- 018：報名表單強化 —— 新增欄位型別（生日、身分證、分級收費、監護人）與「依生日自動判定身分別」設定
--
-- 為什麼：成熟版（event-registration-）的報名表單支援 11 種欄位型別，這個專案原本只有 7 種，
-- event_fields.field_type 有一條 CHECK 白名單。沒放寬的話，新增生日／身分證／分級收費／監護人欄位時
-- 會被資料庫擋下：violates check constraint "event_fields_field_type_check"。
--
-- 影響：既有活動與欄位完全不變，只是多允許四種新型別、多一個空欄位。可重複執行。
-- 還原：先確認沒有欄位使用新型別，再把 CHECK 改回原本 7 種、DROP COLUMN auto_tier（會丟掉自動判定設定）。
ALTER TABLE event_fields DROP CONSTRAINT IF EXISTS event_fields_field_type_check;
ALTER TABLE event_fields ADD CONSTRAINT event_fields_field_type_check
  CHECK (field_type = ANY (ARRAY[
    'text', 'number', 'textarea', 'select', 'radio', 'checkbox', 'date',
    'birthday',    -- 出生日期（填民國年、存西元）
    'id_number',   -- 身分證字號（檢查碼驗證）
    'fee',         -- 分級收費（選項各自訂價）
    'guardian'     -- 監護人（姓名＋電話，未滿 18 歲自動出現）
  ]));

ALTER TABLE event_fields ADD COLUMN IF NOT EXISTS auto_tier JSONB;
