"""聚會人數回報 ↔ 點名：以點名為準（使用者決定 2026-11-08，方向 A）。

守住的事：點名那邊沒有數字就不覆蓋（空白不是 0）、成人主日堂數不齊不覆蓋、逐人模式「到」＋「遲到」才算、
讀不到資料退回手填、連結時回報頁不收手填、設定頁存得下來、讀的地方都接上了。
"""
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

from routes import roll_call_link as L

ROOT = Path(__file__).resolve().parent.parent
D = '2026-11-08'


def _chain(data, count=None, record=None, name=''):
    c = MagicMock()
    for m in ('select', 'eq', 'in_', 'gte', 'lt', 'order', 'limit'):
        def f(*a, _m=m, **k):
            if record is not None:
                record.append((name, _m, a))
            return c
        getattr(c, m).side_effect = f
    c.execute.return_value.data = list(data)
    c.execute.return_value.count = count
    return c


def _sb(sessions=(), mode='headcount', counts=None, any_row=True, boom=False, record=None):
    """counts: {session_id: 到場人數}；any_row：該場有沒有任何紀錄（逐人模式）"""
    counts = counts or {}

    def table(name):
        if boom:
            raise RuntimeError('db down')
        if name == 'rc_sessions':
            return _chain(sessions, record=record, name=name)
        if name == 'rc_meeting_types':
            return _chain([{'record_mode': mode}], record=record, name=name)
        c = _chain([{'id': 'r'}] if any_row else [], record=record, name=name)
        # rc_records：count 依 session_id 回
        orig_eq = c.eq.side_effect

        def eq(col, val):
            orig_eq(col, val)
            if col == 'session_id':
                c.execute.return_value.count = counts.get(val, 0)
            return c
        c.eq.side_effect = eq
        return c
    return MagicMock(table=table)


CFG = {'rc_type_id': 'T1', 'service_count': 1}


def test_no_link_means_no_change():
    row = {'id': 'x', 'attendance_count': 5}
    assert L.overlay('prayer', D, row, cfg={}, sb=_sb()) is row


def test_a_headcount_session_gives_its_number():
    out = L.overlay('prayer', D, {'id': 'x', 'attendance_count': 5}, cfg=CFG,
                    sb=_sb([{'id': 's1', 'headcount': 87}]))
    assert out['attendance_count'] == 87 and out['_linked'] == [87] and out['id'] == 'x'


def test_a_blank_headcount_is_not_zero():
    """★ 點名那邊 headcount 是 NULL＝還沒填：不可以當 0 蓋掉手填的。"""
    row = {'attendance_count': 5}
    assert L.overlay('prayer', D, row, cfg=CFG, sb=_sb([{'id': 's1', 'headcount': None}])) is row


def test_a_zero_headcount_that_was_typed_is_zero():
    out = L.overlay('prayer', D, None, cfg=CFG, sb=_sb([{'id': 's1', 'headcount': 0}]))
    assert out['attendance_count'] == 0 and out['_linked'] == [0]


def test_individual_mode_counts_present_and_late_only():
    rec = []
    out = L.overlay('children_sunday', D, None, cfg=CFG,
                    sb=_sb([{'id': 's1', 'headcount': None}], mode='individual', counts={'s1': 40}, record=rec))
    assert out['attendance_count'] == 40
    statuses = [a for n, m, a in rec if n == 'rc_records' and m == 'in_']
    assert statuses and set(statuses[0][1]) == {'present', 'late'}, '請假、缺席不可以算進人數'


def test_nobody_marked_yet_is_not_zero():
    """★ 逐人場次一筆紀錄都沒有＝還沒開始點（點名單會自動建場次），不是「0 人」。"""
    row = {'attendance_count': 9}
    out = L.overlay('prayer', D, row, cfg=CFG,
                    sb=_sb([{'id': 's1', 'headcount': None}], mode='individual', counts={}, any_row=False))
    assert out is row


