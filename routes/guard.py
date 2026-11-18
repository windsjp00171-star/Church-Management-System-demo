"""外部（免登入）端點的基本防護：速率限制與蜜罐

## 為什麼需要

報名連結是**公開**的 —— 貼在 LINE 群組、印在海報上、掃 QR 就進得來。
所以 `/event/<id>/external-register`、`/event/<id>/find` 這幾支
**任何人都打得到，而且不用登入**。

使用者的擔心（原話）：「會不會有白目 在我們開放外部的時候 用系統之類的
重複報名來塞爆我們系統」。

★ 這不是想太多。真正會痛的不是資料庫塞不塞得下，是**名額**：
  80 個位子被一支腳本在幾秒內佔滿，真的要報名的人就報不進來了 ——
  而畫面上完全正常（就是額滿而已）。

而且最常發生的其實是最無辜的那一種：**手滑連按兩次送出**。
同一道防線兩種都擋。

## 這裡做什麼、不做什麼

做：
- 每個 IP 的速率限制（滑動視窗，存在行程記憶體裡）
- 蜜罐欄位：人看不到、不會填；笨機器人會填

**不做 CAPTCHA**。這個系統的使用者有一半以上是長輩，圖形驗證碼會擋掉
真的要報名的人 —— 那比被灌幾筆假資料嚴重得多。

## ★ 這道防線的極限（要講清楚，不要以為它是萬能的）

- **IP 換掉就繞過了**。手機切換行動網路就是新 IP。它擋的是
  「隨手寫個迴圈」的人，不是有心人。
- **上限要開得很寬**。★ 「一個人一個 IP」是錯的假設：
  行動網路多半走 CGNAT（一個對外 IP 後面掛著一大票用戶），
  同一家電信的人在伺服器眼裡很可能是**同一個 IP**。
  （原本這裡寫的理由是「教會共用 WiFi」，使用者更正過：
    大家都用自己的手機網路 —— 結論一樣，但理由不同，
    而寫錯理由的註解會讓下一個人以為可以放心調緊。）

  抓太緊的話，公告完大家一起報名，後面的人全部被擋，
  而畫面上只會說「太多次了」。所以這條線畫在「一支腳本才做得到」
  的量級，不是「正常使用的上限」。
- **狀態在行程記憶體裡**：Render 重啟就歸零；gunicorn 開多個 worker 的話
  每個 worker 各算各的（目前 `Procfile` 沒設 `-w`，就是一個）。
  存資料庫可以做得更準，但那等於每一次請求多一次寫入 ——
  為了擋一件還沒發生的事，讓每個人的報名都變慢，不划算。
- **真正的重複防線是身分證字號**（見 `event._reject_duplicate_person`）——
  那個擋的是「同一個人報兩次」，跟 IP 無關，而且擋得準。

所以三層一起看：蜜罐擋笨機器人、速率限制擋手滑和隨手寫的迴圈、
身分證字號擋真正的重複。
"""
import time
from collections import defaultdict, deque

from flask import request

# {桶子: deque[timestamp]}
_HITS = defaultdict(deque)

# 桶子總數的上限 —— 不設的話，換 IP 灌進來的請求會把記憶體吃光，
# 而那正是這個模組要防的事（防護本身變成攻擊面）。
_MAX_BUCKETS = 20000

# ★ 蜜罐欄位的名字要看起來像真的，不然稍微聰明一點的腳本就跳過了。
#   ★ 不可以取跟真欄位一樣的名字 —— 那會變成真的使用者填了它。
HONEYPOT_FIELD = 'nickname_confirm'


def client_ip():
    """呼叫端的 IP。

    ★ Render 在反向代理後面，`remote_addr` 是代理的位址 ——
      不看 `X-Forwarded-For` 的話**所有人共用同一個桶子**，
      第一個人報完名，後面的全部被擋（而畫面上只會說「太頻繁」）。

    ★ XFF 是可以偽造的。這裡不是身分驗證，只是分桶：偽造的效果等同
      換 IP，而換 IP 本來就繞得過去（見模組開頭）。所以取最左邊那個就好，
      不必為了防偽造把事情做複雜。
    """
    fwd = (request.headers.get('X-Forwarded-For') or '').split(',')
    first = fwd[0].strip()
    return first or (request.remote_addr or 'unknown')


def too_many(key, limit, per_seconds, now=None):
    """這個桶子在 `per_seconds` 內是不是已經超過 `limit` 次。

    回 True 代表**這一次要擋下來**（本次也算進去了）。
    """
    now = time.time() if now is None else now
    hits = _HITS[key]
    cutoff = now - per_seconds
    while hits and hits[0] < cutoff:
        hits.popleft()
    if len(hits) >= limit:
        return True
    hits.append(now)
    if len(_HITS) > _MAX_BUCKETS:
        _evict(now)
    return False


def _evict(now):
    """把已經空掉的桶子丟掉（順便清一次過期的）。"""
    for k in list(_HITS):
        while _HITS[k] and _HITS[k][0] < now - 3600:
            _HITS[k].popleft()
        if not _HITS[k]:
            del _HITS[k]


def rate_limited(name, limits):
    """`limits` = [(次數, 秒數), …]，任何一條超過就擋。

    回「要給使用者看的那句話」，沒超過回 None。

    ★ 訊息要講**多久之後可以再試**，不要只說「操作太頻繁」——
      一句沒有下一步的錯誤訊息，使用者只會一直重按。
    """
    ip = client_ip()
    for limit, per in limits:
        if too_many(f'{name}:{ip}:{per}', limit, per):
            mins = max(1, round(per / 60))
            return (f'太多次了，請等 {mins} 分鐘再試。'
                    '如果你是要幫很多人報名，請分次送出，'
                    '或直接聯絡教會辦公室。')
    return None


def looks_automated(payload):
    """蜜罐有沒有被填。

    人看不到那一格（版面上藏起來、`tabindex=-1`、`autocomplete=off`），
    所以**填了就不是人**。

    ★ 擋下來要回一個看得懂的錯誤，不要假裝成功。
      假成功對真的使用者是災難：萬一哪天自動填表工具幫他填了那一格，
      他會看到「報名成功」而名單上沒有他。
    """
    return bool(str((payload or {}).get(HONEYPOT_FIELD) or '').strip())


def reset_for_tests():
    _HITS.clear()
