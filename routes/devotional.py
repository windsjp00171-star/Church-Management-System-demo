from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from db import supabase
from routes.decorators import login_required, admin_required
import datetime
import uuid as _uuid
import os

devotional_bp = Blueprint('devotional', __name__)


def _primary_groups():
    """回傳所有主標籤小組名稱清單（is_primary=True，依 sort_order 排序）"""
    res = supabase.table('groups').select('name').eq('is_primary', True).order('sort_order').execute()
    return [g['name'] for g in (res.data or [])]


def _detect_user_group(primary_names):
    """從 session group_tags 比對主標籤，回傳第一個符合的小組名稱，找不到回傳 None"""
    tags = session.get('group_tags') or []
    primary_set = set(primary_names)
    for t in tags:
        if t in primary_set:
            return t
    return None


def _regs_map(order_id):
    """回傳 {group_name: registration_row} for an order"""
    res = supabase.table('devotional_registrations').select('*').eq('order_id', order_id).execute()
    return {r['group_name']: r for r in (res.data or [])}


# ─────────────────────────────────────────────
# 前台
# ─────────────────────────────────────────────

@devotional_bp.get('/devotional')
@login_required
def devotional_list():
    today = datetime.date.today().isoformat()
    orders = supabase.table('devotional_orders')\
        .select('*').gte('deadline', today).order('deadline').execute().data or []
    return render_template('devotional/list.html', orders=orders, today=today)


@devotional_bp.get('/devotional/<order_id>')
@login_required
def devotional_detail(order_id):
    order = supabase.table('devotional_orders').select('*').eq('id', order_id).execute()
    if not order.data:
        flash('找不到訂購資料', 'error')
        return redirect(url_for('devotional.devotional_list'))
    order = order.data[0]

    primary_names = _primary_groups()
    user_group = _detect_user_group(primary_names)
    regs = _regs_map(order_id)
    today = datetime.date.today().isoformat()
    is_closed = order['deadline'] < today

    existing = regs.get(user_group) if user_group else None

    return render_template('devotional/detail.html',
                           order=order,
                           primary_names=primary_names,
                           user_group=user_group,
                           regs=regs,
                           existing=existing,
                           is_closed=is_closed,
                           today=today)


@devotional_bp.post('/devotional/<order_id>/register')
@login_required
def devotional_register(order_id):
    order = supabase.table('devotional_orders').select('id,deadline').eq('id', order_id).execute()
    if not order.data:
        return jsonify({'ok': False, 'msg': '找不到訂購'}), 404
    order = order.data[0]

    today = datetime.date.today().isoformat()
    if order['deadline'] < today:
        return jsonify({'ok': False, 'msg': '登記已截止'}), 400

    primary_names = _primary_groups()
    user_group = _detect_user_group(primary_names)
    if not user_group:
        return jsonify({'ok': False, 'msg': '找不到您的所屬小組'}), 400

    try:
        qty = int(request.form.get('quantity', 1))
        if qty < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'msg': '數量格式錯誤'}), 400
    notes = request.form.get('notes', '').strip()
    user_id = session.get('user_id')

    # upsert
    existing = supabase.table('devotional_registrations')\
        .select('id').eq('order_id', order_id).eq('group_name', user_group).execute()

    if existing.data:
        supabase.table('devotional_registrations').update({
            'quantity': qty, 'notes': notes, 'registered_by': user_id
        }).eq('id', existing.data[0]['id']).execute()
    else:
        supabase.table('devotional_registrations').insert({
            'order_id': order_id, 'group_name': user_group,
            'quantity': qty, 'notes': notes, 'registered_by': user_id
        }).execute()

    # 寫修改履歷
    supabase.table('devotional_registration_logs').insert({
        'order_id': order_id, 'group_name': user_group,
        'quantity': qty, 'notes': notes, 'changed_by': user_id
    }).execute()

    return jsonify({'ok': True, 'group_name': user_group, 'quantity': qty})


# ─────────────────────────────────────────────
# 後台
# ─────────────────────────────────────────────

@devotional_bp.get('/admin/devotional')
@admin_required
def admin_devotional_list():
    orders = supabase.table('devotional_orders').select('*').order('created_at', desc=True).execute().data or []
    today = datetime.date.today().isoformat()
    return render_template('devotional/admin_list.html', orders=orders, today=today)


