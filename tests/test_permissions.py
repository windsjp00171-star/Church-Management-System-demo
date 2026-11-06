"""後台權限矩陣（副標籤 × 模塊）。判定只有一份：routes.permissions.module_allows_path。"""
import re
import sys
from pathlib import Path

import pytest

import structure_scan as scan

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def perm(fake_db):
    sys.modules.pop('routes.permissions', None)
    sys.modules.pop('routes.decorators', None)
    import routes.permissions as p
    return p


def sess(**kw):
    return kw


# ── 路徑分類 ────────────────────────────────────────────
@pytest.mark.parametrize('path,kind,key', [
    ('/admin', 'shared', None), ('/admin/', 'shared', None),
    ('/admin/permissions', 'shared', None), ('/admin/permissions/save', 'shared', None),
    ('/admin/api/upload-image', 'shared', None),
    ('/admin/events', 'module', 'events'), ('/admin/events/abc/registrations', 'module', 'events'),
    ('/admin/courses/group-overview', 'module', 'courses'),
    ('/admin/settings/payment', 'reserved', None),          # 比 /admin/settings 更長：金流不交給矩陣
    ('/admin/payments/export', 'reserved', None),
    ('/admin/settings', 'module', 'settings'),
    ('/admin/api/users/search-for-cell', 'module', 'cell_groups'),   # 最長前綴勝出，不被 members 吃掉
    ('/admin/api/users/search', 'module', 'members'),
    ('/api/admin/roll-call/rules', 'module', 'roll_call'),
    ('/admin/roll-call/rates/export', 'module', 'roll_call'),
    ('/admin/something-new', 'unregistered', None),
    ('/events', 'outside', None), ('/cell-report/admin/meeting-settings', 'outside', None),
    ('/administrator', 'outside', None),                    # 前綴要整段比對，不是字串開頭
])
def test_classify(perm, path, kind, key):
    assert perm.classify(path) == (kind, key)


def test_registry_has_unique_keys_and_prefixes(perm):
    keys = [m[0] for m in perm.ADMIN_MODULES]
    assert len(keys) == len(set(keys))
    prefixes = [p for m in perm.ADMIN_MODULES for p in m[2]]
    assert len(prefixes) == len(set(prefixes)), '同一個前綴不可登記給兩個模塊'
    assert perm.DEFAULT_ADMIN_MODULES <= set(keys)


def _normalized_admin_paths():
    return sorted({re.sub(r'<[^>]+>', 'x', p) for _f, _fn, p, _n in scan.admin_routes()})


def test_every_admin_route_is_registered_in_a_module_or_shared_or_reserved(perm):
    """新增後台路由卻沒登記模塊 → 副標籤的人進不去、而且沒人發現。這條讓它在開發時就紅。"""
    unregistered = [p for p in _normalized_admin_paths() if perm.classify(p)[0] == 'unregistered']
    assert unregistered == [], f'沒登記進 ADMIN_MODULES 的後台路徑：{unregistered}'


def test_index_cards_point_at_registered_modules(perm):
    text = (ROOT / 'templates' / 'admin' / 'index.html').read_text(encoding='utf-8')
    for path in re.findall(r"can_see\('([^']+)'\)", text):
        assert perm.classify(path)[0] in ('module', 'shared'), f'首頁卡片 {path} 沒有對應的模塊'


# ── 判定 ───────────────────────────────────────────────
def test_admins_pass_everything(perm):
    for flag in ('is_admin', 'is_super_admin'):
        assert perm.module_allows_path(sess(**{flag: True}), '/admin/anything-at-all')


def test_holder_only_gets_granted_modules(perm):
    s = sess(admin_modules=['events'])
    assert perm.module_allows_path(s, '/admin/events/1/registrations')
    assert not perm.module_allows_path(s, '/admin/roll-call')
    assert not perm.module_allows_path(s, '/admin/users')
    assert perm.module_allows_path(s, '/admin')                 # 有任一模塊就能進首頁
    assert perm.module_allows_path(s, '/admin/api/upload-image')


