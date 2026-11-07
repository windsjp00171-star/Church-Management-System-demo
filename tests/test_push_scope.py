"""哪些通知會跳到手機上

## ★★ 這張表是使用者一項一項圈的，不是我排的

18 種通知，他圈了 14 種要推、4 種只留站內（2026-09-12）。
所以這一份測試守的不是「我覺得合理的設定」，是**他那次的決定還在不在**。

## 為什麼推不推這件事需要守衛

兩個方向都會**安靜地**出事：

- 該推的沒推 → 站內通知照樣有、鈴鐺照樣亮，**只是手機不會響**。
  沒有人會回報，因為對他來說那不叫壞掉。
- 不該推的推了 → `announcement` 是「推給全體」那一組，
  隨手拿來用就是**一次吵 119 支手機，而且收不回來**。
"""
import sys
import types

# routes.push 載入時會 import db；沒有真的環境變數時換成假的（需要資料庫的測試自己 patch supabase）
if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

import json
import ast
import re
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from routes import push

ROOT = Path(__file__).resolve().parent.parent
HELPERS = {'create_notification', 'batch_notify'}


# ══ 一、註冊表要蓋滿原始碼真的會產生的每一種 type ═══════

def _types_in_source():
    """原始碼裡所有會寫進 `notifications.type` 的字面值。

    ★ 用 AST 不是 grep：`type` 這個字到處都是（欄位型別、MIME、
      `field_type`），文字比對會撈回一堆不相干的東西，
      而那種測試很快就會被當成雜訊關掉。

    收兩種形狀：
      ① `create_notification(..., type='x')` / `batch_notify(..., type='x')`
      ② `batch_notify_rows` 那條路 —— 它收的是一排 dict，
         所以在**有 import 它的檔案**裡，額外收 `dict(type='x')`
         和 `{'type': 'x'}`。範圍限縮在那幾個檔案，
         不然全站每一個有 `type` 鍵的 dict 都會被誤收。
    """
    found = {}
    for path in sorted((ROOT / 'routes').glob('*.py')):
        src = path.read_text(encoding='utf-8')
        tree = ast.parse(src)
        rows_file = 'batch_notify_rows' in src

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, 'id', None) or getattr(fn, 'attr', None)

            if name in HELPERS or (rows_file and name == 'dict'):
                for kw in node.keywords:
                    if kw.arg == 'type' and isinstance(kw.value, ast.Constant) \
                            and isinstance(kw.value.value, str):
                        found.setdefault(kw.value.value, set()).add(path.name)

        if rows_file:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == 'type' \
                            and isinstance(v, ast.Constant) \
                            and isinstance(v.value, str):
                        found.setdefault(v.value, set()).add(path.name)
    return found


def test_the_scanner_actually_finds_things():
    """★ 先證明掃描器不是空的 —— 掃不到東西的話，
    下面那條「每一種都登記過」會**永遠通過**，而那是這個專案
    記過最多次的一種假守衛。"""
    found = _types_in_source()
    assert len(found) >= 5, f'只掃到 {sorted(found)}，掃描器大概壞了'
    assert 'announcement' in found and 'enrollment' in found


def test_every_type_the_code_can_produce_is_registered():
    """★★ 新增一種通知卻沒有表態要不要推 —— **沒有任何症狀**。

    它會落到 `should_push` 的「不認得就不推」，於是那則通知
    永遠只有站內。而那跟「刻意不推」在畫面上一模一樣。
    """
    known = set(push.PUSH_TYPES) | set(push.NO_PUSH)
    missing = {t: sorted(f) for t, f in _types_in_source().items()
               if t not in known}
    assert not missing, (
        '這幾種通知還沒決定要不要推播：\n'
        + '\n'.join(f'  {t}（出現在 {", ".join(fs)}）'
                    for t, fs in sorted(missing.items()))
        + '\n\n要推就加進 routes/push.PUSH_TYPES，不推就加進 NO_PUSH 並寫理由。')


