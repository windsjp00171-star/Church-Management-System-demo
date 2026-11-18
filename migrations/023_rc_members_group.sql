-- 023：點名名冊可以分小組（點名單照小組分段、可收合，比較快找到人）
--
-- 為什麼：點名名冊（rc_members）跟會員帳號脫鉤，原本沒有「這個人是哪一組」。使用者決定（2026-11-17）：
--   組別直接用「週間小組」（cell_groups，小組回報那一份；讀經進度分組也是用它）。
-- ★ 只是「點名單怎麼分段顯示」，跟出席率、人數算法無關。
-- ★ 小組被刪掉時那些人回到「未分組」（ON DELETE SET NULL），點名名冊與歷史紀錄都不受影響。
--
-- 影響：rc_members 多一欄，既有資料全部是 NULL（＝未分組），其他表不動。可重複執行。
-- 還原：ALTER TABLE rc_members DROP COLUMN IF EXISTS group_id;（會清掉已設定的分組）
ALTER TABLE rc_members
    ADD COLUMN IF NOT EXISTS group_id UUID REFERENCES cell_groups(id) ON DELETE SET NULL;
