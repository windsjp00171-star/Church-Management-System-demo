"""整個應用的啟動煙霧測試（在子行程裡跑，不會汙染其他測試載入的模組）。

做兩件事：
1. 用真正的 app.create_app() 啟動（所有藍圖、before_request、模板全部真的載入）
2. 用「空資料庫」打遍每一條路由（GET 與帶空 JSON 的 POST），身分分別是：未登入、一般會友、超管

輸出一行 JSON：{"checked": N, "bad": [[身分, 方法, 路徑, 狀態或例外], ...], "ok200": {身分: 回 200 的 GET 數}}
資料庫替身：users 查詢回登入者那一列、寫入回傳寫入的內容、其餘一律空；不連任何網路。
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


bad, n = [], 0
ok200 = {k: 0 for k in ROLES}
for role, flags in ROLES.items():
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.rule.startswith('/static') or rule.rule == '/auth/logout':
            continue
        url = re.sub(r'<[^>]+>', UID, re.sub(r'<int:[^>]+>', '1', rule.rule))
        for m in ('GET', 'POST'):
            if m not in rule.methods:
                continue
            n += 1
            try:
                c = client(flags)
                r = c.get(url) if m == 'GET' else c.post(url, json={}, headers={'X-CSRF-Token': 't'})
                if m == 'GET' and r.status_code == 200:
                    ok200[role] += 1
                if r.status_code >= 500:
                    bad.append([role, m, rule.rule, r.status_code])
            except Exception as e:
                bad.append([role, m, rule.rule, f'EXC {type(e).__name__}: {str(e)[:80]}'])
# 授權探針：這些頁面對某些身分『不可以』是 200（空資料庫下 5xx 檢查看不到這種洞）
PROBES = {
    'anon': ['/cell-report/sunday', '/cell-report/children', '/cell-report/prayer', '/cell-report/morning-prayer', '/cell-report/pastor-dashboard', '/cell-report/staff-dashboard', '/admin/users', '/admin/backup/',
             '/admin/modules', '/admin/permissions', '/admin/data-export', '/roll-call', '/admin/roll-call',
             '/diary/export', '/staff', '/my-history'],
    'member': ['/cell-report/sunday', '/cell-report/children', '/cell-report/prayer', '/cell-report/morning-prayer', '/cell-report/pastor-dashboard', '/cell-report/staff-dashboard', '/admin/users', '/admin/backup/',
               '/admin/modules', '/admin/permissions', '/admin/data-export', '/admin/roll-call', '/staff'],
}
probe = {role: {u: client(ROLES[role]).get(u).status_code for u in urls} for role, urls in PROBES.items()}
print(json.dumps({'checked': n, 'bad': bad, 'ok200': ok200, 'probe': probe}, ensure_ascii=False))
