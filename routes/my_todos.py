"""前台「我的提醒」—— 讓會友一進首頁就知道「接下來有什麼」。

這裡只做**提醒**，不做待辦管理。規則只有四條：

1. 每一則都必須綁一個時間。沒有到期時間的事（缺勤快超標、資料沒補完）不放 ——
   那種東西關不掉，會一直卡在畫面上，最後整塊被當成背景無視。
2. 時間過了就自動消失，不需要任何人去關掉它。
3. 只提醒「需要被提醒的事」。固定行程（主日崇拜、每週小組）不提醒 ——
   沒有人會忘記禮拜天要守主日，唸那個只會稀釋真正該注意的事。
   判斷方式是 remind_days 由排行事的人明確設定，沒設就是不提醒。
4. 最近的排最前面，並且有數量上限。不分急迫層級 —— 教會的事本來就少有
   真正緊急的，全部標紅等於沒有標；而「什麼算緊急」也沒有人維護得起來。

每個來源函式簽名 fn(user_id, now) -> list[dict]：
    icon / title / detail / link / action
    when  這則提醒對應的時間（datetime），過了那一天就自動不再出現
"""
from datetime import datetime, timedelta, timezone

from db import supabase

TAIPEI_TZ = timezone(timedelta(hours=8))

# 查詢先撈這個範圍，再由每一筆自己的 remind_days 決定要不要出現。
# 跟站內通知共用同一個值，兩邊的提醒時機才會一致。
from routes.calendar import MAX_REMIND_DAYS

# 畫面上最多顯示幾則。
# 以前壓到 5 則是因為往下疊會把首頁推很長；現在改成輪播、高度固定成一張卡，
# 可以多放一些，比較不會有事情被無聲丟掉。再多就是點點太多、沒人滑得完。
MAX_ITEMS = 8


def _day_str(now, offset=0):
    return (now + timedelta(days=offset)).date().isoformat()


def _to_taipei(s):
    """UTC ISO 字串 → 台灣時間 datetime

    ★ 實作在 `routes/tw_time.py`（唯一來源）。
    ★ 原本這一支對沒有時區的字串是 `.astimezone(TAIPEI_TZ)` ——
      那會用**伺服器的系統時區**去解讀，在 Render（UTC）上剛好對，
      在台灣的機器上跑就差 8 小時。改成明講 UTC。
    """
    from routes.tw_time import to_taipei
    return to_taipei(s, naive_is='utc')


WEEKDAY_ZH = '一二三四五六日'


def _when_label(dt, now):
    """把日期講成人聽得懂的話：今天 / 明天 / 還有 3 天"""
    days = (dt.date() - now.date()).days
    if days <= 0:
        return '今天'
    if days == 1:
        return '明天'
    return f'還有 {days} 天'


def date_stamp(dt):
    """8/1（六）—— 「還有 3 天」很模糊，人得自己去數哪一天，所以一定要有具體日期。

    放在補充說明那行而不是標題：標題已經有「還有幾天」，
    再塞日期會在手機上折行，反而更難讀。
    """
    return f'{dt.month}/{dt.day}（{WEEKDAY_ZH[dt.weekday()]}）'


def _detail(dt, text=''):
    """補充說明一律以具體日期開頭"""
    stamp = date_stamp(dt)
    return f'{stamp} · {text}' if text else stamp


def remind_days_of(row):
    """這筆行事要提前幾天提醒；0 或沒設 = 不提醒。

    刻意是「明確設定才提醒」而不是給預設值：行事曆上多數是主日崇拜、
    每週小組這種固定行程，給了預設值就變成每一則都在唸，
    真正需要記得的（洗禮、特會、報名截止）反而被稀釋掉。
    """
    try:
        raw = row.get('remind_days')
        return max(int(raw), 0) if raw not in (None, '') else 0
    except (TypeError, ValueError):
        return 0


# ── 各項提醒 ──────────────────────────────────────────

