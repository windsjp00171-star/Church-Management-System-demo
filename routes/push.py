# 推播（Web Push / VAPID）
#
# 使用者：「PWA未來都還會繼續安裝 現在先把推播做好應該不吃虧」
#
# ## ★★ 為什麼是 Web Push 不是 LINE
#
# 站內通知已經發過 1300 多則，但**人要自己打開網站才看得到** ——
# 而提醒的價值幾乎全部取決於「他有沒有看到」。
#
# - LINE Notify **2025 年 3 月已經停掉**
# - LINE 官方帳號的推播有免費額度但很低，119 個人群發幾次就超過，而
#   **使用者說過不花錢**；而且那個帳號是他個人的小秘書，不該借來用
# - Web Push（VAPID）**免費、不用申請任何服務、不經過第三方帳號**，
#   金鑰自己產。這是唯一符合條件的路。
#
# ## ★★ 它的天花板是「有多少人裝了 PWA 並按了允許」
#
# iOS 只有**加到主畫面的 PWA** 收得到推播（Safari 分頁收不到），
# 而且使用者要按「允許通知」。所以這個功能的覆蓋率**不是我們決定的**。
#
# ★ 但那個數字**不用另外做統計** —— `push_subscriptions` 的列數就是它。
#   訂閱得到幾個人，就是推播送得到幾個人。
#
# ## ★★ 推播是「錦上添花」，永遠不可以是唯一的路
#
# 每一則推播都**同時**是一則站內通知（`notifications`）。推播失敗、
# 沒訂閱、關掉權限、iOS 沒裝 PWA —— 那個人仍然看得到那則通知，
# 只是要自己打開網站。反過來做的話（只推播不留站內），
# 沒訂閱的人**什麼都沒有**，而系統看起來一切正常。

import json
import threading
from collections import deque, OrderedDict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, session

from config import Config
from db import supabase

push_bp = Blueprint('push', __name__)

TABLE = 'push_subscriptions'


# ── 哪些通知會跳到手機上 ──────────────────────────────
#
# ★★ 這張表是**使用者一項一項圈的**（2026-09-12），不是我排的。
#   我建議拿掉「報名成功」（他剛按完送出、人就盯著畫面），他決定留著。
#
# ★ 為什麼用 `type` 當開關：18 種通知裡他要拿掉的四個
#   （新的福音詢問、代禱被移除、報名已取消、福音關懷指派）
#   剛好**全落在 `info` 和 `gospel`**，一個都沒有跨界 ——
#   所以不用為了這件事多一個欄位。
#
# ★★ 為什麼是註冊表不是一個 if：兩個方向都會安靜地出事。
#   ① `info` **是 `create_notification` 的預設值** —— 以後誰加通知忘了寫
#      `type`，就會靜靜地不推。方向是安全的（站內一定有），但不可以是意外。
#   ② 反面更危險：`announcement` 是「推給全體」那一組，隨手拿來用
#      就是**一次吵 119 支手機，而且收不回來**。
#
# 新增一個 type 沒登記在這兩張表裡，`tests/test_push_scope.py` 會紅。

PUSH_TYPES = {
    'reminder':         '候補遞補成功、教會行事快到了、個人行程提醒',
    'announcement':     '全體廣播、教會行事通知全體、即將開課符合資格',
    'event_reminder':   '活動通知（同工手動發給報名者，例如場地異動）',
    'course_reminder':  '課程通知（同工手動發給學員）',
    'enrollment':       '報名成功（活動／課程）'
                        ' —— ★ 我建議不推，使用者決定要推；'
                        '以後真的有人嫌吵，這一個是第一個該看的',
    'reading':          '聖經速讀每天一則（他自己的下一格）',
}

