"""PWA 續登失敗：**三種原因要分得開，而且要留下痕跡**

使用者回報：「然後PWA會偶發性卡登入」。

## 為什麼原本查不動

`load_user_for_pwa` 的 `except Exception: return None` 把兩件事壓成一件：

    Supabase 抖了一下（我們的問題）   ─┐
                                      ├─→ 回 None ─→ 不給登入 ─→ LINE 登入頁
    這個帳號被停用（本來就不該登入）  ─┘

而 LINE 那一頁在 PWA 的獨立 cookie 容器裡**要他輸入註冊 email 和密碼**
（見 `routes/pwa_session.py` 開頭）—— 幾乎沒有人記得那組。

★★ 更糟的是**整件事沒有任何記錄**：他回報的時候，`audit_logs` 裡
   60 天內一筆跟登入有關的都沒有。分不出是「偶爾抖一下」還是
   「某個人的 token 永遠過期」，而這兩件事的修法完全不同。

## 這一份守的是「分得開」和「留得下」

不是「PWA 一定登得進去」—— 那件事要一支真的 iPhone。
"""
from unittest.mock import patch

import pytest

from routes import pwa_session as P


# ══ 一、三種原因是三個不同的值 ═══════════════════════════

def test_the_three_reasons_are_distinct():
    """★ 壓成一種的話，後台那份記錄就回答不了「要不要去修」。"""
    assert len({P.BAD_TOKEN, P.NOT_ALLOWED, P.LOAD_FAILED}) == 3


def _exchange(app_secret='s3cret', load_user=None, token='tok', verify=True):
    """跑一次兌換，回 [(why, user_id), …]。"""
    from flask import Flask
    app = Flask(__name__)
    app.secret_key = app_secret
    seen, logged_in = [], []
    P.init_pwa_session(
        app,
        load_user=load_user or (lambda uid: {'id': uid}),
        on_login=logged_in.append,
        on_problem=lambda why, uid: seen.append((why, uid)),
    )

    @app.route('/')
    def home():
        return 'ok'

    real = P.verify_token
    with patch.object(P, 'verify_token',
                      (lambda *a, **k: 'u-1') if verify else (lambda *a, **k: None)):
        app.test_client().get(f'/?{P.DEFAULT_PARAM}={token}')
    assert P.verify_token is real
    return seen, logged_in


# ══ 二、★★ 主線：資料庫抖了 ≠ 這個人被停用 ═══════════════

def test_a_database_hiccup_is_not_read_as_a_blocked_account():
    """★★ 這就是「偶發性卡登入」的形狀。

    我們自己的問題，而他看到的是「請輸入 LINE 註冊 email 與密碼」。
    """
    def boom(uid):
        raise RuntimeError('Supabase 抖了一下')

    seen, logged_in = _exchange(load_user=boom)
    assert logged_in == []
    assert seen == [(P.LOAD_FAILED, 'u-1')], f'分類錯了：{seen}'


def test_a_real_denial_still_says_not_allowed():
    """★ 對照組：查無此人／已停用**本來就不該登入**，那不是故障。

    跟上面那條回同一個值的話，後台那份記錄會把
    「資料庫今天不穩」和「有人拿著被停用的帳號在敲」混成一堆。
    """
    seen, logged_in = _exchange(load_user=lambda uid: None)
    assert logged_in == []
    assert seen == [(P.NOT_ALLOWED, 'u-1')]


def test_a_stale_token_says_bad_token():
    """★ manifest 舊了／SECRET_KEY 換過 —— 重新登入一次就好，不用查。"""
    seen, logged_in = _exchange(verify=False)
    assert logged_in == []
    assert seen and seen[0][0] == P.BAD_TOKEN


def test_a_good_token_logs_in_and_reports_nothing():
    """★ 成功的時候**不可以**也叫一次 `on_problem` ——
    那份記錄會被成功的次數淹掉，而它存在的理由就是找出失敗。"""
    seen, logged_in = _exchange()
    assert seen == []
    assert logged_in == [{'id': 'u-1'}]


# ══ 三、記錄失敗不可以讓登入失敗 ═══════════════════════════

def test_a_broken_recorder_does_not_break_the_exchange():
    """★ `on_problem` 自己爆掉時，兌換那一段照樣要走完。

    統計壞掉不可以讓人進不來 —— 跟 `module_views` 掛在
    `after_request` 整支包 try 是同一條。
    """
    from flask import Flask
    app = Flask(__name__)
    app.secret_key = 's3cret'
    logged_in = []

    def explode(why, uid):
        raise RuntimeError('記錄壞了')

    P.init_pwa_session(app, load_user=lambda uid: {'id': uid},
                       on_login=logged_in.append, on_problem=explode)

    @app.route('/')
    def home():
        return 'ok'

    with patch.object(P, 'verify_token', lambda *a, **k: None):
        r = app.test_client().get(f'/?{P.DEFAULT_PARAM}=tok')
    assert r.status_code in (200, 302), '記錄壞掉把整個請求弄掛了'