def test_no_type_is_in_both_tables():
    """兩邊都寫的話，讀的人分不出哪一邊算數。"""
    both = set(push.PUSH_TYPES) & set(push.NO_PUSH)
    assert not both, f'{both} 同時出現在 PUSH_TYPES 和 NO_PUSH'


def test_every_entry_has_a_reason():
    """★ 留白的下一個人分不出「刻意不推」和「忘了登記」。"""
    for table, name in ((push.PUSH_TYPES, 'PUSH_TYPES'),
                        (push.NO_PUSH, 'NO_PUSH')):
        for key, why in table.items():
            assert why and len(why.strip()) >= 8, f'{name}[{key!r}] 沒寫理由'


# ══ 二、使用者那次的決定 ═════════════════════════════════

#  ★ 這四個是**他明確圈掉**的（2026-09-12）。
#    剛好都是同工／管理員收的，加上「代禱事項已被移除」。
STAYS_IN_APP_ONLY = {
    'info':   '代禱事項已被移除、報名已取消（通知另一方）',
    'gospel': '新的福音詢問、福音關懷指派 —— 收件者是同工',
    #  ★★ 2026-09-30 加進來的，而且是**改決定**：09-12 那次他是
    #    留著要推的。他的原話：「費用催繳不要做 這個在教會內部很敏感」。
    #    現在沒有任何地方會產生這種通知（`reminders` 那兩支已移除），
    #    這一行是第二層 —— 萬一以後有人手動發，也不會跳到 119 支手機上。
    #    整件事的守衛在 `tests/test_no_payment_chasing.py`。
    'payment_reminder': '費用待繳 —— 使用者要求不主動催繳（教會內部很敏感）',
}


@pytest.mark.parametrize('type_', sorted(STAYS_IN_APP_ONLY))
def test_the_four_he_crossed_out_do_not_push(type_):
    assert push.should_push(type_) is False, \
        f'{type_}（{STAYS_IN_APP_ONLY[type_]}）被他圈掉了，不可以推'


@pytest.mark.parametrize('type_', [
    'reminder',          # 1 候補遞補、12 教會行事提醒、13 個人行程提醒
    #  ★ 10、11 費用待繳**不在這裡了** —— 見上面 STAYS_IN_APP_ONLY
    'announcement',      # 4 全體廣播、5 教會行事、6 即將開課
    'event_reminder',    # 2 活動通知
    'course_reminder',   # 3 課程通知
    'enrollment',        # 16、17 報名成功
    'reading',           # 18 速讀每天一則
])
def test_the_ones_he_kept_do_push(type_):
    assert push.should_push(type_) is True


def test_an_unknown_type_does_not_push():
    """★★ 預設**不推**。

    反過來（預設推）的話，以後新加一種通知會在**沒有人決定過**的情況下
    直接跳到 119 支手機上。而漏推的代價只是「他要自己打開網站看」——
    站內那一則一定還在。
    """
    assert push.should_push('something_new') is False
    assert push.should_push(None) is False


# ══ 三、兩支發通知的函式都要走同一張表 ═══════════════════

def _fake_push():
    """把送出那一層換掉，回傳被推給了哪些人。

    ★ **兩個入口都要蓋**：單人那一支走
      `send_in_background`，一批各自不同的那一支走
      `send_many_in_background`（一條執行線跑完整批）。
      只蓋一個的話，另一條路的回歸完全沒人看著。
    """
    sent = []

    @contextmanager
    def both():
        with patch('routes.push.send_in_background',
                   side_effect=lambda uids, *a, **k: sent.append(list(uids))), \
             patch('routes.push.send_many_in_background',
                   side_effect=lambda jobs: [sent.append(list(u))
                                             for u, *_ in jobs]):
            yield

    return sent, both()


