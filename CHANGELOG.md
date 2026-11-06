# CHANGELOG

格式依 Keep a Changelog 簡化版；語言：繁體中文。

## [Unreleased]

### 新增
- 聚會點名模塊（`/roll-call`、`/admin/roll-call`）：點名名冊獨立於會員帳號，支援逐人點名（到／未到／請假／遲到）與只記人數、名冊外訪客人數、場次鎖定、鎖定後修改須附原因、紙本名冊列印與事後補登標記、所有操作寫入只追加的稽核。
- 出席率（`/admin/roll-call/rates`）：規則為資料（不可改、可版本化），請假／遲到／中途加入的算法須由教會明確選擇；由伺服器計算，匯出 CSV 附計算依據（匯出需超級管理員，每次留記錄）。
- 需先在 Supabase 執行 `migrations/009_roll_call.sql`（`schema.sql` 已併入）。
- 聚焦式教學（`static/tour.js`，以 `data-tour` 綁定）與 `tests/`（65 條測試，含對真實 Postgres 的資料庫函式測試）。
- 資料匯出／匯入新增「聚會點名」分類。

### 變更
- 員工請假／加班模組更名為「全職同工差勤」：網址改為 `/staff-leave`、`/admin/staff-leave`，舊網址 `/attendance`、`/admin/attendance` 會自動轉址（通知連結與書籤仍可用）；備份分類鍵改為 `staff_leave_mgmt`。

### 新增
- `docs/GAP_REPORT.md`：現有系統與新規格（Master／PRODUCT／SPEC／總報告第 17 版）的差距報告與建議重構順序（僅文件，未改程式）。
