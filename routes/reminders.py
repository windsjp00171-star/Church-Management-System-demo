"""提醒的去重（只搬了這一塊）。

成熟版的 `reminders.py` 還有「活動快到了／課程快到了」等排程提醒；這個 repo 目前只用得到
「這個人這件事今天發過沒有」—— 聖經速讀每天一則靠它。
shortcut: 其餘的排程提醒沒搬，要搬時整支換成成熟版，`already_sent` 的行為不變。

★★ 去重**不看 `is_read`**：原本只撈未讀，他一讀完去重就失效、下一次又發一次
   （資料庫裡查得到同一件事發 9 次）。搬到排程之後同一個 bug 會變成每 15 分鐘一則推播。
"""
from db import supabase


def already_sent(rows, sb=None):
    """這些 (user, type, ref_type, ref_id) 裡，哪些已經發過了。

    ★★ **不看 `is_read`。** 原本那支只撈未讀，於是他一讀完
      去重就失效、下一次又發一次 —— 資料庫裡查得到同一件事發 9 次。
      （理由寫在模組開頭。）

    ★ 查詢用 `ref_id` 收斂：候選的 ref_id 很少（窗內的活動／行事），
      所以這是**一次**查詢，不跟著人數長。
    """
    sb = sb or supabase
    ref_ids = list({r.get('ref_id') for r in rows if r.get('ref_id')})
    if not ref_ids:
        return set()
    try:
        sent = sb.table('notifications')\
            .select('user_id, type, ref_type, ref_id')\
            .in_('ref_id', ref_ids).execute().data or []
    except Exception:                              # noqa: BLE001
        #  ★ 查不到就**當成全部發過**（什麼都不發）。
        #    反過來做的話，資料庫抖一下就是全教會被重發一輪。
        return {_key(r) for r in rows}
    return {_key(r) for r in sent}


def _key(row):
    return (row.get('user_id'), row.get('type'),
            row.get('ref_type'), row.get('ref_id'))
