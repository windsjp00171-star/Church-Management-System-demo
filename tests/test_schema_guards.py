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


# ── 程式寫入的每個欄位，schema.sql 都要有（守衛 13 的欄位層級）────────────
def _schema_columns():
    cols = {}
    for m in re.finditer(r'CREATE TABLE(?: IF NOT EXISTS)?\s+(?:public\.)?(\w+)\s*\((.*?)\n\);', SCHEMA_CODE, re.S | re.I):
        t, body = m.groups()
        cols.setdefault(t, set())
        for line in body.split('\n'):
            c = re.match(r'\s*(\w+)\s+[A-Za-z]', line)
            if c and c.group(1).upper() not in ('PRIMARY', 'UNIQUE', 'CHECK', 'FOREIGN', 'CONSTRAINT'):
                cols[t].add(c.group(1))
    for m in re.finditer(r'ALTER TABLE\s+(?:public\.)?(\w+)\s+(.*?);', SCHEMA_CODE, re.S | re.I):
        for c in re.findall(r'ADD COLUMN(?: IF NOT EXISTS)?\s+(\w+)', m.group(2)):
            cols.setdefault(m.group(1), set()).add(c)
    return cols


def _written_columns():
    import ast
    out = {}
    files = list((ROOT / 'routes').glob('*.py')) + [ROOT / 'settings_store.py']
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding='utf-8'))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('insert', 'update', 'upsert') and node.args):
                continue
            cur, table = node.func.value, None
            while isinstance(cur, (ast.Call, ast.Attribute)):
                if (isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute) and cur.func.attr == 'table'
                        and cur.args and isinstance(cur.args[0], ast.Constant)):
                    table = cur.args[0].value
                    break
                cur = cur.func.value if isinstance(cur, ast.Call) else cur.value
            if not table:
                continue
            for p in (node.args[0].elts if isinstance(node.args[0], ast.List) else [node.args[0]]):
                if isinstance(p, ast.Dict):
                    for k in p.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            out.setdefault((table, k.value), set()).add(f.name)
    return out


#  已知程式會寫、schema.sql 還沒有的欄位（新專案只跑 schema.sql 時，這些寫入會失敗）。
#  ★ 只准減少；目前已經清空。之後若程式新增了寫入的欄位，要同時補進 schema.sql（和 migration）。
KNOWN_MISSING_COLUMNS = set()


def test_every_column_the_code_writes_exists_in_schema():
    cols = _schema_columns()
    assert len(cols) >= 40 and len(_written_columns()) >= 100       # 掃描器自己壞掉不能安靜地變成空集合
    missing = {(t, c) for (t, c) in _written_columns() if t in cols and c not in cols[t]}
    assert missing <= KNOWN_MISSING_COLUMNS, f'程式會寫、schema.sql 沒有的新欄位：{sorted(missing - KNOWN_MISSING_COLUMNS)}'
    assert missing == KNOWN_MISSING_COLUMNS, f'這些欄位已補上，請從 KNOWN_MISSING_COLUMNS 拿掉：{sorted(KNOWN_MISSING_COLUMNS - missing)}'


@pytest.mark.skipif(not pg_helper.AVAILABLE, reason=pg_helper.SKIP_REASON)
def test_migration_016_renames_an_old_plan_date_column_and_is_repeatable():
    """舊的資料庫（用過舊版 schema.sql）diary_plan 的欄位叫 plan_date；migration 016 要把它改成程式用的 date。"""
    psql, stop = pg_helper.start(55436)
    try:
        psql('create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;')
        assert psql(file=str(ROOT / 'schema.sql')).returncode == 0
        assert psql('ALTER TABLE diary_plan RENAME COLUMN date TO plan_date').returncode == 0   # 模擬舊資料庫
        mig = str(ROOT / 'migrations' / '016_missing_columns.sql')
        for _ in range(2):                                                                       # 可重複執行
            r = psql(file=mig)
            assert r.returncode == 0, r.stderr
        cols = psql("select string_agg(column_name, ',') from information_schema.columns "
                    "where table_name='diary_plan'").stdout
        assert 'date' in cols.split(',') and 'plan_date' not in cols.split(',')
    finally:
        stop()


