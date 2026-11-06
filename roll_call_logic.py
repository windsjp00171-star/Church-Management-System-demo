"""聚會點名：純邏輯（不連資料庫、不依賴 Flask，可直接單元測試）。

出席率完全在伺服器端算；規則是資料（rc_rate_rules），不是程式常數。
被點名的人是 rc_members（點名名冊），與 users 無關。
"""
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

STATUSES = ('present', 'absent', 'leave', 'late')
STATUS_LABELS = {'present': '到', 'absent': '未到', 'leave': '請假', 'late': '遲到'}
LEAVE_MODES = ('exclude', 'absent', 'present')
LATE_MODES = ('present', 'absent', 'half')

LEAVE_MODE_LABELS = {
    'exclude': '請假不計入分母',
    'absent': '請假算未到',
    'present': '請假算到',
}
LATE_MODE_LABELS = {
    'present': '遲到算到',
    'absent': '遲到算未到',
    'half': '遲到算半次',
}

_TAIPEI = timezone(timedelta(hours=8))


def to_taipei(value):
    """UTC ISO 字串或 datetime → 台北時間 datetime。時間一律以 UTC 儲存，顯示前才轉。"""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_TAIPEI)


def taipei_input_to_utc_iso(date_str, time_str):
    """表單輸入的台北日期＋時間 → UTC ISO 字串。"""
    local = datetime.fromisoformat(f'{date_str}T{time_str}').replace(tzinfo=_TAIPEI)
    return local.astimezone(timezone.utc).isoformat()


def validate_status(value):
    if value not in STATUSES:
        raise ValueError('無效的點名狀態')
    return value


def parse_count(raw):
    """人數欄位：空白、非整數、負數一律退回，絕不預設為 0。"""
    if raw is None or isinstance(raw, bool):
        raise ValueError('人數不可空白')
    if isinstance(raw, int):
        n = raw
    else:
        text = str(raw).strip()
        if text == '':
            raise ValueError('人數不可空白')
        try:
            n = int(text)
        except ValueError:
            raise ValueError('人數必須是整數')
    if n < 0:
        raise ValueError('人數不可為負數')
    return n


def validate_rule(rule):
    """規則必須明確給定，沒有預設值（教會決定，問卷回收前不替他們選）。"""
    if rule.get('leave_mode') not in LEAVE_MODES:
        raise ValueError('請選擇請假的算法')
    if rule.get('late_mode') not in LATE_MODES:
        raise ValueError('請選擇遲到的算法')
    if not isinstance(rule.get('respect_membership_window'), bool):
        raise ValueError('請選擇中途加入／離開者的算法')
    if not rule.get('type_ids'):
        raise ValueError('請至少選一個聚會類型')
    start, end = _as_date(rule.get('range_start')), _as_date(rule.get('range_end'))
    if end < start:
        raise ValueError('結束日不可早於起始日')
    return rule


def _as_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        raise ValueError('請填寫起訖日期')
    return date.fromisoformat(str(value)[:10])


def describe_rule(rule):
    """匯出時附上的計算依據（讓遴選小組能核對）。"""
    window = '只計在籍期間內的場次' if rule['respect_membership_window'] else '不論在籍期間，範圍內所有場次都計'
    return (f"規則「{rule.get('name', '')}」第 {rule.get('version', '?')} 版；"
            f"{rule['range_start']} ～ {rule['range_end']}；"
            f"{LEAVE_MODE_LABELS[rule['leave_mode']]}；{LATE_MODE_LABELS[rule['late_mode']]}；{window}；"
            "只計已鎖定的場次；已鎖定場次中沒有紀錄者算未到")


def compute_member_rate(member, sessions, records, rule):
    """計算一位名冊成員在規則下的出席率。

    member   : {'id', 'joined_on', 'left_on'}（日期可為 None / ISO 字串）
    sessions : [{'id', 'type_id', 'starts_at', 'status'}]（starts_at 為 UTC）
    records  : {(session_id, member_id): status}
    rule     : rc_rate_rules 的一列
    回傳 {'numerator', 'denominator', 'percent', 'details'}；分母為 0 時 percent 為 None。
    只讀傳入的資料；前端送來的任何數值都不會進到這裡。
    """
    validate_rule(rule)
    start, end = _as_date(rule['range_start']), _as_date(rule['range_end'])
    type_ids = {str(t) for t in rule['type_ids']}
    joined = _as_date(member['joined_on']) if member.get('joined_on') else None
    left = _as_date(member['left_on']) if member.get('left_on') else None

    num, den = Fraction(0), Fraction(0)
    details = []
    for s in sorted(sessions, key=lambda x: x['starts_at']):
        if str(s['type_id']) not in type_ids or s.get('status') != 'locked':
            continue
        day = to_taipei(s['starts_at']).date()
        if not (start <= day <= end):
            continue
        if rule['respect_membership_window']:
            if (joined and day < joined) or (left and day > left):
                continue

        status = records.get((s['id'], member['id'])) or 'absent'   # 鎖定場次無紀錄＝未到
        n, d = _weight(status, rule)
        num += n
        den += d
        details.append({'session_id': s['id'], 'date': day.isoformat(), 'status': status,
                        'counted': d > 0, 'numerator': str(n), 'denominator': str(d)})

    percent = None
    if den > 0:
        ratio = num / den
        percent = (Decimal(ratio.numerator) * 100 / Decimal(ratio.denominator)).quantize(
            Decimal('0.1'), rounding=ROUND_HALF_UP)
    return {'numerator': num, 'denominator': den, 'percent': percent, 'details': details}


def _weight(status, rule):
    """單一場次的 (分子, 分母) 貢獻。"""
    if status == 'present':
        return Fraction(1), Fraction(1)
    if status == 'absent':
        return Fraction(0), Fraction(1)
    if status == 'leave':
        mode = rule['leave_mode']
        return {'exclude': (Fraction(0), Fraction(0)),
                'absent': (Fraction(0), Fraction(1)),
                'present': (Fraction(1), Fraction(1))}[mode]
    if status == 'late':
        mode = rule['late_mode']
        return {'present': (Fraction(1), Fraction(1)),
                'absent': (Fraction(0), Fraction(1)),
                'half': (Fraction(1, 2), Fraction(1))}[mode]
    raise ValueError('無效的點名狀態')


def can_mark(session_row, is_admin, is_staff):
    """誰能點名：同工（含牧者）可點名開放中的場次；已鎖定場次只有管理員
    （且必須附原因，由資料庫函式強制）。第一階段不做「指派負責人」，待與教會討論。"""
    if is_admin:
        return True
    return bool(is_staff) and session_row.get('status') != 'locked'
