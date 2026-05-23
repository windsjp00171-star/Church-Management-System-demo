# ⛪ 整合型教會行政系統

> 以 LINE Login 為核心的台灣本土教會管理平台，整合活動報名、小組牧養、靈修日記、差勤管理等功能於單一系統。

---

## 功能模組

| 模組 | 路由 | 說明 |
|------|------|------|
| 活動報名 | `/events` | 報名、候補、簽到 QR Code |
| 電子簽到 | `/checkin` | 現場掃碼 / 手動補簽 |
| 牧養小組 | `/profile` | 會友自選小組，管理員核准 |
| 小組回報 | `/cell-report` | 週報三步驟填寫、出席紀錄 |
| 門訓學程 | `/courses` | 課程管理、出席追蹤、結業認證 |
| 天父日記 | `/diary` | 每日靈修日記 + AI 反思引導 |
| 代禱麥田 | `/prayer` | 代禱發佈、回應、蒙應允標記 |
| 教會行事曆 | `/calendar` | 公共行事曆 + 個人私人事項 |
| 每週週報 | `/bulletins` | PDF 上傳與歷史瀏覽 |
| 福音探索 | `/gospel` | 新朋友詢問紀錄與跟進管理 |
| 留名單 | `/visitor-form` | 同工拍照上傳新朋友名單 |
| 檔案分享 | `/files` | R2 雲端儲存，資料夾權限管理 |
| 差勤管理 | `/attendance` | 全職同工特休／補休／加班（勞基法計算） |
| 站內通知 | — | 系統廣播、個人通知 |
| 系統更新通知 | 首頁橫幅 | 維運者發布更新，所有教會同步收到 |

---

## 技術架構

- **後端**：Python Flask（Blueprint 模組化）
- **資料庫**：Supabase PostgreSQL
- **登入**：LINE Login OAuth2
- **檔案儲存**：Cloudflare R2
- **AI**：Groq（主）/ Google Gemini（備援）
- **部署**：Render（gunicorn）
- **錯誤監控**：Sentry（選用）

---

## 快速部署

### 前置條件

| 平台 | 用途 | 誰管理 |
|------|------|--------|
| [Supabase](https://supabase.com) | 資料庫 | 各教會自建 |
| [LINE Developers](https://developers.line.biz) | 登入驗證 | 各教會自建 |
| [Render](https://render.com) | 應用程式伺服器 | 維運者統一管理 |
| [Cloudflare R2](https://cloudflare.com) | 檔案儲存（選用） | 各教會自建 |
| [Groq](https://groq.com) | AI 功能（選用） | 各教會自建 |

### 環境變數

```env
# Flask
FLASK_SECRET_KEY=

# LINE Login
LINE_CHANNEL_ID=
LINE_CHANNEL_SECRET=
LINE_REDIRECT_URI=https://<your-domain>/auth/callback
LINE_LIFF_ID=

# Supabase
SUPABASE_URL=
SUPABASE_KEY=

# 教會資訊
CHURCH_NAME=
CHURCH_SHORT_NAME=
PRIVACY_POLICY_URL=

# Cloudflare R2（選用）
R2_ENDPOINT=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=

# AI（選用）
GROQ_API_KEY=
GEMINI_API_KEY=

# 管理員 LINE User IDs（逗號分隔）
ADMIN_LINE_USER_IDS=

# 錯誤監控（選用）
SENTRY_DSN=

# Render 部署旗標
RENDER=true
```

### 資料庫建立

1. 建立 Supabase 專案（Region：Singapore）
2. 至 SQL Editor 執行 `schema.sql`
3. 選擇 **Run without RLS**

### Render 部署

```
Runtime:       Python
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
```

部署完成後前往 `/setup-wizard` 驗證所有設定。

---

## 本地開發

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入環境變數
python app.py          # http://localhost:5000
```

---

## 角色權限

| 角色 | 說明 |
|------|------|
| 訪客 | 僅能使用公開報名功能 |
| 會友 | 完整會友功能（日記、代禱、行事曆） |
| 小組長 | 填寫週報單、管理所屬小組 |
| 同工 | 聚會人數回報、現場簽到 |
| 牧者 | 查閱授權日記、牧養數據總覽 |
| 管理員 | 後台管理所有功能 |
| 超級管理員 | 會員管理、系統設定、差勤審核 |
| 全職同工 | 差勤申請（由超級管理員另行設定） |

---

## 維運指令（Claude Code Skill）

在 Claude Code 中可使用以下專案 Skill：

```
/release          發布系統更新日誌並推送
/deploy-church    引導完成新教會六步驟部署流程
```

---

## 隱私權政策

系統內建隱私權政策頁面，路由為 `/auth/privacy`，符合 LINE Login 審查要求。

---

## License

本專案為教會內部使用系統，未授權商業轉售。
