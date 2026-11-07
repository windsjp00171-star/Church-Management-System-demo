"""點名單（紙本那種表格）：左邊人名、上面日期，點一下打勾；不用自己建類型、開場次。"""
import datetime
import re
import sys


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


def _buttons(html, enabled):
    """表格裡可點／反灰的按鈕數量（只數按鈕本身）。"""
    allb = re.findall(r'<button[^>]*class="cell"[^>]*>', html)
    return len([b for b in allb if (' disabled' not in b) == enabled])


def _sheet_world(fake_db):
    fake_db.tables.update(
        rc_meeting_types=[TYPE],
        rc_sessions=[_sess('s1', '2026-11-01T02:00:00+00:00'), _sess('s2', '2026-11-08T02:00:00+00:00')],
        rc_members=[{'id': 'm1', 'name': '王小明', 'status': 'active'}, {'id': 'm2', 'name': '李小華', 'status': 'active'}],
        rc_records=[{'session_id': 's1', 'member_id': 'm1', 'status': 'present'},
                    {'session_id': 's2', 'member_id': 'm1', 'status': 'present'},
                    {'session_id': 's2', 'member_id': 'm2', 'status': 'absent'}])


def test_sheet_lays_out_the_whole_quarter_of_sundays(fake_db, client_as, monkeypatch):
    _today(monkeypatch, datetime.date(2026, 11, 8))                # 週日，第四季
    _sheet_world(fake_db)
    html = client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    labels = re.findall(r'<th[^>]*>\s*(\d+/\d+)', html)
    assert labels == ['10/4', '10/11', '10/18', '10/25', '11/1', '11/8', '11/15', '11/22', '11/29',
                      '12/6', '12/13', '12/20', '12/27']             # 整季 13 個主日，由左到右
    assert '王小明' in html and '李小華' in html


def test_only_this_weeks_sunday_can_be_clicked_everything_else_is_greyed(fake_db, client_as, monkeypatch):
    _today(monkeypatch, datetime.date(2026, 11, 8))
    _sheet_world(fake_db)
    html = client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    assert _buttons(html, True) == 2                                 # 2 位成員 × 本週 1 欄
    assert _buttons(html, False) == 2 * 12                           # 其餘 12 欄全部反灰
    assert html.count('id="col-current"') == 1                       # 本週那一欄有標記（手機上自動捲到它）


def test_ticks_in_greyed_columns_are_still_shown(fake_db, client_as, monkeypatch):
    _today(monkeypatch, datetime.date(2026, 11, 8))
    _sheet_world(fake_db)
    html = client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    assert _ticks(html, '1') == 2                                    # 王：11/1 與 11/8 都到；李 11/8 缺席
    # 11/1（過去）的打勾還在，只是反灰不能改
    past = [b for b in re.findall(r'<button[^>]*class="cell"[^>]*>', html) if 'data-on="1"' in b and ' disabled' in b]
    assert len(past) == 1


def test_midweek_the_sundays_column_is_still_this_weeks_and_next_sunday_is_not_yet(fake_db, client_as, monkeypatch):
    _today(monkeypatch, datetime.date(2026, 11, 11))                 # 週三
    _sheet_world(fake_db)
    fake_db.tables['rc_sessions'].append(_sess('wed', '2026-11-11T02:00:00+00:00'))   # 臨時加開的週三聚會
    html = client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    assert _buttons(html, True) == 2 * 2                             # 本週主日 11/8 ＋ 同週的臨時聚會 11/11
    assert 'const ADD_DATE = "2026-11-08"' in html                   # 本週的主日是 11/8（週日起算）


def test_locked_current_column_is_not_clickable(fake_db, client_as, monkeypatch):
    _today(monkeypatch, datetime.date(2026, 11, 8))
    _sheet_world(fake_db)
    fake_db.tables['rc_sessions'][1]['status'] = 'locked'
    assert _buttons(client_as(is_staff=True).get('/roll-call').get_data(as_text=True), True) == 0


def test_there_is_no_per_person_total_column_on_the_sheet(fake_db, client_as, monkeypatch):
    """個人到幾次、出席率在「出席統計」；點名單上那一欄只會讓人困惑。"""
    _today(monkeypatch, datetime.date(2026, 11, 8))
    _sheet_world(fake_db)
    html = client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    assert 'rowcount' not in html and '>到<' not in html


def test_quarter_start_week_whose_sunday_falls_in_the_previous_quarter_still_has_its_column(fake_db, client_as, monkeypatch):
    """1/1 那一週的主日是 12/28（上一季）：不顯示的話自動建立會無限重新整理。"""
    _today(monkeypatch, datetime.date(2026, 1, 1))
    fake_db.tables.update(rc_meeting_types=[TYPE], rc_members=[{'id': 'm1', 'name': '甲', 'status': 'active'}],
                          rc_sessions=[_sess('s1', '2025-12-28T02:00:00+00:00')])
    html = client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    assert 'const AUTO_ADD = false' in html and 'id="col-current"' in html and '12/28' in html
    assert _buttons(html, True) == 1


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


