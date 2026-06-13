import logging
# 會員個人資料路由
from flask import Blueprint, session, redirect, url_for, render_template, request, jsonify, current_app, flash
from db import supabase
from routes.decorators import login_required

profile_bp = Blueprint('profile', __name__)


def _find_merge_candidate(real_name, group_tags, current_user_id):
    """找「姓名相同、至少一個小組相符」的既有帳號（自助合併偵測用）。

    回傳候選帳號 row 或 None。候選若已綁 LINE 則由呼叫端引導聯繫管理員。
    """
    if not real_name or not group_tags:
        return None
    try:
        candidates = supabase.table('users')\
            .select('id, real_name, line_user_id, group_tags')\
            .eq('real_name', real_name)\
            .neq('id', current_user_id)\
            .execute().data or []
    except Exception:
        logging.getLogger(__name__).warning('合併候選查詢失敗', exc_info=True)
        return None
    for c in candidates:
        if set(c.get('group_tags') or []) & set(group_tags):
            return c
    return None


@profile_bp.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    """首次登入 onboarding 流程（3 步驟：歡迎 → 填資料 → 功能預覽）"""
    # 已完成設定的使用者直接進入首頁
    if session.get('real_name'):
        return redirect(url_for('event.portal'))

    if request.method == 'POST':
        data = request.get_json() or {}
        real_name = data.get('real_name', '').strip()
        if not real_name:
            return jsonify({'error': '請填寫真實姓名'}), 400

        member_type = data.get('member_type', 'member')
        if member_type not in ('member', 'visitor'):
            member_type = 'member'

        tags = [t for t in data.get('group_tags', []) if t] if member_type == 'member' else []

        # 自助合併偵測：管理員先手動建檔（同名＋同小組、無 LINE）的情境
        if member_type == 'member' and not data.get('merge_confirmed'):
            candidate = _find_merge_candidate(real_name, tags, session['user_id'])
            if candidate:
                if candidate.get('line_user_id'):
                    return jsonify({'needs_contact_admin': True})
                return jsonify({
                    'needs_merge': True,
                    'candidate_id': candidate['id'],
                    'candidate_name': candidate['real_name'],
                    'candidate_tags': candidate.get('group_tags') or [],
                })

        supabase.table('users').update({
            'real_name': real_name,
            'group_tags': tags,
            'member_type': member_type,
        }).eq('id', session['user_id']).execute()

        session['real_name']   = real_name
        session['member_type'] = member_type
        session['group_tags']  = tags

        next_url = session.pop('next_url', None) or url_for('event.portal')
        return jsonify({'success': True, 'next': next_url})

    # 撈小組清單（含 is_primary 供 template 分區顯示）
    groups = supabase.table('groups').select('name, is_primary').order('sort_order').execute().data or []
    church_name = current_app.jinja_env.globals.get('church_name', '教會')
    return render_template('onboarding.html', groups=groups, church_name=church_name)


