import logging
import uuid
import os
from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, abort, g, current_app, Response
import requests as http_requests
import bcrypt
from werkzeug.utils import secure_filename
from db import supabase
import settings_store
from storage import upload_file, get_presigned_url, delete_file
from routes.notifications import create_notification
from extensions import limiter

logger = logging.getLogger(__name__)
files_bp = Blueprint('files', __name__)

ALLOWED_ROLES = {'admin', 'pastor', 'accountant', 'ppt'}

ROLE_LABELS = {
    'admin': '管理員',
    'pastor': '牧者',
    'accountant': '會計',
    'ppt': 'PPT同工',
    'pending': '待審核',
}

VISIBILITY_LABELS = {
    'private': '只有我',
    'public': '所有同工',
    'users': '指定使用者',
    'groups': '指定分組',
    'roles': '指定角色',
    'management': '管理層',
}

PREVIEWABLE = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.webm'}
OFFICE_PREVIEW = {'.ppt', '.pptx', '.doc', '.docx', '.xls', '.xlsx'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

# 允許上傳的副檔名白名單
ALLOWED_EXTENSIONS = {
    # 文件
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.odt', '.ods', '.odp', '.txt', '.rtf', '.csv',
    # 圖片
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif',
    # 影音
    '.mp4', '.mov', '.mp3', '.m4a', '.wav',
    # 壓縮
    '.zip', '.7z',
}

MAX_FILENAME_LEN = 200


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('auth.login_page'))
        if session.get('is_blocked'):
            session.clear()
            return render_template('blocked.html')
        if session.get('role') == 'pending':
            return render_template('pending.html')
        return f(*args, **kwargs)
    return decorated


def _get_user_group_ids():
    """取得當前用戶所屬群組 ID 集合，每個 request 只查一次 DB。"""
    if not hasattr(g, 'user_group_ids'):
        user_id = session.get('user_id')
        res = supabase.table('group_members').select('group_id').eq('user_id', user_id).execute()
        g.user_group_ids = {r['group_id'] for r in (res.data or [])}
    return g.user_group_ids


def _can_access_file(file_record):
    role = session.get('role')
    user_id = session.get('user_id')
    if role == 'admin':
        return True
    if file_record.get('owner_id') == user_id:
        return True
    visibility = file_record.get('visibility', 'private')
    if visibility == 'public':
        return True
    if visibility == 'management' and role in {'admin', 'pastor'}:
        return True
    if role in (file_record.get('allowed_roles') or []):
        return True
    if user_id in (file_record.get('allowed_users') or []):
        return True
    allowed_groups = file_record.get('allowed_groups') or []
    if allowed_groups and _get_user_group_ids() & set(allowed_groups):
        return True
    return False


def _can_access_folder(folder_record):
    role = session.get('role')
    user_id = session.get('user_id')
    if role == 'admin':
        return True
    if folder_record.get('created_by') == user_id:
        return True
    visibility = folder_record.get('visibility', 'private')
    if visibility == 'public':
        return True
    if visibility == 'management' and role in {'admin', 'pastor'}:
        return True
    if role in (folder_record.get('allowed_roles') or []):
        return True
    if visibility == 'users' and user_id in (folder_record.get('allowed_users') or []):
        return True
    if visibility == 'groups':
        allowed_groups = folder_record.get('allowed_groups') or []
        if allowed_groups and _get_user_group_ids() & set(allowed_groups):
            return True
    return False


def _format_size(size_bytes):
    if size_bytes is None:
        return ''
    if size_bytes < 1024:
        return f'{size_bytes} B'
    if size_bytes < 1024 * 1024:
        return f'{size_bytes / 1024:.1f} KB'
    if size_bytes < 1024 * 1024 * 1024:
        return f'{size_bytes / (1024 * 1024):.1f} MB'
    return f'{size_bytes / (1024 * 1024 * 1024):.2f} GB'


def _get_total_storage():
    res = supabase.table('files').select('file_size').execute()
    return sum(r.get('file_size') or 0 for r in (res.data or []))


def _get_storage_limit():
    return settings_store.get_max_storage_bytes()


