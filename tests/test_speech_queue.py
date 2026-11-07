"""朗讀的佇列 —— 在 node 裡用假的 speechSynthesis 真的跑一次

## 為什麼不是掃原始碼

朗讀的失敗模式全部是**「按了，然後就沒有然後了」**：唸完第一節就停住、
按停止再按朗讀沒有聲音、切到背景回來跳掉三節。

這些看程式碼看不出來，而且**畫面完全正常** —— 按鈕還在、字還在、
沒有任何錯誤。掃原始碼的斷言也驗不到（它只看得到「有沒有寫這一行」，
看不到「連起來會不會動」）。

## ★ 使用者要的是 iOS 上正常

使用者的原話：「朗讀模式確認IOS系統正常喔」。

★ **我沒有 iOS 裝置可以實測，所以這裡驗的不是「在 iPhone 上會動」**，
  是「iOS Safari 那幾個有記錄的行為出現時，我們接得住」。
  真的要確認還是得拿一支 iPhone 打開來聽 —— 這一點必須講清楚，
  不可以讓一排綠燈看起來像「已經在 iOS 上驗過了」。

重現的三個 iOS 行為：
  1. `onend` 不觸發（cancel 之後、切背景回來時很常見）
  2. `cancel()` 之後同一個 tick 送的 `speak()` 會被丟掉
  3. utterance 沒人留參考就會被 GC，事件全部消失
"""
import json
import shutil
import subprocess

import pytest