@pytest.mark.parametrize('type_,expected', [
    ('reminder', True),       # 9 候補遞補（同工手動）——原本推不出去
    ('payment_reminder', False),   # ★ 2026-09-30 改成不推（見上面）
    ('enrollment', True),     # 16、17 報名成功
    ('info', False),          # 14 報名已取消
    ('gospel', False),        # 15 福音關懷指派
])
def test_create_notification_pushes_exactly_what_he_picked(type_, expected):
    """★★ `create_notification`（單人那一支）原本**完全沒有接推播**。

    最能說明問題的是候補遞補：系統自動補的走 `batch_notify_rows`
    （推得出去），同工手動補的走這一支（推不出去）——
    **同一件事，名冊上一模一樣**，只有手機會不會響不一樣。
    """
    from routes import notifications
    sent, p = _fake_push()
    with patch('routes.notifications.supabase', MagicMock()), p:
        notifications.create_notification('u1', '標題', type=type_, link='/x')
    assert bool(sent) is expected, f'type={type_} 應該{"推" if expected else "不推"}'


@pytest.mark.parametrize('type_,expected', [
    ('announcement', True),   # 4 全體廣播
    ('info', False),
])
def test_batch_notify_respects_the_table_too(type_, expected):
    """★ 兩支各判一次的話，遲早會不一樣 —— 而不一樣的症狀是
    「同一種通知，群發推得出去、單發推不出去」。"""
    from routes import notifications
    sent, p = _fake_push()
    with patch('routes.notifications.supabase', MagicMock()), p:
        notifications.batch_notify(['u1', 'u2'], '標題', type=type_, link='/x')
    assert bool(sent) is expected




# ══ 四、送出不可以讓按下去的人等 ═════════════════════════

def test_sending_happens_off_the_request():
    """★★ 這一條守的是我上一版寫壞的地方。

    全體廣播是 119 個人，每一台裝置一個對外 HTTPS 請求（timeout=10）。
    同步跑的話同工按下「發送公告」要等二十幾秒才回來 —— 他會以為當掉、
    再按一次，於是**全教會收到兩則一模一樣的公告**。
    而站內那一半早就寫進去了，畫面上完全看不出問題在推播。
    """
    from config import Config
    old = (Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY)
    Config.VAPID_PUBLIC_KEY = Config.VAPID_PRIVATE_KEY = 'k'
    try:
        with patch('routes.push.threading.Thread') as T:
            assert push.send_in_background(['u1'], '標題') is True
        T.assert_called_once()
        assert T.call_args[1].get('daemon') is True, \
            '★ 要 daemon —— 不然重啟時整個行程會等這條執行緒'
    finally:
        Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY = old


def test_nothing_is_spawned_when_push_is_off():
    """沒設金鑰時連執行緒都不要開。"""
    from config import Config
    old = (Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY)
    Config.VAPID_PUBLIC_KEY = Config.VAPID_PRIVATE_KEY = ''
    try:
        with patch('routes.push.threading.Thread') as T:
            assert push.send_in_background(['u1'], '標題') is False
        T.assert_not_called()
    finally:
        Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY = old


def test_one_thread_for_the_whole_batch_not_one_per_person():
    """★ 一人一條的話，全體廣播是 119 條執行緒 ——
    免費方案的記憶體吃不下。"""
    from config import Config
    old = (Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY)
    Config.VAPID_PUBLIC_KEY = Config.VAPID_PRIVATE_KEY = 'k'
    try:
        with patch('routes.push.threading.Thread') as T:
            push.send_in_background([f'u{i}' for i in range(119)], '公告')
        assert T.call_count == 1
    finally:
        Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY = old


def test_a_crash_in_the_background_is_swallowed():
    """★ 執行緒裡沒有人接的例外只會印在 log 上，而沒有人在看那個 log。
    更重要的是：它不可以把整個行程帶走。"""
    with patch('routes.push.send_many', side_effect=RuntimeError('boom')):
        #  不可以丟出來
        push._send_quietly([(['u1'], '標題', '', '/')])
    #  ★ 但**吃掉不等於不留痕跡** —— 不記的話，
    #    整批全滅和整批成功長得一模一樣，而那正是使用者
    #    回報的那個症狀（「沒有收到過其他的東西」）。
    assert push.recent_attempts(1), '整批失敗却沒留下任何紀錄'


# ══ 五、文件要跟著這張表走 ═══════════════════════════════

