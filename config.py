import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask Session 加密金鑰
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')

    # Session：30 天長效，減少長輩重新登入頻率
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('RENDER', False)
    SESSION_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)

    # LINE Login 設定
    LINE_CHANNEL_ID = os.getenv('LINE_CHANNEL_ID')
    LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
    LINE_REDIRECT_URI = os.getenv('LINE_REDIRECT_URI')
    LINE_LIFF_ID = os.getenv('LINE_LIFF_ID', '')

    # LINE OAuth 端點
    LINE_AUTH_URL = 'https://access.line.me/oauth2/v2.1/authorize'
    LINE_TOKEN_URL = 'https://api.line.me/oauth2/v2.1/token'
    LINE_PROFILE_URL = 'https://api.line.me/v2/profile'

    # Supabase 設定
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')

    # 教會資訊（各機構部署時設定）
    CHURCH_NAME         = os.getenv('CHURCH_NAME', '我的教會')
    CHURCH_SHORT_NAME   = os.getenv('CHURCH_SHORT_NAME', '')   # 留空則自動用 CHURCH_NAME
    PRIVACY_POLICY_URL  = os.getenv('PRIVACY_POLICY_URL', '')

    # Cloudflare R2 設定（church-data-hub 檔案分享模組）
    R2_ENDPOINT         = os.getenv('R2_ENDPOINT', '')
    R2_ACCESS_KEY_ID    = os.getenv('R2_ACCESS_KEY_ID', '')
    R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY', '')
    R2_BUCKET_NAME      = os.getenv('R2_BUCKET_NAME', '')

    # 功能模組開關（設為 'false' 停用，其餘值或未設定皆視為啟用）
    ENABLE_PRAYER    = os.getenv('ENABLE_PRAYER',    'true').lower() != 'false'
    ENABLE_GOSPEL    = os.getenv('ENABLE_GOSPEL',    'true').lower() != 'false'
    ENABLE_BULLETIN  = os.getenv('ENABLE_BULLETIN',  'true').lower() != 'false'
    ENABLE_CALENDAR  = os.getenv('ENABLE_CALENDAR',  'true').lower() != 'false'
    ENABLE_COURSES   = os.getenv('ENABLE_COURSES',   'true').lower() != 'false'
    ENABLE_VISITOR_FORMS = os.getenv('ENABLE_VISITOR_FORMS', 'true').lower() != 'false'
