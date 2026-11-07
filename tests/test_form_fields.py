"""報名表單的收值／必填／跳題：只准有一份實作

## 事故（使用者的活動，正式環境）

同一套表單有三個入口：會員報名、幫別人報名、外部報名。原本每一份各寫各的，
於是它們**已經長得不一樣了**，而且是靜靜地不一樣：

  ✗ 外部報名的收值只認 radio，不認 fee
    → 選了「成人 $800」，collectAnswers() 收到的 answer 是空字串
    → 必填檢查用同一套判斷，所以也算成「沒填」
    → 永遠跳「請填寫所有必填欄位」，**整張表單送不出去**

  ✗ 外部報名的跳題用 cond.trigger_field_id 找觸發問題，
    但後台存進 condition_json 的只有 trigger_sort_order
    → 永遠找不到 → 跳題整個不生效 → 該藏的欄位一直露著
    → 而它還是必填，於是又多擋一道

★ 為什麼沒有人回報：畫面完全正常。四個選項選得到、看得見選中，
  右邊的應繳金額還正確顯示 $800。使用者看到的只是
  「我明明都填了，它說我沒填」—— 那看起來像自己操作錯。

## 這裡守的是「只有一份」

三個入口都必須用 static/js/form-fields.js。誰再自己寫一份，
這裡就會紅 —— 因為分歧本身才是 bug 的來源，不是某一份寫錯。
"""
import re

import pytest

JS = 'static/js/form-fields.js'
ENTRY_TEMPLATES = ('event_detail.html', 'external_register.html')


def _js():
    return open(JS, encoding='utf-8').read()


def _tpl(name):
    return open(f'templates/{name}', encoding='utf-8').read()


# ── 共用模組本身 ──────────────────────────

def test_fee_is_read_like_a_radio():
    """★ fee 就是帶價格的單選。漏掉它 → 落到「找 input[data-field-id]」
    的預設分支 → radio 沒有那個屬性 → 答案永遠是空字串。"""
    src = _js()
    fn = src[src.index('window.getWrapperValue'):]
    fn = fn[:fn.index('\n  };')]  # 只看收值函式；prefillFields 也有同一行，會遮住這裡被弄壞
    assert "type === 'radio' || type === 'fee'" in fn


def test_required_check_goes_through_the_same_reader():
    """★ 必填檢查另外寫一套判斷，就是「選了卻說沒選」的來源。

    只要它跟收值走同一個函式，兩者就不可能各自認得不同的型別。
    """
    src = _js()
    fn = src[src.index('window.isFieldFilled'):]
    fn = fn[:fn.index('\n  };')]
    assert 'getWrapperValue' in fn, '必填檢查沒有走同一個收值函式'


def test_conditions_match_on_sort_order():
    """後台存進 condition_json 的是 trigger_sort_order（0-based，
    跟模板的 loop.index0 對齊）。只認 trigger_field_id 的話，
    跳題會整個靜靜失效 —— 外部報名就是這樣壞了很久。

    ★ 這裡釘的是**那行比對本身**，不只是「字串有沒有出現」。
      原本只斷言 'trigger_sort_order' in src，結果把整個比對分支
      拿掉之後測試照樣綠 —— 因為註解裡也有那個字。
      （mutation 測試抓到的。）
    """
    src = _js()
    assert 'String(w.dataset.sortOrder) === String(cond.trigger_sort_order)' in src, \
        '跳題沒有用 sort order 比對觸發問題'


def test_conditions_also_tolerate_the_legacy_key():
    """舊資料可能帶 trigger_field_id。只認一種格式 → 另一種整個不生效，
    而且沒有任何徵兆。"""
    assert 'w.dataset.fieldId === cond.trigger_field_id' in _js()


