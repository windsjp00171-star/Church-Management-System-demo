"""階段 A 結構守衛（棘輪式）：現況先記成基準，之後只准減少、不准增加。

基準在 tests/structure_baseline.json。數字「減少」時測試也會紅，提醒你把基準往下調
（執行 `python tests/structure_scan.py`），這樣進步才不會被之後的退步吃掉。
"""
import structure_scan as scan

BASE = scan.load_baseline()


def _ratchet(actual, baseline, what):
    grew = {k: (baseline.get(k, 0), v) for k, v in actual.items() if v > baseline.get(k, 0)}
    assert not grew, f'{what}增加了（檔案：基準→現在）：{grew}'
    shrunk = {k: (v, actual.get(k, 0)) for k, v in baseline.items() if actual.get(k, 0) < v}
    assert not shrunk, f'{what}減少了，請執行 `python tests/structure_scan.py` 把基準往下調：{shrunk}'


def test_baseline_file_is_loadable_and_sane():
    assert set(BASE) == {'users_table_hits', 'date_today_hits', 'ungated_admin_routes', 'or_zero_hits'}


# ── 新模組不得直接查 users（既有的凍結，只減不增）──────────────
def test_users_table_access_is_frozen():
    _ratchet(scan.users_table_hits(), BASE['users_table_hits'], '直接查 users 的次數')


def test_new_modules_never_touch_the_users_table():
    hits = scan.users_table_hits()
    for f in ('routes/roll_call.py', 'roll_call_logic.py'):
        assert f not in hits, f'{f} 不得直接查 users（點名與使用者帳號脫鉤）'


def test_users_rows_are_only_deleted_where_we_already_knew():
    """目前只有兩個帳號合併入口會刪 users 列（admin.py 管理員合併、profile.py 自助合併）。
    已決定沿用成熟版的合併做法（全部搬完才刪），所以這兩處是已知的；其他地方出現就是新的刪除路徑。"""
    import re
    allowed = {'routes/admin.py', 'routes/profile.py'}
    for f in scan.py_files():
        src = scan.strip_py(f.read_text(encoding='utf-8'))
        if re.search(r"table\(\s*['\"]users['\"]\s*\)\s*\.\s*delete\(", src):
            assert scan.rel(f) in allowed, f'{scan.rel(f)} 新增了刪除 users 列的路徑'


# ── 時間：不依賴伺服器時區 ───────────────────────────────────
def test_server_timezone_date_calls_are_frozen():
    _ratchet(scan.date_today_hits(), BASE['date_today_hits'], '依伺服器時區取日期的寫法')


def test_new_modules_have_no_server_timezone_dates():
    hits = scan.date_today_hits()
    for f in ('routes/roll_call.py', 'roll_call_logic.py'):
        assert f not in hits, f'{f} 不得用 date.today()／無時區的 now()'


# ── 空白不得當 0 ────────────────────────────────────────────
def test_or_zero_pattern_is_frozen():
    _ratchet(scan.or_zero_hits(), BASE['or_zero_hits'], '`or 0` 的次數')


# ── /admin 路由的權限 ───────────────────────────────────────
def test_every_admin_route_has_some_gate():
    """每一個 /admin 路由都要有閘門：管理員／同工裝飾器，或函式開頭手寫的管理員檢查。"""
    assert scan.unprotected_admin_routes() == []


def test_admin_routes_without_the_admin_decorator_are_frozen():
    """沒掛 admin_required 的 /admin 路由清單只准減少（要遷移成裝飾器）。"""
    now, base = set(scan.ungated_admin_routes()), set(BASE['ungated_admin_routes'])
    assert now <= base, f'新增了沒掛 admin_required 的 /admin 路由：{sorted(now - base)}'
    assert now == base, f'有路由已改用裝飾器，請更新基準：{sorted(base - now)}'


def test_new_admin_routes_use_the_decorator():
    for f, fn, path, names in scan.admin_routes():
        if f in ('routes/roll_call.py',):
            assert names & scan.ADMIN_GATES or fn in ('home', 'session_page', 'print_roster', 'api_mark',
                                                      'api_mark_all_present', 'api_count'), (f, fn)
