"""活動自訂欄位：帶價格的選項

## 為什麼需要這個

原本 `events.fee` 是**單一數字**，一場活動只能有一個價格。但實際上常常
要分級收費 —— 教會旅遊的景點門票就是：成人 800、敬老 600、身障 600、
12 歲以下 400。

沒有這個的話只能把價格寫在選項文字裡（「成人 $800」），報名者看得到，
但**系統不知道那是錢**：名冊不會加總、後台看不到應收多少，每辦一次就要
自己拉一次 Excel —— 而對錯的是錢。

## 語法：行尾的 `|價格`

    成人|800
    敬老|600
    身障|600
    12歲以下孩童|400

選了 `這是|一個選項` 這種本來就含 `|` 的標籤也不會壞 —— 只有**行尾是
`|` 接純數字**才當成價格（見 _PRICED）。沒有 `|` 的選項就是沒有價格，
既有的活動一行都不用改。

## 存的是「標籤」，不是整行

報名者的答案存 `成人`（不是 `成人|800`）。這樣：
  - 既有答案不受影響
  - 跳題條件（condition_json 比對答案文字）繼續有效
  - 改價格不會讓舊答案對不上

## 金額不存起來，每次讀的時候算

沒有另外開欄位存「這個人應繳多少」。理由是改價格時所有人一起更新 ——
教會活動改的多半是打錯的價格，這時候「早報名的人停在舊價」才是錯的。

★ 但這帶來一個必須處理的情況：管理員把選項**改名**（成人 → 成人票）
  之後，舊答案 `成人` 就對不到任何價格了。這種時候一定要回 None 而不是
  0 —— 回 0 的話名冊上那個人靜靜地變成不用繳錢，沒有人會發現。
  呼叫端要把 None 顯示成「找不到對應價格」，讓它跳出來。
"""
import re

# 只有「行尾是 | 接純數字」才是價格。
# 標籤裡本來就有 | 的（例如「A|B 方案」）不會被誤判 —— 除非它剛好也以
# |數字 結尾，那種標籤實務上不存在。
_PRICED = re.compile(
    r'^(?P<label>.*?\S)\s*\|\s*(?P<price>\d{1,7})(?:\s*\|\s*(?P<cap>\d{1,5}))?\s*$')

OTHER = '__other__'


def parse_option_full(line):
    """一行 → (標籤, 價格或 None, 名額或 None)

    名額是價格後面再接一段 `|數字`（「搭車|200|20」＝ 收 200、最多 20 人）。
    ★ 沒有價格就沒有名額：名額一律掛在帶價格的選項上，免費的就寫 `|0|20`。
    """
    line = (line or '').strip()
    if not line:
        return None, None, None
    m = _PRICED.match(line)
    if m:
        cap = m.group('cap')
        return m.group('label').strip(), int(m.group('price')), \
            (int(cap) if cap is not None else None)
    return line, None, None


def parse_option(line):
    """一行 → (標籤, 價格或 None)"""
    label, price, _cap = parse_option_full(line)
    return label, price


def parse_options(options_text):
    """選項文字 → [{'label':…, 'price':… or None, 'cap':… or None}]，略過空行與 __other__"""
    out = []
    for line in (options_text or '').split('\n'):
        label, price, cap = parse_option_full(line)
        if not label or label == OTHER:
            continue
        out.append({'label': label, 'price': price, 'cap': cap})
    return out


def has_prices(options_text):
    return any(o['price'] is not None for o in parse_options(options_text))


def price_of(options_text, answer):
    """某個答案對應的價格。

    回 None 有兩種意思，呼叫端都不該當成 0：
      - 這個欄位本來就沒標價
      - 答案對不上任何選項（多半是選項被改名了）
    """
    if answer is None:
        return None
    answer = str(answer).strip()
    for opt in parse_options(options_text):
        if opt['label'] == answer:
            return opt['price']
    return None


def is_unmatched(options_text, answer):
    """有標價的欄位，但這個答案對不到任何選項 → 名冊要標出來。

    這是「改了選項名稱」之後會發生的事，而症狀是某個人的應繳金額
    默默變成 0。所以要能問出來、而不是靜靜算過去。
    """
    if not answer or not has_prices(options_text):
        return False
    labels = {o['label'] for o in parse_options(options_text)}
    return str(answer).strip() not in labels


