# 整合型教會行政系統

整合自四個子系統的統一 Flask 應用，以 Blueprint 模組化組織各功能。

## 整合來源

| 子系統 | 功能 | Blueprint |
|--------|------|-----------|
| event-registration- | 活動報名、簽到、會友管理（基礎） | 多個 Blueprint |
| church-data-hub | 檔案分享（R2 儲存） | `files_bp` |
| tianfu-diary | 靈修日記 + AI 反思引導 | `diary_bp` |
| cell_reporter | 小組回報單（Django→Flask 移植） | `cell_report_bp` |

## 技術架構

- **後端**：Python Flask（Blueprint 架構）
- **資料庫**：Supabase PostgreSQL（`db.py` 的全域 `supabase` client）
- **登入**：LINE Login OAuth2
- **檔案儲存**：Cloudflare R2（`storage.py`）
- **AI**：Groq（主）/ Gemini（備援）/ Anthropic（保留）
- **部署**：Render（`Procfile` + gunicorn）

## 專案結構

```
app.py                  # Flask app factory，所有 Blueprint 在此註冊
config.py               # 環境變數讀取（Config class）
db.py                   # Supabase client（全域唯一）
extensions.py           # flask-limiter（供 files blueprint 使用）
storage.py              # Cloudflare R2 操作（upload/download/delete）
settings_store.py       # Supabase 應用設定存取（儲存空間上限等）
plan.xlsx               # 讀經進度表（天父日記用）
routes/                 # Blueprint 模組
  auth.py               # LINE OAuth2 登入/登出
  event.py              # 活動報名
  admin.py              # 後台管理
  checkin.py            # 電子簽到
  profile.py            # 會員個人資料
  notifications.py      # 站內通知
  courses.py            # 門訓學程
  calendar.py           # 教會行事曆
  bulletin.py           # 每週週報
  prayer.py             # 代禱麥田
  gospel.py             # 福音探索
  visitor_forms.py      # 留名單
  files.py              # 檔案分享（church-data-hub）
  diary.py              # 天父日記（tianfu-diary）
  cell_report.py        # 小組回報（cell_reporter）
  devotional.py         # 禱讀本訂購（devotional_bp）
  staff_leave.py        # 全職同工差勤（請假／加班，原 attendance）
  roll_call.py          # 聚會點名（與使用者帳號脫鉤）
templates/              # Jinja2 模板
  base.html             # 共用基底模板
  diary/                # 天父日記模板（extends base.html）
  files/                # 檔案分享模板
  cell_report/          # 小組回報模板
  devotional/           # 禱讀本訂購模板
  ...                   # 其他模板
data/
  book_background.py    # 聖經書卷背景說明
scripture/
  cuv.json              # 和合本聖經全文（JSON）
migrations/             # Supabase SQL migration 腳本
  007_devotional.sql    # 禱讀本訂購三張表
  008_diary_admin_whitelist.sql  # 天父日記後台白名單表
  009_devotional_pickup.sql  # 禱讀本 QR 簽收欄位
  010_audit_logs.sql    # 稽核日誌表
```

## Blueprint 路由前綴

| Blueprint | url_prefix | 說明 |
|-----------|-----------|------|
| auth_bp | `/auth` | LINE OAuth |
| event_bp | — | 活動相關 |
| admin_bp | `/admin` | 後台管理 |
| files_bp | — | `/files`, `/folders` |
| diary_bp | — | `/diary`, `/api/diary/...` |
| cell_report_bp | — | `/cell-report/...` |
| devotional_bp | — | `/devotional/...` |

## 重要開發規則

### 資料庫存取
永遠從 `db.py` import `supabase`：
```python
from db import supabase
```

### Session 結構（整合系統）
| key | 說明 |
|-----|------|
| `user_id` | Supabase UUID |
| `real_name` | 真實姓名 |
| `line_id` | LINE user ID |
| `is_admin` | 管理員旗標 |
| `is_super_admin` | 超管旗標（env var ADMIN_LINE_USER_IDS） |
| `is_pastor` | 牧者旗標（小組回報用） |
| `is_staff` | 同工旗標（小組回報用） |
| `picture_url` | 大頭貼 URL |
| `member_type` | `'member'` / `'visitor'` |

