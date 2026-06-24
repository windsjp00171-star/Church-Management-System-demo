-- Demo 洽詢系統留言表（DEMO_MODE 底部洽詢橫幅送出的資料）
-- 缺少此表時送出洽詢會被靜默忽略（auth.py 有 try-except），
-- 但 /admin/contact-leads 將永遠空白。正式教會部署可略過此表。

CREATE TABLE IF NOT EXISTS contact_leads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  church TEXT,
  contact_info TEXT NOT NULL,
  message TEXT,
  submitted_at TIMESTAMPTZ DEFAULT NOW()
);