# ── 沒有 LINE 帳號的人：users.line_user_id 必須可以是空的 ──────────────────
ROLES = 'create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;'


@pytest.mark.skipif(not pg_helper.AVAILABLE, reason=pg_helper.SKIP_REASON)
def test_a_person_without_a_line_account_can_exist_on_a_fresh_schema():
    """手動建立的會員、帳號合併後被清掉 LINE 身分的那一列，line_user_id 都是空的。
    schema 原本寫 NOT NULL —— 新專案上這兩個功能會直接失敗；UNIQUE 允許多個空值。"""
    psql, stop = pg_helper.start(55437)
    try:
        psql(ROLES)
        assert psql(file=str(ROOT / 'schema.sql')).returncode == 0
        for name in ('甲', '乙'):                                    # 兩個沒有 LINE 的人（建立）
            r = psql(f"insert into users (real_name, display_name, member_type) values ('{name}','{name}','member')")
            assert r.returncode == 0, r.stderr
        assert psql("insert into users (line_user_id, real_name) values ('U1','丙')").returncode == 0
        assert psql("update users set line_user_id = NULL where real_name='丙'").returncode == 0   # 合併清掉身分
        dup = psql("insert into users (line_user_id) values ('U2'), ('U2')")                       # 有值的仍然唯一
        assert dup.returncode != 0
    finally:
        stop()


@pytest.mark.skipif(not pg_helper.AVAILABLE, reason=pg_helper.SKIP_REASON)
def test_migration_017_relaxes_an_old_database_and_is_repeatable():
    psql, stop = pg_helper.start(55438)
    try:
        psql(ROLES)
        assert psql(file=str(ROOT / 'schema.sql')).returncode == 0
        assert psql('ALTER TABLE users ALTER COLUMN line_user_id SET NOT NULL').returncode == 0    # 模擬舊資料庫
        assert psql("insert into users (real_name) values ('x')").returncode != 0
        mig = str(ROOT / 'migrations' / '017_users_line_user_id_nullable.sql')
        for _ in range(2):
            r = psql(file=mig)
            assert r.returncode == 0, r.stderr
        assert psql("insert into users (real_name) values ('x')").returncode == 0
    finally:
        stop()


# ── 報名表單新欄位型別（生日、身分證、分級收費、監護人）──────────────────
NEW_TYPES = ('birthday', 'id_number', 'fee', 'guardian')


def _event_and_field_sql(ftype):
    return ("insert into events (title) values ('e') on conflict do nothing; "
            f"insert into event_fields (event_id, label, field_type) select id, 'x', '{ftype}' from events limit 1")


@pytest.mark.skipif(not pg_helper.AVAILABLE, reason=pg_helper.SKIP_REASON)
def test_fresh_schema_accepts_the_new_field_types_and_rejects_nonsense():
    psql, stop = pg_helper.start(55439)
    try:
        psql(ROLES)
        assert psql(file=str(ROOT / 'schema.sql')).returncode == 0
        for t in NEW_TYPES + ('text', 'date'):
            r = psql(_event_and_field_sql(t))
            assert r.returncode == 0, (t, r.stderr)
        assert psql(_event_and_field_sql('bogus')).returncode != 0          # 白名單還在
        assert psql("update event_fields set auto_tier = '{\"enabled\": true}'::jsonb").returncode == 0
    finally:
        stop()


@pytest.mark.skipif(not pg_helper.AVAILABLE, reason=pg_helper.SKIP_REASON)
def test_migration_018_upgrades_an_old_database_and_is_repeatable():
    psql, stop = pg_helper.start(55440)
    try:
        psql(ROLES)
        assert psql(file=str(ROOT / 'schema.sql')).returncode == 0
        # 模擬舊資料庫：只有 7 種型別、沒有 auto_tier
        assert psql('ALTER TABLE event_fields DROP COLUMN auto_tier').returncode == 0
        assert psql('ALTER TABLE event_fields DROP CONSTRAINT event_fields_field_type_check').returncode == 0
        assert psql("ALTER TABLE event_fields ADD CONSTRAINT event_fields_field_type_check CHECK (field_type IN "
                    "('text','textarea','select','checkbox','radio','number','date'))").returncode == 0
        assert psql(_event_and_field_sql('guardian')).returncode != 0          # 升級前被擋
        mig = str(ROOT / 'migrations' / '018_event_field_types.sql')
        for _ in range(2):                                                      # 可重複執行
            r = psql(file=mig)
            assert r.returncode == 0, r.stderr
        for t in NEW_TYPES:
            assert psql(_event_and_field_sql(t)).returncode == 0, t
        assert psql("update event_fields set auto_tier = '{}'::jsonb").returncode == 0
    finally:
        stop()


