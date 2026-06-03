-- 禱讀本訂購模組
-- 執行方式：Supabase > SQL Editor > 貼上執行

CREATE TABLE IF NOT EXISTS devotional_orders (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scripture   TEXT NOT NULL,
    author      TEXT,
    price       INTEGER DEFAULT 0,
    deadline    DATE,
    cover_url   TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS devotional_registrations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID REFERENCES devotional_orders(id) ON DELETE CASCADE,
    group_name      TEXT NOT NULL,
    quantity        INTEGER DEFAULT 0,
    notes           TEXT,
    is_delivered    BOOLEAN DEFAULT FALSE,
    registered_by   UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(order_id, group_name)
);

CREATE TABLE IF NOT EXISTS devotional_registration_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    UUID REFERENCES devotional_orders(id) ON DELETE CASCADE,
    group_name  TEXT,
    quantity    INTEGER,
    notes       TEXT,
    changed_by  UUID REFERENCES users(id),
    changed_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS devotional_regs_order_idx ON devotional_registrations (order_id);
CREATE INDEX IF NOT EXISTS devotional_logs_order_idx ON devotional_registration_logs (order_id);
