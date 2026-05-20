# 會員個人資料路由
from flask import Blueprint, session, redirect, url_for, render_template, request, jsonify
from db import supabase
from routes.decorators import login_required

profile_bp = Blueprint('profile', __name__)


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

    user = supabase.table('users').select('*').eq('id', uid).execute().data[0]
    groups = supabase.table('groups').select('name, is_primary').order('sort_order').execute().data or []

    # 天父日記授權資料
    from routes.diary import sb_list_pastors, sb_get_owner_grants
    pastors = sb_list_pastors()
    granted_ids = sb_get_owner_grants(session.get('line_id', ''))
    granted_map = {pid: True for pid in granted_ids}

    return render_template('profile/edit.html', user=user, groups=groups, pastors=pastors, granted_map=granted_map)


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
