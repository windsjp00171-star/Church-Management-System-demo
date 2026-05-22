import os
from flask import Blueprint, render_template, session, redirect, url_for, jsonify
from config import Config

setup_wizard_bp = Blueprint('setup_wizard', __name__)

# ── 環境變數定義（用於精靈頁面顯示）─────────────────────────────────
_ENV_GROUPS = [
    {
        'title': 'Flask 基本',
        'emoji': '⚙️',
        'vars': [
            {
                'key': 'FLASK_SECRET_KEY',
                'label': 'Flask Secret Key',
                'required': True,
                'secret': True,
                'hint': '用於 session 加密，請用 python -c "import secrets; print(secrets.token_hex(32))" 生成',
            },
        ],
    },
    {
        'title': 'LINE Login',
        'emoji': '💬',
        'vars': [
            {
                'key': 'LINE_CHANNEL_ID',
                'label': 'LINE Channel ID',
                'required': True,
                'secret': False,
                'hint': '從 LINE Developers Console → Channel Basic settings 取得',
            },
            {
                'key': 'LINE_CHANNEL_SECRET',
                'label': 'LINE Channel Secret',
                'required': True,
                'secret': True,
                'hint': '同上，Channel secret 欄位',
            },
            {
                'key': 'LINE_REDIRECT_URI',
                'label': 'LINE Redirect URI',
                'required': True,
                'secret': False,
                'hint': '格式：https://你的網域/auth/callback',
            },
            {
                'key': 'LINE_LIFF_ID',
                'label': 'LINE LIFF ID',
                'required': False,
                'secret': False,
                'hint': '可選，LIFF 應用程式 ID；未設定則 LIFF 功能停用',
            },
        ],
    },
    {
        'title': 'Supabase',
        'emoji': '🗄️',
        'vars': [
            {
                'key': 'SUPABASE_URL',
                'label': 'Supabase Project URL',
                'required': True,
                'secret': False,
                'hint': '格式：https://xxxxxxxxxxxx.supabase.co',
            },
            {
                'key': 'SUPABASE_KEY',
                'label': 'Supabase Anon Key',
                'required': True,
                'secret': True,
                'hint': 'Project Settings → API → anon public key',
            },
        ],
    },
    {
        'title': '教會資訊',
        'emoji': '⛪',
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
                'hint': '設定後，這些 LINE 帳號登入即為管理員；可在登入後從個人資料頁複製 User ID',
            },
        ],
    },
    {
        'title': 'Cloudflare R2（檔案分享）',
        'emoji': '📁',
        'optional_group': True,
        'vars': [
            {'key': 'R2_ENDPOINT',          'label': 'R2 Endpoint',          'required': False, 'secret': False, 'hint': 'Cloudflare R2 API 端點'},
            {'key': 'R2_ACCESS_KEY_ID',     'label': 'R2 Access Key ID',     'required': False, 'secret': True,  'hint': ''},
            {'key': 'R2_SECRET_ACCESS_KEY', 'label': 'R2 Secret Access Key', 'required': False, 'secret': True,  'hint': ''},
            {'key': 'R2_BUCKET_NAME',       'label': 'R2 Bucket Name',       'required': False, 'secret': False, 'hint': ''},
        ],
    },
    {
        'title': 'AI 功能（天父日記）',
        'emoji': '🤖',
        'optional_group': True,
        'vars': [
            {'key': 'GROQ_API_KEY',      'label': 'Groq API Key（主）',      'required': False, 'secret': True, 'hint': '主要 AI 服務，免費額度充足'},
            {'key': 'GEMINI_API_KEY',    'label': 'Gemini API Key（備援）',  'required': False, 'secret': True, 'hint': ''},
            {'key': 'ANTHROPIC_API_KEY', 'label': 'Anthropic API Key（保留）','required': False, 'secret': True, 'hint': ''},
        ],
    },
]

# 核心資料表（檢查是否存在）
_CORE_TABLES = [
    'users', 'events', 'event_registrations', 'groups', 'settings',
    'cell_groups', 'cell_members', 'cell_group_leaders', 'cell_reports',
    'cell_attendance', 'sunday_reports', 'children_sunday_reports',
    'prayer_reports', 'morning_prayer_reports',
    'custom_meeting_reports',
    'diary_entries', 'diary_whitelist',
    'portal_cards', 'portal_links',
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
