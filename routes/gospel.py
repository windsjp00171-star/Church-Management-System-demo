# 福音探索系統路由
from flask import Blueprint, render_template, request, session, jsonify
from db import supabase

gospel_bp = Blueprint('gospel', __name__)

STATUS_LABELS = {
    'pending':   '⏳ 待跟進',
    'following': '🤝 跟進中',
    'done':      '✅ 已完成',
}

# ── 公開頁面（不需登入）────────────────────────────────
@gospel_bp.route('/gospel')
def index():
    try:
        cards = supabase.table('gospel_cards')\
            .select('*').eq('is_active', True)\
            .order('sort_order').execute().data or []
    except Exception:
        cards = []
    try:
        form_questions = supabase.table('gospel_form_questions')\
            .select('*').eq('is_active', True)\
            .order('sort_order').execute().data or []
    except Exception:
        form_questions = []
    return render_template('gospel/index.html', cards=cards, form_questions=form_questions)


# ── 送出詢問表單（不需登入）────────────────────────────────
@gospel_bp.route('/gospel/inquiry', methods=['POST'])
def inquiry():
    data = request.get_json() or {}
    name    = (data.get('name') or '').strip()
    contact = (data.get('contact') or '').strip()
    message = (data.get('message') or '').strip()

    if not name or not contact:
        return jsonify({'success': False, 'error': '請填寫姓名與聯絡方式'})

    extra = data.get('extra_answers') or {}

    try:
        supabase.table('gospel_inquiries').insert({
            'name': name,
            'contact': contact,
            'message': message or None,
            'extra_answers': extra if extra else None,
            'status': 'pending',
        }).execute()

        # 通知所有超管
        try:
            admins = supabase.table('users')\
                .select('id').eq('is_super_admin', True).execute().data or []
            if admins:
                from routes.notifications import batch_notify
                batch_notify(
                    user_ids=[a['id'] for a in admins],
                    title=f'✝️ 新的福音詢問 — {name}',
                    body=f'聯絡方式：{contact}' + (f'\n留言：{message}' if message else ''),
                    type='gospel',
                    link='/admin/gospel',
                )
        except Exception as e:
            print(f'[gospel] notify error: {e}')

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 後台：詢問名單 ────────────────────────────────
@gospel_bp.route('/admin/gospel')
def admin_index():
    if not session.get('user_id'):
        return jsonify({'error': '請先登入'}), 401
    if not (session.get('is_super_admin') or session.get('is_admin')):
        return render_template('admin/forbidden.html'), 403

    status_filter = request.args.get('status', 'all')
    try:
        q = supabase.table('gospel_inquiries').select('*').order('created_at', desc=True)
        if status_filter != 'all':
            q = q.eq('status', status_filter)
        inquiries = q.execute().data or []

        # 取得小組長清單（管理員）供指派
        leaders = supabase.table('users')\
            .select('id,real_name,display_name')\
            .eq('is_admin', True).execute().data or []

        # 補上指派者名稱
        leader_map = {l['id']: l.get('real_name') or l.get('display_name') for l in leaders}
        for inq in inquiries:
            inq['assigned_name'] = leader_map.get(inq.get('assigned_to'), '')
            inq['status_label'] = STATUS_LABELS.get(inq['status'], inq['status'])

        # 各狀態數量
        all_inq = supabase.table('gospel_inquiries').select('status').execute().data or []
        counts = {'all': len(all_inq), 'pending': 0, 'following': 0, 'done': 0}
        for row in all_inq:
            counts[row['status']] = counts.get(row['status'], 0) + 1

    except Exception as e:
        inquiries, leaders, counts = [], [], {'all': 0, 'pending': 0, 'following': 0, 'done': 0}
        print(f'[gospel] admin error: {e}')

    return render_template('gospel/admin.html',
        inquiries=inquiries,
        leaders=leaders,
        status_filter=status_filter,
        counts=counts,
        status_labels=STATUS_LABELS,
    )


# ── 後台：更新狀態 / 指派 / 備註 ────────────────────────────────
@gospel_bp.route('/admin/gospel/<inq_id>/update', methods=['POST'])
def admin_update(inq_id):
    if not session.get('user_id'):
        return jsonify({'success': False}), 401
    if not (session.get('is_super_admin') or session.get('is_admin')):
        return jsonify({'success': False, 'error': '無權限'}), 403

    data = request.get_json() or {}
    update = {}
    if 'status' in data and data['status'] in STATUS_LABELS:
        update['status'] = data['status']
    if 'assigned_to' in data:
        update['assigned_to'] = data['assigned_to'] or None
    if 'notes' in data:
        update['notes'] = data['notes']
    if not update:
        return jsonify({'success': False, 'error': '沒有要更新的資料'})

    update['updated_at'] = 'now()'
    try:
        supabase.table('gospel_inquiries').update(update).eq('id', inq_id).execute()

        # 若指派給小組長，發通知
        if 'assigned_to' in data and data['assigned_to']:
            from routes.notifications import create_notification
            inq = supabase.table('gospel_inquiries')\
                .select('name,contact').eq('id', inq_id).single().execute().data or {}
            create_notification(
                user_id=data['assigned_to'],
                title=f'🤝 福音關懷指派 — {inq.get("name", "")}',
                body=f'聯絡方式：{inq.get("contact", "")}',
                type='gospel',
                link='/admin/gospel',
            )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 後台：刪除詢問 ────────────────────────────────