def test_missing_current_week_column_is_added_automatically_with_the_sundays_date(fake_db, client_as, monkeypatch):
    fake_db.tables.update(rc_meeting_types=[TYPE])
    _today(monkeypatch, datetime.date(2026, 11, 11))                 # 週三：本週主日 11/8 還沒有那一欄
    html = client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    assert 'const AUTO_ADD = true' in html and 'const ADD_DATE = "2026-11-08"' in html


def test_nothing_is_added_when_the_current_week_column_already_exists(fake_db, client_as, monkeypatch):
    fake_db.tables.update(rc_meeting_types=[TYPE], rc_sessions=[_sess('s1', '2026-11-08T02:00:00+00:00')])
    _today(monkeypatch, datetime.date(2026, 11, 11))
    assert 'const AUTO_ADD = false' in client_as(is_staff=True).get('/roll-call').get_data(as_text=True)


def test_auto_add_has_a_loop_guard_in_the_page(fake_db, client_as):
    html = client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    assert 'rc_auto_add' in html and '15000' in html               # 15 秒內不重複自動重新整理


def test_old_session_list_still_reachable_for_headcount_and_backfill(fake_db, client_as):
    assert client_as(is_staff=True).get('/roll-call/sessions').status_code == 200


# ── 臨時來了新朋友：直接在點名單加 ──
def _today(monkeypatch, day=datetime.date(2026, 11, 8)):
    monkeypatch.setattr(sys.modules['routes.roll_call'], '_today_taipei', lambda: day)


def _quick(client, **body):
    return client.post('/api/roll-call/members/quick-add', json=body)


def test_quick_add_creates_the_person_and_ticks_them_for_today(fake_db, client_as, monkeypatch):
    _today(monkeypatch)
    fake_db.tables.update(rc_meeting_types=[TYPE], rc_sessions=[_sess('s1', '2026-11-08T02:00:00+00:00')])
    r = _quick(client_as(is_staff=True), name='  新  朋友 ', session_id='s1')
    assert r.status_code == 200 and r.get_json()['data']['ticked'] is True
    row = _writes(fake_db, 'rc_members')[0][2]
    assert row['name'] == '新 朋友' and row['joined_on'] == '2026-11-08' and row['source'] == 'manual'
    fn, args = fake_db.rpcs[0]
    assert fn == 'rc_save_record' and args['p_status'] == 'present' and args['p_session'] == 's1'   # 走既有的稽核函式


def test_quick_add_without_a_column_only_adds_the_name(fake_db, client_as, monkeypatch):
    _today(monkeypatch)
    r = _quick(client_as(is_staff=True), name='新朋友')
    assert r.status_code == 200 and r.get_json()['data']['ticked'] is False and not fake_db.rpcs


def test_quick_add_never_duplicates_an_existing_name(fake_db, client_as, monkeypatch):
    _today(monkeypatch)
    fake_db.tables['rc_members'] = [{'id': 'm1', 'name': '王小明', 'status': 'active'},
                                    {'id': 'm2', 'name': '陳大文', 'status': 'left'}]
    c = client_as(is_staff=True)
    for n in ('王小明', ' 王　小明 ', '陳大文'):
        assert _quick(c, name=n).status_code == 409
    assert not _writes(fake_db, 'rc_members') and not fake_db.rpcs


def test_quick_add_similar_name_needs_confirmation(fake_db, client_as, monkeypatch):
    _today(monkeypatch)
    fake_db.tables['rc_members'] = [{'id': 'm1', 'name': '王小明', 'status': 'active'}]
    c = client_as(is_staff=True)
    r = _quick(c, name='王曉明')
    assert r.status_code == 409 and r.get_json()['data']['similar'] == '王小明' and not _writes(fake_db, 'rc_members')
    assert _quick(c, name='王曉明', confirm=True).status_code == 200 and _writes(fake_db, 'rc_members')


def test_quick_add_input_and_permissions(fake_db, client_as, monkeypatch):
    _today(monkeypatch)
    assert _quick(client_as(is_staff=True), name='  ').status_code == 400
    assert _quick(client_as(is_staff=True), name='甲' * 31).status_code == 400
    assert _quick(client_as(), name='新朋友').status_code == 403
    assert not _writes(fake_db, 'rc_members')


def test_quick_add_into_a_locked_column_is_refused_for_staff(fake_db, client_as, monkeypatch):
    _today(monkeypatch)
    fake_db.tables.update(rc_meeting_types=[TYPE], rc_sessions=[_sess('s1', '2026-11-08T02:00:00+00:00', 'locked')])
    r = _quick(client_as(is_staff=True), name='新朋友', session_id='s1')
    assert r.status_code == 403 and not _writes(fake_db, 'rc_members') and not fake_db.rpcs


