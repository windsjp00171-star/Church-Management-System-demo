"""後台預覽：開了「依生日自動判定」的收費欄位

## 事故（使用者回報，附截圖）

管理員把分級收費設好了 —— 勾了「依出生日期自動判定身分別」，四個選項
的年齡範圍、「其他年齡」、「自行申報」全部設對。按預覽，看到的是：

    身分別 *
      ○ 成人   $800
      ○ 孩童   $500
      ○ 長者   $600
      ○ 持身障證明者 $600
    應繳金額  $0

**而實際報名頁根本沒有那些選項** —— 那裡是一格「你的身分別：自動判定」。

使用者的話：「預覽的邏輯不是就讓設定者確認正式填單的狀況 才做的嗎」。
對。預覽 certify 一個不存在的行為，比沒有預覽更糟 —— 因為你會相信它。

## 根因兩層，只修一層還是假的

1. **預覽的 if/else 少了那一支**。三份報名表單都有

       {% if field.field_type == 'fee' and (field.auto_tier or {}).enabled %}
           → _auto_tier_field.html
       {% elif field.field_type in ['radio', 'fee'] %}
           → 一排選項

   預覽只有下面那支，所以一律畫成選項。
   （CLAUDE.md 那張表裡「表單預覽看不到分級收費」的同一個形狀，
     當時修的是別的分支，這一支漏了。）

2. **就算畫對了也算不出來**。`refreshAutoTiers` 沒有 event id 就直接
   return，而後台的活動可能還沒存；就算存過，改了設定還沒按儲存的話，
   打 `/event/<id>/compute-tier` 算的是**舊設定**。
   只修第 1 層的話，預覽會永遠停在「請先填寫上面的出生日期」——
   那是另一種假象。

所以加了 `POST /admin/events/preview-tier`：吃表單上的草稿設定，
**判定本身還是同一支 routes/auto_tier.resolve**。

## 為什麼舊測試抓不到

`tests/test_preview_covers_every_field_type.py` 守的是「每一種 field_type
都有分支」。但 auto_tier 是掛在 fee 上的**旗標**，不是型別 —— 那張網
天生蓋不到它。所以這裡改成守「真表單有幾種畫法，預覽就要有幾種」。

★ mutation 驗過：
  - 預覽拿掉 auto-tier 分支 → test_preview_does_not_fall_through_to_radios 紅
  - 預覽的 DOM 少一個 class（.at-hidden 等）→ test_preview_dom_matches_the_real_partial 紅
  - previewTierPayload 拿掉 → test_preview_computes_from_the_draft_config 紅
  - refreshAutoTiers 改回寫死 compute-tier → test_the_tier_endpoint_is_pluggable 紅
  - preview_tier 自己算而不走 resolve → test_the_endpoint_uses_the_one_implementation 紅
  - fallback_label 沒生效 → test_the_screenshot_case 紅
"""
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _src(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _preview_body():
    src = _src('templates/admin/event_form.html')
    return src.split('function openPreview')[1].split('\nfunction ')[0]


# ── 1. 預覽要有那一支分支 ──────────────────────────

def test_the_real_forms_have_two_ways_to_draw_a_fee_field():
    """先確認前提：真表單確實分兩種畫法。這條垮了表示前台改過，
    下面幾條的意義就要重新想。"""
    for name in ('templates/event_detail.html', 'templates/external_register.html'):
        src = _src(name)
        assert "auto_tier or {}).enabled" in src, f'{name} 沒有自動判定那一支'
        assert "_auto_tier_field.html" in src


def test_preview_does_not_fall_through_to_radios():
    """★★ 這條就是使用者回報的那個 bug。

    開了自動判定的收費欄位，預覽必須畫成「你的身分別」那一格，
    不可以掉到畫選項的分支 —— 掉下去的話，預覽列出一排實際上
    不存在的選項，而管理員以為自己驗過了。
    """
    body = _preview_body()
    auto = body.index('rowAutoTier(row)')
    radios = body.index("type === 'fee' || type === 'radio'")
    assert auto < radios, '自動判定那一支要排在畫選項之前'
    assert re.search(r'\}\s*else if \(type === .fee. \|\| type === .radio.\)', body), \
        '兩支不是互斥的 —— 開了自動判定還是會一起畫出選項'


def test_preview_dom_matches_the_real_partial():
    """★ 共用的那支 JS 靠 class 找東西。少一個 class 不會報錯，
    只會靜靜地不動作：

      .at-hidden 少了  → 答案永遠是空的（而畫面上身分別顯示得好好的）
      .at-value 少了   → applyTier 直接爆掉，整個預覽停在半路
      data-at-field 少 → 伺服器算好了對不回來，永遠是「—」
    """
    partial = _src('templates/_auto_tier_field.html')
    body = _preview_body()
    for token in ('class="auto-tier"', 'data-at-field', 'at-value', 'at-price',
                  'at-note', 'at-cheaper', 'at-hidden', 'data-field-id'):
        assert token in partial, f'前提變了：真表單沒有 {token}'
        assert token in body, f'預覽少了 {token} —— 會靜靜地不動作'


def test_preview_keeps_the_self_declared_checkbox():
    """特殊身分別是唯一保留給報名者勾的 —— 預覽沒有它的話，
    管理員驗不到「勾了會變成哪一項」。"""
    body = _preview_body()
    assert 'at-special' in body
    assert 'refreshAutoTiers()' in body, '勾了要重算，不然畫面不會變'


# ── 2. 預覽要真的算得出來（用草稿設定） ──────────────────────────

def test_preview_computes_from_the_draft_config():
    """★ 只把畫面改對、算不出來的話，預覽會永遠停在
    「請先填寫上面的出生日期」—— 那是另一種假象。"""
    src = _src('templates/admin/event_form.html')
    assert 'window.previewTierPayload' in src
    fn = src.split('window.previewTierPayload')[1].split('\n};')[0]
    assert "f-auto-tier-json" in fn or 'rowAutoTier' in fn, \
        '沒有把表單上的草稿設定送上去'
    assert 'PREVIEW_BASIS_DATE' in fn, '沒送基準日 —— 年齡會用今天算'


def test_the_tier_endpoint_is_pluggable():
    """★ 寫死 /event/<id>/compute-tier 的話，後台預覽永遠算的是
    資料庫裡的舊設定（或因為沒有 id 直接 return）。"""
    js = _src('static/js/form-fields.js')
    fn = js.split('function tierRequest')[1].split('\n  }')[0]
    assert 'compute-tier' in fn and 'previewTierPayload' in fn, \
        'refreshAutoTiers 沒有留給預覽的路'
    body = js.split('window.refreshAutoTiers')[1].split('\n  };')[0]
    assert 'req.url' in body and "fetch('/event/" not in body, \
        '網址又被寫死回去了'


def test_the_calculation_is_still_only_one_implementation():
    """★ 預覽自己在後台算一份的話，症狀是「預覽說成人、實際算成敬老」，
    兩邊都看起來完全正常。"""
    src = _src('routes/admin.py')
    fn = src.split('def preview_tier')[1].split('\n@admin_bp')[0]
    assert 'resolve(' in fn, '沒有走 auto_tier.resolve'
    assert 'describe(' in fn, '判定方式那句話也要走同一支'
    # 自己判年齡就是第二份實作
    assert 'age_on' not in fn and 'ages' not in fn.split('rules[fid]')[0].replace(
        'auto_tier', ''), '看起來在自己算年齡分級'


# ── 3. 真的打一次端點（使用者截圖那組設定） ──────────────────────────

SCREENSHOT_CONFIG = {
    'options': '成人|800\n孩童|500\n長者|600\n持身障證明者|600',
    'auto_tier': {
        'enabled': True,
        'special_label': '持身障證明者',
        'fallback_label': '成人',
        'ages': {'孩童': [None, 12], '長者': [65, None]},
    },
}


def post_preview(admin_client, birthday, special=False, basis='2026-09-01'):
    payload = {'basis': basis, 'birthday': birthday,
               'fields': [dict(SCREENSHOT_CONFIG, id='pv2', special=special)]}
    with patch('routes.admin_events.supabase', MagicMock()):
        return admin_client.post('/admin/events/preview-tier', json=payload,
                                 headers={'X-CSRF-Token': 'test-csrf-token'})
















# ── 編輯頁載入不可以吃掉設定 ──────────────────────────

def _fn(name):
    """取出某個 JS 函式的**函式體**（剝掉註解）。

    ★ 一定要剝註解 —— 這個檔案的 _src 是原文。下面那條在比「快照有沒有
      在建列之前取」，而我在旁邊寫的說明裡就有 .f-auto-tier-json、
      addOptionRow、loadAutoTier 這幾個字，位置全被打亂。
      （專案裡這坑第六次了，共用 test_dom_ids 那一份。）
    """
    from tests.test_dom_ids import _strip_comments
    src = _strip_comments(_src('templates/admin/event_form.html'))
    body = src.split('function ' + name + '(')[1]
    return body[:body.index('\n}')]


def test_loading_the_editor_does_not_wipe_the_auto_tier_config():
    """★★ 使用者回報（附三張圖）：設好存檔 → 再打開編輯頁，
    「依出生日期自動判定」變成沒勾、年齡範圍全空。

    ## 為什麼

    loadOptionRows 會一列一列 addOptionRow，而 addOptionRow 結尾呼叫
    syncAutoTier（使用者編輯時必要）。那個時間點勾選框還沒被 loadAutoTier
    還原 —— syncAutoTier 看起來就像「這個欄位沒開自動判定」，直接把
    .f-auto-tier-json 清成空字串。等一下 loadAutoTier 讀到的是空的。

    ## 為什麼比看起來嚴重

    畫面上選項（成人 800、孩童 500…）還在，看起來只是「忘了勾」——
    **下一次按儲存就把 null 寫回資料庫，設定真的沒了。**
    跟 CLAUDE.md 那條「打開編輯頁就洗掉舊活動的價格」是同一家族。
    """
    fn = _fn('loadOptionRows')
    assert 'f-auto-tier-json' in fn, \
        'loadOptionRows 沒有保護自動判定的設定 —— 建列的過程會把它洗掉'
    snapshot = fn.index('f-auto-tier-json')
    first_row = fn.index('addOptionRow')
    assert snapshot < first_row, \
        '快照取得太晚 —— 那時候設定已經被 syncAutoTier 清掉了'
    restore = fn.rindex('f-auto-tier-json')
    load = fn.index('loadAutoTier')
    assert first_row < restore < load, \
        '還原的位置不對：必須在建完列之後、loadAutoTier 之前'


def test_the_row_builder_still_syncs_for_real_edits():
    """★ 反向：不能為了修上面那條就把 syncAutoTier 從 addOptionRow 拿掉。

    拿掉的話，使用者**新增一列選項**時 .f-auto-tier-json 不會跟著更新 ——
    存下去的年齡設定少了那一列，而畫面上那一列看起來好好的。
    """
    assert 'syncAutoTier(fieldRow);' in _fn('addOptionRow'), \
        'addOptionRow 不再同步設定 —— 新增選項時的年齡範圍會存不進去'


# ── 畫面上不可以有寫死的類別名稱 ──────────────────────────

# 這個機制是通用的：「有一個級距算不出來，只能由本人申報」。
# 那一格可能是身心障礙、工作人員、清寒證明、教會同工…… 而欄位本身
# 可能叫「身分別」也可能叫「票種」。
#
# ★ 使用者一眼看出問題：「未來活動內容不一樣，問題不一樣，
#   不就打臉還要重修」。對 —— 所以文案一律從設定來。
HARDCODED = ('持有身心障礙證明者', '當日請攜帶證明', '你的身分別',
             '特殊身分別（')

def _registrant_facing():
    """報名者真的會看到的那幾段（含後台預覽，因為它模擬的就是報名者的畫面）。

    ★ 後台**設定介面本身**不算 —— 那裡的 placeholder
      「提醒文字（選填，例：當日請攜帶證明）」是給管理員看的範例，
      正是在告訴他這一格該填什麼。把它一起禁掉的話，等於逼人拿掉
      唯一說得清楚的說明，而規則本身一點也沒變嚴。
    """
    from tests.test_dom_ids import _strip_comments
    admin = _strip_comments((ROOT / 'templates/admin/event_form.html')
                            .read_text(encoding='utf-8'))
    preview = admin.split('function openPreview')[1].split('\nfunction ')[0]
    return [
        ('templates/_auto_tier_field.html',
         _strip_comments((ROOT / 'templates/_auto_tier_field.html').read_text(encoding='utf-8'))),
        ('static/js/form-fields.js',
         _strip_comments((ROOT / 'static/js/form-fields.js').read_text(encoding='utf-8'))),
        ('templates/admin/event_form.html（預覽）', preview),
    ]


@pytest.mark.parametrize('idx', range(3))
def test_no_hardcoded_category_names(idx):
    """★★ 報名者看得到的字裡不可以有寫死的類別名稱。

    寫死的話，換一場活動（那一格拿來當「工作人員」）畫面還在講
    身心障礙 —— 而管理員設定得完全正確，看起來就是系統在亂講。
    """
    path, src = _registrant_facing()[idx]
    for token in HARDCODED:
        assert token not in src, \
            f'{path} 裡還寫死著「{token}」—— 換一種問法就錯了'


def test_the_labels_come_from_the_config():
    """欄位名稱用 field.label，申報項名稱用 special_label。"""
    src = (ROOT / 'templates/_auto_tier_field.html').read_text(encoding='utf-8')
    assert '你的{{ field.label }}' in src, '標題沒有用欄位自己的名字'
    assert '{{ _at.special_label }}' in src, '申報項沒有用設定的名稱'


def test_the_extra_reminder_is_optional_and_configurable():
    """★ 「當日請攜帶證明」這種提醒因活動而異 —— 要能設，而且沒填就不顯示。

    給一句寫死的預設值的話，用不到的活動會多出一行不相干的字，
    而管理員找不到地方關掉。
    """
    src = (ROOT / 'templates/_auto_tier_field.html').read_text(encoding='utf-8')
    assert 'if _at.special_note' in src, '沒填提醒時應該整段不出現'
    admin = _src('templates/admin/event_form.html')
    assert 'opt-special-note' in admin, '後台沒有地方填那句提醒'
    fn = _fn('syncAutoTier')
    assert 'special_note' in fn, '填了不會被存下來'
    assert 'special_note' in _fn('loadAutoTier'), '存了不會被讀回來'


def test_the_reminder_box_only_shows_on_the_self_declared_row():
    """每一列都放的話，管理員會在別列填了字然後發現存不進去 ——
    那個欄位只有申報項才有。"""
    fn = _fn('syncSpecialNotes')
    assert "opt-special')?.checked" in fn and 'style.display' in fn


def test_the_error_message_uses_the_field_label():
    """「算出來是 35 歲，但對不到任何身分別」—— 欄位叫「票種」時
    這句會講一個報名者沒看過的詞。"""
    js = (ROOT / 'static/js/form-fields.js').read_text(encoding='utf-8')
    fn = js.split('function applyTier')[1].split('\n  }')[0]
    assert 'dataset.fieldLabel' in fn, '錯誤訊息沒有用欄位自己的名字'