def _my_upcoming_sessions(user_id, now):
    """今明兩天我有課 —— 忘記就是缺一堂，缺太多不能完訓"""
    enrolled = supabase.table('course_enrollments')\
        .select('course_id').eq('user_id', user_id)\
        .in_('status', ['enrolled', 'completed']).execute().data or []
    if not enrolled:
        return []
    course_ids = list({e['course_id'] for e in enrolled})

    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=2)
    sessions = supabase.table('course_sessions')\
        .select('id, course_id, session_number, scheduled_at')\
        .in_('course_id', course_ids)\
        .gte('scheduled_at', start.astimezone(timezone.utc).isoformat())\
        .lt('scheduled_at', end.astimezone(timezone.utc).isoformat())\
        .order('scheduled_at').execute().data or []
    if not sessions:
        return []

    courses = supabase.table('courses').select('id, title')\
        .in_('id', course_ids).execute().data or []
    title_map = {c['id']: c['title'] for c in courses}

    out = []
    for s in sessions:
        dt = _to_taipei(s.get('scheduled_at'))
        if not dt:
            continue
        out.append({
            'icon': '📚',
            'title': f"{_when_label(dt, now)} {dt.strftime('%H:%M')}　"
                     f"{title_map.get(s['course_id'], '課程')} 第 {s['session_number']} 堂",
            'detail': _detail(dt, '記得簽到，出席才算數'),
            'link': f"/courses/{s['course_id']}",
            'action': '課程資訊',
            'when': dt,
        })
    return out


def _my_upcoming_events(user_id, now):
    """我報名的活動快到了 —— 報名了才會收到，不是全教會廣播

    shortcut: 只看 `registrations.user_id`（這個 repo 沒有「代報」＝沒有 participant_user_id）；
    哪天有代報，要把「哪些報名算我的」收成一份實作（成熟版 `routes/participation.py`）。
    """
    #  ★★ 取消的、候補中的不算 —— 他取消了還跟他說「明天的活動」，他會以為自己沒取消成功；
    #    候補中的位子還不是他的。（`walk_in` 是現場補登，人確實會來，算。）
    regs = supabase.table('registrations').select('event_id')\
        .eq('user_id', user_id).in_('status', ['registered', 'walk_in']).execute().data or []
    if not regs:
        return []
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=3)
    events = supabase.table('events')\
        .select('id, title, event_start, location')\
        .in_('id', [r['event_id'] for r in regs])\
        .gte('event_start', start.astimezone(timezone.utc).isoformat())\
        .lt('event_start', end.astimezone(timezone.utc).isoformat())\
        .order('event_start').execute().data or []

    out = []
    for e in events:
        dt = _to_taipei(e.get('event_start'))
        if not dt:
            continue
        out.append({
            'icon': '🎪',
            'title': f"{_when_label(dt, now)} {dt.strftime('%H:%M')}　{e['title']}",
            'detail': _detail(dt, e.get('location') or '您已報名'),
            'link': f"/event/{e['id']}",
            'action': '查看活動',
            'when': dt,
        })
    return out


