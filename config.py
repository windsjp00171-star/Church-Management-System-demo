import os
import sys
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Flask Session ──────────────────────────────────────────────
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')

    # Session：30 天長效，減少長輩重新登入頻率
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE   = bool(os.getenv('RENDER', False))
    SESSION_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)

    # ── LINE Login ─────────────────────────────────────────────────
    LINE_CHANNEL_ID     = os.getenv('LINE_CHANNEL_ID')
    LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
    LINE_REDIRECT_URI   = os.getenv('LINE_REDIRECT_URI')
    LINE_LIFF_ID        = os.getenv('LINE_LIFF_ID')        # 可選，None → LIFF 功能停用

    # LINE OAuth 端點（固定值，不從環境變數讀）
    LINE_AUTH_URL    = 'https://access.line.me/oauth2/v2.1/authorize'
    LINE_TOKEN_URL   = 'https://api.line.me/oauth2/v2.1/token'
    LINE_PROFILE_URL = 'https://api.line.me/v2/profile'

    # ── Supabase ───────────────────────────────────────────────────
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')

    # ── 教會資訊 ────────────────────────────────────────────────────
    CHURCH_NAME        = os.getenv('CHURCH_NAME', '教會行政系統')
    CHURCH_SHORT_NAME  = os.getenv('CHURCH_SHORT_NAME', '教會')
    PRIVACY_POLICY_URL = os.getenv('PRIVACY_POLICY_URL', '/auth/privacy')

    # ── Cloudflare R2（可選，未設定則檔案上傳功能停用）───────────────
    R2_ENDPOINT          = os.getenv('R2_ENDPOINT')         or None
    R2_ACCESS_KEY_ID     = os.getenv('R2_ACCESS_KEY_ID')    or None
    R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY') or None
    R2_BUCKET_NAME       = os.getenv('R2_BUCKET_NAME')      or None

    # ── AI 服務（可選，未設定則對應 AI 功能停用）──────────────────────
    GROQ_API_KEY      = os.getenv('GROQ_API_KEY')      or None  # 主要 AI（天父日記）
    GEMINI_API_KEY    = os.getenv('GEMINI_API_KEY')    or None  # 備援 AI
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY') or None  # 保留

    # ── 管理員 LINE User IDs（逗號分隔字串 → list）──────────────────
    _admin_ids_raw  = os.getenv('ADMIN_LINE_USER_IDS', '')
    ADMIN_LINE_USER_IDS = [x.strip() for x in _admin_ids_raw.split(',') if x.strip()]

    # ── 功能模組開關（設為 'false' 停用）────────────────────────────
    ENABLE_PRAYER        = os.getenv('ENABLE_PRAYER',        'true').lower() != 'false'
    ENABLE_GOSPEL        = os.getenv('ENABLE_GOSPEL',        'true').lower() != 'false'
    ENABLE_BULLETIN      = os.getenv('ENABLE_BULLETIN',      'true').lower() != 'false'
    ENABLE_CALENDAR      = os.getenv('ENABLE_CALENDAR',      'true').lower() != 'false'
    ENABLE_COURSES       = os.getenv('ENABLE_COURSES',       'true').lower() != 'false'
    ENABLE_VISITOR_FORMS = os.getenv('ENABLE_VISITOR_FORMS', 'true').lower() != 'false'

    # ── 部署旗標 ────────────────────────────────────────────────────
    RENDER = bool(os.getenv('RENDER', False))

    @classmethod
    def _validate(cls):
        """
        啟動時驗證必填環境變數。
        必填：FLASK_SECRET_KEY、SUPABASE_URL、SUPABASE_KEY、
              LINE_CHANNEL_ID、LINE_CHANNEL_SECRET、LINE_REDIRECT_URI
        可選：其餘變數（None → 對應功能降級）
        """
        required = {
            'FLASK_SECRET_KEY':   cls.SECRET_KEY,
            'SUPABASE_URL':       cls.SUPABASE_URL,
            'SUPABASE_KEY':       cls.SUPABASE_KEY,
            'LINE_CHANNEL_ID':    cls.LINE_CHANNEL_ID,
            'LINE_CHANNEL_SECRET': cls.LINE_CHANNEL_SECRET,
            'LINE_REDIRECT_URI':  cls.LINE_REDIRECT_URI,
        }

        # dev-secret-key 是預設值，在 production（RENDER=true）時也視為缺失
        if cls.RENDER and cls.SECRET_KEY == 'dev-secret-key':
            missing = ['FLASK_SECRET_KEY (使用預設值，production 環境不安全)']
        else:
            missing = []

        for name, val in required.items():
            if name == 'FLASK_SECRET_KEY':
                continue  # 已在上方單獨處理
            if not val:
                missing.append(name)

        if missing:
            print(
                '\n[Config ERROR] 以下必填環境變數未設定，系統無法正常啟動：\n'
                + '\n'.join(f'  - {m}' for m in missing)
                + '\n請在 .env 或 Render 環境變數設定後重新啟動。\n',
                file=sys.stderr,
            )
            sys.exit(1)

        # 可選功能提示（僅在非 production 環境輸出，避免日誌雜訊）
        if not cls.RENDER:
            optional_missing = []
            if not cls.R2_ENDPOINT:
                optional_missing.append('R2_ENDPOINT（檔案上傳功能停用）')
            if not cls.GROQ_API_KEY:
                optional_missing.append('GROQ_API_KEY（AI 功能停用）')
            if not cls.LINE_LIFF_ID:
                optional_missing.append('LINE_LIFF_ID（LIFF 功能停用）')
            if optional_missing:
                print(
                    '[Config INFO] 以下可選環境變數未設定（功能降級）：\n'
                    + '\n'.join(f'  - {m}' for m in optional_missing),
                    file=sys.stderr,
                )
