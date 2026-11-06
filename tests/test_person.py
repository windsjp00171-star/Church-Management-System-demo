"""手動建立「人」：建立前先攤出疑似重複，由管理員決定；沒有 LINE 的人本來就可以存在。"""
import importlib
import sys
import types

import pytest

from fake_supabase import FakeSupabase

PEOPLE = [
    {'id': 'u1', 'real_name': '王小明', 'display_name': 'Ming', 'line_user_id': 'U1', 'member_type': 'member'},
    {'id': 'u2', 'real_name': '陳大', 'display_name': '大陳', 'line_user_id': None, 'member_type': 'member'},
    {'id': 'u3', 'real_name': None, 'display_name': 'John Smith', 'line_user_id': 'U3', 'member_type': 'visitor'},
]


@pytest.fixture
def person(monkeypatch):
    db = FakeSupabase(users=[dict(p) for p in PEOPLE])
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=db))
    sys.modules.pop('routes.person', None)
    mod = importlib.import_module('routes.person')
    yield mod, db
    sys.modules.pop('routes.person', None)


def test_same_name_and_one_character_off_are_flagged(person):
    mod, _ = person
    assert {d['id']: d['reason'] for d in mod.find_possible_duplicates('王小明')} == {'u1': '姓名相同'}
    assert {d['id']: d['reason'] for d in mod.find_possible_duplicates('王曉明')} == {'u1': '姓名只差一個字'}


def test_display_name_equal_counts_but_width_and_spaces_are_ignored(person):
    mod, _ = person
    assert [d['id'] for d in mod.find_possible_duplicates('ｊｏｈｎ　SMITH')] == ['u3']


def test_two_char_names_are_not_called_similar(person):
    mod, _ = person
    assert mod.find_possible_duplicates('陳小') == []          # 陳大 vs 陳小 只差一字，但兩字名不比


def test_has_line_is_reported_so_the_admin_can_tell_them_apart(person):
    mod, _ = person
    d = {x['id']: x['has_line'] for x in mod.find_possible_duplicates('王小明')}
    assert d == {'u1': True}
    assert mod.find_possible_duplicates('陳大')[0]['has_line'] is False


def test_create_stops_on_duplicates_and_writes_nothing_until_forced(person):
    mod, db = person
    kind, dups = mod.create_person('王小明')
    assert kind == 'duplicates' and dups and not [w for w in db.log if w[0] == 'insert']
    kind, row = mod.create_person('王小明', force=True)
    assert kind == 'created' and row['real_name'] == '王小明' and 'line_user_id' not in row


def test_create_a_new_person_has_no_line_account(person):
    mod, db = person
    kind, row = mod.create_person('  李小華 ', 'visitor')
    assert kind == 'created' and row['member_type'] == 'visitor' and row['real_name'] == '李小華'


def test_bad_input_is_refused(person):
    mod, _ = person
    with pytest.raises(ValueError):
        mod.create_person('  ')
    with pytest.raises(ValueError):
        mod.create_person('李小華', 'admin')


def test_a_read_failure_does_not_pass_as_no_duplicates(person, monkeypatch):
    mod, db = person
    real_table = db.table

    class ReadFails:
        def select(self, *a, **k):
            raise RuntimeError('down')

    # 只有「讀」壞掉、「寫」是好的：吞掉讀取錯誤的實作會把它當成『沒有重複』然後照樣建立
    monkeypatch.setattr(db, 'table', lambda n: ReadFails() if n == 'users' else real_table(n))
    with pytest.raises(RuntimeError, match='down'):
        mod.create_person('李小華')
    assert not [w for w in db.log if w[0] == 'insert']


def test_more_than_one_page_of_people_is_all_checked(person):
    mod, db = person
    mk = lambda i: chr(0x4e00 + i) + chr(0x4e00 + i + 2000) + chr(0x4e00 + i + 4000)    # 彼此三個字全不同
    db.data['users'] += [{'id': f'x{i}', 'real_name': mk(i), 'display_name': None, 'line_user_id': None,
                          'member_type': 'member'} for i in range(1205)]
    assert [d['id'] for d in mod.find_possible_duplicates(mk(1204))] == ['x1204']


# ── 路由（admin.create_manual_user）──
def test_admin_route_returns_409_with_candidates_then_accepts_force(monkeypatch):
    from flask import Blueprint, Flask
    db = FakeSupabase(users=[dict(p) for p in PEOPLE], audit_logs=[])
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=db))
    bound = ('routes.admin', 'routes.audit', 'routes.auth', 'routes.permissions', 'routes.person',
             'routes.decorators', 'routes.user_merge', 'settings_store', 'routes.profile')
    saved = {n: sys.modules.get(n) for n in bound}
    for n in bound:
        sys.modules.pop(n, None)
    import routes.admin as admin
    import routes.audit as audit
    import routes.auth as auth
    import routes.permissions as perm
    import routes.person as pmod
    for m in (admin, audit, auth, perm, pmod):
        monkeypatch.setattr(m, 'supabase', db)
    app = Flask(__name__)
    app.secret_key = 't'
    authbp = Blueprint('auth', __name__)
    authbp.add_url_rule('/auth/login', 'login_page', lambda: 'login')
    app.register_blueprint(authbp)
    evt = Blueprint('event', __name__)
    evt.add_url_rule('/', 'portal', lambda: 'portal')
    app.register_blueprint(evt)
    app.register_blueprint(admin.admin_bp)
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(_csrf_token='tok', user_id='root', real_name='root', is_admin=True, is_super_admin=True)

    def post(body):
        return c.post('/admin/api/users/create', json=body, headers={'X-CSRF-Token': 'tok'})
    r = post({'real_name': '王小明'})
    assert r.status_code == 409 and r.get_json()['duplicates'][0]['id'] == 'u1'
    assert not [w for w in db.log if w[0] == 'insert' and w[1] == 'users']
    r = post({'real_name': '王小明', 'force': True})
    assert r.status_code == 200 and r.get_json()['success']
    audit_rows = [w for w in db.log if w[0] == 'insert' and w[1] == 'audit_logs']
    assert audit_rows and audit_rows[-1][2][0]['action'] == 'user.create'
    assert post({'real_name': '  '}).status_code == 400
    for n, old in saved.items():          # 還原原本載入的模組（其他測試在載入時就拿了它們的參考）
        sys.modules.pop(n, None)
        if old is not None:
            sys.modules[n] = old
