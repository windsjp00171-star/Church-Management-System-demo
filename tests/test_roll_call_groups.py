"""點名名冊分小組（週間小組）：點名單照小組分段、可收合；後台設定、匯入時指定；只影響顯示、不影響出席紀錄。"""
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TYPE = {'id': 't1', 'name': '主日', 'record_mode': 'individual', 'created_at': '2026-01-01'}
G1 = {'id': 'g1', 'name': '週二小組', 'is_active': True}
G2 = {'id': 'g2', 'name': '週四小組', 'is_active': True}


def _today(monkeypatch, day=datetime.date(2026, 11, 8)):
    monkeypatch.setattr(sys.modules['routes.roll_call'], '_today_taipei', lambda: day)


def _world(fake_db, members):
    fake_db.tables.update(rc_meeting_types=[TYPE], cell_groups=[G1, G2],
                          rc_sessions=[{'id': 's1', 'type_id': 't1', 'starts_at': '2026-11-08T02:00:00+00:00', 'status': 'open'}],
                          rc_members=members, rc_records=[])


def _rows(html):
    return re.findall(r'<tr (class="grp-head" )?data-(?:group|name)="([^"]*)"', html)


def test_the_sheet_is_split_by_group_with_ungrouped_and_left_at_the_end(fake_db, client_as, monkeypatch):
    _world(fake_db, [{'id': 'a', 'name': '甲', 'status': 'active', 'group_id': 'g2'},
                     {'id': 'b', 'name': '乙', 'status': 'active', 'group_id': None},
                     {'id': 'c', 'name': '丙', 'status': 'active', 'group_id': 'g1'},
                     {'id': 'd', 'name': '丁', 'status': 'active', 'group_id': 'g1'},
                     {'id': 'x', 'name': '1', 'status': 'left', 'group_id': 'g1'}])
    client = client_as(is_staff=True)
    _today(monkeypatch)
    html = client.get('/roll-call').get_data(as_text=True)
    heads = re.findall(r'<tr class="grp-head" data-group="([^"]*)"', html)
    assert heads == ['週二小組', '週四小組', '未分組'], '照組名分段，沒分組的排最後'
    names = re.findall(r'<tr data-name="([^"]*)" data-group="([^"]*)"', html)
    assert [n for n, _ in names] == ['丁', '丙', '甲', '乙', '1']
    assert dict(names)['丙'] == '週二小組' and dict(names)['1'] == '', '已離開的不在任何一組裡（另外收起來）'
    assert '（2 人）' in html, '組別標題要寫有幾個人（不算已離開的）'


def test_no_group_headers_when_nobody_has_a_group(fake_db, client_as, monkeypatch):
    _world(fake_db, [{'id': 'a', 'name': '甲', 'status': 'active'}, {'id': 'b', 'name': '乙', 'status': 'active'}])
    client = client_as(is_staff=True)
    _today(monkeypatch)
    assert 'grp-head' not in client.get('/roll-call').get_data(as_text=True).split('<script')[0]


def test_search_finds_people_inside_a_collapsed_group():
    """★ 收起來的小組，搜尋時還是要找得到人 —— 不然同工以為這個人不在名冊裡，又加一次新朋友。"""
    src = (ROOT / 'templates' / 'roll_call' / 'sheet.html').read_text(encoding='utf-8')
    body = src[src.index('function filterNames'):]
    body = body[:body.index('\n}\n')]
    assert "(q || !COLLAPSED.has(tr.dataset.group))" in body


def _post(c, url, body):
    return c.post(url, json=body, headers={'X-CSRF-Token': 't'})


def test_admin_can_set_and_clear_a_members_group(fake_db, client_as):
    fake_db.tables.update(cell_groups=[G1], rc_members=[{'id': 'a', 'name': '甲', 'status': 'active'}])
    c = client_as(is_admin=True)
    assert _post(c, '/api/admin/roll-call/members/a/group', {'group_id': 'g1'}).status_code == 200
    assert _post(c, '/api/admin/roll-call/members/a/group', {'group_id': ''}).status_code == 200
    ups = [w for w in fake_db.writes if w[0] == 'rc_members']
    assert [w[2] for w in ups][-2:] == [{'group_id': 'g1'}, {'group_id': None}]


def test_an_unknown_group_is_refused(fake_db, client_as):
    fake_db.tables.update(cell_groups=[G1], rc_members=[{'id': 'a', 'name': '甲', 'status': 'active'}])
    r = _post(client_as(is_admin=True), '/api/admin/roll-call/members/a/group', {'group_id': 'nope'})
    assert r.status_code == 400 and not [w for w in fake_db.writes if w[0] == 'rc_members']


def test_staff_cannot_change_groups(fake_db, client_as):
    fake_db.tables.update(cell_groups=[G1])
    assert _post(client_as(is_staff=True), '/api/admin/roll-call/members/a/group', {'group_id': 'g1'}).status_code == 403


def test_an_import_batch_can_go_into_a_group(fake_db, client_as):
    fake_db.tables.update(cell_groups=[G1], rc_members=[])
    r = _post(client_as(is_admin=True), '/api/admin/roll-call/members', {'names': '李小華\n張三豐', 'group_id': 'g1'})
    assert r.get_json()['data']['added'] == 2
    rows = [w[2] for w in fake_db.writes if w[0] == 'rc_members'][0]
    assert all(x['group_id'] == 'g1' for x in rows)
    r = _post(client_as(is_admin=True), '/api/admin/roll-call/members', {'names': '王五', 'group_id': 'nope'})
    assert r.status_code == 400


def test_the_admin_page_offers_the_weekday_groups(fake_db, client_as):
    fake_db.tables.update(cell_groups=[G1, G2], rc_members=[{'id': 'a', 'name': '甲', 'status': 'active', 'group_id': 'g2'}],
                          rc_meeting_types=[], rc_sessions=[])
    html = client_as(is_admin=True).get('/admin/roll-call').get_data(as_text=True)
    assert 'id="m-group"' in html and '週四小組' in html
    assert re.search(r'<option value="g2" selected>週四小組</option>', html)