def test_on_problem_is_optional():
    """★ 這個模組是要複製到別的專案的（`packages/line-pwa-kit`）——
    不傳 `on_problem` 也要能跑。"""
    from flask import Flask
    app = Flask(__name__)
    app.secret_key = 's3cret'
    P.init_pwa_session(app, load_user=lambda uid: {'id': uid},
                       on_login=lambda u: None)

    @app.route('/')
    def home():
        return 'ok'

    with patch.object(P, 'verify_token', lambda *a, **k: None):
        assert app.test_client().get(f'/?{P.DEFAULT_PARAM}=tok').status_code in (200, 302)


# ══ 四、載入端：抖一下要重試，停用要照實回 None ═════════════

def _fake_users(behaviours):
    """`supabase` 替身：`behaviours` 是每一次 execute 要做什麼。"""
    calls = []

    class Q:
        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            b = behaviours[min(len(calls), len(behaviours) - 1)]
            calls.append(b)
            if isinstance(b, Exception):
                raise b
            return type('R', (), {'data': b})()

    class SB:
        def table(self, name):
            return Q()

    return SB(), calls


@pytest.fixture(autouse=True)
def _db(request):
    if 'fake_db' in request.fixturenames:
        return
    if request.function.__name__ in _NEEDS_DB:
        request.getfixturevalue('fake_db')


_NEEDS_DB = {'test_one_hiccup_does_not_cost_him_the_login','test_a_database_that_stays_down_raises_instead_of_denying','test_a_denial_returns_none_without_retrying','test_the_record_carries_who_it_was_and_why'}


def test_one_hiccup_does_not_cost_him_the_login():
    """★ 一次抖動的代價是「他被要求輸入一組他不記得的密碼」。

    這條路一次 PWA 啟動只走一次（不是每個請求），重試一次很划算。
    """
    from routes import auth
    sb, calls = _fake_users([RuntimeError('抖'), [{'id': 'u-1'}]])
    with patch.object(auth, 'supabase', sb):
        assert auth.load_user_for_pwa('u-1') == {'id': 'u-1'}
    assert len(calls) == 2, '第一次失敗之後沒有再試一次'


def test_a_database_that_stays_down_raises_instead_of_denying():
    """★★ 這是整份的核心：**撐不住就丟例外，不要回 None**。

    回 None 的話，`pwa_session` 會把它當成「這個人不該登入」。
    """
    from routes import auth
    sb, _ = _fake_users([RuntimeError('一直掛'), RuntimeError('一直掛')])
    with patch.object(auth, 'supabase', sb):
        with pytest.raises(Exception):
            auth.load_user_for_pwa('u-1')


@pytest.mark.parametrize('rows', [[], [{'id': 'u-1', 'is_blocked': True}]])
def test_a_denial_returns_none_without_retrying(rows):
    """★ 查無此人／已停用是**答案**不是失敗 —— 不可以重試，也不可以丟例外。

    丟例外的話它會被記成 `load_failed`，而後台會以為資料庫有問題。
    """
    from routes import auth
    sb, calls = _fake_users([rows])
    with patch.object(auth, 'supabase', sb):
        assert auth.load_user_for_pwa('u-1') is None
    assert len(calls) == 1, '對一個明確的拒絕重試了'


# ══ 五、那筆記錄要進得了後台 ═══════════════════════════════

def test_the_record_carries_who_it_was_and_why():
    """★ `actor_id` 是 `None` —— 這一刻**沒有人登入**，那是對的。
    身分只存在網址那個 token 裡，所以要放進 `detail`。"""
    from routes import auth
    sent = {}
    with patch('routes.audit.log_action',
               lambda *a, **k: sent.update(args=a, kw=k)):
        auth.record_pwa_problem(P.LOAD_FAILED, 'u-1')
    assert sent['args'][0] == 'pwa.login_failed'
    assert 'u-1' in sent['args']
    assert P.LOAD_FAILED in str(sent['args'])


def test_the_action_has_a_label_in_the_admin_log():
    """★ 後台的操作記錄靠 `ACTION_LABELS` 翻成中文 ——
    少一行的話那幾筆會顯示成一串英文 key，沒有人看得懂。"""
    from routes.audit import ACTION_LABELS
    assert 'pwa.login_failed' in ACTION_LABELS


def test_the_app_really_wires_the_recorder_up():
    """★★ 寫好了但沒接上＝沒有做，而症狀跟原本一模一樣：**什麼都沒記到**。

    掃 `app.py` 那一行（先去掉註解 —— 這個專案記過的坑，
    註解裡就寫著 `on_problem` 在解釋它為什麼存在）。
    """
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / 'app.py'
    code = re.sub(r'(?m)#.*$', '', src.read_text(encoding='utf-8'))
    m = re.search(r'init_pwa_session\((.*?)\)', code, re.S)
    assert m, '找不到 init_pwa_session 的呼叫'
    args = re.sub(r'\s+', '', m.group(1))
    assert 'on_problem=record_pwa_problem' in args, \
        f'on_problem 沒有接上：{m.group(1)}'
