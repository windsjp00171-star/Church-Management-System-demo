"""聖經速讀：每天一則，推他**自己的下一格**

使用者：「每天擷取一次現在速讀的範圍推播 點進去 推播進去就會跳到
相對應的內容這樣」

## ★★ 推的是「他的下一格」，不是「日曆上今天是第幾格」

教會發的是**一張沒有日期的紙**，所以系統不可以發明日期。而且對一個
讀到第 100 格的人，推「今天第 254 格」＝ 在講「你落後 154 天」——
那正是 365 天計畫的頭號死因，也是這個專案刻意不做的事。

`bible_plan.next_unread()` 回的是**第一個沒打勾的**（不是最後打勾的
下一格）—— 先讀新約再回頭補的人，用後者會把中間整段跳過去。

## ★★ 一格都還沒打過勾的人**也要推**（使用者否掉了我的規則）

我提議「沒開始讀的就不推」，他說「這個我要否掉 要推」。他是對的：
那條規則會讓**最不知道有這個功能的人，永遠不會被告知有這個功能**，
而在數據上那看起來就是「他不想讀」。

★ 所以文案要分兩種。對還沒開始的人，這則不是**提醒**，是**邀請**。

## 幾個刻意的決定

- **今天已經打勾的人不推**：那是「他今天做完了」的事實，不是猜測
  （對照上面那條被否掉的規則 —— 那條是在猜他不想讀）
- **09:00 起才推**（上界收在全站的安靜時段 21:00）。使用者對**這一則**
  說過：「不要太早發 反正推播發了沒滑掉 就是會在手機通知列提醒他們」
  —— 通知會留著，所以不用搶那一刻。
  ★★ 全站的安靜時段是 **21:00–07:00**（他後來訂正的另一件事），
  這一則刻意比它晚兩小時。兩者**不可以混成一條** —— 混掉的話，
  要嘛速讀七點就吵人，要嘛「明天有課」被壓到九點才講。
  ★ 上界那一條的理由：排程不是「準點響」，是「那之後的第一次 tick」。
  伺服器睡掉半天再醒來時，沒有上界那一則會補在半夜十一點半
- **一人一列，每天覆蓋**（`_prune_old`）。這一則跟其他通知不一樣：
  它**每天一則而且會自我取代**。不清的話一年之後鈴鐺裡是 365 則讀經
  提醒，而**繳費、候補遞補那些真正要緊的會被擠出去**（鈴鐺只顯示
  最近 30 則）。推播那邊靠 `tag` 天生就會蓋掉，站內這邊要自己做。
  ★ 順序是**先寫今天的、再刪舊的** —— 反過來的話寫入失敗時他兩則都沒有
"""
from datetime import datetime, timedelta, timezone

from db import supabase
from routes import bible_plan

TAIPEI_TZ = timezone(timedelta(hours=8))

TABLE = 'notifications'
REF_TYPE = 'reading_day'
TYPE = 'reading'

#  ★ 時段的規則搬到 `routes/quiet_hours`（**唯一一份**）——
#    原本只有這一支有時段窗，而同一支排程裡的另外四種提醒沒有，
#    於是教會行事提醒會在半夜 00:07 推到 119 支手機。
#    兩份規則、只有一份生效，正是這個專案最常見的那種壞法。
from routes import quiet_hours

#  ★★ 速讀這一則**自己的**起點，比全站的安靜時段（07:00）晚兩小時。
#
#    使用者對**這一則**講過：「不要太早發 反正推播發了沒滑掉 就是會在
#    手機通知列提醒他們」。全站的安靜時段是他後來訂正的另一件事
#    （21:00–07:00），兩者不可以混成一條 —— 混掉的話，
#    要嘛速讀七點就吵人，要嘛「明天有課」被壓到九點才講。
READING_START_HOUR = 9


def in_window(now=None):
    """這一則可以推了嗎（09:00 起，收在全站的安靜時段）。"""
    return quiet_hours.in_window(now, start=READING_START_HOUR)


def _now():
    return datetime.now(TAIPEI_TZ)


def _all_progress(sb):
    """`{user_id: {打過勾的 day_no}}`。

    ★ 要分頁：PostgREST 一次最多回 1000 筆，而這張表會長到
      119 人 × 365 格。不分頁的話，**排在後面的人會安靜地被當成
      「一格都沒讀」**，然後每天收到「從第 1 格開始」的邀請。
    """
    key = bible_plan.active_plan_key()
    out, start, page = {}, 0, 1000
    while True:
        rows = sb.table(bible_plan.TABLE).select('user_id, day_no')\
            .eq('plan_key', key).range(start, start + page - 1).execute().data or []
        for r in rows:
            if r.get('user_id') is not None and r.get('day_no') is not None:
                out.setdefault(r['user_id'], set()).add(r['day_no'])
        if len(rows) < page:
            return out
        start += page


def _read_today(sb, today):
    """今天已經打過勾的人 —— 這幾個不推。"""
    try:
        rows = sb.table(bible_plan.TABLE).select('user_id')\
            .eq('plan_key', bible_plan.active_plan_key())\
            .eq('read_on', today).execute().data or []
    except Exception:                                  # noqa: BLE001
        #  ★ 查不到就**當成大家今天都讀過了**（誰都不推）。
        #    反過來做的話，資料庫抖一下就是全教會被多吵一次，
        #    包括今天明明已經讀完的人。
        return None
    return {r['user_id'] for r in rows if r.get('user_id')}


