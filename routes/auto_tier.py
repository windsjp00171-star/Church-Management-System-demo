"""依生日自動判定身分別

## 為什麼要有這個

原本是讓報名者自己選身分別（成人／敬老／身障／孩童）。使用者的實際問題：
**自己選就會選錯，而對帳時查不出來** —— 名冊上「成人」和「敬老」看起來
一模一樣，只有金額差 200，要一個一個對生日才知道。

所以改成：生日本來就要填（保險要用），系統自己算年齡、自己判身分別，
報名者不用做判斷 —— 而判斷正是出錯的地方。

## 只有一件事是系統算不出來的

身心障礙不可能從生日推出來，一定要本人申報。所以那一項是唯一保留給
使用者勾的，勾了就覆蓋年齡判定的結果 —— **但只有在它不會讓人變貴的
時候**（見下一節）。

## ★ 自行申報那一項是「優待」，不可以讓人變貴（使用者回報的 bug）

使用者的原話：「如果是嬰兒 或幼童 勾優待 繳費費用會變成優待費用 更貴」。

實際那場活動的價目：

    成人 800 ／ 孩童 500 ／ 長者 600 ／ 優待 600 ／ 嬰兒(旅平險費用) 50

原本「勾了就覆蓋」是無條件的，所以：

| 這個人 | 依年齡 | 勾了優待之後 |
|---|---|---|
| 嬰兒 | 50 | **600**（貴 12 倍） |
| 孩童 | 500 | **600** |

而他勾那一格是**在講實話**（他真的有證明）—— 系統卻因此多收他錢。
沒有人會為了多付錢去勾一個優待選項，所以「勾了變貴」一定是 bug，
不是設定問題。

**規則：兩邊都算得出價格時，取比較便宜的那一項。** 一樣價錢時保留
自行申報的那一項（金額沒差，而那是他主動申報的身分，名冊上留著比較有用）。

★ 算不出價格（沒標價、或年齡算不出來）時維持原本的行為 ——
  沒有東西可以比較，這時候唯一的資訊就是他自己申報的那一項。

★ 讓開的時候一定要**講出來**（`decide()` 的 note）。默默改掉的話，
  他勾了那一格什麼都沒發生，看起來就是「這個勾選框壞了」。

問法用「特殊身分別（持有身心障礙證明者）」—— 教會不賣票，講「優待票」
不成立；而且這個講法是在描述**類別**，不是在問「你是不是身障」。

## ★ 存進資料庫的答案不變

算出來之後存的還是**選項標籤**（「成人」「65歲以上者」），跟使用者自己選
的時候一模一樣。所以名冊、收款單、採購清單、匯出全部不用改 ——
它們讀到的東西沒有變。

這是刻意的：改動面越小，靜默壞掉的機會越少。

## ★ 一定要在伺服器端再算一次

身分別決定金額。只在前端算的話，任何人都能送出任意身分別 ——
畫面上完全正常，名冊上也完全正常，只是那個人少付了 300 塊。
前端算是為了「當場看得到」，伺服器算才是真的。

## 年齡基準是活動當日

使用者定的：「年齡界定的部分，我們還是以活動當日為邏輯計算」。
景點是當天查驗的，用報名日算會出現「系統說他是兒童、現場查出來是成人」。
跨日活動用第一天。
"""

def _in_range(age, bounds):
    lo, hi = (bounds + [None, None])[:2] if isinstance(bounds, list) else (None, None)
    if lo is not None and age < lo:
        return False
    if hi is not None and age > hi:
        return False
    return lo is not None or hi is not None


def _by_age(labels, special, rules, age):
    """純粹依年齡算出來的那一項（不看自行申報），算不出來回 None。"""
    if age is None:
        return None
    ages = rules.get('ages') or {}

    # 有設範圍的照範圍判（依表單順序，第一個吻合的算數）
    for label in labels:
        if label == special:
            continue          # 特殊身分別只能自行申報，不參與年齡判定
        if _in_range(age, ages.get(label)):
            return label

    # 其他年齡 → 明確指定的預設項。沒指定就回 None，不猜。
    fallback = rules.get('fallback_label')
    if fallback and fallback in labels and fallback != special:
        return fallback
    return None


def decide(options, rules, age, has_special=False):
    """算身分別，並在「自行申報那一項比較貴」時說明為什麼沒有採用它。

    回 `{'label': 標籤 或 None, 'note': 給報名者看的一句話（沒事就是 ''）}`

    ★ note 一定要有人顯示出來。系統把他勾的那一項讓開卻不說的話，
      畫面上就是「我勾了，什麼都沒變」—— 看起來像勾選框壞了，
      而他下一步多半是取消勾選、或打電話問。

    ★ note 裡的類別名稱一律從設定來（`special_label` 和選項標籤），
      不可以寫死 —— 換一場活動那句話就在講別人的事。
    """
    rules = rules or {}
    prices = {o['label']: o.get('price') for o in (options or [])}
    labels = list(prices)
    special = rules.get('special_label')

    by_age = _by_age(labels, special, rules, age)
    if not (has_special and special and special in labels):
        return {'label': by_age, 'note': ''}

    # ── 自行申報那一項只有在「不會讓他變貴」時才算數 ──
    sp_price, age_price = prices.get(special), prices.get(by_age)
    if by_age is None or sp_price is None or age_price is None \
            or sp_price <= age_price:
        return {'label': special, 'note': ''}
    return {
        'label': by_age,
        'note': (f'你勾的「{special}」是 ${sp_price}，'
                 f'而依年齡是「{by_age}」${age_price} —— '
                 f'系統自動採用比較便宜的那一個。'),
    }


