"""小組回報的「主日」欄以聚會點名為準（盤點第 4 步，2026-11-17）

同一個人的主日出席原本記兩次：組長在小組回報填一次、同工在點名單打勾一次，兩邊對不起來。
現在**帳號對帳號**（`cell_members.user_id` ＝ `rc_members.user_id`，不用姓名猜）時，主日讀點名；
點名還沒開始、或這個人沒連帳號，組長照舊自己填。
"""
import datetime
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

from routes import roll_call_link as L

ROOT = Path(__file__).resolve().parent.parent
WED = datetime.date(2026, 11, 11)          # 週三的小組 → 那一週的主日是 11/8
CFG = {'rc_type_id': 'T1'}


def _sb(sessions, members, records, seen=None):
    def table(name):
        rows = {'rc_sessions': sessions, 'rc_members': members, 'rc_records': records}[name]
        c = MagicMock()
        for m in ('select', 'eq', 'in_', 'gte', 'lt', 'order', 'limit'):
            def f(*a, _m=m, **k):
                if seen is not None:
                    seen.append((name, _m, a))
                return c
            getattr(c, m).side_effect = f
        c.execute.return_value.data = list(rows)
        return c
    return MagicMock(table=table)


M = [{'id': 'm1', 'user_id': 'u1', 'status': 'active', 'joined_on': None},
     {'id': 'm2', 'user_id': 'u2', 'status': 'active', 'joined_on': None}]


def test_status_comes_from_roll_call_and_unticked_is_absent():
    out = L.sunday_statuses(['u1', 'u2'], WED, CFG, sb=_sb([{'id': 's1'}], M, [{'member_id': 'm1', 'status': 'present'}]))
    assert out == {'u1': 'full', 'u2': 'absent'}


def test_not_started_yet_means_leader_fills_it():
    """★ 主日有場次但一筆都沒點：是還沒開始，不是全部沒來。"""
    assert L.sunday_statuses(['u1'], WED, CFG, sb=_sb([{'id': 's1'}], M, [])) == {}


def test_two_services_take_the_best():
    recs = [{'member_id': 'm1', 'status': 'absent'}, {'member_id': 'm1', 'status': 'late'}]
    assert L.sunday_statuses(['u1'], WED, CFG, sb=_sb([{'id': 's1'}, {'id': 's2'}], M[:1], recs))['u1'] == 'late'


def test_no_link_no_session_left_or_not_yet_joined_are_skipped():
    assert L.sunday_statuses(['u1'], WED, {}, sb=_sb([{'id': 's1'}], M, [{'member_id': 'm1', 'status': 'present'}])) == {}
    assert L.sunday_statuses(['u1'], WED, CFG, sb=_sb([], M, [])) == {}
    gone = [{'id': 'm1', 'user_id': 'u1', 'status': 'left', 'joined_on': None},
            {'id': 'm2', 'user_id': 'u2', 'status': 'active', 'joined_on': '2026-11-09'}]
    assert L.sunday_statuses(['u1', 'u2'], WED, CFG,
                             sb=_sb([{'id': 's1'}], gone, [{'member_id': 'x', 'status': 'present'}])) == {}


def test_the_sunday_is_the_one_starting_that_week():
    seen = []
    L.sunday_statuses(['u1'], WED, CFG, sb=_sb([{'id': 's1'}], M, [], seen=seen))
    lo = next(a[1] for n, m, a in seen if n == 'rc_sessions' and m == 'gte')
    assert lo.startswith('2026-11-07T16:00')                 # 台北 11/8 00:00


def test_db_failure_falls_back_to_manual():
    assert L.sunday_statuses(['u1'], WED, CFG, sb=MagicMock(table=MagicMock(side_effect=RuntimeError))) == {}


def test_report_pages_and_save_use_it():
    src = (ROOT / 'routes' / 'cell_report.py').read_text(encoding='utf-8')
    assert src.count('rc_sunday = _rc_sunday(members, week_date') == 2          # 填寫頁＋牧者查閱頁
    assert "'這週主日已由聚會點名記錄" in src                          # 手填被擋
    tpl = (ROOT / 'templates' / 'cell_report' / 'section2.html').read_text(encoding='utf-8')
    assert "rc_sunday.get(m.id|string)" in tpl and 'class="att-fixed"' in tpl
