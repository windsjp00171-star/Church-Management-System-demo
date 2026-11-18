import logging
import os
import secrets
import requests
from urllib.parse import urlparse
from flask import Blueprint, redirect, request, session, url_for, render_template, jsonify, abort
from config import Config
from db import supabase
from extensions import limiter
from datetime import datetime, timedelta, timezone

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/privacy')
def privacy():
    return render_template('auth/privacy.html')


def _permission_fields(user):
    """「他是誰、他能做什麼」那幾格——只准有這一份實作。

    先算好整包再回傳（可能丟例外），呼叫端才一次寫進 session：
    算到一半失敗的話，session 不會停在「旗標是新的、模塊是舊的」的半套狀態。
    """
    user_id = user['id']
    leaders_res = supabase.table('cell_group_leaders')\
        .select('group_id').eq('user_id', user_id).execute()
    fields = {
        'real_name':      user.get('real_name') or '',
        'member_type':    user.get('member_type') or 'member',
        'group_tags':     user.get('group_tags') or [],
        'role':           user.get('role') or 'approved',
        # 權限旗標（全部從 users 表讀取，統一管理）
        'is_admin':       bool(user.get('is_admin')),
        'is_super_admin': bool(user.get('is_super_admin')),
        'is_pastor':      bool(user.get('is_pastor')),
        'is_staff':       bool(user.get('is_staff')),
        'is_blocked':     bool(user.get('is_blocked')),
        'cell_group_ids': [r['group_id'] for r in (leaders_res.data or [])],
    }
    # 環境變數定義的超管（ADMIN_LINE_USER_IDS）一律具備超管權限（與 CLAUDE.md 設計一致）
    _luid = user.get('line_user_id') or ''
    if _luid and _luid in Config.ADMIN_LINE_USER_IDS:
        fields['is_admin'] = True
        fields['is_super_admin'] = True
    # 後台模塊權限（副標籤 × 模塊矩陣）。超管／管理員為 '*'；其他人由其副標籤授權的模塊決定
    from routes.permissions import compute_admin_modules
    mods = compute_admin_modules(fields['is_super_admin'], fields['is_admin'], fields['group_tags'])
    fields['admin_modules'] = '*' if mods == '*' else sorted(mods)
    return fields


def _now_ts():
    return int(datetime.now(timezone.utc).timestamp())


def _populate_session(user):
    """登入時把使用者所有角色旗標一次寫入 session，各模組不需要自己查 DB。"""
    fields = _permission_fields(user)
    session.permanent        = True
    session['user_id']       = user['id']
    session['line_id']       = user.get('line_user_id', '')
    session['display_name']  = user.get('display_name', '')
    session['picture_url']   = user.get('picture_url', '')
    session.update(fields)
    session['is_demo']       = False  # 真實登入預設非展示帳號（demo_login 會覆寫為 True）
    session['_user_verified']= True  # 剛從 DB 讀出，免去 before_request 再驗證
    session['_perm_checked_at'] = _now_ts()


# ── PWA 續登（機制說明見 routes/pwa_session.py）──────────────────────────
def load_user_for_pwa(user_id):
    """PWA 續登用：依 id 撈使用者。

    ★★ **查詢失敗要丟例外，不可以回 `None`。** 兩者都回 `None` 的話，「Supabase 抖了一下」跟
      「這個帳號被停用」走同一條路 —— 而那條路是把他丟回 LINE 登入頁、要他輸入註冊 email 和密碼
      （幾乎沒有人記得那組）。「PWA 會偶發性卡登入」就是這個形狀：偶發、重開一次又好了、系統裡沒有記錄。
    ★ 先重試一次再放棄：這條路一次 PWA 啟動只走一次（不是每個請求），一次抖動的代價是他被要求輸入
      一組他不記得的密碼，這筆交換很划算。
    """
    last = None
    for attempt in (1, 2):
        try:
            rows = supabase.table('users').select('*')\
                .eq('id', user_id).execute().data or []
            break
        except Exception as exc:       # noqa: PERF203 — 只有兩次
            last = exc
    else:
        raise last                      # ★ 丟出去，讓呼叫端分得出是誰的問題
    if not rows or rows[0].get('is_blocked'):
        return None                     # 這一種才是「本來就不給登入」
    return rows[0]


