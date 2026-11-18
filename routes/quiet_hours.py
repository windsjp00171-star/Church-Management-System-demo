"""安靜時段：21:00–07:00 不吵人

使用者的原話（訂正我的版本）：
**「靜音時段應該是 21：00-07：00 這種手機離峰期才對吧」**。

所以真正的規則是講「**什麼時候安靜**」，送出的窗是它的補集：

    安靜  21:00 ────────── 07:00     ← 不推
    可推  07:00 ────────── 21:00

## ★★ 我原本寫成 09:00–21:00，那是把他的話套錯了範圍

他說「不要太早發」是在講**聖經速讀那一則**（那一則現在仍然是 09:00，
見 `routes/reading_nudge.READING_START_HOUR`）。我把那一句拿去當成
**全部排程提醒**的下限 —— 而「明天有課」「還沒繳費」這種事，
早上七點講完全合理，壓到九點只是讓他晚兩小時才知道。

★ 這是這份專案記過好幾次的同一個形狀：**分不清哪一條是他說的、
  哪一條是我推的**。他講的是一則，我推成了全部。

## ★★ 為什麼每一種排程提醒都要過這一關

提醒的「到期」是**以天為單位**算的（`reminders._due`：還剩幾天 ≤
remind_days）。所以一件事會在它進入視窗的那一天 **00:00 就變成該發** ——
而排程每 15 分鐘轉一次，於是

    ⛪ 教會行事提醒 → 半夜 00:07 推到 119 支手機

## 上界（21:00）是同一個邏輯

排程不是「準點響」，是「那個時間之後的**第一次 tick**」。Render 免費方案
會睡，睡掉半天再醒來的話，沒有上界那一則會補在半夜十一點半。

## ★ 這一關只擋**排程**，不擋人自己觸發的

前台那支 poll（他打開網站時）照常跑：他人醒著、正在看這個網站，
而且那一下只會通知他自己。
"""
from datetime import datetime, timedelta, timezone

TAIPEI_TZ = timezone(timedelta(hours=8))

#  安靜時段（台北時間）：從 QUIET_FROM 開始安靜，到 QUIET_UNTIL 結束。
#  也就是「可以推」的窗是 [QUIET_UNTIL, QUIET_FROM)。
QUIET_FROM = 21
QUIET_UNTIL = 7


def now_taipei():
    return datetime.now(TAIPEI_TZ)


def in_window(now=None, start=None, end=None):
    """現在可以推嗎（＝**不在**安靜時段裡）。

    `start` / `end` 可以蓋掉預設 —— 某一種提醒想更晚才開始講話時用
    （速讀那一則就是：他明確說過那一則不要太早發）。
    """
    now = now or now_taipei()
    start = QUIET_UNTIL if start is None else start
    end = QUIET_FROM if end is None else end
    return start <= now.hour < end


def label(start=None, end=None):
    """講給人看的時段，給「這次跳過」的回報用。"""
    start = QUIET_UNTIL if start is None else start
    end = QUIET_FROM if end is None else end
    return f'{start:02d}:00–{end:02d}:00'
