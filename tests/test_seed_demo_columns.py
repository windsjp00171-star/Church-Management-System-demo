"""展示資料腳本寫的每個欄位 schema.sql 都要有（寫錯會被 safe_insert 的警告吞掉，整張表靜靜地沒資料）。"""
import importlib
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL = re.sub(r'--[^\n]*', '', (ROOT / 'schema.sql').read_text(encoding='utf-8'))


def _columns():
    cols = {}
    for name, body in re.findall(r'CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);', SQL, re.S):
        cols[name] = set(re.findall(r'^\s+(\w+)\s', body, re.M))
    for name, body in re.findall(r'ALTER TABLE (\w+)\s+(ADD COLUMN.*?);', SQL, re.S):
        cols.setdefault(name, set()).update(re.findall(r'ADD COLUMN IF NOT EXISTS (\w+)', body))
    return cols


def test_seed_only_writes_columns_that_exist(monkeypatch):
    written = {}

    class Table:
        def __init__(self, name):
            self.name = name

        def insert(self, rows, **_):
            for r in rows if isinstance(rows, list) else [rows]:
                written.setdefault(self.name, set()).update(r)
            return self

        upsert = insert

        def execute(self):
            return types.SimpleNamespace(data=[])

    monkeypatch.setitem(sys.modules, 'supabase', types.SimpleNamespace(
        create_client=lambda *a: types.SimpleNamespace(table=Table)))
    monkeypatch.setenv('SUPABASE_URL', 'http://x')
    monkeypatch.setenv('SUPABASE_KEY', 'x')
    sys.modules.pop('seed_demo', None)
    seed_demo = importlib.import_module('seed_demo')
    monkeypatch.setattr(seed_demo, 'save_ids', lambda ids: None)
    try:
        seed_demo.seed()
    finally:
        sys.modules.pop('seed_demo', None)
    cols = _columns()
    bad = {t: sorted(c - cols.get(t, set())) for t, c in written.items() if c - cols.get(t, set())}
    assert len(written) > 25 and not bad, bad
