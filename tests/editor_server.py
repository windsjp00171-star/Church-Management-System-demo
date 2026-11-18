"""後台活動表單的瀏覽器測試用的伺服器：真的 create_app()、空資料庫、固定的管理員身分。

用法：python tests/editor_server.py <port>   （由 tests/test_event_editor_browser.py 啟動）
資料庫替身沿用 smoke_boot.py 的那一份（程式碼相同，這裡只多了「啟動伺服器」）。
"""
import json
import os
import re
import sys
import time
import types
import uuid

os.environ.update(FLASK_SECRET_KEY='k', LINE_CHANNEL_ID='1', LINE_CHANNEL_SECRET='s',
                  LINE_REDIRECT_URI='http://x/auth/callback', SUPABASE_URL='http://x', SUPABASE_KEY='k',
                  LINE_LIFF_ID='1-x')
for k in ('R2_ENDPOINT', 'GROQ_API_KEY', 'GEMINI_API_KEY', 'SENTRY_DSN', 'DEMO_MODE'):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UID = str(uuid.uuid4())
ME = {'id': UID, 'real_name': '測試', 'display_name': '測試', 'line_user_id': 'Ume', 'member_type': 'member',
      'is_admin': True, 'is_super_admin': True, 'is_pastor': True, 'is_staff': True, 'is_blocked': False,
      'group_tags': [], 'role': 'admin', 'picture_url': ''}


class Res:
    def __init__(self, data):
        self.data, self.count = data, len(data)


class Query:
    def __init__(self, name):
        self.name, self.op, self.payload = name, 'select', None

    def __getattr__(self, attr):
        if attr == 'not_':
            return self
        if attr in ('insert', 'upsert', 'update'):
            def w(payload, *a, **k):
                self.op, self.payload = attr, payload
                return self
            return w
        if attr == 'delete':
            def d(*a, **k):
                self.op = 'delete'
                return self
            return d
        return lambda *a, **k: self

    def execute(self, *a, **k):
        if self.op in ('insert', 'upsert'):
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            return Res([dict(r, id=r.get('id') or str(uuid.uuid4())) for r in rows])
        if self.op in ('update', 'delete'):
            return Res([])
        return Res([ME] if self.name == 'users' else [])


class DB:
    def table(self, name):
        return Query(name)

    def rpc(self, *a, **k):
        return Query('rpc')

    @property
    def storage(self):
        return types.SimpleNamespace(from_=lambda b: types.SimpleNamespace(
            upload=lambda **k: None, get_public_url=lambda n: 'http://x/' + n, remove=lambda *a, **k: None))


sys.modules['db'] = types.SimpleNamespace(supabase=DB())
import logging
logging.disable(logging.CRITICAL)
import app as appmod                                              # noqa: E402

app = appmod.create_app()
ROLES = {
    'anon': None,
    'member': dict(user_id=UID, real_name='會友', line_id='Um', member_type='member'),
    'admin': dict(user_id=UID, real_name='超管', line_id='Ua', member_type='member', is_admin=True,
                  is_super_admin=True, is_pastor=True, is_staff=True),
}


def client(flags):
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(_csrf_token='t', _perm_checked_at=int(time.time()), _user_verified=True, **(flags or {}))
    return c



from flask import session as _s


@app.before_request
def _force_admin():
    _s.update(_csrf_token='t', _perm_checked_at=int(time.time()), _user_verified=True, **ROLES['admin'])


if __name__ == '__main__':
    from werkzeug.serving import make_server
    s = make_server('127.0.0.1', int(sys.argv[1]), app, threaded=True)
    print('READY', flush=True)
    s.serve_forever()