#  不推的，每一種都要寫理由 —— 留白的話下一個人分不出
#  「刻意不推」和「忘了登記」。
NO_PUSH = {
    #  ★★ 2026-09-30 從 `PUSH_TYPES` 移過來。使用者：
    #    **「費用催繳不要做 / 這個在教會內部很敏感」**。
    #    ★ 他 2026-09-12 逐項圈選時是**留著要推**的 —— 這是改決定，
    #      兩個都記著。現在**沒有任何地方會產生這種通知**
    #      （`reminders` 那兩支已移除），這一行是第二層：
    #      萬一以後有人手動發，它也不會跳到 119 支手機上。
    'payment_reminder':
              '費用待繳 —— 使用者要求不主動催繳（教會內部很敏感）',
    'info':   '目前只有「代禱事項已被移除」和「報名已取消（通知另一方）」'
              '——★ 而且它是 create_notification 的**預設值**，'
              '所以「忘了寫 type」會落在這裡，不推是安全的方向',
    'attendance': '同工請假／加班的審核通知，收件者是管理員 —— 使用者圈的範圍裡沒有',
    'calendar_reminder': '教會行事提醒目前只在他打開網站時由前台產生（沒有排程），'
                         '推出去只會是「他正在看網站、手機卻響」',
    'cell_group': '加入牧養小組的申請與確認，收件者是小組長／管理員 —— 使用者圈的範圍裡沒有',
    'gospel': '「新的福音詢問」和「福音關懷指派」，收件者是同工／管理員'
              '—— 使用者圈的範圍裡沒有這兩個',
}


def should_push(type_):
    """這一種通知要不要跳到手機上。

    ★ **不認得的一律不推**。反過來（預設推）的話，以後新加一種通知
      會在沒有人決定過的情況下直接跳到 119 支手機上 ——
      而漏推的代價只是「他要自己打開網站看」，站內那則一定還在。
    """
    return type_ in PUSH_TYPES

#  推播服務回這幾個狀態 = 這個訂閱死了，要刪掉。
#  ★ 不刪的話每次推播都會對一個永遠失敗的 endpoint 重試，
#    而失敗是安靜的 —— 那張表會慢慢長滿死掉的裝置。
DEAD_STATUSES = (404, 410)


def is_enabled():
    """有沒有設金鑰。**沒設就是整個關掉，不是壞掉。**

    ★ 沒設時前端不畫「開啟通知」那顆鈕 —— 畫一顆按了一定失敗的按鈕
      比不畫更糟（同工分不出是自己手機的問題還是系統的問題）。
    """
    return bool(Config.VAPID_PUBLIC_KEY and Config.VAPID_PRIVATE_KEY)


# ── 訂閱 ────────────────────────────────────────────────

@push_bp.route('/api/push/key')
def public_key():
    """瀏覽器訂閱時要用的公鑰。沒設定就回 enabled: false。"""
    return jsonify({'enabled': is_enabled(), 'key': Config.VAPID_PUBLIC_KEY})


