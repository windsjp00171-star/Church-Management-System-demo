"""差勤計算邏輯單元測試 — 不需要資料庫連線"""
from datetime import date

def _annual_leave_days(years: int) -> int:
    if years < 1:   return 3   # 半年~未滿1年
    if years < 2:   return 7
    if years < 3:   return 10
    if years < 5:   return 14
    if years < 10:  return 15
    return min(15 + int(years - 10) + 1, 30)

def _months_elapsed(from_date: date, to_date: date) -> int:
    m = (to_date.year - from_date.year) * 12 + to_date.month - from_date.month
    if to_date.day < from_date.day:
        m -= 1
    return m

def _full_years_elapsed(from_date: date, to_date: date) -> int:
    y = to_date.year - from_date.year
    try:
        ann = from_date.replace(year=to_date.year)
    except ValueError:
        ann = from_date.replace(year=to_date.year, day=28)
    if to_date < ann:
        y -= 1
    return max(y, 0)

def _calc_entitlement(hire_date: date, cycle: str, today: date = None) -> float:
    today = today or date.today()
    if cycle == 'anniversary':
        months = _months_elapsed(hire_date, today)
        if months < 6:
            return 0.0
        full_years = _full_years_elapsed(hire_date, today)
        days = 3 if full_years < 1 else _annual_leave_days(full_years)
    else:
        jan1 = date(today.year, 1, 1)
        months = _months_elapsed(hire_date, jan1)
        if months < 6:
            return 0.0
        full_years = _full_years_elapsed(hire_date, jan1)
        days = 3 if full_years < 1 else _annual_leave_days(full_years)
    return days * 8.0

all_ok = True
ref = date(2026, 5, 22)

def check(label, got, expected):
    global all_ok
    ok = got == expected
    if not ok: all_ok = False
    print(f"  {'✓' if ok else '✗'} {label} → {got} {'(應為'+str(expected)+')' if not ok else ''}")

# ── 勞基法天數對照表 ────────────────────────────────────
print("=== 勞基法特休天數 ===")
for years, expected, label in [
    (0,  3,  "未滿1年（半年後）"),
    (1,  7,  "滿1年"),
    (2, 10,  "滿2年"),
    (3, 14,  "滿3年"),
    (5, 15,  "滿5年"),
    (9, 15,  "滿9年"),
    (10,16,  "滿10年"),
    (11,17,  "滿11年"),
    (25,30,  "滿25年（上限30天）"),
]:
    check(label, _annual_leave_days(years), expected)

# ── 週年制時數 ──────────────────────────────────────────
print("\n=== 特休時數（週年制，基準 2026-05-22）===")
for hire, expected, label in [
    (date(2026,  1, 22),   0.0, "入職4個月"),
    (date(2025, 11, 23),   0.0, "入職未滿6個月（差1天）"),
    (date(2025, 11, 22),  24.0, "入職剛好6個月 → 3天"),
    (date(2025,  5, 23),  24.0, "入職364天，未滿1年 → 3天"),
    (date(2025,  5, 22),  56.0, "入職整1年 → 7天"),
    (date(2024,  5, 22),  80.0, "入職2年 → 10天"),
    (date(2023,  5, 22), 112.0, "入職3年 → 14天"),
    (date(2021,  5, 22), 120.0, "入職5年 → 15天"),
    (date(2016,  5, 22), 128.0, "入職10年 → 16天"),
    (date(2015,  5, 22), 136.0, "入職11年 → 17天"),
]:
    check(label, _calc_entitlement(hire, 'anniversary', today=ref), expected)

# ── 曆年制時數 ──────────────────────────────────────────
print("\n=== 特休時數（曆年制，基準 2026-05-22，參照 2026-01-01）===")
for hire, expected, label in [
    (date(2025,  8,  1),   0.0, "Jan1時入職5個月，未到半年"),
    (date(2025,  7,  1),  24.0, "Jan1時剛好6個月 → 3天"),
    (date(2025,  1,  1),  56.0, "Jan1時整1年 → 7天"),
    (date(2024,  1,  1),  80.0, "Jan1時整2年 → 10天"),
    (date(2021,  1,  1), 120.0, "Jan1時整5年 → 15天"),
    (date(2016,  1,  1), 128.0, "Jan1時整10年 → 16天"),
]:
    check(label, _calc_entitlement(hire, 'calendar', today=ref), expected)

# ── 邊界：閏年2月29日入職 ────────────────────────────────
print("\n=== 邊界：閏年 2 月 29 日入職 ===")
hire_leap = date(2024, 2, 29)
check("2026-02-28（非閏年）不崩潰", type(_calc_entitlement(hire_leap, 'anniversary', today=date(2026, 2, 28))), float)
check("2026-03-01 應有半年以上年資", _calc_entitlement(hire_leap, 'anniversary', today=date(2026, 3, 1)) > 0, True)

print(f"\n{'✅ 全部通過' if all_ok else '❌ 有測試失敗'}")