def _member_ids(sb):
    rows = sb.table('users').select('id')\
        .eq('member_type', 'member').execute().data or []
    return [u['id'] for u in rows if u.get('id')]


def passage(day):
    """這一則要告訴他的就是這個：**讀哪裡**。

    ★★ 不講「第 N 格」。使用者的原話：
      「不用說第幾格 沒人看到的 說經節範圍就好
      格是你的理解 他們理解都是經文範圍」。

      他是對的 —— 「格」是我從那張紙上 365 個方格學來的詞，
      而**推播裡根本沒有那張表**。手機上跳出一句「這是第 25 格」，
      沒有任何參照物可以讓他知道那是什麼意思。

    ★ 用**全名**（出埃及記）不用簡稱：標題已經是簡稱了（通知列寬度
      有限），內文這一行正好拿來把「出」是哪一卷講清楚。
    """
    book = day.get('book') or ''
    lo = day.get('chapter_start')
    hi = day.get('chapter_end') or lo
    if not book or not lo:
        return day.get('label') or ''
    if hi and hi != lo:
        return f'{book} {lo}–{hi} 章'
    return f'{book} {lo} 章'


def _row_for(user_id, done, today):
    """這個人今天該收到的那一則。全部讀完了回 None。"""
    nxt = bible_plan.next_unread(done)
    if not nxt:
        return None                      # 365 格都讀完了 —— 不要再吵他
    label = nxt.get('label') or passage(nxt)
    if done:
        title = f'📖 接下來：{label}'
        body = passage(nxt)
    else:
        #  ★ 對還沒開始的人，這一則不是提醒，是**邀請** ——
        #    他很可能根本不知道系統裡有這個計畫。
        title = f'📖 一年讀完一遍聖經，從 {label} 開始'
        body = f'{passage(nxt)}。讀完點一下就好。'
    return {
        'user_id': user_id,
        'title': title,
        'body': body,
        'type': TYPE,
        #  ★★ 連到**我們自己的**那一格（`/reading/<第幾格>`），
        #    不是 `bible_plan.read_url()` —— 那一支回的是**外部**聖經
        #    平台的網址，點下去會把人直接丟出系統：他看不到「讀完了」、
        #    也沒有朗讀，而那兩件正是他點進來要做的事。
        #    （站內通知的 `link` 也吃不下外部網址。）
        'link': f'/reading/{nxt["day_no"]}',
        'ref_type': REF_TYPE,
        #  ★ 一天一則的去重鍵就是日期本身。`notifications.ref_id` 是
        #    text 欄位（查過 information_schema），所以放日期不用改 schema。
        'ref_id': today,
    }


def _prune_old(sb, today):
    """把**昨天以前**的讀經提醒清掉，一人只留最新那一則。

    ★ 保留 `ref_id == today` 那一列 —— 它是今天的去重鍵，
      刪掉的話同一天會重複發。
    """
    try:
        sb.table(TABLE).delete()\
            .eq('ref_type', REF_TYPE).neq('ref_id', today).execute()
    except Exception:                                  # noqa: BLE001
        pass          # 清不掉只是鈴鐺裡多幾則，不值得讓整支失敗


def run(now=None, sb=None):
    """排程的進入點。回一份**照實**的結果。"""
    now = now or _now()
    sb = sb or supabase
    if not in_window(now):
        return {'skipped': f'不在 {quiet_hours.label(start=READING_START_HOUR)} 之間'}

    today = now.date().isoformat()
    try:
        members = _member_ids(sb)
    except Exception as e:                             # noqa: BLE001
        return {'error': f'撈不到會友名單（{type(e).__name__}）'}
    if not members:
        return {'members': 0, 'sent': 0}

    read_today = _read_today(sb, today)
    if read_today is None:
        return {'skipped': '查不到今天的讀經進度，這一輪不推'}

    try:
        progress = _all_progress(sb)
    except Exception as e:                             # noqa: BLE001
        return {'error': f'撈不到讀經進度（{type(e).__name__}）'}

    rows = []
    for uid in members:
        if uid in read_today:
            continue                     # 今天已經讀完了，不要再吵他
        row = _row_for(uid, progress.get(uid, set()), today)
        if row:
            rows.append(row)
    if not rows:
        return {'members': len(members), 'sent': 0}

    #  ★ 去重走 `reminders.already_sent`（同一份實作）—— 它刻意
    #    **不看 `is_read`**，理由見那個模組（讀過就被重發的那個 bug）。
    from routes.reminders import already_sent
    sent_keys = already_sent(rows, sb=sb)
    fresh = [r for r in rows
             if (r['user_id'], r['type'], r['ref_type'], r['ref_id']) not in sent_keys]

    sent = 0
    if fresh:
        from routes.notifications import batch_notify_rows
        sent = batch_notify_rows(fresh)
    #  ★ 先寫今天的、再刪舊的
    _prune_old(sb, today)
    return {'members': len(members), 'candidates': len(rows), 'sent': sent}
