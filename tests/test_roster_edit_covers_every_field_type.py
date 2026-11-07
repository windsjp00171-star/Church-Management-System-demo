"""後台編輯報名資料的彈窗：每一種欄位型別都要有自己的分支

## 事故（使用者回報）

> 「編輯報名資料的部分 有的忘記填勾選身障 可是後台編輯資料沒辦法改」
> 「變成只能手打身分別去改」

那個彈窗的 if/elif 鏈**沒有 `fee` 的分支**，於是分級收費掉到最後的
`{% else %}`，變成一個普通文字框。

★ 手打的後果比「不方便」嚴重得多：那一格的答案要跟選項**完全相符**
  才算得出價格。差一個字（「身障」vs「持身障證明」）就對不上，
  應繳金額靜靜地算成沒有那一級 —— 而名單上那一格看起來完全正常。

★★ 這是 CLAUDE.md 記過的同一個 bug 的**第四次**。前三次是會員報名、
   代報、外部報名／預覽表單 —— 每一次都是「新增了型別，某一個渲染的
   地方沒跟上，掉到預設的文字框」。

   前三次補的是 `tests/test_preview_covers_every_field_type.py`，
   而它只掃 `openPreview`。**這個彈窗是第四個渲染器，沒有人在看。**

## 這裡守什麼

跟預覽那一份同一個做法：`FIELD_TYPES` 是單一來源，少一個分支就紅。
下次再加型別，不必等有人打開彈窗才發現。
"""
import re

import pytest

from routes.field_types import FIELD_TYPES

ROSTER = 'templates/admin/registrations.html'


def _modal_body():
    """切出編輯彈窗裡渲染欄位的那一段。

    ★ 一定要切出來，不能對整份檔案比對：這一頁還有名單表格、篩選器、
      收款單彈窗，隨便一個地方出現「fee」都會讓斷言自己通過。
      （CLAUDE.md：掃原始碼的斷言一律要先切出該掃的那一段。）
    """
    src = open(ROSTER, encoding='utf-8').read()
    start = src.index('<div id="edit-fields-section">')
    end = src.index('</div>', src.index('{% if not fields %}', start))
    return src[start:end]


def _open_edit_body():
    src = open(ROSTER, encoding='utf-8').read()
    fn = src[src.index('function openEditModal('):]
    return fn[:fn.index('\nfunction ')]


def _save_edit_body():
    src = open(ROSTER, encoding='utf-8').read()
    fn = src[src.index('function saveEditModal('):]
    return fn[:fn.index('\nfunction ')]


def _no_comments(js):
    """把註解拿掉再掃。

    ★★ 這一刀是被自己咬到才加的：我在註解裡寫了「不要在這裡自己減 1911」，
       而那條斷言掃的是「有沒有出現 1911」—— 於是**一段正確的程式碼**
       被它自己的說明判定成作弊。

       CLAUDE.md 記過反過來的那一次（註解讓錯的程式碼通過）。兩個方向
       都是同一件事：**掃原始碼的斷言要先把不是程式碼的東西拿掉**。
    """
    js = re.sub(r'/\*[\s\S]*?\*/', '', js)
    return re.sub(r'^\s*//.*$', '', js, flags=re.M)


#  這幾種沒有自己的分支是**對的** —— 它們就是預設的文字框。
#  ★ 列出來是為了讓「漏寫」跟「刻意共用」分得開。沒有這份白名單的話，
#    這條測試只能整條放寬，等於沒守。
FALLS_BACK_TO_TEXT = {
    'text': '本來就是文字框',
    'number': '預設分支會依型別給 type=number',
    'date': '預設分支會依型別給 type=date',
    #  身分證字號在**伺服器**驗檢查碼（_reject_bad_id_numbers），
    #  存不進錯的號碼。彈窗少了即時提示只是少一層方便，不會存進壞資料。
    'id_number': '伺服器驗檢查碼，文字框存不進錯的號碼',
}


@pytest.mark.parametrize('field_type',
                         sorted(set(FIELD_TYPES) - set(FALLS_BACK_TO_TEXT)))
def test_the_edit_modal_has_a_branch_for_every_field_type(field_type):
    """★★ 少一個分支 ＝ 那種欄位在彈窗裡變成普通文字框，而畫面完全正常。"""
    body = _modal_body()
    #  分支可能是 `== 'fee'` 也可能是共用的 `in ['radio', 'fee']`
    branch = re.search(r"field\.field_type\s+in\s+\[([^\]]*)\]", body)
    shared = branch.group(1) if branch else ''
    assert f"field.field_type == '{field_type}'" in body \
        or f"'{field_type}'" in shared, (
        f'編輯彈窗沒有處理「{FIELD_TYPES[field_type]}」（{field_type}）—— '
        f'它會掉到最後的 else 變成普通文字框，同工只能手打')


