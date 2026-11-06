-- 010 安全強化：每張表開 RLS（不設任何政策）、函式不開放給公開角色
--
-- 目的：就算有人拿到「公開金鑰（anon / publishable key）」，直接連 Supabase 也什麼都讀不到、寫不進、呼叫不了。
-- 前提：伺服器（Render）使用的是「服務端金鑰（service_role / secret key）」——它繞過 RLS，所以網站照常運作。
--       若 Render 的 SUPABASE_KEY 填的是公開金鑰，執行後網站會讀不到任何資料（請先確認金鑰種類）。
-- 可重複執行。新增資料表後請再執行一次（或在建表時自己加 ENABLE ROW LEVEL SECURITY）。
-- 還原（不建議）：ALTER TABLE <表名> DISABLE ROW LEVEL SECURITY;
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.tablename);
    END LOOP;

    -- Supabase 才有這些角色；一般 Postgres（本機測試）略過
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated;
        GRANT  EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT  EXECUTE ON FUNCTIONS TO service_role;
    END IF;
END $$;
