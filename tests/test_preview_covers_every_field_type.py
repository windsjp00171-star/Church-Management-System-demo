"""預覽表單：每一種欄位型別都要有自己的分支

## 事故

「分級收費」「出生日期」「身分證字號」三種型別，後台下拉有、前台渲染有、
送出有、名冊有、資料庫約束也放寬了 —— **就是預覽表單那支 openPreview 沒有**。

它的 if/else 鏈沒有這三個分支，全部掉到最後的 else，
所以預覽出來是三個普通文字框。使用者的原話：「我看不到身分別的選項」。

★ 為什麼特別糟：預覽存在的**唯一理由**就是「告訴你報名者會看到什麼」。
  它答錯的時候不會像壞掉，會像「這個功能沒設定成功」——
  使用者於是回去重設一次、再重設一次，而每次預覽都一樣。

## 這裡守什麼

FIELD_TYPES 是單一來源（routes/field_types.py）。下次再加型別，
只要漏了預覽這一支，這條就會紅 —— 不必等有人開預覽才發現。

刻意用「型別字串有沒有出現在 openPreview 的函式體裡」來判斷，
不是解析 JS。夠粗但抓得到真正會發生的錯（整個分支忘了寫）。
"""
import re

import pytest

from routes.field_types import FIELD_TYPES

FORM = 'templates/admin/event_form.html'


def _src():
    return open(FORM, encoding='utf-8').read()


def _fn(name):
    """切出某個 top-level function 的函式體。"""
    src = _src()
    start = src.index(f'function {name}(')
    rest = src[start + 1:]
    end = rest.index('\nfunction ')
    return rest[:end]


def _open_preview_body():
    """切出 openPreview() 的函式體 —— 到下一個 top-level function 為止。"""
    src = _src()
    start = src.index('function openPreview()')
    rest = src[start + 1:]
    end = rest.index('\nfunction ')
    return rest[:end]


# 這幾種沒有自己的分支是**對的**：它們就是預設的文字框。
# 列在這裡是為了讓「漏寫」跟「刻意共用」分得開 ——
# 沒有這份白名單的話，測試只能整條放寬，等於沒守。
FALLS_BACK_TO_TEXT = {'text'}


@pytest.mark.parametrize('field_type', sorted(set(FIELD_TYPES) - FALLS_BACK_TO_TEXT))
def test_preview_has_a_branch_for_every_field_type(field_type):
    """★ 少一個分支 = 那種欄位在預覽裡變成普通文字框，而畫面完全正常。"""
    body = _open_preview_body()
    assert f"type === '{field_type}'" in body, (
        f'預覽表單沒有處理「{FIELD_TYPES[field_type]}」（{field_type}）—— '
        f'它會掉到最後的 else 變成普通文字框')


def test_fee_preview_shows_the_prices():
    """分級收費的重點就是金額。只列出名稱的話等於沒回答使用者的問題。"""
    body = _open_preview_body()
    fee = body[body.index("type === 'fee'"):]
    fee = fee[:fee.index('} else if')]
    assert 'optionPrice(' in fee, '預覽沒把金額拆出來'
    assert '應繳金額' in fee, '預覽沒有顯示合計 —— 那是這個型別存在的理由'


def test_legacy_priced_options_still_show_their_price():
    """★ 「分級收費」型別出現之前，價格是寫在單選／下拉的選項裡（成人|800）。

    舊活動還帶著那種資料，前台照樣會把金額顯示出來。預覽不跟著顯示的話，
    看起來就像價格掉了 —— 使用者會回去「修好」一個沒壞的東西。
    """
    body = _open_preview_body()
    for kind in ('radio', 'select'):
        chunk = body[body.index(f"type === '{kind}'"):]
        chunk = chunk[:chunk.index('} else if')] if '} else if' in chunk else chunk
        assert 'optionPrice(' in chunk, f'{kind} 的預覽沒帶出選項價格'


def test_preview_strips_the_pipe_syntax_from_labels():
    """★ 選項存的是「成人|800」，那是儲存格式不是給人看的。

    預覽直接把整行印出來的話，會顯示「成人|800」——
    使用者以為自己把選項名稱打錯了。
    """
    body = _open_preview_body()
    assert 'optionLabel(' in body, '預覽沒把標籤跟價格拆開'


# ── 舊活動的價格：光是打開編輯頁就被洗掉 ──────────────────────────