@push_bp.route('/api/push/subscribe', methods=['POST'])
def subscribe():
    """存一筆訂閱。同一台裝置重訂會蓋掉舊的（endpoint 是唯一鍵）。"""
    uid = session.get('user_id')
    if not uid:
        return jsonify({'error': '請先登入'}), 401
    data = request.get_json(silent=True) or {}
    endpoint = (data.get('endpoint') or '').strip()
    keys = data.get('keys') or {}
    p256dh = (keys.get('p256dh') or '').strip()
    auth = (keys.get('auth') or '').strip()
    #  ★ 三個都要有才存得下去。少一個的話推播會在**送出的那一刻**才失敗，
    #    而那時候沒有人在看 —— 現在擋掉，訂閱的人當場就知道沒成功。
    if not (endpoint and p256dh and auth):
        return jsonify({'error': '訂閱資料不完整'}), 400
    try:
        supabase.table(TABLE).upsert({
            'user_id': uid,
            'endpoint': endpoint,
            'p256dh': p256dh,
            'auth': auth,
            #  只留很短的一段，用來讓他在「我有哪些裝置」認得出是哪一台。
            #  ★ 不存完整的 UA —— 那是裝置指紋，而我們只需要「哪一台」。
            'user_agent': (request.headers.get('User-Agent') or '')[:120],
        }, on_conflict='endpoint').execute()
    except Exception as e:
        return jsonify({'error': f'存不進去（{type(e).__name__}）'}), 500

    #  ★★ 存好之後**立刻推一則**，而且同步等結果回報給他。
    #    按完那顆鈕之後可能好幾天都不會有任何一則通知（那幾天本來
    #    就沒事），所以這一則是他唯一能確認「真的收得到」的機會。
    #
    #  ★ 只推**剛剛訂的這一台**，不是他所有的裝置 —— 在電腦上按開啟
    #    卻讓他手機響，他會以為推錯人了。
    #
    #  ★ 這一則失敗**不可以讓訂閱失敗**：訂閱已經存好了，而且下一則
    #    真的通知可能就送得出去（推播服務暫時掛掉）。所以回 200，
    #    只是照實把 `test_sent` 講出來。
    ok, why = try_send_one(
        {'endpoint': endpoint, 'p256dh': p256dh, 'auth': auth},
        WELCOME_TITLE, WELCOME_BODY, '/profile')
    return jsonify({'success': True, 'test_sent': ok, 'test_error': why})


@push_bp.route('/api/push/unsubscribe', methods=['POST'])
def unsubscribe():
    """退訂這台裝置。

    ★ **不需要登入也要能退**：他可能已經登出了，但瀏覽器還握著訂閱。
      要求登入的話，那台裝置會永遠收到推播而他關不掉。
    """
    endpoint = ((request.get_json(silent=True) or {}).get('endpoint') or '').strip()
    if not endpoint:
        return jsonify({'error': '缺少 endpoint'}), 400
    try:
        supabase.table(TABLE).delete().eq('endpoint', endpoint).execute()
    except Exception:
        pass                      # 刪不掉也不要讓他卡在「關不掉通知」
    return jsonify({'success': True})


@push_bp.route('/api/push/test', methods=['POST'])
def test_push():
    """傳一則測試通知給**我自己的**裝置，同步等結果，照實回報。

    ★★ 這一支存在的理由是：推播是這個系統裡唯一一件
      **「沒消息」和「壞掉了」長得一模一樣**的事。站內通知看得到、
      報名看得到、簽到看得到 —— 只有推播，什麼都沒發生的時候
      你分不出是今天沒事、還是它三個星期前就不動了。

    ★ 只推給**自己**（`session['user_id']`），所以最壞的情況是他吵自己，
      不需要速率限制。改成可以指定對象的話，這就變成一顆
      「叫全教會手機響」的按鈕。

    ★ 同步跑，不丟背景執行緒 —— 人就在畫面前面等這個答案，
      而「已送出」不等於「送得出去」。

    ★ 一台失敗不影響其他台，而且**每一台各自回報** ——
      三台裡壞一台時只回「成功」的話，那台從此收不到而畫面正常。
    """
    uid = session.get('user_id')
    if not uid:
        return jsonify({'error': '請先登入'}), 401
    if not is_enabled():
        #  ★ 回 200 不是 5xx：**沒設金鑰是「整個關掉」，不是「壞掉」**
        #    （`is_enabled` 那一段的規則）。回 5xx 的話瀏覽器和監控
        #    都會把一個刻意關掉的功能當成故障。
        return jsonify({'success': False, 'error': '系統還沒設定推播金鑰'})
    try:
        rows = supabase.table(TABLE).select('*').eq('user_id', uid)\
            .execute().data or []
    except Exception as e:                             # noqa: BLE001
        return jsonify({'error': f'查不到你的裝置（{type(e).__name__}）'}), 500
    if not rows:
        #  ★ 「沒有裝置」不是錯誤，是一個他做得到的下一步。
        return jsonify({'success': False, 'devices': 0,
                        'error': '這個帳號還沒有任何裝置開啟通知'})

    sent, problems = 0, []
    for row in rows:
        ok, why = try_send_one(row, TEST_TITLE, TEST_BODY, '/profile')
        if ok:
            sent += 1
        else:
            problems.append(why)
    return jsonify({'success': sent > 0, 'devices': len(rows),
                    'sent': sent, 'problems': problems})