@gospel_bp.route('/admin/gospel/<inq_id>/delete', methods=['POST'])
def admin_delete(inq_id):
    if not session.get('user_id') or not session.get('is_super_admin'):
        return jsonify({'success': False, 'error': '無權限'}), 403
    try:
        supabase.table('gospel_inquiries').delete().eq('id', inq_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 後台：卡片管理 ────────────────────────────────
@gospel_bp.route('/admin/gospel/cards')
def admin_cards():
    if not session.get('is_super_admin'):
        return render_template('admin/forbidden.html'), 403
    cards = supabase.table('gospel_cards').select('*').order('sort_order').execute().data or []
    return render_template('gospel/admin_cards.html', cards=cards)


@gospel_bp.route('/admin/gospel/cards/create', methods=['POST'])
def admin_card_create():
    if not session.get('is_super_admin'):
        return jsonify({'success': False}), 403
    data = request.get_json() or {}
    question = (data.get('question') or '').strip()
    answer   = (data.get('answer') or '').strip()
    if not question or not answer:
        return jsonify({'success': False, 'error': '問題與答案不能空白'})
    icon = (data.get('icon') or '✝️').strip() or '✝️'
    try:
        max_order = supabase.table('gospel_cards').select('sort_order').order('sort_order', desc=True).limit(1).execute().data
        next_order = (max_order[0]['sort_order'] + 1) if max_order else 1
        supabase.table('gospel_cards').insert({
            'question': question,
            'answer': answer,
            'icon': icon,
            'sort_order': next_order,
            'is_active': True,
        }).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@gospel_bp.route('/admin/gospel/cards/<card_id>/update', methods=['POST'])
def admin_card_update(card_id):
    if not session.get('is_super_admin'):
        return jsonify({'success': False}), 403
    data = request.get_json() or {}
    update = {}
    if 'question' in data: update['question'] = data['question']
    if 'answer'   in data: update['answer']   = data['answer']
    if 'icon'     in data: update['icon']     = data['icon']
    if 'is_active' in data: update['is_active'] = bool(data['is_active'])
    try:
        supabase.table('gospel_cards').update(update).eq('id', card_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 後台：自訂表單問題管理 ────────────────────────────────
@gospel_bp.route('/admin/gospel/form-questions')
def admin_form_questions():
    if not session.get('is_admin'):
        return render_template('admin/forbidden.html'), 403
    try:
        questions = supabase.table('gospel_form_questions')\
            .select('*').order('sort_order').execute().data or []
    except Exception as e:
        print(f'[gospel] form_questions error: {e}')
        questions = []
    return render_template('gospel/admin_form_questions.html', questions=questions)


@gospel_bp.route('/admin/gospel/form-questions/save', methods=['POST'])
def admin_form_questions_save():
    if not session.get('is_admin'):
        return jsonify({'error': '無權限'}), 403
    data = request.get_json() or {}
    action = data.get('action')

    if action == 'create':
        supabase.table('gospel_form_questions').insert({
            'label':       data.get('label', '').strip(),
            'placeholder': data.get('placeholder', '').strip(),
            'is_textarea': bool(data.get('is_textarea', False)),
            'is_required': bool(data.get('is_required', False)),
            'sort_order':  int(data.get('sort_order', 0)),
            'is_active':   True,
        }).execute()
        return jsonify({'success': True})

    if action == 'update':
        qid = data.get('id')
        if not qid:
            return jsonify({'error': '缺少 id'}), 400
        update = {}
        for f in ('label', 'placeholder', 'is_textarea', 'is_required', 'sort_order', 'is_active'):
            if f in data:
                update[f] = data[f]
        supabase.table('gospel_form_questions').update(update).eq('id', qid).execute()
        return jsonify({'success': True})

    if action == 'delete':
        qid = data.get('id')
        if not qid:
            return jsonify({'error': '缺少 id'}), 400
        supabase.table('gospel_form_questions').delete().eq('id', qid).execute()
        return jsonify({'success': True})

    return jsonify({'error': '未知 action'}), 400
