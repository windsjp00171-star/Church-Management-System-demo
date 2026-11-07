import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """假的 Supabase 查詢鏈：記錄寫入，讀取回傳預先放好的資料。"""
    def __init__(self, db, name):
        self.db, self.name, self.op, self.payload = db, name, 'select', None

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def range(self, lo, hi):
        self._range = (lo, hi)
        return self

    def insert(self, payload):
        self.op, self.payload = 'insert', payload
        return self

    def update(self, payload):
        self.op, self.payload = 'update', payload
        return self

    def upsert(self, payload, **_kw):
        self.op, self.payload = 'upsert', payload
        return self

    def execute(self):
        if self.op == 'select':
            rows = list(self.db.tables.get(self.name, []))
            r = getattr(self, '_range', None)
            return FakeResult(rows[r[0]:r[1] + 1] if r else rows)
        self.db.writes.append((self.name, self.op, self.payload))
        payload = self.payload if isinstance(self.payload, list) else [self.payload]
        return FakeResult([dict(p, id='new-id') for p in payload])


class FakeRpc:
    def __init__(self, db, fn, args):
        self.db, self.fn, self.args = db, fn, args

    def execute(self):
        self.db.rpcs.append((self.fn, self.args))
        if self.db.rpc_error:
            raise self.db.rpc_error
        return FakeResult({'changed': True})


class FakeSupabase:
    def __init__(self):
        self.tables, self.writes, self.rpcs, self.rpc_error = {}, [], [], None

    def table(self, name): return FakeQuery(self, name)
    def rpc(self, fn, args): return FakeRpc(self, fn, args)


@pytest.fixture
def fake_db():
    fake = FakeSupabase()
    mod = types.ModuleType('db')
    mod.supabase = fake
    sys.modules['db'] = mod
    for name in ('routes.roll_call', 'routes.audit', 'routes.decorators'):
        sys.modules.pop(name, None)      # 載入時綁住 db 的模組，跟著這一輪的假資料庫重新載入
    return fake


@pytest.fixture
def app(fake_db):
    from flask import Blueprint, Flask
    app = Flask(__name__, template_folder=os.path.join(ROOT, 'templates'))
    app.secret_key = 'test'
    auth = Blueprint('auth', __name__)

    @auth.route('/auth/login')
    def login_page():
        return 'login'

    app.register_blueprint(auth)
    # 簡化 app 沒有正式 app 在啟動時掛上的模板全域函式；要渲染 base.html 的頁面需要它們
    app.jinja_env.globals.update(csrf_token=lambda: 't', module_on=lambda *_: True, church_name='測試教會',
                                 church_short_name='測試', line_liff_id='', privacy_policy_url='',
                                 card_names={}, can_see=lambda *_: True)
    from routes.roll_call import roll_call_bp
    app.register_blueprint(roll_call_bp)
    return app


@pytest.fixture
def client_as(app):
    def make(**flags):
        c = app.test_client()
        with c.session_transaction() as s:
            if flags is not None:
                s['user_id'] = 'op-1'
                s['real_name'] = '測試操作者'
                s.update(flags)
        return c
    return make


import re as _re
from pathlib import Path as _Path


#  asset() 引用得到的**原始碼**副檔名。
#  ★ 圖片也走 asset()（頭像、icon），而圖片不是文字 ——
#    一律 read_text 的話會 UnicodeDecodeError，而且是在 **import 期**炸，
#    所以整個檔案連收集都收集不到：畫面上是「2 errors during collection」，
#    看起來像測試壞了，其實只是有人在模板裡加了一張圖。
#    （實際發生過：小舟的頭像從 emoji 換成 PNG 的那一次。）
_SOURCE_EXTS = ('.css', '.js', '.svg')


def source_bundle(template):
    """回傳 template 的內容 ＋ 它透過 asset() 引用的所有 static **原始碼**內容。

    template: 相對 templates/ 的路徑，例如 'base.html'。
    """
    root = _Path(__file__).resolve().parent.parent
    text = (root / 'templates' / template).read_text(encoding='utf-8')
    parts = [text]
    for rel in _re.findall(r"asset\(\s*['\"]([^'\"]+)['\"]\s*\)", text):
        f = root / 'static' / rel
        if f.exists() and f.suffix.lower() in _SOURCE_EXTS:
            parts.append(f.read_text(encoding='utf-8'))
    # 還沒改用 asset() 的寫死路徑也一起收進來
    for rel in _re.findall(r'src="/static/([^"]+\.js)"', text):
        f = root / 'static' / rel
        if f.exists():
            parts.append(f.read_text(encoding='utf-8'))
    return '\n'.join(parts)



@pytest.fixture(autouse=True)
def _no_real_bible_fetches():
    """測試一律不去打聖經平台（別人的站）。要驗抓取行為的測試自己傳 `fetch=`，
    這一道擋的是「忘了傳」而偷偷連出去的那一種。"""
    from unittest.mock import patch

    def _blocked(url, timeout=None):
        raise AssertionError(f'測試不可以真的去抓 {url} —— 請傳 fetch= 進去')

    try:
        import routes.bible_text  # noqa: F401
    except Exception:
        yield
        return
    with patch('routes.bible_text._http_get', _blocked):
        yield


@pytest.fixture
def client(fake_db):
    """只掛聖經速讀藍圖的簡化 app 的 test client（這個 repo 的完整 app 不能和其他測試同一個行程，
    所以跟 `app` fixture 一樣的做法）。測試自己用 patch 把資料庫那一層換掉。"""
    from flask import Blueprint, Flask
    for name in ('routes.bible_plan', 'routes.bible_text', 'routes.decorators'):
        sys.modules.pop(name, None)
    app = Flask(__name__, template_folder=os.path.join(ROOT, 'templates'),
                static_folder=os.path.join(ROOT, 'static'))
    app.secret_key = 'test'
    app.config['TESTING'] = True
    auth = Blueprint('auth', __name__)
    auth.add_url_rule('/auth/login', 'login_page', lambda: 'login')
    app.register_blueprint(auth)
    app.jinja_env.globals.update(csrf_token=lambda: 't', module_on=lambda *_: True, church_name='測試教會',
                                 church_short_name='測試', line_liff_id='', privacy_policy_url='',
                                 card_names={}, can_see=lambda *_: True,
                                 asset=lambda path: '/static/' + path)
    from routes.bible_plan import bible_plan_bp
    app.register_blueprint(bible_plan_bp)
    return app.test_client()


@pytest.fixture
def logged_in_client(client):
    with client.session_transaction() as s:
        s.update(user_id='test-user-uuid', real_name='測試會友', line_id='U123456789', member_type='member')
    return client


@pytest.fixture
def admin_client(client):
    with client.session_transaction() as s:
        s.update(user_id='admin-user-uuid', real_name='測試管理員', member_type='member', is_admin=True,
                 _csrf_token='test-csrf-token')
    return client
