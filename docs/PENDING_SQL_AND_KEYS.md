# 你要處理的 SQL 與金鑰（2026-11-07）

> **2026-11-08 更新**：推播（B1）、主日信息（B2）、讀經推播、首頁近期提醒**程式都已經合併**，
> 對應的 SQL 就是 `migrations/021_push_subscriptions.sql`、`migrations/022_sermons.sql`（可重複執行，直接在 Supabase → SQL Editor 貼上）。
> 生日祝賀（B3）、使用數據（B4）**決定不搬**，可忽略。

## A. 已經合併、需要你在正式站執行（不執行＝新功能不會動或存不進去）

| 檔案 | 說明 | 不執行的後果 |
|---|---|---|
| `migrations/018_event_field_types.sql` | 報名欄位多四種型別、`auto_tier` | 後台建分級收費／生日／監護人欄位會失敗 |
| `migrations/020_bible_reading.sql` | 365 天速讀進度與經文快取 | `/reading` 打勾存不進去 |

新教會直接執行整份 `schema.sql`（已含）。

## B. 想要的功能需要的 SQL（程式還沒搬，你同意我才搬）

### B1. 手機推播（`push_subscriptions`）
```sql
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint    TEXT NOT NULL UNIQUE,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_ok_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS push_subscriptions_user_idx ON push_subscriptions(user_id);
```
- 動到：只新增一張表，既有資料不變。回復：`DROP TABLE push_subscriptions;`（只有裝置憑證，重新訂閱就有，但每個人要再按一次）。
- 不做的話：推播整個不存在（站內通知照舊）。

### B2. 主日信息（`sermons`，欄位是從成熟版程式反推的，成熟版 repo 沒有這張表的 migration）
```sql
CREATE TABLE IF NOT EXISTS sermons (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id     TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    speaker      TEXT,
    scripture    TEXT,
    is_hidden    BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ
);
```
- 回復：`DROP TABLE sermons;`（影片重抓就有，但同工補的講員／經文會消失）。
- 另需：後台「設定」填教會 YouTube 播放清單網址（一行一個）。**不需要金鑰**。

### B3. 生日祝賀（`users.birthday`）
```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS birthday date;
```
- 既有資料全部是 NULL，不受影響。回復：`ALTER TABLE users DROP COLUMN birthday;`（會刪掉已填的生日）。
- 注意：這會動到 `users` 表，`schema.sql`、備份登記表也要同步。

### B4. 使用數據（兩張表，沒有個人資料以外的內容）
```sql
CREATE TABLE IF NOT EXISTS module_views (
    user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module    TEXT NOT NULL,
    viewed_on DATE NOT NULL,
    hits      INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, module, viewed_on)
);
CREATE TABLE IF NOT EXISTS portal_link_clicks (
    link_id    UUID NOT NULL,
    clicked_on DATE NOT NULL,
    hits       INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (link_id, clicked_on)
);
```
- `module_views` 是唯一會留個人瀏覽紀錄的功能：只記模組不記網址、一人一模組一天一列、只保留 180 天（程式負責清）。
- 回復：`DROP TABLE module_views; DROP TABLE portal_link_clicks;`。

## C. 金鑰與環境變數（Render → Environment）

| 變數 | 用在 | 怎麼拿 | 備註 |
|---|---|---|---|
| `VAPID_PUBLIC_KEY`、`VAPID_PRIVATE_KEY` | 手機推播 | 在自己電腦 `pip install py-vapid` 後執行 `vapid --gen`，會產生一組金鑰 | **私鑰只放 Render，不要進 repo、不要貼到對話** |
| `VAPID_SUBJECT` | 手機推播 | 填教會網站網址（`https://…`，後面不要加斜線或路徑） | 不要填個人 email |
| `TASK_TOKEN` | 手動觸發排程 `/tasks/tick?token=…` | 自己隨便取一串夠長的亂數 | 選填；沒設只是不能手動觸發，排程照跑 |
| `LINE_LIFF_ID` | 「用瀏覽器開啟」按鈕 | LIFF 網址 `https://liff.line.me/<這一段>` | 沒設會靜默失效，且 Safari 私密瀏覽登不進來時沒有備援 |

主日信息、行事曆訂閱、PWA 續登、讀經計畫：**不需要新金鑰**（PWA／行事曆用 `FLASK_SECRET_KEY` 簽章，**換了這把，所有人的訂閱網址與 PWA 續登會一起失效**）。

## D. 我沒有動、也不建議自動動的
- 成熟版 `tianfu-diary` 有 15 張表 RLS 關閉（是另一個專案，不在這個 repo）。
- 備份：`push_subscriptions`、`sermons`、`portal_link_clicks` 在成熟版有備份；搬進來時我會一併補進備份登記表。
