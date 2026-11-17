"""LINE 自助合併的候選：同名＋（同標籤，或在點名名冊上的空殼帳號）。

點名單「加入新朋友」建的空殼帳號沒有標籤；不認「在名冊上」的話，新朋友用 LINE 註冊只會變第二個帳號。
"""
import sys
import types

import pytest

if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m


class Q:
    def __init__(self, rows):
        self.rows, self.f = rows, []

    def select(self, *a, **k): return self
    def eq(self, c, v): self.f.append(lambda r: r.get(c) == v); return self
    def neq(self, c, v): self.f.append(lambda r: r.get(c) != v); return self
    def in_(self, c, vs): self.f.append(lambda r: r.get(c) in vs); return self

    def execute(self):
        return types.SimpleNamespace(data=[r for r in self.rows if all(f(r) for f in self.f)])


def _sb(users, roster=(), boom=None):
    def table(n):
        if n == boom:
            raise RuntimeError('down')
        return Q({'users': users, 'rc_members': list(roster)}.get(n, []))
    return types.SimpleNamespace(table=table)


@pytest.fixture
def P(monkeypatch, fake_db):
    import importlib
    import routes.profile as P
    return P


def test_a_roster_shell_with_the_same_name_is_offered_even_without_tags(P, monkeypatch):
    monkeypatch.setattr(P, 'supabase', _sb([{'id': 'shell', 'real_name': '王小明', 'line_user_id': None, 'group_tags': []}],
                                            roster=[{'user_id': 'shell'}]))
    assert P._find_merge_candidate('王小明', [], 'me')['id'] == 'shell'


def test_a_same_name_account_not_on_the_roster_and_without_shared_tags_is_not_offered(P, monkeypatch):
    monkeypatch.setattr(P, 'supabase', _sb([{'id': 'x', 'real_name': '王小明', 'line_user_id': None, 'group_tags': ['A']}]))
    assert P._find_merge_candidate('王小明', ['B'], 'me') is None
    assert P._find_merge_candidate('王小明', [], 'me') is None


def test_the_old_rule_still_works(P, monkeypatch):
    monkeypatch.setattr(P, 'supabase', _sb([{'id': 'x', 'real_name': '王小明', 'line_user_id': None, 'group_tags': ['A']}]))
    assert P._find_merge_candidate('王小明', ['A'], 'me')['id'] == 'x'


def test_a_roster_account_that_already_has_line_is_not_offered_by_the_roster_rule(P, monkeypatch):
    monkeypatch.setattr(P, 'supabase', _sb([{'id': 'y', 'real_name': '王小明', 'line_user_id': 'L', 'group_tags': []}],
                                            roster=[{'user_id': 'y'}]))
    assert P._find_merge_candidate('王小明', [], 'me') is None


def test_a_roster_read_failure_offers_nothing(P, monkeypatch):
    monkeypatch.setattr(P, 'supabase', _sb([{'id': 's', 'real_name': '王小明', 'line_user_id': None, 'group_tags': []}],
                                            boom='rc_members'))
    assert P._find_merge_candidate('王小明', [], 'me') is None


def test_visitors_are_checked_too():
    """點名建的空殼帳號是訪客，註冊的人也可能先選訪客 —— 兩種身分都要偵測。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / 'routes' / 'profile.py').read_text(encoding='utf-8')
    assert "if member_type == 'member' and not data.get('merge_confirmed')" not in src
    assert src.count("if not data.get('merge_confirmed'):") == 2