@devotional_bp.post('/admin/devotional/new')
@admin_required
def admin_devotional_new():
    scripture = request.form.get('scripture', '').strip()
    author    = request.form.get('author', '').strip() or None
    price     = int(request.form.get('price', 0))
    deadline  = request.form.get('deadline', '')
    if not scripture or not deadline:
        flash('請填寫經卷與截止日', 'error')
        return redirect(url_for('devotional.admin_devotional_list'))
    supabase.table('devotional_orders').insert({
        'scripture': scripture, 'author': author,
        'price': price, 'deadline': deadline
    }).execute()
    flash(f'已新增《{scripture}》訂購', 'success')
    return redirect(url_for('devotional.admin_devotional_list'))


@devotional_bp.get('/admin/devotional/<order_id>')
@admin_required
def admin_devotional_detail(order_id):
    order = supabase.table('devotional_orders').select('*').eq('id', order_id).execute()
    if not order.data:
        flash('找不到訂購資料', 'error')
        return redirect(url_for('devotional.admin_devotional_list'))
    order = order.data[0]

    primary_names = _primary_groups()
    regs = _regs_map(order_id)

    registered_count = len(regs)
    total_qty = sum(r['quantity'] for r in regs.values())
    delivered_count = sum(1 for r in regs.values() if r.get('is_delivered'))
    total_amount = total_qty * order['price']

    confirmed_user_ids = list({r['confirmed_by'] for r in regs.values() if r.get('confirmed_by')})
    confirmed_name_map = {}
    if confirmed_user_ids:
        users = supabase.table('users').select('id,real_name')\
            .in_('id', confirmed_user_ids).execute().data or []
        confirmed_name_map = {u['id']: u['real_name'] for u in users}
    for r in regs.values():
        r['confirmed_name'] = confirmed_name_map.get(r.get('confirmed_by'), '')

    return render_template('devotional/admin_detail.html',
                           order=order,
                           primary_names=primary_names,
                           regs=regs,
                           registered_count=registered_count,
                           total_qty=total_qty,
                           delivered_count=delivered_count,
                           total_amount=total_amount)


@devotional_bp.post('/admin/devotional/<order_id>/register')
@admin_required
def admin_devotional_register(order_id):
    order = supabase.table('devotional_orders').select('id').eq('id', order_id).execute()
    if not order.data:
        return jsonify({'ok': False, 'msg': '找不到訂購'}), 404

    group_name = request.form.get('group_name', '').strip()
    qty_str = request.form.get('quantity', '').strip()
    notes = request.form.get('notes', '').strip()

    if not group_name:
        return jsonify({'ok': False, 'msg': '請選擇小組'}), 400
    try:
        qty = int(qty_str)
        if qty < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'msg': '數量格式錯誤'}), 400

    user_id = session.get('user_id')

    existing = supabase.table('devotional_registrations')\
        .select('id').eq('order_id', order_id).eq('group_name', group_name).execute()

    if existing.data:
        supabase.table('devotional_registrations').update({
            'quantity': qty, 'notes': notes
        }).eq('id', existing.data[0]['id']).execute()
    else:
        supabase.table('devotional_registrations').insert({
            'order_id': order_id, 'group_name': group_name,
            'quantity': qty, 'notes': notes, 'registered_by': user_id
        }).execute()

    supabase.table('devotional_registration_logs').insert({
        'order_id': order_id, 'group_name': group_name,
        'quantity': qty, 'notes': notes, 'changed_by': user_id
    }).execute()

    return jsonify({'ok': True})


@devotional_bp.post('/admin/devotional/<order_id>/delete')
@admin_required
def admin_devotional_delete(order_id):
    supabase.table('devotional_orders').delete().eq('id', order_id).execute()
    flash('已刪除訂購', 'success')
    return redirect(url_for('devotional.admin_devotional_list'))


@devotional_bp.get('/admin/devotional/<order_id>/logs')
@admin_required
def admin_devotional_logs(order_id):
    logs = supabase.table('devotional_registration_logs')\
        .select('group_name, quantity, notes, changed_at, users(real_name)')\
        .eq('order_id', order_id)\
        .order('changed_at', desc=True).execute().data or []
    result = []
    for l in logs:
        user_info = l.get('users') or {}
        result.append({
            'group_name': l['group_name'],
            'quantity': l['quantity'],
            'notes': l.get('notes') or '',
            'changed_by': user_info.get('real_name') or '—',
            'changed_at': l['changed_at'][:16].replace('T', ' '),
        })
    return jsonify(result)


