"""小組長看組員的讀經進度（依週間小組）。

守住的事：只有組長／管理員／牧者看得到；組員只算「已確認＋連結帳號」的（不用姓名猜帳號）；
一個人讀超過 1000 列也不能被截斷；查不到進度不印 0；沒連結的只講人數；兒童小組不在內；
這一頁**不講落後、不排名**。
"""
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

from routes import bible_plan as B

ROOT = Path(__file__).resolve().parent.parent


class Q:
    """會記下過濾條件、支援 range 的小替身。"""
    def __init__(self, rows, log, name):
        self.rows, self.log, self.name, self.rng = rows, log, name, None

    def __getattr__(self, m):
        def f(*a, **k):
            self.log.append((self.name, m, a))
            if m == 'range':
                self.rng = a
            return self
        return f

    def execute(self):
        rows = self.rows
        if self.rng:
            rows = rows[self.rng[0]:self.rng[1] + 1]
        return types.SimpleNamespace(data=list(rows))


def _sb(log=None, **tables):
    log = [] if log is None else log
    return MagicMock(table=lambda n: Q(tables.get(n, []), log, n)), log


G1 = {'id': 'g1', 'name': '週二小組', 'weekly_gather_day': '二', 'is_children_group': False}
KIDS = {'id': 'g2', 'name': '兒童組', 'weekly_gather_day': '日', 'is_children_group': True}


def test_a_leader_sees_only_the_groups_they_lead_and_never_the_kids_group():
    sb, _ = _sb(cell_group_leaders=[{'group_id': 'g1'}, {'group_id': 'g2'}], cell_groups=[G1, KIDS])
    assert [g['id'] for g in B.viewable_groups('u1', sb=sb)] == ['g1']


def test_someone_who_leads_nothing_sees_nothing():
    sb, _ = _sb(cell_group_leaders=[], cell_groups=[G1])
    assert B.viewable_groups('u1', sb=sb) == []


def test_admin_and_pastor_see_every_group():
    sb, log = _sb(cell_groups=[G1, KIDS])
    assert [g['id'] for g in B.viewable_groups('u1', is_all=True, sb=sb)] == ['g1']
    assert not any(n == 'cell_group_leaders' for n, *_ in log)


def test_a_database_failure_shows_no_groups_rather_than_everyone():
    sb = MagicMock(table=MagicMock(side_effect=RuntimeError('x')))
    assert B.viewable_groups('u1', sb=sb) == []


def test_members_must_be_confirmed_and_linked_and_unlinked_are_only_counted():
    sb, log = _sb(
        cell_members=[{'group_id': 'g1', 'name': '王', 'user_id': 'u2'},
                      {'group_id': 'g1', 'name': '李', 'user_id': None}],
        bible_reading_progress=[{'user_id': 'u2', 'day_no': i} for i in range(1, 11)])
    out = B.group_progress([G1], sb=sb)
    assert out[0]['members'] == [{'name': '王', 'done': 10}] and out[0]['unlinked'] == 1
    filters = [a for n, m, a in log if n == 'cell_members' and m == 'eq']
    assert ('is_confirmed', True) in filters and ('is_active', True) in filters, '沒確認的組員不可以出現'


def test_more_than_a_thousand_rows_are_not_truncated():
    """★ 十個人就會超過 PostgREST 一次 1000 筆；不分頁的話排後面的人會被當成讀得少。"""
    rows = [{'user_id': 'u2', 'day_no': 1}] * 400 + [{'user_id': 'u3', 'day_no': 1}] * 365 + \
           [{'user_id': 'u4', 'day_no': 1}] * 365
    sb, _ = _sb(cell_members=[{'group_id': 'g1', 'name': n, 'user_id': u}
                              for n, u in (('甲', 'u2'), ('乙', 'u3'), ('丙', 'u4'))],
                bible_reading_progress=rows)
    got = {m['name']: m['done'] for m in B.group_progress([G1], sb=sb)[0]['members']}
    assert got == {'甲': 400, '乙': 365, '丙': 365}