def test_the_manual_says_which_notifications_reach_the_phone():
    """★ 手冊寫「通知會跳到手機」而實際上有四種不會 —— 那是**手冊在講
    一件不再為真的事**，比沒寫更糟（沒寫至少不會誤導）。"""
    doc = (ROOT / 'templates' / 'manual.html').read_text(encoding='utf-8')
    sec = doc[doc.index('id="push-notify"'):]
    sec = sec[:sec.index('</div>')]
    assert '手機通知' in sec
    #  ★ 要講出「不是每一種都會跳」——不然收不到的那四種看起來像壞了
    assert '不會跳到手機' in sec or '只留在這裡' in sec, \
        '手冊沒有說明哪些通知不會推到手機'


# ══ 六、整批推播只准開一條執行緒、查一次資料庫 ═══════════
#
#  使用者：「推播測試鈕 有正確推播 但是沒有收到過其他的東西」。
#
#  ★★ 測試鈕是**同步**送的，所以它會動。其他每一則都走背景執行緒，
#    而 `batch_notify_rows` 是**逐則**呼叫背景推播的 —— 聖經速讀那一則
#    是 114 個人，於是免費方案上瞬間開 114 條執行緒、114 次資料庫查詢。
#    失敗全部被背景執行緒吃掉，所以症狀正好是
#    「站內通知全部都在、手機一則都沒響」。
#
#  ★ 最說明問題的是：`send_in_background` 自己的說明裡就寫著
#    「只開一條執行緒跑整個迴圈，不是一人一條 —— 119 條執行緒會把
#    免費方案的記憶體吃掉」，而呼叫端違反了它。
#    **寫在註解裡的規則不會自己生效**，所以現在有這一條測試。

def _many_rows(n):
    return [{'user_id': f'u{i}', 'title': f'第 {i} 則',
             'type': 'reading', 'link': f'/reading/{i}'} for i in range(n)]




def test_a_hundred_notifications_do_not_make_a_hundred_queries():
    """★ 每一條執行緒本來還各自查一次 `push_subscriptions` ——
    114 次同時打進免費方案的 Supabase，而失敗是安靜的
    （`send_many` 查不到就回 0）。"""
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value\
        .execute.return_value.data = []
    with patch('routes.push.is_enabled', return_value=True):
        push.send_many([([f'u{i}'], f'第 {i} 則', '', '/') for i in range(114)],
                       sb=sb)
    assert sb.table.return_value.select.return_value.in_.call_count <= 2, \
        '一批人要一次問完（超過 100 人才分第二批）'


def test_everyone_still_gets_their_own_message():
    """★★ 併批不可以把大家的內容洗成同一則。

    速讀那一則對每個人講的是**他自己的下一格** —— 併成一則的話，
    讀到第 100 格的人會收到「從第 1 格開始」，而推播確實送出去了。
    """
    payloads = []
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value\
        .execute.return_value.data = [
            {'user_id': 'u0', 'endpoint': 'e0', 'p256dh': 'p', 'auth': 'a'},
            {'user_id': 'u1', 'endpoint': 'e1', 'p256dh': 'p', 'auth': 'a'},
        ]
    with patch('routes.push.is_enabled', return_value=True), \
         patch('routes.push._send_one',
               side_effect=lambda row, payload, **k: payloads.append(
                   (row['endpoint'], payload))):
        push.send_many([(['u0'], '甲', '', '/a'), (['u1'], '乙', '', '/b')],
                       sb=sb)
    got = {ep: json.loads(p)['title'] for ep, p in payloads}
    assert got == {'e0': '甲', 'e1': '乙'}


def test_a_batch_that_goes_nowhere_leaves_a_trace():
    """★★ 背景執行緒把例外吃掉是對的（推播不可以拖垮報名），
    但**整批全滅和整批成功長得一模一樣** —— 那正是使用者回報的症狀：
    站內通知全部都在，而他從來沒收到過任何一則推播。

    所以每一批都要記下「幾台、成功幾台、失敗原因」。
    """
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value\
        .execute.return_value.data = [
            {'user_id': 'u0', 'endpoint': 'e0', 'p256dh': 'p', 'auth': 'a'}]
    boom = Exception('nope')
    boom.response = type('R', (), {'status_code': 403})()
    with patch('routes.push.is_enabled', return_value=True), \
         patch('routes.push._send_one', side_effect=boom):
        push.send_many([(['u0'], '甲', '', '/a')], sb=sb)
    last = push.recent_attempts(1)[0]
    assert last['devices'] == 1 and last['sent'] == 0
    assert '403' in last['problems'][0], '沒留下原因就查不出是哪一種失敗'


