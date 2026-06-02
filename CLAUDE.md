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
templates/              # Jinja2 模板
  base.html             # 共用基底模板
  diary/                # 天父日記模板（extends base.html）
  files/                # 檔案分享模板
  cell_report/          # 小組回報模板
  ...                   # 其他模板
data/
  book_background.py    # 聖經書卷背景說明
scripture/
  cuv.json              # 和合本聖經全文（JSON）
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
| `is_pastor` | 牧者旗標（小組回報用） |
| `is_staff` | 同工旗標（小組回報用） |
| `picture_url` | 大頭貼 URL |
| `member_type` | `'member'` / `'visitor'` |

### 天父日記 session 相容
diary.py 的 `_get_user()` 從整合系統 session 讀取（`line_id`、`real_name`），相容 event-registration- 格式。

### AI 客戶端
diary blueprint 在每次 API 呼叫時動態建立 AI 客戶端（`_get_ai_clients()`），不在啟動時強制依賴。優先使用 Groq，備援 Gemini。

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

# 管理員 LINE User IDs（逗號分隔）
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

## 本地開發啟動

```bash
pip install -r requirements.txt
python app.py      # debug=True, port 5000
```

## 部署

平台：Render，自動從 `Procfile` 讀取 gunicorn 指令。

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