### 聚會點名（roll_call_bp）
- **與使用者帳號脫鉤**：被點名的是 `rc_members`（點名名冊），不引用 `users.id`；點名模組不得查 `users`（有測試守衛）。操作者只存 id＋姓名快照，不設外鍵。
- 點名寫入一律走資料庫函式 `rc_save_record` / `rc_lock_session` / `rc_set_count`（同交易寫紀錄＋稽核）；不得直接寫 `rc_records`。
- `rc_audit` 只許追加（觸發器擋 UPDATE／DELETE／TRUNCATE）；修改必須附原因；人數空白一律退回、不得當 0。
- 出席率規則是資料（`rc_rate_rules`，不可改、同名新增即新版本），請假／遲到／中途加入的算法沒有預設值，由教會決定；計算在伺服器端（`roll_call_logic.py`）。
- **點名單**（`/roll-call`）：紙本樣式的表格（人名×日期）；`GET` 不寫資料庫，建立「主日」類型與加欄由 `POST /api/roll-call/sheet/add-column`（同一天不重複、預設台北 10:00）；打勾走既有的 `api_mark`（present／absent）。逐場次頁移到 `/roll-call/sessions`。
- **首頁「本週點名」**：`routes.roll_call.portal_rollcall()` 供首頁（只讀、出錯回 None 不拖垮首頁；同工以上才呼叫、模組關掉不呼叫），前端 `static/portal-rollcall.js`；打勾同樣走 `api_mark`。
- 名冊匯入：`/api/admin/roll-call/members/preview`（只分類、不寫入）→ `/api/admin/roll-call/members`（伺服器重算分類；疑似重複須 `confirm_similar` 明確確認；同名一律略過）。分類邏輯只有 `roll_call_logic.plan_import` 一份。
- 測試：`tests/`（`pytest`；`test_roll_call_db.py` 需要 root＋Postgres 16，否則略過）。
- 網址：同工 `/roll-call`；後台 `/admin/roll-call`、`/admin/roll-call/rates`。API 回傳 `{"status", "data", "error"}`。

### 功能模組登記表（`routes/modules.py`）— 各教會自己選要用哪些功能
- **核心永遠開著**（人、登入、權限、稽核、通知、備份、首頁與後台外殼、說明）；**選配模組**可由超管在 `/admin/modules` 開關，狀態存在 `settings` 表（`modules_state`，沒寫的預設為開，所以既有部署行為不變）。
- **關掉＝整塊消失**：網址一律 404（`enforce_modules`，全站 `before_request`）、首頁卡片與連結（模板的 `module_on()`）、後台卡片（`can_see()`）、權限矩陣欄位。**關掉不刪資料**，備份與匯出照常包含（資料安全優先）。
- **依賴**：關掉被依賴的模組，依賴它的跟著不存在（例如金流依賴活動報名）；儲存時會檢查，依賴沒滿足不能開啟。
- **展示站專用**（`demo`：展示帳號登入、洽詢、洽詢紀錄）只在 `DEMO_MODE` 為真時存在，不靠資料庫開關；正式教會部署不會有。
- **新增功能時**：把網址前綴登記進 `MODULES`（`*` 可代表任一段），或明確列為核心。`tests/test_modules.py` 掃所有路由，沒歸屬的會紅；`portal.html`／`staff/index.html`／`admin/index.html` 裡指向選配模組的連結一律要有 `module_on()`／`can_see()` 守著。
- 判定只有一份（`classify()` / `is_enabled()`）；讀不到開關時維持預設（開）。
- **舊的 `ENABLE_*` 環境變數**（`ENABLE_COURSES`／`CALENDAR`／`BULLETIN`／`PRAYER`／`GOSPEL`／`VISITOR_FORMS`）只剩「預設值」的作用（`ENV_DEFAULTS`）：後台沒表態才生效，表態後以後台為準。這 6 個藍圖現在**一律註冊**（以前 `false` 時不註冊，模板裡的連結會斷）；`Config.ENABLE_*` 已移除，`guide`／`tutorial` 也改走登記表。
- **說明文件跟著開關**：`routes/guide.py`／`routes/tutorial.py` 每一步另外用 `is_path_enabled(url)` 判一次；`templates/manual.html` 每個 `feature-block` 依歸屬模組包 `{% if module_on('key') %}`（沒有路徑的區塊在 `tests/test_manual_follows_modules.py` 的 `PATHLESS` 登記歸屬）。新增手冊區塊時要照做，否則測試會紅。
- 新教會部署與交接：`docs/NEW_CHURCH_SETUP.md`（給非技術同工）；部署精靈 `/setup-wizard` 的「可選功能設定」列出目前的模組狀態。