@files_bp.route('/files')
@login_required
def index():
    from storage import r2_configured
    if not r2_configured():
        return render_template('files/unavailable.html'), 503

    folder_id = request.args.get('folder_id')
    q = request.args.get('q', '').strip()
    role = session.get('role')

    folders_q = supabase.table('folders').select('*')
    if folder_id:
        folders_q = folders_q.eq('parent_id', folder_id)
    else:
        folders_q = folders_q.is_('parent_id', 'null')

    if role != 'admin':
        folders_q = folders_q.or_(
            f'visibility.eq.public,visibility.eq.management,allowed_roles.cs.{{"{role}"}},created_by.eq.{session["user_id"]}'
        )
    folders = folders_q.order('name').execute().data or []

    if q:
        files_q = supabase.table('files').select('*').ilike('name', f'%{q}%')
        folders = [f for f in folders if q.lower() in f['name'].lower()]
    else:
        files_q = supabase.table('files').select('*')
        if folder_id:
            files_q = files_q.eq('folder_id', folder_id)
        else:
            files_q = files_q.is_('folder_id', 'null')
    all_files = files_q.order('created_at', desc=True).execute().data or []
    files = [f for f in all_files if _can_access_file(f)]

    # 批次取上傳者姓名
    uploader_ids = list({f['uploaded_by'] for f in files if f.get('uploaded_by')})
    uploader_map = {}
    if uploader_ids:
        up_users = supabase.table('users').select('id, display_name')\
            .in_('id', uploader_ids).execute().data or []
        uploader_map = {u['id']: u['display_name'] for u in up_users}

    # 圖片縮圖 URL（本地簽名，無網路請求）
    for f in files:
        ext = os.path.splitext(f['name'])[1].lower()
        f['thumb_url'] = get_presigned_url(f['file_key'], expires=3600) if ext in IMAGE_EXTS else None
        f['size_label'] = _format_size(f.get('file_size'))
        f['uploader'] = uploader_map.get(f.get('uploaded_by'), '')

    current_folder = None
    if folder_id:
        res = supabase.table('folders').select('*').eq('id', folder_id).execute()
        current_folder = res.data[0] if res.data else None

    all_users = supabase.table('users').select('id, display_name, role') \
        .not_.eq('role', 'pending') \
        .eq('is_blocked', False) \
        .neq('id', session['user_id']) \
        .order('display_name').execute().data or []

    all_groups = supabase.table('user_groups').select('id, name') \
        .order('name').execute().data or []

    # 儲存空間資訊（僅 admin 使用）
    storage_info = None
    if session.get('is_admin'):
        used = _get_total_storage()
        limit = _get_storage_limit()
        storage_info = {
            'used': used,
            'limit': limit,
            'used_label': _format_size(used),
            'limit_label': _format_size(limit),
            'pct': min(100, round(used / limit * 100)) if limit else 0,
        }

    return render_template('files/index.html',
                           folders=folders,
                           files=files,
                           current_folder=current_folder,
                           folder_id=folder_id,
                           role_labels=ROLE_LABELS,
                           visibility_labels=VISIBILITY_LABELS,
                           all_users=all_users,
                           all_groups=all_groups,
                           current_user=session['user_id'],
                           q=q,
                           is_admin=session.get('is_admin'),
                           user_role=role,
                           storage_info=storage_info)