@pytest.fixture(scope='module')
def out():
    assert shutil.which('node'), (
        'node 不在 —— 這條**不能 skip**：它守的是「朗讀會不會靜靜停住」，'
        '而那正是看程式碼看不出來的那一類')
    r = subprocess.run(['node', 'tests/js/speech_harness.js'],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_normal_run_reads_every_verse_then_stops(out):
    r = out['normal_run']
    assert r['spoken'] == ['第一節', '第二節', '第三節']
    assert r['highlights'] == [0, 1, 2, 'stop'], '每一節都要標出來，最後要收乾淨'
    assert r['speaking'] is False


# ── iOS 坑 1：onend 不來 ────────────────────────────────

def test_it_keeps_going_when_onend_never_fires(out):
    """★★ 這是 iOS 上最常見的死法。

    我們靠 `onend` 接下一節 —— 不觸發就等於**唸完第一節就停住**，
    而畫面完全正常（還亮著、按鈕還在），使用者只會覺得「壞了」。
    """
    r = out['onend_never_fires']
    assert r['after_start'] == ['第一節'], '一開始只唸第一節'
    assert r['after_one_watchdog'] == ['第一節', '第二節'], \
        '看門狗到期要自己推到下一節'
    assert r['all_spoken'] == ['第一節', '第二節', '第三節']
    assert r['still_speaking'] is False, '唸完要自己停'


def test_the_watchdog_never_skips_a_verse(out):
    """★ 看門狗和 `onend` 都到的話不可以各推一次。"""
    assert out['watchdog_does_not_double_advance']['spoken'] == \
        ['第一節', '第二節', '第三節']


def test_a_late_onend_does_not_skip_the_next_verse(out):
    """★★ 真實瀏覽器的 `onend` 是**非同步**的，iOS 上常常晚到 ——
    甚至晚到下一節已經開始之後。

    沒有比對「是哪一節結束了」的話，那一下會把**還沒唸的第三節
    直接跳過去** —— 而使用者只會覺得「怎麼少唸了一句」。

    ★ 第一版的情境測不到這條（那裡的 `onend` 是同步發的，
      根本不會有殘留的計時器）—— mutation 當場抓到它是假的。
    """
    r = out['late_onend_does_not_skip']
    assert r['after_watchdog'] == ['第一節', '第二節'], '看門狗推到第二節'
    assert r['after_late_onend'] == ['第一節', '第二節'], \
        '遲到的 onend 不可以再推一次（那會跳掉第三節）'


def test_the_watchdog_is_much_longer_than_the_real_speech(out):
    """★★ 寧可晚不可早。

    太短會**跳掉還在唸的那一節**（使用者以為漏了經文）；
    太長只是多一點空白。所以估算值抓得比實際慢很多。
    """
    w = out['watchdog_is_generous']
    #  四個字實際唸不到 1 秒，看門狗要有好幾秒
    assert w['short'] >= 8000
    #  八十個字實際約 15 秒，看門狗要明顯更久
    assert w['long'] >= 30000
    assert w['faster_is_shorter'] is True, '唸得快，等待也要跟著短'


# ── iOS 坑 2：cancel 之後馬上 speak 會被丟掉 ──────────────

def test_restarting_waits_for_cancel_to_settle(out):
    """★★ 按「停止」再按「朗讀」就沒有聲音了 —— 那是這個坑。

    iOS 的佇列還在收尾，同一個 tick 送進去的那一句直接消失。
    """
    r = out['restart_after_cancel']
    assert r['spoken_immediately'] == [], '正在唸的時候不可以同 tick 就送'
    assert r['dropped'] == 0, '不該有句子被丟掉'
    assert r['spoken_after_delay'] == ['第一節', '第二節', '第三節']


def test_the_very_first_speak_stays_in_the_user_gesture(out):
    """★★ 反過來的規定：**第一次** `speak()` 必須在使用者手勢的同一個 tick。

    為了閃坑 2 而把它包進 `setTimeout` 的話，iOS 會直接不出聲 ——
    而那是「按了完全沒反應」，比慢一點糟得多。
    所以只有「正在唸」時才延遲。
    """
    assert out['first_speak_is_synchronous']['spoken_before_any_timer'] == ['第一節']


# ── iOS 坑 3：utterance 被 GC ───────────────────────────

def test_it_holds_on_to_the_utterance(out):
    """★ 只丟給 `speak()` 而自己不留參考的話，瀏覽器可能在唸完之前
    就把它回收掉 —— 事件全部消失，於是又變成「唸一節就停住」。"""
    r = out['keeps_utterance_reference']
    assert r['has_current'] is True
    assert r['text'] == '第一節'


# ── 收尾與續播 ─────────────────────────────────────────

def test_stop_leaves_nothing_running(out):
    """★ 計時器沒清掉的話，停止之後看門狗還會到期 ——
    然後它會在使用者以為已經停了的時候突然又唸起來。"""
    r = out['stop_clears_everything']
    assert r['speaking'] is False
    assert r['index'] == 0
    assert r['current'] is None
    assert r['timers_left'] == 0


def test_resume_continues_from_the_same_verse(out):
    """★ 暫停之後接著唸要從**同一節**，不是從頭 ——
    從頭的話聽到一半接個電話回來就要重聽二十節。"""
    r = out['resume_continues']
    assert r['paused_at'] == 1
    assert r['after_resume'] == ['第二節']


def test_one_bad_verse_does_not_kill_the_rest(out):
    """★ 某一節唸不出來（奇怪的標點、太長）不該讓後面全部沒聲音。"""
    assert out['one_bad_verse_does_not_kill_the_rest']['spoken'] == ['第一節', '第三節']


def test_blank_verses_do_not_stall_the_queue(out):
    """★ 空白的那一節要跳過。停在那裡的話後面全部不會唸，
    而畫面上看不出是哪裡卡住。"""
    assert out['blank_verses_are_skipped']['spoken'] == ['甲', '丙']


# ── 頁面那一層 ─────────────────────────────────────────

def test_going_to_the_background_pauses_instead_of_racing_the_watchdog():
    """★★ iOS 切到背景（或鎖螢幕）時系統會把語音停住，
    但我們的看門狗還在跑 —— 回來的時候它已經「走過」好幾節，
    而那幾節根本沒唸出來。

    所以離開畫面就先暫停，回來由使用者自己按「接著唸」。
    """
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent
          / 'static' / 'js' / 'bible-reading-day.js').read_text(encoding='utf-8')
    assert 'visibilitychange' in js
    assert 'document.hidden' in js


def test_the_page_keeps_no_second_copy_of_the_speaking_state():
    """★ 「有沒有在唸」只准有一份（在佇列裡）。

    頁面自己再留一份的話，兩份遲早會不一樣，而症狀是
    「按暫停沒反應」—— 按鈕以為沒在唸，佇列還在唸。
    """
    from pathlib import Path
    import re
    js = (Path(__file__).resolve().parent.parent
          / 'static' / 'js' / 'bible-reading-day.js').read_text(encoding='utf-8')
    code = re.sub(r'//.*$', '', js, flags=re.M)
    assert not re.search(r'\bvar\s+speaking\b', code), '頁面不可以自己再存一份'
    assert 'queue.isSpeaking()' in code, '要問佇列'
