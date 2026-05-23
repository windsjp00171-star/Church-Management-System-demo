# 會員個人資料路由
from flask import Blueprint, session, redirect, url_for, render_template, request, jsonify, current_app, flash
from db import supabase
from routes.decorators import login_required

profile_bp = Blueprint('profile', __name__)


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
        supabase.table('users').update({
            'real_name': real_name,
            'group_tags': tags,
            'member_type': member_type,
        }).eq('id', session['user_id']).execute()

        session['real_name']    = real_name
        session['member_type']  = member_type

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
        pass

    pastors = []
    granted_map = {}
    try:
        from routes.diary import sb_list_pastors, sb_get_owner_grants
        pastors = sb_list_pastors()
        granted_ids = sb_get_owner_grants(session.get('line_id', ''))
        granted_map = {pid: True for pid in granted_ids}
    except Exception:
        pass

    return render_template('profile/edit.html',
        user=user, groups=groups,
        cell_groups=cell_groups,
        my_cell_group_id=my_cell_group_id,
        my_cell_confirmed=my_cell_confirmed,
        pastors=pastors, granted_map=granted_map,
    )


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
