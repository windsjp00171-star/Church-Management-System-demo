"""PWA 續登：讓「裝好 PWA 後被要求輸入 LINE 帳號密碼」這個 bug 消失。

═══ 這個模組在解什麼問題 ═══

任何「用 LINE Login 的網站 + PWA」都會踩到：

  1. 使用者在瀏覽器裡登入過，用得好好的
  2. 加到主畫面，從桌面圖示打開
  3. PWA 裡卻是「未登入」→ 被導去 LINE 登入頁
  4. 而且不是「用 LINE App 一鍵授權」，是要求輸入**註冊 email 與密碼**
  5. 幾乎沒有人記得那組帳密（平常都靠 App 自動登入）→ 卡死

原因有兩層：

  * iOS 的 PWA 使用獨立的 cookie 容器，跟 Safari 不共用 → 原本的 session 不在裡面
  * 那個容器裡同樣沒有 LINE 的登入 cookie → LINE 判定為陌生瀏覽器，
    於是退回最原始的 email + 密碼流程

解法是繞過整個 OAuth 來回：使用者「已登入時」抓 manifest，就在 start_url
夾帶一枚簽章 token；PWA 第一次啟動走 start_url，驗章後直接建立 session。


═══ 移植到其他專案（四個步驟，缺一不可）═══

1. 複製本檔案到專案裡。

2. manifest 的 start_url 帶 token（只在已登入時）：

       from routes.pwa_session import start_url_for
       start_url = start_url_for(app.secret_key, session.get('user_id'))

3. 在 app factory 裡接上兌換：

       from routes.pwa_session import init_pwa_session
       init_pwa_session(app, load_user=..., on_login=...)

   load_user(user_id) -> dict 或 None（回 None 代表拒絕登入，例如帳號已停用）
   on_login(user)     -> 建立 session（沿用你原本 LINE 登入成功後那段）

4. ★ HTML 的 manifest 連結必須加 crossorigin="use-credentials"：

       <link rel="manifest" href="/manifest.json" crossorigin="use-credentials">

   少了這個屬性，瀏覽器抓 manifest 時**不會帶 cookie**，後端永遠讀不到登入狀態，
   token 不會被夾帶，整套機制靜默失效 —— 而且沒有任何錯誤訊息。
   這是最容易漏、也最難查的一步。


═══ 安全性 ═══

token 等同「這台裝置上這位使用者的長效登入憑證」，性質接近 remember-me cookie：

  * 以 SECRET_KEY 簽章，改一個字元就失效
  * 有效期限（預設 30 天 —— 使用者可能裝了很久才第一次打開）
  * 兌換後立刻從網址移除，不留在瀏覽記錄
  * 已經登入的 session 不會被 token 覆蓋
  * load_user 可以擋掉停用帳號

SECRET_KEY 換掉時，所有已發出的 token 會一起失效（使用者需重新登入一次）。
"""
from urllib.parse import urlencode

from flask import redirect, request, session

DEFAULT_PARAM = 'pwa_login'
DEFAULT_SALT = 'pwa-login'
DEFAULT_MAX_AGE = 60 * 60 * 24 * 30      # 30 天：裝了 PWA 可能隔很久才第一次打開

# 從 LINE 內建瀏覽器跳到 Safari/Chrome 時的身分交接。
# 那是另一個 cookie 容器，session 不會跟著過去，於是又被丟去 LINE 要 email 密碼。
# 這種交接是「按下按鈕的當下」就完成，所以效期壓到很短。
HANDOFF_SALT = 'browser-handoff'
HANDOFF_MAX_AGE = 60 * 10                # 10 分鐘


def _serializer(secret, salt=DEFAULT_SALT):
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(secret, salt=salt)


def issue_token(secret, user_id, salt=DEFAULT_SALT):
    """簽一枚續登 token；失敗回 None（絕不讓簽章問題炸掉 manifest）"""
    if not user_id:
        return None
    try:
        return _serializer(secret, salt).dumps(str(user_id))
    except Exception:
        return None


def verify_token(secret, token, max_age=DEFAULT_MAX_AGE, salt=DEFAULT_SALT):
    """驗章並取出 user_id；無效／過期回 None"""
    if not token:
        return None
    try:
        return _serializer(secret, salt).loads(token, max_age=max_age)
    except Exception:
        return None


