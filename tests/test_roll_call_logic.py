from datetime import date

import pytest

from roll_call_logic import (
    can_mark, compute_member_rate, describe_rule, parse_count, taipei_input_to_utc_iso,
    to_taipei, validate_rule, validate_status,
)

TYPE = 'type-1'
M = {'id': 'm1', 'joined_on': None, 'left_on': None}


def sess(sid, day, status='locked', type_id=TYPE):
    # 台北 10:00 = UTC 02:00
    return {'id': sid, 'type_id': type_id, 'starts_at': f'{day}T02:00:00+00:00', 'status': status}


def rule(**kw):
    base = dict(name='r', version=1, type_ids=[TYPE], range_start='2026-01-01', range_end='2026-12-31',
                leave_mode='exclude', late_mode='present', respect_membership_window=False)
    base.update(kw)
    return base


# 守衛 25：空白必須退回，不得當 0
@pytest.mark.parametrize('raw', [None, '', '   ', True])
def test_count_blank_rejected(raw):
    with pytest.raises(ValueError):
        parse_count(raw)


@pytest.mark.parametrize('raw', ['abc', '-1', -3, '1.5'])
def test_count_invalid_rejected(raw):
    with pytest.raises(ValueError):
        parse_count(raw)


def test_count_zero_is_explicit_zero():
    assert parse_count('0') == 0 and parse_count(0) == 0   # 明確填 0 才是 0


def test_status_validation():
    assert validate_status('late') == 'late'
    with pytest.raises(ValueError):
        validate_status('maybe')


# 守衛 15：時間存 UTC、顯示轉台北
def test_timezone_roundtrip():
    utc = taipei_input_to_utc_iso('2026-11-08', '10:00')
    assert utc.startswith('2026-11-08T02:00:00')
    assert to_taipei(utc).hour == 10


def test_taipei_date_crosses_midnight():
    # UTC 2026-11-07 17:00 = 台北 11-08 01:00，場次日期必須是台北日期
    s = {'id': 's', 'type_id': TYPE, 'starts_at': '2026-11-07T17:00:00+00:00', 'status': 'locked'}
    r = compute_member_rate(M, [s], {('s', 'm1'): 'present'}, rule(range_start='2026-11-08', range_end='2026-11-08'))
    assert r['denominator'] == 1


# 守衛 5：分母與請假、遲到算法
def test_basic_rate():
    sessions = [sess('a', '2026-03-01'), sess('b', '2026-03-08'), sess('c', '2026-03-15'), sess('d', '2026-03-22')]
    recs = {('a', 'm1'): 'present', ('b', 'm1'): 'present', ('c', 'm1'): 'present', ('d', 'm1'): 'absent'}
    r = compute_member_rate(M, sessions, recs, rule())
    assert (r['numerator'], r['denominator']) == (3, 4) and str(r['percent']) == '75.0'


@pytest.mark.parametrize('mode,num,den', [('exclude', 1, 1), ('absent', 1, 2), ('present', 2, 2)])
def test_leave_modes(mode, num, den):
    sessions = [sess('a', '2026-03-01'), sess('b', '2026-03-08')]
    recs = {('a', 'm1'): 'present', ('b', 'm1'): 'leave'}
    r = compute_member_rate(M, sessions, recs, rule(leave_mode=mode))
    assert (r['numerator'], r['denominator']) == (num, den)


@pytest.mark.parametrize('mode,num,den', [('present', 1, 1), ('absent', 0, 1), ('half', 0.5, 1)])
def test_late_modes(mode, num, den):
    r = compute_member_rate(M, [sess('a', '2026-03-01')], {('a', 'm1'): 'late'}, rule(late_mode=mode))
    assert (float(r['numerator']), r['denominator']) == (num, den)


def test_only_locked_sessions_count():
    sessions = [sess('a', '2026-03-01'), sess('b', '2026-03-08', status='open')]
    r = compute_member_rate(M, sessions, {('a', 'm1'): 'present'}, rule())
    assert r['denominator'] == 1


def test_missing_record_in_locked_session_is_absent():
    r = compute_member_rate(M, [sess('a', '2026-03-01')], {}, rule())
    assert (r['numerator'], r['denominator']) == (0, 1)


def test_other_types_and_out_of_range_excluded():
    sessions = [sess('a', '2026-03-01'), sess('b', '2026-03-08', type_id='other'), sess('c', '2027-01-01')]
    r = compute_member_rate(M, sessions, {}, rule())
    assert r['denominator'] == 1


def test_membership_window():
    m = {'id': 'm1', 'joined_on': '2026-03-05', 'left_on': '2026-03-20'}
    sessions = [sess('a', '2026-03-01'), sess('b', '2026-03-08'), sess('c', '2026-03-15'), sess('d', '2026-03-22')]
    recs = {(s['id'], 'm1'): 'present' for s in sessions}
    assert compute_member_rate(m, sessions, recs, rule(respect_membership_window=True))['denominator'] == 2
    assert compute_member_rate(m, sessions, recs, rule(respect_membership_window=False))['denominator'] == 4


def test_no_sessions_gives_no_percent():
    assert compute_member_rate(M, [], {}, rule())['percent'] is None


# 規則沒有預設值：教會沒決定前不替他們選
@pytest.mark.parametrize('field,value', [('leave_mode', None), ('late_mode', 'x'),
                                         ('respect_membership_window', None), ('type_ids', [])])
def test_rule_has_no_defaults(field, value):
    with pytest.raises(ValueError):
        validate_rule(rule(**{field: value}))


def test_rule_end_before_start_rejected():
    with pytest.raises(ValueError):
        validate_rule(rule(range_start='2026-05-01', range_end='2026-04-01'))


def test_describe_rule_names_version_and_modes():
    text = describe_rule(rule(name='遴選', version=3))
    assert '第 3 版' in text and '請假不計入分母' in text and '遲到算到' in text


# 守衛 6：點名者、修改者分權
def test_can_mark_roles():
    open_s, locked = {'status': 'open'}, {'status': 'locked'}
    assert can_mark(open_s, False, True)
    assert not can_mark(open_s, False, False)
    assert not can_mark(locked, False, True)       # 鎖定後一般同工不可改
    assert can_mark(locked, True, True)            # 管理員可（原因由資料庫強制）