def _branch(body, marker):
    """切出某一個 jinja 分支的內容（到下一個 {% elif / {% else 為止）。"""
    i = body.index(marker)
    rest = body[i:]
    ends = [rest.index(t) for t in ('{% elif', '{% else') if t in rest]
    return rest[:min(ends)] if ends else rest


def test_a_tiered_fee_field_has_both_of_its_shapes():
    """★★★ 分級收費有**兩種畫法**，缺一個就有一半的活動壞掉：

      開了「依生日自動判定」→ 不列選項，畫自動判定那一格
      沒開                  → 列出帶價格的選項

    ★ 這一條是 mutation 測試逼出來的：上面那個通用迴圈只要求
      「fee 有出現在某個分支」，所以**拿掉任何一種**它都還是綠的 ——
      而少掉的那一種就是掉回文字框。
      （tests/test_preview_auto_tier.py 記過同一件事：旗標式的分歧，
        「每一種型別都有分支」那種測試天生蓋不到。）
    """
    body = _modal_body()
    assert "field.field_type == 'fee' and (field.auto_tier or {}).enabled" in body, \
        '開了自動判定的分級收費沒有自己的分支'
    assert "_auto_tier_field.html" in _branch(
        body, "field.field_type == 'fee' and (field.auto_tier or {}).enabled"), \
        '自動判定那一格沒有走共用的 markup'

    shared = _branch(body, "field.field_type in ['radio', 'fee']")
    assert 'field_options(' in shared, '沒開自動判定的分級收費沒有列出選項'
    assert 'opt.price' in shared, '選項沒有顯示價格 —— 那是這個型別存在的理由'


@pytest.mark.parametrize('marker,what', [
    ("field.field_type in ['radio', 'fee']", '單選／分級收費'),
    ("field.field_type == 'select'", '下拉'),
])
def test_every_trigger_field_re_evaluates_the_conditions(marker, what):
    """★★ 跳題的觸發型別（`TRIGGER_TYPES`）改變時要重算。

    ★ 這一條也是 mutation 逼出來的：只檢查「evaluateConditions 有出現」
      的話，**兩個分支拿掉任何一個**都還是綠的 —— 而少掉的那一個
      就是「選了那一項，該出現的欄位沒有出現」。
    """
    branch = _branch(_modal_body(), marker)
    assert 'evaluateConditions(' in branch, \
        f'{what}改變時沒有重算跳題 —— 該出現的欄位不會出現'


def test_every_fallback_type_says_why():
    """★ 白名單要寫理由。只有一份名單的話，下次有人為了讓測試變綠
    就把型別加進去 —— 而那正是這條測試要防的事。"""
    for t, why in FALLS_BACK_TO_TEXT.items():
        assert t in FIELD_TYPES, f'{t} 已經不是有效的型別了'
        assert len(why) > 6, f'{t} 沒有寫清楚為什麼可以退回文字框'


# ══ 共用那幾份 markup，不要自己再畫一次 ═════════════════

@pytest.mark.parametrize('partial,why', [
    ('_auto_tier_field.html', '依生日自動判定'),
    ('_guardian_field.html', '監護人姓名＋電話'),
    ('_roc_date_field.html', '民國生日'),
])
def test_it_reuses_the_shared_markup(partial, why):
    """★★ 這三種都不是「一個輸入框」，而是一組互相牽動的元素。

    自己再畫一份的話，class 打錯一個字那個功能就在這個入口整個消失 ——
    而畫面上看起來只是「怎麼沒反應」。（`.roc-echo` vs `.roc-hint`
    那次就是這樣。）
    """
    body = _modal_body()
    assert f"include '{partial}'" in body, f'{why}沒有共用那一份 markup'


# ══ 行為要跟報名表單一致（使用者定的） ═════════════════
#
#  > 「後台編輯還是要跟前端報名表行為一致才對 這個我們應該上次有討論過了」
#
#  他說的「上次」是預覽那一條（CLAUDE.md：後台預覽 ＝ 報名者跑的那一份）。
#  這個彈窗是**第四個**入口，同一條規則適用。


