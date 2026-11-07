"""時間的唯一來源：存 UTC、顯示前轉台北

## 為什麼要有這個模組

這個專案的時區 bug 已經踩過三次，形狀完全一樣：**畫面每一格都有東西、
格式完全正常，只是時間是假的**。

而根因不是「時區很難」，是三件事疊在一起：

1. **轉換是「約定」不是「邊界」**。讀這些欄位的地方有 ~65 處，
   每一處都要作者自己記得先轉。漏掉幾次是必然，不是意外。
2. **轉換函式本身就不只一份** —— 寫入 2 份、讀取 3 份（其中兩份同名
   `_to_taipei` 但行為不同）。連單一來源都不單一。
3. **它幾乎總是看起來對的**。差 8 小時只有兩種時候會被看見：你剛好去
   核對，或者事件在早上 8 點以前（唯一會連日期都跑掉的區間）。
   教會的活動大多在下午晚上，所以這個 bug 大部分時間是隱形的。

## ★ 資料庫的事實（2026-08 用 information_schema 查過）

**`public` schema 裡 90 幾個時間欄位，全部都是 `timestamp with time zone`，
一個 naive 的都沒有。**

所以 PostgREST 一律回傳 UTC，跟寫進去時帶什麼時區無關：

    寫入 datetime.now(TAIPEI_TZ).isoformat()  → '2026-08-09T13:22:33+08:00'
    讀出來                                     → '2026-08-09T05:22:33+00:00'

**推論：任何時間欄位切字串都是錯的。** 不必逐欄位判斷「這欄是不是 UTC」——
沒有例外。

    raw[:10]     # ← UTC 的日期。早上 8 點以前會退到前一天
    raw[11:16]   # ← UTC 的時間。永遠早 8 小時
    raw >= today # ← 拿 UTC 比台北的今天

一律用這裡的函式。`tests/test_time_handling.py` 用 AST 掃著
（掃 AST 不掃文字 —— 註解天生騙不了它，而這個專案已經被自己的註解
騙過兩次）。

## 「沒有時區的字串」要當成什麼？

資料庫不會給出這種值（見上面），但表單會（`datetime-local` 是 naive），
而舊資料也可能有。三份舊 helper 對它給三種答案，所以這裡**要求明講**：

    to_taipei(s, naive_is='utc')     # 資料庫來的
    to_taipei(s, naive_is='taipei')  # 表單、使用者輸入來的

★ 不給預設值是故意的？不是 —— 預設 `'utc'`（資料庫是主要來源），
  但 `naive_is` 一定要能被指定，因為舊呼叫端的行為不一樣，
  合併時不可以偷偷改掉它們。
"""
from datetime import datetime, timedelta, timezone

TAIPEI_TZ = timezone(timedelta(hours=8))

# ── 所有 timestamptz 欄位名 ────────────────────────────
# 從 information_schema 撈出來的（見模組開頭）。守衛測試拿它比對。
#
# ★ 新增時間欄位時要補一行。漏補的後果是「那個欄位不受守衛保護」——
#   所以守衛另外有一條：欄位名長得像時間（`*_at` / `*_time` /
#   `*_deadline` / `*_start` / `*_end`）卻不在這裡，也會紅。
UTC_COLUMNS = frozenset({
    'answered_at', 'archived_at', 'attended_at', 'changed_at', 'checked_in_at',
    'completed_at', 'confirmed_at', 'created_at', 'end_time', 'event_end',
    'fetched_at', 'lock_released_at',
    'event_start', 'granted_at', 'last_seen_changelog_at',
    'material_received_at', 'member_reserved_until', 'paid_at',
    'payment_deadline', 'published_at', 'reg_deadline', 'reg_end', 'reg_start',
    'registered_at', 'reviewed_at', 'revoked_at', 'scheduled_at',
    'submitted_at', 'updated_at', 'waitlist_deadline',
})


def _parse(s, naive_is):
    """字串 → aware datetime。壞掉回 None（呼叫端不可以當成「現在」）。"""
    if not s:
        return None
    if isinstance(s, datetime):
        dt = s
    else:
        try:
            t = str(s)
            if t.endswith('Z'):
                t = t[:-1] + '+00:00'
            dt = datetime.fromisoformat(t)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        if naive_is == 'taipei':
            dt = dt.replace(tzinfo=TAIPEI_TZ)
        elif naive_is == 'utc':
            dt = dt.replace(tzinfo=timezone.utc)
        else:                       # 'keep'：維持 naive（舊 calendar 的行為）
            return dt
    return dt


def to_taipei(s, naive_is='utc'):
    """資料庫的時間字串 → 台北時間 datetime（aware）。壞掉回 None。"""
    dt = _parse(s, naive_is)
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(TAIPEI_TZ)