def test_everyone_marked_absent_is_a_real_zero():
    out = L.overlay('prayer', D, None, cfg=CFG,
                    sb=_sb([{'id': 's1', 'headcount': None}], mode='individual', counts={}, any_row=True))
    assert out['attendance_count'] == 0


def test_two_services_need_two_sessions():
    """★ 只蓋一堂的話合計是一個假數字：少一場就整個不覆蓋。"""
    cfg = {'rc_type_id': 'T1', 'service_count': 2}
    row = {'first_service_count': 1}
    assert L.overlay('adult_sunday', D, row, cfg=cfg, sb=_sb([{'id': 'a', 'headcount': 100}])) is row
    out = L.overlay('adult_sunday', D, row, cfg=cfg,
                    sb=_sb([{'id': 'a', 'headcount': 100}, {'id': 'b', 'headcount': 60}]))
    assert (out['first_service_count'], out['second_service_count']) == (100, 60)


def test_one_service_setting_zeroes_the_second_field():
    out = L.overlay('adult_sunday', D, {'second_service_count': 7}, cfg={'rc_type_id': 'T1', 'service_count': 1},
                    sb=_sb([{'id': 'a', 'headcount': 100}]))
    assert out['first_service_count'] == 100 and out['second_service_count'] == 0


def test_a_database_hiccup_falls_back_to_manual():
    """★ 讀不到點名資料不可以讓回報頁打不開：當成沒有連結。"""
    row = {'attendance_count': 5}
    assert L.overlay('prayer', D, row, cfg=CFG, sb=_sb(boom=True)) is row


def test_the_day_window_is_taipei_midnight_in_utc():
    rec = []
    L.overlay('prayer', D, None, cfg=CFG, sb=_sb([], record=rec))
    ge = [a for n, m, a in rec if n == 'rc_sessions' and m == 'gte'][0]
    assert ge[1] == '2026-11-07T16:00:00+00:00', '那一天的起點要是台北 00:00（UTC 前一天 16:00）'


def test_this_module_never_reads_users_or_writes():
    src = (ROOT / 'routes' / 'roll_call_link.py').read_text(encoding='utf-8')
    code = re.sub(r'(?m)#.*$', '', re.sub(r'"""[\s\S]*?"""', '', src))
    for banned in ("table('users')", '.insert(', '.update(', '.upsert(', '.delete(', 'rpc('):
        assert banned not in code, f'roll_call_link 不可以有 {banned}'


# ── 回報頁：連結時唯讀、不收手填；設定頁存得下來 ──────────────

@pytest.fixture
def app():
    from flask import Flask
    import routes.cell_report as CR
    a = Flask(__name__, template_folder=str(ROOT / 'templates'))
    a.secret_key = 't'
    a.jinja_env.globals.update(
        csrf_token=lambda: 't', module_on=lambda *_: True, church_name='測試', church_short_name='測',
        line_liff_id='', privacy_policy_url='', card_names={}, can_see=lambda *_: True,
        asset=lambda p: '/static/' + p, push_enabled=False, assistant_name='小助手')
    a.register_blueprint(CR.cell_report_bp)
    return a


def _staff(client):
    with client.session_transaction() as s:
        s.update(user_id='u1', real_name='同工', is_staff=True, member_type='member')
    return client


@pytest.mark.parametrize('path,key', [('/cell-report/sunday', 'adult_sunday'), ('/cell-report/children', 'children_sunday'),
                                      ('/cell-report/prayer', 'prayer'), ('/cell-report/morning-prayer', 'morning_prayer')])
def test_a_linked_meeting_refuses_hand_entry(app, path, key):
    import routes.cell_report as CR
    sb = MagicMock()
    with patch.object(CR, '_raw_linked', lambda k, d: k == key), patch.object(CR, 'supabase', sb), \
         patch.object(CR, '_get_meeting_settings', lambda: {k: {'weekday': 6, 'service_count': 1, 'label': 'X'}
                                                            for k in ('adult_sunday', 'children_sunday', 'prayer', 'morning_prayer')}):
        r = _staff(app.test_client()).post(path, json={'attendance_count': '5', 'first_service_count': '5'})
    assert r.status_code == 409 and '點名' in r.get_json()['error']
    sb.table.assert_not_called()