def _my_calendar_soon(user_id, now):
    """行事曆上「有設提醒」的事：教會行事（大家的）＋ 個人行程（自己的）

    沒設 remind_days 的一律不提醒 —— 主日崇拜這種固定行程排在行事曆上
    是為了讓人查得到，不是為了每週被通知一次。
    """
    today = _day_str(now)
    horizon = _day_str(now, MAX_REMIND_DAYS)
    out = []

    church = supabase.table('church_events')\
        .select('id, title, event_date, description, remind_days')\
        .gte('event_date', today).lte('event_date', horizon)\
        .order('event_date').execute().data or []
    personal = supabase.table('personal_events')\
        .select('id, title, event_date, description, remind_days')\
        .eq('user_id', user_id)\
        .gte('event_date', today).lte('event_date', horizon)\
        .order('event_date').execute().data or []

    for rows, icon, fallback in ((church, '⛪', '教會行事'),
                                 (personal, '🗓', '您的個人行程')):
        for e in rows:
            days_ahead = remind_days_of(e)
            if not days_ahead:
                continue                            # 沒設提醒 = 不用提醒
            try:
                d = datetime.fromisoformat(e['event_date']).date()
            except Exception:
                continue
            days = (d - now.date()).days
            if days < 0 or days > days_ahead:
                continue
            when = '今天' if days == 0 else ('明天' if days == 1 else f'還有 {days} 天')
            out.append({
                'icon': icon,
                'title': f"{when}　{e['title']}",
                'detail': _detail(datetime.combine(d, datetime.min.time()),
                                  (e.get('description') or '')[:60] or fallback),
                # 帶上日期：只跳到「行事曆」而不指到哪一天，等於還要自己再找一次
                'link': f'/calendar?date={d.isoformat()}',
                'action': '看行事曆',
                # 全天事項當成當天 00:00，會排在同一天有時間的事項之前
                'when': datetime.combine(d, datetime.min.time(), tzinfo=TAIPEI_TZ),
            })
    return out


#  ── ★★ 這裡**刻意沒有**「還沒繳費」────────────────────
#
#  使用者（2026-09-30）：**「費用催繳不要做 / 這個在教會內部很敏感」**。
#
#  原本有兩支（`_my_unpaid_events`、`_my_unpaid_courses`），已經整支移除。
#  理由不是「做不出來」也不是「沒人要」—— 是**教會不用系統去點名誰還沒繳錢**。
#
#  ★★ 這一條一定要留在這裡，因為它看起來**非常像一個 bug**：
#    正式站現在就有 80 筆未繳費的報名（秋之旅），而系統一個字都不提。
#    我自己在 2026-09-29 就把它當成 bug 修過一次（PR #432），
#    然後使用者說了上面那句話。下一次看到「80 人未繳而沒有提醒」時，
#    **那是刻意的，不要再修一次**。
#
#  ★ 錢的事留在**同工那一側**（都還在，不受這條影響）：
#    小組收款單、會計總覽（`routes/collection.py`）、後台名單的已付款勾選。
#    差別是「同工去收」和「系統去催會友」—— 前者是他們本來就在做的事。
#  ★ 會友**自己來看**的地方也還在（活動詳情頁、我的記錄）：
#    他自己點進來查不是催繳。
#
#  `tests/test_no_payment_chasing.py` 在守這件事。


# ── 註冊表：新增提醒就在這裡加一行 ──────────────────────────
MY_TODO_SOURCES = [
    _my_upcoming_sessions,
    _my_upcoming_events,
    _my_calendar_soon,
    #  ★ 沒有「還沒繳費」—— 見上面那一段（使用者定的，不是漏掉的）
]


def collect_my_todos(user_id, now=None, limit=MAX_ITEMS):
    """這位會友接下來要注意的事，最近的排最前面。

    只留「今天以後」的：時間過了就自動消失，不需要任何人去關掉它。
    以「那一天結束」為界而不是「那個時刻」—— 19:00 的課不該在 19:01
    就從提醒裡消失，人可能還在路上。

    首頁是會友看的，壞了不該讓他們看到錯誤訊息（他們也無從處理），
    所以單一來源出錯就跳過那一項，其餘照常顯示。
    """
    if not user_id:
        return []
    now = now or datetime.now(TAIPEI_TZ)
    items = []
    for fn in MY_TODO_SOURCES:
        try:
            items.extend(fn(user_id, now) or [])
        except Exception:
            continue

    today = now.date()
    items = [t for t in items if t.get('when') and t['when'].date() >= today]
    items.sort(key=lambda t: t['when'])

    # when 是 datetime，不能直接 jsonify，換成顯示用字串
    for t in items:
        t['when'] = t['when'].strftime('%Y-%m-%d %H:%M')
    return items[:limit]
