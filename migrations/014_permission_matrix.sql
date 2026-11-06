-- 014 後台權限矩陣：副標籤（服事身份）可進入的後台功能模塊
-- 影響：只替 groups 表加一個欄位（預設空陣列＝沒有授權），既有資料不變、不影響任何現有功能。
-- 可重複執行。還原：ALTER TABLE groups DROP COLUMN admin_modules;（不影響其他資料）
-- 不執行的話：權限矩陣頁會讀不到欄位，副標籤成員一律進不了後台（超管與管理員不受影響）。
ALTER TABLE groups ADD COLUMN IF NOT EXISTS admin_modules JSONB NOT NULL DEFAULT '[]'::jsonb;
