"""民國年與年齡

保險名冊要民國年。這裡守的重點是：**認不出來的一律回空，絕不猜**。

猜一個日期出去的後果是保險名冊上有一筆錯資料 —— 而錯資料看起來跟
對的一模一樣，要出事才會發現那個人根本沒被保到。
"""
from datetime import date

import re

import pytest

from routes.roc import (
    age_on, from_roc_input, normalize_year, parse_date,
    to_roc, to_roc_parts, to_roc_text,
)


# ── 解析 ──────────────────────────

@pytest.mark.parametrize('value, expected', [
    ('1999-03-05', date(1999, 3, 5)),
    ('1999/03/05', date(1999, 3, 5)),
    ('1999-03-05T00:00:00+00:00', date(1999, 3, 5)),   # 資料庫回的 ISO
    (date(1999, 3, 5), date(1999, 3, 5)),
])
def test_parse_date(value, expected):
    assert parse_date(value) == expected


@pytest.mark.parametrize('value', ['', None, '   ', '民國88年', '不知道', '99/99/99'])
def test_unparseable_returns_none(value):
    """★ 答案是使用者填的，什麼都可能出現。一律回 None，不要猜。"""
    assert parse_date(value) is None


# ── 民國年 ──────────────────────────

@pytest.mark.parametrize('iso, roc', [
    ('1999-03-05', '088/03/05'),
    ('2012-01-01', '101/01/01'),
    ('1912-01-01', '001/01/01'),      # 民國元年
    ('2026-12-31', '115/12/31'),
])
def test_to_roc(iso, roc):
    assert to_roc(iso) == roc


def test_to_roc_text_is_for_humans():
    assert to_roc_text('1999-03-05') == '民國 88 年 3 月 5 日'


def test_before_the_republic_returns_empty_not_a_negative_year():
    """★ 西元 1911 以前算出來是 0 或負數。

    回負數的話會被當成正常年份印進保險名冊 —— 一筆看起來正常的錯資料。
    """
    assert to_roc_parts('1911-06-01') is None
    assert to_roc('1911-06-01') == ''
    assert to_roc_text('1911-06-01') == ''


@pytest.mark.parametrize('bad', ['', None, '亂填的'])
def test_roc_of_garbage_is_empty(bad):
    assert to_roc(bad) == ''
    assert to_roc_text(bad) == ''


# ── 年齡 ──────────────────────────

@pytest.mark.parametrize('birth, ref, age', [
    ('2014-08-06', '2026-08-06', 12),   # 生日當天 → 已經滿 12
    ('2014-08-07', '2026-08-06', 11),   # 差一天 → 還沒滿
    ('2014-08-05', '2026-08-06', 12),
    ('1960-01-01', '2026-08-06', 66),
])
def test_age_on(birth, ref, age):
    assert age_on(birth, ref) == age


def test_the_day_before_a_birthday_still_counts_as_younger():
    """★ 這一天差一歲，而一歲就是一個票種。

    景點門票是足歲認定，差一天就差好幾百塊 —— 這條界線不能寫錯。
    """
    assert age_on('2014-10-05', '2026-10-04') == 11
    assert age_on('2014-10-05', '2026-10-05') == 12


def test_leap_day_birthday_in_a_common_year():
    """2/29 出生的人，平年要到 3/1 才算長一歲（跟戶政一致）"""
    assert age_on('2000-02-29', '2026-02-28') == 25
    assert age_on('2000-02-29', '2026-03-01') == 26
    # 閏年當天
    assert age_on('2000-02-29', '2024-02-29') == 24


def test_a_future_birthday_returns_none_not_a_negative_age():
    """打錯年份（2026 打成 2062）會算出負數。

    負數年齡印在名冊上很明顯，但如果呼叫端拿它去比大小就會靜靜出錯。
    """
    assert age_on('2030-01-01', '2026-08-06') is None


@pytest.mark.parametrize('bad', ['', None, '亂填'])
def test_age_of_garbage_is_none(bad):
    assert age_on(bad, '2026-08-06') is None


def test_age_defaults_to_today():
    """沒給基準日就用今天 —— 不該爆掉"""
    assert age_on('2000-01-01') is not None


# ══ 接到系統上 ══════════════════════════════════════

#  ★ 民國三格的 markup 現在住在 `_roc_date_field.html`（原本三個入口各抄
#    一份，而後台的編輯彈窗整個沒有 —— 使用者回報「編輯這邊生日還是跳
#    西元」的就是那一份）。所以掃原始碼的斷言要**跟著 include 進去**：
#    只掃檔案本身的話，這幾條會因為「markup 搬家了」而紅，
#    但真正要守的東西（這個入口有沒有一個能用的生日欄）其實沒變。
_INCLUDE = re.compile(r"\{%-?\s*include\s+'([^']+)'\s*-?%\}")