### 後台權限矩陣（`routes/permissions.py`，移植自 event-registration-）
- Y 軸＝後台功能模塊（`ADMIN_MODULES`，**新增後台路由要到這裡登記前綴**，否則有測試會紅）；X 軸＝副標籤群組；權限存 `groups.admin_modules`；只有超管能在 `/admin/permissions` 編輯。
- 超管／`is_admin` 全部放行；其他人＝其副標籤授權模塊的聯集。**判定只有一份**：`module_allows_path()`，`admin_required` 與測試都走它。
- **與成熟版的差異（fail closed）**：沒登記的 `/admin` 路徑、後台以外的路徑，對副標籤成員一律拒絕；金流（`/admin/payments`、`/admin/settings/payment`）刻意不交給矩陣；session 裡的 `'*'` 只有「現在仍是管理員」才算數。
- **撤銷立即生效**：`routes/auth.py` 的 `refresh_session_permissions()` 每 5 分鐘（`PERM_RECHECK_SECONDS`）回資料庫重算 session 的權限（降權、封鎖、帳號被刪、矩陣調整都會生效，不必重新登入）；登入與重算共用 `_permission_fields()`，權限旗標只准在那裡寫一份。連不上資料庫時**維持原狀**（不登出、不推進時間戳）；只更新權限格，不碰 `is_demo` 等其他 session 內容。

### 帳號合併（`routes/user_merge.py`，移植自 event-registration-）
- 兩個入口（管理員 `admin.merge_line_account`、本人 `profile.merge_confirm`）共用 `merge_users()`；舊的 `account_merge.transfer_user_records`（每步 `except` 只記 log、失敗照樣刪帳號）已移除，有測試擋它復活。
- `REFS` 是唯一的引用清單（`schema.sql` 所有指向 `users` 的欄位＋`audit_logs.actor_id`）；測試掃 schema，漏一個或寫了不存在的欄位就紅。
- **失敗不吞掉**：任何一步失敗就中止、還原已搬的（含被刪掉的重複列）、不刪帳號、丟 `MergeError`；全部搬完且確認沒有殘留才刪被合併者的 `users` 列（已決定沿用成熟版，規格守衛 22 因此只對合併放寬）。
- 唯一限制衝突：只有登記 `dedupe` 的表（小組長、小組成員、禱告回應、每日經文、白名單）取聯集；其餘（出席、報名、認證、同工資料）一律中止，不替人決定留哪一邊。
- 聚會點名（`rc_*`）刻意不在清單裡；天父日記以 `line_user_id` 為鍵，隨 LINE 身分自動跟隨。

### 備份登記表（`backup_registry.py`）— 備份哪些表只有一份判定
- `TABLES`（外鍵安全的匯入順序＋upsert 衝突欄位＝真實主鍵＋所屬匯出模組）／`EXCLUDED`（刻意不備份，**必須寫理由**）／`VIEWS`（檢視表，不匯出）。**`schema.sql` 的每張表都必須在其中一處**，`tests/test_backup_registry.py` 掃 schema 守著；父表必須排在子表前面；衝突欄位對照 schema 的 PRIMARY KEY。
- 新增資料表時：同時補 `schema.sql` 與登記表，否則測試會紅。
- 超管匯出／匯入（`routes/data_transfer.py`）：匯出任何一張表讀取失敗就**整個中止**（不產出殘缺 ZIP）；資料表不存在（`reg.is_missing_table`）才記成「尚未建立」；匯入只寫登記表內的表，其餘略過並回報。匯出／匯入都寫稽核。
- 目前刻意不備份：`diary_entries`／`diary_share_grants`（隱私，**已決定**：超管匯出不含日記內容；個人可在 `/diary/export` 匯出自己的；災難還原需靠 Supabase 層級備份）、`notifications`（暫時性）、`contact_leads`（展示站專用）。檔案本體（R2）與留名單照片（Storage）不在資料庫匯出內，需另外備份。
- 可讀的 CSV 備份中心（`routes/backup.py`）：讀取失敗（`BackupReadError`）與資料表不存在是兩件事，前者顯示「讀取失敗」，不可顯示成「尚未啟用」。

