"""推播（Web Push）

使用者：「PWA未來都還會繼續安裝 現在先把推播做好應該不吃虧」

## ★★ 這個功能的失敗全部是安靜的

推播送不到不會有人回報 —— 他只會覺得「系統沒有提醒我」，
而畫面上一切正常。下面每一條各守一種安靜的失敗。
"""
import sys
import types

# routes.push 載入時會 import db；沒有真的環境變數時換成假的（需要資料庫的測試自己 patch supabase）
if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from routes import push

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def app(fake_db):
    from flask import Flask
    a = Flask(__name__)
    a.secret_key = 'test'
    import routes.push as P
    a.register_blueprint(P.push_bp)
    return a


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def keyed():
    """假裝金鑰設好了。"""
    from config import Config
    old = (Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY)
    Config.VAPID_PUBLIC_KEY = 'pub-key'
    Config.VAPID_PRIVATE_KEY = 'priv-key'
    yield
    Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY = old


def _member(client):
    with client.session_transaction() as s:
        s.update(user_id='u1', real_name='測試', member_type='member',
                 line_id='U1', is_admin=False)
    return client


SUB = {'endpoint': 'https://push.example/abc',
       'keys': {'p256dh': 'p-key', 'auth': 'a-key'}}


# ══ 一、沒設金鑰＝整個關掉，不是壞掉 ═════════════════════

def test_without_keys_it_is_simply_off():
    """★ 有訂閱在資料表裡，但**沒設金鑰** —— 一則都不可以送出去。

    ★★ 這一條原本斷言 `send_to(...) == (0, 0)`，而那是**假的**：
      拿掉 `is_enabled()` 那道守衛之後，替身資料庫本來就回 0 筆，
      於是結果照樣是 `(0, 0)`。要讓它真的守著，資料表裡必須**有東西**，
      `_send_one` 一次都沒被呼叫才算數。（mutation 當場抓到。）
    """
    from config import Config
    old = (Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY)
    Config.VAPID_PUBLIC_KEY = Config.VAPID_PRIVATE_KEY = ''
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = _rows(3)
    try:
        assert push.is_enabled() is False
        with patch('routes.push._send_one') as send:
            assert push.send_to(['u1'], '標題', sb=sb) == (0, 0)
        send.assert_not_called()
    finally:
        Config.VAPID_PUBLIC_KEY, Config.VAPID_PRIVATE_KEY = old


def _profile_html(client, push_enabled):
    """真的把個人資料頁 render 出來（不是掃模板原始碼）。"""
    _member(client)
    sb = MagicMock()

    def table(name):
        c = MagicMock()
        for m in ('select', 'eq', 'order'):
            getattr(c, m).return_value = c
        c.execute.return_value.data = (
            [{'id': 'u1', 'real_name': '測試', 'display_name': 'LINE 暱稱',
              'picture_url': None, 'group_tags': [], 'birthday': None}]
            if name == 'users' else [])
        return c

    sb.table.side_effect = table
    with patch('routes.profile.supabase', sb), \
         patch('routes.push.is_enabled', return_value=push_enabled):
        r = client.get('/profile')
    assert r.status_code == 200
    return r.get_data(as_text=True)






def test_the_key_endpoint_says_it_is_off(client):
    from config import Config
    old = Config.VAPID_PUBLIC_KEY
    Config.VAPID_PUBLIC_KEY = ''
    try:
        d = client.get('/api/push/key').get_json()
        assert d['enabled'] is False
    finally:
        Config.VAPID_PUBLIC_KEY = old


# ══ 二、訂閱 ═════════════════════════════════════════════

def test_subscribing_needs_a_login(client):
    assert client.post('/api/push/subscribe', json=SUB).status_code == 401