def to_utc(s, naive_is='taipei'):
    """表單值（台北）→ UTC ISO 字串，給寫入用。壞掉回 None。

    ★ 預設 `naive_is='taipei'`：這一支的輸入來自 `datetime-local`，
      使用者打的就是台北時間。
    """
    dt = _parse(s, naive_is)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI_TZ)
    return dt.astimezone(timezone.utc).isoformat()


def parts(s, naive_is='utc'):
    """→ ('YYYY-MM-DD', 'HH:MM')，兩個都是台北時間。壞掉回 ('', '')。

    ★ 日期和時間一起給，是因為**只修日期不修時間**是這個 bug 最常見的
      半套修法：日期看起來對了（下午的活動本來就同一天），
      時間還是早 8 小時。
    """
    dt = to_taipei(s, naive_is)
    return (dt.strftime('%Y-%m-%d'), dt.strftime('%H:%M')) if dt else ('', '')


def date_str(s, naive_is='utc'):
    """→ 'YYYY-MM-DD'（台北）。取代 `raw[:10]`。"""
    return parts(s, naive_is)[0]


def time_str(s, naive_is='utc'):
    """→ 'HH:MM'（台北）。取代 `raw[11:16]`。"""
    return parts(s, naive_is)[1]


def day_bounds_utc(day):
    """台北某一天的 [起, 迄) → UTC ISO 字串，給查詢條件用。

    ★ 查詢要比的是 UTC，所以**不是**把欄位轉台北再比（那樣索引用不到，
      而且 Supabase 那一端也做不到）—— 是把台北的邊界轉成 UTC。
      `.gte('scheduled_at', now.strftime('%Y-%m-%dT00:00:00'))` 這種
      寫法是錯的：右邊是台北的字串，左邊是 UTC 的欄位。
    """
    if isinstance(day, datetime):
        day = day.astimezone(TAIPEI_TZ).date()
    start = datetime(day.year, day.month, day.day, tzinfo=TAIPEI_TZ)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc).isoformat(), \
        end.astimezone(timezone.utc).isoformat()


def now_taipei():
    return datetime.now(TAIPEI_TZ)


# ══════════════════════════════════════════════════════
#  執行期防護：時間欄位讀出來是「不給切的字串」
# ══════════════════════════════════════════════════════
#
# `tests/test_time_handling.py` 那條 AST 守衛擋的是**寫得出來的**錯誤。
# 這一層擋的是它看不到的：動態取欄位（`row[col]`，欄位名是變數）、
# 以及從別處傳進來的值。
#
# ## 為什麼是 str 的子類，不是 datetime
#
# 一開始的計畫是「讀出來就是 datetime 物件」。實測發現不行：
#
#     jsonify({'attended_at': datetime(...)})
#     → {"attended_at": "Sun, 09 Aug 2026 05:22:33 GMT"}   ← RFC 822，不是 ISO
#
# 而有 18 條路由直接把整列丟 `jsonify`。那等於**悄悄改掉 API 的格式** ——
# 前端照樣渲染、字串全錯，正是這個專案最常出事的形狀。
#
# str 的子類則完全透明（都實測過）：
#
#     jsonify / json.dumps  → 一模一樣的 ISO 字串
#     跟字串比大小、== 、f-string、fromisoformat → 全部照舊
#     v[:10] → TypeError，訊息直接說該用什麼
#
# ## 出事時怎麼關掉
#
# 環境變數 `TW_TIME_GUARD=off`。這一層是防護不是功能，
# 萬一它自己出問題，關掉之後系統要能照常跑。

class GuardedTime(str):
    """時間欄位的值。跟普通字串一模一樣，只是不給切。

    ★ 不擋 `.split('T')[0]` 那種寫法 —— 擋得完的只有最常見的那一種。
      這一層是補 AST 守衛的漏，不是取代它。
    """
    __slots__ = ()

    def __getitem__(self, key):
        if isinstance(key, slice):
            raise TypeError(
                '時間欄位存的是 UTC，切字串會差 8 小時（早上 8 點以前連日期都會退一天）。'
                '要台北的日期用 routes.tw_time.date_str()、時間用 time_str()、'
                '兩個一起用 parts()。'
                '真的要比原始 UTC 字串，先 str() 一次並註明理由。')
        return super().__getitem__(key)


def guard_row(row):
    """把一列裡的時間欄位換成 GuardedTime。就地改，回傳同一個 dict。"""
    if not isinstance(row, dict):
        return row
    for col in UTC_COLUMNS:
        v = row.get(col)
        if type(v) is str:          # 已經包過或不是字串就不要再動
            row[col] = GuardedTime(v)
    return row


def guard_data(data):
    """`execute().data` 的內容 → 包好時間欄位。"""
    if isinstance(data, list):
        for r in data:
            guard_row(r)
    elif isinstance(data, dict):
        guard_row(data)
    return data
