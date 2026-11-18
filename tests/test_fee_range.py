"""活動頁的費用：分級收費也要算進去

## 事故

活動頁的費用那一欄只讀 `events.fee`。分級收費是寫在自訂欄位裡的，
所以一場「成人 800／敬老 600／持身障 600／國小以下 500」的教會旅遊，
只要 events.fee 留 0，頁面就大大方方標著 **「免收費」**。

★ 這不是少顯示一點資訊，是**印在頁面上的假話** ——
  而且人會照著它決定要不要帶錢出門。

★ 它也不會被任何人回報成 bug：頁面沒壞、沒有錯誤訊息、
  報名流程從頭到尾正常，金額在最後一步才出現。
"""
import re

import pytest

from routes.event_fields import fee_range

TIERS = '成人|800\n敬老|600\n持身障證明|600\n國小以下孩童|500'


def _f(options, required=True):
    return {'id': 'x', 'options': options, 'is_required': required}


# ── 使用者實際撞到的那一場 ──────────────────────────

def test_the_trip_that_said_it_was_free():
    """★ 教會旅遊：events.fee = 0，但分級收費 500~800。

    修正前這裡是 (0, 0) → 頁面標「免收費」。
    """
    assert fee_range(0, [_f(TIERS)]) == (500, 800)


def test_a_tiered_event_is_never_labelled_free():
    lo, hi = fee_range(0, [_f(TIERS)])
    assert hi > 0, '最高金額是 0 的話頁面就會標成免收費'


# ── 真的免費 ──────────────────────────

def test_no_fee_and_no_priced_fields_is_actually_free():
    assert fee_range(0, []) == (0, 0)
    assert fee_range(None, None) == (0, 0)


def test_options_without_prices_do_not_make_it_paid():
    """沒標價的選項就是沒標價 —— 不要憑空生出金額"""
    assert fee_range(0, [_f('葷\n素\n不用餐')]) == (0, 0)


# ── 基本費 ──────────────────────────

def test_base_fee_alone():
    assert fee_range(300, []) == (300, 300)


def test_base_fee_stacks_on_top_of_the_tiers():
    """基本費 ＋ 分級收費是相加的（前台的 data-base-fee 就是這樣算）"""
    assert fee_range(100, [_f(TIERS)]) == (600, 900)


# ── 必填 / 選填 ──────────────────────────

def test_optional_field_can_be_skipped_so_the_floor_stays_low():
    """★ 選填的加購項目可以整個不選 → 最低是 0，但最高要算進去。

    把選填當必填的話，頁面會宣告一個「其實可以不用付」的下限，
    看起來像漲價。
    """
    assert fee_range(0, [_f('接駁車|150', required=False)]) == (0, 150)


def test_required_field_sets_a_real_floor():
    assert fee_range(0, [_f('接駁車|150', required=True)]) == (150, 150)


def test_multiple_fee_fields_stack():
    """身分別 ＋ 加購，兩個都收錢的話要疊加"""
    fields = [_f(TIERS), _f('接駁車|150', required=False)]
    assert fee_range(0, fields) == (500, 950)


# ── 邊界 ──────────────────────────

def test_a_zero_priced_tier_still_counts_as_a_priced_field():
    """免費的級距（0 元）跟「沒有價格」是兩件事 —— 下限應該是 0，
    但這個欄位仍然是收費欄位。"""
    assert fee_range(0, [_f('會友|0\n非會友|200')]) == (0, 200)


def test_single_tier_shows_one_number_not_a_range():
    """只有一個級距的話 lo == hi，頁面該顯示「費用：800 元」而不是「800 ~ 800」"""
    lo, hi = fee_range(0, [_f('全票|800')])
    assert lo == hi == 800


def test_archived_or_missing_options_are_ignored_safely():
    assert fee_range(0, [{'id': 'a'}, {'id': 'b', 'options': None}]) == (0, 0)


# ══ 接到頁面上 ══════════════════════════════════════

def _src(path):
    return open(path, encoding='utf-8').read()


# ══ 畫面上那一行字 ════════════════════════════════════
#
#  ★★ 這一組是 mutation 逼出來的：我把 `fee_display` 的
#    `if hi == 0` 改成 `if not base_fee`（＝**把原本那個 bug 原封不動
#    放回去**），而當時 45 條測試**全綠** —— 因為那支函式從頭到尾
#    只有模板在掃，一條行為測試都沒有。
#
#    掃模板看得到「有沒有走那支函式」，看不到「那支函式算得對不對」。

def test_a_tiered_event_with_no_base_fee_is_never_free():
    """★★ 這就是事故本身：`events.fee = 0`、身分別 50～800，
    而畫面上寫著「免費」。用正式站那一場的真實選項。"""
    from routes.event_fields import fee_display
    real = [{'options': '成人|800\n孩童|500\n長者|600\n優待|600\n嬰兒(旅平險費用)|50',
             'is_required': True}]
    kind, text = fee_display(0, real)
    assert kind == 'range', kind
    assert text == '50 ~ 800 元', text
    assert '免費' not in text


def test_a_genuinely_free_event_still_says_free():
    """★ 反過來也要對 —— 不然每一場活動都會冒出一個金額。"""
    from routes.event_fields import fee_display
    assert fee_display(0, [{'options': '葷\n素'}]) == ('free', '免費')
    assert fee_display(0, []) == ('free', '免費')