# ── 區間出席 ──
def _report_world(fake_db):
    fake_db.tables.update(
        rc_meeting_types=[TYPE],
        rc_sessions=[_sess('a', '2026-10-11T02:00:00+00:00'), _sess('b', '2026-10-18T02:00:00+00:00'),
                     _sess('c', '2026-10-25T02:00:00+00:00'), _sess('d', '2026-11-01T02:00:00+00:00'),
                     _sess('future', '2026-11-15T02:00:00+00:00')],
        rc_members=[{'id': 'm1', 'name': '甲', 'status': 'active'},
                    {'id': 'm2', 'name': '乙', 'status': 'active', 'joined_on': '2026-10-25'}],
        rc_records=[{'session_id': 'a', 'member_id': 'm1', 'status': 'present'},
                    {'session_id': 'b', 'member_id': 'm1', 'status': 'absent'},
                    {'session_id': 'c', 'member_id': 'm1', 'status': 'present'},
                    {'session_id': 'c', 'member_id': 'm2', 'status': 'present'},
                    {'session_id': 'd', 'member_id': 'm2', 'status': 'present'},
                    {'session_id': 'future', 'member_id': 'm1', 'status': 'present'}])


def _people(data):
    return {p['name']: p for p in data['people']}


def test_range_report_counts_only_sessions_in_range_up_to_today(fake_db, app, monkeypatch):
    _today(monkeypatch, datetime.date(2026, 11, 8))
    _report_world(fake_db)
    rc = sys.modules['routes.roll_call']
    with app.test_request_context():
        from flask import session
        session.update(user_id='u', is_staff=True)
        data = rc.range_report(TYPE, datetime.date(2026, 10, 1), datetime.date(2026, 11, 30))
    assert data['total'] == 4                                          # 未來那一次不算進分母
    p = _people(data)
    assert (p['甲']['present'], p['甲']['total'], p['甲']['percent']) == (2, 4, 50.0)     # 沒打勾/缺席＝沒來
    assert (p['乙']['present'], p['乙']['total'], p['乙']['percent']) == (2, 2, 100.0)    # 10/25 才加入，之前不算他沒來
    assert data['per_session'] == [1, 0, 2, 1]


def test_range_report_narrows_to_the_chosen_dates(fake_db, app, monkeypatch):
    _today(monkeypatch, datetime.date(2026, 11, 8))
    _report_world(fake_db)
    rc = sys.modules['routes.roll_call']
    with app.test_request_context():
        from flask import session
        session.update(user_id='u', is_staff=True)
        data = rc.range_report(TYPE, datetime.date(2026, 10, 18), datetime.date(2026, 10, 25))
    assert [s['id'] for s in data['sessions']] == ['b', 'c'] and _people(data)['甲']['percent'] == 50.0


def test_report_page_defaults_to_the_last_month_and_survives_reversed_dates(fake_db, client_as, monkeypatch):
    _today(monkeypatch, datetime.date(2026, 11, 8))
    _report_world(fake_db)
    c = client_as(is_staff=True)
    html = c.get('/roll-call/report').get_data(as_text=True)
    assert '2026/10/10' in html and '2026/11/8' in html and '甲' in html        # 預設過去 30 天
    assert c.get('/roll-call/report?from=2026-11-30&to=2026-10-01').status_code == 200   # 日期顛倒不會壞
    assert c.get('/roll-call/report?from=garbage&to=nope').status_code == 200


def test_report_page_when_there_is_nothing_yet(fake_db, client_as):
    assert client_as(is_staff=True).get('/roll-call/report').status_code == 200


def test_csv_export_is_admin_only_and_audited(fake_db, client_as, monkeypatch):
    _today(monkeypatch, datetime.date(2026, 11, 8))
    _report_world(fake_db)
    assert client_as(is_staff=True).get('/roll-call/report?format=csv').status_code == 403
    r = client_as(is_admin=True).get('/roll-call/report?from=2026-10-01&to=2026-11-30&format=csv')
    assert r.status_code == 200 and 'attachment' in r.headers['Content-Disposition']
    text = r.data.decode('utf-8-sig')
    assert '甲' in text and '50.0%' in text and '100.0%' in text
    logged = [w for w in fake_db.writes if w[0] == 'audit_logs']
    assert logged and logged[0][2]['action'] == 'roll_call.range_export'
    assert logged[0][2]['detail']['people'] == 2                        # 只記人數，不記姓名


def test_plain_members_cannot_open_the_report(fake_db, client_as):
    assert client_as().get('/roll-call/report').status_code == 403
