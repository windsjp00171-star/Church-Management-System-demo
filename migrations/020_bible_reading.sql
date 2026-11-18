-- 020：365 天聖經速讀計畫 —— 每個人的打勾進度，以及經文快取
--
-- 為什麼：成熟版（event-registration-）的「聖經速讀」搬進這個專案。計畫本身（365 格）放在 repo 的
-- data/bible_reading_plan_365.json，資料庫只存「誰讀完了哪一格」和「抓回來的經文」。
--
-- 影響：兩張全新的表，既有表與資料完全不動。每個人的進度只存日期。可重複執行。
--   bible_reading_progress：主鍵 (user_id, plan_key, day_no) ＝「一人一格一次」；
--                           plan_key 讓日後換計畫時大家的勾不會悄悄指到不一樣的經文。
--   bible_chapters        ：經文快取（抓一次存起來，可重抓，所以備份不備它）。
-- 兩張表都開 RLS 且不設政策（伺服器用服務端金鑰，跟 013 一致）。
-- 還原：DROP TABLE IF EXISTS bible_reading_progress; DROP TABLE IF EXISTS bible_chapters;
--       （只會丟掉大家的打勾進度與經文快取，快取之後可以重抓）
-- 沒執行的話：讀經頁照常打得開（進度是空的、經文每次重抓），按「我讀完了」會顯示存不進去；其他功能不受影響。
CREATE TABLE IF NOT EXISTS bible_reading_progress (
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_key        TEXT        NOT NULL,
    day_no          INTEGER     NOT NULL CHECK (day_no >= 1),
    read_on         DATE,                               -- 打勾的日期（台北）
    reread_count    INTEGER     NOT NULL DEFAULT 0,     -- 這一格重讀過幾次
    last_reread_on  DATE,                               -- 最近一次重讀（台北）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, plan_key, day_no)
);
CREATE INDEX IF NOT EXISTS bible_reading_progress_user_idx ON bible_reading_progress (user_id, plan_key);

CREATE TABLE IF NOT EXISTS bible_chapters (
    book        TEXT        NOT NULL,                   -- 書卷全名，例：創世記
    chapter     INTEGER     NOT NULL CHECK (chapter >= 1),
    verses      JSONB       NOT NULL,                   -- [{"v":1,"text":"…"}, …]
    source      TEXT,                                   -- 從哪個網址抓的
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (book, chapter)
);

ALTER TABLE bible_reading_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE bible_chapters         ENABLE ROW LEVEL SECURITY;
