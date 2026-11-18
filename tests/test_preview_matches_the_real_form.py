"""預覽的行為要**完全**跟正式填單一樣，只差在不能送出

使用者定的規則，一字不改：

    「預覽的行為要完全跟正式填單一樣 只是差在不能送出 這才是有意義的」

預覽的價值全部來自這一條。差一點點就不只是「不完整」—— 是**會騙人**：
管理員驗過了、覺得沒問題，然後上線出事。已經踩過兩次
（#226 少了分級收費的分支、#236 少了自動判定的分支）。

所以這個檔案不驗「某個功能有沒有做」，驗的是**兩邊有沒有分岔**。

## 這一輪照這條規則掃出來的三件事

1. ★ `toggleOtherText` **只定義在 external_register.html 裡**，而
   event_detail.html（會員報名／幫別人報名兩份）也在 onchange 呼叫它
   → 會員報名頁每次點「其他（請填寫）」都是 ReferenceError，
     那個文字框永遠不出現。**這是正式報名頁的 bug，不是預覽的。**

     沒有人回報，因為畫面完全正常：選項選得到、看得見選中，只是旁邊
     該冒出來的輸入框沒有 —— 使用者會以為「其他」本來就不用填。
     送出時收到的答案是「其他」兩個字，名冊上就長那樣。

2. 預覽的生日提示掛在自己發明的 `.roc-echo` 上，而 `syncRocDate` 寫的是
   `.roc-hint` → 報名者看得到的驗證訊息（「這一天不存在」「年份看起來
   不對」「出生日期不能是未來」）在預覽裡一個都不出現。管理員在預覽
   填 2 月 30 日，畫面什麼都不說。

3. 預覽對收費欄位多擋了一層「不畫其他」。真表單只看選項裡有沒有
   `__other__` → 舊活動的收費欄位真的可能帶著它，報名者選得下去而
   金額算不出來，但預覽看不到那個問題。

★ mutation 驗過：
  - toggleOtherText 搬回模板 → test_toggle_other_text_is_defined_once 紅
  - 某個入口不載入共用模組 → test_every_caller_loads_the_module 紅
  - 預覽的生日 hint 改回 .roc-echo → test_preview_birthday_uses_the_same_hint 紅
  - previewChanged 自己寫回顯 → test_preview_does_not_reimplement_feedback 紅
  - 預覽的「其他」條件多加 type !== 'fee' → test_preview_other_option_matches 紅
"""
import glob
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHARED = 'static/js/form-fields.js'

# 三個報名入口 + 後台預覽 —— 四個地方跑的必須是同一份
ENTRY_POINTS = ('templates/event_detail.html',
                'templates/external_register.html',
                'templates/admin/event_form.html')


# ★ 掃描前一定要先剝註解 —— 這坑專案裡踩過五次了：測試在掃「程式碼裡
#   有沒有 X」，而我自己在旁邊寫「不可以用 X」的註解，於是抓到自己的說明。
#   共用 test_dom_ids 那一份（它處理了「JS 註解只能在 <script> 裡剝」
#   那個更難的問題），再多剝一層 HTML 註解。
_HTML_COMMENT = re.compile(r'<!--[\s\S]*?-->')


def _src(rel):
    from tests.test_dom_ids import _strip_comments
    raw = (ROOT / rel).read_text(encoding='utf-8')
    return _HTML_COMMENT.sub('', _strip_comments(raw))


def _templates():
    return [p for p in glob.glob(str(ROOT / 'templates' / '**' / '*.html'),
                                 recursive=True)]


def _preview_changed():
    return _src('templates/admin/event_form.html') \
        .split('function previewChanged')[1].split('\n}')[0]


# ── 1. 共用的東西只准有一份，而且呼叫它的人要載得到 ──────────────────────────

def test_toggle_other_text_is_defined_once():
    """★★ 這條守的是一個**正式報名頁**的 bug。

    原本這支只定義在 external_register.html 裡。event_detail.html 呼叫了
    四次卻沒有任何定義 —— 會員報名頁點「其他」就是 ReferenceError。
    """
    assert 'window.toggleOtherText' in _src(SHARED), \
        '共用模組裡沒有 toggleOtherText'
    for path in _templates():
        body = _src(str(Path(path).relative_to(ROOT)))
        assert not re.search(r'function\s+toggleOtherText', body), \
            f'{Path(path).name} 又自己定義了一份 —— 兩份遲早會不一樣'


def test_every_caller_loads_the_module():
    """★ 呼叫了但沒載入 → ReferenceError，而畫面完全正常。

    這正是上面那個 bug 的形狀：那個選項照樣選得到、看得見選中，
    只是該冒出來的東西沒冒出來。
    """
    for path in _templates():
        body = _src(str(Path(path).relative_to(ROOT)))
        if 'toggleOtherText(' not in body:
            continue
        rel = str(Path(path).relative_to(ROOT))
        assert 'js/form-fields.js' in body, \
            f'{rel} 呼叫了 toggleOtherText 卻沒載入共用模組'