def test_sync_keeps_prices_on_non_fee_fields():
    """★ 這條守一個會**憑空少收錢**的 bug。

    「分級收費」型別是後來才有的。在那之前，價格就是寫在單選／下拉的選項裡
    （成人|800），前台到現在都還照樣把金額算出來、收出來。

    syncOptionRows 原本對非收費型別無條件只寫回標籤。而載入頁面時
    addOptionRow 每加一列就會叫一次 sync —— 也就是說：

        打開舊活動的編輯頁 → 價格當場被洗掉 → 按儲存 → 那場活動從此不收錢

    使用者什麼都沒做，畫面上四個選項名稱一字不差。
    """
    src = _src()
    body = src[src.index('function syncOptionRows'):]
    body = body[:body.index('\n// ==')]
    assert 'if (!fee) { lines.push(label); return; }' not in body, \
        '非收費型別的選項價格又被無條件丟掉了'
    assert "raw === '' ? label : label + '|'" in body, \
        '非收費型別要保留既有價格，只有真的沒價格才寫回純標籤'


def test_price_box_is_visible_whenever_there_is_a_price():
    """★ 金額框藏起來、但那個值還在被儲存，是最糟的組合 ——
    使用者看不到也改不到一個正在生效的價格。

    有價格就要看得見，不管型別是不是「分級收費」。
    """
    src = _src()
    body = src[src.index('function applyOptionMode'):]
    body = body[:body.index('\nfunction ')]
    assert 'hasPrice' in body, '金額框的顯示條件只看型別，沒看有沒有價格'
    assert '(fee || hasPrice)' in body


def test_birthday_preview_is_in_roc_years():
    """前台收民國年。預覽長成西元的話，會以為報名者得自己換算。"""
    body = _open_preview_body()
    bd = body[body.index("type === 'birthday'"):]
    bd = bd[:bd.index('} else if')]
    assert '民國' in bd


def test_preview_reads_the_same_storage_as_submit():
    """★ 選項的真正儲存處是隱藏的 .f-options，由 syncOptionRows 寫入。

    預覽沒先同步的話會讀到舊值 —— 畫面正常，只是跟實際會存的東西不一樣，
    而這種不一致要等活動上線才會被發現。
    """
    body = _open_preview_body()
    assert 'syncOptionRows(row)' in body, '預覽沒有先同步選項，可能讀到舊值'


def test_preview_labels_conditional_fields():
    """★ 跳題在預覽裡要**真的會動**（選了孩童，監護人才冒出來）。

    原本是靜態預覽，只在旁邊標一行「只在…時才會出現」。但使用者想確認的
    正是「它到底會不會冒出來」—— 那是互動的結果，看一張靜止的圖看不出來。

    做法是把條件還原成前台看得懂的 condition_json 放進 data-condition，
    然後叫同一支 evaluateConditions。
    """
    src = _src()
    assert 'function previewConditionJson' in src
    body = _open_preview_body()
    assert 'previewConditionJson(row)' in body, '預覽沒有把跳題條件放進 DOM'
    assert 'dataset.condition' in body, '預覽的 wrapper 沒帶 data-condition'


def test_incomplete_condition_is_called_out():
    """條件勾了但沒選完 = 那題永遠不顯示。這是真的會發生的設定錯誤，
    而且完全沒有徵兆 —— 活動上線後那題就是不出現。

    這種情況下 condition_json 是空的（不然會產生一條對不到的條件），
    所以要另外講一句，否則預覽裡那題會正常顯示，看起來一切都好。
    """
    src = _src()
    note = src[src.index('function previewBrokenCondition'):]
    note = note[:note.index('\nconst PV_ON')]
    assert 'trigger' not in note or 'isNaN' in note
    body = _open_preview_body()
    # conditionProblem() 回的是「哪裡不對」的字串，previewBrokenCondition
    # 只是它的 boolean 包裝 —— 預覽用前者才講得出原因
    assert 'conditionProblem(row)' in body
    assert 'escHtml(condProblem)' in body, '預覽沒有把原因印出來'

    # ★ 訊息不可以再寫死一個後果。兩種問題的後果是**相反**的：
    #   沒設完 → condition_json 存成 null → 等於沒有條件 → 每個人都看到
    #   範圍寫反 → 條件成立不了 → 那題永遠不出現
    #   寫死成「永遠不顯示」的話，其中一種是反的，而預覽當下就自相矛盾
    #   （畫面上那題明明看得到，底下卻寫著「等於永遠不顯示」）。
    assert '永遠不顯示' not in body, \
        '預覽把後果寫死了 —— 條件沒設完時那題其實是對每個人顯示'
    fn = _src().split('function conditionProblem')[1].split('\n}\n')[0]
    assert '每個人都會看到' in fn, '沒設完的後果講錯了'
    assert '永遠不會出現' in fn, '範圍寫反的後果沒講'


