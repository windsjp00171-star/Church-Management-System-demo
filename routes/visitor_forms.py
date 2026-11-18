import logging
from flask import Blueprint, session, request, jsonify, render_template, redirect, url_for
from db import supabase
from routes.decorators import login_required, admin_required
from datetime import datetime, timezone, timedelta
import uuid

visitor_forms_bp = Blueprint('visitor_forms', __name__)

TAIPEI_TZ = timezone(timedelta(hours=8))


@visitor_forms_bp.route('/visitor-form/upload', methods=['GET'])
@login_required
def upload_visitor_form_page():
    """同工上傳留名單的前端頁面"""
    uid = session['user_id']
    allowed = session.get('is_admin', False)
    if not allowed:
        try:
            user = supabase.table('users').select('group_tags').eq('id', uid).single().execute()
            tags = (user.data or {}).get('group_tags') or []
        except Exception:
            tags = []
        allowed = '同工' in tags
    if not allowed:
        return render_template('admin/forbidden.html'), 403
    return render_template('visitor_forms/upload.html')


@visitor_forms_bp.route('/visitor-form/upload', methods=['POST'])
@login_required
def upload_visitor_form():
    """同工上傳留名單照片"""
    uid = session['user_id']

    # 同工或管理員驗證
    if not session.get('is_admin'):
        try:
            user = supabase.table('users').select('group_tags').eq('id', uid).single().execute()
            tags = (user.data or {}).get('group_tags') or []
        except Exception:
            tags = []
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
    db_ok = True
    records = []
    try:
        records = supabase.table('visitor_forms')\
            .select('*')\
            .order('created_at', desc=True).execute().data or []

        # 批次取得上傳者姓名
        user_ids = list({r['uploaded_by'] for r in records if r.get('uploaded_by')})
        user_map = {}
        if user_ids:
            users = supabase.table('users').select('id, real_name, display_name')\
                .in_('id', user_ids).execute().data or []
            user_map = {u['id']: u for u in users}
        for r in records:
            r['_user'] = user_map.get(r.get('uploaded_by'), {})

        # 產生 signed URL（1 小時有效）
        for r in records:
            try:
                signed = supabase.storage.from_('visitor-forms')\
                    .create_signed_url(r['image_path'], 3600)
                r['signed_url'] = signed.get('signedURL') or signed.get('signedUrl') or ''
            except Exception:
                r['signed_url'] = ''
    except Exception as e:
        print(f'[visitor_forms admin] DB error: {e}')
        db_ok = False

    return render_template('admin/visitor_forms.html', records=records, db_ok=db_ok)


@visitor_forms_bp.route('/admin/visitor-forms/<record_id>/delete', methods=['POST'])
@admin_required
def admin_delete_visitor_form(record_id):
    """後台：刪除留名單"""
    row = supabase.table('visitor_forms').select('image_path').eq('id', record_id).execute()
    if row.data:
        try:
            supabase.storage.from_('visitor-forms').remove([row.data[0]['image_path']])
        except Exception:
            logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
        supabase.table('visitor_forms').delete().eq('id', record_id).execute()
    return jsonify({'success': True})
