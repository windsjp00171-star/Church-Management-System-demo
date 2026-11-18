"""首頁「我的近期提醒」：報名的活動、上的課、有設提醒的行事（只看得到自己的；時間過了自動消失）。

守住的事：
- 取消的、候補的報名不提醒（他會以為自己沒取消成功）
- 只有「明確設了 remind_days」的行事才提醒（主日崇拜每週唸一次只會稀釋真正要緊的）
- 個人行程只撈自己的（少了 user_id 條件＝每個人看到全教會的私人行程）
- **不催繳**：這裡不講錢（使用者定的：教會內部很敏感）、不講缺席
"""
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

from routes.calendar import MAX_REMIND_DAYS
from routes.my_todos import MAX_ITEMS, MY_TODO_SOURCES, collect_my_todos, remind_days_of

ROOT = Path(__file__).resolve().parent.parent
TW = timezone(timedelta(hours=8))
NOW = datetime(2026, 7, 29, 10, 0, tzinfo=TW)


def _chain(data, record=None, name=''):
    c = MagicMock()

    def rec(m):
        def f(*a, **k):
            if record is not None:
                record.append((name, m, a))
            return c
        return f
    for m in ('select', 'eq', 'in_', 'gte', 'lte', 'gt', 'lt', 'order', 'limit', 'not_', 'is_'):
        getattr(c, m).side_effect = rec(m)
    c.execute.return_value.data = list(data)
    return c


def _sb(record=None, **by_name):
    return MagicMock(table=lambda n: _chain(by_name.get(n, []), record, n))


def _collect(**tables):
    rec = []
    with patch('routes.my_todos.supabase', _sb(rec, **tables)):
        return collect_my_todos('u1', now=NOW), rec


def test_a_registered_event_in_the_next_days_shows_up_with_its_date():
    items, _ = _collect(
        registrations=[{'event_id': 'e1'}],
        events=[{'id': 'e1', 'title': '秋之旅', 'event_start': '2026-07-30T01:00:00+00:00', 'location': '山上'}])
    assert len(items) == 1 and '秋之旅' in items[0]['title'] and items[0]['icon'] == '🎪'
    assert items[0]['link'] == '/event/e1' and '7/30' in items[0]['detail']


def test_only_active_registrations_are_asked_for():
    """★ 取消的、候補的不提醒 —— 要在查詢條件裡擋，不是事後濾。"""
    _, rec = _collect(registrations=[{'event_id': 'e1'}], events=[])
    statuses = [a for n, m, a in rec if n == 'registrations' and m == 'in_']
    assert statuses and set(statuses[0][1]) == {'registered', 'walk_in'}


def test_church_events_need_an_explicit_remind_days():
    items, _ = _collect(church_events=[
        {'id': 'c1', 'title': '洗禮', 'event_date': '2026-07-31', 'remind_days': 3},
        {'id': 'c2', 'title': '主日崇拜', 'event_date': '2026-07-30', 'remind_days': None},
        {'id': 'c3', 'title': '太遠的特會', 'event_date': '2026-08-20', 'remind_days': 3}])
    assert [i['title'] for i in items] == ['還有 2 天　洗禮']


def test_personal_events_are_filtered_to_the_owner():
    _, rec = _collect(personal_events=[])
    assert any(n == 'personal_events' and m == 'eq' and a == ('user_id', 'u1') for n, m, a in rec), \
        '個人行程沒有綁使用者'


def test_the_query_window_follows_the_max_setting():
    """★ 窗寫死的話，remind_days 設再大都沒用，而且是靜默失效。"""
    _, rec = _collect(church_events=[])
    lte = [a for n, m, a in rec if n == 'church_events' and m == 'lte']
    assert lte and lte[0][1] == (NOW + timedelta(days=MAX_REMIND_DAYS)).date().isoformat()


def test_past_items_disappear_and_the_nearest_comes_first():
    items, _ = _collect(church_events=[
        {'id': 'a', 'title': '後', 'event_date': '2026-08-05', 'remind_days': 10},
        {'id': 'b', 'title': '先', 'event_date': '2026-07-30', 'remind_days': 10}])
    assert [i['title'].split('　')[1] for i in items] == ['先', '後']


def test_the_list_is_capped():
    rows = [{'id': str(i), 'title': f't{i}', 'event_date': '2026-07-30', 'remind_days': 5}
            for i in range(MAX_ITEMS + 5)]
    items, _ = _collect(church_events=rows)
    assert len(items) == MAX_ITEMS


def test_one_broken_source_does_not_take_the_others_down(monkeypatch):
    def boom(*a):
        raise RuntimeError('x')
    monkeypatch.setattr('routes.my_todos.MY_TODO_SOURCES',
                        [boom, lambda u, n: [{'title': 'ok', 'when': NOW}]])
    assert [t['title'] for t in collect_my_todos('u1', now=NOW)] == ['ok']


def test_nobody_logged_in_gets_nothing():
    assert collect_my_todos(None) == []


@pytest.mark.parametrize('raw,expected', [(None, 0), ('', 0), (0, 0), (3, 3), ('5', 5), (-2, 0), ('abc', 0)])
def test_remind_days_parsing(raw, expected):
    assert remind_days_of({'remind_days': raw}) == expected


def test_there_is_no_money_and_no_absence_here():
    """★★ 這裡**刻意沒有**「還沒繳費」（不催繳是使用者定的）、也不講缺席。
    看起來像漏掉一個功能，其實是刻意的 —— 先去掉註解再掃（註解裡就在解釋這件事）。"""
    src = (ROOT / 'routes' / 'my_todos.py').read_text(encoding='utf-8')
    code = re.sub(r'(?m)#.*$', '', re.sub(r'"""[\s\S]*?"""', '', src))
    for banned in ('payment_status', 'unpaid', '未繳', '繳費', '缺席', '缺課', 'absence'):
        assert banned not in code, f'my_todos 出現了「{banned}」'
    assert len(MY_TODO_SOURCES) == 3


def test_the_home_page_really_renders_them():
    """★ 寫好了但沒接上＝首頁完全沒有變化。真 app（子行程）看首頁有沒有那一區的標記不夠（空資料庫沒有提醒），
    所以驗接線：route 有傳 my_todos、模板有畫。"""
    py = re.sub(r'(?m)#.*$', '', (ROOT / 'routes' / 'event.py').read_text(encoding='utf-8'))
    assert 'collect_my_todos(uid)' in py and 'my_todos=my_todos' in py
    html = re.sub(r'\{#.*?#\}', '', (ROOT / 'templates' / 'portal.html').read_text(encoding='utf-8'), flags=re.S)
    assert '{% for t in my_todos %}' in html and 'data-tour="my-todos"' in html


def test_a_fixed_event_today_without_remind_days_is_not_nagged():
    """★ 「今天」那天最容易漏：沒設 remind_days 的主日崇拜，今天當天也不可以出現
    （days=0 不大於 remind_days=0，所以只靠窗判斷會放它進來）。"""
    items, _ = _collect(church_events=[
        {'id': 'c2', 'title': '主日崇拜', 'event_date': '2026-07-29', 'remind_days': None},
        {'id': 'c3', 'title': '每週小組', 'event_date': '2026-07-29', 'remind_days': 0}])
    assert items == []
