# /deploy-church — 新教會部署引導

引導完成一間新教會的完整部署流程，逐步確認每個平台的設定。

## 使用方式

```
/deploy-church <教會名稱>
```

若未帶教會名稱，先詢問用戶。

---

## 部署流程（共 6 步驟）

逐步引導，每步確認完成後才進入下一步。

---

### Step 1 — Supabase 專案

**請用戶完成以下操作，完成後告知我：**

1. 前往 https://supabase.com → New Project
2. Project name 建議：`<教會短名>-church`（全小寫英文）
3. 選擇離台灣最近的 Region：**Southeast Asia (Singapore)**
4. 記下 **Project URL** 和 **anon/public key**（Settings → API）

**完成後，請求用戶提供：**
- `SUPABASE_URL`
- `SUPABASE_KEY`

**自動執行：**
使用 Supabase MCP 工具，在該專案執行 `schema.sql` 的全部內容建立所有資料表。
執行完成後列出已建立的資料表清單供用戶確認。

---

### Step 2 — LINE Login Channel

**請用戶完成以下操作：**

1. 前往 LINE Developers Console → Create a new channel → **LINE Login**
2. Channel 名稱：`<教會名稱>管理系統`
3. 在 LINE Login → Callback URL 填入：`https://<之後Render的域名>/auth/callback`
   （先暫填，Step 4 完成後再回來更新）
4. 記下 **Channel ID** 和 **Channel Secret**

**完成後，請求用戶提供：**
- `LINE_CHANNEL_ID`
- `LINE_CHANNEL_SECRET`

---

### Step 3 — 管理員 LINE User ID

**請用戶完成以下操作：**

取得管理員的 LINE User ID（可用 LINE Developers 的 Profile API，或讓管理員先登入系統後從 Supabase `users` 表查詢）。

**完成後，請求用戶提供：**
- `ADMIN_LINE_USER_IDS`（多位管理員用逗號分隔）

---

### Step 4 — Render 部署

**請用戶完成以下操作：**

1. 前往 https://render.com → New → Web Service
2. 連接 GitHub repo：`windsjp00171-star/church-management-system-demo`
3. 設定：
   - Name：`<教會短名>-church`
   - Branch：`main`
   - Runtime：`Python`
   - Build Command：`pip install -r requirements.txt`
   - Start Command：`gunicorn app:app`
4. 新增環境變數（列出所有必填項）：

```
FLASK_SECRET_KEY=<隨機長字串，可用 openssl rand -hex 32 產生>
LINE_CHANNEL_ID=<Step 2>
LINE_CHANNEL_SECRET=<Step 2>
LINE_REDIRECT_URI=https://<render域名>/auth/callback
SUPABASE_URL=<Step 1>
SUPABASE_KEY=<Step 1>
CHURCH_NAME=<教會全名>
CHURCH_SHORT_NAME=<教會簡稱>
ADMIN_LINE_USER_IDS=<Step 3>
GROQ_API_KEY=<教會自行申請>
GEMINI_API_KEY=<教會自行申請，可選>
RENDER=true
```

5. 點 **Deploy**，等待部署完成
6. 記下 Render 提供的域名（如 `xxx-church.onrender.com`）

**部署完成後，回到 Step 2 更新 LINE Login 的 Callback URL。**

---

### Step 5 — 驗證部署精靈

**請用戶：**

1. 打開 `https://<render域名>/setup-wizard`
2. 截圖或告知每個區塊的狀態（✓ / ✗）

**自動判斷：**
- 若全部 ✓：繼續 Step 6
- 若有 ✗：根據失敗項目提供具體修復指引

---

### Step 6 — 初始化第一位管理員

**請用戶：**

1. 用管理員的 LINE 帳號登入系統
2. 前往 `/admin` 確認可以進入後台
3. 在「會員管理」將自己的帳號設為超級管理員

**完成！** 列出部署摘要：
- 教會名稱
- 系統網址
- 已完成的平台清單
- 提醒：定期備份 Supabase 資料

---

## 注意事項

- Render 免費方案 15 分鐘無流量會休眠，首次載入較慢（約 30–60 秒）
- `FLASK_SECRET_KEY` 一旦設定不要修改，否則所有用戶 session 會失效
- LINE Redirect URI 必須完全符合，包含 https 與路徑