### 「人」的建立（`routes/person.py`）
- 手動建立沒有 LINE 的會員一律走 `create_person()`：建立前 `find_possible_duplicates()`（姓名相同／差一個字／LINE 暱稱相同），有疑似重複回 409 讓管理員確認，`force` 才強制建立。比對用的正規化與「差一個字」判定與點名名冊共用（`roll_call_logic.norm_name`／`within_one_edit`）。
- 綁定 LINE 的唯一入口是「整合 LINE」（`user_merge`）：LINE 帳號必須自己登入過，不接受貼上 LINE ID 直接綁定（避免冒用）。
- 其餘 `users` 寫入（登入、個人資料、權限開關）維持原位，由結構守衛的棘輪凍結；`routes/person.py` 是新增的合法入口（基準 2 次）。

### 結構守衛（`tests/test_structure_guards.py`，棘輪式）
- 基準在 `tests/structure_baseline.json`：直接查 `users` 的次數（17 個檔案）、`date.today()` 等依伺服器時區的寫法、`or 0`、沒掛 `admin_required` 的 `/admin` 路由。**只准減少，不准增加**；減少時測試也會紅，提醒你執行 `python tests/structure_scan.py` 把基準往下調。
- 新模組（點名）不得查 `users`、不得用 `date.today()`；每個 `/admin` 路由必須有閘門（裝飾器或函式開頭手寫的管理員檢查）；刪除 `users` 列的路徑只有 `routes/user_merge.py` 一條。
- 掃描工具 `tests/structure_scan.py` 讀 AST／去掉註解後的原始碼，不執行程式。

### 天父日記 session 相容
diary.py 的 `_get_user()` 從整合系統 session 讀取（`line_id`、`real_name`），相容 event-registration- 格式。

### AI 客戶端
diary blueprint 在每次 API 呼叫時動態建立 AI 客戶端（`_get_ai_clients()`），不在啟動時強制依賴。優先使用 Groq，備援 Gemini。

**聚會人數回報**（`/cell-report/sunday`、`children`、`prayer`、`morning-prayer`）需要同工／牧者／管理員登入（`@staff_required`）；原 cell_reporter 的「免登入提交」已刻意取消。

### Supabase 資料表（小組回報）
| 資料表 | 說明 |
|--------|------|
| `cell_groups` | 小組（name, weekly_gather_day, is_active） |
| `cell_members` | 組員（group_id, name, is_active） |
| `cell_group_leaders` | 組長對應（user_id, group_id） |
| `cell_reports` | 週報主表 |
| `cell_attendance` | 出席紀錄（report_id, member_id, cell/sunday/rpg_status） |
| `sunday_reports` | 成人主日聚會人數 |
| `children_sunday_reports` | 兒童主日聚會人數 |
| `prayer_reports` | 禱告會人數 |
| `morning_prayer_reports` | 晨禱人數 |

### Supabase 資料表（禱讀本訂購）
| 資料表 | 說明 |
|--------|------|
| `devotional_orders` | 訂購主表（scripture, author, price, deadline, cover_url） |
| `devotional_registrations` | 各小組登記數量（order_id, group_name, quantity, is_delivered） |
| `devotional_registration_logs` | 登記變更記錄（audit log） |

migration 腳本：`migrations/007_devotional.sql`

### Supabase 資料表（天父日記後台）
| 資料表 | 說明 |
|--------|------|
| `diary_plan` | DB 讀經進度表（date, book, range）；優先於 plan.xlsx |
| `admin_whitelist` | 天父日記後台管理員白名單（line_user_id, is_active） |

migration 腳本：`migrations/008_diary_admin_whitelist.sql`

## 功能模組說明

