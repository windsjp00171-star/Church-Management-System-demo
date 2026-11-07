# 行事曆訂閱（.ics）
#
# 使用者：「行事曆訂閱我個人也覺得是好東西可以做」
#
# ★★ 這個功能的價值就一句話：**不用回來看**。訂閱一次之後，教會的聚會
#    直接長在他自己手機的日曆上，跟上班、接小孩排在一起 —— 而那才是
#    他真正在看的那一本。回到我們的頁面才看得到的東西，多數人不會回來。
#
# ★ 訂閱網址**不可以要登入**：Google 日曆、iOS「訂閱行事曆」去抓的時候
#   不會帶 cookie，只會拿到登入頁，而畫面上的症狀是「訂閱了但一直是空的」。
#   所以身分放在網址裡的簽章 token —— 跟 `routes/pwa_session` 同一套簽章，
#   不另外發明一份（salt 不同，所以續登的 token 不能拿來讀行事曆）。
#
# ★ token **沒有短效期**（訂閱是裝一次用好幾年）。代價要講清楚：
#   網址等於他的行事曆，轉發出去就是把個人行程給了對方。頁面上要寫。

from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, session, request, abort, current_app

from db import supabase
from routes.pwa_session import issue_token, verify_token

calendar_feed_bp = Blueprint('calendar_feed', __name__)

FEED_SALT = 'calendar-feed'
#  10 年。★ 過期的症狀是「訂閱的日曆從某一天起再也不更新」，
#  而**手機不會告訴他**——所以寧可長，不要讓它默默死掉。
FEED_MAX_AGE = 60 * 60 * 24 * 365 * 10

TAIPEI = timezone(timedelta(hours=8))

#  撈多遠。★ 不是全部 —— 訂閱的人不需要三年前的聚會，
#  而 feed 越小、手機抓得越快。
DAYS_BACK = 90
DAYS_AHEAD = 400


# ── ICS 格式的三件小事，錯了會整份日曆讀不進去 ──────────────

def esc(text):
    """TEXT 值要跳脫反斜線、分號、逗號、換行（RFC 5545 §3.3.11）。

    ★ 不跳脫的話，標題裡一個逗號就會被當成「兩個值」，
      而多數客戶端的反應是**整個事件消失**，不是顯示錯誤。
    """
    s = '' if text is None else str(text)
    return (s.replace('\\', '\\\\')
             .replace(';', r'\;')
             .replace(',', r'\,')
             .replace('\r\n', r'\n')
             .replace('\n', r'\n')
             .replace('\r', r'\n'))


def fold(line):
    """折行：一行不可以超過 75 個**位元組**（不是 75 個字）。

    ★ 中文一個字 3 個位元組，所以 26 個字就超過了 —— 幾乎每一個
      教會行事的標題都會超過。不折的話 Google 日曆會直接跳過那一行。
    ★ 折的時候**不可以把一個中文字切成兩半**：所以是逐字累加位元組，
      不是對 bytes 切片。切壞的後果是整份 feed 變成亂碼。
    """
    out, cur, size = [], '', 0
    for ch in line:
        n = len(ch.encode('utf-8'))
        # 續行前面要加一個空白，所以續行的可用長度少 1
        limit = 75 if not out else 74
        if size + n > limit:
            out.append(cur)
            cur, size = ch, n
        else:
            cur += ch
            size += n
    out.append(cur)
    return out[0] + ''.join('\r\n ' + seg for seg in out[1:])


def ics_datetime(dt):
    """有時間的事件一律輸出 UTC 的 `...Z`。

    ★ 這正好繞開這個專案踩過三次的時區坑：資料庫存的就是 UTC，
      不轉就不會錯。客戶端自己會用使用者的時區顯示。
    """
    return dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _parse_utc(raw):
    """資料庫的 timestamptz 字串 → aware datetime。算不出來回 None。

    ★ **不可以切字串**（`[:10]` 那種）—— 那是這個專案的 AST 守衛在擋的
      寫法，而且會在早上 8 點前把日期算成前一天。
    """
    if not raw:
        return None
    try:
        s = str(raw).replace('Z', '+00:00')
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_date(raw):
    """純日期欄位（DATE）→ date。算不出來回 None。"""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).date()
    except (ValueError, TypeError):
        return None


# ── 事件 ────────────────────────────────────────────────

def _vevent(uid, summary, dtstamp, *, day=None, end_day=None,
            start_dt=None, end_dt=None, description='', location=''):
    """一個 VEVENT。全天事件給 day/end_day，有時間的給 start_dt/end_dt。"""
    lines = ['BEGIN:VEVENT', f'UID:{uid}', f'DTSTAMP:{ics_datetime(dtstamp)}']
    if day is not None:
        lines.append('DTSTART;VALUE=DATE:' + day.strftime('%Y%m%d'))
        #  ★ 全天事件的 DTEND 是**結束日的隔天**（RFC 是「不包含」的）。
        #    直接放結束日的話，跨日的特會在手機上會少一天，
        #    而且看起來完全正常。
        last = end_day or day
        lines.append('DTEND;VALUE=DATE:' + (last + timedelta(days=1)).strftime('%Y%m%d'))
    else:
        lines.append('DTSTART:' + ics_datetime(start_dt))
        lines.append('DTEND:' + ics_datetime(end_dt or start_dt))
    lines.append('SUMMARY:' + esc(summary))
    if description:
        lines.append('DESCRIPTION:' + esc(description))
    if location:
        lines.append('LOCATION:' + esc(location))
    lines.append('END:VEVENT')
    return lines