@devotional_bp.get('/admin/devotional/<order_id>/print')
@admin_required
def admin_devotional_print(order_id):
    order = supabase.table('devotional_orders').select('*').eq('id', order_id).execute()
    if not order.data:
        return '找不到資料', 404
    order = order.data[0]
    primary_names = _primary_groups()
    regs = _regs_map(order_id)
    total_qty = sum(r['quantity'] for r in regs.values())
    return render_template('devotional/print.html',
                           order=order,
                           primary_names=primary_names,
                           regs=regs,
                           total_qty=total_qty)


@devotional_bp.post('/admin/devotional/registrations/<reg_id>/deliver')
@admin_required
def admin_devotional_deliver(reg_id):
    reg = supabase.table('devotional_registrations').select('is_delivered, order_id').eq('id', reg_id).execute()
    if not reg.data:
        return jsonify({'ok': False}), 404
    new_val = not reg.data[0]['is_delivered']
    body = request.get_json() or {}
    update = {'is_delivered': new_val}
    if new_val:
        update['confirmed_at'] = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
        update['confirmed_by'] = session.get('user_id')
        update['pickup_note'] = (body.get('pickup_note') or '').strip() or None
    else:
        update['confirmed_at'] = None
        update['confirmed_by'] = None
        update['pickup_note'] = None
    supabase.table('devotional_registrations').update(update).eq('id', reg_id).execute()
    return jsonify({'ok': True, 'is_delivered': new_val})


@devotional_bp.route('/devotional/<order_id>/pickup', methods=['GET', 'POST'])
@login_required
def devotional_pickup(order_id):
    order = supabase.table('devotional_orders').select('*').eq('id', order_id).execute()
    if not order.data:
        return redirect('/devotional')
    order = order.data[0]
    primary_names = _primary_groups()
    my_group = _detect_user_group(primary_names)
    reg_data = None
    if my_group:
        res = supabase.table('devotional_registrations').select('*')\
            .eq('order_id', order_id).eq('group_name', my_group).execute()
        reg_data = res.data[0] if res.data else None
    if request.method == 'POST':
        if not my_group:
            return jsonify({'error': '無法取得您的小組資訊'}), 400
        if not reg_data or reg_data.get('quantity', 0) == 0:
            return jsonify({'error': '您的小組尚未登記此訂購'}), 400
        if reg_data.get('is_delivered'):
            return jsonify({'error': '已簽收'}), 400
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
        supabase.table('devotional_registrations').update({
            'is_delivered': True,
            'confirmed_at': now,
            'confirmed_by': session.get('user_id'),
            'pickup_note': session.get('real_name', ''),
        }).eq('id', reg_data['id']).execute()
        return jsonify({'success': True})
    return render_template('devotional/pickup.html',
        order=order, my_group=my_group, my_reg=reg_data,
        real_name=session.get('real_name', ''))


@devotional_bp.post('/admin/devotional/<order_id>/upload-cover')
@admin_required
def admin_devotional_upload_cover(order_id):
    """上傳封面圖片到 Supabase Storage（bucket: event-posters）"""
    order = supabase.table('devotional_orders').select('id').eq('id', order_id).execute()
    if not order.data:
        return jsonify({'ok': False, 'msg': '找不到訂購'}), 404

    f = request.files.get('cover')
    if not f or not f.filename:
        return jsonify({'ok': False, 'msg': '請選擇圖片'}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
        return jsonify({'ok': False, 'msg': '僅支援 jpg/png/webp/gif'}), 400

    filename = f'devotional-covers/{_uuid.uuid4()}{ext}'
    content_type_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif',
    }
    content_type = content_type_map.get(ext, 'image/jpeg')

    try:
        file_bytes = f.read()
        supabase.storage.from_('event-posters').upload(
            filename, file_bytes, {'content-type': content_type}
        )
        url = supabase.storage.from_('event-posters').get_public_url(filename)
        supabase.table('devotional_orders').update({'cover_url': url}).eq('id', order_id).execute()
        return jsonify({'ok': True, 'url': url})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@devotional_bp.post('/admin/devotional/registrations/<reg_id>/delete')
@admin_required
def admin_devotional_reg_delete(reg_id):
    reg = supabase.table('devotional_registrations').select('order_id').eq('id', reg_id).execute()
    if not reg.data:
        return jsonify({'ok': False}), 404
    order_id = reg.data[0]['order_id']
    supabase.table('devotional_registrations').delete().eq('id', reg_id).execute()
    return jsonify({'ok': True, 'order_id': order_id})
