"""schema.sql 守衛（守衛 13：資料庫結構涵蓋程式用到的每張表；新專案資料列權限全開）。

新的 Supabase 專案只跑 schema.sql，所以它必須獨立可跑、涵蓋程式用到的一切。
"""
import re
from pathlib import Path

import pytest

import pg_helper

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / 'schema.sql').read_text(encoding='utf-8')


def code(sql):
    return re.sub(r'--[^\n]*', '', sql)


SCHEMA_CODE = code(SCHEMA)
DEFINED = {m.lower() for m in re.findall(
    r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)\s+(?:IF NOT EXISTS\s+)?(?:public\.)?(\w+)', SCHEMA_CODE, re.I)}


def used_tables():
    names = set()
    files = list((ROOT / 'routes').glob('*.py')) + [p for p in ROOT.glob('*.py')]
    for f in files:
        names |= set(re.findall(r"\.table\(\s*['\"](\w+)['\"]\s*\)", f.read_text(encoding='utf-8')))
    return names


def test_schema_covers_every_table_the_code_uses():
    missing = used_tables() - DEFINED
    assert not missing, f'程式用到、schema.sql 沒建的表：{sorted(missing)}'


def test_session_attendance_is_not_misnamed():
    """schema 曾把 session_attendance 寫成 course_attendance，新專案的門訓點名會直接壞掉。"""
    assert 'session_attendance' in DEFINED and 'course_attendance' not in DEFINED


def test_material_transactions_columns_match_the_code():
    block = re.search(r'CREATE TABLE IF NOT EXISTS material_transactions \((.*?)\n\);', SCHEMA_CODE, re.S).group(1)
    cols = set(re.findall(r'^\s+(\w+)\s', block, re.M))
    assert {'type', 'unit_cost', 'total_cost', 'course_id', 'enrollment_id', 'notes', 'transaction_date'} <= cols


def test_rls_block_comes_after_every_create_table():
    last_create = max(m.start() for m in re.finditer(r'CREATE\s+TABLE', SCHEMA_CODE, re.I))
    rls = SCHEMA_CODE.find('ENABLE ROW LEVEL SECURITY', SCHEMA_CODE.find("pg_tables WHERE schemaname = 'public'"))
    assert rls > last_create, '安全強化區塊必須放在所有建表語句之後，否則後面建的表沒開 RLS'


def test_no_public_function_grants_left_for_anon():
    assert 'REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated' in SCHEMA_CODE


@pytest.mark.skipif(not pg_helper.AVAILABLE, reason=pg_helper.SKIP_REASON)
def test_schema_runs_on_empty_postgres_and_every_table_has_rls():
    psql, stop = pg_helper.start(55435)
    try:
        psql('create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;')
        for _ in range(2):   # 可重複執行
            r = psql(file=str(ROOT / 'schema.sql'))
            assert r.returncode == 0, r.stderr
        no_rls = psql("select string_agg(c.relname, ',') from pg_class c join pg_namespace n on n.oid=c.relnamespace "
                      "where n.nspname='public' and c.relkind='r' and not c.relrowsecurity").stdout.strip()
        assert no_rls == '', f'沒開 RLS 的表：{no_rls}'
        have = {t.strip() for t in psql("select table_name from information_schema.tables where table_schema='public'").stdout.split()}
        assert used_tables() <= have
        for fn in ('rc_save_record(uuid,uuid,text,uuid,text,text,boolean)', 'public.check_table_exists(text)'):
            assert psql(f"select has_function_privilege('anon','{fn}','execute')").stdout.strip() == 'f'
            assert psql(f"select has_function_privilege('service_role','{fn}','execute')").stdout.strip() == 't'
    finally:
        stop()