@files_bp.route('/files/upload', methods=['POST'])
@login_required
@limiter.limit('30 per hour')
def upload():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': '請選擇檔案'}), 400

    # 清理並驗證檔名
    original_name = f.filename
    safe_stem = secure_filename(os.path.splitext(original_name)[0]) or 'file'
    ext = os.path.splitext(original_name)[1].lower()
    if not ext or ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': f'不支援的檔案類型（{ext or "無副檔名"}）'}), 400
    safe_name = safe_stem[:MAX_FILENAME_LEN] + ext

    # 讀取檔案大小
    f.seek(0, 2)
    file_size = f.tell()
    f.seek(0)

    # 檢查單檔大小（上限 500 MB）
    if file_size > 500 * 1024 * 1024:
        return jsonify({'error': f'單檔最大 500 MB，此檔案為 {_format_size(file_size)}'}), 400

    # 檢查總儲存空間
    try:
        used = _get_total_storage()
        limit = _get_storage_limit()
    except Exception:
        return jsonify({'error': '無法讀取儲存空間資訊，請稍後再試'}), 500
    if used + file_size > limit:
        remaining = _format_size(max(0, limit - used))
        return jsonify({'error': f'儲存空間不足，剩餘 {remaining}，請聯繫管理員清理空間'}), 400

    folder_id = request.form.get('folder_id') or None
    visibility = request.form.get('visibility', 'private')
    allowed_roles = request.form.getlist('allowed_roles')
    allowed_users = request.form.getlist('allowed_users')
    allowed_groups = request.form.getlist('allowed_groups')
    protection = request.form.get('protection', 'none')
    password = request.form.get('password', '')

    file_key = f'files/{uuid.uuid4()}{ext}'
    content_type = f.content_type or 'application/octet-stream'

    try:
        upload_file(f, file_key, content_type)
    except Exception:
        logger.exception('R2 upload failed: %s', safe_name)
        return jsonify({'error': '檔案上傳至儲存空間失敗，請稍後再試'}), 500

    password_hash = None
    if protection == 'password' and password:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    record = {
        'name': safe_name,
        'file_key': file_key,
        'content_type': content_type,
        'file_size': file_size,
        'folder_id': folder_id,
        'owner_id': session['user_id'],
        'visibility': visibility,
        'allowed_roles': allowed_roles if allowed_roles else None,
        'allowed_users': allowed_users if allowed_users else None,
        'allowed_groups': allowed_groups if allowed_groups else None,
        'protection': protection,
        'password_hash': password_hash,
    }
    try:
        result = supabase.table('files').insert(record).execute()
        file_id = result.data[0]['id'] if result.data else None
    except Exception:
        # DB 寫入失敗，清掉已傳到 R2 的孤兒檔
        try:
            delete_file(file_key)
        except Exception:
            pass
        return jsonify({'error': '資料庫寫入失敗，請稍後再試'}), 500

    # 上傳後通知指定對象（失敗不影響上傳結果）
    if file_id:
        try:
            _notify_file_shared(file_id, safe_name, visibility, allowed_users, allowed_groups)
        except Exception:
            pass
        logger.info('上傳成功 file=%s size=%d user=%s', safe_name, file_size, session.get('user_id', '')[:8])

    return jsonify({'success': True, 'file_id': file_id})


def _notify_file_shared(file_id, filename, visibility, allowed_users, allowed_groups):
    uploader = session.get('display_name', '同工')
    title = f'{uploader} 分享了「{filename}」給你'
    link = f'/files/{file_id}/view'
    notify_ids = set()

    if visibility == 'users' and allowed_users:
        notify_ids.update(allowed_users)

    if visibility == 'groups' and allowed_groups:
        res = supabase.table('group_members').select('user_id') \
            .in_('group_id', allowed_groups).execute()
        for r in (res.data or []):
            notify_ids.add(r['user_id'])

    # 排除自己
    notify_ids.discard(session.get('user_id'))

    for uid in notify_ids:
        create_notification(uid, 'file_shared', title, body='點擊查看文件', link=link)


@files_bp.route('/files/<file_id>/rename', methods=['POST'])
@login_required
def rename_file(file_id):
    res = supabase.table('files').select('owner_id').eq('id', file_id).execute()
    if not res.data:
        abort(404)
    if res.data[0]['owner_id'] != session['user_id'] and not session.get('is_admin'):
        abort(403)
    new_name = request.form.get('name', '').strip()
    if not new_name:
        return jsonify({'error': '請輸入檔名'}), 400
    supabase.table('files').update({'name': new_name}).eq('id', file_id).execute()
    return jsonify({'success': True})


@files_bp.route('/files/<file_id>/view')
@login_required
def view_file(file_id):
    res = supabase.table('files').select('*').eq('id', file_id).execute()
    if not res.data:
        abort(404)
    file_record = res.data[0]

    if not _can_access_file(file_record):
        abort(403)

    if file_record.get('protection') == 'password':
        verified = session.get(f'file_unlocked_{file_id}')
        if not verified:
            return render_template('files/password_prompt.html', file=file_record)

    ext = os.path.splitext(file_record['name'])[1].lower()
    preview_url = None
    preview_type = None
    is_owner = file_record.get('owner_id') == session.get('user_id')

    if ext in PREVIEWABLE:
        preview_url = get_presigned_url(file_record['file_key'])
        preview_type = 'direct'
    elif ext in OFFICE_PREVIEW:
        raw_url = get_presigned_url(file_record['file_key'])
        preview_url = f'https://docs.google.com/gview?url={raw_url}&embedded=true'
        preview_type = 'office'

    return render_template('files/view.html',
                           file=file_record,
                           preview_url=preview_url,
                           preview_type=preview_type,
                           ext=ext,
                           is_owner=is_owner)