@profile_bp.route('/profile/merge-confirm', methods=['POST'])
@login_required
def merge_confirm():
    """會友自助合併：把新 LINE 帳號的身份移入既有手動帳號，刪除新帳號。"""
    data = request.get_json() or {}
    old_id = (data.get('candidate_id') or '').strip()   # 手動帳號（保留方）
    if not old_id:
        return jsonify({'error': '缺少目標帳號 ID'}), 400
    new_id = session['user_id']                          # 新 LINE 帳號（刪除方）
    if old_id == new_id:
        return jsonify({'error': '不能與自己合併'}), 400

    old_rows = supabase.table('users').select('*').eq('id', old_id).execute().data
    if not old_rows:
        return jsonify({'error': '找不到目標帳號'}), 404
    old_user = old_rows[0]
    if old_user.get('line_user_id'):
        return jsonify({'error': '該帳號已綁定其他 LINE，請聯繫管理員'}), 400

    new_rows = supabase.table('users').select('*').eq('id', new_id).execute().data
    if not new_rows:
        return jsonify({'error': '找不到目前帳號'}), 404
    new_user = new_rows[0]

    saved_line_user_id = new_user.get('line_user_id')
    saved_display_name = new_user.get('display_name')
    saved_picture_url  = new_user.get('picture_url')

    # ① 先清除新帳號的 line_user_id（UNIQUE 約束，必須先釋放）
    supabase.table('users').update({'line_user_id': None}).eq('id', new_id).execute()
    # ② 複製 LINE 身份到既有帳號
    try:
        supabase.table('users').update({
            'line_user_id': saved_line_user_id,
            'display_name': saved_display_name,
            'picture_url':  saved_picture_url,
        }).eq('id', old_id).execute()
    except Exception as e:
        # 還原，避免卡在中間狀態
        supabase.table('users').update({'line_user_id': saved_line_user_id}).eq('id', new_id).execute()
        return jsonify({'error': f'合併失敗：{e}'}), 500

    # ③ 移轉新帳號名下的關聯紀錄 → 既有帳號
    from routes.account_merge import transfer_user_records
    failed = transfer_user_records(new_id, old_id)

    # ④ 刪除新帳號
    try:
        supabase.table('users').delete().eq('id', new_id).execute()
    except Exception:
        logging.getLogger(__name__).warning('自助合併：刪除新帳號失敗', exc_info=True)

    # ⑤ session 改指向保留帳號（重新載入全部角色旗標）
    merged = supabase.table('users').select('*').eq('id', old_id).execute().data[0]
    from routes.auth import _populate_session
    _populate_session(merged)

    from routes.audit import log_action
    log_action('user.merge_line_self', 'user', old_id, {
        'merged_from': new_id, 'line_user_id': saved_line_user_id,
        'failed_tables': failed or None,
    })

    next_url = session.pop('next_url', None) or url_for('event.portal')
    return jsonify({'success': True, 'next': next_url})


@profile_bp.route('/profile/setup', methods=['GET', 'POST'])
@login_required
def setup():
    """第一次登入填寫個人資料"""
    if request.method == 'POST':
        data = request.get_json() or {}
        real_name = data.get('real_name', '').strip()
        if not real_name:
            return jsonify({'error': '請填寫真實姓名'}), 400

        member_type = data.get('member_type', 'member')
        if member_type not in ('member', 'visitor'):
            member_type = 'member'

        tags = [t for t in data.get('group_tags', []) if t] if member_type == 'member' else []

        # 自助合併偵測（與 onboarding 相同邏輯）
        if member_type == 'member' and not data.get('merge_confirmed'):
            candidate = _find_merge_candidate(real_name, tags, session['user_id'])
            if candidate:
                if candidate.get('line_user_id'):
                    return jsonify({'needs_contact_admin': True})
                return jsonify({
                    'needs_merge': True,
                    'candidate_id': candidate['id'],
                    'candidate_name': candidate['real_name'],
                    'candidate_tags': candidate.get('group_tags') or [],
                })

        supabase.table('users').update({
            'real_name': real_name,
            'group_tags': tags,
            'member_type': member_type,
        }).eq('id', session['user_id']).execute()

        session['real_name']    = real_name
        session['member_type']  = member_type
        session['group_tags']   = tags

        next_url = session.pop('next_url', None) or url_for('event.portal')
        return jsonify({'success': True, 'next': next_url})

    # 撈小組清單（含 is_primary 供 template 分區顯示）
    groups = supabase.table('groups').select('name, is_primary').order('sort_order').execute().data or []
    return render_template('profile/setup.html', groups=groups)


