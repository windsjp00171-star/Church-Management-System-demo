# CHANGELOG

格式依 Keep a Changelog 簡化版；語言：繁體中文。

## [Unreleased]

### 新增
- 權限撤銷立即生效：登入後每 5 分鐘自動回資料庫重算權限。把某人的管理員／同工關掉、封鎖帳號、調整權限矩陣，不必等對方重新登入就會生效；資料庫暫時連不上時維持原狀（不會把大家登出）。
- 後台權限矩陣（`/admin/permissions`，僅超管）：副標籤（服事身份）× 後台功能模塊，勾選即授權；`admin_required` 會依模塊放行被授權的副標籤成員，沒被授權、沒登記的後台路徑一律拒絕。需先在 Supabase 執行 `migrations/014_permission_matrix.sql`（`schema.sql` 已併入）；變更後受影響的人後台首頁卡片依權限顯示。
- 結構守衛（`tests/test_structure_guards.py`）：直接查 `users`、依伺服器時區取日期、`or 0` 的次數與沒掛 `admin_required` 的 `/admin` 路由，現況記成基準，只准減少；每個 `/admin` 路由必須有權限閘門。
- `docs/COMPARISON_REPORT.md`：與 event-registration-、tianfu-diary、cell_reporter 三個 repo 的整合比對報告（僅文件）。
- 聚會點名模塊（`/roll-call`、`/admin/roll-call`）：點名名冊獨立於會員帳號，支援逐人點名（到／未到／請假／遲到）與只記人數、名冊外訪客人數、場次鎖定、鎖定後修改須附原因、紙本名冊列印與事後補登標記、所有操作寫入只追加的稽核。
- 出席率（`/admin/roll-call/rates`）：規則為資料（不可改、可版本化），請假／遲到／中途加入的算法須由教會明確選擇；由伺服器計算，匯出 CSV 附計算依據（匯出需超級管理員，每次留記錄）。
- 需先在 Supabase 執行 `migrations/012_roll_call.sql`（`schema.sql` 已併入）。
- 聚焦式教學（`static/tour.js`，以 `data-tour` 綁定）與 `tests/`（65 條測試，含對真實 Postgres 的資料庫函式測試）。
- 資料匯出／匯入新增「聚會點名」分類。

### 修正
- **帳號合併不再「成功」但搬漏資料**：改用共用的 `user_merge`。原本清單寫錯表名（`course_attendance`，實際是 `session_attendance`）、漏了稽核日誌，且每一步失敗都只記 log、照樣刪掉被合併的帳號；現在任何一步失敗都會全部還原、不刪帳號，並寫入稽核日誌（管理員整合與會友自助合併兩個入口都一樣）。
- 聚會人數回報（成人主日、兒童主日、禱告會、晨禱、自訂聚會）與留名單上傳寫入的欄位（`submitted_by`／`updated_at`／`uploaded_by`）補進 `schema.sql`（migration 015）；新專案原本會在這幾個功能存檔時失敗。
- 福音探索後台、會友資料編輯的權限檢查改用統一裝飾器（原本是各路由手寫），行為不變，並可由權限矩陣授權。
- 舊網址 `/admin/attendance`（轉址到全職同工差勤）補上管理員檢查。
- 小組回報：**空白人數不再被存成 0**（週報 Step 1、成人主日、兒童主日、禱告會、晨禱、自訂聚會；前端與後端都擋，填 0 必須明確輸入）。
- 小組回報：**開啟週報頁面（GET）不再建立資料列**（Step 1、Step 2、Step 3），避免儀表板誤報「已開始回報」。
- 小組回報：**成人主日、兒童主日、禱告會、晨禱人數回報原本無法儲存**（程式誤用 `datetime.now`，每次送出都回 500），已修正。
- `schema.sql`：門訓出席表名稱改為程式實際使用的 `session_attendance`；教材交易表欄位對齊程式；補上 `contact_leads`；新專案現在只跑 `schema.sql` 即涵蓋程式用到的所有表。

### 新增
- `schema.sql` 結尾加入安全強化（`migrations/013_security_hardening.sql`）：所有資料表開 RLS 且不設政策、函式不開放給公開角色；新增 `docs/SUPABASE_SETUP.md`（新專案的金鑰與 RLS 建議）。
- `tests/`：小組回報回歸守衛、`schema.sql` 守衛（涵蓋所有用到的表、RLS 全開，可在真實 Postgres 上執行）。

### 變更
- 員工請假／加班模組更名為「全職同工差勤」：網址改為 `/staff-leave`、`/admin/staff-leave`，舊網址 `/attendance`、`/admin/attendance` 會自動轉址（通知連結與書籤仍可用）；備份分類鍵改為 `staff_leave_mgmt`。

### 新增
- `docs/GAP_REPORT.md`：現有系統與新規格（Master／PRODUCT／SPEC／總報告第 17 版）的差距報告與建議重構順序（僅文件，未改程式）。
