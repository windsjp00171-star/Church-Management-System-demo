"""小組對照（標籤小組 vs 週間小組）：只讀、照實列出差異、讀不到不說「一致」。"""
import re
import sys
import types
from pathlib import Path

import pytest

if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

from routes import group_compare as GC

ROOT = Path(__file__).resolve().parent.parent


class Q:
    def __init__(self, rows, log, name):
        self.rows, self.log, self.name, self.rng, self.filters = rows, log, name, None, []

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def range(self, a, b):
        self.rng = (a, b)
        return self

    def __getattr__(self, m):
        def f(*a, **k):
            self.log.append((self.name, m))
            return self
        return f

    def execute(self):
        rows = [r for r in self.rows if all(r.get(c) == v for c, v in self.filters)]
        if self.rng:
            rows = rows[self.rng[0]:self.rng[1] + 1]
        return types.SimpleNamespace(data=list(rows))


def _sb(**tables):
    log = []
    return types.SimpleNamespace(table=lambda n: Q(tables.get(n, []), log, n)), log


WORLD = dict(
    groups=[{'name': '週二小組', 'is_primary': True}, {'name': '週四 小組', 'is_primary': True},
            {'name': '青年牧區', 'is_primary': True}, {'name': '敬拜團', 'is_primary': False}],
    cell_groups=[{'id': 'c2', 'name': '週二小組', 'is_active': True}, {'id': 'c4', 'name': '週四小組', 'is_active': True},
                 {'id': 'c5', 'name': '週五小組', 'is_active': True}, {'id': 'cx', 'name': '舊小組', 'is_active': False}],
    users=[{'id': 'u1', 'real_name': '王', 'group_tags': ['週二小組']},
           {'id': 'u2', 'real_name': '李', 'group_tags': ['週二小組', '敬拜團']},
           {'id': 'u3', 'real_name': '陳', 'group_tags': ['青年牧區']},
           {'id': 'u4', 'real_name': '林', 'group_tags': []}],
    cell_members=[{'group_id': 'c2', 'name': '王', 'user_id': 'u1', 'is_active': True, 'is_confirmed': True},
                  {'group_id': 'c4', 'name': '李', 'user_id': 'u2', 'is_active': True, 'is_confirmed': True},
                  {'group_id': 'c5', 'name': '林', 'user_id': 'u4', 'is_active': True, 'is_confirmed': True},
                  {'group_id': 'c5', 'name': '沒帳號', 'user_id': None, 'is_active': True, 'is_confirmed': True},
                  {'group_id': 'c2', 'name': '待確認', 'user_id': 'u3', 'is_active': True, 'is_confirmed': False}]
)


def test_group_names_are_compared_ignoring_spaces_and_sub_tags_are_left_out():
    sb, _ = _sb(**WORLD)
    n = GC.compare(sb)['names']
    assert n['both'] == ['週二小組', '週四 小組']
    assert n['only_tag'] == ['青年牧區'], '副標籤（敬拜團）不參與'
    assert n['only_cell'] == ['週五小組'], '停用的週間小組不列'


def test_people_in_different_groups_are_listed():
    sb, _ = _sb(**WORLD)
    d = GC.compare(sb)
    assert d['differ'] == [{'name': '李', 'tag': ['週二小組'], 'cell': ['週四小組']}]


def test_people_on_only_one_side():
    sb, _ = _sb(**WORLD)
    d = GC.compare(sb)
    assert [r['name'] for r in d['tag_only']] == ['陳'], '待確認的組員不算在週間小組裡'
    assert [r['name'] for r in d['cell_only']] == ['林']
    assert d['unlinked'] == [('週五小組', 1)]


def test_a_matching_person_is_not_listed_anywhere():
    sb, _ = _sb(**WORLD)
    d = GC.compare(sb)
    everyone = [r['name'] for k in ('differ', 'tag_only', 'cell_only') for r in d[k]]
    assert '王' not in everyone


def test_more_than_a_thousand_users_are_read():
    users = [{'id': f'u{i}', 'real_name': f'人{i}', 'group_tags': ['週二小組']} for i in range(1500)]
    sb, _ = _sb(groups=WORLD['groups'], cell_groups=WORLD['cell_groups'], users=users, cell_members=[])
    assert len(GC.compare(sb)['tag_only']) == 1500


def test_it_never_writes():
    src = (ROOT / 'routes' / 'group_compare.py').read_text(encoding='utf-8')
    code = re.sub(r'(?m)#.*$', '', re.sub(r'"""[\s\S]*?"""', '', src))
    for banned in ('.insert(', '.update(', '.upsert(', '.delete(', 'rpc('):
        assert banned not in code


def _app():
    from flask import Flask
    a = Flask(__name__, template_folder=str(ROOT / 'templates'))
    a.secret_key = 't'
    a.jinja_env.globals.update(csrf_token=lambda: 't', module_on=lambda *_: True, church_name='測', church_short_name='測',
                               line_liff_id='', privacy_policy_url='', card_names={}, can_see=lambda *_: True,
                               asset=lambda p: '/static/' + p, push_enabled=False, assistant_name='小助手')
    a.register_blueprint(GC.group_compare_bp)
    return a


def _admin(c):
    with c.session_transaction() as s:
        s.update(user_id='a', is_admin=True, real_name='管理員', member_type='member')
    return c


def test_the_page_shows_the_differences(monkeypatch, fake_db):
    sb, _ = _sb(**WORLD)
    monkeypatch.setattr(GC, 'supabase', sb)
    html = _admin(_app().test_client()).get('/admin/groups/compare').get_data(as_text=True)
    assert '兩邊分在不同組的人' in html and '週四小組' in html and '青年牧區' in html


def test_unreadable_data_is_not_shown_as_consistent(monkeypatch, fake_db):
    monkeypatch.setattr(GC, 'compare', lambda sb=None: (_ for _ in ()).throw(RuntimeError('down')))
    html = _admin(_app().test_client()).get('/admin/groups/compare').get_data(as_text=True)
    assert '讀不到資料' in html and '沒辦法比對' in html and '兩邊分在不同組的人' not in html