# ── 預覽要跑報名者跑的那一份 ──────────────────────────



def test_preview_does_not_reimplement_the_engine():
    """誰在後台又自己寫一份，兩份就會開始各自演化。"""
    src = _src()
    for fn in ('function getWrapperValue', 'function evaluateConditions'):
        assert fn not in src, f'預覽又自己定義了一份 {fn}'


def test_preview_fields_are_actually_fillable():
    """★ 全部 disabled 的預覽答不出使用者真正想確認的事：
    「選了孩童，監護人會不會冒出來」「選了敬老，金額會不會變 600」。"""
    body = _open_preview_body()
    assert 'disabled' not in body, '預覽的欄位還是 disabled，填不了'


def test_preview_wrappers_carry_what_the_engine_needs():
    """少一個屬性，跳題或收值就會靜靜地不動作，而畫面完全正常。"""
    body = _open_preview_body()
    for attr in ('dataset.sortOrder', 'dataset.fieldType', 'dataset.fieldId',
                 'dataset.condition'):
        assert attr in body, f'預覽的 wrapper 少了 {attr}'
    assert "className = 'field-wrapper'" in body, '預覽沒有用 .field-wrapper'


def test_preview_submit_does_not_post():
    """「試按送出」只能做檢查，不能真的建立報名。"""
    fn = _fn('previewSubmit')
    assert 'fetch(' not in fn, '預覽的送出真的打了 API'


def test_fee_options_carry_the_price_for_the_engine():
    """★ 金額是 fee-total.js 從 data-price 讀的。
    只把 $800 印在畫面上、沒放進 data-price 的話，
    看得到價格但應繳金額永遠是 0。"""
    body = _open_preview_body()
    assert 'data-price=' in body


# ── 那行永遠亮著的 ⚠ ──────────────────────────

def test_the_condition_hint_hides_once_it_is_satisfied():
    """★ 那行「觸發問題需為單選／下拉選單／分級收費」原本是永遠顯示的，
    條件設好了也還在。

    一個永遠亮著的警告會被學會忽略 —— 等哪天它真的在警告你
    （觸發問題被改成文字型別、選項被清空，下拉整個變空的），
    你不會注意到，因為它跟平常長得一模一樣。
    """
    src = _src()
    assert src.count('class="cond-hint"') == 2, \
        '兩份（既有欄位／新增欄位）都要掛上 class，少一份就有一半沒修到'
    trigger = src[src.index('function rebuildTriggerDropdown'):]
    trigger = trigger[:trigger.index('\nfunction ')]
    assert '.cond-hint' in trigger, '沒有人去收起那行 ⚠'
    assert 'triggerSelect.options.length > 1' in trigger, \
        '判斷依據應該是「下拉裡真的有東西可選」'


def test_the_hint_lists_exactly_the_types_that_can_trigger():
    """★ 說明文字跟實際能觸發的型別不一致的話，使用者會照著說明去找
    一個不存在的選項（或反過來，以為某個型別不能用而繞路）。"""
    from routes.field_types import TRIGGER_TYPES
    src = _src()
    hint = re.search(r'⚠️ 觸發問題需為(.+?)。', src).group(1)
    # ★ 比對要連「」一起比。純子字串比的話，「出生日期」裡含著「日期」，
    #   下面那個反向斷言會誤判成「說明列了不能觸發的『日期』型別」——
    #   而那是一個正確的改動被測試擋下來，最容易被改成放寬測試。
    for t in TRIGGER_TYPES:
        assert f'「{FIELD_TYPES[t]}」' in hint, \
            f'說明沒提到可以用「{FIELD_TYPES[t]}」觸發'
    # 反過來也要對：說明列了一個實際上不能用的型別，使用者會建好一整題
    # 才發現它沒出現在觸發下拉裡。
    for t in set(FIELD_TYPES) - set(TRIGGER_TYPES):
        assert f'「{FIELD_TYPES[t]}」' not in hint, \
            f'說明列了「{FIELD_TYPES[t]}」，但 TRIGGER_TYPES 不收它'