def test_unregistered_and_outside_paths_fail_closed(perm):
    s = sess(admin_modules=['events', 'members'])
    assert not perm.module_allows_path(s, '/admin/brand-new-feature')
    assert not perm.module_allows_path(s, '/admin/payments')           # 金流不交給矩陣
    assert not perm.module_allows_path(sess(admin_modules=['settings']), '/admin/settings/payment')
    assert not perm.module_allows_path(s, '/cell-report/admin/meeting-settings')
    assert not perm.module_allows_path(s, '/diary/admin')


def test_no_modules_no_entry(perm):
    for s in (sess(), sess(admin_modules=[]), sess(admin_modules=None)):
        assert not perm.module_allows_path(s, '/admin')
        assert not perm.module_allows_path(s, '/admin/events')


def test_stale_wildcard_is_not_trusted(perm):
    """登入時存的 '*' 可能已過期（之後被降權）；不能單靠它放行。"""
    s = sess(admin_modules='*', is_admin=False, is_super_admin=False)
    assert not perm.module_allows_path(s, '/admin/events')
    assert not perm.can_enter_admin(s)


def test_index_visibility(perm):
    assert perm.visible_index_modules(sess(is_super_admin=True)) == set(perm.MODULE_KEYS)
    assert perm.visible_index_modules(sess(is_admin=True)) == perm.DEFAULT_ADMIN_MODULES
    assert perm.visible_index_modules(sess(admin_modules=['events', 'files'])) == {'events', 'files'}


# ── 登入時計算 ─────────────────────────────────────────
def test_compute_admin_modules(perm, fake_db):
    assert perm.compute_admin_modules(True, False, []) == '*'
    assert perm.compute_admin_modules(False, True, []) == '*'
    assert perm.compute_admin_modules(False, False, []) == set()
    fake_db.tables['groups'] = [{'name': '敬拜', 'admin_modules': ['events', 'bogus-key']},
                                {'name': '招待', 'admin_modules': ['files', 'events']}]
    assert perm.compute_admin_modules(False, False, ['敬拜', '招待']) == {'events', 'files'}   # 聯集、濾掉未知 key


def test_compute_fails_closed_when_db_breaks(perm, fake_db):
    class Boom:
        def table(self, *_a):
            raise RuntimeError('db down')
    sys.modules['db'].supabase = Boom()
    sys.modules.pop('routes.permissions', None)
    import routes.permissions as p
    assert p.compute_admin_modules(False, False, ['敬拜']) == set()      # 連不上＝沒有授權，不是全部授權


# ── 裝飾器整合 ─────────────────────────────────────────
@pytest.fixture
def client_for(fake_db, perm):
    from flask import Blueprint, Flask
    sys.modules.pop('routes.decorators', None)
    from routes.decorators import admin_required
    app = Flask(__name__)
    app.secret_key = 't'
    auth = Blueprint('auth', __name__)
    auth.add_url_rule('/auth/login', 'login_page', lambda: 'login')
    app.register_blueprint(auth)
    bp = Blueprint('t', __name__)

    @bp.route('/admin/events/<x>')
    @admin_required
    def events(x): return 'events-ok'

    @bp.route('/admin/roll-call')
    @admin_required
    def rc(): return 'rc-ok'

    @bp.route('/api/admin/roll-call/x', methods=['POST'])
    @admin_required
    def rc_api(): return 'api-ok'

    @bp.route('/not-admin-path')
    @admin_required
    def elsewhere(): return 'elsewhere-ok'

    app.register_blueprint(bp)

    def make(**flags):
        c = app.test_client()
        with c.session_transaction() as s:
            s.update(user_id='u1', **flags)
        return c
    return make