def test_hidden_fields_are_cleared():
    """★ 藏起來但不清空的話，那個答案還是會被送出 ——
    送出去的是一個使用者早就看不到的選擇（而且可能還帶價格）。"""
    src = _js()
    fn = src[src.index('window.evaluateConditions'):]
    fn = fn[:fn.index('\n  };')]
    #  ★ 清空那一段抽成了 `clearWrapper` —— 後台編輯彈窗換一個人時也要
    #    用它（那個彈窗是重複使用的，不清的話會留著上一位的答案）。
    #    所以這裡驗兩件事：跳題有沒有去叫它、它有沒有真的清。
    assert 'clearWrapper(' in fn, '藏起來的欄位沒有被清空'

    #  ★ 要找**定義**不是呼叫的地方 —— 呼叫在前面，切到的會是兩行。
    clear = src[src.index('window.clearWrapper = function'):]
    clear = clear[:clear.index('\n  };')]
    assert 'checked = false' in clear
    assert "inp.value = ''" in clear
    #  ★ 畫面上那些**沒有 data-field-id** 的元素也要清 ——
    #    只清帶 data-field-id 的東西等於只清掉真的那一半：
    #    螢幕上寫著民國88年3月5日、送出的答案卻是空字串。
    for cls in ('.roc-y', '.gd-name', '.auto-tier'):
        assert cls in clear, cls + ' 沒有被清掉'


def test_invisible_fields_are_not_collected():
    """跳題藏起來的欄位不該進答案 —— 否則會送出一個沒被問過的答案。"""
    src = _js()
    fn = src[src.index('window.collectFieldAnswers'):]
    fn = fn[:fn.index('\n  };')]
    assert 'isFieldVisible' in fn


def test_invisible_required_fields_do_not_block():
    """★ 反過來也要對：藏起來的必填欄位不能擋住送出。

    「監護人姓名」只在選了孩童時才出現，成人報名時它是隱藏的 ——
    這時還要求填它的話，成人永遠報不了名。
    """
    src = _js()
    fn = src[src.index('window.missingRequiredFields'):]
    fn = fn[:fn.index('\n  };')]
    assert 'isFieldVisible' in fn


# ── 三個入口都要接上 ──────────────────────────

@pytest.mark.parametrize('name', ENTRY_TEMPLATES)
def test_every_entry_point_loads_the_shared_module(name):
    assert "asset('js/form-fields.js')" in _tpl(name), \
        f'{name} 沒有載入共用的收值／跳題模組'


@pytest.mark.parametrize('name', ENTRY_TEMPLATES)
def test_no_entry_point_redefines_the_logic(name):
    """★ 這條才是重點：分歧本身就是 bug 的來源。

    誰再自己寫一份 getWrapperValue / evaluateConditions，
    兩份就會開始各自演化，而症狀是「某一個入口靜靜地壞掉」。
    """
    src = _tpl(name)
    for fn in ('function getWrapperValue', 'function evaluateConditions'):
        assert fn not in src, f'{name} 又自己定義了一份 {fn}'


@pytest.mark.parametrize('name', ENTRY_TEMPLATES)
def test_wrappers_carry_the_sort_order(name):
    """★ 跳題比對的是 data-sort-order。少了這個屬性，條件永遠對不到，
    而畫面上只是「那一題一直都在」—— 看不出是條件沒生效。"""
    assert 'data-sort-order=' in _tpl(name), f'{name} 的 field-wrapper 沒帶 sort order'


def test_the_shared_module_loads_before_the_inline_script():
    """★ 外部報名的 inline script 最後會直接呼叫 evaluateConditions()。

    共用模組載在它後面的話是 ReferenceError —— 而那一行之後的東西
    全部不執行，整頁的表單邏輯靜靜地死掉。
    """
    src = _tpl('external_register.html')
    assert src.index("asset('js/form-fields.js')") < src.index('const eventId'), \
        '共用模組載得比 inline script 晚，evaluateConditions() 會是 ReferenceError'


# ── 錯誤訊息要講得出是哪一題 ──────────────────────────

def test_the_error_says_which_field_is_missing():
    """只說「請填寫所有必填欄位」的話，欄位一多就得自己一格一格找 ——
    而使用者多半會認為是系統壞了（這次就是）。"""
    src = _js()
    fn = src[src.index('window.missingRequiredFields'):]
    fn = fn[:fn.index('\n  };')]
    # ★ 驗的是「有沒有把欄位名稱帶出來」，不是「有沒有出現 field-label
    #   這個字串」。怎麼從 label 讀出名稱已經收成 fieldLabelText 了
    #   （必填標記要拿掉，見 tests/test_required_marker.py）——
    #   寫死選擇器的話，那個完全正確的重構會讓這條紅。
    assert 'fieldLabelText' in fn, '沒有把欄位名稱帶出來'
    reader = src[src.index('window.fieldLabelText'):]
    assert 'field-label' in reader[:400], 'fieldLabelText 沒有去讀欄位標籤'
    assert '還沒填' in _tpl('external_register.html')
