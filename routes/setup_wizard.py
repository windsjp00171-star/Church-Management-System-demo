import os
from flask import Blueprint, render_template, session, redirect, url_for, jsonify
from config import Config

setup_wizard_bp = Blueprint('setup_wizard', __name__)

# ── 環境變數定義（用於精靈頁面顯示）─────────────────────────────────
_ENV_GROUPS = [
    {
        'title': 'Flask 基本',
        'emoji': '⚙️',
        'signup_url': '',
        'signup_label': '',
        'vars': [
            {
                'key': 'FLASK_SECRET_KEY',
                'label': 'Flask Secret Key',
                'required': True,
                'secret': True,
                'hint': '不需申請帳號。在終端機執行：python -c "import secrets; print(secrets.token_hex(32))"，複製輸出值填入。',
            },
        ],
    },
    {
        'title': 'LINE Login',
        'emoji': '💬',
        'signup_url': 'https://developers.line.biz/',
        'signup_label': '申請 LINE Developers 帳號',
        'signup_steps': '1. 登入 developers.line.biz（用你的 LINE 帳號）→ 2. 建立 Provider → 3. 新增 Channel（選「LINE Login」）→ 4. 在 Channel 頁面取得 Channel ID 與 Channel Secret → 5. 在「Callback URL」填入你的 https://你的網域/auth/callback',
        'vars': [
            {
                'key': 'LINE_CHANNEL_ID',
                'label': 'LINE Channel ID',
                'required': True,
                'secret': False,
                'hint': 'LINE Developers → 你的 Channel → Basic settings → Channel ID',
            },
            {
                'key': 'LINE_CHANNEL_SECRET',
                'label': 'LINE Channel Secret',
                'required': True,
                'secret': True,
                'hint': '同上頁面 → Channel secret 欄位',
            },
            {
                'key': 'LINE_REDIRECT_URI',
                'label': 'LINE Redirect URI',
                'required': True,
                'secret': False,
                'hint': '格式：https://你的網域/auth/callback（必須與 LINE Developers 後台填寫的 Callback URL 完全一致）',
            },
            {
                'key': 'LINE_LIFF_ID',
                'label': 'LINE LIFF ID',
                'required': False,
                'secret': False,
                'hint': '可選。LINE Developers → 你的 Channel → LIFF → 新增 LIFF App → 複製 LIFF ID；未設定則 LINE 內自動登入功能停用',
            },
        ],
    },
    {
        'title': 'Supabase',
        'emoji': '🗄️',
        'signup_url': 'https://supabase.com/',
        'signup_label': '申請 Supabase 帳號',
        'signup_steps': '1. 前往 supabase.com 免費註冊 → 2. 建立新 Project（建議選 ap-southeast-1 新加坡，延遲較低）→ 3. 等待 Project 啟動後，進入 Project Settings → Data API → 複製 Project URL 與 anon public key',
        'vars': [
            {
                'key': 'SUPABASE_URL',
                'label': 'Supabase Project URL',
                'required': True,
                'secret': False,
                'hint': 'Supabase Dashboard → Project Settings → Data API → Project URL（格式：https://xxxx.supabase.co）',
            },
            {
                'key': 'SUPABASE_KEY',
                'label': 'Supabase Anon Key',
                'required': True,
                'secret': True,
                'hint': '同頁面 → Project API keys → anon public（這是公開金鑰，可安全使用）',
            },
        ],
    },
    {
        'title': '教會資訊',
        'emoji': '⛪',
        'signup_url': '',
        'signup_label': '',
        'vars': [
            {
                'key': 'CHURCH_NAME',
                'label': '教會全名',
                'required': False,
                'secret': False,
                'hint': '顯示在網站標題與通知，例如：天父恩典教會',
            },
            {
                'key': 'CHURCH_SHORT_NAME',
                'label': '教會簡稱',
                'required': False,
                'secret': False,
                'hint': '顯示在 PWA App 圖示下方，例如：天父堂',
            },
            {
                'key': 'ADMIN_LINE_USER_IDS',
                'label': '管理員 LINE User ID（逗號分隔）',
                'required': False,
                'secret': False,
                'hint': '登入系統後，從「個人資料」頁面複製你的 LINE User ID，填入此欄。多人用逗號隔開。',
            },
        ],
    },
    {
        'title': 'Cloudflare R2（檔案分享）',
        'emoji': '📁',
        'optional_group': True,
        'signup_url': 'https://dash.cloudflare.com/',
        'signup_label': '申請 Cloudflare 帳號',
        'signup_steps': '1. cloudflare.com 免費註冊 → 2. 左側選「R2 Object Storage」→ 3. 建立 Bucket（記住 Bucket 名稱）→ 4. 在 R2 Overview 頁面點「Manage R2 API Tokens」→ 5. 建立 Token（Object Read & Write 權限）→ 複製 Access Key ID、Secret Access Key、Endpoint URL',
        'vars': [
            {'key': 'R2_ENDPOINT',          'label': 'R2 Endpoint',          'required': False, 'secret': False, 'hint': '格式：https://帳號ID.r2.cloudflarestorage.com（建立 API Token 後頁面會顯示）'},
            {'key': 'R2_ACCESS_KEY_ID',     'label': 'R2 Access Key ID',     'required': False, 'secret': True,  'hint': 'Manage R2 API Tokens → 建立 Token 後取得'},
            {'key': 'R2_SECRET_ACCESS_KEY', 'label': 'R2 Secret Access Key', 'required': False, 'secret': True,  'hint': '同上，只在建立時顯示一次，請立即複製'},
            {'key': 'R2_BUCKET_NAME',       'label': 'R2 Bucket Name',       'required': False, 'secret': False, 'hint': '你在 Cloudflare R2 建立的 Bucket 名稱'},
        ],
    },
    {
        'title': '錯誤監控（Sentry）',
        'emoji': '🔍',
        'optional_group': True,
        'signup_url': 'https://sentry.io/',
        'signup_label': '申請 Sentry 帳號（免費）',
        'signup_steps': '1. sentry.io 免費註冊 → 2. 建立新 Project（選 Python → Flask）→ 3. 複製 DSN（格式：https://xxx@xxx.ingest.sentry.io/xxx）填入 SENTRY_DSN。免費方案每月 5,000 筆錯誤，小型教會完全足夠。',
        'vars': [
            {'key': 'SENTRY_DSN', 'label': 'Sentry DSN', 'required': False, 'secret': True,
             'hint': 'Sentry Dashboard → 你的 Project → Settings → Client Keys (DSN)；未設定則錯誤監控停用'},
        ],
    },
    {
        'title': 'AI 功能（天父日記）',
        'emoji': '🤖',
        'optional_group': True,
        'signup_url': 'https://console.groq.com/',
        'signup_label': '申請 Groq 帳號（免費）',
        'signup_steps': '1. console.groq.com 免費註冊 → 2. 左側選「API Keys」→ 3. 點「Create API Key」→ 複製 key 填入 GROQ_API_KEY。Groq 免費額度對小型教會已十分充足。',
        'vars': [
            {'key': 'GROQ_API_KEY',      'label': 'Groq API Key（主）',      'required': False, 'secret': True, 'hint': 'console.groq.com → API Keys → Create API Key'},
            {'key': 'GEMINI_API_KEY',    'label': 'Gemini API Key（備援）',  'required': False, 'secret': True, 'hint': 'aistudio.google.com → Get API Key（可選，Groq 失效時自動備援）'},
            {'key': 'ANTHROPIC_API_KEY', 'label': 'Anthropic API Key（保留）','required': False, 'secret': True, 'hint': '保留欄位，目前系統未主動使用'},
        ],
    },
]

