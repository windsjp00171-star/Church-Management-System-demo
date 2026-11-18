"""聖經速讀每天一則

使用者：「每天擷取一次現在速讀的範圍推播 點進去 推播進去就會跳到
相對應的內容這樣」

## ★★ 推的是「他的下一格」，不是「今天是第幾格」

教會發的是**一張沒有日期的紙**，所以系統不可以發明日期。而且對讀到
第 100 格的人推「今天第 254 格」＝ 在講「你落後 154 天」—— 那正是
365 天計畫的頭號死因。（「不可以罵人」那條守衛在 `test_bible_plan.py`，
這個模組已經加進它的清單。）

## ★★ 一格都沒打過勾的人也要推 —— 使用者否掉了我的規則

我提議「沒開始讀的就不推」，他說「這個我要否掉 要推」。
他是對的：那條會讓**最不知道有這個功能的人永遠不會被告知它的存在**，
而在數據上那看起來就是「他不想讀」。
"""
import sys
import types

# routes.reading_nudge 載入時會 import db；沒有真的環境變數時換成假的（測試自己 patch supabase）
if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from routes import reading_nudge as nudge

TW = timezone(timedelta(hours=8))
AT_9AM = datetime(2026, 9, 12, 9, 30, tzinfo=TW)
TODAY = '2026-09-12'


def _sb(members=('u1',), progress=(), read_today=(), notifications=(),
        on_delete=None):
    """替身：progress 是 [(user_id, day_no), ...]。

    `on_delete`：有 delete 時，把那條鏈上的每一個過濾條件交給它 ——
    ★ 「有沒有真的刪」光看「有沒有碰這張表」是問不出來的。
    """
    def table(name):
        c = MagicMock()
        state = {'read_on': None, 'deleting': False, 'chain': []}

        def eq(col, val):
            if col == 'read_on':
                state['read_on'] = val
            if state['deleting']:
                state['chain'].append(('eq', col, val))
            return c

        def neq(col, val):
            if state['deleting']:
                state['chain'].append(('neq', col, val))
            return c

        def delete():
            state['deleting'] = True
            return c
        for m in ('select', 'in_', 'gt', 'gte', 'lte', 'lt', 'order', 'range'):
            getattr(c, m).return_value = c
        c.eq.side_effect = eq
        c.neq.side_effect = neq
        c.delete.side_effect = delete

        def execute():
            r = MagicMock()
            if state['deleting']:
                if on_delete:
                    on_delete(list(state['chain']))
                state['deleting'], state['chain'] = False, []
                r.data = []
                return r
            if name == 'users':
                r.data = [{'id': m} for m in members]
            elif name == 'bible_reading_progress':
                if state['read_on'] is not None:
                    r.data = [{'user_id': u} for u in read_today]
                else:
                    r.data = [{'user_id': u, 'day_no': d} for u, d in progress]
            elif name == 'notifications':
                r.data = list(notifications)
            else:
                r.data = []
            return r
        c.execute.side_effect = execute
        return c
    sb = MagicMock()
    sb.table.side_effect = table
    return sb


def _run(sb, now=AT_9AM):
    with patch('routes.notifications.batch_notify_rows', side_effect=len) as send:
        out = nudge.run(now=now, sb=sb)
    rows = send.call_args[0][0] if send.call_args else []
    return out, rows


# ══ 一、時段 ═════════════════════════════════════════════

@pytest.mark.parametrize('hour,ok', [
    (6, False), (8, False),            # ★ 速讀自己的下限是 09:00
                                       #   （全站的安靜時段是 07:00 起，
                                       #    這一則刻意晚兩小時 —— 他對
                                       #    **這一則**說過「不要太早發」）
    (9, True), (14, True), (20, True),
    (21, False), (23, False),          # ★ 半夜補一則「今天的進度」沒有用
])
def test_only_between_nine_and_nine(hour, ok):
    """★★ 使用者：「不要太早發 反正推播發了沒滑掉 就是會在手機
    通知列提醒他們」—— 通知會留著，所以不用搶那一刻。

    ★ 上界是順著同一個邏輯來的：排程不是「9 點整響」，是
    「9 點之後的**第一次 tick**」。伺服器睡掉半天再醒來時，
    沒有上界那一則會補在半夜十一點半。
    """
    assert nudge.in_window(datetime(2026, 9, 12, hour, 0, tzinfo=TW)) is ok


def test_outside_the_window_nothing_is_sent():
    out, rows = _run(_sb(), now=datetime(2026, 9, 12, 3, 0, tzinfo=TW))
    assert 'skipped' in out and not rows


# ══ 二、推的是他自己的下一格 ═════════════════════════════