def record_pwa_problem(why, user_id):
    """PWA 續登沒成功時留一筆（原本完全沒有記錄，使用者回報「偶發卡登入」時手上一個數字都沒有）。

    三種原因處理方式完全不同，所以分開記：bad_token（manifest 舊了／SECRET_KEY 換過，重新登入就好）、
    not_allowed（查無此人或已停用，本來就不該登入）、load_failed（我們自己的問題，資料庫連不上）。
    ★ `actor_id` 會是 None，那是對的 —— 這一刻沒有人登入，身分只存在網址那個 token 裡，所以放進 detail。
    ★ 不可以丟例外：留記錄失敗不可以讓登入失敗（呼叫端也包了一層）。
    """
    from routes.audit import log_action
    log_action('pwa.login_failed', 'user', user_id, {'why': why})


# ── 權限撤銷要立即生效 ──────────────────────────
#
# session 很長（使用者族群有一半是長輩，常常重登會直接放棄）。代價是「登入時算一次」的東西
# 會一直停在登入那一刻：把某人的管理員／同工關掉、封鎖帳號、調整權限矩陣，
# 後台那顆開關確實變了，他的 session 卻照樣是舊的。這一類「按了有反應但實際沒生效」
# 是最難發現的 bug。所以每隔 PERM_RECHECK_SECONDS 回資料庫重算一次（跟登入同一支）。
PERM_RECHECK_SECONDS = 300      # 5 分鐘：夠即時，又不會每個請求都多查詢


def refresh_session_permissions(force=False):
    """定期回資料庫重算 session 裡的權限。回 True 代表這個 session 已被清掉。

    ★ 查不到人（帳號被刪）或已封鎖 → 清掉 session。清掉之後**不自己決定導去哪**，
      交給原本的守衛（頁面導登入頁、API 回 401），避免兩邊各有一份回應邏輯。
    ★ 連不上資料庫、或重算失敗時**維持原狀**（fail open），而且**不更新時間戳**，下一個請求再試。
      反過來做的話，Supabase 抖一下就把全教會登出，代價遠大於「撤銷晚五分鐘生效」。
    ★ 只更新權限那幾格；不碰 is_demo 等其他 session 內容。
    """
    uid = session.get('user_id')
    if not uid:
        return False
    if not force and _now_ts() - int(session.get('_perm_checked_at', 0)) < PERM_RECHECK_SECONDS:
        return False
    try:
        rows = supabase.table('users').select('*').eq('id', uid).execute().data or []
        if rows and not rows[0].get('is_blocked'):
            fields = _permission_fields(rows[0])
        else:
            fields = None
    except Exception:
        logging.getLogger(__name__).warning('權限重算失敗，維持原狀', exc_info=True)
        return False
    if fields is None:
        session.clear()
        return True
    session.update(fields)
    session['_perm_checked_at'] = _now_ts()
    return False


def _safe_next_url(value):
    """只允許站內路徑或同網域網址，避免登入後被導到外部網站。"""
    if not value:
        return None

    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        current = urlparse(request.host_url)
        if parsed.scheme not in ('http', 'https') or parsed.netloc != current.netloc:
            return None
        path = parsed.path or '/'
        return path + (f'?{parsed.query}' if parsed.query else '')

    if not value.startswith('/') or value.startswith('//'):
        return None
    return value


def _remember_next_url(value):
    next_url = _safe_next_url(value)
    if next_url:
        session['next_url'] = next_url
    return next_url


def _consume_next_url(fallback=None):
    return _safe_next_url(session.pop('next_url', None)) or fallback


@auth_bp.route('/login')
def login():
    _remember_next_url(request.args.get('next'))

    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state

    params = (
        f"response_type=code"
        f"&client_id={Config.LINE_CHANNEL_ID}"
        f"&redirect_uri={Config.LINE_REDIRECT_URI}"
        f"&state={state}"
        f"&scope=profile%20openid"
    )
    return redirect(f"{Config.LINE_AUTH_URL}?{params}")