def test_decorator_lets_granted_holder_in_only(client_for):
    c = client_for(admin_modules=['events'])
    assert c.get('/admin/events/1').status_code == 200
    assert c.get('/admin/roll-call').status_code == 403
    assert c.post('/api/admin/roll-call/x', json={}).status_code == 403


def test_decorator_denies_holder_outside_admin_area(client_for):
    """admin_required 掛在後台以外的路徑時，副標籤的人一律進不去（只有真正的管理員可以）。"""
    assert client_for(admin_modules=['events', 'roll_call']).get('/not-admin-path').status_code == 403
    assert client_for(is_admin=True).get('/not-admin-path').status_code == 200


def test_decorator_api_returns_json_403(client_for):
    r = client_for(admin_modules=['events']).post('/api/admin/roll-call/x', json={})
    assert r.status_code == 403 and r.get_json()['error']


def test_plain_member_and_stale_wildcard_denied(client_for):
    assert client_for().get('/admin/events/1').status_code == 403
    assert client_for(admin_modules='*').get('/admin/events/1').status_code == 403


def test_admins_unaffected(client_for):
    for flag in ({'is_admin': True}, {'is_super_admin': True}):
        c = client_for(**flag)
        assert c.get('/admin/events/1').status_code == 200 and c.get('/admin/roll-call').status_code == 200


# ── 編輯頁（僅超管）────────────────────────────────────
@pytest.fixture
def editor(fake_db, perm):
    from flask import Blueprint, Flask
    sys.modules.pop('routes.decorators', None)
    sys.modules.pop('routes.permissions', None)
    sys.modules.pop('routes.audit', None)
    import routes.permissions as p
    app = Flask(__name__)
    app.secret_key = 't'
    auth = Blueprint('auth', __name__)
    auth.add_url_rule('/auth/login', 'login_page', lambda: 'login')
    app.register_blueprint(auth)
    app.register_blueprint(p.permissions_bp)
    fake_db.tables['groups'] = [{'id': 'g1', 'name': '敬拜', 'admin_modules': []}]

    def make(**flags):
        c = app.test_client()
        with c.session_transaction() as s:
            s.update(user_id='u1', real_name='超管', **flags)
        return c
    return make, fake_db


def test_only_super_admin_can_edit_matrix(editor):
    make, fake = editor
    body = {'matrix': {'g1': ['events']}}
    assert make(is_admin=True).post('/admin/permissions/save', json=body).status_code == 403
    assert make(admin_modules=['events']).post('/admin/permissions/save', json=body).status_code == 403
    assert not [w for w in fake.writes if w[0] == 'groups']


def test_save_filters_unknown_groups_and_keys_and_audits(editor):
    make, fake = editor
    r = make(is_super_admin=True).post('/admin/permissions/save', json={
        'matrix': {'g1': ['events', 'not-a-module'], 'evil-group': ['events']}})
    assert r.status_code == 200 and r.get_json()['data']['updated'] == 1
    upd = [w for w in fake.writes if w[0] == 'groups']
    assert len(upd) == 1 and upd[0][2] == {'admin_modules': ['events']}
    audit = [w for w in fake.writes if w[0] == 'audit_logs']
    assert audit and audit[0][2]['action'] == 'permission.update'


# ── 結構守衛 ───────────────────────────────────────────
def _src(rel):
    return scan.strip_py((ROOT / rel).read_text(encoding='utf-8'))


def test_admin_required_delegates_to_the_single_implementation():
    assert 'module_allows_path' in _src('routes/decorators.py')


def test_login_populates_admin_modules_and_app_registers_the_editor():
    assert "session['admin_modules']" in _src('routes/auth.py')
    assert 'permissions_bp' in _src('app.py')


def test_groups_table_has_the_admin_modules_column():
    for f in ('schema.sql', 'migrations/014_permission_matrix.sql'):
        text = re.sub(r'--[^\n]*', '', (ROOT / f).read_text(encoding='utf-8'))
        assert re.search(r'admin_modules\s+JSONB', text, re.I), f