# ── 送出 ────────────────────────────────────────────────

def _payload(title, body, link):
    return json.dumps({'title': title or '通知', 'body': body or '',
                       'url': link or '/'}, ensure_ascii=False)


TAIPEI_TZ = timezone(timedelta(hours=8))

#  ── 最近的推播：把「安靜地失敗」變成看得見的東西 ──────────
#
#  ★★ 使用者：「推播測試鈕 有正確推播 但是沒有收到過其他的東西」。
#
#    測試鈕是**同步**送的，所以它送不出去的時候當場就講得出原因。
#    其他每一則都走背景執行緒，而背景執行緒裡的例外
#    `_send_quietly` 一律吃掉 —— 那是對的（推播不可以拖垮報名），
#    但代價是**整批全滅和整批成功長得一模一樣**。
#
#  ★ 所以留一份「最近幾批推了什麼、幾台、成功幾台、失敗原因」。
#    ★ 放**行程記憶體**不是資料表：這是拿來查問題的，不是紀錄；
#      而且加一張表要先跟使用者說明（這個專案的規矩）。
#      重啟就沒了 —— 對「現在到底有沒有在動」這個問題夠用。
_LOG_MAX = 60
_log = deque(maxlen=_LOG_MAX)
_log_lock = threading.Lock()


def record_attempt(title, devices, sent, problems):
    with _log_lock:
        _log.appendleft({
            'at': datetime.now(TAIPEI_TZ).isoformat(timespec='seconds'),
            'title': (title or '')[:60],
            'devices': devices,
            'sent': sent,
            #  ★ 只留前幾個原因：三十台同一個錯誤時，看一個就夠了，
            #    而全部留著會把這一份變成沒有人讀得完的東西。
            'problems': list(OrderedDict.fromkeys(problems))[:5],
        })


def recent_attempts(n=20):
    with _log_lock:
        return list(_log)[:n]


def _subscriptions_for(user_ids, sb=None):
    """一次查完**整批人**的訂閱。回 `{user_id: [row, …]}`。

    ★★ 查不到回 `None` 不是 `{}` —— 「資料庫沒回話」和「沒有人訂閱」
      要分得出來。混在一起的話，每一次抖動都會被記成
      「大家都沒訂閱」，而那看起來就像推播功能沒人用。
    """
    ids = [u for u in dict.fromkeys(user_ids) if u]
    if not ids:
        return {}
    sb = sb or supabase
    out = {}
    #  ★ PostgREST 的 `in_` 會塞進網址列，一次太多人會超過長度上限
    #    （Procfile 的 `--limit-request-line` 管的是進來的方向，
    #    出去的這一邊是 Supabase 那頭在管）。分批問。
    for i in range(0, len(ids), 100):
        try:
            rows = sb.table(TABLE).select('*')\
                .in_('user_id', ids[i:i + 100]).execute().data or []
        except Exception:                              # noqa: BLE001
            return None
        for r in rows:
            out.setdefault(r.get('user_id'), []).append(r)
    return out


