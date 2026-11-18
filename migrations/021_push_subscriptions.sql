-- 021：手機推播訂閱（Web Push）
--
-- 為什麼：成熟版的「手機推播」搬進這個專案。一個人可以有很多列（手機一列、平板一列）。
-- ★ UNIQUE 的是 endpoint（瀏覽器給的那台裝置的位址），不是 user_id —— 弄成 user_id 唯一的話，
--   他在平板上訂閱會把手機那筆蓋掉，而手機從此收不到，沒有任何症狀。
-- ★ 同一台裝置重新訂閱時 endpoint 一樣 → upsert 蓋掉舊的，不會累積到一則通知收 N 次。
-- ★ ON DELETE CASCADE：帳號刪掉時訂閱跟著走，不會繼續往沒有主人的裝置推播。
--
-- 影響：一張全新的表，既有表與資料完全不動。可重複執行。
-- 還原：DROP TABLE IF EXISTS push_subscriptions;（裡面只有裝置憑證，重新訂閱就有，
--       但每個人都要再按一次「開啟手機通知」）
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

ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;