def amount_for(fields, answers):
    """一筆報名的應繳金額。

    fields  : [{'id':…, 'options':…}, …]（event_fields 的列）
    answers : {field_id: answer}

    回 (總額, [對不上的欄位 id])。對不上的不計入總額 —— 猜一個數字
    比留白更危險。
    """
    total = 0
    unmatched = []
    for f in fields or []:
        opts = f.get('options') or ''
        if not has_prices(opts):
            continue
        ans = (answers or {}).get(f.get('id'))
        if not ans:
            continue
        if is_unmatched(opts, ans):
            unmatched.append(f.get('id'))
            continue
        price = price_of(opts, ans)
        if price:
            total += price
    return total, unmatched


def fee_range(base_fee, fields):
    """這場活動實際會收多少 → (最低, 最高)。

    ## 為什麼要有這個

    活動頁的費用那一欄原本只讀 `events.fee`。分級收費是寫在自訂欄位裡的，
    所以一場「成人 800／敬老 600／孩童 500」的旅遊，只要 events.fee 是 0，
    頁面就大大方方標著 **「免收費」**。

    這不是少顯示一點資訊，是**印在頁面上的假話**——
    而且人會照著它決定要不要帶錢出門。

    ## 必填與選填分開算

    必填的收費欄位一定要選一項 → 最低就是它最便宜的那項。
    選填的可以不選 → 最低是 0，但最高還是要算進去。

    多個收費欄位會疊加（身分別 ＋ 加購接駁車），所以是逐欄相加。
    """
    lo = hi = int(base_fee) if base_fee not in (None, '') else 0     # 沒設基本費＝0（免費），不是算錯
    for f in fields or []:
        prices = [o['price'] for o in parse_options(f.get('options') or '')
                  if o['price'] is not None]
        if not prices:
            continue
        hi += max(prices)
        # 選填的可以整個不選，最低貢獻 0
        if f.get('is_required'):
            lo += min(prices)
    return lo, hi


#  ── 畫面上那一行費用：**只准有一份** ────────────────────────
#
#  ★★ `fee_range` 抽出來之後，**格式化那三個分支卻被各頁自己抄了一份**
#    （活動詳情、外部報名各一份）。於是新做的頁面沒有人想起來要抄 ——
#    活動列表（`index.html`）和外部身分頁（`event_identity.html`）
#    就是這樣，**直接讀 `events.fee`**。
#
#    正式站的症狀（使用者截圖回報）：2026 秋之旅 `events.fee = 0`，
#    而身分別欄位是「成人 800／孩童 500／長者 600／優待 600／嬰兒 50」，
#    列表頁大大方方標著 **💰 免費**。
#
#    這不是少顯示一點資訊，是**印在頁面上的假話** ——
#    而人會照著它決定要不要帶錢出門。
#
#  ★ 回 `(種類, 文字)` 而不是一整段 HTML：每一頁的外框不一樣
#    （詳情頁是徽章、列表頁是一行小字），但**數字和措辭只能有一份**。
FREE, FLAT, RANGE = 'free', 'flat', 'range'


def fee_display(base_fee, fields):
    """`('free'|'flat'|'range', '免費'|'800 元'|'50 ~ 800 元')`。

    ★ `range` 那一種呼叫端要自己補一句「（依所選項目）」——
      **不要寫死「依身分別」**：收費欄位不一定叫身分別，
      也可能是一個選填的加購（接駁車、餐點）。
    """
    lo, hi = fee_range(base_fee, fields)
    if hi == 0:
        return FREE, '免費'
    if lo == hi:
        return FLAT, f'{hi} 元'
    return RANGE, f'{lo} ~ {hi} 元'


def label_only(options_text):
    """把價格拿掉，只留標籤 —— 給跳題條件的下拉選單用。

    條件比對的是**答案文字**，而答案存的是標籤。這裡若回整行
    （成人|800），條件就永遠不會成立，而且畫面完全正常：那個欄位
    只是再也不出現。
    """
    return '\n'.join(o['label'] for o in parse_options(options_text))