def _rendered_source(path):
    """把 `{% include %}` 展開一層 —— 要驗的是這一頁最後長什麼樣。"""
    src = open(path, encoding='utf-8').read()
    return _INCLUDE.sub(
        lambda m: open(f'templates/{m.group(1)}', encoding='utf-8').read(), src)


#  會讓人填生日的四個地方。★ 後台的編輯彈窗也算 —— 它是**可以改**的那個
#  入口，掉到普通文字框的後果比只是顯示錯更嚴重：同工照著「(民國)」的
#  標題把它改成 58-10-20，存進去就是一個算不出年齡的爛值，
#  身分別和「未滿18歲才問監護人」會一起靜靜地算錯。
BIRTHDAY_FORMS = (
    'templates/event_detail.html',
    'templates/external_register.html',
    'templates/admin/registrations.html',
)








def test_this_roc_year_uses_taipei_time():
    """用 UTC 的話跨年那一刻會差一年"""
    src = open('app.py', encoding='utf-8').read()
    assert 'def this_roc_year' in src
    assert 'timedelta(hours=8)' in src, 'this_roc_year 沒有用台灣時間'


def test_frontend_and_backend_agree_on_the_year_rule():
    """★ JS 和 Python 各有一份「民國還是西元」的判斷，必須一致。

    不一致的話：前端顯示「＝ 西元 1999」但後端算年齡時當成別的年 ——
    而畫面上完全看不出來。
    """
    js = open('static/js/fee-total.js', encoding='utf-8').read()
    assert 'ROC_OFFSET = 1911' in js
    assert 'normalizeRocYear' in js
    from routes.roc import ROC_OFFSET
    assert ROC_OFFSET == 1911








# ══ 民國年輸入 ══════════════════════════════════════
#
# 台灣人多半記得民國年而不是西元年，所以出生日期收的是民國。
# 但一定會有人（尤其年輕人）順手填西元 —— 兩種都要收。
#
# ★ 之所以能自動判斷而不必問使用者，是因為兩個範圍不重疊：
#   民國 1912 年是西元 3823 年，不會是任何在世的人的生日；西元 88 年也不會。
#   所以沒有一個數字同時說得通兩種解讀。

THIS_YEAR = 2026        # 民國 115


@pytest.mark.parametrize('given, expected', [
    (88, 1999),          # 民國
    ('88', 1999),        # 字串也要吃
    (' 88 ', 1999),      # 前後空白
    (1, 1912),           # 民國元年
    (115, 2026),         # 今年（民國）
    (1999, 1999),        # 西元
    (1912, 1912),        # 西元下界
    (2026, 2026),        # 今年（西元）
])
def test_normalize_year_accepts_both(given, expected):
    assert normalize_year(given, THIS_YEAR) == expected


@pytest.mark.parametrize('bad', [
    116,      # 民國 116 還沒到
    2027,     # 西元 2027 還沒到
    1911,     # 民國前
    0, -5,
    '', None, 'abc', '八十八',
])
def test_normalize_year_rejects_the_impossible(bad):
    """★ 認不出來回 None，絕不湊。

    湊出來的年份看起來跟對的一模一樣，而它會被送進保險名冊。
    """
    assert normalize_year(bad, THIS_YEAR) is None


def test_the_two_ranges_never_overlap():
    """★ 這是整個「自動判斷」能成立的前提。

    哪天有人想放寬範圍，這條會先擋下來 —— 一旦重疊，
    同一個數字會有兩種解讀，而系統只會靜靜選一種。
    """
    roc_max = THIS_YEAR - 1911          # 115
    ad_min = 1912
    assert roc_max < ad_min, '民國與西元的可接受範圍重疊了，無法再自動判斷'


def test_from_roc_input_builds_a_date():
    from datetime import date as _d
    assert from_roc_input(88, 3, 5, THIS_YEAR) == _d(1999, 3, 5)
    assert from_roc_input(1999, 3, 5, THIS_YEAR) == _d(1999, 3, 5)


@pytest.mark.parametrize('y, m, d', [
    (88, 2, 30),      # 2 月 30 日
    (88, 13, 1),      # 13 月
    (88, 0, 5),
    (88, 3, 0),
    (116, 3, 5),      # 年份不合理
    ('', 3, 5),
    (88, '', 5),
    (88, 3, ''),
])
def test_from_roc_input_rejects_nonsense(y, m, d):
    """任何一格不合理就整筆回 None —— 不要「盡量湊一個」"""
    assert from_roc_input(y, m, d, THIS_YEAR) is None


def test_a_leap_day_is_accepted_only_in_a_leap_year():
    from datetime import date as _d
    assert from_roc_input(89, 2, 29, THIS_YEAR) == _d(2000, 2, 29)   # 2000 是閏年
    assert from_roc_input(90, 2, 29, THIS_YEAR) is None              # 2001 不是


def test_normalize_year_defaults_to_this_year():
    """沒給 this_year 就用今天（台灣時間）—— 不該爆掉"""
    assert normalize_year(88) == 1999
