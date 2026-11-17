"""點名名冊連到帳號（2026-11-17：「名冊其實不跟帳號脫鉤」「就是一個身分對應而已」）。

一個人＝一個帳號：新朋友加進點名單就建空殼帳號（之後用「整合 LINE」合併）；帳號裡已有疑似同一個人時
請同工選（是他／另外建），不用姓名替人決定。點名模組本身仍不直接查 users（經由 routes/person.py）。
"""
import datetime
import sys

import pytest

TYPE = {'id': 't1', 'name': '主日', 'record_mode': 'individual', 'created_at': '2026-01-01'}


@pytest.fixture
def world(fake_db, monkeypatch):
    import routes.person as P
    monkeypatch.setattr(P, 'supabase', fake_db)
    fake_db.tables.update(rc_meeting_types=[TYPE], rc_members=[], users=[],
                          rc_sessions=[{'id': 's1', 'type_id': 't1', 'starts_at': '2026-11-08T02:00:00+00:00', 'status': 'open'}])
    return fake_db


def _writes(fake, table, op=None):
    return [w for w in fake.writes if w[0] == table and (op is None or w[1] == op)]


def _add(client, **body):
    return client.post('/api/roll-call/members/quick-add', json=dict({'name': '新朋友'}, **body))


def test_a_newcomer_gets_a_shell_account_and_is_linked(world, client_as):
    r = _add(client_as(is_staff=True), session_id='s1')
    assert r.status_code == 200
    made = _writes(world, 'users', 'insert')
    assert made and made[0][2]['real_name'] == '新朋友' and made[0][2]['member_type'] == 'visitor'
    assert _writes(world, 'rc_members', 'insert')[0][2]['user_id'] == 'new-id', '名冊成員要連到剛建的帳號'
    assert world.rpcs and world.rpcs[0][0] == 'rc_save_record', '並且在本週那一欄打勾'


def test_a_possible_existing_account_is_offered_not_guessed(world, client_as):
    world.tables['users'] = [{'id': 'u9', 'real_name': '新朋友', 'display_name': '新朋友', 'line_user_id': 'L'}]
    r = _add(client_as(is_staff=True))
    assert r.status_code == 409
    acc = r.get_json()['data']['accounts']
    assert acc[0]['id'] == 'u9' and acc[0]['has_line'] is True
    assert not world.writes, '還沒選之前什麼都不可以寫'


def test_choosing_the_existing_account_links_it_without_a_new_one(world, client_as):
    world.tables['users'] = [{'id': 'u9', 'real_name': '新朋友', 'display_name': '新朋友'}]
    r = _add(client_as(is_staff=True), link_user_id='u9')
    assert r.status_code == 200
    assert not _writes(world, 'users', 'insert')
    assert _writes(world, 'rc_members', 'insert')[0][2]['user_id'] == 'u9'


def test_saying_it_is_someone_else_creates_a_new_shell(world, client_as):
    world.tables['users'] = [{'id': 'u9', 'real_name': '新朋友', 'display_name': '新朋友'}]
    r = _add(client_as(is_staff=True), new_account=True)
    assert r.status_code == 200 and len(_writes(world, 'users', 'insert')) == 1


def test_an_account_already_on_the_roster_cannot_be_added_twice(world, client_as):
    world.tables['rc_members'] = [{'id': 'm1', 'name': '王小明', 'user_id': 'u9', 'status': 'active'}]
    r = _add(client_as(is_staff=True), name='王曉明二號', link_user_id='u9')
    assert r.status_code == 409 and '已經在名冊上' in r.get_json()['error']
    assert not _writes(world, 'rc_members', 'insert')


def test_admin_can_link_a_name_only_member(world, client_as):
    world.tables['rc_members'] = [{'id': 'm1', 'name': '王小明', 'user_id': None, 'status': 'active'}]
    c = client_as(is_admin=True)
    r = c.post('/api/admin/roll-call/members/m1/link', json={})
    assert r.status_code == 200
    assert _writes(world, 'users', 'insert')[0][2]['real_name'] == '王小明'
    assert _writes(world, 'rc_members', 'update')[0][2] == {'user_id': 'new-id'}


def test_admin_link_offers_existing_accounts_first(world, client_as):
    world.tables.update(rc_members=[{'id': 'm1', 'name': '王小明', 'user_id': None, 'status': 'active'}],
                        users=[{'id': 'u9', 'real_name': '王小明', 'display_name': '小明'}])
    r = client_as(is_admin=True).post('/api/admin/roll-call/members/m1/link', json={})
    assert r.status_code == 409 and r.get_json()['data']['accounts'][0]['id'] == 'u9'
    assert not world.writes


def test_an_already_linked_member_is_not_relinked(world, client_as):
    world.tables['rc_members'] = [{'id': 'm1', 'name': '王小明', 'user_id': 'u1', 'status': 'active'}]
    r = client_as(is_admin=True).post('/api/admin/roll-call/members/m1/link', json={'new_account': True})
    assert r.status_code == 409 and '已經連到帳號' in r.get_json()['error'] and not world.writes


def test_staff_cannot_use_the_admin_link(world, client_as):
    assert client_as(is_staff=True).post('/api/admin/roll-call/members/m1/link', json={}).status_code == 403


def test_the_roll_call_module_still_does_not_query_users_directly():
    """★ 查重與建帳號都經過 routes/person.py —— 點名模組自己不碰 users（結構守衛另外也在看）。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / 'routes' / 'roll_call.py').read_text(encoding='utf-8')
    assert "table('users')" not in src and 'from routes.person import create_person' in src
