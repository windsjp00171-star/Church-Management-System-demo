-- 補上 files.allowed_groups 與 folders.allowed_users / allowed_groups
-- 這三個欄位在初版 schema 中遺漏，導致建立資料夾與上傳檔案時 500。

ALTER TABLE files
  ADD COLUMN IF NOT EXISTS allowed_groups UUID[];

ALTER TABLE folders
  ADD COLUMN IF NOT EXISTS allowed_users UUID[],
  ADD COLUMN IF NOT EXISTS allowed_groups UUID[];
