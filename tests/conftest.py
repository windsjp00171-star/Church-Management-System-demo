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

    def insert(self, payload):
        self.op, self.payload = 'insert', payload
        return self

    def update(self, payload):
        self.op, self.payload = 'update', payload
        return self

    def execute(self):
        if self.op == 'select':
            return FakeResult(list(self.db.tables.get(self.name, [])))
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
    sys.modules.pop('routes.roll_call', None)
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
