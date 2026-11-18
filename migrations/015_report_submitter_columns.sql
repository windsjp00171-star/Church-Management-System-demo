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