def test_it_pushes_the_first_gap_not_the_calendar_day():
    """★★ 「第一個沒打勾的」不是「最後打勾的下一格」。

    先讀新約再回頭補的人，用後者會把中間整段跳過去，
    而他的進度條看起來一路往前。
    """
    #  讀了 1、2、4 —— 下一格是 3，不是 5
    _, rows = _run(_sb(progress=[('u1', 1), ('u1', 2), ('u1', 4)]))
    assert len(rows) == 1
    assert rows[0]['link'].endswith('/3'), rows[0]['link']


def test_the_link_goes_to_that_cell():
    """★ 使用者要的就是這個：「點進去 推播進去就會跳到相對應的內容」。"""
    _, rows = _run(_sb(progress=[('u1', 1)]))
    assert rows[0]['link'] == '/reading/2'
    assert rows[0]['type'] == 'reading'


def test_the_type_is_one_that_actually_pushes():
    """★ `type` 沒登記在 `PUSH_TYPES` 的話，這一整支只會寫站內通知 ——
    而那正好是它存在的理由（不用回來看）被拿掉。"""
    from routes.push import should_push
    assert should_push(nudge.TYPE) is True


# ══ 三、誰收得到 ═════════════════════════════════════════

def test_someone_who_never_started_still_gets_it():
    """★★ 使用者否掉了我「沒開始就不推」那條規則，而他是對的 ——
    那條會讓**最不知道有這個功能的人永遠不會被告知它的存在**。"""
    _, rows = _run(_sb(members=('newbie',), progress=[]))
    assert len(rows) == 1
    assert rows[0]['link'] == '/reading/1'


def test_the_invitation_reads_differently_from_the_reminder():
    """★ 對還沒開始的人，這一則不是提醒，是**邀請** ——
    同一句話寫不好這兩件事。"""
    _, newbie = _run(_sb(members=('newbie',), progress=[]))
    _, ongoing = _run(_sb(members=('u1',), progress=[('u1', 1), ('u1', 2)]))
    #  ★★ 只斷言「兩個 title 不相等」是**假守衛**：兩個人的格子本來就不同，
    #    `label` 不一樣就讓 title 不一樣了 —— 文案改成同一句照樣通過
    #    （mutation 當場抓到）。要對著**各自講了什麼**問。
    assert '接下來' in ongoing[0]['title'], ongoing[0]['title']
    assert '接下來' not in newbie[0]['title'], \
        f'還沒開始的人收到的是提醒不是邀請：{newbie[0]["title"]}'
    assert '開始' in newbie[0]['title']
    #  ★ 內文的差別是**怎麼做**：還沒開始的人需要那一句（他不知道
    #    「讀完點一下」是什麼意思），已經在讀的人每天看同一句話只是雜訊。
    assert '讀完點一下' in newbie[0]['body'], newbie[0]['body']
    assert '讀完點一下' not in ongoing[0]['body'], ongoing[0]['body']


def test_someone_who_already_read_today_is_left_alone():
    """★ 這一條跟被否掉那條不一樣：這是「他今天做完了」的**事實**，
    不是在猜他想不想讀。

    不擋的話，最認真的那個人每天被提醒一件他已經做完的事。
    """
    out, rows = _run(_sb(progress=[('u1', 1)], read_today=('u1',)))
    assert rows == [] and out['sent'] == 0


def test_someone_who_finished_all_365_is_left_alone():
    _, rows = _run(_sb(progress=[('u1', d) for d in range(1, 366)]))
    assert rows == []


def test_each_person_gets_their_own_cell():
    """★ 兩個人進度不同，收到的就要不同 —— 發同一則的話，
    那就變成「今天是第幾格」了。"""
    _, rows = _run(_sb(members=('a', 'b'),
                       progress=[('a', 1), ('a', 2), ('b', 1)]))
    by_user = {r['user_id']: r['link'] for r in rows}
    assert by_user == {'a': '/reading/3', 'b': '/reading/2'}


# ══ 四、一天一則 ═════════════════════════════════════════

def test_it_does_not_send_twice_in_one_day():
    """★ 排程每 15 分鐘轉一次 —— 沒有去重的話一天 48 則。"""
    sent = []

    def run_once():
        sb = _sb(progress=[('u1', 1)], notifications=list(sent))
        with patch('routes.notifications.batch_notify_rows',
                   side_effect=lambda rows: sent.extend(rows) or len(rows)):
            return nudge.run(now=AT_9AM, sb=sb)

    assert run_once()['sent'] == 1
    assert run_once()['sent'] == 0, '同一天發了第二則'