@pytest.mark.parametrize('bad', [
    {'endpoint': '', 'keys': {'p256dh': 'a', 'auth': 'b'}},
    {'endpoint': 'x', 'keys': {'p256dh': '', 'auth': 'b'}},
    {'endpoint': 'x', 'keys': {'p256dh': 'a', 'auth': ''}},
    {'endpoint': 'x'},
])
def test_an_incomplete_subscription_is_rejected_now_not_later(client, bad):
    """★ 少一個欄位的話，推播會在**送出的那一刻**才失敗 ——
    而那時候沒有人在看。現在擋掉，訂閱的人當場就知道沒成功。"""
    _member(client)
    with patch('routes.push.supabase') as sb:
        r = client.post('/api/push/subscribe', json=bad)
    assert r.status_code == 400
    sb.table.return_value.upsert.assert_not_called()


def test_the_same_device_overwrites_instead_of_adding(client):
    """★★ endpoint 是唯一鍵，重訂要**蓋掉**。

    不蓋的話同一台會累積很多列，於是他每一則通知**收到 N 次** ——
    而那看起來像系統壞了，他會把通知整個關掉。
    """
    _member(client)
    with patch('routes.push.supabase') as sb:
        client.post('/api/push/subscribe', json=SUB)
        kwargs = sb.table.return_value.upsert.call_args[1]
    assert kwargs.get('on_conflict') == 'endpoint'


def test_unsubscribing_does_not_need_a_login(client):
    """★★ 他可能已經登出了，但瀏覽器還握著訂閱。

    要求登入的話，那台裝置會**永遠收到推播而他關不掉**。
    """
    with patch('routes.push.supabase'):
        r = client.post('/api/push/unsubscribe',
                        json={'endpoint': 'https://push.example/abc'})
    assert r.status_code == 200


# ══ 三、送出 ═════════════════════════════════════════════

def _rows(n=1):
    return [{'endpoint': f'https://push.example/{i}', 'p256dh': 'p',
             'auth': 'a', 'user_id': 'u1'} for i in range(n)]


def test_it_pushes_to_every_device_of_that_person(keyed):
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = _rows(3)
    with patch('routes.push._send_one') as send:
        sent, dead = push.send_to(['u1'], '標題', '內文', '/events', sb=sb)
    assert (sent, dead) == (3, 0)
    assert send.call_count == 3


def test_a_dead_subscription_is_deleted(keyed):
    """★★ 推播服務回 404/410 ＝ 這個訂閱死了。

    不刪的話那張表會慢慢長滿死掉的裝置，而每次推播都對它們重試 ——
    失敗是安靜的，所以沒有人會發現。
    """
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = _rows(1)
    err = RuntimeError('gone')
    err.response = MagicMock(status_code=410)
    with patch('routes.push._send_one', side_effect=err):
        sent, dead = push.send_to(['u1'], '標題', sb=sb)
    assert (sent, dead) == (0, 1)
    sb.table.return_value.delete.return_value.eq.assert_called_with(
        'endpoint', 'https://push.example/0')


def test_a_temporary_failure_does_not_delete_anything(keyed):
    """★ 網路問題、推播服務暫時掛掉 —— **不可以**把訂閱刪掉。
    刪了的話他要自己再去按一次開啟，而沒有人會知道要去按。"""
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = _rows(1)
    err = RuntimeError('timeout')
    err.response = MagicMock(status_code=500)
    with patch('routes.push._send_one', side_effect=err):
        sent, dead = push.send_to(['u1'], '標題', sb=sb)
    assert (sent, dead) == (0, 0)
    sb.table.return_value.delete.assert_not_called()


def test_deadness_is_decided_by_the_status_code_not_the_message():
    """★ 用訊息字串判斷的話，套件改一次措辭我們就會**安靜地**
    停止清理死訂閱。"""
    src = (ROOT / 'routes' / 'push.py').read_text(encoding='utf-8')
    body = src[src.index('def _is_dead'):]
    body = body[:body.index('\ndef ', 1)]
    assert 'status_code' in body
    assert 'str(' not in body and '.message' not in body


