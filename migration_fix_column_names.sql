-- ============================================================
-- 修正欄位名稱不符問題
-- 執行時機：在 Supabase SQL Editor 中執行一次
-- 背景：schema.sql 原始設計與 Python 程式碼使用的欄位名不符，
--       導致所有聚會人數回報與小組回報 POST 出現 500 錯誤。
-- ============================================================

-- ============================================================
-- 1. 修正 sunday_reports: report_date → date
-- ============================================================
ALTER TABLE sunday_reports RENAME COLUMN report_date TO date;

-- ============================================================
-- 2. 修正 children_sunday_reports: report_date → date
-- ============================================================
ALTER TABLE children_sunday_reports RENAME COLUMN report_date TO date;

-- ============================================================
-- 3. 修正 prayer_reports: report_date → date
-- ============================================================
ALTER TABLE prayer_reports RENAME COLUMN report_date TO date;

-- ============================================================
-- 4. 修正 morning_prayer_reports: report_date → date
-- ============================================================
ALTER TABLE morning_prayer_reports RENAME COLUMN report_date TO date;

-- ============================================================
-- 5. 修正 cell_attendance: 移除舊 status 欄位，新增三個分項欄位
-- ============================================================
ALTER TABLE cell_attendance DROP COLUMN IF EXISTS status;
ALTER TABLE cell_attendance ADD COLUMN IF NOT EXISTS cell_status TEXT;
ALTER TABLE cell_attendance ADD COLUMN IF NOT EXISTS sunday_status TEXT;
ALTER TABLE cell_attendance ADD COLUMN IF NOT EXISTS rpg_status TEXT;

-- ============================================================
-- 6. 修正 cell_reports: 移除舊欄位，新增符合程式碼的欄位
-- ============================================================

-- 移除不再使用的舊欄位
ALTER TABLE cell_reports DROP COLUMN IF EXISTS member_count;
ALTER TABLE cell_reports DROP COLUMN IF EXISTS status_worship;
ALTER TABLE cell_reports DROP COLUMN IF EXISTS status_prayer;
ALTER TABLE cell_reports DROP COLUMN IF EXISTS status_word;
ALTER TABLE cell_reports DROP COLUMN IF EXISTS status_service;
ALTER TABLE cell_reports DROP COLUMN IF EXISTS coworker_note;

-- attendance_count 改為可為 NULL（未召開時為 NULL）
ALTER TABLE cell_reports ALTER COLUMN attendance_count DROP NOT NULL;
ALTER TABLE cell_reports ALTER COLUMN attendance_count DROP DEFAULT;

-- 新增小組長自評四大面向欄位
ALTER TABLE cell_reports ADD COLUMN IF NOT EXISTS spiritual_status TEXT;
ALTER TABLE cell_reports ADD COLUMN IF NOT EXISTS spiritual_note TEXT;
ALTER TABLE cell_reports ADD COLUMN IF NOT EXISTS family_status TEXT;
ALTER TABLE cell_reports ADD COLUMN IF NOT EXISTS family_note TEXT;
ALTER TABLE cell_reports ADD COLUMN IF NOT EXISTS work_status TEXT;
ALTER TABLE cell_reports ADD COLUMN IF NOT EXISTS work_note TEXT;
ALTER TABLE cell_reports ADD COLUMN IF NOT EXISTS health_status TEXT;
ALTER TABLE cell_reports ADD COLUMN IF NOT EXISTS health_note TEXT;

-- 新增整體狀況與建議欄位
ALTER TABLE cell_reports ADD COLUMN IF NOT EXISTS group_status TEXT;
ALTER TABLE cell_reports ADD COLUMN IF NOT EXISTS coworker_suggestion TEXT;
