# Supabase 連線模組
from supabase import create_client
from config import Config

# 建立 Supabase client（全域唯一）
supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)