def test_one_broken_device_does_not_stop_the_others(keyed):
    """★ 三台裝置，第一台炸掉 —— 另外兩台還是要收到。"""
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = _rows(3)
    calls = {'n': 0}

    def flaky(row, payload):
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('boom')

    with patch('routes.push._send_one', side_effect=flaky):
        sent, _ = push.send_to(['u1'], '標題', sb=sb)
    assert sent == 2


def test_the_payload_carries_a_link(keyed):
    """★ 點了通知要去對的地方。沒有 url 的話點了停在首頁，
    而他要自己找那件事在哪裡。"""
    data = json.loads(push._payload('標題', '內文', '/events/1'))
    assert data['url'] == '/events/1'
    assert data['title'] == '標題'


# ══ 四、推播永遠不是唯一的路 ═════════════════════════════

def test_the_in_app_notification_is_written_first():
    """★★ 順序是**先寫站內、再推播**。

    反過來的話，推播成功而站內寫入失敗時，他手機上看到一則通知、
    點進來卻什麼都沒有。
    """
    src = (ROOT / 'routes' / 'notifications.py').read_text(encoding='utf-8')
    body = src[src.index('def batch_notify('):]
    body = body[:body.index('\ndef ', 1)]
    assert body.index("table('notifications').insert") < body.index('_push('), \
        '推播排在寫站內通知前面了'


def test_push_failure_never_breaks_sending_a_notification():
    """★★ 推播壞掉不可以讓「發通知」失敗，更不可以讓報名、遞補、
    簽到那些主要流程失敗。"""
    src = (ROOT / 'routes' / 'notifications.py').read_text(encoding='utf-8')
    body = src[src.index('def _push('):]
    body = body[:body.index('\ndef ', 1) if '\ndef ' in body[1:] else len(body)]
    assert 'try:' in body and 'except Exception' in body


def test_both_notification_helpers_push():
    """★ 兩支發通知的函式都要推 —— 只接一支的話，
    候補遞補（走另一支）的人永遠收不到手機通知，而站內是有的。"""
    #  ★★ 這一條原本是掃原始碼找 `_push(`。兩件事讓它變成假守衛：
    #    ① 把呼叫改名（現在一批那一支走 `_push_rows`）它就紅，
    #      而行為完全正確；② 把 `_push` 的函式體挖空它照樣綠。
    #    所以改成**真的呼叫兩支**，看送出那一層有沒有被碰到。
    from routes import notifications
    for call in (
        lambda: notifications.batch_notify(['u1'], '標題', type='reminder'),
        lambda: notifications.create_notification('u1', '標題', type='reminder'),
    ):
        hits = []
        with patch('routes.notifications.supabase', MagicMock()), \
             patch('routes.push.send_in_background',
                   side_effect=lambda *a, **k: hits.append(a)), \
             patch('routes.push.send_many_in_background',
                   side_effect=lambda *a, **k: hits.append(a)):
            call()
        assert hits, '這一支沒有接上推播'


# ══ 五、Service Worker ═══════════════════════════════════

def _sw():
    return (ROOT / 'static' / 'sw.js').read_text(encoding='utf-8')


def test_the_push_event_always_shows_a_notification():
    """★★ 瀏覽器規定：收到推播卻不顯示通知（silent push），
    累犯會被**取消這個網站的推播權限** —— 而那是靜靜發生的，
    之後每一則都送不到，沒有任何錯誤。

    所以解析失敗也要顯示一句通用的字。
    """
    sw = _sw()
    body = sw[sw.index("addEventListener('push'"):]
    body = body[:body.index("addEventListener('notificationclick'")]
    assert 'showNotification' in body
    #  解析失敗那一路也要走到 showNotification（不可以 return）
    assert 'catch' in body and 'return;' not in body