@auth_bp.route('/callback')
@limiter.limit('20 per minute')
def callback():
    # 驗證 state 防止 CSRF 攻擊
    received_state = request.args.get('state')
    expected_state = session.pop('oauth_state', None)
    if not received_state or not expected_state or received_state != expected_state:
        return '登入驗證失敗，請重新登入', 400

    code = request.args.get('code')
    if not code:
        return '授權失敗，請重試', 400

    token_res = requests.post(Config.LINE_TOKEN_URL, data={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': Config.LINE_REDIRECT_URI,
        'client_id': Config.LINE_CHANNEL_ID,
        'client_secret': Config.LINE_CHANNEL_SECRET,
    })
    token_data = token_res.json()
    access_token = token_data.get('access_token')

    if not access_token:
        return 'LINE 登入失敗，請重試', 400

    profile_res = requests.get(
        Config.LINE_PROFILE_URL,
        headers={'Authorization': f'Bearer {access_token}'}
    )
    profile = profile_res.json()
    line_user_id = profile.get('userId')
    display_name = profile.get('displayName')
    picture_url = profile.get('pictureUrl')

    existing = supabase.table('users')\
        .select('*')\
        .eq('line_user_id', line_user_id)\
        .execute()

    if existing.data:
        user = existing.data[0]
        # 更新名稱與頭像，然後重新撈最新資料（包含最新的 is_admin）
        supabase.table('users').update({
            'display_name': display_name,
            'picture_url': picture_url,
        }).eq('id', user['id']).execute()

        # 重新查詢拿最新的 is_admin
        refreshed = supabase.table('users')\
            .select('*')\
            .eq('id', user['id'])\
            .execute()
        user = refreshed.data[0]

    else:
        result = supabase.table('users').insert({
            'line_user_id': line_user_id,
            'display_name': display_name,
            'picture_url': picture_url,
        }).execute()
        user = result.data[0]

    if user.get('is_blocked'):
        return render_template('auth/blocked.html'), 403

    _populate_session(user)

    if not user.get('real_name'):
        return redirect(url_for('profile.onboarding'))

    return redirect(_consume_next_url(url_for('event.portal')))


@auth_bp.route('/liff-login', methods=['POST'])
@limiter.limit('20 per minute')
def liff_login():
    """LIFF 登入：前端送來 ID Token，驗證後建立 session"""
    data = request.get_json() or {}
    id_token = data.get('id_token')
    if not id_token:
        return jsonify({'error': 'Missing ID token'}), 400

    # 向 LINE 驗證 ID Token
    verify_res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
        'id_token': id_token,
        'client_id': Config.LINE_CHANNEL_ID,
    })
    profile = verify_res.json()

    if 'error' in profile:
        return jsonify({'error': f'登入驗證失敗，請重試（{profile.get("error_description", "unknown")}）'}), 401

    line_user_id = profile.get('sub')
    display_name = profile.get('name')
    picture_url = profile.get('picture', '')

    # 查或建立使用者（同 OAuth callback 邏輯）
    existing = supabase.table('users')\
        .select('*').eq('line_user_id', line_user_id).execute()

    if existing.data:
        user = existing.data[0]
        supabase.table('users').update({
            'display_name': display_name,
            'picture_url': picture_url,
        }).eq('id', user['id']).execute()
        refreshed = supabase.table('users')\
            .select('*').eq('id', user['id']).execute()
        user = refreshed.data[0]
    else:
        result = supabase.table('users').insert({
            'line_user_id': line_user_id,
            'display_name': display_name,
            'picture_url': picture_url,
        }).execute()
        user = result.data[0]

    if user.get('is_blocked'):
        return jsonify({'error': '帳號已被停用，請聯繫教會行政同工'}), 403

    _populate_session(user)

    # 第一次登入尚未填真實姓名 → 引導填資料
    incoming_next = _safe_next_url(data.get('next_url'))
    session_next = _consume_next_url()
    next_url = incoming_next or session_next

    if not user.get('real_name'):
        if next_url:
            session['next_url'] = next_url
        return jsonify({'redirect': url_for('profile.onboarding')})

    # 從 POST data 讀 next_url（手機 LIFF 跳轉後 cookie 可能消失，以 URL 參數為主）
    # fallback 到 session（OAuth 桌機流程）
    return jsonify({'redirect': next_url or url_for('event.portal')})


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login_page'))