def build_ics(church, events, personal, *, name='教會行事曆', now=None):
    """三種來源 → 一份 .ics 的文字。**純函式，不碰資料庫**（好測）。"""
    now = now or datetime.now(timezone.utc)
    out = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//anbolc//church calendar//ZH-TW',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:' + esc(name),
        'X-WR-TIMEZONE:Asia/Taipei',
        #  多久回來抓一次。
        #
        #  ★★ 這兩行是**建議，不是命令** —— 訂閱的那一端什麼時候來抓，
        #    決定權在它。實測／官方說法：
        #
        #      Google 日曆    大致每 8～24 小時，**不理會這兩行**
        #      Apple 日曆     會理，而且 iPhone 上還可以自己改
        #                     （行事曆 →「訂閱的行事曆」→ 重新整理頻率）
        #      Outlook        大致 3 小時
        #
        #  使用者回報過：「我在系統新增好像不會即時新增行程到 GOOGLE 日曆」。
        #  ★ 那**不是壞了**，是 Google 還沒回來抓。我們這邊唯一能做的
        #    就是把建議值壓低、而且不要用快取擋住它（見底下的 no-cache）。
        #    ★ 真的要「馬上知道」的東西不要靠這條路 —— 走站內通知／推播，
        #      那兩個是我們推出去的，不用等別人來拿。
        'REFRESH-INTERVAL;VALUE=DURATION:PT1H',
        'X-PUBLISHED-TTL:PT1H',
    ]

    for e in church or []:
        day = _parse_date(e.get('event_date'))
        if not day:
            continue                      # 算不出日期的就跳過，不要猜一天
        out += _vevent(
            f"church-{e.get('id')}@anbolc", e.get('title') or '教會行事', now,
            day=day, end_day=_parse_date(e.get('end_date')) or day,
            description=e.get('description') or '')

    for e in events or []:
        start = _parse_utc(e.get('event_start'))
        if not start:
            continue
        out += _vevent(
            f"event-{e.get('id')}@anbolc", e.get('title') or '活動', now,
            start_dt=start, end_dt=_parse_utc(e.get('event_end')) or start,
            location=e.get('location') or '')

    for e in personal or []:
        day = _parse_date(e.get('event_date'))
        if not day:
            continue
        out += _vevent(
            f"personal-{e.get('id')}@anbolc", e.get('title') or '個人行程', now,
            day=day, description=e.get('description') or '')

    out.append('END:VCALENDAR')
    #  ★ 一律 CRLF —— RFC 要求，而且有客戶端真的會因為 LF 而整份不讀。
    return '\r\n'.join(fold(line) for line in out) + '\r\n'


# ── 網址 ────────────────────────────────────────────────

def feed_url_for(secret, user_id, base=''):
    """個人的訂閱網址。沒登入回空字串（呼叫端就不要畫那一塊）。"""
    token = issue_token(secret, user_id, FEED_SALT)
    return f'{base}/calendar.ics?t={token}' if token else ''


@calendar_feed_bp.route('/calendar.ics')
def calendar_ics():
    """訂閱端點。**不經過登入**，身分看網址裡的簽章。"""
    uid = verify_token(current_app.secret_key, request.args.get('t'),
                       max_age=FEED_MAX_AGE, salt=FEED_SALT)
    if not uid:
        #  ★ 不要導去登入頁 —— 日曆客戶端不會登入，它只會一直拿到 HTML
        #    然後顯示「訂閱成功但沒有東西」。回 403 才看得出是壞的。
        abort(403)

    today = datetime.now(TAIPEI).date()
    lo = (today - timedelta(days=DAYS_BACK)).isoformat()
    hi = (today + timedelta(days=DAYS_AHEAD)).isoformat()

    church, events, personal = [], [], []
    #  ★ 三段各自包 try：其中一張表出問題時，其他兩種照樣要送得出去。
    #    整份失敗的話，他手機上的日曆會**整個變空**，
    #    而那看起來像教會突然什麼活動都沒有了。
    try:
        church = supabase.table('church_events')\
            .select('id, title, event_date, end_date, description')\
            .gte('event_date', lo).lte('event_date', hi)\
            .order('event_date').execute().data or []
    except Exception:
        pass
    try:
        events = supabase.table('events')\
            .select('id, title, event_start, event_end, location')\
            .gte('event_start', lo).lte('event_start', hi)\
            .order('event_start').execute().data or []
    except Exception:
        pass
    try:
        personal = supabase.table('personal_events')\
            .select('id, title, event_date, description')\
            .eq('user_id', uid)\
            .gte('event_date', lo).lte('event_date', hi)\
            .order('event_date').execute().data or []
    except Exception:
        pass

    body = build_ics(church, events, personal)
    return Response(body, mimetype='text/calendar; charset=utf-8', headers={
        'Content-Disposition': 'inline; filename="church.ics"',
        'Cache-Control': 'no-cache',
    })
