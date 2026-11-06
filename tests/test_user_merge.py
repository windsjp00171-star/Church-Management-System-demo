"""帳號合併（routes/user_merge.py）的守衛。移植自 event-registration-，改成對照本系統的 schema.sql。

背景：原本的 account_merge 每一步都 `except` 只記 log，失敗的表丟進清單後**照樣刪掉 users**；
清單還寫錯表名（course_attendance，實際是 session_attendance）、漏了 audit_logs.actor_id。
畫面上合併「成功」，資料卻被 CASCADE 刪掉、被 SET NULL 清空，或留在懸空引用上。

這裡的守衛：
1. 清單蓋滿 schema.sql 所有引用 users 的欄位，而且每一欄都真的存在（沒有空操作）
2. 每個欄位真的會被搬（行為，不是掃字串）
3. 任何一步失敗 → 全部還原、不刪帳號、身分還原
4. 唯一限制衝突：只有登記 dedupe 的表取聯集，其他一律中止
5. 兩個入口都走同一份；舊的 account_merge 不能復活
"""
import ast
import json
import re
import sys
import types
from pathlib import Path

import pytest

if 'db' not in sys.modules:                  # routes.user_merge 載入時要 import db
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

from fake_supabase import FakeSupabase, _Query                        # noqa: E402
from routes import user_merge                                         # noqa: E402
from routes.user_merge import REFS, MergeError, label, merge_users, preview   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KEEP, DROP = 'keep-uuid', 'drop-uuid'


def _refs():
    return {(r.table, r.col) for r in REFS}


# ── 1. 清單蓋滿 ─────────────────────────────────
def _strip_sql(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'--[^\n]*', '', text)


SCHEMA = _strip_sql((ROOT / 'schema.sql').read_text(encoding='utf-8'))


def _schema_columns():
    cols = {}
    for m in re.finditer(r'CREATE TABLE(?: IF NOT EXISTS)?\s+(?:public\.)?(\w+)\s*\((.*?)\n\);', SCHEMA, re.S | re.I):
        t, body = m.groups()
        cols.setdefault(t, set())
        for line in body.split('\n'):
            c = re.match(r'\s*(\w+)\s+[A-Za-z]', line)
            if c and c.group(1).upper() not in ('PRIMARY', 'UNIQUE', 'CHECK', 'FOREIGN', 'CONSTRAINT'):
                cols[t].add(c.group(1))
    for m in re.finditer(r'ALTER TABLE\s+(?:public\.)?(\w+)\s+(.*?);', SCHEMA, re.S | re.I):
        for c in re.findall(r'ADD COLUMN(?: IF NOT EXISTS)?\s+(\w+)', m.group(2)):
            cols.setdefault(m.group(1), set()).add(c)
    return cols


def _sql_fk_columns():
    found = set()
    for m in re.finditer(r'CREATE TABLE(?: IF NOT EXISTS)?\s+(?:public\.)?(\w+)\s*\((.*?)\n\);', SCHEMA, re.S | re.I):
        table, body = m.groups()
        for line in body.split('\n'):
            c = re.match(r'\s*(\w+)\s+UUID\b.*REFERENCES\s+(?:public\.)?users\s*\(', line, re.I)
            if c:
                found.add((table, c.group(1)))
    for m in re.finditer(r'ALTER TABLE\s+(?:public\.)?(\w+)\s+(.*?);', SCHEMA, re.S | re.I):
        for clause in re.finditer(r'ADD COLUMN(?: IF NOT EXISTS)?\s+(\w+)\s+([^,;]*)', m.group(2), re.I):
            if re.search(r'REFERENCES\s+(?:public\.)?users\s*\(', clause.group(2), re.I):
                found.add((m.group(1), clause.group(1)))
    return found


def test_sql_scan_finds_something():
    assert len(_sql_fk_columns()) >= 15     # 掃描器自己壞掉會讓下一條安靜地變成空集合
    assert len(_schema_columns()) >= 40