def test_clicking_a_notification_reuses_an_open_tab():
    """★ 每次都開新視窗的話，他點五則通知就開五個分頁 ——
    PWA 使用者更慘：每一則都開一個新視窗。

    ★ 比對要用**完整的呼叫**（`clients.matchAll(`）不是 `matchAll` 三個字 ——
    子字串的話 `matchAllX` 也會通過，而那正是「這行已經壞了」的樣子。
    （這個專案記過的第三種假守衛，mutation 當場抓到。）
    """
    sw = _sw()
    body = sw[sw.index("addEventListener('notificationclick'"):]
    assert 'clients.matchAll(' in body, '沒有先找已經開著的分頁'
    assert '.focus()' in body, '找到分頁卻沒有帶到前景'


def test_notifications_with_the_same_target_collapse():
    """★ 排程重試時，同一件事會推第二次 ——
    沒有 tag 的話他會看到兩三則一模一樣的通知。"""
    sw = _sw()
    body = sw[sw.index("addEventListener('push'"):]
    assert 'tag:' in body


# ══ 六、前端：在 node 裡用假的瀏覽器真的跑一次 ══════════
#
# ★★ 這一節原本全部是掃 JS 原始碼的斷言，而 mutation 抓到**兩條是假的**：
#   ① `'matchAll' in js` —— 改成 `matchAllX` 照樣通過（子字串）
#   ② `'getSubscription' in js` —— 那個字在 `disable()` 裡也有一個，
#      所以把「載入時去查」整段拿掉，測試還是綠的
#
#   更根本的是：掃原始碼看得到「有沒有寫這一行」，看不到
#   「這一行會不會被走到」。把 `if (st === 'granted' …)` 改成 `if (false)`
#   —— 每一條掃字串的斷言都還是綠的，而畫面上那顆鈕**永遠寫著
#   「開啟手機通知」**，他會以為沒設定成功而一直按。
#
# ★ 這裡驗的是「接線有沒有接上」，**不是「在 iPhone 上會動」**。
#   iOS 那兩道門檻（要裝成 PWA、要按允許）沒有任何模擬器驗得了 ——
#   跟朗讀那一份一樣，一排綠燈不等於在 iOS 上驗過。

import shutil
import subprocess


