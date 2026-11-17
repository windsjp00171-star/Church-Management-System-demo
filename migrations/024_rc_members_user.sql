-- 024：點名名冊連到帳號（一個人＝一個帳號；沒申請 LINE 就先建空殼帳號，之後用「整合 LINE」合併）
--
-- 為什麼：使用者（2026-11-17）：「名冊其實不跟帳號脫鉤」「就是一個身分對應而已」。
--   點名名冊原本只有姓名；現在記「這個人是哪個帳號」。點名單上新增新朋友會直接建空殼帳號並連起來。
-- ★ 出勤紀錄（rc_records）、稽核、出席率算法都不動：它們仍然掛在名冊成員上，只是名冊成員多了帳號。
-- ★ 唯一索引：一個帳號只能對到名冊上的一個人（不然同一人會在點名單出現兩次）。
-- ★ 帳號被刪時名冊成員保留、回到「未連帳號」（ON DELETE SET NULL），點名紀錄不會跟著消失。
--   帳號合併時名冊跟著搬（routes/user_merge.py 的 REFS）。
--
-- 影響：rc_members 多一欄＋一個部分唯一索引；既有資料全部是 NULL（＝未連帳號）。可重複執行。
-- 還原：DROP INDEX IF EXISTS rc_members_user_uidx; ALTER TABLE rc_members DROP COLUMN IF EXISTS user_id;
ALTER TABLE rc_members
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX IF NOT EXISTS rc_members_user_uidx ON rc_members (user_id) WHERE user_id IS NOT NULL;
