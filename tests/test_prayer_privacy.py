"""代禱：匿名就是匿名 —— 回給瀏覽器的 JSON 不可以帶作者的 user_id。"""
import importlib
import sys
import types

import pytest

from fake_supabase import FakeSupabase


@pytest.fixture
def prayer(monkeypatch):
    db = FakeSupabase(prayer_comments=[
        {'id': 'c1', 'prayer_id': 'p1', 'user_id': 'secret-author', 'content': '匿名留言', 'is_anonymous': True},
        {'id': 'c2', 'prayer_id': 'p1', 'user_id': 'me', 'content': '我的留言', 'is_anonymous': False},
    ])
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=db))
    sys.modules.pop('routes.prayer', None)
    mod = importlib.import_module('routes.prayer')
    monkeypatch.setattr(mod, 'get_user_display', lambda uid, anon: ('匿名' if anon else '某人', ''))
    from flask import Flask
    app = Flask(__name__)
    app.secret_key = 't'
    app.register_blueprint(mod.prayer_bp)
    c = app.test_client()
    with c.session_transaction() as s:
        s['user_id'] = 'me'
    yield c
    sys.modules.pop('routes.prayer', None)


def test_comment_json_never_carries_the_author_id(prayer):
    j = prayer.get('/prayer/p1/comments').get_json()
    assert j['success'] and len(j['comments']) == 2
    assert all('user_id' not in c for c in j['comments'])
    assert 'secret-author' not in prayer.get('/prayer/p1/comments').get_data(as_text=True)


def test_page_still_knows_which_comment_is_mine_and_who_is_anonymous(prayer):
    by_id = {c['id']: c for c in prayer.get('/prayer/p1/comments').get_json()['comments']}
    assert by_id['c1']['is_mine'] is False and by_id['c1']['display_name'] == '匿名'
    assert by_id['c2']['is_mine'] is True


def test_login_is_still_required(prayer):
    anon = prayer.application.test_client()
    assert anon.get('/prayer/p1/comments').status_code == 401