def send_many(jobs, sb=None):
    """一批**各自不同**的推播。`jobs`: `[(user_ids, title, body, link), …]`

    ★★ 這一支存在的理由是「一次查詢、一條執行緒」。原本
      `batch_notify_rows` 是**逐則**呼叫 `send_in_background` 的，
      於是速讀那一則（114 個人）會在免費方案上瞬間開
      **114 條執行緒、114 次資料庫查詢** —— 而
      `send_in_background` 自己的說明裡就寫著不可以這樣做
      （「119 條執行緒會把免費方案的記憶體吃掉」）。
      失敗全部被 `_send_quietly` 吃掉，所以症狀是
      **站內通知全部都在、手機一則都沒響**。

    回 `(送出幾則, 清掉幾個死訂閱)`。
    """
    if not is_enabled() or not jobs:
        return (0, 0)
    sb = sb or supabase
    by_user = _subscriptions_for(
        [u for uids, *_ in jobs for u in (uids or ())], sb=sb)
    if by_user is None:
        record_attempt(jobs[0][1] if jobs else '', 0, 0, ['查不到訂閱名單'])
        return (0, 0)

    sent = dead = 0
    for uids, title, body, link in jobs:
        payload = _payload(title, body, link)
        n, problems = 0, []
        rows = [r for u in (uids or ()) for r in by_user.get(u, ())]
        for row in rows:
            try:
                _send_one(row, payload)
                n += 1
            except Exception as e:                     # noqa: BLE001
                if _is_dead(e):
                    _forget(sb, row.get('endpoint'))
                    dead += 1
                    problems.append('訂閱已失效，已清掉')
                else:
                    #  其他錯誤（網路、推播服務暫時掛掉）什麼都不做 ——
                    #  下一則通知會再試一次。
                    code = getattr(getattr(e, 'response', None),
                                   'status_code', None)
                    problems.append(f'推播服務回 {code}' if code
                                    else f'送不出去（{type(e).__name__}）')
        sent += n
        record_attempt(title, len(rows), n, problems)
    return (sent, dead)


def send_to(user_ids, title, body='', link='/', sb=None):
    """推播給這幾個人（他們所有的裝置）。回 `(送出幾則, 清掉幾個死訂閱)`。

    ★★ **整支包起來，永遠不要往上炸**。這一支是掛在
      `notifications.batch_notify` 後面的 —— 推播失敗不可以讓
      「發通知」這件事失敗，更不可以讓報名、簽到那些主要流程失敗。

    ★ 推播**不是唯一的路**：呼叫端一定已經寫了站內通知。
      所以這裡全軍覆沒也只是「沒有人收到手機通知」，不是「沒有人收到通知」。

    ★ 實作就是 `send_many` 的一組 —— 兩份實作的話，
      「一次查詢」那個修正只會蓋到其中一條路。
    """
    if not user_ids:
        return (0, 0)
    return send_many([(list(user_ids), title, body, link)], sb=sb)


def send_in_background(user_ids, title, body='', link='/'):
    """把推播丟到背景執行緒，不讓按下去的那個人等。

    ★★ **這一步不是優化，是修一個我上一版寫壞的地方。**

      全體廣播是 119 個人，而每一台裝置都是一個對外的 HTTPS 請求
      （`_send_one` 的 `timeout=10`）。同步跑的話，同工按下「發送公告」
      之後那個請求要等**二十幾秒**才回來 —— 他會以為當掉了，
      然後再按一次，於是**全教會收到兩則一模一樣的公告**。

      報名那條路更不能等：`create_notification` 就在送出報名的流程裡。

    ★ 推播**本來就是射後不理**：站內通知已經寫好了，所以這裡整支失敗
      （執行緒被重啟砍掉、網路斷線）的代價只是「手機沒響」，
      不是「沒收到通知」。這也是它可以安心丟到背景的理由。

    ★★ 只開**一條**執行緒跑整個迴圈，不是一人一條 ——
      119 條執行緒會把免費方案的記憶體吃掉。
      **這條規則寫在這裡，而呼叫端違反了它一整年**：
      `batch_notify_rows` 逐則呼叫這一支 ＝ 一人一條。
      現在整批走 `send_many_in_background`。
    """
    if not user_ids:
        return False
    return send_many_in_background([(list(user_ids), title, body, link)])


def send_many_in_background(jobs):
    """整批推播，**一條執行緒**跑完。"""
    jobs = [(list(uids), title, body, link)
            for uids, title, body, link in (jobs or []) if uids]
    if not is_enabled() or not jobs:
        return False
    threading.Thread(target=_send_quietly, args=(jobs,), daemon=True).start()
    return True