def test_unreadable_progress_is_not_printed_as_zero():
    sb, _ = _sb(cell_members=[{'group_id': 'g1', 'name': '王', 'user_id': 'u2'}])
    real = sb.table

    def table(n):
        if n == 'bible_reading_progress':
            raise RuntimeError('down')
        return real(n)
    sb.table = table
    assert B.group_progress([G1], sb=sb)[0]['members'] == [{'name': '王', 'done': None}]


def test_a_member_is_told_that_the_leader_can_see_them():
    sb, _ = _sb(cell_members=[{'id': 'm'}])
    assert B.in_confirmed_group('u2', sb=sb) is True
    sb, _ = _sb(cell_members=[])
    assert B.in_confirmed_group('u2', sb=sb) is False


# ── 頁面 ──

def _app():
    from flask import Flask
    a = Flask(__name__, template_folder=str(ROOT / 'templates'))
    a.secret_key = 't'
    a.jinja_env.globals.update(
        csrf_token=lambda: 't', module_on=lambda *_: True, church_name='測', church_short_name='測',
        line_liff_id='', privacy_policy_url='', card_names={}, can_see=lambda *_: True,
        asset=lambda p: '/static/' + p, push_enabled=False, assistant_name='小助手')
    a.register_blueprint(B.bible_plan_bp)
    return a


def _login(c, **flags):
    with c.session_transaction() as s:
        s.update(user_id='u1', real_name='組長', member_type='member', **flags)
    return c


def test_a_non_leader_is_sent_back_to_their_own_page(monkeypatch):
    monkeypatch.setattr(B, 'viewable_groups', lambda *a, **k: [])
    r = _login(_app().test_client()).get('/reading/group')
    assert r.status_code == 302 and r.headers['Location'].endswith('/reading')


def test_the_page_shows_counts_without_ranking_or_blame(monkeypatch):
    monkeypatch.setattr(B, 'viewable_groups', lambda *a, **k: [G1])
    monkeypatch.setattr(B, 'group_progress', lambda groups, sb=None: [
        {'group': G1, 'members': [{'name': '王', 'done': 10}, {'name': '李', 'done': 0}], 'unlinked': 2}])
    html = _login(_app().test_client()).get('/reading/group').get_data(as_text=True)
    assert '週二小組' in html and '10 / 365' in html and '0 / 365' in html
    assert '另有 2 位組員還沒有連結帳號' in html
    for banned in ('落後', '逾期', '遲到', '沒跟上', '排名', '第一名'):
        body = html[html.index('class="bg-wrap"'):]
        assert banned not in re.sub(r'組員在自己的速讀頁[^<]*|這裡只看得到數字，不排名', '', body), f'出現了「{banned}」'


def test_the_entry_link_only_shows_for_people_who_can_use_it(monkeypatch):
    monkeypatch.setattr(B, 'in_confirmed_group', lambda *a, **k: False)
    monkeypatch.setattr(B, 'done_days', lambda *a, **k: set())
    monkeypatch.setattr(B, 'viewable_groups', lambda *a, **k: [])
    off = _login(_app().test_client()).get('/reading').get_data(as_text=True)
    monkeypatch.setattr(B, 'viewable_groups', lambda *a, **k: [G1])
    on = _login(_app().test_client()).get('/reading').get_data(as_text=True)
    assert 'href="/reading/group"' not in off and 'href="/reading/group"' in on


def test_the_group_page_is_registered_under_the_reading_module():
    import routes.modules as m
    assert m.classify('/reading/group') == 'reading'


def test_a_group_member_is_told_the_leader_can_see_their_count(monkeypatch):
    """★ 透明：被看的人要知道自己被看（只有數字）。不是組員的人不會看到這句。"""
    monkeypatch.setattr(B, 'done_days', lambda *a, **k: set())
    monkeypatch.setattr(B, 'viewable_groups', lambda *a, **k: [])
    monkeypatch.setattr(B, 'in_confirmed_group', lambda *a, **k: True)
    yes = _login(_app().test_client()).get('/reading').get_data(as_text=True)
    monkeypatch.setattr(B, 'in_confirmed_group', lambda *a, **k: False)
    no = _login(_app().test_client()).get('/reading').get_data(as_text=True)
    assert '小組長看得到你讀了幾格' in yes and '小組長看得到你讀了幾格' not in no
