"""牧者查閱日記：身分一律認 users.line_user_id（登入寫的那一欄）。

以前查的是 users.line_id——沒有任何程式會寫那一欄，所以用 LINE 登入的牧者和小組長全部被擋在外面。
同時守住隱私：有牧者身分也只能看「主動授權給他」的人。
"""
import importlib
import re
import sys
import types
from pathlib import Path

import pytest
from fake_supabase import FakeSupabase

ROOT = Path(__file__).resolve().parent.parent


def _users():
    def u(i, name, **kw):
        return {'id': f'id-{i}', 'line_user_id': f'U-{i}', 'line_id': None, 'display_name': name,
                'picture_url': '', 'is_pastor': False, 'created_at': f'2026-01-0{i}', **kw}
    return [u(1, '牧師', is_pastor=True), u(2, '小組長'), u(3, '會友'),
            u(4, '空殼', line_user_id=None, is_pastor=True)]


@pytest.fixture
def diary(monkeypatch):
    db = FakeSupabase(users=_users(), cell_group_leaders=[{'user_id': 'id-2', 'group_id': 'g1'}],
                      diary_share_grants=[], diary_entries=[])
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=db))
    sys.modules.pop('routes.diary', None)
    mod = importlib.import_module('routes.diary')
    yield mod, db
    sys.modules.pop('routes.diary', None)


def test_pastor_and_leader_are_recognised_by_the_id_login_writes(diary):
    mod, _ = diary
    assert mod.sb_is_pastor('U-1') is True
    assert mod.sb_is_pastor('U-2') is True


def test_member_and_blank_are_not_pastors(diary):
    mod, _ = diary
    assert mod.sb_is_pastor('U-3') is False
    assert mod.sb_is_pastor('') is False


def test_member_can_choose_who_to_share_with(diary):
    mod, _ = diary
    assert {p['line_user_id'] for p in mod.sb_list_pastors()} == {'U-1', 'U-2'}


def test_admin_list_uses_real_ids_and_hides_people_without_line(diary):
    mod, _ = diary
    assert {r['line_user_id'] for r in mod.sb_list_users()} == {'U-1', 'U-2', 'U-3'}


def test_setting_a_pastor_changes_only_that_person(diary):
    mod, db = diary
    mod.sb_set_pastor_whitelist('U-3', '', '', True)
    assert {r['id'] for r in db.rows('users') if r['is_pastor']} == {'id-1', 'id-3', 'id-4'}


def test_pastor_without_a_grant_cannot_open_a_diary(diary):
    from flask import Blueprint, Flask
    mod, _ = diary
    app = Flask(__name__, template_folder=str(ROOT / 'templates'))
    app.secret_key = 't'
    auth = Blueprint('auth', __name__)
    auth.add_url_rule('/auth/login', 'login_page', lambda: 'login')
    app.register_blueprint(auth)
    app.register_blueprint(mod.diary_bp)
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(user_id='id-1', real_name='牧師', line_id='U-1')
    r = c.get('/diary/pastor/view/U-3')
    assert r.status_code == 302 and r.headers['Location'].endswith('/diary/pastor')


def test_nobody_queries_the_column_nothing_writes():
    bad = [f.name for f in (ROOT / 'routes').glob('*.py')
           if re.search(r"\.eq\(\s*['\"]line_id['\"]", f.read_text(encoding='utf-8'))]
    assert not bad, f'users.line_id 沒有程式會寫，請改用 line_user_id：{bad}'


def test_every_class_in_the_pastor_page_has_a_style():
    html = (ROOT / 'templates/diary/pastor_view.html').read_text(encoding='utf-8')
    css = (ROOT / 'static/css/main.css').read_text(encoding='utf-8')
    used = {c for attr in re.findall(r'class="([^"]*)"', html) for c in re.findall(r'\bpastor-[a-z-]+', attr)}
    assert used and not {c for c in used if not re.search(rf'\.{c}(?![\w-])', css)}
