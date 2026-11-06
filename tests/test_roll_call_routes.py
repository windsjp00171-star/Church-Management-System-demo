import pytest

SESSION_OPEN = {'id': 's1', 'type_id': 't1', 'starts_at': '2026-11-08T02:00:00+00:00', 'status': 'open'}
SESSION_LOCKED = dict(SESSION_OPEN, status='locked')
TYPE_IND = {'id': 't1', 'name': '主日', 'record_mode': 'individual'}
TYPE_HEAD = {'id': 't1', 'name': '禱告會', 'record_mode': 'headcount'}


def load(fake, session=SESSION_OPEN, mtype=TYPE_IND):
    fake.tables['rc_sessions'] = [session]
    fake.tables['rc_meeting_types'] = [mtype]


def post(c, url, body):
    return c.post(url, json=body)


def test_api_requires_login(app):
    r = app.test_client().post('/api/roll-call/session/s1/mark', json={})
    assert r.status_code == 401


def test_plain_member_cannot_mark(fake_db, client_as):
    load(fake_db)
    r = post(client_as(), '/api/roll-call/session/s1/mark', {'member_id': 'm1', 'status': 'present'})
    assert r.status_code == 403 and fake_db.rpcs == []


def test_staff_marks_via_rpc_with_actor(fake_db, client_as):
    load(fake_db)
    r = post(client_as(is_staff=True), '/api/roll-call/session/s1/mark', {'member_id': 'm1', 'status': 'present'})
    body = r.get_json()
    assert r.status_code == 200 and body['status'] == 200 and body['error'] is None
    fn, args = fake_db.rpcs[0]
    assert fn == 'rc_save_record' and args['p_actor'] == 'op-1' and args['p_actor_name'] == '測試操作者'


def test_invalid_status_rejected_before_db(fake_db, client_as):
    load(fake_db)
    r = post(client_as(is_staff=True), '/api/roll-call/session/s1/mark', {'member_id': 'm1', 'status': 'maybe'})
    assert r.status_code == 400 and fake_db.rpcs == [] and r.get_json()['error']


def test_locked_session_blocks_staff_but_not_admin(fake_db, client_as):
    load(fake_db, SESSION_LOCKED)
    body = {'member_id': 'm1', 'status': 'absent', 'reason': '補正'}
    assert post(client_as(is_staff=True), '/api/roll-call/session/s1/mark', body).status_code == 403
    assert fake_db.rpcs == []
    assert post(client_as(is_admin=True), '/api/roll-call/session/s1/mark', body).status_code == 200
    assert fake_db.rpcs[0][1]['p_reason'] == '補正'


@pytest.mark.parametrize('raw', ['', None, '  ', 'abc', '-2'])
def test_blank_or_bad_count_never_reaches_db(fake_db, client_as, raw):
    load(fake_db, mtype=TYPE_HEAD)
    r = post(client_as(is_staff=True), '/api/roll-call/session/s1/count', {'kind': 'headcount', 'count': raw})
    assert r.status_code == 400 and fake_db.rpcs == []


def test_count_zero_explicit_is_allowed(fake_db, client_as):
    load(fake_db, mtype=TYPE_HEAD)
    r = post(client_as(is_staff=True), '/api/roll-call/session/s1/count', {'kind': 'headcount', 'count': 0})
    assert r.status_code == 200 and fake_db.rpcs[0][1]['p_count'] == 0


def test_db_error_text_not_leaked(fake_db, client_as):
    load(fake_db)
    fake_db.rpc_error = RuntimeError('connection string password=SECRET')
    r = post(client_as(is_staff=True), '/api/roll-call/session/s1/mark', {'member_id': 'm1', 'status': 'present'})
    assert r.status_code == 500 and 'SECRET' not in r.get_data(as_text=True)


def test_db_raised_message_is_shown(fake_db, client_as):
    load(fake_db)

    class E(Exception):
        code, message = 'P0001', '修改點名必須填寫原因'
    fake_db.rpc_error = E()
    r = post(client_as(is_staff=True), '/api/roll-call/session/s1/mark', {'member_id': 'm1', 'status': 'late'})
    assert r.status_code == 400 and r.get_json()['error'] == '修改點名必須填寫原因'


def test_admin_routes_reject_staff(client_as):
    c = client_as(is_staff=True)
    assert post(c, '/api/admin/roll-call/types', {'name': 'x', 'record_mode': 'individual'}).status_code == 403
    assert post(c, '/api/admin/roll-call/sessions/s1/lock', {}).status_code == 403


def test_rule_requires_every_choice(client_as):
    c = client_as(is_admin=True)
    r = post(c, '/api/admin/roll-call/rules', {'name': 'r', 'type_ids': ['t1'], 'range_start': '2026-01-01',
                                                 'range_end': '2026-12-31', 'late_mode': 'present',
                                                 'respect_membership_window': True})
    assert r.status_code == 400   # 缺 leave_mode，不替教會預設


def test_members_dedupe_by_name(fake_db, client_as):
    fake_db.tables['rc_members'] = [{'name': '王小明'}]
    r = post(client_as(is_admin=True), '/api/admin/roll-call/members', {'names': '王小明\n李小華\n李小華\n'})
    assert r.get_json()['data'] == {'added': 1, 'skipped': ['王小明']}
    assert [w for w in fake_db.writes if w[0] == 'rc_members'][0][2] == [
        {'name': '李小華', 'source': 'import', 'joined_on': None}]


def test_export_requires_super_admin_and_logs(fake_db, client_as):
    fake_db.tables['rc_rate_rules'] = [{'id': 'r1', 'name': '規則', 'version': 1, 'type_ids': ['t1'],
                                        'range_start': '2026-01-01', 'range_end': '2026-12-31',
                                        'leave_mode': 'exclude', 'late_mode': 'present',
                                        'respect_membership_window': False}]
    assert client_as(is_admin=True).get('/admin/roll-call/rates/export?rule_id=r1').status_code == 403
    r = client_as(is_super_admin=True).get('/admin/roll-call/rates/export?rule_id=r1')
    assert r.status_code == 200 and '計算依據' in r.get_data(as_text=True).replace('﻿', '')
    audit = [w for w in fake_db.writes if w[0] == 'rc_audit']
    assert audit and audit[0][2]['action'] == 'export' and audit[0][2]['actor_name'] == '測試操作者'
