from flask import Blueprint, session, request, jsonify, render_template, redirect, url_for
from functools import wraps
from db import supabase
from datetime import datetime, timezone, timedelta
import uuid, io

visitor_forms_bp = Blueprint('visitor_forms', __name__)

TAIPEI_TZ = timezone(timedelta(hours=8))


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('auth.login_page'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return '無權限', 403
        return f(*args, **kwargs)
    return decorated


def coworker_required(f):
    """同工或管理員才可存取"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('auth.login_page'))
        if session.get('is_admin'):
            return f(*args, **kwargs)
        uid = session['user_id']
        user = supabase.table('users').select('group_tags').eq('id', uid).single().execute()
        tags = (user.data or {}).get('group_tags') or []
        if '同工' not in tags:
            return jsonify({'error': '無同工權限'}), 403
        return f(*args, **kwargs)
    return decorated


@visitor_forms_bp.route('/visitor-form/upload', methods=['POST'])
@login_required
def upload_visitor_form():
    """同工上傳留名單照片"""
    uid = session['user_id']

    # 同工或管理員驗證
    if not session.get('is_admin'):
        user = supabase.table('users').select('group_tags').eq('id', uid).single().execute()
        tags = (user.data or {}).get('group_tags') or []
        if '同工' not in tags:
            return jsonify({'error': '無同工權限'}), 403

    file = request.files.get('image')
    if not file:
        return jsonify({'error': '請選擇圖片'}), 400

    # 副檔名
    ext = (file.filename or '').rsplit('.', 1)[-1].lower()
    if ext not in {'jpg', 'jpeg', 'png', 'webp', 'heic', 'heif'}:
        ext = 'jpg'

    path = f"{datetime.now(TAIPEI_TZ).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}.{ext}"
    file_bytes = file.read()

    # 上傳到 Supabase Storage
    try:
        supabase.storage.from_('visitor-forms').upload(
            path, file_bytes,
            file_options={'content-type': file.mimetype or 'image/jpeg'}
        )
    except Exception as e:
        return jsonify({'error': f'上傳失敗：{e}'}), 500

    # 儲存記錄
    notes = (request.form.get('notes') or '').strip() or None

    supabase.table('visitor_forms').insert({
        'image_path':  path,
        'notes':       notes,
        'uploaded_by': uid,
    }).execute()

    return jsonify({'success': True})


@visitor_forms_bp.route('/admin/visitor-forms')
@admin_required
def admin_visitor_forms():
    """後台：留名單列表"""
    records = supabase.table('visitor_forms')\
        .select('*, users(real_name, display_name)')\
        .order('created_at', desc=True).execute().data or []

    # 產生 signed URL（1 小時有效）
    for r in records:
        try:
            signed = supabase.storage.from_('visitor-forms')\
                .create_signed_url(r['image_path'], 3600)
            r['signed_url'] = signed.get('signedURL') or signed.get('signedUrl') or ''
        except Exception:
            r['signed_url'] = ''

    return render_template('admin/visitor_forms.html', records=records)


@visitor_forms_bp.route('/admin/visitor-forms/<record_id>/delete', methods=['POST'])
@admin_required
def admin_delete_visitor_form(record_id):
    """後台：刪除留名單"""
    row = supabase.table('visitor_forms').select('image_path').eq('id', record_id).execute()
    if row.data:
        try:
            supabase.storage.from_('visitor-forms').remove([row.data[0]['image_path']])
        except Exception:
            pass
        supabase.table('visitor_forms').delete().eq('id', record_id).execute()
    return jsonify({'success': True})