def _send_quietly(jobs):
    """背景執行緒的進入點。★ 例外一定要在這裡吃掉 ——
    執行緒裡沒有人接的例外只會印在 log 上，而沒有人在看那個 log。

    ★ 但**吃掉不等於不留痕跡**：`send_many` 會把每一批的結果記進
      `recent_attempts()`，不然整批全滅和整批成功長得一模一樣。
    """
    try:
        send_many(jobs)
    except Exception as e:                             # noqa: BLE001
        try:
            record_attempt(jobs[0][1] if jobs else '', 0, 0,
                           [f'整批失敗（{type(e).__name__}）'])
        except Exception:                              # noqa: BLE001
            pass


def _send_one(row, payload, timeout=10):
    from pywebpush import webpush
    webpush(
        subscription_info={
            'endpoint': row['endpoint'],
            'keys': {'p256dh': row['p256dh'], 'auth': row['auth']},
        },
        data=payload,
        vapid_private_key=Config.VAPID_PRIVATE_KEY,
        vapid_claims={'sub': Config.VAPID_SUBJECT},
        timeout=timeout,
    )


#  ★ 訂閱成功那一刻推的那一則，以及「傳一則測試通知」推的那一則。
#
#  ★★ 這兩則是這個功能**唯一的自我驗證**。使用者回報：
#    「手機只看到這樣 沒有推播內容」—— 那天他的裝置其實完全正常，
#    只是系統那一天沒有任何事要通知他（讀經那一則他自己已經打過勾，
#    所以刻意跳過）。問題不在推播壞了，在於**他沒有辦法知道它是好的**：
#    「設定成功但今天沒事」和「金鑰錯了每一則都 403」
#    在畫面上長得一模一樣，而後者要等到真的有事要通知那天才會發現。
WELCOME_TITLE = '🔔 手機通知開好了'
WELCOME_BODY = '以後公告、活動通知和讀經提醒會直接跳到這裡。'

TEST_TITLE = '🔔 測試通知'
TEST_BODY = '看到這一則，就表示這台裝置收得到。'

#  人在畫面前面等，所以比排程那條路的 10 秒短。
FOREGROUND_TIMEOUT = 5


def try_send_one(row, title, body='', link='/', sb=None,
                 timeout=FOREGROUND_TIMEOUT):
    """送一則給**一台**裝置，同步等結果，然後**照實**回報。

    回 `(成功了嗎, 說明)`。

    ★ 跟 `send_to` 的差別就在「照實」兩個字：那一支是射後不理的
      （背景執行緒、失敗吃掉），因為站內通知一定還在。這一支是
      **人按了按鈕在等答案**，所以失敗一定要講出來 ——
      這裡回 True 而其實沒送出去的話，他會以為開好了，
      然後等一個永遠不會來的通知。

    ★ 錯誤訊息帶**狀態碼**：403 幾乎一定是金鑰對不起來（換過 VAPID
      金鑰），而那個原因沒講出來的話沒有人查得到。
    """
    if not is_enabled():
        return (False, '系統還沒設定推播金鑰')
    try:
        _send_one(row, _payload(title, body, link), timeout=timeout)
        return (True, '')
    except Exception as e:                             # noqa: BLE001
        if _is_dead(e):
            #  ★ 死掉的訂閱當場清掉（跟 `send_to` 同一條規則），
            #    而且要告訴他「再開一次」—— 不講的話那台裝置從此收不到，
            #    而畫面上那顆鈕還寫著「已開啟」。
            _forget(sb or supabase, row.get('endpoint'))
            return (False, '這個訂閱已經失效了（瀏覽器清過網站資料，'
                           '或是重裝過），請再開啟一次')
        code = getattr(getattr(e, 'response', None), 'status_code', None)
        if code:
            return (False, f'推播服務回 {code}')
        return (False, f'送不出去（{type(e).__name__}）')