@auth_bp.route('/force-relogin')
def force_relogin():
    """清除 session 後直接發起 LINE 登入。

    用於帳號被刪除／合併後瀏覽器仍殘留舊 session 導致卡死的自助恢復。
    """
    session.clear()
    return redirect(url_for('auth.login'))


@auth_bp.route('/')
def login_page():
    next_url = _safe_next_url(request.args.get('next'))
    if session.get('user_id'):
        return redirect(next_url or url_for('event.portal'))
    _remember_next_url(next_url)
    return render_template('auth/login.html', next_url=next_url, demo_mode=Config.DEMO_MODE)


# ── 展示廳沙盒登入（僅 DEMO_MODE 啟用時存在）─────────────────────────────────
# 安全規範：所有假登入邏輯都被 Config.DEMO_MODE 閘門包住。
# 正式環境（DEMO_MODE 未設或為 false）這些路由一律回 404，完全走原本 LINE 登入。

# 角色 → 對應的 seed_demo.py 預設帳號（line_user_id 是固定值，可穩定撈出）。
# 若該專案尚未跑 seed_demo.py，則以 fallback 動態建立基本展示帳號。
_DEMO_ACCOUNTS = {
    'pastor': {
        'line_user_id': 'Udemo00000001',
        'fallback': {'display_name': '林建志牧師', 'real_name': '林建志', 'member_type': 'member',
                     'is_admin': True, 'is_super_admin': True, 'is_pastor': True, 'role': 'approved'},
    },
    'admin': {
        'line_user_id': 'Udemo00000002',
        'fallback': {'display_name': '陳美玲同工', 'real_name': '陳美玲', 'member_type': 'member',
                     'is_admin': True, 'is_staff': True, 'role': 'approved'},
    },
    'leader': {
        'line_user_id': 'Udemo00000008',
        'fallback': {'display_name': '劉思穎', 'real_name': '劉思穎', 'member_type': 'member', 'role': 'approved'},
        'is_leader': True,
    },
    'member': {
        'line_user_id': 'Udemo00000004',
        'fallback': {'display_name': '李靜宜', 'real_name': '李靜宜', 'member_type': 'member', 'role': 'approved'},
    },
}


def _ensure_demo_leader_group(user_id):
    """確保展示用小組長至少帶領一個小組（沒有任何小組時建一個展示小組）。"""
    grp = supabase.table('cell_groups').select('id').eq('is_active', True).limit(1).execute().data
    gid = grp[0]['id'] if grp else supabase.table('cell_groups').insert(
        {'name': '展示小組', 'weekly_gather_day': '三', 'is_active': True}).execute().data[0]['id']
    exists = supabase.table('cell_group_leaders').select('id')\
        .eq('user_id', user_id).eq('group_id', gid).execute().data
    if not exists:
        supabase.table('cell_group_leaders').insert({'user_id': user_id, 'group_id': gid}).execute()


@auth_bp.route('/demo-login/<role>')
def demo_login(role):
    """點擊角色按鈕直接模擬登入：撈出（或建立）該角色的展示帳號並寫入 session。"""
    if not Config.DEMO_MODE:
        abort(404)
    spec = _DEMO_ACCOUNTS.get(role)
    if not spec:
        abort(404)

    res = supabase.table('users').select('*').eq('line_user_id', spec['line_user_id']).execute()
    if res.data:
        user = res.data[0]
    else:
        # 後備：未跑 seed_demo.py 時，動態建立基本展示帳號
        payload = dict(spec['fallback'], line_user_id=spec['line_user_id'])
        user = supabase.table('users').insert(payload).execute().data[0]
        if spec.get('is_leader'):
            _ensure_demo_leader_group(user['id'])

    _populate_session(user)
    session['is_demo'] = True   # 標記為展示帳號（純體驗；資料每日重置）
    return redirect(url_for('event.portal'))


def _run_demo_reseed():
    """背景執行：清除並重新灌入展示假資料。"""
    try:
        import seed_demo
        seed_demo.clear()
        seed_demo.seed()
        logging.info('demo reseed completed')
    except Exception as e:
        logging.warning('demo reseed failed: %s', e)


