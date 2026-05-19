from functools import wraps
from flask import session, redirect, url_for, request
from urllib.parse import quote


def login_required(f):
    """未登入就導向登入頁，並記住原始路徑（只傳 path，避免 host 比對失敗）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            next_path = request.path
            if request.query_string:
                next_path += '?' + request.query_string.decode('utf-8', errors='replace')
            session['next_url'] = next_path
            return redirect(url_for('auth.login_page') + '?next=' + quote(next_path, safe='/'))
        return f(*args, **kwargs)
    return decorated