def test_registry_covers_every_fk_in_schema():
    missing = _sql_fk_columns() - _refs()
    assert not missing, f'schema.sql 有引用 users 的欄位沒進 REFS：{sorted(missing)}'


def test_registry_has_no_phantom_columns():
    """清單裡的欄位在 schema 裡必須真的存在；不存在的是空操作，永遠不會有人發現。"""
    cols = _schema_columns()
    phantom = {(t, c) for t, c in _refs() if c not in cols.get(t, set())}
    assert not phantom, f'schema.sql 查不到這些欄位：{sorted(phantom)}'


def test_no_duplicate_entries():
    assert len(REFS) == len(_refs())


def test_the_old_wrong_table_name_is_gone():
    assert ('course_attendance', 'user_id') not in _refs()
    assert ('session_attendance', 'user_id') in _refs()
    assert ('audit_logs', 'actor_id') in _refs()


_USER_COL = re.compile(r'^(user_id|\w+_by|owner_id|actor_id|leader_user_id|participant_user_id)$')
#  程式碼寫入、名字長得像使用者引用、但**不是**指向 users.id 的欄位（每一個要寫理由）
NOT_A_USER_REF = {
    ('gospel_inquiries', 'assigned_to'): 'text，不是 uuid',
}


def _written_user_columns():
    """AST：routes/*.py 裡 .table('X').insert/update/upsert({...'col':...}) 的 (X, col)。"""
    found = set()
    for f in (ROOT / 'routes').glob('*.py'):
        tree = ast.parse(f.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('insert', 'update', 'upsert') and node.args):
                continue
            cur, table = node.func.value, None
            while isinstance(cur, (ast.Call, ast.Attribute)):
                if (isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute)
                        and cur.func.attr == 'table' and cur.args and isinstance(cur.args[0], ast.Constant)):
                    table = cur.args[0].value
                    break
                cur = cur.func.value if isinstance(cur, ast.Call) else cur.value
            if not table:
                continue
            payloads = node.args[0].elts if isinstance(node.args[0], ast.List) else [node.args[0]]
            for p in payloads:
                if isinstance(p, ast.Dict):
                    for k in p.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str) and _USER_COL.match(k.value):
                            found.add((table, k.value))
    return found


#  這些寫入的欄位名字像使用者引用，但本系統刻意不把它們當引用搬（每一個要寫理由）
INTENTIONALLY_NOT_MOVED = {
    ('rc_audit', 'actor_id'): '聚會點名與使用者帳號脫鉤：操作者只存 id＋姓名快照，不是引用',
    ('rc_sessions', 'created_by'): '同上', ('rc_sessions', 'locked_by'): '同上',
    ('rc_records', 'marked_by'): '同上', ('rc_records', 'modified_by'): '同上',
    ('rc_guest_counts', 'filled_by'): '同上', ('rc_rate_rules', 'created_by'): '同上',
}


def test_every_user_column_the_code_writes_is_in_the_registry():
    """程式碼往哪些「看起來是使用者」的欄位寫入，合併就要搬哪些。"""
    missing = (_written_user_columns() - _refs() - set(NOT_A_USER_REF)
               - set(INTENTIONALLY_NOT_MOVED) - {('users', 'id')})
    assert not missing, (
        f'程式碼寫入了這些欄位，但合併清單沒有：{sorted(missing)}。'
        '若它確實指向 users.id 就加進 user_merge.REFS；否則寫進 NOT_A_USER_REF／INTENTIONALLY_NOT_MOVED 並附理由。')


def test_code_scan_actually_sees_columns():
    assert len(_written_user_columns()) >= 5


def test_roll_call_tables_are_deliberately_not_references():
    assert not [t for t, _ in _refs() if t.startswith('rc_')]


# ── 測試用的資料 ───────────────────────────────
def _seed_row(ref, owner, n):
    row = {'id': f'{ref.table}.{ref.col}-{owner}-{n}', 'created_at': 't', ref.col: owner}
    for c in ref.dedupe or ():
        row[c] = f'{c}-{n}'
    for c in ref.key:
        row.setdefault(c, f'{c}-{n}')
    return row


def _world(extra=None):
    tables = {'users': [
        {'id': KEEP, 'real_name': '舊', 'line_user_id': None, 'display_name': None, 'picture_url': None},
        {'id': DROP, 'real_name': '新', 'line_user_id': 'U123', 'display_name': 'LINE名', 'picture_url': 'p.png'}]}
    for ref in REFS:
        tables.setdefault(ref.table, []).append(_seed_row(ref, DROP, 1))
    for t, rows in (extra or {}).items():
        tables.setdefault(t, []).extend(rows)
    return FakeSupabase(**tables)


@pytest.fixture
def db(monkeypatch):
    fake = _world()
    monkeypatch.setattr(user_merge, 'supabase', fake)
    return fake


IDENT_KEEP = {'line_user_id': None, 'display_name': None, 'picture_url': None}
IDENT_DROP = {'line_user_id': 'U123', 'display_name': 'LINE名', 'picture_url': 'p.png'}


def _do():
    return merge_users(KEEP, DROP, keep_before=IDENT_KEEP, drop_before=IDENT_DROP, new_identity=IDENT_DROP)


def _dump(fake):
    return {t: sorted(json.dumps(r, sort_keys=True) for r in rows) for t, rows in fake.data.items()}


# ── 2. 每個欄位真的會被搬 ────────────────────────
@pytest.mark.parametrize('ref', REFS, ids=label)
def test_every_reference_is_moved(db, ref):
    _do()
    rows = [r for r in db.rows(ref.table) if str(r.get('id', '')).startswith(f'{ref.table}.{ref.col}-')]
    assert rows, '種子資料不見了'
    assert all(r[ref.col] == KEEP for r in rows), f'{label(ref)} 沒有被搬到留下的帳號'
    assert not [r for r in db.rows(ref.table) if r.get(ref.col) == DROP]


def test_old_user_deleted_and_identity_moved(db):
    summary = _do()
    assert {u['id'] for u in db.rows('users')} == {KEEP}
    keep = db.rows('users')[0]
    assert (keep['line_user_id'], keep['display_name']) == ('U123', 'LINE名')
    assert summary['total_moved'] == len(REFS)


def test_preview_counts_without_writing(db):
    before = _dump(db)
    s = preview(KEEP, DROP)
    assert s['total_moved'] == len(REFS)
    assert _dump(db) == before and not db.log


# ── 4. 唯一限制衝突 ─────────────────────────────
def test_group_membership_is_a_union_and_keeps_the_existing_row(monkeypatch):
    fake = FakeSupabase(users=[{'id': KEEP}, {'id': DROP}], group_members=[
        {'group_id': 'g1', 'user_id': KEEP, 'role': 'keep'},
        {'group_id': 'g1', 'user_id': DROP, 'role': 'drop'},       # 兩邊都在 g1：只留 keep 那一列
        {'group_id': 'g2', 'user_id': DROP, 'role': 'drop'}])
    monkeypatch.setattr(user_merge, 'supabase', fake)
    monkeypatch.setattr(user_merge, 'REFS', [r for r in REFS if r.table == 'group_members'])
    s = _do()
    rows = {r['group_id']: r for r in fake.rows('group_members')}
    assert set(rows) == {'g1', 'g2'} and all(r['user_id'] == KEEP for r in rows.values())
    assert rows['g1']['role'] == 'keep'
    assert s['duplicates_dropped'] == {'group_members.user_id': 1}


def test_cell_leadership_duplicate_is_ignored(monkeypatch):
    fake = FakeSupabase(users=[{'id': KEEP}, {'id': DROP}], cell_group_leaders=[
        {'id': 'a', 'user_id': KEEP, 'group_id': 'g1'}, {'id': 'b', 'user_id': DROP, 'group_id': 'g1'},
        {'id': 'c', 'user_id': DROP, 'group_id': 'g2'}])
    monkeypatch.setattr(user_merge, 'supabase', fake)
    monkeypatch.setattr(user_merge, 'REFS', [r for r in REFS if r.table == 'cell_group_leaders'])
    _do()
    assert sorted(r['group_id'] for r in fake.rows('cell_group_leaders')) == ['g1', 'g2']
    assert {r['user_id'] for r in fake.rows('cell_group_leaders')} == {KEEP}


def test_tables_with_different_content_never_silently_drop(db):
    """兩邊內容不一樣的表不在 dedupe 清單：默默丟掉哪一邊都是在替人做決定。"""
    for r in REFS:
        if r.table in ('staff_profiles', 'session_attendance', 'course_enrollments',
                       'course_certifications', 'course_certificates'):
            assert r.dedupe is None, label(r)


def _fail_on(monkeypatch, table, op, col=None):
    orig = _Query.execute

    def boom(self):
        hit = self.table_name == table and self._op == op
        if hit and col is not None:
            hit = (self._payload or {}).get(col) == KEEP or any(f[1] == col for f in self._filters)
        if hit:
            raise RuntimeError('db down')
        return orig(self)
    monkeypatch.setattr(_Query, 'execute', boom)
    return orig


def test_conflict_in_non_dedupe_table_aborts_and_restores(db, monkeypatch):
    orig = _Query.execute

    def boom(self):
        if self.table_name == 'staff_profiles' and self._op == 'update':
            raise RuntimeError('duplicate key value violates unique constraint')
        return orig(self)
    monkeypatch.setattr(_Query, 'execute', boom)
    before = _dump(db)
    with pytest.raises(MergeError) as ei:
        _do()
    monkeypatch.setattr(_Query, 'execute', orig)
    assert 'staff_profiles' in ei.value.message and ei.value.rolled_back
    assert _dump(db) == before


# ── 3. 失敗：中止、全部還原、不刪帳號 ─────────────
@pytest.mark.parametrize('ref', REFS, ids=label)
def test_failure_at_any_reference_rolls_everything_back(db, monkeypatch, ref):
    before = _dump(db)
    orig = _fail_on(monkeypatch, ref.table, 'update', ref.col)
    with pytest.raises(MergeError) as ei:
        _do()
    monkeypatch.setattr(_Query, 'execute', orig)
    assert ei.value.rolled_back and label(ref) in ei.value.message
    assert {u['id'] for u in db.rows('users')} == {KEEP, DROP}, '失敗了還刪帳號'
    assert _dump(db) == before, '失敗後資料沒有回到原樣（半合併）'


def test_failure_deleting_the_user_rolls_back_every_move(db, monkeypatch):
    before = _dump(db)
    orig = _fail_on(monkeypatch, 'users', 'delete')
    with pytest.raises(MergeError):
        _do()
    monkeypatch.setattr(_Query, 'execute', orig)
    assert _dump(db) == before


def test_failure_restores_deleted_duplicates(monkeypatch):
    fake = FakeSupabase(users=[
        {'id': KEEP, **IDENT_KEEP}, {'id': DROP, **IDENT_DROP}],
        cell_group_leaders=[{'id': 'a', 'user_id': KEEP, 'group_id': 'g1', 'created_at': 't'},
                            {'id': 'b', 'user_id': DROP, 'group_id': 'g1', 'created_at': 't'},   # 重複：會被刪掉
                            {'id': 'c', 'user_id': DROP, 'group_id': 'g2', 'created_at': 't'}],
        files=[{'id': 'f', 'owner_id': DROP}])
    monkeypatch.setattr(user_merge, 'supabase', fake)
    monkeypatch.setattr(user_merge, 'REFS', [r for r in REFS if r.table in ('cell_group_leaders', 'files')])
    before = _dump(fake)
    orig = _fail_on(monkeypatch, 'files', 'update')
    with pytest.raises(MergeError):
        _do()
    monkeypatch.setattr(_Query, 'execute', orig)
    assert _dump(fake) == before                        # 被刪掉的重複列也補回來了


def test_read_failure_touches_nothing(db, monkeypatch):
    before = _dump(db)
    orig = _fail_on(monkeypatch, 'audit_logs', 'select')
    with pytest.raises(MergeError):
        _do()
    monkeypatch.setattr(_Query, 'execute', orig)
    assert _dump(db) == before and not db.log


def test_rollback_failure_is_reported_not_hidden(db, monkeypatch):
    orig = _Query.execute

    def boom(self):
        if self.table_name == 'events' and self._op == 'update':
            raise RuntimeError('db down')                # 搬 events 失敗
        if self.table_name == 'registrations' and self._op == 'update' \
                and (self._payload or {}).get('user_id') == DROP:
            raise RuntimeError('db down')                # 還原 registrations 也失敗
        return orig(self)
    monkeypatch.setattr(_Query, 'execute', boom)
    with pytest.raises(MergeError) as ei:
        _do()
    monkeypatch.setattr(_Query, 'execute', orig)
    assert ei.value.rolled_back is False and '人工檢查' in ei.value.message


def test_identity_is_restored_on_failure(db, monkeypatch):
    orig = _fail_on(monkeypatch, 'files', 'update')
    with pytest.raises(MergeError):
        _do()
    monkeypatch.setattr(_Query, 'execute', orig)
    users = {u['id']: u for u in db.rows('users')}
    assert users[KEEP]['line_user_id'] is None and users[DROP]['line_user_id'] == 'U123'


def test_update_that_silently_changes_nothing_aborts(db, monkeypatch):
    """更新成功但沒有任何列被改（例如被 RLS 靜靜擋掉）：搬完檢查仍有殘留 → 中止並還原。"""
    orig = _Query.execute

    def noop(self):
        if self.table_name == 'notifications' and self._op == 'update':
            return type('R', (), {'data': []})()
        return orig(self)
    monkeypatch.setattr(_Query, 'execute', noop)
    before = _dump(db)
    with pytest.raises(MergeError) as ei:
        _do()
    monkeypatch.setattr(_Query, 'execute', orig)
    assert 'notifications' in ei.value.message and _dump(db) == before


# ── 5. 結構：兩個入口都走同一份 ─────────────────────
def _func_src(path, name):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.unparse(fn)


@pytest.mark.parametrize('path,fn', [('routes/admin.py', 'merge_line_account'),
                                     ('routes/profile.py', 'merge_confirm')])
def test_both_flows_use_the_shared_merge(path, fn):
    src = _func_src(path, fn)
    assert 'merge_users(' in src and 'MergeError' in src
    assert 'transfer_user_records' not in src
    assert ".table('users').delete()" not in src, '又自己刪帳號了'


def test_old_account_merge_cannot_come_back():
    assert not (ROOT / 'routes' / 'account_merge.py').exists()
    import structure_scan as scan
    for f in (ROOT / 'routes').glob('*.py'):
        assert 'transfer_user_records' not in scan.strip_py(f.read_text(encoding='utf-8')), f.name


def test_user_merge_never_swallows_errors():
    tree = ast.parse((ROOT / 'routes' / 'user_merge.py').read_text(encoding='utf-8'))
    for n in ast.walk(tree):
        if isinstance(n, ast.ExceptHandler):
            assert not (len(n.body) == 1 and isinstance(n.body[0], ast.Pass)), 'except: pass'


