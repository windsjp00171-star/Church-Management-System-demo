"""「這一題每個人都要填」—— 一個以前表達不出來的答案

## 這一條在解什麼

監護人欄位的預設是「只問未滿 18 歲的人」，而那條條件是**伺服器在存檔時
自動補的**（`_apply_guardian_conditions`）：沒有 `condition_json` 就補。

所以「兒童營全部都要填」這種活動，管理員唯一想得到的做法是**把條件清掉**
—— 而清掉正是「沒有 condition_json」，存檔時系統把「未滿18歲」補回去。

    他清掉 → 存檔成功 → 後台看起來設好了 → 預覽也正常（預覽補同一條）
    → 只有 18 歲以上的人打開報名表時那一題不出現

**沒有人會發現。** 沒有任何一個畫面會說「這場活動有 40 個成人跳過了監護人」。
而後台那一頁、預覽、報名表，三個地方各自看都完全正常。

★ 更糟的是後台的說明文字**明講**「要換成別的規則（例如全部都要填）就照
  下面的跳題面板設」—— 而跳題面板只能設「比答案」和「比年齡」兩種條件，
  兩種都不是「所有人」。系統在教管理員做一件做不到的事。

## 做法：一個存得下來的印記

`{"auto": "everyone"}`（`routes/guardian.everyone_condition`）。它沒有
trigger，所以求值器**就算不認得它也會顯示** —— 但兩邊仍各寫一條明確的
分支，理由寫在那兩個地方：靠「壞掉時的預設剛好正確」跟「刻意這樣做」
在程式碼裡長得一模一樣，而收緊那個預設是一個看起來很合理的改動。

★ mutation 驗過（實際測到的，不是預期的）：
  - `needs_auto` 的 `== MINOR` 放寬成「有 auto 印記就重新產生」
    → 印記被蓋掉那兩條紅
  - `form-fields.js` 的分支改成 `display='none'`、或整條刪掉 → JS 那兩條紅
  - 模板不存印記（回空字串）→ 「勾了要存下去」那條紅
  - 編輯頁不還原勾勾 → 對應那條紅
  - `conditions.py` 拿掉明確分支 → **行為測試全綠**（沒有 trigger 的條件
    本來就落到「維持顯示」）。所以另外寫了
    `test_both_evaluators_name_the_mark_explicitly` 守它 —— 那一條是唯一
    會紅的。理由見那條的 docstring。

★ 我第一版在 `needs_auto` 開頭加了一段「是 everyone 就 return False」，
  mutation 一跑才發現**那是死程式碼**：everyone 本來就不等於 minor，
  既有的「只重新產生自己補的那條」已經涵蓋了。刪掉了。
"""
import json
from pathlib import Path

import pytest


from routes.conditions import missing_required, visibility
from routes.guardian import (EVERYONE, MINOR, condition_mark,
                             everyone_condition)

ROOT = Path(__file__).resolve().parent.parent
FORM = ROOT / 'templates' / 'admin' / 'event_form.html'
JS = ROOT / 'static' / 'js' / 'form-fields.js'


def _guardian(cond=None, required=True):
    return {'id': 'f-guard', 'label': '緊急聯絡人', 'field_type': 'guardian',
            'sort_order': 1, 'is_required': required,
            'condition_json': cond}


def _birthday():
    return {'id': 'f-birth', 'label': '出生年月日', 'field_type': 'birthday',
            'sort_order': 0, 'is_required': True}


# ══ 一、印記本身 ═══════════════════════════════════

def test_the_two_marks_are_different_things():
    assert MINOR != EVERYONE


def test_the_mark_reads_back_from_both_shapes():
    """★ 資料庫拿回來的是**字串**，前端送上來的是 dict —— 兩種都要認得。

    只認 dict 的話，編輯一場已經存好的活動時印記讀不出來，
    而症狀是「打開編輯頁、什麼都沒動、存檔，它就變回未滿18歲」。
    """
    cond = everyone_condition()
    assert condition_mark(cond) == EVERYONE
    assert condition_mark(json.dumps(cond)) == EVERYONE


@pytest.mark.parametrize('raw', [
    None, '', '{}', 'not json', '[]',
    json.dumps({'trigger_sort_order': 0, 'trigger_value': '孩童'}),
])
def test_anything_else_is_not_a_mark(raw):
    assert condition_mark(raw) is None


def test_the_mark_has_no_trigger():
    """★ 「每個人都問」在資料上就是「沒有條件」。多帶一個假的 trigger
    的話，那個 index 會在欄位順序改過之後指到別的問題上。"""
    cond = everyone_condition()
    assert 'trigger_sort_order' not in cond
    assert 'trigger_value' not in cond
    assert 'op' not in cond


