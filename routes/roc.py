"""民國年與年齡

保險公司的名冊要民國年，但**存進資料庫的一定是西元**。

民國年是顯示格式，不是資料。存成民國的話，之後每次要算年齡、排序、
或換一家保險公司改格式，都得先反轉一次；而且輸入端一定會出現有人填
`111`、有人填 `民國111`、有人填 `2022` —— 三種都「看起來沒錯」。

所以：**存西元，要給人看的時候才轉民國。** 這個模組就是那層轉換。
"""
from datetime import date, datetime, timedelta, timezone

ROC_OFFSET = 1911          # 民國 1 年 = 西元 1912 年


def parse_date(value):
    """把欄位答案轉成 date。認不出來回 None（絕不猜）。

    答案是使用者填的，什麼都可能出現 —— 空字串、亂填的字、
    還沒填。這裡一律回 None，讓呼叫端顯示「—」而不是一個編出來的日期。
    """
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def to_roc_parts(value):
    """→ (民國年, 月, 日)，或 None。

    民國前的日期（西元 1912 年以前）回 None —— 那需要「民國前 N 年」
    的寫法，而報名表單不會出現。回 None 比回一個負數安全：
    負數會被當成正常年份印出去，變成保險名冊上的錯資料。
    """
    d = parse_date(value)
    if not d:
        return None
    roc_year = d.year - ROC_OFFSET
    if roc_year < 1:
        return None
    return roc_year, d.month, d.day


def to_roc(value, sep='/'):
    """→ '88/03/05'（給 Excel、給保險公司）。認不出來回空字串。"""
    parts = to_roc_parts(value)
    if not parts:
        return ''
    y, m, d = parts
    return f'{y:03d}{sep}{m:02d}{sep}{d:02d}'


def to_roc_text(value):
    """→ '民國 88 年 3 月 5 日'（給人看的）。認不出來回空字串。"""
    parts = to_roc_parts(value)
    if not parts:
        return ''
    y, m, d = parts
    return f'民國 {y} 年 {m} 月 {d} 日'


def age_on(birth, ref=None):
    """在 ref 那天滿幾歲（足歲）。算不出來回 None。

    ref 預設今天。教會旅遊的年齡基準是**活動當日**（使用者後來改的規則）——
    景點是當天查驗的，用報名日算會出現「系統說他是兒童、現場查出來是成人」。
    跨日活動用第一天。

    ★ 這表示改活動日期會連帶改金額。那是對的行為（日期真的變了），
      但改日期的人不會想到，所以後台要提醒一句。

    2/29 出生的人在平年會落在 3/1 之後才算生日 —— 這裡用「還沒到今年
    的生日就減一歲」的算法，2/29 在平年自然被當成 3/1，跟戶政一致。
    """
    b = parse_date(birth)
    if not b:
        return None
    r = parse_date(ref) or datetime.now(timezone(timedelta(hours=8))).date()     # 沒給基準日＝台北的今天，不看伺服器時區
    if r < b:
        return None          # 生日在未來 —— 多半是打錯，不要回負數
    had_birthday = (r.month, r.day) >= (b.month, b.day)
    return r.year - b.year - (0 if had_birthday else 1)


def normalize_year(value, this_year=None):
    """把使用者填的「年」正規化成西元年。認不出來回 None。

    台灣人多半記得民國年而不是西元年，所以出生日期的輸入欄位收的是民國。
    但一定會有人（尤其年輕人）順手填西元 —— 所以兩種都要收。

    ★ 這件事之所以可以自動判斷而不必問使用者，是因為兩個範圍不重疊：

        1 ~ 今年的民國年      → 民國（例如 88 → 1999）
        1912 ~ 今年的西元年   → 西元（例如 1999 → 1999）

      民國 1912 年是西元 3823 年，不會是任何在世的人的生日；
      西元 88 年也不會。所以沒有一個數字同時說得通兩種解讀。

      「請選擇你要填西元還是民國」那種問法本身就會卡住人 ——
      能自動判斷就不要問。
    """
    try:
        y = int(str(value).strip())
    except (TypeError, ValueError):
        return None

    if this_year is None:
        from datetime import datetime, timedelta, timezone
        this_year = datetime.now(timezone(timedelta(hours=8))).year

    if 1 <= y <= this_year - ROC_OFFSET:      # 民國
        return y + ROC_OFFSET
    if ROC_OFFSET + 1 <= y <= this_year:      # 西元
        return y
    return None                                # 未來、或明顯打錯


def from_roc_input(year, month, day, this_year=None):
    """三個輸入框 → 西元的 date。任何一格不合理就回 None。

    回 None 而不是「盡量湊一個」—— 湊出來的日期看起來跟對的一模一樣，
    而它會被送進保險名冊。
    """
    y = normalize_year(year, this_year)
    if y is None:
        return None
    try:
        m, d = int(str(month).strip()), int(str(day).strip())
        return date(y, m, d)      # 2 月 30 日之類的會在這裡 ValueError
    except (TypeError, ValueError):
        return None