def test_an_unlinked_meeting_still_accepts_hand_entry(app):
    import routes.cell_report as CR
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{'id': 'r1', 'date': D}]
    with patch.object(CR, '_raw_linked', lambda k, d: False), patch.object(CR, 'supabase', sb), \
         patch.object(CR, '_get_meeting_settings', lambda: {'prayer': {'weekday': 6, 'label': '禱告會'}}):
        r = _staff(app.test_client()).post('/cell-report/prayer', json={'attendance_count': '12'})
    assert r.status_code == 200 and r.get_json()['success'] is True


def test_the_linked_page_is_read_only(app):
    import routes.cell_report as CR
    linked = {'date': D, 'attendance_count': 33, '_linked': [33]}
    with patch.object(CR, '_get_prayer_report', lambda d: linked), \
         patch.object(CR, '_get_meeting_settings', lambda: {'prayer': {'weekday': 6, 'label': '禱告會'}}):
        html = _staff(app.test_client()).get('/cell-report/prayer').get_data(as_text=True)
    assert '33 人' in html and 'type="number"' not in html and '不用再填一次' in html


def test_the_settings_page_saves_the_link(app):
    import routes.cell_report as CR
    sb = MagicMock()
    with patch.object(CR, 'supabase', sb), patch.object(CR, '_invalidate_meeting_cache', lambda: None), \
         patch.object(CR, '_invalidate_module_cache', lambda: None):
        c = app.test_client()
        with c.session_transaction() as s:
            s.update(user_id='u1', is_admin=True, member_type='member')
        c.post('/cell-report/admin/meeting-settings',
               data={'prayer_weekday': '2', 'prayer_service_count': '1', 'prayer_rc_type': 'TYPE-9',
                     'adult_sunday_weekday': '6', 'adult_sunday_service_count': '2'})
    import json
    saved = {}
    for call in sb.table.return_value.upsert.call_args_list:
        row = call.args[0]
        if row.get('key', '').startswith('meeting.'):
            saved[row['key']] = json.loads(row['value'])
    assert saved['meeting.prayer']['rc_type_id'] == 'TYPE-9'
    assert saved['meeting.adult_sunday']['rc_type_id'] is None, '沒選就要存成空（不連結）'


# ── 接線：每個讀人數的地方都過同一支 overlay ──────────────

def _code(path):
    return re.sub(r'(?m)#.*$', '', (ROOT / path).read_text(encoding='utf-8'))


@pytest.mark.parametrize('fn,key', [('sunday', 'adult_sunday'), ('children', 'children_sunday'),
                                    ('prayer', 'prayer'), ('morning_prayer', 'morning_prayer')])
def test_every_report_getter_goes_through_the_overlay(fn, key):
    code = _code('routes/cell_report.py')
    body = code[code.index(f'def _get_{fn}_report'):]
    body = body[:body.index('\n\n\n')]
    assert f"overlay('{key}'" in body


@pytest.mark.parametrize('fn', ['sunday', 'children', 'prayer', 'morning_prayer'])
def test_get_or_create_reads_the_raw_row(fn):
    """★ 手填那條路要的是資料庫真的那一列（要有 id）；拿到「疊上點名」的合成列會 KeyError。"""
    code = _code('routes/cell_report.py')
    body = code[code.index(f'def _get_or_create_{fn}_report'):]
    body = body[:body.index('\n\n\n')]
    assert f'_raw_{fn}_report' in body and f'_get_{fn}_report' not in body


def test_the_home_summary_uses_the_overlay_too():
    code = _code('routes/event.py')
    assert 'roll_call_link import overlay' in code and 'attendance_summary[_k] = _rc_overlay(_key, _d' in code
