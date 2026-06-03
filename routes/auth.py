import secrets
import requests
from urllib.parse import urlparse
from flask import Blueprint, redirect, request, session, url_for, render_template, jsonify
from config import Config
from db import supabase
from datetime import datetime, timedelta, timezone

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/privacy')
def privacy():
    return render_template('auth/privacy.html')


def _populate_session(user):
    """把使用者所有角色旗標一次寫入 session，各模組不需要自己查 DB。"""
    user_id = user['id']

    # 查詢此使用者負責的小組 ID 清單
    leaders_res = supabase.table('cell_group_leaders')\
        .select('group_id')\
        .eq('user_id', user_id)\
        .execute()
    cell_group_ids = [r['group_id'] for r in (leaders_res.data or [])]

    session.permanent        = True
    session['user_id']       = user_id
    session['line_id']       = user.get('line_user_id', '')
    session['display_name']  = user.get('display_name', '')
    session['picture_url']   = user.get('picture_url', '')
    session['real_name']     = user.get('real_name') or ''
    session['member_type']   = user.get('member_type') or 'member'
    session['group_tags']    = user.get('group_tags') or []
    session['role']          = user.get('role') or 'approved'
    # 權限旗標（全部從 users 表讀取，統一管理）
    session['is_admin']      = bool(user.get('is_admin'))
    session['is_super_admin']= bool(user.get('is_super_admin'))
    session['is_pastor']     = bool(user.get('is_pastor'))
    session['is_staff']      = bool(user.get('is_staff'))
    session['cell_group_ids']= cell_group_ids


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


@auth_bp.route('/')
def login_page():
    next_url = _safe_next_url(request.args.get('next'))
    if session.get('user_id'):
        return redirect(next_url or url_for('event.portal'))
    _remember_next_url(next_url)
    return render_template('auth/login.html', next_url=next_url)


@auth_bp.route('/contact', methods=['POST'])
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
        pass  # 表不存在時靜默忽略

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
        pass

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
