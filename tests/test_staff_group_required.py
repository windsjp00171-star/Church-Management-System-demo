"""留名單上傳的權限與首頁「上傳留名單」卡片共用同一份同工判定（routes.decorators.in_staff_group）。

以前卡片看「副標籤是否屬於被標成同工的群組」，上傳頁卻只認名字叫「同工」的標籤：
在「招待組」這類同工群組的人看得到卡片、點進去卻被擋。
"""
import os
import sys
import types

import pytest
from flask import Flask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Groups:
    """只回答「哪些群組是同工群組」的假資料庫；in_staff_group 在呼叫時才 import db，不必重新載入模組。"""
    def table(self, name):
        rows = [{'name': '招待組'}] if name == 'groups' else []
        q = types.SimpleNamespace()
        q.select = q.eq = lambda *a, **k: q
        q.execute = lambda: types.SimpleNamespace(data=rows)
        return q


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=_Groups()))
    from flask import Blueprint
    from routes.decorators import staff_group_required
    app = Flask(__name__, template_folder=os.path.join(ROOT, 'templates'))
    app.secret_key = 'x'
    app.jinja_env.globals.update(csrf_token=lambda: 't', module_on=lambda *_: True, church_name='測試教會',
                                 church_short_name='測試', line_liff_id='', privacy_policy_url='',
                                 card_names={}, can_see=lambda *_: True)
    auth = Blueprint('auth', __name__)
    auth.add_url_rule('/login', 'login_page', lambda: 'login')
    app.register_blueprint(auth)
    app.add_url_rule('/up', 'up', staff_group_required(lambda: 'ok'), methods=['GET', 'POST'])
    return app.test_client()


def _login(c, **flags):
    with c.session_transaction() as s:
        s['user_id'] = 'u1'
        s.update(flags)


def test_anonymous_goes_to_login(client):
    assert client.get('/up').status_code == 302


def test_staff_group_member_is_allowed(client):
    _login(client, group_tags=['招待組'])
    assert client.get('/up').status_code == 200
    assert client.post('/up').status_code == 200


def test_admin_is_allowed_without_tags(client):
    _login(client, is_admin=True)
    assert client.get('/up').status_code == 200


def test_other_member_is_refused(client):
    _login(client, group_tags=['敬拜團'])
    assert client.get('/up').status_code == 403
    r = client.post('/up')
    assert r.status_code == 403 and r.get_json() == {'error': '無同工權限'}


def test_portal_card_and_upload_page_share_one_rule():
    src = open(os.path.join(ROOT, 'routes', 'event.py'), encoding='utf-8').read()
    assert 'in_staff_group(' in src
    vf = open(os.path.join(ROOT, 'routes', 'visitor_forms.py'), encoding='utf-8').read()
    assert vf.count('@staff_group_required') == 2 and "'同工' in tags" not in vf