def test_a_successful_batch_is_recorded_too():
    """★ 反過來也要記，不然「最近的推播」永遠是一排失敗，
    看起來像推播從來沒成功過。"""
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value\
        .execute.return_value.data = [
            {'user_id': 'u0', 'endpoint': 'e0', 'p256dh': 'p', 'auth': 'a'}]
    with patch('routes.push.is_enabled', return_value=True), \
         patch('routes.push._send_one'):
        push.send_many([(['u0'], '甲', '', '/a')], sb=sb)
    last = push.recent_attempts(1)[0]
    assert last['sent'] == 1 and not last['problems']


def test_a_database_hiccup_is_not_recorded_as_nobody_subscribed():
    """★★ 「查不到訂閱名單」和「沒有人訂閱」要分得出來。

    混在一起的話，資料庫抖一下會被記成「0 台裝置」——
    而那看起來就像這個功能沒有人用。
    """
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value\
        .execute.side_effect = Exception('db down')
    with patch('routes.push.is_enabled', return_value=True):
        push.send_many([(['u0'], '甲', '', '/a')], sb=sb)
    assert '訂閱名單' in push.recent_attempts(1)[0]['problems'][0]


# ══ 七、後台看得到「最近的推播」 ═════════════════════════

@pytest.fixture
def keyed():
    """假裝金鑰設好了（＝推播是開著的）。"""
    from config import Config
    old = (Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY)
    Config.VAPID_PUBLIC_KEY = Config.VAPID_PRIVATE_KEY = 'k'
    yield
    Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY = old


def _usage_html(client):
    from tests.fake_supabase import FakeSupabase
    import glob
    import os
    from contextlib import ExitStack
    db = FakeSupabase()
    with client.session_transaction() as s:
        s.update(user_id='u1', real_name='管', is_admin=True,
                 is_super_admin=True, admin_modules='*', member_type='member')
    with ExitStack() as stack:
        for path in glob.glob('routes/*.py'):
            mod = 'routes.' + os.path.basename(path)[:-3]
            try:
                stack.enter_context(patch(f'{mod}.supabase', db))
            except (AttributeError, ModuleNotFoundError):
                pass
        return client.get('/admin/usage').get_data(as_text=True)






# ══ 八、覆蓋率：這件事的天花板不在程式 ═══════════════════
#
#  ★★ CLAUDE.md 寫著「覆蓋率不用另外做統計 —— `push_subscriptions`
#    的列數就是它」。那句話是對的，但那個數字**沒有任何一個畫面顯示它**
#    —— 每次要看都得有人進資料庫撈。這正是這個專案記過的
#    「沒有入口的功能等於不存在」，發生在覆蓋率這個數字本身上。

def _subs(*specs):
    """(user_id, user_agent, endpoint, created_at)"""
    return [{'user_id': u, 'user_agent': ua, 'endpoint': ep, 'created_at': at}
            for u, ua, ep, at in specs]