@files_bp.route('/files/<file_id>/unlock', methods=['POST'])
@login_required
def unlock_file(file_id):
    res = supabase.table('files').select('*').eq('id', file_id).execute()
    if not res.data:
        abort(404)
    file_record = res.data[0]
    password = request.form.get('password', '')

    if bcrypt.checkpw(password.encode(), file_record['password_hash'].encode()):
        session[f'file_unlocked_{file_id}'] = True
        return redirect(url_for('files.view_file', file_id=file_id))

    return render_template('files/password_prompt.html', file=file_record, error='密碼錯誤')


@files_bp.route('/files/<file_id>/set-password', methods=['POST'])
@login_required
def set_password(file_id):
    res = supabase.table('files').select('*').eq('id', file_id).execute()
    if not res.data:
        abort(404)
    file_record = res.data[0]

    if file_record['owner_id'] != session['user_id']:
        abort(403)

    new_password = request.form.get('new_password', '').strip()
    if not new_password:
        return jsonify({'error': '請輸入新密碼'}), 400

    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    supabase.table('files').update({
        'protection': 'password',
        'password_hash': new_hash,
    }).eq('id', file_id).execute()

    session.pop(f'file_unlocked_{file_id}', None)
    return jsonify({'success': True})


@files_bp.route('/files/<file_id>/remove-password', methods=['POST'])
@login_required
def remove_password(file_id):
    res = supabase.table('files').select('*').eq('id', file_id).execute()
    if not res.data:
        abort(404)
    file_record = res.data[0]

    if file_record['owner_id'] != session['user_id']:
        abort(403)

    supabase.table('files').update({
        'protection': 'none',
        'password_hash': None,
    }).eq('id', file_id).execute()

    session.pop(f'file_unlocked_{file_id}', None)
    return jsonify({'success': True})


@files_bp.route('/files/<file_id>/share-link', methods=['POST'])
@login_required
def share_link(file_id):
    res = supabase.table('files').select('*').eq('id', file_id).execute()
    if not res.data:
        abort(404)
    file_record = res.data[0]

    if not _can_access_file(file_record):
        abort(403)

    expires_map = {'1h': 3600, '24h': 86400, '7d': 604800}
    expires_key = request.form.get('expires', '24h')
    expires_sec = expires_map.get(expires_key, 86400)

    url = get_presigned_url(file_record['file_key'], expires=expires_sec)
    return jsonify({'url': url, 'expires': expires_key})


@files_bp.route('/files/<file_id>/stream')
@login_required
def stream_file(file_id):
    """PDF / 圖片 inline preview：透過 server proxy 避免 R2 CORS 問題。"""
    res = supabase.table('files').select('*').eq('id', file_id).execute()
    if not res.data:
        abort(404)
    file_record = res.data[0]

    if not _can_access_file(file_record):
        abort(403)

    if file_record.get('protection') == 'password':
        if not session.get(f'file_unlocked_{file_id}'):
            abort(403)

    url = get_presigned_url(file_record['file_key'], expires=300)
    r = http_requests.get(url, stream=True, timeout=30)

    content_type = file_record.get('content_type') or 'application/octet-stream'

    def generate():
        for chunk in r.iter_content(chunk_size=8192):
            yield chunk

    return Response(generate(), headers={
        'Content-Type': content_type,
        'Content-Disposition': f'inline; filename="{file_record["name"]}"',
        'Cache-Control': 'private, max-age=300',
    }, status=r.status_code)