def test_it_uses_the_shared_form_logic_instead_of_its_own():
    """★★★ 收值／填值／必填／跳題**只准有一份實作**。

    這個彈窗原本自己寫了一份「找出所有 [data-field-id] 塞值進去」，
    而那份只認得單純的輸入框。於是每一種**畫面跟儲存格式不一樣**的欄位
    都各自壞在不同的地方，四個症狀分開看都像不同的 bug：

    | 欄位 | 畫面 | 存的 | 症狀 |
    |---|---|---|---|
    | 生日 | 民國三格 | 西元 | 打開來三格是空的 |
    | 監護人 | 兩格 | 姓名／電話 | 姓名欄寫著整串 |
    | 複選 | 勾選框 | 素食、不吃牛 | 一個都沒勾 |
    | 自動判定 | 勾選框沒有 data-field-id | 標籤 | 勾過身障的人打開來沒勾 |

    最後那個最危險：**同工按下儲存就把他的申報取消掉了**，
    而畫面上完全正常，要到對帳時才發現多收了他的錢。
    """
    fn = _no_comments(_open_edit_body())
    assert 'prefillFields(' in fn, '彈窗沒有走報名表單那一份填值邏輯'

    save = _no_comments(_save_edit_body())
    assert 'collectFieldAnswers(' in save, '彈窗自己收了一份答案'
    assert 'missingRequiredFields(' in save, '彈窗沒有用共用的必填檢查'

    #  ★ 只掃**自訂欄位**那一段。外部來賓的姓名／電話是報名紀錄自己的
    #    欄位（不是活動表單的），那兩格直接讀是對的 ——
    #    不切這一刀的話，這條會對一個完全正確的版本報錯。
    #    （CLAUDE.md：掃原始碼的斷言一律要先切出該掃的那一段。）
    fields_part = save[save.index('const section ='):]
    for smell, why in [
        (':checked', '自己找選中的 radio／checkbox'),
        ("join('、')", '自己拼複選的分隔符號'),
        ("join(',')", '自己拼複選的分隔符號'),
        ('.value.trim()', '自己一格一格讀值'),
    ]:
        assert smell not in fields_part, \
            f'彈窗又自己寫了一份收值（{why}：{smell}）'


def test_the_wrappers_look_like_the_registration_form():
    """★★ 共用那幾支 JS 靠 `.field-wrapper` 和它的 data-* 找東西。

    少一個屬性，那個功能就在這個入口整個消失，而畫面上看不出來：

      data-field-type  → 收值不知道這格是什麼型別，一律當文字框
      data-condition   → 跳題永遠不成立，該藏的欄位一直在
      data-sort-order  → 跳題找不到觸發的那一題
      data-required    → 必填檢查跳過它
    """
    body = _modal_body()
    assert 'class="field-wrapper"' in body, '彈窗沒有用共用的 wrapper'
    for attr in ('data-field-type', 'data-condition',
                 'data-sort-order', 'data-field-id'):
        assert attr in body, f'wrapper 少了 {attr}'
    assert 'data-required' in body, 'wrapper 少了必填標記'


def test_the_tier_value_is_not_computed_here():
    """★★★ 身分別**不可以**在前端算。

    伺服器送出時一律重算並覆蓋（`_enforce_auto_tiers`）——
    這裡自己算一份的話，畫面顯示的和實際存進去的會不一樣，
    而兩邊分開看都正常。
    """
    fn = _no_comments(_open_edit_body())
    for cheating in ('1911', 'getFullYear()', 'new Date('):
        assert cheating not in fn, f'彈窗自己算了年齡／身分別（{cheating}）'


def test_conditional_fields_are_evaluated_here_too():
    """★★★ 跳題要真的跑。

    使用者的截圖裡，一個**民國 58 年出生**（57 歲）的人，彈窗上還印著
    「監護人姓名(未滿18歲者) 必填」—— 那題在報名表單上根本不會出現。

    ★ 而必填只對看得見的欄位成立：不跑跳題的話，同工會被擋在一個
      他畫面上根本不該有的欄位上，而他完全不知道該怎麼過關。
    """
    body = _modal_body()
    assert 'evaluateConditions(' in body, '選項改變時沒有重算跳題'
    fn = _no_comments(_open_edit_body())
    #  prefillFields 填完會自己重跑一次跳題（順序也是它管的）
    assert 'prefillFields(' in fn


def test_the_page_loads_what_the_modal_needs():
    """★ 共用的那幾支住在 form-fields.js。

    少載那一支的話，身分別那一格會永遠停在「請先填寫上面的出生日期」——
    而它旁邊的生日明明填好了，看起來就是壞掉。
    """
    src = open(ROSTER, encoding='utf-8').read()
    assert "js/form-fields.js" in src, '沒有載入共用的表單邏輯'
    assert src.index("js/form-fields.js") < src.index("js/fee-total.js"), \
        'form-fields.js 要排在 fee-total.js 之前（跟報名頁一樣）'
    assert re.search(r'body\.dataset\.eventId\s*=', src), \
        '沒有把活動 id 交給 tierRequest —— 它會直接放棄，那一格靜靜地不更新'