@auth_bp.route('/demo-reset')
def demo_reset():
    """每日重置展示資料。授權方式二擇一：
      1. 帶 ?token=<DEMO_RESET_TOKEN>（供外部排程 / UptimeRobot 每日呼叫）
      2. 擁有者本人（真實登入的超管，非展示帳號）—— 供現場手動重置
    內建「每日只重置一次」防護：頻繁呼叫不會重複重灌（owner 可帶 ?force=1 強制）。
    """
    if not Config.DEMO_MODE:
        abort(404)
    import threading
    import settings_store as ss
    from datetime import date

    token    = request.args.get('token', '')
    expected = os.environ.get('DEMO_RESET_TOKEN', '')
    is_owner = bool(session.get('is_super_admin')) and not session.get('is_demo')
    if not (is_owner or (expected and token == expected)):
        abort(403)

    today = date.today().isoformat()
    force = request.args.get('force') == '1' or is_owner
    try:
        last = ss.get('demo_last_reset')
    except Exception:
        last = None
    if last == today and not force:
        return jsonify({'status': 'skipped', 'reason': 'already reset today', 'date': today})

    try:
        ss.set('demo_last_reset', today)
    except Exception:
        pass
    threading.Thread(target=_run_demo_reseed, daemon=True).start()
    return jsonify({'status': 'started', 'date': today})


@auth_bp.route('/contact', methods=['POST'])
@limiter.limit('5 per minute')
def contact_submit():
    """Demo 洽詢表單：將留言存入 DB 並通知所有管理員。"""
    data = request.get_json() or {}
    name         = (data.get('name') or '').strip()[:50]
    church       = (data.get('church') or '').strip()[:100]
    contact_info = (data.get('contact') or '').strip()[:200]
    message      = (data.get('message') or '').strip()[:1000]

    if not name or not contact_info:
        return jsonify({'error': '姓名與聯絡方式為必填'}), 400

    body_text = f"教會/機構：{church or '（未填）'}\n聯絡方式：{contact_info}\n\n{message or '（無附加說明）'}"

    # 儲存到 contact_leads 表（不存在也不崩潰）
    try:
        supabase.table('contact_leads').insert({
            'name': name,
            'church': church,
            'contact_info': contact_info,
            'message': message,
            'submitted_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        }).execute()
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)  # 表不存在時靜默忽略

    # 通知所有管理員
    try:
        admins = supabase.table('users').select('id')\
            .eq('is_admin', True).execute().data or []
        admin_ids = [a['id'] for a in admins]
        if admin_ids:
            rows = [{
                'user_id': uid,
                'title':   f'📩 新洽詢：{name}',
                'body':    body_text[:200],
                'type':    'info',
                'link':    '/admin/contact-leads',
            } for uid in admin_ids]
            for i in range(0, len(rows), 100):
                supabase.table('notifications').insert(rows[i:i+100]).execute()
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)

    return jsonify({'success': True})


@auth_bp.route('/setup-admin', methods=['GET', 'POST'])
def setup_admin():
    """首次部署初始化，或已是 admin 但尚未有 is_super_admin 時升級用。"""
    if not session.get('user_id'):
        return redirect(url_for('auth.login_page') + '?next=/auth/setup-admin')

    existing_admin = supabase.table('users').select('id')\
        .eq('is_admin', True).limit(1).execute().data

    # 已有 super_admin → 只允許現有超管進入，任何非超管（含一般 admin）一律擋回
    existing_super = supabase.table('users').select('id')\
        .eq('is_super_admin', True).limit(1).execute().data
    if existing_super and not session.get('is_super_admin'):
        return redirect(url_for('event.portal'))

    # 已是 admin 且已有 super_admin → 已設定完成，直接進後台
    if existing_super and session.get('is_super_admin'):
        return redirect(url_for('admin.index'))

    if request.method == 'POST':
        supabase.table('users').update({'is_admin': True, 'is_super_admin': True})\
            .eq('id', session['user_id']).execute()
        # 重新載入 user 並更新 session
        updated = supabase.table('users').select('*')\
            .eq('id', session['user_id']).execute().data[0]
        _populate_session(updated)
        return redirect(url_for('admin.index'))

    return render_template('auth/setup_admin.html')
