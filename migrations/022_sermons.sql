-- 022：主日信息（影片留在 YouTube，系統只記「有這一部、它是什麼時候的」）
--
-- 為什麼：成熟版的「主日信息」搬進這個專案。影片本來就會上傳到教會的 YouTube，系統去讀播放清單，
--   把沒看過的影片存進來；前台按「一週一組」顯示。
-- ★ video_id 唯一：同一部影片重抓只會被略過（insert only，不覆蓋）。
-- ★ speaker／scripture／is_hidden 是同工手動補的，抓取永遠不會覆蓋；標題與日期跟著 YouTube 更新。
--
-- 影響：一張全新的表，既有表與資料完全不動。可重複執行。
-- 還原：DROP TABLE IF EXISTS sermons;（影片重抓就有，但同工補的講員／經文會消失）
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
CREATE INDEX IF NOT EXISTS sermons_created_idx ON sermons (created_at DESC);

ALTER TABLE sermons ENABLE ROW LEVEL SECURITY;
