from functools import wraps
from flask import session, redirect, url_for, request, jsonify, abort, render_template
from urllib.parse import quote


def _is_json():
    return request.is_json or request.path.startswith('/api/')


def login_required(f):
    """未登入導向登入頁，並記住原始路徑。已封鎖帳號立即擋回。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            next_path = request.path
            if request.query_string:
                next_path += '?' + request.query_string.decode('utf-8', errors='replace')
            session['next_url'] = next_path
            if _is_json():
                return jsonify({'error': '請先登入'}), 401
            return redirect(url_for('auth.login_page') + '?next=' + quote(next_path, safe='/'))
        if session.get('is_blocked'):
            if _is_json():
                return jsonify({'error': '此帳號已被封鎖'}), 403
            return render_template('auth/blocked.html'), 403
        return f(*args, **kwargs)
    return decorated


def approved_required(f):
    """需要已核准帳號（非 pending/blocked）。"""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        role = session.get('role', 'approved')
        if role in ('pending', 'blocked'):
            if _is_json():
                return jsonify({'error': '帳號尚未核准'}), 403
            return redirect(url_for('auth.login_page'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """需要管理員或超級管理員身分。"""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not (session.get('is_admin') or session.get('is_super_admin')):
            if _is_json():
                return jsonify({'error': '權限不足'}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated


def super_admin_required(f):
    """需要超級管理員身分。"""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not session.get('is_super_admin'):
            if _is_json():
                return jsonify({'error': '權限不足'}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated


def pastor_required(f):
    """需要牧者身分（is_pastor）。"""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not session.get('is_pastor'):
            if _is_json():
                return jsonify({'error': '需要牧者身分'}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated


def staff_required(f):
    """需要同工身分（is_staff 或 is_pastor）。"""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not (session.get('is_staff') or session.get('is_pastor') or session.get('is_admin')):
            if _is_json():
                return jsonify({'error': '需要同工身分'}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated


def cell_leader_required(f):
    """需要至少負責一個小組（cell_group_ids 非空），牧者和管理員自動通過。"""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if session.get('is_pastor') or session.get('is_admin'):
            return f(*args, **kwargs)
        if not session.get('cell_group_ids'):
            if _is_json():
                return jsonify({'error': '需要小組長身分'}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated
