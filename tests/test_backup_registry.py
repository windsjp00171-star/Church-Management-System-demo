"""備份／匯出登記表：每張資料表都要表態；匯入順序要外鍵安全；匯出再匯入要一筆不少（還原演練）。"""
import io
import json
import re
import sys
import types
import zipfile
from pathlib import Path

import pytest

import structure_scan as scan

if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

import backup_registry as reg                                       # noqa: E402
from fake_supabase import FakeSupabase                              # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = re.sub(r'--[^\n]*', '', (ROOT / 'schema.sql').read_text(encoding='utf-8'))


def _schema():
    tables = {}
    for m in re.finditer(r'CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);', SCHEMA, re.S):
        t, body = m.groups()
        pk = None
        one = re.search(r'^\s*(\w+)\s+[^\n]*PRIMARY KEY', body, re.M)
        if one:
            pk = (one.group(1),)
        many = re.search(r'PRIMARY KEY\s*\(([^)]*)\)', body)
        if many:
            pk = tuple(x.strip() for x in many.group(1).split(','))
        tables[t] = {'pk': pk, 'parents': set(re.findall(r'REFERENCES\s+(?:public\.)?(\w+)', body))}
    for m in re.finditer(r'ALTER TABLE\s+(\w+)\s+(.*?);', SCHEMA, re.S):
        if m.group(1) in tables:
            tables[m.group(1)]['parents'] |= set(re.findall(r'REFERENCES\s+(?:public\.)?(\w+)', m.group(2)))
    return tables


SCH = _schema()
VIEWS = set(re.findall(r'CREATE (?:OR REPLACE )?VIEW (\w+)', SCHEMA))


# ── 1. 每張表都要表態 ───────────────────────────────────
def test_schema_scan_finds_the_tables():
    assert len(SCH) >= 60 and 'users' in SCH and 'rc_audit' in SCH


def test_every_schema_table_is_backed_up_or_excluded_with_a_reason():
    covered = set(reg.TABLE_NAMES) | set(reg.EXCLUDED)
    missing = set(SCH) - covered
    assert not missing, f'這些資料表沒有進備份登記表（也沒列入排除）：{sorted(missing)}'


def test_registry_has_no_unknown_duplicate_or_overlapping_tables():
    assert len(reg.TABLE_NAMES) == len(set(reg.TABLE_NAMES)), '資料表重複登記'
    assert not (set(reg.TABLE_NAMES) & set(reg.EXCLUDED)), '同一張表又備份又排除'
    assert not set(reg.TABLE_NAMES) - set(SCH), f'登記了 schema 沒有的表：{sorted(set(reg.TABLE_NAMES) - set(SCH))}'
    assert not set(reg.EXCLUDED) - set(SCH), f'排除了 schema 沒有的表：{sorted(set(reg.EXCLUDED) - set(SCH))}'


def test_views_are_known_and_never_registered():
    assert reg.VIEWS == VIEWS
    assert not (reg.VIEWS & set(reg.TABLE_NAMES)), '檢視表只能讀、不能 upsert，不能登記成要備份的表'


def test_every_exclusion_has_a_real_reason():
    for t, why in reg.EXCLUDED.items():
        assert len(why) >= 10, t
    privacy = [t for t, w in reg.EXCLUDED.items() if '隱私' in w]
    assert {'diary_entries', 'diary_share_grants'} <= set(privacy)


def test_every_table_belongs_to_a_described_module():
    for t, m, _c in reg.TABLES:
        assert m in reg.MODULE_META, f'{t} 的模組 {m} 沒有說明'
    for key in reg.MODULE_META:
        assert any(m == key for _t, m, _c in reg.TABLES), f'模組 {key} 底下沒有任何表'


# ── 2. 匯入順序外鍵安全、衝突欄位正確 ───────────────────
def test_import_order_puts_parents_before_children():
    pos = {t: i for i, t in enumerate(reg.TABLE_NAMES)}
    bad = []
    for t in reg.TABLE_NAMES:
        for p in SCH[t]['parents']:
            if p == t:
                continue                                  # 自己指自己（courses／folders）：同一批裡處理
            if p not in pos:
                bad.append(f'{t} 指向沒有備份的表 {p}')
            elif pos[p] > pos[t]:
                bad.append(f'{t}（第 {pos[t]}）要在它的父表 {p}（第 {pos[p]}）之後')
    assert not bad, bad


def test_conflict_columns_are_the_real_primary_keys():
    for t in reg.TABLE_NAMES:
        real = SCH[t]['pk']
        assert real is not None, f'{t} 在 schema 找不到主鍵'
        assert tuple(reg.CONFLICT[t].split(',')) == real, f'{t}：登記 {reg.CONFLICT[t]}，schema 是 {real}'


# ── 3. 還原演練：匯出 → 匯入空資料庫 → 一筆不少 ──────────
def _row(table, i):
    row = {'id': f'{table}-{i}', 'created_at': 't', 'note': f'{table}#{i}'}
    pk = reg.CONFLICT[table].split(',')
    for c in pk:
        row[c] = f'{table}-{c}-{i}'
    return row


def _world(extra=None):
    tables = {t: [_row(t, 1), _row(t, 2)] for t in reg.TABLE_NAMES}
    tables['audit_logs'] = [_row('audit_logs', i) for i in range(1205)]       # 超過一頁（1000）：驗證分頁與分批
    tables['diary_entries'] = [{'id': 'secret', 'content': '私人日記'}]
    tables['notifications'] = [{'id': 'n1'}]
    tables.update(extra or {})
    return FakeSupabase(**tables)


@pytest.fixture
def dt(monkeypatch):
    sys.modules.pop('routes.data_transfer', None)
    import routes.data_transfer as m
    return m


def test_restore_drill_loses_nothing(dt, monkeypatch):
    src = _world()
    monkeypatch.setattr(dt, 'supabase', src)
    data, meta = dt.build_export(list(reg.MODULE_META))
    assert set(meta['tables']) == set(reg.TABLE_NAMES) and not meta['not_available']

    dst = FakeSupabase()                                                       # 全新的空專案
    monkeypatch.setattr(dt, 'supabase', dst)
    results = dt.import_bundle(zipfile.ZipFile(io.BytesIO(data)))
    assert not [r for r in results if r['error']], [r for r in results if r['error']]
    for t in reg.TABLE_NAMES:
        assert len(dst.rows(t)) == len(src.rows(t)), f'{t}：匯出 {len(src.rows(t))} 筆，還原後 {len(dst.rows(t))} 筆'
        assert sorted(json.dumps(r, sort_keys=True) for r in dst.rows(t)) == \
            sorted(json.dumps(r, sort_keys=True) for r in src.rows(t)), f'{t} 內容不一致'


def test_private_diaries_and_transient_tables_never_enter_the_zip(dt, monkeypatch):
    monkeypatch.setattr(dt, 'supabase', _world())
    data, meta = dt.build_export(list(reg.MODULE_META))
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    for t in reg.EXCLUDED:
        assert f'{t}.json' not in names, t
    assert 'diary_entries' in meta['excluded'] and 'material_stock.json' not in names


def test_exporting_only_selected_modules(dt, monkeypatch):
    monkeypatch.setattr(dt, 'supabase', _world())
    data, meta = dt.build_export(['roll_call', 'not-a-module'])
    assert meta['modules'] == ['roll_call']
    assert set(meta['tables']) == {t for t, m, _ in reg.TABLES if m == 'roll_call'}


# ── 4. 失敗要明講，不可以產出殘缺備份 ────────────────────
def test_a_failed_read_aborts_the_export_instead_of_writing_a_partial_zip(dt, monkeypatch):
    class Flaky(FakeSupabase):
        def table(self, name):
            if name == 'registrations':
                raise RuntimeError('connection reset')
            return super().table(name)
    monkeypatch.setattr(dt, 'supabase', Flaky(**{t: [_row(t, 1)] for t in reg.TABLE_NAMES}))
    with pytest.raises(dt.ExportError) as ei:
        dt.build_export(['events'])
    assert 'registrations' in str(ei.value)


def test_a_missing_table_is_reported_as_not_available_not_as_empty(dt, monkeypatch):
    class NoRollCall(FakeSupabase):
        def table(self, name):
            if name.startswith('rc_'):
                raise RuntimeError('PGRST205 Could not find the table public.' + name)
            return super().table(name)
    monkeypatch.setattr(dt, 'supabase', NoRollCall(**{t: [_row(t, 1)] for t in reg.TABLE_NAMES}))
    data, meta = dt.build_export(['roll_call', 'prayer'])
    assert set(meta['not_available']) == {t for t, m, _ in reg.TABLES if m == 'roll_call'}
    assert set(meta['tables']) == {'prayers', 'prayer_comments', 'prayer_reactions'}


# ── 5. 匯入：不信任 ZIP 裡的檔名 ─────────────────────────
def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('export_meta.json', '{}')
        for name, rows in files.items():
            zf.writestr(name, json.dumps(rows))
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_import_only_touches_registered_tables(dt, monkeypatch):
    dst = FakeSupabase()
    monkeypatch.setattr(dt, 'supabase', dst)
    results = dt.import_bundle(_zip({
        'prayers.json': [{'id': 'p1'}], 'diary_entries.json': [{'id': 'd1'}],
        'material_stock.json': [{'id': 'm1'}], 'pg_catalog.json': [{'id': 'x'}]}))
    assert dst.rows('prayers') and not dst.rows('diary_entries') and not dst.rows('material_stock')
    assert not dst.rows('pg_catalog')
    skipped = {r['table']: r['skipped'] for r in results if r.get('skipped')}
    assert set(skipped) == {'diary_entries', 'material_stock', 'pg_catalog'} and all(skipped.values())


def test_import_follows_the_registry_order_not_the_zip_order(dt, monkeypatch):
    order = []
    dst = FakeSupabase()
    monkeypatch.setattr(dt, 'supabase', dst)
    dt.import_bundle(_zip({'registrations.json': [{'id': 'r'}], 'users.json': [{'id': 'u'}],
                           'events.json': [{'id': 'e'}]}), upsert=lambda t, r: order.append(t) or (len(r), None))
    assert order == ['users', 'events', 'registrations']


def test_one_table_failing_is_reported_and_the_rest_continue(dt, monkeypatch):
    def upsert(table, records):
        return (0, 'boom') if table == 'events' else (len(records), None)
    results = dt.import_bundle(_zip({'users.json': [{'id': 'u'}], 'events.json': [{'id': 'e'}],
                                     'prayers.json': [{'id': 'p'}]}), upsert=upsert)
    by = {r['table']: r for r in results}
    assert by['events']['error'] == 'boom' and by['users']['imported'] == 1 and by['prayers']['imported'] == 1


def test_upsert_uses_the_registered_conflict_columns(dt, monkeypatch):
    seen = []

    class Spy:
        def table(self, name):
            return self

        def upsert(self, chunk, on_conflict=None):
            seen.append((on_conflict, len(chunk)))
            return self

        def execute(self):
            return None
    monkeypatch.setattr(dt, 'supabase', Spy())
    assert dt._upsert_batch('group_members', [{'group_id': 'g', 'user_id': 'u'}]) == (1, None)
    assert dt._upsert_batch('settings', [{'key': 'k'}]) == (1, None)
    assert dt._upsert_batch('users', [{'id': str(i)} for i in range(450)]) == (450, None)
    assert seen == [('group_id,user_id', 1), ('key', 1), ('id', 200), ('id', 200), ('id', 50)]


# ── 6. 結構 ─────────────────────────────────────────────
def test_no_hand_written_table_lists_remain():
    src = scan.strip_py((ROOT / 'routes' / 'data_transfer.py').read_text(encoding='utf-8'))
    assert 'TABLE_ORDER' not in src and "'users', 'user_groups'" not in src
    assert 'backup_registry' in src


def test_export_and_import_are_audited():
    src = scan.strip_py((ROOT / 'routes' / 'data_transfer.py').read_text(encoding='utf-8'))
    assert "log_action('data.export'" in src and "log_action('data.import'" in src


# ── 可讀 CSV 備份中心：「讀取失敗」不可以顯示成「尚未啟用」 ──────────────────────

def _load_backup_module(monkeypatch, supabase):
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=supabase))
    for name in ('routes.backup',):
        sys.modules.pop(name, None)
    import importlib
    return importlib.import_module('routes.backup')


class _Boom:
    def __init__(self, msg):
        self.msg = msg

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def range(self, *_a):
        return self

    def execute(self):
        raise RuntimeError(self.msg)


def test_backup_center_tells_read_failure_apart_from_missing_table(monkeypatch):
    mod = _load_backup_module(monkeypatch, _Boom('connection reset by peer'))
    with pytest.raises(mod.BackupReadError):
        mod._fetch('events')                      # 網路壞掉：要丟，不可以回 None

    mod = _load_backup_module(monkeypatch, _Boom('relation "events" does not exist'))
    assert mod._fetch('events') is None           # 資料表真的不存在：才是「尚未啟用」


def test_backup_center_marks_failed_category_not_as_not_enabled(monkeypatch):
    mod = _load_backup_module(monkeypatch, _Boom('timeout'))
    key, meta = next(iter(mod.CATEGORIES.items()))
    result = mod._run(meta)
    assert result.get('failed') is True and result.get('available') is False