@pytest.mark.parametrize('entry', ENTRY_POINTS)
def test_no_entry_point_reimplements_the_shared_helpers(entry):
    """收值／必填／跳題／其他文字框開合 —— 誰再自己寫一份就會紅。"""
    body = _src(entry)
    for fn in ('getWrapperValue', 'isFieldFilled', 'evaluateConditions',
               'collectFieldAnswers', 'missingRequiredFields', 'toggleOtherText',
               'syncOtherTexts'):
        assert not re.search(r'function\s+' + fn + r'\s*\(', body), \
            f'{entry} 自己定義了 {fn}'


# ── 2. 預覽不可以自己做「報名者會看到的回饋」 ──────────────────────────

def test_preview_birthday_uses_the_same_hint_element():
    """★ syncRocDate 把驗證訊息寫進 .roc-hint。

    預覽自己掛一個 .roc-echo 的話，那些訊息在預覽裡一個都不出現 ——
    管理員填 2 月 30 日、填未來的日期，畫面什麼都不說，
    而報名者會看到紅字。
    """
    assert "querySelector('.roc-hint')" in _src('static/js/fee-total.js'), \
        '前提變了：syncRocDate 不再寫 .roc-hint'
    preview = _src('templates/admin/event_form.html')
    body = preview.split('function openPreview')[1].split('\nfunction ')[0]
    assert 'roc-hint' in body, '預覽的生日沒有 .roc-hint —— 看不到驗證訊息'
    assert 'roc-echo' not in preview, '又自己發明了一個回顯元素'


def test_preview_does_not_reimplement_feedback():
    """★ previewChanged 只准「呼叫」共用的東西，不准自己算。

    自己寫的話，格式會跟真表單不一樣（例如回顯成 1999-03-05 而不是
    「＝ 西元 1999 年 3 月 5 日」），而兩邊看起來都正常。
    """
    fn = _preview_changed()
    assert '.roc-iso' not in fn, 'previewChanged 又自己讀生日算回顯了'
    assert 'textContent' not in fn, 'previewChanged 又自己寫畫面上的文字了'
    # 該呼叫的都要呼叫到
    for call in ('syncOtherTexts', 'evaluateConditions',
                 'refreshAgeConditions', 'updateFeeTotal'):
        assert call in fn, f'previewChanged 沒有跑 {call}'


def test_preview_other_option_matches_the_real_form():
    """★ 真表單的 radio/fee 分支只看「選項裡有沒有 __other__」，不看型別。

    舊活動的收費欄位真的可能帶著它（那是設定問題：自由填的答案對不到
    價格）。預覽多擋一層的話，那個問題在預覽裡看不到，
    而報名者選得下去、金額算不出來。
    """
    real = _src('templates/event_detail.html')
    assert "'__other__' in field.options" in real, '前提變了：真表單改過'
    body = _src('templates/admin/event_form.html') \
        .split('function openPreview')[1].split('\nfunction ')[0]
    assert "type !== 'fee' && hasOther" not in body, \
        '預覽比真表單多擋了一層 —— 收費欄位的設定問題在預覽裡看不到'
    assert 'if (hasOther)' in body


# ── 3. 「只差在不能送出」 ──────────────────────────

def test_the_only_difference_is_that_it_does_not_submit():
    """預覽的送出鍵跑真的必填檢查，但不打 API。

    ★ 真的送出去的話，管理員按一按就會在正式名單裡多出幾筆測試資料，
      而且看起來跟真的報名一模一樣。
    """
    src = _src('templates/admin/event_form.html')
    fn = src.split('function previewSubmit')[1].split('\n}')[0]
    assert 'missingRequiredFields' in fn, '預覽的送出沒有跑真的必填檢查'
    assert 'fetch(' not in fn, '預覽的送出真的打了 API'
    assert '不會真的報名' in src, '按鈕上沒有講清楚它不會送出'


# ── 送出摘要也要是同一份 ──────────────────────────

def test_the_preview_summary_is_the_real_confirm_component():
    """★★ 預覽自己拼摘要時漏掉了轉換：生日存的是西元，但欄位叫
    「出生年月日(民國)」—— 預覽印出「出生年月日(民國)：1989-09-01」，
    標題說民國、數字是西元。

    報名者的確認頁一直是對的（民國 78 年 9 月 1 日），因為
    form-confirm.js 的 display() 會照著畫面上那三個框轉回民國。
    只有預覽在說謊 —— 而管理員正是拿預覽在驗「報名者會看到什麼」。
    """
    src = _src('templates/admin/event_form.html')
    fn = src.split('function previewSubmit')[1].split('\n}')[0]
    assert 'buildAnswerSummary' in fn, '預覽的摘要不是報名者確認頁那一份'
    # 自己組「標籤：答案」就是又寫了一份
    assert '：${' not in fn and "'：'" not in fn, \
        '預覽又自己拼了一次摘要 —— 那份不會做民國轉換'