def test_yesterdays_nudge_is_cleared_but_todays_is_kept():
    """★★ 這一則跟其他通知不一樣：它**每天一則而且會自我取代**。

    不清的話一年之後鈴鐺裡是 365 則讀經提醒，而**繳費、候補遞補
    那些真正要緊的會被擠出去**（鈴鐺只顯示最近 30 則）。

    ★ 但**今天那一列要留著** —— 它是今天的去重鍵，刪掉的話
      同一天會重複發。
    """
    #  ★★ 「有碰過 notifications 這張表」是**假守衛**：去重那一步
    #    （`already_sent`）本來就會查它，所以把 `_prune_old` 整個拿掉
    #    照樣通過（mutation 當場抓到）。要問的是**有沒有真的 delete**。
    deleted = []
    sb = _sb(progress=[('u1', 1)], on_delete=deleted.append)
    _run(sb)
    assert deleted, '舊的讀經提醒沒有被清掉 —— 一年後鈴鐺裡會有 365 則'
    #  ★ 而且一定要帶 `neq('ref_id', 今天)`，不然連今天的去重鍵一起刪掉
    assert ('neq', 'ref_id', TODAY) in deleted[0], \
        f'清舊的時候沒有保留今天那一列：{deleted[0]}'


# ══ 五、壞掉的時候寧可不推 ═══════════════════════════════

def test_a_progress_hiccup_sends_nothing_rather_than_everything():
    """★★ 查不到「今天誰讀過」時要**當成大家都讀過了**。

    反過來做的話，資料庫抖一下就是全教會被多吵一次 ——
    包括今天明明已經讀完的人。
    """
    sb = _sb(progress=[('u1', 1)])

    def table(name):
        c = MagicMock()
        for m in ('select', 'eq', 'neq', 'in_', 'order', 'range', 'delete'):
            getattr(c, m).return_value = c
        if name == 'users':
            c.execute.return_value.data = [{'id': 'u1'}]
        else:
            c.execute.side_effect = RuntimeError('db down')
        return c
    sb.table.side_effect = table
    out, rows = _run(sb)
    assert 'skipped' in out and rows == []


def test_progress_is_paged():
    """★★ PostgREST 一次最多回 1000 筆，而這張表會長到 119 × 365。

    不分頁的話，**排在後面的人會安靜地被當成「一格都沒讀」**，
    然後每天收到「從第 1 格開始」的邀請 —— 而他明明讀到一半。
    """
    import inspect
    src = inspect.getsource(nudge._all_progress)
    assert '.range(' in src, '沒有分頁'
    assert 'while True' in src


# ══ 六、排程真的接上了 ═══════════════════════════════════

def test_the_scheduler_runs_it():
    from routes import tasks
    assert 'reading_nudge' in dict(tasks.JOBS)


def test_the_job_calls_run():
    from routes import tasks
    with patch('routes.reading_nudge.run', return_value={'sent': 1}) as r:
        assert dict(tasks.JOBS)['reading_nudge']() == {'sent': 1}
    r.assert_called_once()


# ══ 六、講經文範圍，不講「第幾格」 ═══════════════════════
#
#  使用者的原話：「不用說第幾格 沒人看到的 說經節範圍就好
#  格是你的理解 他們理解都是經文範圍」。
#
#  ★★ 他是對的：「格」是我從那張紙上 365 個方格學來的詞，
#    而**推播裡根本沒有那張表**。手機上跳出「這是第 25 格」，
#    沒有任何參照物可以讓他知道那是什麼意思。

def test_the_notification_never_says_which_cell():
    """★★ 這一條問的是**送出去的字**，不是原始碼有沒有那個字 ——
    註解裡本來就會寫到「格」（在解釋為什麼不用它）。"""
    _, ongoing = _run(_sb(members=('u1',), progress=[('u1', 1), ('u1', 2)]))
    _, newbie = _run(_sb(members=('newbie',), progress=[]))
    for row in (ongoing[0], newbie[0]):
        text = row['title'] + ' ' + row['body']
        assert '格' not in text, f'通知裡還在講「格」：{text}'


def test_the_body_says_where_to_read():
    """★ 拿掉「第幾格」之後不可以變成空的 —— 內文要回答
    「讀哪裡」，而且用**全名**（標題是簡稱，通知列寬度有限）。"""
    _, rows = _run(_sb(members=('u1',), progress=[('u1', 1)]))
    body = rows[0]['body']
    assert '章' in body, body
    #  第 2 格是「創 5-8」，內文要把「創」講成「創世記」
    assert '創世記' in body, body


def test_a_single_chapter_reads_naturally():
    """★ 一格只有一章時不要寫成「詩篇 119–119 章」。"""
    assert nudge.passage({'book': '詩篇', 'chapter_start': 119,
                          'chapter_end': 119}) == '詩篇 119 章'


def test_a_broken_row_falls_back_to_the_label():
    """★ 資料缺書名時退回原本的標籤，**不要吐出一個怪句子** ——
    一筆壞資料不可以讓那個人收到一則看不懂的通知。"""
    assert nudge.passage({'label': '出 39-40'}) == '出 39-40'
    assert nudge.passage({}) == ''
