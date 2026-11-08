"""聚會人數回報 ↔ 聚會點名：**以點名為準**，回報頁的人數由點名那場帶出來，不用再填第二次。

為什麼：同一場聚會原本在兩個系統各記一次人數（點名 `rc_*`、人數回報 `sunday_reports` 等），
同工要填兩遍，而且兩邊會對不起來。使用者決定（2026-11-08）：以點名為準。

## 規則（每一條都是為了不讓畫面說假話）

- **只在「點名那邊真的有數字」時才覆蓋**；沒有就維持原本的手填 —— 所以沒設連結、或點名還沒做時，回報頁照舊能用。
- **人數空白一律不覆蓋、不當 0**（跟點名一貫的規矩）：人數模式的場次 `headcount` 是 NULL＝還沒填；
  逐人模式的場次一筆紀錄都沒有＝還沒開始點，不是「0 人」。
- **成人主日有幾堂，就要有幾場點名**（依「聚會設定」的堂數，依開始時間排序：最早的是第一堂）。
  少一場就整個不覆蓋 —— 只蓋一堂的話合計會是一個假數字。
- **逐人模式只算「到場」的**：打勾「到」與「遲到」都算（人確實在場）；請假、缺席不算。
  這是**人數**，不是出席率 —— 出席率的算法由教會自己決定（`rc_rate_rules`），跟這裡無關。
- 讀不到點名資料（資料庫抖一下）一律當成「沒有連結」，退回手填，**不可以讓回報頁打不開**。
- 這一支**只讀** `rc_*`，不寫；也**不碰 `users`**（點名模組與帳號脫鉤，有測試守衛）。

設定在「聚會設定」頁：每個聚會選一個點名類型（`settings` 的 `meeting.<key>` 的 `rc_type_id`）。
"""
import logging
from datetime import date

from db import supabase
from routes import tw_time

#  回報表裡「人數」的欄位。成人主日有兩堂，其餘一個。
FIELDS = {
    'adult_sunday': ('first_service_count', 'second_service_count'),
    'children_sunday': ('attendance_count',),
    'prayer': ('attendance_count',),
    'morning_prayer': ('attendance_count',),
}

#  逐人模式裡算「人數」的狀態（人在場）。請假、缺席不算。
PRESENT_STATUSES = ('present', 'late')

log = logging.getLogger(__name__)


def _services_needed(key, cfg):
    if key != 'adult_sunday':
        return 1
    try:
        return max(int((cfg or {}).get('service_count', 2)), 1)
    except (TypeError, ValueError):
        return 2


def _count_of(sess, mode, sb):
    """這一場的人數；點名那邊還沒有數字回 None（不是 0）。"""
    if mode == 'headcount':
        return sess.get('headcount')                         # NULL＝還沒填
    res = sb.table('rc_records').select('id', count='exact')\
        .eq('session_id', sess['id']).in_('status', list(PRESENT_STATUSES)).execute()
    total = res.count
    if not total:
        #  一個「到」都沒有：可能是還沒開始點，也可能真的沒人 —— 分不出來，所以不覆蓋
        any_row = sb.table('rc_records').select('id').eq('session_id', sess['id']).limit(1).execute().data
        return 0 if any_row else None
    return total


def linked_counts(key, date_str, cfg, sb=None):
    """這個聚會、這一天，點名那邊的人數 `[第一堂, (第二堂)]`；沒有連結或還不完整回 None。"""
    type_id = (cfg or {}).get('rc_type_id')
    if not type_id or key not in FIELDS:
        return None
    sb = sb or supabase
    try:
        lo, hi = tw_time.day_bounds_utc(date.fromisoformat(date_str))
        sessions = sb.table('rc_sessions').select('id, starts_at, headcount')\
            .eq('type_id', type_id).gte('starts_at', lo).lt('starts_at', hi)\
            .order('starts_at').execute().data or []
        need = _services_needed(key, cfg)
        if len(sessions) < need:
            return None
        mtype = sb.table('rc_meeting_types').select('record_mode')\
            .eq('id', type_id).limit(1).execute().data
        if not mtype:
            return None
        counts = [_count_of(s, mtype[0].get('record_mode'), sb) for s in sessions[:need]]
    except Exception:                                        # noqa: BLE001
        log.warning('讀點名人數失敗，退回手填', exc_info=True)
        return None
    return None if any(c is None for c in counts) else counts


def overlay(key, date_str, row, cfg=None, sb=None):
    """把點名的人數蓋到回報那一列上；沒有連結就原樣回傳。

    蓋過的列多一個 `_linked`（各堂人數），畫面據此改成唯讀、伺服器據此擋手填。
    """
    if cfg is None:
        try:
            from routes.cell_report import _get_meeting_settings
            cfg = _get_meeting_settings().get(key, {})
        except Exception:                                    # noqa: BLE001
            return row
    counts = linked_counts(key, date_str, cfg, sb=sb)
    if counts is None:
        return row
    out = dict(row or {'date': date_str})
    for field, n in zip(FIELDS[key], counts):
        out[field] = n
    if len(counts) < len(FIELDS[key]):
        out[FIELDS[key][1]] = 0                              # 設定只有一堂：第二堂不存在
    out['_linked'] = counts
    return out