def start_url_for(secret, user_id, base='/', param=DEFAULT_PARAM, salt=DEFAULT_SALT):
    """manifest 用的 start_url：已登入才夾帶 token，未登入就是原本的路徑

    base 本身可以帶 query（例如 '/calendar?app=calendar'）—— 這時要接 &，
    寫死 ? 的話會產出 '/calendar?app=calendar?pwa_login=...' 這種壞網址，
    而且是壞在 manifest 裡面：不會有任何錯誤，只有 PWA 開起來位置不對。
    """
    token = issue_token(secret, user_id, salt)
    if not token:
        return base
    sep = '&' if '?' in base else '?'
    return f'{base}{sep}{param}={token}'


def handoff_token(secret, user_id):
    """短效交接 token：從 LINE 內建瀏覽器跳到 Safari/Chrome 時帶著走，
    讓對面那個容器不必重跑 LINE 登入（否則會被要求輸入註冊 email 與密碼）。"""
    return issue_token(secret, user_id, HANDOFF_SALT) or ''


#  兌換沒成功的三種原因。★ 分開是因為**處理方式完全不同**：
#
#    bad_token   → 他的 manifest 舊了／換過 SECRET_KEY。重新登入一次就好
#    not_allowed → 查無此人或已停用。**本來就不該登入**，不是故障
#    load_failed → **我們自己的問題**（資料庫抖了）。他什麼都沒做錯
#
#  ★★ 原本這三種全部走同一條路，而且都不留痕跡 —— 於是
#    「偶發性卡登入」這件事在系統裡**完全沒有任何記錄**，
#    只能靠猜。（使用者回報時我手上一個數字都沒有。）
BAD_TOKEN, NOT_ALLOWED, LOAD_FAILED = 'bad_token', 'not_allowed', 'load_failed'


def init_pwa_session(app, load_user, on_login, param=DEFAULT_PARAM, accept=None,
                     on_problem=None):
    """註冊 before_request，把網址上的 token 兌換成 session。

    load_user(user_id) -> dict | None    回 None 代表不給登入（查無此人／已停用）
                                         **查詢失敗要丟例外**，不要回 None ——
                                         回 None 的話「資料庫抖了」會被當成
                                         「這個人被停用」，而他只會看到登入頁
    on_login(user)     -> None           建立 session（沿用既有的登入邏輯）
    accept             -> [(salt, max_age), ...] 接受哪些用途的 token
    on_problem(why, user_id) -> None     選配。兌換沒成功時叫一次，讓呼叫端
                                         自己決定要不要記錄（這個模組不碰資料庫）

    需排在其他 before_request 之前註冊，否則會先被當成未登入而導去登入頁。
    """
    accept = accept or [
        (DEFAULT_SALT, DEFAULT_MAX_AGE),      # PWA 啟動
        (HANDOFF_SALT, HANDOFF_MAX_AGE),      # 跳外部瀏覽器
    ]

    @app.before_request
    def _consume_pwa_token():
        token = request.args.get(param)
        if not token:
            return

        # 已經登入的人不處理 —— 不讓任何 token 覆蓋現有身分
        if not session.get('user_id'):
            user_id = None
            for salt, max_age in accept:
                user_id = verify_token(app.secret_key, token, max_age, salt)
                if user_id:
                    break
            why = None
            if not user_id:
                why = BAD_TOKEN
            else:
                try:
                    user = load_user(user_id)
                except Exception:
                    #  ★★ 我們自己的問題，不是他的。分不出來的話，
                    #    資料庫抖一下就跟「這個帳號被停用」走同一條路 ——
                    #    而他看到的是登入頁，還會被要求輸入 LINE 的
                    #    註冊 email 和密碼（幾乎沒有人記得那組）。
                    why = LOAD_FAILED
                else:
                    if user:
                        on_login(user)
                    else:
                        why = NOT_ALLOWED
            if why and on_problem:
                #  ★ 記錄失敗絕對不可以讓登入失敗 —— 整段包起來。
                try:
                    on_problem(why, user_id)
                except Exception:
                    pass

        # 不論成功與否都把 token 從網址移除，避免留在瀏覽記錄或被轉傳
        rest = {k: v for k, v in request.args.items(multi=False) if k != param}
        qs = urlencode(rest)
        return redirect(request.path + ('?' + qs if qs else ''))

    return _consume_pwa_token