# ── 兩個入口的端對端 ───────────────────────────────
@pytest.fixture
def flows(monkeypatch):
    from flask import Blueprint, Flask
    import routes.admin as admin
    import routes.audit as audit
    import routes.auth as auth
    import routes.permissions as perm
    import routes.profile as profile
    fake = _world({'cell_group_leaders': [], 'audit_logs': []})
    # 手動帳號（保留）不能已經綁 LINE；LINE 帳號（刪除）有身分
    for m in (admin, audit, auth, perm, profile, user_merge):
        monkeypatch.setattr(m, 'supabase', fake)
    monkeypatch.setattr(admin.Config, 'ADMIN_LINE_USER_IDS', [], raising=False)
    app = Flask(__name__)
    app.secret_key = 't'
    authbp = Blueprint('auth', __name__)
    authbp.add_url_rule('/auth/login', 'login_page', lambda: 'login')
    app.register_blueprint(authbp)
    evt = Blueprint('event', __name__)
    evt.add_url_rule('/', 'portal', lambda: 'portal')
    app.register_blueprint(evt)
    app.register_blueprint(admin.admin_bp)
    app.register_blueprint(profile.profile_bp)

    class Client:
        def __init__(self, c): self.c = c
        def post(self, url, **kw):
            kw.setdefault('headers', {})['X-CSRF-Token'] = 'tok'
            return self.c.post(url, **kw)

    def client(**flags):
        c = app.test_client()
        with c.session_transaction() as s:
            s.update(_csrf_token='tok', **flags)
        return Client(c)
    return fake, client


def test_admin_endpoint_moves_everything_and_audits_counts(flows):
    fake, client = flows
    c = client(user_id='admin-uuid', is_admin=True, is_super_admin=True, real_name='超管')
    r = c.post(f'/admin/api/users/{KEEP}/merge-line', json={'line_user_id': 'U123'})
    assert r.status_code == 200 and r.get_json()['success'] is True
    assert {u['id'] for u in fake.rows('users')} == {KEEP}
    assert all(row[ref.col] != DROP for ref in REFS for row in fake.rows(ref.table) if ref.col in row)
    audit = [a for a in fake.rows('audit_logs') if a.get('action') == 'user.merge_line_admin']
    assert audit and audit[-1]['detail']['moved'] and 'failed_tables' not in audit[-1]['detail']


def test_admin_endpoint_failure_returns_error_keeps_both_accounts_and_audits(flows, monkeypatch):
    fake, client = flows
    before_users = {u['id']: dict(u) for u in fake.rows('users')}
    _fail_on(monkeypatch, 'files', 'update')
    c = client(user_id='admin-uuid', is_admin=True, is_super_admin=True, real_name='超管')
    r = c.post(f'/admin/api/users/{KEEP}/merge-line', json={'line_user_id': 'U123'})
    assert r.status_code == 500 and r.get_json()['rolled_back'] is True
    assert {u['id']: u for u in fake.rows('users')} == before_users
    assert any(a.get('action') == 'user.merge_line_admin_failed' for a in fake.rows('audit_logs'))


def test_non_super_admin_cannot_merge(flows):
    fake, client = flows
    r = client(user_id='a', is_admin=True, real_name='管理員').post(
        f'/admin/api/users/{KEEP}/merge-line', json={'line_user_id': 'U123'})
    assert r.status_code == 403 and {u['id'] for u in fake.rows('users')} == {KEEP, DROP}


def test_self_merge_endpoint_moves_into_the_existing_account(flows):
    fake, client = flows
    #  本人登入的是「新 LINE 帳號」(DROP)，要併進既有的手動帳號 (KEEP)
    r = client(user_id=DROP, real_name='新').post('/profile/merge-confirm', json={'candidate_id': KEEP})
    assert r.status_code == 200 and r.get_json()['success'] is True
    assert {u['id'] for u in fake.rows('users')} == {KEEP}
    assert fake.rows('users')[0]['line_user_id'] == 'U123'
    assert any(a.get('action') == 'user.merge_line_self' for a in fake.rows('audit_logs'))


def test_self_merge_failure_keeps_both_accounts(flows, monkeypatch):
    fake, client = flows
    _fail_on(monkeypatch, 'folders', 'update')
    r = client(user_id=DROP, real_name='新').post('/profile/merge-confirm', json={'candidate_id': KEEP})
    assert r.status_code == 500 and r.get_json()['rolled_back'] is True
    users = {u['id']: u for u in fake.rows('users')}
    assert set(users) == {KEEP, DROP} and users[DROP]['line_user_id'] == 'U123' and users[KEEP]['line_user_id'] is None