def _is_dead(exc):
    """這個錯誤代表「這個訂閱已經沒用了」嗎。

    ★ 用狀態碼判斷，不是用字串比對訊息 ——
      訊息會隨版本改，而改掉之後我們會**安靜地**停止清理死訂閱。
    """
    resp = getattr(exc, 'response', None)
    return getattr(resp, 'status_code', None) in DEAD_STATUSES


def _forget(sb, endpoint):
    if not endpoint:
        return
    try:
        sb.table(TABLE).delete().eq('endpoint', endpoint).execute()
    except Exception:
        pass


#  ── 覆蓋率：這件事的天花板看得見 ──────────
#
#  ★★ 「覆蓋率不用另外做統計 —— `push_subscriptions` 的列數就是它」，
#    這句話是對的，但那個數字**沒有任何一個畫面顯示它** ——
#    每次要看都得有人進資料庫撈。這正好是這個專案記過的
#    「沒有入口的功能等於不存在」，發生在覆蓋率這個數字本身上。
#
#  ★ 它同時是「他把通知關掉了」**唯一**的訊號：我們看不到誰關掉，
#    但覆蓋率往下掉就是那件事在發生。

#  ★★ 分類看 **User-Agent**，不看 endpoint。
#    FCM 的網址（`fcm.googleapis.com`）**電腦版 Chrome 也在用** ——
#    只看 endpoint 的話桌機會被算成 Android，而
#    **iOS 的覆蓋率是這件事最重要的數字**（iPhone 沒裝 PWA 就永遠
#    收不到）。我自己就因為只看 endpoint 而跟使用者講錯過一次。
DEVICE_RULES = (
    ('iPhone / iPad', ('iphone', 'ipad', 'ipod')),
    ('Android', ('android',)),
)


def device_label(user_agent, endpoint=''):
    """這一台是什麼裝置。認不出來回「其他／電腦」。"""
    ua = (user_agent or '').lower()
    for label, needles in DEVICE_RULES:
        if any(n in ua for n in needles):
            return label
    #  ★ 認不出來不要猜一個手機 —— 猜錯的代價是
    #    iOS 那一格的數字是假的，而那正是我們要用來做判斷的那一格。
    return '其他／電腦'


def coverage(rows, members=None, now=None, days=7):
    """推播覆蓋率。`rows` 是 `push_subscriptions` 撈回來的列。

    回 `{people, devices, members, rate, by_device, recent, since}`。

    ★ `members` 是 `None`（撈不到會友人數）時 `rate` 也回 `None` ——
      **查不到 ≠ 0%**。印成 0% 的話同工會以為沒有人開，
      而他會據此做決定。
    """
    now = now or datetime.now(TAIPEI_TZ)
    since = (now - timedelta(days=days)).isoformat()
    people, by_device, recent = set(), {}, 0
    for r in rows or ():
        if r.get('user_id'):
            people.add(r['user_id'])
        label = device_label(r.get('user_agent'), r.get('endpoint'))
        by_device[label] = by_device.get(label, 0) + 1
        if (r.get('created_at') or '') >= since:      # utc-ok: 兩邊都是帶時區的 ISO
            recent += 1
    order = [lbl for lbl, _ in DEVICE_RULES] + ['其他／電腦']
    return {
        'people': len(people),
        'devices': len(rows or ()),
        'members': members,
        'rate': (round(len(people) * 100 / members) if members else None),
        'by_device': [(lbl, by_device[lbl]) for lbl in order if lbl in by_device],
        'recent': recent,
        'days': days,
    }


def device_count(user_id, sb=None):
    """他有幾台裝置訂閱了 —— 畫面上用來說「這台已經開啟」。"""
    try:
        rows = (sb or supabase).table(TABLE).select('id')\
            .eq('user_id', user_id).execute().data or []
        return len(rows)
    except Exception:
        return 0