def test_a_desktop_is_not_counted_as_android():
    """★★ FCM 的網址（`fcm.googleapis.com`）**電腦版 Chrome 也在用**。

    只看 endpoint 的話桌機會被算成 Android —— 而 **iPhone 那一格是這件事
    最重要的數字**（iOS 沒裝 PWA 就永遠收不到）。我自己就因為只看
    endpoint 而跟使用者講錯過一次：說「Android 8」，其中一台是 Windows。
    """
    assert push.device_label('Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                             'https://fcm.googleapis.com/fcm/send/x') == '其他／電腦'
    assert push.device_label('Mozilla/5.0 (Linux; Android 10; K)',
                             'https://fcm.googleapis.com/fcm/send/x') == 'Android'


def test_an_iphone_is_recognised():
    """★ iOS 那一格算錯的話，「iPhone 的人裝不起來」這件事就看不到了。"""
    assert push.device_label(
        'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X)') == 'iPhone / iPad'


def test_an_unknown_device_is_not_guessed():
    """★ 認不出來就說「其他／電腦」，不要猜一個手機 ——
    猜錯的代價是 iOS 那一格的數字是假的，而那正是要拿來做判斷的那一格。"""
    assert push.device_label('') == '其他／電腦'
    assert push.device_label(None) == '其他／電腦'


def test_one_person_with_three_devices_is_one_person():
    """★★ 覆蓋率問的是「幾個人收得到」，不是「幾台裝置」。

    混在一起的話，一個人裝了手機＋平板＋電腦會讓覆蓋率看起來是三倍，
    而那個數字會被拿去決定要不要推廣。
    """
    cov = push.coverage(_subs(
        ('u1', 'iPhone', 'e1', '2026-09-13T00:00:00+08:00'),
        ('u1', 'Android', 'e2', '2026-09-13T00:00:00+08:00'),
        ('u1', 'Windows', 'e3', '2026-09-13T00:00:00+08:00'),
    ), members=120)
    assert cov['people'] == 1 and cov['devices'] == 3


def test_a_missing_member_count_is_not_zero_percent():
    """★★ 查不到會友人數 ≠ 0%。

    印成 0% 的話同工會以為沒有人開通知，而他會據此做決定
    —— 跟使用統計那一頁「查不到 ≠ 0」同一條規則。
    """
    cov = push.coverage(_subs(('u1', 'iPhone', 'e1', '2026-09-13T00:00:00+08:00')),
                        members=None)
    assert cov['rate'] is None


def test_the_rate_is_people_over_members():
    from datetime import datetime, timedelta, timezone
    tw = timezone(timedelta(hours=8))
    rows = _subs(*[(f'u{i}', 'iPhone', f'e{i}', '2026-09-13T00:00:00+08:00')
                   for i in range(12)])
    cov = push.coverage(rows, members=120,
                        now=datetime(2026, 9, 13, 12, 0, tzinfo=tw))
    assert cov['rate'] == 10


def test_new_this_week_only_counts_this_week():
    """★ 「最近七天新增」是趨勢 —— 全部算進去的話它永遠等於總數，
    而趨勢正是「有人把通知關掉」唯一看得到的訊號。"""
    from datetime import datetime, timedelta, timezone
    tw = timezone(timedelta(hours=8))
    now = datetime(2026, 9, 13, 12, 0, tzinfo=tw)
    cov = push.coverage(_subs(
        ('u1', 'iPhone', 'e1', '2026-09-12T00:00:00+08:00'),   # 昨天
        ('u2', 'iPhone', 'e2', '2026-01-01T00:00:00+08:00'),   # 很久以前
    ), members=120, now=now)
    assert cov['devices'] == 2 and cov['recent'] == 1


def test_batch_notify_rows_uses_each_rows_own_type():
    """★ 這一支每一列的 type 可能不同，拿整批的第一個去判是錯的。"""
    from routes import notifications
    sent, p = _fake_push()
    rows = [
        {'user_id': 'u1', 'title': 'A', 'type': 'reminder', 'link': '/a'},
        {'user_id': 'u2', 'title': 'B', 'type': 'info', 'link': '/b'},
    ]
    with patch('routes.notifications.supabase', MagicMock()), p:
        notifications.batch_notify_rows(rows)
    assert sent == [['u1']], f'只有 u1 那一列該推，實際 {sent}'


def test_a_hundred_notifications_do_not_start_a_hundred_threads():
    """★★ 這就是那個 bug 本身。"""
    from routes import notifications
    with patch('routes.notifications.supabase', MagicMock()), \
         patch('routes.push.is_enabled', return_value=True), \
         patch('routes.push.threading.Thread') as T:
        notifications.batch_notify_rows(_many_rows(114))
    assert T.call_count == 1, f'開了 {T.call_count} 條執行緒'
