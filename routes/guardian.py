"""監護人欄位：姓名＋電話存成一格

## 為什麼是一種欄位型別，而不是叫管理員建兩個條件欄位

使用者的要求是「後台表單設定不要太複雜」。做成兩個一般欄位的話，
管理員每次都要：建「監護人姓名」→ 設年齡跳題條件 → 建「監護人電話」→
**再設一次一模一樣的條件**。四個步驟、兩份同樣的設定，而兩份設定
遲早會不一樣（改了一個忘了另一個）—— 那時候會變成「姓名要填、
電話不用填」，名冊上有名字沒電話，看起來像那個人自己漏填。

現在是：加一個欄位 → 型別選「監護人（姓名＋電話）」→ 勾必填。結束。
「未滿18歲才問」的條件由伺服器在存檔時自動產生（見 routes/admin_events.py），
所以管理員完全不用碰跳題面板，而前台、伺服器、預覽全部沿用現有機制。

## ★ 為什麼存成一個字串而不是 JSON

`registration_answers.answer` 是純文字，而**每一個讀它的地方都是直接印出來**：
名冊、Excel 匯出、報名者自己的「我的報名」、後台的編輯彈窗。存 JSON 的話，
這四個地方會同時出現 `{"name": "王小明", "phone": "0912345678"}`。

跟 auto_tier 同一個決定：存進去的東西保持「人看得懂的樣子」，
下游一行都不用改。改動面越小，靜默壞掉的機會越少。

格式是 `王小明／0912345678`。分隔符號用全形斜線，而且**兩邊的輸入都會
先把它拿掉** —— 不然名字裡有一個斜線就會把電話切錯位置，
而名冊上看起來只是那個人的電話怪怪的。
"""
import re

SEP = '／'

# 這個界線是法律定的，不是收費定的（收費分級可能切在 12 歲，
# 那是另一回事）。寫成常數是為了讓「為什麼是 18」有一個地方可以問。
MINOR_MAX_AGE = 17          # 未滿 18 歲 ＝ 17 歲以下


# ── 「什麼時候問這一題」的兩個預設答案 ────────────────────
#
# ★ 為什麼「每個人都問」需要一個明確的印記
#
#   「每個人都問」在資料上就是**沒有條件**。而沒有條件的監護人欄位，
#   存檔時會被 `_apply_guardian_conditions` 自動補上「未滿18歲才問」——
#   所以管理員想要「兒童營全部都要填」時，他把條件清掉、存檔，
#   系統靜靜地把「未滿18歲」補回去。
#
#   後台看起來設好了、預覽也正常（預覽補的是同一條），只有 18 歲以上的
#   人打開報名表時那一題不出現 —— 而沒有人會發現，因為誰都不會去比對
#   「這場活動到底有幾個人填了監護人」。
#
#   所以要分得出「還沒設」和「設成每個人都問」，就得有一個存得下來的印記。
MINOR = 'minor'             # 未滿 18 歲才問（沒設條件時自動補的）
EVERYONE = 'everyone'       # 每個人都問

_MARKS = (MINOR, EVERYONE)


def everyone_condition():
    """「每個人都問」存進 condition_json 的樣子。

    ★ 它沒有 trigger —— 求值器看到沒有 trigger 的條件本來就是「顯示」，
      所以這個印記**即使求值器不認得它也是對的**。但兩邊仍然各寫了一條
      明確的分支（`routes/conditions._is_visible`、
      `static/js/form-fields.js` 的 `evaluateConditions`），
      因為「靠壞掉時的預設行為剛好正確」跟「刻意這樣做」在程式碼裡
      長得一模一樣 —— 哪天有人把預設收緊成「藏起來」，
      這一題就會安靜地從報名表上消失。
    """
    return {'auto': EVERYONE}


def condition_mark(raw):
    """這條 condition_json 是誰設的？

    回 `MINOR`（系統自動補的）、`EVERYONE`（管理員選「每個人都問」），
    或 `None`（管理員自己在跳題面板設的，或根本沒設）。
    """
    import json as _json

    if not raw:
        return None
    cond = raw
    if isinstance(cond, str):
        try:
            cond = _json.loads(cond)
        except (ValueError, TypeError):
            return None
    if not isinstance(cond, dict):
        return None
    mark = cond.get('auto')
    return mark if mark in _MARKS else None


def compose(name, phone):
    """姓名 + 電話 → 存進資料庫的那一格。兩個都空就回空字串。"""
    name = _clean(name)
    phone = _clean(phone)
    if not name and not phone:
        return ''
    return f'{name}{SEP}{phone}'


def parse(answer):
    """存進去的那一格 → (姓名, 電話)。

    ★ 從**最後一個**分隔符號切。名字裡的斜線已經在 compose 清掉了，
      但舊資料、或有人直接打 API 送上來的東西不保證 —— 從後面切的話，
      多出來的斜線會留在名字裡（看得出來哪裡怪），而不是把電話切掉一半
      （看起來像個正常但錯的電話號碼）。
    """
    text = str(answer or '').strip()
    if not text:
        return '', ''
    if SEP not in text:
        # 舊資料或手動填的：整串當姓名，不要猜哪一段是電話
        return text, ''
    name, _, phone = text.rpartition(SEP)
    return name.strip(), phone.strip()


def is_complete(answer):
    """★ 姓名和電話**都要有**才算填了。

    只驗「這一格非空」的話，只填姓名就會通過必填檢查 ——
    而名冊上那一列有名字沒電話，出事那天打不到人。
    """
    name, phone = parse(answer)
    return bool(name and phone)


def _clean(v):
    # 分隔符號一律拿掉；連續空白收成一個
    return re.sub(r'\s+', ' ', str(v or '').replace(SEP, '').replace('/', '')).strip()