### Portal（首頁入口）
- Hero 區塊與功能卡片同在 `max-width: 1280px` 容器內，Navbar 保持全寬
- Demo 模式啟用時底部顯示洽詢橫幅，`?` 說明按鈕自動上移避免被遮住
- 功能卡片包含：活動報名、天父日記、禱讀本訂購、檔案分享、小組回報等

### 禱讀本訂購（devotional_bp）
- 管理員可新增訂購、上傳封面圖、設截止日
- 各小組可登記本數，支援備註與已領取標記
- 管理員後台提供登記連結 QR code（使用 `api.qrserver.com` 產生）
- 封面上傳相容 iOS LINE WebView（使用 `<label for>` 而非 JS `click()`）
- 列印簽收條：`/devotional/<id>/print`

### 天父日記（diary_bp）
- 讀經進度：DB `diary_plan` 優先，fallback 讀 `plan.xlsx`（TTL 5 分鐘快取）
- 逐節經文支援逗號分隔多段範圍，如 `6:28-29,31:3`（去重保序）
- 日記後台管理員三層驗證：`session.is_admin` → 環境變數 `ADMIN_LINE_USER_IDS` → `admin_whitelist` 資料表（TTL 2 分鐘快取）
- 後台可管理讀經進度（逐筆 key-in 或批次匯入 xlsx）、牧者白名單、日記後台白名單
- 個人匯出 `/diary/export`：只匯出登入者自己的日記（鍵為 session 的 `line_id`，不接受參數）；讀取失敗不給檔案；稽核 `diary.export_self` 只記篇數

### 檔案分享（files_bp）
- 支援音訊預覽（`.mp3`, `.m4a`, `.wav`, `.ogg`, `.aac`）：直接顯示 `<audio>` 播放器
- **密碼保護**：檔案／資料夾的密碼只有 `_password_matches`、`_folder_locked`、`_file_in_locked_folder` 三個判定；分享連結、搜尋、view／stream／download 都要過；解鎖端點限速且要先有存取權（`tests/test_files_password_guards.py`）。資料夾可見性只有 `_can_access_folder` 一份
- 通知系統使用 `real_name`（整合系統 session key），非 `display_name`
- User picker 過濾已封鎖使用者（`.eq('is_blocked', False)`）

## 環境變數

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

# 管理員 LINE User IDs（逗號分隔）——同時是天父日記超管
ADMIN_LINE_USER_IDS=

# Demo 洽詢系統（正式教會部署版設為 false 或移除）
DEMO_MODE=          # true → 顯示底部洽詢橫幅
CONTACT_EMAIL=      # 管理員/開發者信箱（顯示於洽詢 Modal）
CONTACT_LINE=       # LINE 連結（可選）

# 錯誤監控（可選）
SENTRY_DSN=