def test_no_fields_at_all_falls_back_to_the_base_fee():
    """★ 欄位撈失敗時傳進來的是 None —— 不可以整個爆掉，
    也不可以把一場 300 元的活動講成免費。"""
    from routes.event_fields import fee_display
    assert fee_display(0, None) == ('free', '免費')
    assert fee_display(300, None) == ('flat', '300 元')


def test_one_price_reads_as_one_price_not_a_range():
    """★ 「300 ~ 300 元」看起來像我們算錯了。"""
    from routes.event_fields import fee_display
    assert fee_display(300, []) == ('flat', '300 元')


def test_an_optional_add_on_starts_from_zero():
    """★ 選填的可以整個不選，所以下限是 0 —— 但上限還是要講出來，
    不然他不知道那個加購要錢。"""
    from routes.event_fields import fee_display
    kind, text = fee_display(0, [{'options': '接駁車|100', 'is_required': False}])
    assert kind == 'range' and text == '0 ~ 100 元'


def test_the_base_fee_and_the_tiers_add_up():
    """★ 兩個都有的話是**相加**，不是取其一。"""
    from routes.event_fields import fee_display
    assert fee_display(100, [{'options': '成人|800\n孩童|500',
                              'is_required': True}]) == ('range', '600 ~ 900 元')


#  ★★ **每一個把費用印在畫面上的頁面**都要登記在這裡。
#
#  原本這份清單只有兩個報名入口 —— 而 `fee_range` 抽出來之後，
#  **格式化那三個分支卻被兩頁各自抄了一份**，於是後來做的頁面
#  沒有人想起來要抄：
#
#    `index.html`（活動列表）      → 直接讀 `event.fee`，標「💰 免費」
#    `event_identity.html`（外部身分頁）→ 直接讀 `event.fee`，整行不出現
#
#  使用者截圖回報：2026 秋之旅 `events.fee = 0`、身分別「成人 800…嬰兒 50」，
#  列表上大大方方寫著 **💰 免費**。
#
#  ★ 新增一個會顯示費用的頁面就加一行 —— 漏掉的話它會安靜地說假話。
FEE_PAGES = [
    'templates/event_detail.html',
    'templates/external_register.html',
]  # 這個 repo 的列表頁與身分頁不顯示費用，所以只有這兩頁


def _code(src):
    """去掉 Jinja／HTML 註解。

    ★★ 底下每一條要掃的字，在這幾頁的註解裡都出現過
    （「只讀 `event.fee` 的話…」）—— 不去掉的話這些斷言會自己通過。
    """
    src = re.sub(r'\{#[\s\S]*?#\}', '', src)
    return re.sub(r'<!--[\s\S]*?-->', '', src)


@pytest.mark.parametrize('path', FEE_PAGES)
def test_every_page_that_shows_a_fee_goes_through_the_helper(path):
    """★★ 三個分支的判斷**只准有一份**（`event_fields.fee_display`）。

    各頁自己抄一份，正是「列表頁標成免費」那個洞的成因 ——
    抄的人會想到，沒抄的人不會知道自己漏了什麼。
    """
    src = _code(_src(path))
    assert 'fee_display(' in src, f'{path} 沒有走 fee_display'


@pytest.mark.parametrize('path', FEE_PAGES)
def test_no_page_reads_the_base_fee_to_decide_what_to_show(path):
    """★★ `{% if event.fee %}` 就是這個 bug 本身：分級收費寫在自訂欄位裡，
    `events.fee` 是 0，於是 800 元的活動標成免費。

    ★ 兩種用法是**對的**，不在此列：
      - `data-base-fee="{{ event.fee or 0 }}"` —— 把基本費交給前端試算
      - 試算框裡那句 `（含基本費 $X）` —— 它是**標註**，不是在決定價錢；
        旁邊那個數字是 `fee-total.js` 連自訂欄位一起算出來的
      （這一條是 mutation 抓到的：第一版把整個檔案掃過，
        於是對兩個完全正確的試算框報錯。）
    """
    src = _code(_src(path))
    #  ★ 先把那個已知正確的用法拿掉，再掃剩下的 —— 不是放寬比對，
    #    是**指名**放行一個看得到的例外。
    src = src.replace('{% if event.fee %}（含基本費 ${{ event.fee }}）{% endif %}', '')
    for bad in ('{% if event.fee %}', '{%- if event.fee -%}'):
        assert bad not in src, f'{path} 拿 event.fee 決定要顯示什麼'


@pytest.mark.parametrize('path', FEE_PAGES)
def test_the_free_wording_comes_from_the_helper(path):
    """★ 「免費」兩個字要是 `fee_display` 回來的，不是頁面自己寫死的 ——
    寫死的話它就跟「有沒有算自訂欄位」脫鉤了。"""
    src = _code(_src(path))
    body = src[src.index('fee_display('):]
    #  同一段裡不可以再出現寫死的免費字樣
    seg = body[:body.index('{% endif %}')] if '{% endif %}' in body else body
    assert '免費' not in seg and '免收費' not in seg, \
        f'{path} 自己寫死了免費字樣：{seg[:120]}'


def test_the_helper_is_registered_for_templates():
    assert "app.jinja_env.globals['fee_range']" in _src('app.py')
    assert "app.jinja_env.globals['fee_display']" in _src('app.py')






