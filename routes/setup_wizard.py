import os
from flask import Blueprint, render_template, session, redirect, url_for, jsonify
from config import Config

setup_wizard_bp = Blueprint('setup_wizard', __name__)

# ── 環境變數定義（用於精靈頁面顯示）─────────────────────────────────
_ENV_GROUPS = [
    {
        'title': 'Render 部署平台',
        'emoji': '🚀',
        'signup_url': 'https://render.com/',
        'signup_label': '申請 Render 帳號（免費）',
        'deploy_guide_only': True,
        'signup_steps': (
            '═══ 首次部署（新服務）═══\n'
            '\n'
            '① 前往 render.com → 點右上角「Get Started for Free」\n'
            '   → 選擇「GitHub」登入（建議用你管理源碼的 GitHub 帳號）\n'
            '\n'
            '② 登入後進入 Dashboard → 點「New +」→ 選「Web Service」\n'
            '\n'
            '③ 連接 GitHub Repo\n'
            '   • 選「Connect a repository」→ 搜尋你的 church-management-system-demo\n'
            '   • 若看不到 repo → 點「Configure account」→ 在 GitHub 授權頁面允許 Render 存取\n'
            '   • ⚠️ 本系統源碼由維運者統一管理，教會不需要自己的 GitHub 帳號\n'
            '\n'
            '④ 基本設定（新建 Web Service 頁面）\n'
            '   • Name：填入易識別的名稱，例如 church-abc-system\n'
            '   • Region：選 Singapore（離台灣最近）\n'
            '   • Branch：main（或你指定的部署分支）\n'
            '   • Runtime：Python 3\n'
            '   • Build Command：pip install -r requirements.txt\n'
            '   • Start Command：gunicorn app:app（或參考 Procfile）\n'
            '   • Instance Type：Free（免費，初期夠用）\n'
            '\n'
            '⑤ 往下滑到「Environment Variables」區塊\n'
            '   → 點「Add Environment Variable」逐一填入以下各組設定\n'
            '   → 所有帶敏感資訊的值（key、secret）請直接填值，不要公開\n'
            '   ⚠️ Groq / Gemini API Key 每間教會填自己申請的，避免 rate limit 互相影響\n'
            '\n'
            '⑥ 填完環境變數後 → 點最下方「Create Web Service」\n'
            '   → Render 開始自動 Build & Deploy（約 3～5 分鐘）\n'
            '   → 部署完成後會顯示綠色 ● Live，URL 格式：https://你命名的服務.onrender.com\n'
            '\n'
            '═══ 之後更新代碼（維運者操作）═══\n'
            '\n'
            '• 你 push 代碼到 GitHub → Render 自動偵測並重新部署（預設開啟 Auto-Deploy）\n'
            '• 若要手動觸發：Dashboard → 選服務 → 右上角「Manual Deploy」→「Deploy latest commit」\n'
            '• 多間教會各自一個 Web Service，一次 push 全部自動更新，無需個別操作\n'
            '\n'
            '═══ 新增第二間教會（複製服務）═══\n'
            '\n'
            '① Dashboard → 點「New +」→「Web Service」→ 選同一個 repo\n'
            '② 修改 Name（改成第二間教會的識別名稱）\n'
            '③ 環境變數填入新教會的 Supabase、LINE、CHURCH_NAME 等（每間都不同）\n'
            '④ 建立完成，兩間教會共用同一份代碼，完全獨立運行\n'
        ),
        'vars': [],
    },
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
        'signup_steps': (
            '① 前往 developers.line.biz，點右上角「Log in」→ 用你的 LINE 帳號登入\n'
            '② 登入後點左側「Providers」→「Create」→ 輸入 Provider 名稱（例：你的教會名稱）→「Create」\n'
            '③ 進入 Provider 頁面 → 點「Create a new channel」→ 選「LINE Login」\n'
            '④ 填寫：Channel name（任意）、Channel description、App type 勾選「Web app」→ 點「Create」\n'
            '⑤ 進入剛建立的 Channel →「Basic settings」分頁：\n'
            '   • Channel ID（數字）→ 複製填入 LINE_CHANNEL_ID\n'
            '   • Channel secret（點「Issue」後複製）→ 填入 LINE_CHANNEL_SECRET\n'
            '⑥ 點「LINE Login」分頁 →「Callback URL」欄位填入：\n'
            '   https://你的Render網域/auth/callback\n'
            '   （例：https://church-xxxx.onrender.com/auth/callback）→ 點「Update」儲存\n'
            '⑦ 回到 Channel 頁面頂部，將狀態從「Development」切換為「Published」\n'
            '   ⚠️ 未 Publish 前只有你自己能登入，其他會友無法使用'
        ),
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
        'signup_steps': (
            '① 前往 supabase.com →「Start your project」→「Sign Up」免費註冊（可用 GitHub 帳號）\n'
            '② 登入後點右上角「New project」\n'
            '③ 填寫：\n'
            '   • Name：任意（例：church-system）\n'
            '   • Database Password：設定強密碼並記住（之後不會用到，但忘了就麻煩了）\n'
            '   • Region：選「Southeast Asia (Singapore)」— 台灣延遲最低\n'
            '   → 點「Create new project」，等待約 1-2 分鐘啟動\n'
            '④ 啟動完成後，左側點「Project Settings（齒輪圖示）」→「Data API」\n'
            '⑤ 複製「Project URL」→ 填入 SUPABASE_URL\n'
            '   （格式：https://xxxxxxxxxxxxxxxx.supabase.co）\n'
            '⑥ 往下找「Project API keys」→ 複製「anon public」那行 →填入 SUPABASE_KEY\n'
            '   （service_role 那行不要用，權限過大）\n'
            '⑦ 建表：左側點「SQL Editor」→ 貼上本頁「建表 SQL」→ 點「Run」執行\n'
            '   看到「Success. No rows returned」表示建表成功'
        ),
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
        'signup_steps': (
            '① 前往 cloudflare.com →「Sign Up」免費註冊\n'
            '② 登入後，左側選單找「R2 Object Storage」（可能需要先啟用，按提示操作即可）\n'
            '③ 點「Create bucket」：\n'
            '   • Bucket name：全英文小寫+連字號（例：church-files）→ 記住這個名稱\n'
            '   • Location：選「Asia Pacific (APAC)」→「Create bucket」\n'
            '④ 回到 R2 主頁（左側 R2 Object Storage），點右上角「Manage R2 API Tokens」\n'
            '⑤ 點「Create API Token」：\n'
            '   • Token name：任意（例：church-system）\n'
            '   • Permissions：選「Object Read & Write」\n'
            '   • Specify bucket：選你剛建立的 bucket\n'
            '   → 點「Create API Token」\n'
            '⑥ 建立後頁面顯示憑證（⚠️ 只顯示一次，請立刻複製）：\n'
            '   • Access Key ID → 填入 R2_ACCESS_KEY_ID\n'
            '   • Secret Access Key → 填入 R2_SECRET_ACCESS_KEY\n'
            '   • Endpoint（頁面上方的 S3 API 網址）→ 填入 R2_ENDPOINT\n'
            '     格式：https://帳號ID.r2.cloudflarestorage.com\n'
            '⑦ 步驟③的 Bucket 名稱 → 填入 R2_BUCKET_NAME'
        ),
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
        'signup_steps': (
            '① 前往 sentry.io →「Get Started」免費註冊（可用 GitHub 帳號）\n'
            '② 登入後系統會引導建立第一個 Organization，名稱隨意\n'
            '③ 點「Create Project」：\n'
            '   • 選平台：找「Python」→「Flask」\n'
            '   • Alert frequency：選「Alert me on every new issue」\n'
            '   • Project name：任意（例：church-system）→「Create Project」\n'
            '④ 建立後頁面會顯示 DSN，格式如下：\n'
            '   https://xxxxxxxx@xxxxxxxx.ingest.sentry.io/xxxxxxx\n'
            '   → 複製填入 SENTRY_DSN\n'
            '⑤ 若找不到 DSN：左側「Settings」→「Projects」→ 你的 Project\n'
            '   →「Client Keys (DSN)」→ 複製第一個 DSN\n'
            '   免費方案每月 5,000 筆錯誤回報，小型教會完全足夠'
        ),
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
        'signup_steps': (
            '【Groq — 主要 AI，免費】\n'
            '① 前往 console.groq.com →「Sign Up」（可用 Google 帳號）\n'
            '② 登入後，左側點「API Keys」\n'
            '③ 點「Create API Key」→ 輸入名稱（例：church-system）→「Submit」\n'
            '④ 複製顯示的 key（⚠️ 只顯示一次）→ 填入 GROQ_API_KEY\n'
            '   免費方案每分鐘 30 次、每天 14,400 次，小型教會完全足夠\n\n'
            '【Gemini — 備援 AI，可選】\n'
            '① 前往 aistudio.google.com →「Get API key」（需 Google 帳號）\n'
            '② 點「Create API key」→ 選或建一個 Google Cloud 專案 → 複製 key → 填入 GEMINI_API_KEY\n'
            '   Groq 若臨時達到速率限制，系統會自動切換 Gemini 繼續服務'
        ),
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
    'gospel_cards', 'gospel_form_questions', 'gospel_inquiries',
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

        # 優先嘗試 RPC（繞過 PostgREST schema cache）
        # 若 RPC 本身也不可用，fallback 到 select limit 0
        rpc_ok = False
        try:
            r = supabase.rpc('check_table_exists', {'tbl_name': 'users'}).execute()
            if r.data is not None:
                rpc_ok = True
        except Exception:
            pass

        for tbl in _CORE_TABLES:
            try:
                if rpc_ok:
                    result = supabase.rpc('check_table_exists', {'tbl_name': tbl}).execute()
                    if result.data:
                        existing.add(tbl)
                else:
                    supabase.table(tbl).select('*').limit(0).execute()
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
