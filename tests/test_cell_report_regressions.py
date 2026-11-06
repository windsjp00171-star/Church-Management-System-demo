"""小組回報的回歸守衛：cell_reporter 踩過的坑，展示站移植時又帶回來了。

1. 空白人數不得被存成 0（cell_reporter 曾上線兩次）
2. GET 不得建立資料列（否則看一眼舊週報，儀表板就誤報「已開始回報」）
3. 聚會回報 POST 不得因為 `datetime.now` 打錯而永遠 500
"""
import os
import sys

import pytest

SUNDAY = '/cell-report/sunday'
SINGLE = ['/cell-report/children', '/cell-report/prayer', '/cell-report/morning-prayer']
GROUP = {'id': 'g1', 'name': '一組', 'weekly_gather_day': '日', 'is_active': True}


@pytest.fixture
def cr(fake_db, monkeypatch):
    from flask import Blueprint, Flask
    sys.modules.pop('routes.cell_report', None)
    app = Flask(__name__)
    app.secret_key = 't'
    auth = Blueprint('auth', __name__)
    auth.add_url_rule('/auth/login', 'login_page', lambda: 'login')
    app.register_blueprint(auth)
    import routes.cell_report as mod
    monkeypatch.setattr(mod, 'render_template', lambda *a, **k: 'rendered')
    app.register_blueprint(mod.cell_report_bp)
    fake_db.tables['cell_groups'] = [GROUP]
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(user_id='u1', is_staff=True)
    return c, fake_db


def written(fake, table=None):
    return [w for w in fake.writes if table is None or w[0] == table]


# ── 空白不得為 0 ─────────────────────────────────────
@pytest.mark.parametrize('body', [
    {}, {'first_service_count': '', 'second_service_count': '3'},
    {'first_service_count': '3', 'second_service_count': ''},
    {'first_service_count': None, 'second_service_count': None},
    {'first_service_count': 'abc', 'second_service_count': '1'},
    {'first_service_count': '-1', 'second_service_count': '1'},
])
def test_sunday_blank_or_bad_is_rejected_and_nothing_written(cr, body):
    c, fake = cr
    r = c.post(SUNDAY, json=body)
    assert r.status_code == 400 and r.get_json()['success'] is False
    assert written(fake) == []


@pytest.mark.parametrize('url', SINGLE)
@pytest.mark.parametrize('body', [{}, {'attendance_count': ''}, {'attendance_count': None},
                                  {'attendance_count': 'x'}, {'attendance_count': '-5'}])
def test_other_gatherings_blank_or_bad_rejected(cr, url, body):
    c, fake = cr
    r = c.post(url, json=body)
    assert r.status_code == 400 and written(fake) == []


def test_malformed_json_rejected_not_zero(cr):
    c, fake = cr
    r = c.post(SUNDAY, data='not json', content_type='application/json')
    assert r.status_code == 400 and written(fake) == []


def test_custom_meeting_blank_rejected(cr):
    c, fake = cr
    fake.tables['settings'] = [{'key': 'cell_meeting_custom', 'value': '[]'}]
    # 非 custom_ 開頭直接 404；此處只驗證 blank 路徑不會寫入
    r = c.post('/cell-report/custom-meeting/custom_x', json={'attendance_count': ''})
    assert r.status_code in (400, 404) and written(fake) == []


# ── 正常送出要真的存得進去（打字錯誤的 datetime.now 曾讓它永遠 500）────
def test_sunday_valid_saves_counts(cr):
    c, fake = cr
    r = c.post(SUNDAY, json={'first_service_count': '30', 'second_service_count': '25'})
    assert r.status_code == 200 and r.get_json()['success'] is True
    upd = [w for w in written(fake, 'sunday_reports') if w[1] == 'update'][0][2]
    assert upd['first_service_count'] == 30 and upd['second_service_count'] == 25
    assert isinstance(upd['updated_at'], str)


@pytest.mark.parametrize('url,table', [('/cell-report/children', 'children_sunday_reports'),
                                       ('/cell-report/prayer', 'prayer_reports'),
                                       ('/cell-report/morning-prayer', 'morning_prayer_reports')])
def test_other_gatherings_valid_saves_count(cr, url, table):
    c, fake = cr
    r = c.post(url, json={'attendance_count': '12'})
    assert r.status_code == 200
    upd = [w for w in written(fake, table) if w[1] == 'update'][0][2]
    assert upd['attendance_count'] == 12


@pytest.mark.parametrize('url,table', [('/cell-report/children', 'children_sunday_reports')])
def test_explicit_zero_is_a_real_zero(cr, url, table):
    c, fake = cr
    assert c.post(url, json={'attendance_count': 0}).status_code == 200
    assert [w for w in written(fake, table) if w[1] == 'update'][0][2]['attendance_count'] == 0


# ── 小組週報 Step 1 ──────────────────────────────────
def test_section1_blank_attendance_not_saved(cr):
    c, fake = cr
    r = c.post('/cell-report/g1/section1', data={'week_date': '2026-11-01', 'attendance_count': ''})
    assert r.status_code == 302 and written(fake) == []


def test_section1_explicit_count_saved(cr):
    c, fake = cr
    r = c.post('/cell-report/g1/section1', data={'week_date': '2026-11-01', 'attendance_count': '8'})
    assert r.status_code == 302
    upd = [w for w in written(fake, 'cell_reports') if w[1] == 'update'][0][2]
    assert upd['attendance_count'] == 8


def test_section1_no_meeting_needs_no_count(cr):
    c, fake = cr
    r = c.post('/cell-report/g1/section1', data={'week_date': '2026-11-01', 'no_meeting': 'on'})
    assert r.status_code == 302
    upd = [w for w in written(fake, 'cell_reports') if w[1] == 'update'][0][2]
    assert upd['attendance_count'] is None and upd['no_meeting'] is True


# ── GET 不得建資料列 ─────────────────────────────────
@pytest.mark.parametrize('url', [
    '/cell-report/g1/section1',
    '/cell-report/g1/section1?prefill_date=2026-10-25',
    '/cell-report/g1/section2?week_date=2026-10-25',
    '/cell-report/g1/step3?week_date=2026-10-25',
])
def test_get_never_creates_rows(cr, url):
    c, fake = cr
    r = c.get(url)
    assert r.status_code == 200 and written(fake) == [], r.status_code


def test_step3_post_still_creates_the_report(cr):
    c, fake = cr
    c.post('/cell-report/g1/step3?week_date=2026-10-25', data={
        'spiritual_status': 'good', 'family_status': 'good', 'work_status': 'good',
        'health_status': 'good', 'group_status': '平安'})
    assert any(w[1] == 'insert' and w[0] == 'cell_reports' for w in fake.writes)