@profile_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def edit():
    """編輯個人資料"""
    uid = session['user_id']
    if request.method == 'POST':
        data = request.get_json() or {}
        action = data.get('action', 'save_profile')

        # ── 申請加入牧養小組 ────────────────────────────────────
        if action == 'request_cell_group':
            try:
                group_id = (data.get('cell_group_id') or '').strip()
                if not group_id:
                    return jsonify({'error': '請選擇小組'}), 400

                # 確認小組存在
                grp = supabase.table('cell_groups').select('id, name').eq('id', group_id).eq('is_active', True).execute().data
                if not grp:
                    return jsonify({'error': '找不到此小組'}), 404

                # 取得使用者姓名
                name = session.get('real_name') or session.get('display_name') or '未命名'

                # 若已有相同姓名＋小組的記錄，直接回傳（不依賴 user_id 欄位）
                existing = supabase.table('cell_members').select('id, is_confirmed')\
                    .eq('group_id', group_id).eq('name', name).eq('is_active', True).execute().data
                if existing:
                    status = '已在此小組' if existing[0].get('is_confirmed', True) else '申請已送出，等待管理員確認'
                    return jsonify({'success': True, 'message': status})

                # 建立待確認記錄，依序嘗試最完整到最精簡的欄位組合
                base_payload = {'group_id': group_id, 'name': name, 'is_active': True}
                inserted = False
                for payload in [
                    {**base_payload, 'user_id': uid, 'is_confirmed': False},
                    {**base_payload, 'is_confirmed': False},
                    base_payload,
                ]:
                    try:
                        supabase.table('cell_members').insert(payload).execute()
                        inserted = True
                        break
                    except Exception:
                        continue
                if not inserted:
                    return jsonify({'error': '寫入資料庫失敗，請聯絡管理員'})

                # 通知管理員
                try:
                    admins = supabase.table('users').select('id')\
                        .eq('is_super_admin', True).execute().data or []
                    if not admins:
                        admins = supabase.table('users').select('id')\
                            .eq('is_admin', True).execute().data or []
                    if admins:
                        from routes.notifications import batch_notify
                        batch_notify(
                            user_ids=[a['id'] for a in admins],
                            title=f'📋 小組申請 — {name}',
                            body=f'申請加入「{grp[0]["name"]}」，請至小組管理頁面確認。',
                            type='cell_group',
                            link='/admin/cell-groups',
                        )
                except Exception as e:
                    print(f'[profile] notify error: {e}')

                return jsonify({'success': True, 'message': '申請已送出，等待管理員確認'})
            except Exception as e:
                print(f'[profile] request_cell_group error: {e}')
                return jsonify({'error': str(e)})

        # ── 儲存一般個人資料 ────────────────────────────────────
        real_name = data.get('real_name', '').strip()
        if not real_name:
            return jsonify({'error': '請填寫真實姓名'}), 400

        tags = [t for t in data.get('group_tags', []) if t]
        supabase.table('users').update({
            'real_name': real_name,
            'group_tags': tags,
        }).eq('id', uid).execute()

        session['real_name'] = real_name
        return jsonify({'success': True})

    try:
        user_rows = supabase.table('users').select('*').eq('id', uid).execute().data
    except Exception:
        user_rows = []
    if not user_rows:
        flash('找不到使用者資料', 'error')
        return redirect(url_for('event.portal'))
    user = user_rows[0]

    try:
        groups = supabase.table('groups').select('name, is_primary').order('sort_order').execute().data or []
    except Exception:
        try:
            groups = supabase.table('groups').select('name, is_primary').execute().data or []
        except Exception:
            groups = []

    try:
        cell_groups = supabase.table('cell_groups').select('id, name').eq('is_active', True).order('name').execute().data or []
    except Exception:
        cell_groups = []

    my_cell_group_id = None
    my_cell_confirmed = None
    try:
        my_cell = supabase.table('cell_members').select('id, group_id, is_confirmed')\
            .eq('user_id', uid).eq('is_active', True).execute().data
        if my_cell:
            my_cell_group_id = my_cell[0]['group_id']
            my_cell_confirmed = my_cell[0]['is_confirmed']
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)

    pastors = []
    granted_map = {}
    try:
        from routes.diary import sb_list_pastors, sb_get_owner_grants
        pastors = sb_list_pastors()
        granted_ids = sb_get_owner_grants(session.get('line_id', ''))
        granted_map = {pid: True for pid in granted_ids}
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)

    return render_template('profile/edit.html',
        user=user, groups=groups,
        cell_groups=cell_groups,
        my_cell_group_id=my_cell_group_id,
        my_cell_confirmed=my_cell_confirmed,
        pastors=pastors, granted_map=granted_map,
    )


import json as _json