@pytest.fixture(scope='module')
def optin():
    assert shutil.which('node'), (
        'node 不在 —— 這一節**不能 skip**：它守的是「那顆鈕會不會靜靜地'
        '什麼都不做」，而那正是掃原始碼看不出來的那一類')
    r = subprocess.run(['node', 'tests/js/push_optin_harness.js'],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_nobody_is_asked_for_permission_just_for_opening_the_page(optin):
    """★★ 一進站就問的話，多數人直覺按「不允許」，而**瀏覽器會記住
    那個拒絕** —— 之後我們再也問不到他，要他自己去設定裡改回來。

    四種裝置狀態載入之後，`requestPermission` 都必須是 0 次。
    """
    for name, case in optin.items():
        assert case['afterLoad']['asked'] == 0, f'{name}：頁面一載入就跳權限對話框了'


def test_asking_happens_on_the_click(optin):
    """★ 反過來也要驗 —— 不然「永遠不問」也會是綠的。"""
    fresh = optin['fresh_device']
    assert fresh['afterLoad']['msg'] == '', '還沒按就講話了'
    assert fresh['calls']['requestPermission'] == 1, '按了卻沒問權限'
    assert fresh['calls']['subscribe'] == 1, '問到了卻沒有真的訂閱'
    assert '/api/push/subscribe' in fresh['calls']['posted'], '訂閱沒有存回伺服器'


def test_an_already_subscribed_device_shows_as_on(optin):
    """★★ 不顯示成已開啟的話，他每次來都看到「開啟通知」，
    會以為沒設定成功而一直按。

    ★ 這一條要**真的跑一次**才驗得到：掃原始碼分不出
      「那段不見了」和「那段還在但走不到」。
    """
    load = optin['already_subscribed']['afterLoad']
    assert load['on'] == '1', '已經訂閱了，按鈕卻還停在「開啟」的狀態'
    assert '關閉' in load['label'], f"按鈕上寫的是「{load['label']}」"
    assert '已經開啟' in load['msg']
    #  ★ 而且不可以順手又問一次權限
    assert optin['already_subscribed']['calls']['requestPermission'] == 0


def test_ios_safari_is_told_to_install_first_not_that_it_is_unsupported(optin):
    """★★ iOS 的 Safari 分頁收不到推播 —— 但那**不是「不支援」**，
    是「還沒加到主畫面」。講成不支援的話他就放棄了，
    而其實他只要多做一個動作。"""
    msg = optin['ios_safari_tab']['afterLoad']['msg']
    assert '加到主畫面' in msg, f'iOS 分頁看到的是「{msg}」'
    assert '不支援' not in msg


def test_a_step_that_never_answers_does_not_leave_him_staring_at_it(optin):
    """★★ 這一條是**正式站真的踩到的那個 bug**（2026-09-12）。

    Service Worker 註冊在 `/static/sw.js`，所以 scope 是 `/static/` ——
    它不控制任何一頁真正的頁面。於是
    `await navigator.serviceWorker.ready` 在 `/profile` 上
    **永遠不會 resolve、也永遠不會 reject**。

    那不是失敗，是**永遠停住**：沒有錯誤、沒有逾時，使用者看到的是
    「處理中…」卡在那裡，而伺服器那邊 `push_subscriptions` **一筆都沒有**。
    使用者的原話：「等待中卡很久」。

    scope 已經修好了（改註冊 `/sw.js`），但「不會回來的 promise」還會
    從別的地方冒出來 —— 所以規則是：**使用者在等的每一步都要有期限**。
    """
    st = optin['sw_never_ready']['afterClick']
    assert st['msg'] != '處理中…', '逾時之後還卡在「處理中…」'
    assert st['disabled'] is False, '按鈕沒有還回去 —— 他連重試都不行'
    #  ★ 而且要講得出**卡在哪一步**，不是「開啟失敗」
    assert '重新整理' in st['msg'], f'沒有告訴他可以做什麼：{st["msg"]}'


def test_the_service_worker_is_registered_at_the_root():
    """★★ 同一個 bug 的另一半：scope。

    Service Worker 的 scope 預設是**那支檔案所在的目錄**。
    掛在 `/static/sw.js` 就等於 scope 是 `/static/` —— 它不控制
    任何一頁，而 `ready` 因此永遠不會回來。

    ★ 這一條掃的是**註冊的路徑**，不是「有沒有 register 這個字」——
      後者連壞掉的版本都會通過。
    """
    js = (ROOT / 'static' / 'js' / 'sw-register.js').read_text(encoding='utf-8')
    body = js[js.index('serviceWorker.register'):]
    assert "register('/sw.js'" in body, \
        'Service Worker 沒有從根目錄註冊 —— scope 會是那支檔案的目錄'
    assert "'/static/sw.js'" not in body, '又註冊回 /static/ 了'




def test_a_denied_device_is_told_where_to_fix_it(optin):
    """★ 「你選了不允許」之後如果不告訴他怎麼改回來，
    那顆按鈕對他就永遠是壞的 —— 我們問不了第二次。"""
    d = optin['denied_device']
    assert '設定' in d['afterLoad']['msg'], d['afterLoad']['msg']
    #  ★ 按下去也不可以再問一次（瀏覽器會直接忽略，看起來像按了沒反應）
    assert d['calls']['requestPermission'] == 0


# ══ 七、資料表要表態 ═════════════════════════════════════

def test_the_table_is_backed_up():
    """★★ 「重新訂閱就有」的完整版是「**每一個人**都要自己再按一次」，
    而沒有人會知道要去按 —— 他只會發現通知突然不來了。"""
    import backup_registry as reg
    assert 'push_subscriptions' in {t[0] for t in reg.TABLES}


# ══ 七、推播唯一的自我驗證：訂閱那一刻推一則 ＋ 測試鈕 ═══
#
#  使用者傳了一張通知列的截圖：「手機只看到這樣 沒有推播內容」。
#
#  ★★ 查下去的結果是**推播沒有壞**：那一天系統本來就沒有任何事要
#    通知他（讀經那一則他自己已經打過勾，所以刻意跳過），而前一天
#    那一則課程提醒是 19:08 發的。
#
#  真正的問題是他**沒有辦法知道它是好的**。推播是這個系統裡唯一一件
#  「沒消息」和「壞掉了」長得一模一樣的事：站內通知打開就看得到，
#  報名、簽到都有畫面，只有推播，什麼都沒發生的時候你分不出是
#  今天沒事、還是金鑰對不起來每一則都 403。

def test_subscribing_pushes_one_right_away(keyed, client):
    """★★ 按完那顆鈕之後可能好幾天都沒有任何通知（那幾天本來就沒事），
    所以**訂閱成功那一刻**是唯一一個推播一定被期待的時機 ——
    也是他唯一能確認「真的收得到」的機會。"""
    _member(client)
    with patch('routes.push.supabase'), patch('routes.push._send_one') as send:
        r = client.post('/api/push/subscribe', json=SUB)
    assert send.call_count == 1, '訂閱成功卻什麼都沒推'
    assert r.get_json().get('test_sent') is True


def test_it_only_pings_the_device_that_just_subscribed(keyed, client):
    """★ 只推**剛剛訂的那一台**，不是他所有的裝置 ——
    在電腦上按開啟卻讓他手機響，他會以為推錯人了。"""
    _member(client)
    with patch('routes.push.supabase'), patch('routes.push._send_one') as send:
        client.post('/api/push/subscribe', json=SUB)
    assert send.call_args[0][0]['endpoint'] == SUB['endpoint']


def test_a_welcome_that_cannot_be_sent_does_not_claim_it_worked(keyed, client):
    """★★ 送不出去的時候**不可以回 `test_sent: True`**。

    回了的話畫面會說「開好了」，而他從此等一個永遠不會來的通知 ——
    正是這一整節要修的那個症狀，只是換成我們自己製造的。
    """
    _member(client)
    boom = Exception('nope')
    boom.response = type('R', (), {'status_code': 403})()
    with patch('routes.push.supabase'), \
         patch('routes.push._send_one', side_effect=boom):
        r = client.post('/api/push/subscribe', json=SUB)
    d = r.get_json()
    assert r.status_code == 200, '訂閱本身已經存好了，不可以回錯誤'
    assert d['success'] is True and d['test_sent'] is False
    assert '403' in d['test_error'], '沒講出狀態碼 —— 403 幾乎一定是金鑰對不起來'




def test_the_test_endpoint_needs_a_login(client):
    """★ 沒登入就能打的話，任何人都可以叫別人的手機響。"""
    with patch('routes.push.supabase'):
        assert client.post('/api/push/test').status_code == 401


def test_the_test_push_only_reaches_my_own_devices(keyed, client):
    """★★ 這一支只准推給**自己** —— 可以指定對象的話，
    它就變成一顆「叫全教會手機響」的按鈕。"""
    _member(client)
    with patch('routes.push.supabase') as sb, patch('routes.push._send_one'):
        sb.table.return_value.select.return_value.eq.return_value\
            .execute.return_value.data = _rows(1)
        client.post('/api/push/test')
        col, val = sb.table.return_value.select.return_value.eq.call_args[0]
    assert (col, val) == ('user_id', 'u1')


def test_each_device_is_reported_separately(keyed, client):
    """★ 三台裡壞一台時只回「成功」的話，那一台從此收不到而畫面正常。"""
    _member(client)
    calls = {'n': 0}

    def flaky(row, payload, timeout=5):
        calls['n'] += 1
        if calls['n'] == 2:
            raise Exception('boom')

    with patch('routes.push.supabase') as sb, \
         patch('routes.push._send_one', side_effect=flaky):
        sb.table.return_value.select.return_value.eq.return_value\
            .execute.return_value.data = _rows(3)
        d = client.post('/api/push/test').get_json()
    assert d['devices'] == 3 and d['sent'] == 2
    assert len(d['problems']) == 1


def test_every_device_failing_is_not_reported_as_success(keyed, client):
    """★ 一台都沒送出去還說成功的話，這顆鈕就跟沒有一樣。"""
    _member(client)
    with patch('routes.push.supabase') as sb, \
         patch('routes.push._send_one', side_effect=Exception('boom')):
        sb.table.return_value.select.return_value.eq.return_value\
            .execute.return_value.data = _rows(2)
        d = client.post('/api/push/test').get_json()
    assert d['success'] is False and d['sent'] == 0


def test_having_no_device_is_a_next_step_not_an_error(keyed, client):
    """★ 「這個帳號還沒有任何裝置開啟通知」是他做得到的下一步。
    回 5xx 的話看起來像系統壞了，而他其實只要按上面那顆鈕。"""
    _member(client)
    with patch('routes.push.supabase') as sb:
        sb.table.return_value.select.return_value.eq.return_value\
            .execute.return_value.data = []
        r = client.post('/api/push/test')
    assert r.status_code == 200
    assert r.get_json()['success'] is False
    assert '裝置' in r.get_json()['error']


def test_no_keys_is_off_not_broken(client):
    """★ 沒設金鑰＝整個關掉，不是壞掉（`is_enabled` 那一段的規則）。
    回 5xx 的話瀏覽器和監控都會把一個刻意關掉的功能當成故障。"""
    _member(client)
    with patch('routes.push.supabase'):
        r = client.post('/api/push/test')
    assert r.status_code == 200 and r.get_json()['success'] is False


def test_a_dead_subscription_found_by_the_test_is_cleaned_up(keyed, client):
    """★ 測試推播撞到 404/410 時要當場清掉，並且告訴他「再開啟一次」——
    不講的話那台裝置從此收不到，而按鈕還寫著「已開啟」。"""
    _member(client)
    dead = Exception('gone')
    dead.response = type('R', (), {'status_code': 410})()
    with patch('routes.push.supabase') as sb, \
         patch('routes.push._send_one', side_effect=dead):
        sb.table.return_value.select.return_value.eq.return_value\
            .execute.return_value.data = _rows(1)
        d = client.post('/api/push/test').get_json()
        sb.table.return_value.delete.return_value.eq.assert_called()
    assert '再開啟' in d['problems'][0]


def test_the_foreground_send_waits_less_than_the_scheduler(keyed):
    """★ 人在畫面前面等 —— 排程那條路的 10 秒在這裡太久了。"""
    with patch('routes.push._send_one') as send:
        push.try_send_one({'endpoint': 'e', 'p256dh': 'p', 'auth': 'a'}, '標題')
    assert send.call_args[1]['timeout'] < 10


# ── 畫面那一半（node ＋ 假瀏覽器，真的跑一次）──────────

def test_a_welcome_that_failed_is_not_shown_as_success(optin):
    """★★ 伺服器說送不出去的時候，畫面**不可以**說開好了。"""
    msg = optin['welcome_failed']['afterClick']['msg']
    assert '✅' not in msg, '送不出去卻打了勾'
    assert '403' in msg, '沒把原因講出來'


def test_a_successful_welcome_tells_him_to_go_look(optin):
    """★ 反過來也要驗，不然「永遠不說成功」也會是綠的。
    而且要叫他**去看通知列** —— 推播跳出來的地方不在這一頁上。"""
    msg = optin['fresh_device']['afterClick']['msg']
    assert '測試通知' in msg and '通知列' in msg


def test_the_test_button_only_shows_on_a_device_that_is_on(optin):
    """★ 還沒開啟就按的話一定失敗，而「按了說沒有裝置」看起來像壞掉。"""
    assert optin['already_subscribed']['afterLoad']['testShown'] is True
    assert optin['fresh_device']['afterLoad']['testShown'] is False
    assert optin['ios_safari_tab']['afterLoad']['testShown'] is False


def test_the_test_button_goes_away_when_notifications_are_turned_off(optin):
    """★★ 這一條才是真的在守隱藏那一半。

    上面那條（「只有開啟的那台才畫得出來」）會靠模板裡的
    `style="display:none"` **自己通過** —— 把 JS 裡隱藏那一行挖掉，
    它照樣是綠的（mutation 當場抓到）。關掉之後那顆鈕還在的話，
    按下去會說「沒有任何裝置」，而他剛剛才親手關掉。
    """
    assert optin['turned_off']['afterLoad']['testShown'] is True
    assert optin['turned_off']['afterClick']['testShown'] is False


def test_the_test_button_appears_as_soon_as_it_is_turned_on(optin):
    """★ 開好之後不用重整就看得到 —— 要重整才出現的話，
    他在最想驗證的那一刻剛好沒有那顆鈕。"""
    assert optin['fresh_device']['afterClick']['testShown'] is True


def test_pressing_test_says_how_many_devices(optin):
    """★★ 他可能在**電腦上**按，而響的是手機。
    只說「送出了」的話他會盯著眼前這台等。"""
    assert '2 台' in optin['test_ok']['afterTest']['msg']


def test_a_failed_test_says_why(optin):
    """★ 「傳送失敗」對想查的人等於沒講。403 幾乎一定是金鑰對不起來。"""
    msg = optin['test_failed']['afterTest']['msg']
    assert '403' in msg and '已經送出' not in msg


def test_the_test_button_comes_back_after_a_failure(optin):
    """★ 卡在 disabled 的話他連再試一次都做不到。"""
    assert optin['test_failed']['afterTest']['disabled'] is False


# ══ 真的 app（子行程）：SW 從根目錄送出、有金鑰才畫按鈕 ═══════

def _real_app(extra_env):
    import os
    import socket
    import subprocess
    import sys
    import time
    with socket.socket() as so:
        so.bind(('127.0.0.1', 0))
        port = so.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith('VAPID')}
    env.update(extra_env)
    srv = subprocess.Popen([sys.executable, str(ROOT / 'tests' / 'editor_server.py'), str(port)], cwd=str(ROOT),
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    assert srv.stdout.readline().strip() == 'READY'
    time.sleep(0.3)
    return srv, f'http://127.0.0.1:{port}'


def test_the_real_app_serves_the_service_worker_from_the_root():
    """★ 註冊 `/sw.js` 而伺服器沒有這條路由，註冊會 404，而 sw-register.js 把錯誤吃掉了（刻意的）——
    那是完全沒有聲音的壞法。"""
    import urllib.request
    srv, base = _real_app({})
    try:
        r = urllib.request.urlopen(base + '/sw.js')
        assert r.status == 200 and 'javascript' in r.headers['Content-Type']
        assert r.headers['Service-Worker-Allowed'] == '/'
        assert 'no-cache' in r.headers['Cache-Control']
        assert "addEventListener('push'" in r.read().decode()
    finally:
        srv.kill()


def test_the_button_is_drawn_only_when_keys_are_set():
    """★★ 畫一顆按了一定失敗的按鈕比不畫更糟。真的 render 一次，問畫面上有沒有那顆鈕
    （掃模板原始碼會被下面另一個 `{% if push_enabled %}` 騙過）。"""
    import urllib.request
    srv, base = _real_app({})
    try:
        off = urllib.request.urlopen(base + '/profile').read().decode()
    finally:
        srv.kill()
    srv, base = _real_app({'VAPID_PUBLIC_KEY': 'pub', 'VAPID_PRIVATE_KEY': 'priv'})
    try:
        on = urllib.request.urlopen(base + '/profile').read().decode()
    finally:
        srv.kill()
    assert 'id="push-optin"' not in off and 'push-optin.js' not in off
    assert 'id="push-optin"' in on and 'id="push-test"' in on
    assert 'sw-register.js' in on and 'push-optin.js' in on
