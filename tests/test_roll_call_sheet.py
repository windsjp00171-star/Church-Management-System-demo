"""點名單（紙本那種表格）：左邊人名、上面日期，點一下打勾；不用自己建類型、開場次。"""
import datetime
import re
import sys

import pytest

@pytest.fixture(autouse=True)
def _template_globals(app):
    """測試用的簡化 app 沒有正式 app 在啟動時掛上的模板全域函式；base.html 要用到。"""
    g = app.jinja_env.globals
    g.update(csrf_token=lambda: 't', module_on=lambda *_: True, church_name='測試教會', church_short_name='測試',
             line_liff_id='', privacy_policy_url='', card_names={}, can_see=lambda *_: True)


TYPE = {'id': 't1', 'name': '主日', 'record_mode': 'individual', 'created_at': '2026-01-01'}


def _sess(sid, iso, status='open'):
    return {'id': sid, 'type_id': 't1', 'starts_at': iso, 'status': status}


def _ticks(html, value):
    """表格裡按鈕的狀態數量（只數按鈕本身，不數 JS 裡的選擇器）。"""
    return len(re.findall(r'<button[^>]*class="cell"[^>]*data-on="%s"' % value, html))


def _writes(fake, table):
    return [w for w in fake.writes if w[0] == table]


def test_empty_database_shows_a_start_button_and_writes_nothing(fake_db, client_as):
    r = client_as(is_staff=True).get('/roll-call')
    assert r.status_code == 200 and '開始：建立主日點名單' in r.get_data(as_text=True)
    assert not fake_db.writes                       # 打開頁面不可以寫資料庫


def test_sheet_has_names_on_the_left_dates_on_top_and_ticks(fake_db, client_as):
    fake_db.tables.update(
        rc_meeting_types=[TYPE],
        rc_sessions=[_sess('s2', '2026-11-08T02:00:00+00:00'), _sess('s1', '2026-11-01T02:00:00+00:00')],
        rc_members=[{'id': 'm1', 'name': '王小明', 'status': 'active'}, {'id': 'm2', 'name': '李小華', 'status': 'active'}],
        rc_records=[{'session_id': 's1', 'member_id': 'm1', 'status': 'present'},
                    {'session_id': 's2', 'member_id': 'm1', 'status': 'present'},
                    {'session_id': 's2', 'member_id': 'm2', 'status': 'absent'}])
    html = client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    assert '王小明' in html and '李小華' in html
    assert html.index('11/1') < html.index('11/8')                 # 舊的在左、新的在右，跟紙本一樣
    assert _ticks(html, '1') == 2 and _ticks(html, '0') == 2      # 王兩次到；李 11/8 缺席、11/1 無紀錄


def test_blank_and_absent_look_the_same_as_on_paper(fake_db, client_as):
    fake_db.tables.update(rc_meeting_types=[TYPE], rc_sessions=[_sess('s1', '2026-11-01T02:00:00+00:00')],
                          rc_members=[{'id': 'm1', 'name': '甲', 'status': 'active'}],
                          rc_records=[{'session_id': 's1', 'member_id': 'm1', 'status': 'absent'}])
    assert _ticks(client_as(is_staff=True).get('/roll-call').get_data(as_text=True), '1') == 0


def test_add_column_creates_the_default_type_and_todays_session(fake_db, client_as):
    r = client_as(is_staff=True).post('/api/roll-call/sheet/add-column', json={'date': '2026-11-08'})
    assert r.status_code == 200 and r.get_json()['data']['created'] is True
    assert _writes(fake_db, 'rc_meeting_types')[0][2] == {'name': '主日', 'record_mode': 'individual',
                                                          'counts_toward_rate': True}
    sess = _writes(fake_db, 'rc_sessions')[0][2]
    assert sess['starts_at'] == '2026-11-08T02:00:00+00:00'      # 台北 10:00 存成 UTC 02:00


def test_add_column_twice_for_the_same_day_does_not_duplicate(fake_db, client_as):
    fake_db.tables.update(rc_meeting_types=[TYPE], rc_sessions=[_sess('s1', '2026-11-08T02:00:00+00:00')])
    r = client_as(is_staff=True).post('/api/roll-call/sheet/add-column', json={'date': '2026-11-08'})
    assert r.get_json()['data'] == {'id': 's1', 'created': False}
    assert not _writes(fake_db, 'rc_sessions') and not _writes(fake_db, 'rc_meeting_types')


def test_add_column_rejects_a_bad_date(fake_db, client_as):
    assert client_as(is_staff=True).post('/api/roll-call/sheet/add-column', json={'date': '11/8'}).status_code == 400


def test_plain_members_cannot_see_or_add(fake_db, client_as):
    assert client_as().get('/roll-call').status_code == 403
    assert client_as().post('/api/roll-call/sheet/add-column', json={}).status_code == 403


def test_empty_roster_tells_you_where_to_add_names(fake_db, client_as):
    fake_db.tables.update(rc_meeting_types=[TYPE], rc_sessions=[_sess('s1', '2026-11-01T02:00:00+00:00')])
    admin = client_as(is_admin=True).get('/roll-call').get_data(as_text=True)
    staff = client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    assert '/admin/roll-call' in admin and '名冊還是空的' in staff


def test_sunday_opens_with_todays_column_added_automatically(fake_db, client_as, monkeypatch):
    fake_db.tables.update(rc_meeting_types=[TYPE])
    rc = sys.modules['routes.roll_call']
    monkeypatch.setattr(rc, '_today_taipei', lambda: datetime.date(2026, 11, 8))     # 週日
    assert 'const AUTO_ADD = true' in client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    monkeypatch.setattr(rc, '_today_taipei', lambda: datetime.date(2026, 11, 9))     # 週一：不自動加
    assert 'const AUTO_ADD = false' in client_as(is_staff=True).get('/roll-call').get_data(as_text=True)


def test_sunday_column_that_already_exists_is_not_added_again(fake_db, client_as, monkeypatch):
    fake_db.tables.update(rc_meeting_types=[TYPE], rc_sessions=[_sess('s1', '2026-11-08T02:00:00+00:00')])
    monkeypatch.setattr(sys.modules['routes.roll_call'], '_today_taipei', lambda: datetime.date(2026, 11, 8))
    assert 'const AUTO_ADD = false' in client_as(is_staff=True).get('/roll-call').get_data(as_text=True)


def test_old_session_list_still_reachable_for_headcount_and_backfill(fake_db, client_as):
    assert client_as(is_staff=True).get('/roll-call/sessions').status_code == 200
