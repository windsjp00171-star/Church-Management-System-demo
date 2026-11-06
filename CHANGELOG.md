# CHANGELOG

格式依 Keep a Changelog 簡化版；語言：繁體中文。

## [Unreleased]

### 新增
- `docs/COMPARISON_REPORT.md`：與 event-registration-、tianfu-diary、cell_reporter 三個 repo 的整合比對報告（僅文件）。
- 聚會點名模塊（`/roll-call`、`/admin/roll-call`）：點名名冊獨立於會員帳號，支援逐人點名（到／未到／請假／遲到）與只記人數、名冊外訪客人數、場次鎖定、鎖定後修改須附原因、紙本名冊列印與事後補登標記、所有操作寫入只追加的稽核。
- 出席率（`/admin/roll-call/rates`）：規則為資料（不可改、可版本化），請假／遲到／中途加入的算法須由教會明確選擇；由伺服器計算，匯出 CSV 附計算依據（匯出需超級管理員，每次留記錄）。
- 需先在 Supabase 執行 `migrations/009_roll_call.sql`（`schema.sql` 已併入）。
- 聚焦式教學（`static/tour.js`，以 `data-tour` 綁定）與 `tests/`（65 條測試，含對真實 Postgres 的資料庫函式測試）。
- 資料匯出／匯入新增「聚會點名」分類。

### 修正
- 小組回報：**空白人數不再被存成 0**（週報 Step 1、成人主日、兒童主日、禱告會、晨禱、自訂聚會；前端與後端都擋，填 0 必須明確輸入）。
- 小組回報：**開啟週報頁面（GET）不再建立資料列**（Step 1、Step 2、Step 3），避免儀表板誤報「已開始回報」。
- 小組回報：**成人主日、兒童主日、禱告會、晨禱人數回報原本無法儲存**（程式誤用 `datetime.now`，每次送出都回 500），已修正。
- `schema.sql`：門訓出席表名稱改為程式實際使用的 `session_attendance`；教材交易表欄位對齊程式；補上 `contact_leads`；新專案現在只跑 `schema.sql` 即涵蓋程式用到的所有表。

### 新增
- `schema.sql` 結尾加入安全強化（`migrations/010_security_hardening.sql`）：所有資料表開 RLS 且不設政策、函式不開放給公開角色；新增 `docs/SUPABASE_SETUP.md`（新專案的金鑰與 RLS 建議）。
- `tests/`：小組回報回歸守衛、`schema.sql` 守衛（涵蓋所有用到的表、RLS 全開，可在真實 Postgres 上執行）。

### 變更
- 員工請假／加班模組更名為「全職同工差勤」：網址改為 `/staff-leave`、`/admin/staff-leave`，舊網址 `/attendance`、`/admin/attendance` 會自動轉址（通知連結與書籤仍可用）；備份分類鍵改為 `staff_leave_mgmt`。

### 新增
- `docs/GAP_REPORT.md`：現有系統與新規格（Master／PRODUCT／SPEC／總報告第 17 版）的差距報告與建議重構順序（僅文件，未改程式）。
