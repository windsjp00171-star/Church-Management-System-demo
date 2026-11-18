"""結構守衛：掃原始碼／SQL（先去掉註解再掃）。"""
import re
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
SQL = (ROOT / 'migrations' / '012_roll_call.sql').read_text(encoding='utf-8')
ROUTE = (ROOT / 'routes' / 'roll_call.py').read_text(encoding='utf-8')
LOGIC = (ROOT / 'roll_call_logic.py').read_text(encoding='utf-8')


def strip_sql(s):
    return re.sub(r'--[^\n]*', '', s)


def strip_py(s):
    s = re.sub(r'"""[\s\S]*?"""', '', s)
    return re.sub(r'#[^\n]*', '', s)


SQL_CODE, ROUTE_CODE, LOGIC_CODE = strip_sql(SQL), strip_py(ROUTE), strip_py(LOGIC)
TABLES = re.findall(r'CREATE TABLE IF NOT EXISTS (rc_\w+)', SQL_CODE)


def test_tables_found():
    assert len(TABLES) >= 7


def test_point_roll_call_is_decoupled_from_users():
    """點名與使用者脫鉤：新表不得外鍵到 users；點名模組不得查 users。"""
    assert not re.search(r'REFERENCES\s+users', SQL_CODE, re.I)
    assert not re.search(r"table\(\s*['\"]users['\"]", ROUTE_CODE)
    assert 'users' not in LOGIC_CODE


def test_no_cascade_or_set_null():
    assert not re.search(r'ON DELETE\s+(CASCADE|SET NULL)', SQL_CODE, re.I)


def test_audit_is_append_only():
    assert re.search(r'BEFORE UPDATE OR DELETE ON rc_audit', SQL_CODE)
    assert re.search(r'BEFORE TRUNCATE ON rc_audit', SQL_CODE)
    assert not re.search(r"table\(\s*['\"]rc_audit['\"]\s*\)\s*\.\s*(update|delete)", ROUTE_CODE)


def test_every_table_has_rls_and_no_policy():
    for t in TABLES:
        assert re.search(rf'ALTER TABLE {t}\s+ENABLE ROW LEVEL SECURITY', SQL_CODE), t
    assert 'CREATE POLICY' not in SQL_CODE


def test_schema_covers_every_table_used_in_code():
    used = set(re.findall(r"table\(\s*['\"](rc_\w+)['\"]", ROUTE_CODE))
    assert used and used <= set(TABLES), used - set(TABLES)


def test_attendance_writes_go_through_db_functions():
    """點名紀錄不得直接寫表（會繞過稽核）；只能走 rc_* 函式。"""
    assert not re.search(r"table\(\s*['\"]rc_records['\"]\s*\)\s*\.\s*(insert|update|upsert|delete)", ROUTE_CODE)
    for fn in ('rc_save_record', 'rc_lock_session', 'rc_set_count'):
        assert f"rpc('{fn}'" in ROUTE_CODE


def test_db_enforces_reason_and_blank_count():
    assert '修改點名必須填寫原因' in SQL_CODE
    assert '場次已鎖定，修改必須填寫原因' in SQL_CODE
    assert '人數不可空白' in SQL_CODE


def test_times_are_utc_timestamptz():
    assert not re.search(r'\bTIMESTAMP\b(?!TZ)', SQL_CODE)


def test_no_sensitive_columns():
    assert not re.search(r'id_number|national_id|身分證|birthday|phone', SQL_CODE, re.I)


def test_print_template_has_no_personal_fields():
    t = (ROOT / 'templates' / 'roll_call' / 'print.html').read_text(encoding='utf-8')
    assert not re.search(r'birthday|phone|生日|電話|身分證', t.replace('不含生日、電話等個人資料', ''))


def test_templates_parse_and_have_tour_hooks():
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(ROOT / 'templates')))
    for name in ('home', 'session', 'admin', 'rates', 'print'):
        env.get_template(f'roll_call/{name}.html')       # 語法錯誤會拋例外
    for name in ('home', 'session', 'admin', 'rates'):
        text = (ROOT / 'templates' / 'roll_call' / f'{name}.html').read_text(encoding='utf-8')
        assert 'data-tour="help-btn"' in text and 'RollTour.start' in text, name


def test_tour_targets_exist():
    """教學步驟的 target 必須在同一個模板裡有對應的 data-tour。"""
    for name in ('home', 'session', 'admin', 'rates'):
        text = (ROOT / 'templates' / 'roll_call' / f'{name}.html').read_text(encoding='utf-8')
        targets = re.findall(r"target: '([\w-]+)'", text)
        for t in targets:
            assert f'data-tour="{t}"' in text, (name, t)
