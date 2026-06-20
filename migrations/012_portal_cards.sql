-- 門戶卡片資料表（首頁功能磚）
-- 缺少此表時，超管在 /admin/portal-cards 編輯／排序卡片會 500（紅字警告）。

CREATE TABLE IF NOT EXISTS portal_cards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  emoji TEXT DEFAULT '🔗',
  subtitle TEXT DEFAULT '',
  url TEXT NOT NULL,
  visible_to TEXT DEFAULT 'all',
  is_active BOOLEAN DEFAULT TRUE,
  sort_order INTEGER DEFAULT 0,
  is_system BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO portal_cards (key, name, emoji, subtitle, url, visible_to, sort_order) VALUES
  ('events', '活動報名', '🎉', '查看並報名教會活動', '/events', 'all', 10),
  ('calendar', '行事曆', '📅', '教會行事曆與個人行程', '/calendar', 'member', 20),
  ('bulletin', '每週週報', '📰', '最新週報與公告', '/bulletins', 'all', 30),
  ('prayer', '代禱牆', '🙏', '分享需求，互相代禱', '/prayer', 'all', 40),
  ('gospel', '福音探索', '✝️', '認識信仰的第一步', '/gospel', 'all', 50),
  ('diary', '天父日記', '📖', '記錄每日與神的對話', '/diary', 'member', 60),
  ('my_history', '電子簽到', '🗂️', '我的活動出席紀錄', '/my-history', 'member', 70),
  ('courses', '門訓學程', '📚', '報名及追蹤進度', '/courses', 'member', 80),
  ('cell_report', '小組回報', '👥', '填寫本週小組聚會回報', '/cell-report/portal', 'cell_leader', 90),
  ('pastor_report', '牧者查閱', '📊', '查看各小組回報與統計', '/cell-report/pastor-dashboard', 'pastor', 100),
  ('staff_report', '同工查閱', '📋', '各區小組回報總覽', '/cell-report/staff-dashboard', 'staff', 110),
  ('pastor_diary', '查閱日記', '🔍', '已授權的會友日記', '/diary/pastor', 'pastor', 120),
  ('files', '檔案管理', '📁', '教會資料夾與檔案', '/files', 'admin', 130),
  ('admin', '後台管理', '⚙️', '使用者、活動、系統設定', '/admin', 'admin', 140)
ON CONFLICT (key) DO NOTHING;