# 核心資料表（檢查是否存在）
_CORE_TABLES = [
    'users', 'events', 'registrations', 'groups', 'settings',
    'cell_groups', 'cell_members', 'cell_group_leaders', 'cell_reports',
    'cell_attendance', 'sunday_reports', 'children_sunday_reports',
    'prayer_reports', 'morning_prayer_reports',
    'custom_meeting_reports',
    'diary_entries',
    'portal_card_settings', 'portal_links',
]


def _check_env_vars():
    """Return list of {key, label, required, set, value_preview, hint}."""
    results = []
    for group in _ENV_GROUPS:
        for v in group['vars']:
            val = os.environ.get(v['key'], '')
            is_set = bool(val)
            if is_set and not v['secret']:
                preview = val[:80] + ('…' if len(val) > 80 else '')
            elif is_set:
                preview = '●●●●●●●●'
            else:
                preview = ''
            results.append({**v, 'set': is_set, 'value_preview': preview})
    return results


def _check_db_tables():
    """Return {table_name: exists} dict, or None if DB not reachable."""
    try:
        from db import supabase
        existing = set()
        # Query information_schema for each table
        for tbl in _CORE_TABLES:
            try:
                res = supabase.table(tbl).select('id').limit(0).execute()
                existing.add(tbl)
            except Exception:
                pass
        return {t: (t in existing) for t in _CORE_TABLES}
    except Exception:
        return None


@setup_wizard_bp.get('/setup-wizard')
def index():
    # Allow access if: system not configured (Supabase missing) OR user is admin
    if Config.SUPABASE_URL and Config.SUPABASE_KEY:
        if not session.get('user_id'):
            return redirect(url_for('auth.login_page'))
        if not (session.get('is_admin') or session.get('is_pastor') or session.get('is_super_admin')):
            return redirect(url_for('event.portal'))

    env_vars = _check_env_vars()
    required_missing = [v for v in env_vars if v['required'] and not v['set']]
    all_required_ok = len(required_missing) == 0

    db_tables = _check_db_tables()

    # Group env vars for template display
    env_groups = []
    idx = 0
    for group in _ENV_GROUPS:
        gvars = []
        for v in group['vars']:
            gvars.append(env_vars[idx])
            idx += 1
        env_groups.append({**group, 'vars': gvars})

    # Count env var status per group
    for eg in env_groups:
        eg['ok_count'] = sum(1 for v in eg['vars'] if v['set'])
        eg['total_count'] = len(eg['vars'])

    missing_tables = []
    if db_tables:
        missing_tables = [t for t, ok in db_tables.items() if not ok]

    # Load schema.sql content for inline display
    schema_sql = ''
    try:
        schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'schema.sql')
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
    except Exception:
        pass

    return render_template(
        'setup_wizard/index.html',
        env_groups=env_groups,
        all_required_ok=all_required_ok,
        required_missing=required_missing,
        db_tables=db_tables,
        missing_tables=missing_tables,
        core_tables=_CORE_TABLES,
        render_url=os.environ.get('RENDER_EXTERNAL_URL', ''),
        supabase_url=Config.SUPABASE_URL or '',
        church_name=Config.CHURCH_NAME,
        line_redirect_uri=Config.LINE_REDIRECT_URI or '',
        schema_sql=schema_sql,
    )


@setup_wizard_bp.get('/setup-wizard/db-status')
def db_status():
    """AJAX: return DB table check results."""
    if not (session.get('is_admin') or session.get('is_pastor') or session.get('is_super_admin')):
        return jsonify({'error': 'unauthorized'}), 403
    tables = _check_db_tables()
    if tables is None:
        return jsonify({'error': 'DB not reachable'})
    return jsonify({'tables': tables})