@profile_bp.route('/profile/homepage', methods=['GET', 'POST'])
def homepage_settings():
    if not session.get('user_id'):
        return redirect(url_for('auth.login_page'))
    from db import supabase
    import settings_store
    uid = session['user_id']

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        action = data.get('action', 'cards')
        if action == 'sections':
            # Save section-level show/hide preferences
            config = {'hidden': data.get('hidden', [])}
            settings_store.set(f'portal_sections_user_{uid}', _json.dumps(config))
        else:
            # Save portal card order + hidden (default action)
            config = {'order': data.get('order', []), 'hidden': data.get('hidden', [])}
            settings_store.set(f'portal_user_{uid}', _json.dumps(config))
        return jsonify({'success': True})

    # 7 sections the user can toggle
    SECTIONS = [
        {'key': 'hero',                  'label': 'Hero 橫幅',        'emoji': '🖼️'},
        {'key': 'cell_report_reminder',  'label': '小組回報提醒',     'emoji': '📋'},
        {'key': 'attendance_summary',    'label': '聚會人數總覽',     'emoji': '📊'},
        {'key': 'staff_review',          'label': '同工 / 牧者查閱',  'emoji': '🔍'},
        {'key': 'upcoming_events',       'label': '我的近期活動',     'emoji': '📅'},
        {'key': 'diary_widget',          'label': '靈修空間',         'emoji': '📖'},
        {'key': 'portal_cards',          'label': '更多功能（功能磚）','emoji': '🔲'},
        {'key': 'group_discussion',      'label': '小組討論',         'emoji': '💬'},
        {'key': 'weekly_info',           'label': '本週資訊',         'emoji': '📰'},
    ]

    # Load all active portal cards
    try:
        cards = supabase.table('portal_cards').select('key,name,emoji,subtitle,visible_to,is_active')\
            .eq('is_active', True).order('sort_order').execute().data or []
    except Exception:
        cards = []

    # Load user card config (order + hidden cards)
    raw = settings_store.get(f'portal_user_{uid}')
    config = _json.loads(raw) if raw else {}
    hidden_keys = config.get('hidden', [])
    order = config.get('order', [])

    # Fall back to group default for hidden cards if user has no personal setting
    group_hidden_keys = []
    if not raw:
        for gtag in (session.get('group_tags') or []):
            raw_grp = settings_store.get(f'portal_group_{gtag}')
            if raw_grp:
                try:
                    gcfg = _json.loads(raw_grp)
                    group_hidden_keys = gcfg.get('hidden', [])
                    hidden_keys = group_hidden_keys
                    break
                except Exception:
                    logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)

    # Sort cards by user order
    if order:
        order_map = {k: i for i, k in enumerate(order)}
        cards.sort(key=lambda c: order_map.get(c['key'], 999))

    # Load user section config
    raw_sec = settings_store.get(f'portal_sections_user_{uid}')
    sec_config = _json.loads(raw_sec) if raw_sec else {}
    hidden_sections = sec_config.get('hidden', [])

    return render_template('profile/homepage_settings.html',
        cards=cards, hidden_keys=hidden_keys,
        sections=SECTIONS, hidden_sections=hidden_sections)


@profile_bp.route('/profile/homepage/reset', methods=['POST'])
def homepage_settings_reset():
    if not session.get('user_id'):
        return jsonify({'success': False}), 401
    import settings_store
    settings_store.set(f'portal_user_{session["user_id"]}', '')
    return jsonify({'success': True})


@profile_bp.route('/admin/api/users/<user_id>/profile', methods=['POST'])
@login_required
def admin_edit_profile(user_id):
    """後台管理員修改任意用戶資料"""
    if not session.get('is_admin'):
        return jsonify({'error': '權限不足'}), 403
    data = request.get_json() or {}
    member_type = data.get('member_type', 'member')
    if member_type not in ('member', 'visitor'):
        member_type = 'member'
    tags = [t for t in data.get('group_tags', []) if t] if member_type == 'member' else []
    update = {
        'real_name': data.get('real_name', '').strip() or None,
        'group_tags': tags,
        'member_type': member_type,
    }
    supabase.table('users').update(update).eq('id', user_id).execute()
    return jsonify({'success': True})