@files_bp.route('/files/<file_id>/download')
@login_required
def download_file(file_id):
    res = supabase.table('files').select('*').eq('id', file_id).execute()
    if not res.data:
        abort(404)
    file_record = res.data[0]

    if not _can_access_file(file_record):
        abort(403)

    if file_record.get('protection') == 'password':
        if not session.get(f'file_unlocked_{file_id}'):
            abort(403)

    url = get_presigned_url(file_record['file_key'], expires=60)
    return redirect(url)


@files_bp.route('/files/<file_id>/delete', methods=['POST'])
@login_required
def delete(file_id):
    res = supabase.table('files').select('*').eq('id', file_id).execute()
    if not res.data:
        abort(404)
    file_record = res.data[0]

    is_owner = file_record['owner_id'] == session['user_id']
    if not is_owner and not session.get('is_admin'):
        abort(403)

    if not is_owner:
        create_notification(
            user_id=file_record['owner_id'],
            type_='file_deleted',
            title=f'您的檔案「{file_record["name"]}」已被管理員刪除',
            body='如有疑問請聯繫管理員。',
        )

    delete_file(file_record['file_key'])
    supabase.table('files').delete().eq('id', file_id).execute()
    return jsonify({'success': True})


@files_bp.route('/folders/create', methods=['POST'])
@login_required
def create_folder():
    if session.get('role') not in ALLOWED_ROLES:
        abort(403)
    name = request.form.get('name', '').strip()
    parent_id = request.form.get('parent_id') or None
    visibility = request.form.get('visibility', 'private')
    allowed_roles = request.form.getlist('allowed_roles')
    allowed_users = request.form.getlist('allowed_users')
    allowed_groups = request.form.getlist('allowed_groups')
    protection = request.form.get('protection', 'none')
    password = request.form.get('password', '')

    if not name:
        return jsonify({'error': '請填入資料夾名稱'}), 400

    password_hash = None
    if protection == 'password' and password:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    supabase.table('folders').insert({
        'name': name,
        'parent_id': parent_id,
        'created_by': session['user_id'],
        'visibility': visibility,
        'allowed_roles': allowed_roles if allowed_roles else None,
        'allowed_users': allowed_users if allowed_users else None,
        'allowed_groups': allowed_groups if allowed_groups else None,
        'protection': protection,
        'password_hash': password_hash,
    }).execute()
    return jsonify({'success': True})


@files_bp.route('/folders/<folder_id>/unlock', methods=['POST'])
@login_required
def unlock_folder(folder_id):
    res = supabase.table('folders').select('*').eq('id', folder_id).execute()
    if not res.data:
        abort(404)
    folder = res.data[0]
    password = request.form.get('password', '')

    if bcrypt.checkpw(password.encode(), folder['password_hash'].encode()):
        session[f'folder_unlocked_{folder_id}'] = True
        return redirect(url_for('files.index', folder_id=folder_id))

    return render_template('files/folder_password_prompt.html', folder=folder, error='密碼錯誤')


@files_bp.route('/folders/<folder_id>/set-password', methods=['POST'])
@login_required
def set_folder_password(folder_id):
    res = supabase.table('folders').select('*').eq('id', folder_id).execute()
    if not res.data:
        abort(404)
    folder = res.data[0]

    if folder['created_by'] != session['user_id']:
        abort(403)

    new_password = request.form.get('new_password', '').strip()
    if not new_password:
        return jsonify({'error': '請輸入新密碼'}), 400

    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    supabase.table('folders').update({
        'protection': 'password',
        'password_hash': new_hash,
    }).eq('id', folder_id).execute()

    session.pop(f'folder_unlocked_{folder_id}', None)
    return jsonify({'success': True})


@files_bp.route('/folders/<folder_id>/delete', methods=['POST'])
@login_required
def delete_folder(folder_id):
    res = supabase.table('folders').select('*').eq('id', folder_id).execute()
    if not res.data:
        abort(404)
    folder = res.data[0]

    is_owner = folder['created_by'] == session['user_id']
    if not is_owner and not session.get('is_admin'):
        abort(403)

    if not is_owner:
        create_notification(
            user_id=folder['created_by'],
            type_='folder_deleted',
            title=f'您建立的資料夾「{folder["name"]}」已被管理員刪除',
            body='如有疑問請聯繫管理員。',
        )

    supabase.table('folders').delete().eq('id', folder_id).execute()
    return jsonify({'success': True})
