# HANDOVER 系統交接手冊

> 本文件供系統接手同工 / 維護方使用。目標：即使原開發者或系統完全停擺，
> 負責同工也能在**一週內取出所有核心資料並理解系統架構**。
>
> 緊急時最快路徑：登入後台 → 「資料備份中心」(`/admin/backup`) → 下載
> `church-admin-backup-YYYYMMDD.zip` 與 HTML 離線閱讀器。詳見下方
> [二、匯出資料的操作步驟](#二匯出資料的操作步驟)。

---

## 一、系統整體說明

本系統為**整合型教會行政系統**，以 Python Flask 撰寫，採 Blueprint 模組化架構。
資料庫使用 Supabase（PostgreSQL），登入採 LINE Login OAuth2，部署於 Render。

### 技術堆疊

| 項目 | 內容 |
|------|------|
| 後端框架 | Python Flask（app factory + Blueprint） |
| 資料庫 | Supabase PostgreSQL（`db.py` 全域 `supabase` client） |
| 登入 | LINE Login OAuth2 |
| 檔案儲存 | Cloudflare R2（`storage.py`，檔案分享模組用） |
| AI | Groq（主）/ Gemini（備援）（天父日記用） |
| 部署 | Render（`Procfile` + gunicorn） |

### Blueprint 模組用途一覽

| Blueprint | 檔案 | 路由前綴 | 用途 |
|-----------|------|----------|------|
| `auth_bp` | `routes/auth.py` | `/auth` | LINE OAuth2 登入 / 登出 |
| `event_bp` | `routes/event.py` | — | 活動報名 |
| `admin_bp` | `routes/admin.py` | `/admin` | 後台管理（活動、使用者、小組等） |
| `checkin_bp` | `routes/checkin.py` | — | 電子簽到 |
| `profile_bp` | `routes/profile.py` | — | 會員個人資料 |
| `notifications_bp` | `routes/notifications.py` | — | 站內通知 |
| `courses_bp` | `routes/courses.py` | — | 門訓學程（可選模組） |
| `calendar_bp` | `routes/calendar.py` | — | 教會行事曆（可選模組） |
| `bulletin_bp` | `routes/bulletin.py` | — | 每週週報（可選模組） |
| `prayer_bp` | `routes/prayer.py` | — | 代禱麥田（可選模組） |
| `gospel_bp` | `routes/gospel.py` | — | 福音探索（可選模組） |
| `visitor_forms_bp` | `routes/visitor_forms.py` | — | 留名單（可選模組） |
| `files_bp` | `routes/files.py` | `/files`, `/folders` | 檔案分享（R2 儲存） |
| `diary_bp` | `routes/diary.py` | `/diary` | 天父日記 + AI 反思引導 |
| `cell_report_bp` | `routes/cell_report.py` | `/cell-report` | 小組回報單 |
| `staff_bp` | `routes/staff.py` | — | 同工首頁 |
| `setup_wizard_bp` | `routes/setup_wizard.py` | `/setup-wizard` | 部署精靈（環境 / 資料表狀態） |
| `changelog_bp` | `routes/changelog.py` | — | 更新日誌 |
| `attendance_bp` | `routes/attendance.py` | — | 差勤系統（同工請假 / 加班） |
| `data_transfer_bp` | `routes/data_transfer.py` | `/admin/data-export`, `/admin/data-import` | 全庫 JSON ZIP 匯出 / 還原（遷移用） |
| `backup_bp` | `routes/backup.py` | `/admin/backup` | **數位遺囑備份模塊**（CSV / HTML 交接快照） |
| `devotional_bp` | `routes/devotional.py` | `/devotional` | 禱讀本訂購 |
| `payment_bp` | `routes/payment.py` | — | 線上金流 |

> `data_transfer_bp` 與 `backup_bp` 的差異：
> - **`data_transfer`**：給「遷移到新 Supabase 專案」用，輸出**完整 JSON**、可再匯入還原。
> - **`backup`（本模塊）**：給「緊急交接 / 離線閱讀」用，輸出**人類可讀的 CSV 與單一 HTML**，
>   不需任何系統即可開啟閱讀。

---

## 二、匯出資料的操作步驟

所有匯出功能皆**限管理員**存取。

### A. 一鍵備份（建議）

1. 以管理員帳號登入系統。
2. 後台首頁 →「系統備份 / 交接」→ **資料備份中心**，或直接前往 `/admin/backup`。
3. 點 **「下載 church-admin-backup ZIP」**：
   取得 `church-admin-backup-YYYYMMDD.zip`，內含各模組獨立 CSV 與 `README.txt` 清單。
4. 點 **「下載 HTML 離線閱讀器」**（`/admin/backup/html`）：
   取得單一 `.html` 檔，雙擊即可離線開啟、用分頁 Tab 瀏覽所有模組資料快照（無需網路、無需系統）。

### B. 分類單獨匯出

在資料備份中心頁面，每個分類各有「匯出 CSV」按鈕，可單獨下載：

| 分類 | 檔名 | 主要來源資料表 |
|------|------|----------------|
| 小組回報記錄 | `cell-reports.csv` | `cell_reports`, `cell_groups` |
| 活動報名與簽到記錄 | `event-registrations.csv` | `registrations`, `events`, `users` |
| 代禱事項清單 | `prayers.csv` | `prayers`, `users` |
| 福音探索記錄 | `gospel-inquiries.csv` | `gospel_inquiries` |
| 差勤記錄 | `attendance.csv` | `leave_requests`, `overtime_records`, `users` |
| 成員 / 使用者清單 | `members.csv` | `users` |

> CSV 皆以 UTF-8 BOM 編碼，可直接用 Excel 開啟而不亂碼。
> 若某模組資料表尚未建立，頁面會標註「尚未啟用」並自動略過（ZIP 內亦不含該檔）。

### C. 完整遷移（搬到新 Supabase 專案）

若是要把整個系統搬到新環境，請改用 `/admin/data-export`（超級管理員限定，輸出完整 JSON ZIP），
並於新環境用 `/admin/data-import` 還原。

---

## 三、Supabase 主要資料表清單

> 完整建表 SQL 見專案根目錄 `schema.sql`；後續增量見 `migrations/`。

### 核心 / 使用者

| 資料表 | 說明 |
|--------|------|
| `users` | 會友 / 使用者主表（含 LINE ID、身分旗標 is_admin/is_super_admin/is_pastor/is_staff） |
| `groups` / `group_members` | 服事團隊標籤與歸屬 |

### 活動報名

| 資料表 | 說明 |
|--------|------|
| `events` | 活動主表 |
| `event_fields` | 活動自訂報名欄位 |
| `registrations` | 報名紀錄（含簽到 checked_in / checked_in_at） |
| `registration_answers` | 報名自訂欄位答案 |
| `registration_whitelist` | 報名白名單 |

### 門訓學程

| 資料表 | 說明 |
|--------|------|
| `course_categories` / `courses` / `course_sessions` | 課程分類、課程、場次 |
| `course_enrollments` / `course_attendance` / `session_attendance` | 報名與出席 |
| `course_certifications` / `course_certificates` | 認證記錄 |

### 小組牧養與聚會

| 資料表 | 說明 |
|--------|------|
| `cell_groups` | 小組 |
| `cell_members` | 組員 |
| `cell_group_leaders` | 組長對應 |
| `cell_reports` | 小組週報主表 |
| `cell_attendance` | 週報出席紀錄 |
| `sunday_reports` / `children_sunday_reports` / `prayer_reports` / `morning_prayer_reports` / `custom_meeting_reports` | 各場聚會人數統計 |

### 代禱 / 福音 / 行事曆

| 資料表 | 說明 |
|--------|------|
| `prayers` / `prayer_comments` / `prayer_reactions` | 代禱事項、回應、回饋 |
| `gospel_cards` / `gospel_form_questions` / `gospel_inquiries` | 福音卡、問卷題目、詢問記錄 |
| `church_events` / `personal_events` | 教會行事、個人事項 |

### 差勤 / 物資

| 資料表 | 說明 |
|--------|------|
| `staff_profiles` | 全職同工差勤檔案（到職日、假別週期、初始時數） |
| `leave_requests` | 請假申請（含審核狀態） |
| `overtime_records` | 加班 / 補休記錄 |
| `materials` / `material_stock` / `material_transactions` | 教材物資進銷存 |

### 其他模組

| 資料表 | 說明 |
|--------|------|
| `diary_entries` / `diary_plan` / `admin_whitelist` | 天父日記、讀經進度、後台白名單 |
| `devotional_orders` / `devotional_registrations` / `devotional_registration_logs` | 禱讀本訂購 |
| `files` / `folders` | 檔案分享 |
| `weekly_bulletins` | 每週週報 |
| `notifications` | 站內通知 |
| `settings` / `portal_card_settings` / `portal_links` | 系統 / 首頁設定 |

---

## 四、Render 環境變數清單

> 僅列出 key，value 請依各教會實際設定填入（敏感值勿提交到 git）。

```
# Flask
FLASK_SECRET_KEY=

# LINE Login
LINE_CHANNEL_ID=
LINE_CHANNEL_SECRET=
LINE_REDIRECT_URI=
LINE_LIFF_ID=

# Supabase
SUPABASE_URL=
SUPABASE_KEY=

# 教會資訊
CHURCH_NAME=
CHURCH_SHORT_NAME=
PRIVACY_POLICY_URL=

# Cloudflare R2（檔案分享模組）
R2_ENDPOINT=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=

# AI（天父日記模組）
GROQ_API_KEY=
GEMINI_API_KEY=
ANTHROPIC_API_KEY=

# 管理員 LINE User IDs（逗號分隔，同時是天父日記超管）
ADMIN_LINE_USER_IDS=

# 可選功能開關（設為 false 停用對應模組）
ENABLE_PRAYER=
ENABLE_GOSPEL=
ENABLE_BULLETIN=
ENABLE_CALENDAR=
ENABLE_COURSES=
ENABLE_VISITOR_FORMS=

# Demo 洽詢系統（正式部署設為 false 或移除）
DEMO_MODE=
CONTACT_EMAIL=
CONTACT_LINE=

# 錯誤監控（可選）
SENTRY_DSN=

# Render 部署旗標（部署時設為 true，啟用 Secure Cookie）
RENDER=
```

---

## 五、本機啟動步驟（最簡版）

> 假設你已安裝 Python 3（版本見 `.python-version` / `runtime.txt`）。

```bash
# 1. 取得程式碼
git clone <repo-url>
cd Church-Management-System-demo

# 2. （建議）建立虛擬環境
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. 安裝套件
pip install -r requirements.txt

# 4. 設定環境變數
cp .env.example .env            # 接著編輯 .env 填入上方第四節的變數

# 5. 啟動（debug 模式，預設 http://127.0.0.1:5000）
python app.py
```

部署到 Render：推送程式碼到 GitHub，Render 會依 `Procfile`（gunicorn）自動重新部署。
資料表變更需先在 Supabase > SQL Editor 執行對應 `migrations/*.sql`，再部署新版程式碼。

---

## 六、平台帳號轄管權

本系統設計為「教會獨立、維護方可替換」。**基礎設施帳號的擁有權歸教會，
維護方（開發者）只保留範圍受限、可隨時收回的協作權**。把「擁有權」與「存取權」分開看：

| 平台 | 擁有權（帳單 + 最終控制） | 維護方角色 | 說明 |
|------|--------------------------|------------|------|
| GitHub repo | 維護方 | Owner | 程式碼跨教會共用，教會無需存取 |
| Render | **教會** | 受邀 collaborator（看 log / 管 deploy） | 教會付費、握最終控制；維護方推 code 觸發自動部署即可 |
| Supabase | **教會** | 原則上不持有（僅初次建表臨時用） | 內含會友個資，資料主權必須在教會 |
| LINE Login Channel | **教會** | 協助設定 | 教會官方登入身分 / 品牌 |
| Cloudflare R2（若啟用） | **教會** | 協助設定 | 教會的儲存與帳單 |
| AI 金鑰（Groq / Gemini） | **教會** | — | 用量 / 額度屬教會 |
| App 層超級管理員 | **教會主責行政** | 不保留 | 正式站超管交給教會，維護方不留帳號 |

> 重點：維護方推 code 到 GitHub → Render 自動重新部署，**無需登入系統或接觸教會資料**即可更新功能。
> Schema 變更走「維護方提供 `migrations/*.sql` → 教會於 Supabase SQL Editor 執行」流程。

---

> **備註 — 客製邏輯教會的程式碼分流**
> 共用 repo 適合「設定可調、邏輯一致」的教會。若某間教會需要**與原本不同的程式邏輯**
> （例：小組回報出席算法、差勤計算規則等），建議**獨立 fork 成該教會專屬 repo**，
> 避免改動污染 demo / 其他教會。獨立 repo 仍可保留 `upstream` 來源以便日後同步通用修正。

---

## 七、營運維護（保活與升級）

### Render 免費方案保活（UptimeRobot）

Render 免費 web service 閒置 15 分鐘會休眠，下次喚醒冷啟動約 30–60 秒。
用 [UptimeRobot](https://uptimerobot.com/)（免費）定時戳一次即可保持喚醒：

- Monitor type：**HTTP(s)**
- Interval：**5 分鐘**（免費方案最短）
- 監控網址：**`https://<render網址>/healthz`**
  （此端點回 200、不查資料庫，是最輕量的保活 / 健康檢查目標）

注意事項：
- Render 免費方案每月約 **750 instance 小時**，剛好夠**一個**服務 24/7 常駐；
  同一 workspace 勿再放第二個免費常駐服務，否則會超額休眠。
- UptimeRobot 帳號建議由**教會自己持有**（或可交接），與其他平台一致，
  避免「維護方不在 = 監控消失」。

### 想要零冷啟動 / 更穩 → 升級 Render

若教會在意極少數冷啟動或需要正式 SLA，可在 Render 後台把方案升級為
**Starter（約 US$7/月）**：服務常駐不休眠、資源更足。
升級只是改方案，**不需重新部署、不影響任何設定與資料**，隨時可升。

---

## 八、緊急聯絡建議

依以下順序自助處理：

1. **要資料** → 後台 `/admin/backup` 下載 ZIP 與 HTML 離線閱讀器（不需任何技術背景）。
2. **系統壞了** → 查看 Render 服務的 Deploy / Logs；多數問題重新部署即可恢復。
3. **資料庫問題** → 登入該教會自有的 Supabase 專案後台查看資料表與 SQL Editor。
4. **要搬家** → 用 `/admin/data-export` 匯出完整 JSON，於新環境 `/admin/data-import` 還原。

> **若以上均無法處理，請聯絡 ____________________________**
> （請填入：系統維護方姓名 / 信箱 / 電話 / LINE）