@pytest.mark.skipif(not pg_helper.AVAILABLE, reason=pg_helper.SKIP_REASON)
def test_fresh_schema_lets_an_open_session_be_corrected_without_a_reason_but_not_a_locked_one():
    """新專案跑整份 schema.sql 的點名函式要跟 019 同一個規則（不然新舊部署的行為不一樣）。"""
    psql, stop = pg_helper.start(55442)
    try:
        psql(ROLES)
        assert psql(file=str(ROOT / 'schema.sql')).returncode == 0
        ids = dict(t='00000000-0000-0000-0000-0000000000a1', m='00000000-0000-0000-0000-0000000000b1',
                   s='00000000-0000-0000-0000-0000000000c1')
        psql(f"""INSERT INTO rc_meeting_types(id,name,record_mode) VALUES ('{ids['t']}','主日','individual');
        INSERT INTO rc_members(id,name) VALUES ('{ids['m']}','甲');
        INSERT INTO rc_sessions(id,type_id,starts_at) VALUES ('{ids['s']}','{ids['t']}',now());""")
        save = lambda st, reason='NULL': psql(
            f"select rc_save_record('{ids['s']}','{ids['m']}','{st}',gen_random_uuid(),'操作者',{reason},false)")
        assert save('present').returncode == 0
        assert save('absent').returncode == 0 and save('present').returncode == 0        # 擦掉重打
        assert psql(f"select rc_lock_session('{ids['s']}',gen_random_uuid(),'管理員')").returncode == 0
        r = save('absent')
        assert r.returncode != 0 and '場次已鎖定' in r.stderr
        assert save('absent', "'更正'").returncode == 0
    finally:
        stop()


@pytest.mark.skipif(not pg_helper.AVAILABLE, reason=pg_helper.SKIP_REASON)
def test_migration_020_bible_reading_matches_the_schema_and_is_repeatable():
    """新專案跑整份 schema.sql 與舊專案跑 020 要得到同樣的兩張表；可重複執行；
    一人一格一次（主鍵）；刪帳號時進度跟著走；兩張表都開了 RLS。"""
    psql, stop = pg_helper.start(55460)
    try:
        psql(ROLES)
        assert psql(file=str(ROOT / 'schema.sql')).returncode == 0
        # 舊資料庫：還沒有這兩張表
        assert psql('DROP TABLE bible_reading_progress; DROP TABLE bible_chapters').returncode == 0
        mig = str(ROOT / 'migrations' / '020_bible_reading.sql')
        for _ in range(2):
            r = psql(file=mig)
            assert r.returncode == 0, r.stderr
        uid = '11111111-1111-1111-1111-111111111111'
        assert psql(f"insert into users (id, line_user_id, real_name, display_name) values ('{uid}', 'U1', '測', '測')").returncode == 0
        ins = f"insert into bible_reading_progress (user_id, plan_key, day_no, read_on) values ('{uid}', 'church365', 1, '2026-11-07')"
        assert psql(ins).returncode == 0
        assert psql(ins).returncode != 0                                         # 同一格不能有兩列
        assert psql(f"insert into bible_reading_progress (user_id, plan_key, day_no) values ('{uid}', 'church365', 0)").returncode != 0
        assert psql("insert into bible_chapters (book, chapter, verses) values ('創世記', 1, '[{\"v\":1,\"text\":\"x\"}]')").returncode == 0
        assert psql(f"delete from users where id = '{uid}'").returncode == 0
        assert psql('select count(*) from bible_reading_progress').stdout.strip() == '0'
        rls = psql("select count(*) from pg_class where relname in ('bible_reading_progress','bible_chapters') and relrowsecurity").stdout.strip()
        assert rls == '2'
    finally:
        stop()