# ══ 二、存檔時不可以被蓋掉 ═══════════════════════════













# ══ 三、伺服器求值：每個人都看得到 ═══════════════════

EVENT = {'event_start': '2026-10-09T01:00:00+00:00'}


def _seen(cond, birthday_answer):
    fields = [_birthday(), _guardian(json.dumps(cond))]
    answers = [{'field_id': 'f-birth', 'answer': birthday_answer}]
    return visibility(fields, answers, EVENT)['f-guard']


def test_the_adult_sees_it():
    """★★ 這就是它跟預設那條的差別 —— 預設那條對成人是不顯示的。"""
    assert _seen(everyone_condition(), '1980-01-01') is True


def test_the_child_sees_it_too():
    assert _seen(everyone_condition(), '2018-01-01') is True


def test_someone_with_no_birthday_at_all_sees_it():
    """★★★ 最重要的一條。

    年齡算不出來時，年齡條件的行為是**藏起來**（兩邊都是）。
    「每個人都問」如果走年齡那條路（例如用 0～200 歲的假範圍去模擬），
    沒填生日的人就會看不到那一題 —— 而那正是最需要留監護人的那種資料
    不齊的報名。所以它一定不能是年齡條件。
    """
    assert _seen(everyone_condition(), '') is True


def test_the_default_really_does_hide_it_from_adults():
    """★ 對照組。這條要是也回 True，上面那幾條就什麼都沒驗到。"""
    minor = {'trigger_sort_order': 0, 'op': 'age_between',
             'min': None, 'max': 17, 'auto': MINOR}
    assert _seen(minor, '1980-01-01') is False


def test_required_is_then_enforced_on_the_adult():
    """★★ 看得見才有必填。這一條把兩件事接起來：
    勾了「每個人都要填」的活動，成人沒填監護人**送不出去**。"""
    fields = [_birthday(), _guardian(json.dumps(everyone_condition()))]
    answers = [{'field_id': 'f-birth', 'answer': '1980-01-01'}]
    assert '緊急聯絡人' in missing_required(fields, answers, EVENT)


def test_the_name_only_answer_is_still_not_enough():
    """★ 監護人要姓名＋電話都有（既有規則，順便確認沒被繞過）。"""
    fields = [_birthday(), _guardian(json.dumps(everyone_condition()))]
    answers = [{'field_id': 'f-birth', 'answer': '1980-01-01'},
               {'field_id': 'f-guard', 'answer': '王小明'}]
    assert '緊急聯絡人' in missing_required(fields, answers, EVENT)


# ══ 四、兩邊都要有**明確**的分支 ═════════════════════

def test_both_evaluators_name_the_mark_explicitly():
    """★★★ 這一條守的是「為什麼要多寫一行」。

    印記沒有 trigger，所以求值器**就算不認得它，也會落到
    「找不到觸發問題 → 維持顯示」而給出正確答案**。
    實際 mutation 的結果：把 `conditions.py` 那一段刪掉，
    **所有行為測試都還是綠的** —— 只有這一條會紅。

    但那代表這個功能是**靠壞掉時的預設行為活著**的。而「一個指向空氣的
    條件應該藏起來」是一個看起來很合理的收緊 —— 那天兒童營的監護人
    會從報名表上整個消失，而後台完全看不出來。
    """
    py = (ROOT / 'routes' / 'conditions.py').read_text(encoding='utf-8')
    fn = py[py.index('def _is_visible'):py.index('def visibility')]
    assert 'EVERYONE' in fn, 'conditions.py 沒有「每個人都問」的明確分支'

    js = JS.read_text(encoding='utf-8')
    ev = js[js.index('window.evaluateConditions'):]
    ev = ev[:ev.index('window.clearWrapper')]
    assert "cond.auto === 'everyone'" in ev, \
        'form-fields.js 沒有「每個人都問」的明確分支'




# ══ 五、表單上的即時提示要跟著改口 ═══════════════════

def _ctx(fields):
    return {'event': {}, 'fields': fields, 'primary_groups': ['小組A']}








# ══ 六、後台設得起來（不然上面全部是死程式碼）═════════

CODE = FORM.read_text(encoding='utf-8')










def test_the_condition_panel_is_still_there():
    """★ 既有規則：面板不可以因為多了這個勾勾就被拿掉 ——
    「選了獨木舟才問」那種活動還是要設得起來。"""
    assert 'condition-section' in CODE
    assert 'f-has-condition' in CODE