# Render 部署
RENDER=
```

## 整體煙霧測試與 Python 相容

- **裝飾器順序**：`@login_required`／`@pastor_required`… 一律寫在 `@bp.route` **下面**（`tests/test_decorator_order.py` 掃整個專案）。寫在上面等於沒套，不會有任何錯誤。授權探針在 `tests/smoke_boot.py` 的 `PROBES`：新增需要權限的頁面時加一行。

- `tests/test_app_boot.py` 在子行程跑 `tests/smoke_boot.py`：真的 `create_app()`，三種身分打遍所有路由，不准有 500（唯一例外：沒設 R2 時 `/files` 回 503 說明頁）。新增路由時它自動涵蓋；若某路由在空資料庫下 500，先判斷是缺陷還是替身不夠真（替身在 `smoke_boot.py` 的 `DB`）。
- `tests/test_python_compat.py` 禁止 import 在 Python 3.12／3.13 被移除的標準函式庫（`imghdr`、`cgi`…）。圖片格式判斷用 `image_kind.image_kind()`。注意 Render 不一定看 `runtime.txt`，Python 版本以 `PYTHON_VERSION` 環境變數為準。

## 本地開發啟動

```bash
pip install -r requirements.txt
python app.py      # debug=True, port 5000
```

## 部署

平台：Render，自動從 `Procfile` 讀取 gunicorn 指令。

## 新教會部署 Migration 清單

每次為新教會部署時，依序在 Supabase > SQL Editor 執行：

| 順序 | 檔案 | 說明 |
|------|------|------|
| 001～006 | （既有 migrations） | 基礎資料表 |
| 007 | `migrations/007_devotional.sql` | 禱讀本訂購三張表 |
| 008 | `migrations/008_diary_admin_whitelist.sql` | 天父日記後台白名單 |
| 009 | `migrations/009_devotional_pickup.sql` | 禱讀本 QR 簽收欄位 |
| 010 | `migrations/010_audit_logs.sql` | 稽核日誌表 |
| 011 | `migrations/011_files_folders_groups.sql` | files.allowed_groups、folders.allowed_users / allowed_groups 補欄位 |
| 012 | `migrations/012_roll_call.sql` | 聚會點名（8 張 rc_* 表、稽核觸發器、寫入函式、RLS） |
| 013 | `migrations/013_security_hardening.sql` | 所有表開 RLS（不設政策）、函式不給公開角色。**僅限伺服器用服務端金鑰的專案**，詳見 `docs/SUPABASE_SETUP.md` |
| 014 | `migrations/014_permission_matrix.sql` | `groups.admin_modules`（後台權限矩陣；預設空陣列＝沒有授權，既有功能不受影響） |
| 015 | `migrations/015_report_submitter_columns.sql` | 聚會人數回報的 `submitted_by`／`updated_at`、`visitor_forms.uploaded_by`（程式一直在寫，schema 原本沒有） |
| 016 | `migrations/016_missing_columns.sql` | 補上程式一直在讀寫、schema 原本沒有的欄位（禱讀本收費、教材封面、代禱匿名／蒙應允／封存、日記登入寫入）；`diary_plan.plan_date` 改名為程式用的 `date`（只在舊欄位存在時） |

| 018 | `migrations/018_event_field_types.sql` | `event_fields` 允許 birthday／id_number／fee／guardian 四種欄位型別，並新增 `auto_tier`（報名表單強化、引導式開活動的前置） |
| 017 | `migrations/017_users_line_user_id_nullable.sql` | `users.line_user_id` 允許為空（手動建立的會員、合併後清空 LINE 身分的列；舊 schema 寫成 NOT NULL 會讓兩者失敗） |

新專案只需執行整份 `schema.sql`（已含 012～018）。**程式寫入的每個欄位 `schema.sql` 都必須有**（`tests/test_schema_guards.py` 掃 AST 守著；新增欄位要同時補 schema 與 migration）。

## 多教會部署架構與開發者權限原則

本系統設計為可重複部署給不同教會，每個教會有獨立的 Render 服務與 Supabase project。

### 角色分層

| 角色 | 能做什麼 | 不能做什麼 |
|------|---------|-----------|
| 教會超管（牧師/行政）| 系統設定、會員管理、封鎖用戶、查看全部資料 | — |
| 教會管理員 | 活動、報名、後台一般操作 | 超管功能 |
| **開發者（系統維護方）** | 程式碼更新、Render log 查看、DB schema 變更 | **不接觸教會用戶資料** |

### 開發者維護原則

1. **程式碼層維護**：push 程式碼到 GitHub → Render 自動重新部署，無需登入系統。
2. **不持有教會 Supabase 存取權**：各教會自行建立 Supabase project，填入自己的 `SUPABASE_URL` / `SUPABASE_KEY`。開發者提供 SQL migration 腳本，由教會管理員在 Supabase 後台執行。
3. **不在正式部署版擁有 app 層超管帳號**：Demo 版開發者可以是超管，正式部署版的超管帳號應移交給教會主責行政。
4. **schema 變更流程**：開發者提交 migration SQL → 通知教會管理員在 Supabase > SQL Editor 執行 → 再部署新版程式碼。
5. **DEMO_MODE 旗標**：Demo 示範站設 `DEMO_MODE=true`，正式教會部署設為 `false` 或移除，關閉洽詢橫幅。

### 各教會獨立環境清單

每次為新教會部署時，需準備：
- Render 新服務（或新環境）+ 各自的環境變數
- 獨立的 Supabase project（不共用）
- 獨立的 LINE Login Channel（`LINE_CHANNEL_ID` / `LINE_CHANNEL_SECRET`）
- 獨立的 Cloudflare R2 bucket（若需要檔案分享功能）