def pick_tier(options, rules, age, has_special=False):
    """算出身分別 → 選項標籤，算不出來回 None。

    options : [{'label':…, 'price':…}]（parse_options 的結果，**依表單順序**）
    rules   : {
        'special_label':  需自行申報的那一項（不參與年齡判定）,
        'fallback_label': 其他年齡都算這一項,
        'ages':           {label: [下限, 上限]},
    }
    age     : 整數或 None
    has_special : 使用者有沒有勾「持有身心障礙證明」

    ★ 回 None 的時候呼叫端不可以當成 0 或猜一個 —— 要讓它跳出來問。

    ## 為什麼預設項要「明確指定」而不是推論出來

    第一版是「第一個沒設年齡範圍的選項就是預設」。看起來很合理，
    但只要管理員幫成人也設了範圍，**沒設範圍的就只剩「持身障證明」**——
    於是一個 15 歲的孩子會被自動標成持有身心障礙證明。

    比算錯錢嚴重得多，而且沒有人會發現：名冊上那一格看起來
    就跟本人自己勾的一模一樣。

    我第一次的修法是「剩兩個以上就回 None」，但上面那個情境剛好只剩一個，
    照樣中招。結論是**不能用猜的** —— 預設項一定要管理員明確指定。
    （後台會自動帶第一個選項，所以實際上不用多做事。）

    ★ 判定本身在 `decide()`（那裡還會回一句「為什麼」）—— 這支只取標籤，
      給不需要解釋的呼叫端用。
    """
    return decide(options, rules, age, has_special)['label']


def _in_range_configured(bounds):
    return isinstance(bounds, list) and any(b is not None for b in bounds[:2])


def is_enabled(rules):
    """這個欄位有沒有開自動判定。

    ★ 這是一個**明確的開關**，不是從「有沒有設年齡範圍」推論出來的。

      理由是使用者定的：不是每場活動都要按生日分級收費。有些場次就是
      讓人自己選身分別（或根本沒有年齡差別），那時候即使欄位上還留著
      上一場複製過來的年齡設定，也不該自動生效。

      推論式的話，「複製一場舊活動」就會靜靜地把自動判定一起帶過來 ——
      而畫面上看不出差別。

    ★ 後台把年齡欄位藏在這個開關底下，所以不會有「範圍設好了但沒開」
      的狀態：關著的時候根本設不了範圍。
    """
    return bool((rules or {}).get('enabled'))


def describe(options, rules):
    """把規則講成人話，顯示在報名表上。

    不講的話，報名者只看到一個自己不能改的身分別，會以為是系統填錯了。
    """
    rules = rules or {}
    ages = rules.get('ages') or {}
    special = rules.get('special_label')
    parts = []
    for o in (options or []):
        label = o['label']
        if label == special:
            continue
        b = ages.get(label)
        if not _in_range_configured(b):
            continue
        lo, hi = (b + [None, None])[:2]
        if lo is not None and hi is not None:
            parts.append(f'{lo}–{hi} 歲：{label}')
        elif lo is not None:
            parts.append(f'{lo} 歲以上：{label}')
        else:
            parts.append(f'{hi} 歲以下：{label}')
    fb = rules.get('fallback_label')
    if fb and fb != special:
        parts.append(f'其他年齡：{fb}')
    return '、'.join(parts)


def event_basis_date(event):
    """年齡基準日 = 活動當日（跨日活動用第一天）。

    ★ 使用者原本定的是報名日，後來改成活動當日 —— 景點是當天查驗的，
      用報名日算會出現「系統說他是兒童、現場查出來是成人」。

    活動沒填日期時回 None，age_on 會退回今天 —— 那是唯一還算合理的近似，
    但金額會隨著「今天」漂移，所以後台在沒填日期時要提醒。
    """
    # ★ event_start 是 UTC。切字串的話，早上 8 點以前的活動
    #   基準日會退到前一天 —— 生日剛好是活動當天的人會少算一歲，
    #   而那直接影響收費級距。
    from routes.tw_time import date_str
    return date_str((event or {}).get('event_start')) or None


def resolve(field, options, birthday, event, has_special=False):
    """一個收費欄位在這筆報名上的最終身分別。

    field    : event_fields 的列（要有 auto_tier）
    options  : parse_options(field['options'])
    birthday : 生日（西元 'YYYY-MM-DD'，可為 None）
    event    : 活動列（取 event_start 當年齡基準）
    has_special : 使用者有沒有勾特殊身分別

    回 (身分別標籤 或 None, 年齡 或 None, 給報名者看的說明 或 '')

    ★ 第三個值是「你勾的那一項比較貴，所以系統讓開了」那句話
      （見 `decide`）。呼叫端**一定要有人把它顯示出來** ——
      默默讓開的話，他勾了那一格什麼都沒發生，看起來像勾選框壞了。

    ★ 這個函式是**伺服器端的權威**。前台顯示的東西是呼叫同一支算出來的
      （透過 /event/<id>/compute-tier），所以不可能出現
      「畫面說成人、存進去卻是敬老」。

    ★ 沒開自動判定就回 (None, None) —— 呼叫端要沿用使用者自己選的答案，
      不可以把 None 當成「沒選」。
    """
    from routes.roc import age_on

    rules = field.get('auto_tier') or {}
    if not is_enabled(rules):
        return None, None, ''
    age = age_on(birthday, event_basis_date(event)) if birthday else None
    out = decide(options, rules, age, bool(has_special))
    return out['label'], age, out['note']
