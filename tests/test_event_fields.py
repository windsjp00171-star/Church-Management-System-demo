"""分級收費：選項帶價格

教會旅遊的景點門票要分級（成人 800 / 敬老 600 / 身障 600 / 12歲以下 400），
但 events.fee 只有單一數字。這裡是那個缺口的地基。

★ 這一整份最重要的是「對不上的時候要回 None，不能回 0」。
  管理員把選項改名（成人 → 成人票）之後，舊答案就對不到價格了 ——
  回 0 的話那個人在名冊上靜靜地變成不用繳錢，畫面完全正常，
  沒有人會發現，直到對帳少一筆。
"""
import pytest

from routes.event_fields import (
    amount_for, has_prices, is_unmatched, label_only,
    parse_option, parse_options, price_of,
)

TRIP = '成人|800\n敬老|600\n身障|600\n12歲以下孩童|400'
PLAIN = '葷食\n素食'


# ── 解析 ──────────────────────────

@pytest.mark.parametrize('line, label, price', [
    ('成人|800', '成人', 800),
    ('成人 | 800', '成人', 800),          # 手打的空格
    ('  敬老|600  ', '敬老', 600),
    ('葷食', '葷食', None),               # 沒標價
    ('免費場次|0', '免費場次', 0),         # 0 是有效價格，不是「沒價格」
    ('', None, None),
    ('   ', None, None),
])
def test_parse_option(line, label, price):
    assert parse_option(line) == (label, price)


def test_a_label_containing_a_pipe_is_not_mangled():
    """「A|B 方案」這種標籤本來就含 | —— 只有行尾是 |數字 才算價格"""
    assert parse_option('A|B 方案') == ('A|B 方案', None)


def test_only_a_trailing_number_counts_as_price():
    assert parse_option('成人|八百') == ('成人|八百', None)
    assert parse_option('成人|800元') == ('成人|800元', None)


def test_other_marker_is_skipped():
    opts = parse_options('成人|800\n__other__')
    assert [o['label'] for o in opts] == ['成人']


def test_blank_lines_are_skipped():
    assert len(parse_options('成人|800\n\n\n敬老|600')) == 2


# ── 有沒有標價 ──────────────────────────

def test_has_prices():
    assert has_prices(TRIP) is True
    assert has_prices(PLAIN) is False
    assert has_prices('') is False
    assert has_prices(None) is False


def test_partially_priced_counts_as_priced():
    """有些標價有些沒標 —— 也算是收費欄位，沒標的那個就是 0 元"""
    assert has_prices('成人|800\n工作人員') is True


# ── 查價 ──────────────────────────

@pytest.mark.parametrize('answer, expected', [
    ('成人', 800),
    ('敬老', 600),
    ('12歲以下孩童', 400),
    (' 成人 ', 800),        # 前後空白
])
def test_price_of(answer, expected):
    assert price_of(TRIP, answer) == expected


def test_price_of_returns_none_not_zero_when_unmatched():
    """★ 這條是整份最重要的。

    回 0 的話呼叫端會把它當成「這個人不用繳錢」而且完全不會發現。
    """
    assert price_of(TRIP, '成人票') is None
    assert price_of(TRIP, None) is None
    assert price_of(PLAIN, '葷食') is None      # 這個欄位本來就沒標價


def test_zero_price_is_not_none():
    """0 元和「查不到」是兩件事，不能混在一起"""
    assert price_of('免費|0', '免費') == 0


# ── 對不上 ──────────────────────────

def test_unmatched_is_detected():
    """管理員把「成人」改名成「成人票」之後，舊答案就對不上了"""
    assert is_unmatched(TRIP, '成人') is False
    assert is_unmatched(TRIP, '成人票') is True


def test_plain_field_is_never_unmatched():
    """沒標價的欄位不參與收費，答案是什麼都無所謂"""
    assert is_unmatched(PLAIN, '隨便什麼') is False


def test_empty_answer_is_not_unmatched():
    """還沒填 ≠ 填錯。沒填的人不該出現在「對不上」清單裡"""
    assert is_unmatched(TRIP, '') is False
    assert is_unmatched(TRIP, None) is False


# ── 一筆報名的總額 ──────────────────────────

FIELDS = [
    {'id': 'f-tier', 'options': TRIP},
    {'id': 'f-meal', 'options': PLAIN},
    {'id': 'f-shirt', 'options': '要|150\n不要|0'},
]


def test_amount_sums_only_priced_fields():
    total, bad = amount_for(FIELDS, {'f-tier': '成人', 'f-meal': '素食', 'f-shirt': '要'})
    assert (total, bad) == (950, [])


def test_amount_ignores_unanswered():
    total, bad = amount_for(FIELDS, {'f-tier': '敬老'})
    assert (total, bad) == (600, [])


def test_unmatched_is_excluded_and_reported():
    """★ 猜一個數字比留白更危險 —— 不計入總額，但要回報是哪個欄位"""
    total, bad = amount_for(FIELDS, {'f-tier': '成人票', 'f-shirt': '要'})
    assert total == 150
    assert bad == ['f-tier']


def test_amount_handles_empty_input():
    assert amount_for([], {}) == (0, [])
    assert amount_for(None, None) == (0, [])


# ── 條件下拉用的純標籤 ──────────────────────────

def test_label_only_strips_prices():
    """★ 跳題條件比對的是答案文字，而答案存的是標籤。

    這裡若回整行（成人|800），條件永遠不成立 —— 而且畫面完全正常，
    那個欄位只是再也不出現。典型的靜默失效。
    """
    assert label_only(TRIP) == '成人\n敬老\n身障\n12歲以下孩童'


def test_label_only_leaves_unpriced_alone():
    assert label_only(PLAIN) == '葷食\n素食'


# ══ 端對端：三個報名表單都要把價格畫出來 ══════════════
#
# 三個表單各自 render 一份選項（自己報名 / 幫別人報名 / 外部報名）。
# 少改一個的話，那個入口進來的人看不到價格、也不會被計費 ——
# 而且畫面完全正常，只是金額悄悄變成 0。

import re

import pytest as _pytest

_PRICED_EVENT_OPTIONS = '成人|800\n敬老|600\n12歲以下孩童|400'


def test_templates_never_split_options_by_hand():
    """★ 選項一律走 field_options()。

    自己 split('\\n') 的話會拿到整行「成人|800」當答案 ——
    跳題條件比對不到、後端也查不到價格，而畫面完全正常。
    """
    offenders = []
    for path in ('templates/event_detail.html', 'templates/external_register.html'):
        src = open(path, encoding='utf-8').read()
        if 'field.options.split' in src:
            offenders.append(path)
    assert not offenders, f'這些模板還在自己拆選項：{offenders}'


@_pytest.mark.parametrize('path', [
    'templates/event_detail.html',
    'templates/external_register.html',
])
def test_every_form_renders_prices(path):
    """有標價的選項要帶 data-price，前端才算得出合計"""
    src = open(path, encoding='utf-8').read()
    assert 'data-price' in src, f'{path} 沒有把價格畫出來'
    assert 'updateFeeTotal()' in src, f'{path} 沒有在選擇時更新合計'
    assert 'fee-total' in src, f'{path} 沒有應繳金額列'


def test_admin_editor_strips_price_from_condition_values():
    """★ 後台的跳題觸發值必須只取標籤。

    放整行（成人|800）的話條件永遠不成立 —— 那個欄位只是再也不出現，
    沒有任何錯誤訊息。
    """
    src = open('templates/admin/event_form.html', encoding='utf-8').read()
    assert 'function optionLabel' in src
    assert re.search(r'\.map\(l => optionLabel\(l\)\)', src), \
        '觸發值下拉沒有用 optionLabel 去掉價格'


def test_admin_and_backend_agree_on_the_price_syntax():
    """★ 前端（JS）和後端（Python）各有一份解析規則，必須一致。

    兩邊不一致的話，後台預覽顯示「會收 800」但後端算不到 ——
    或反過來。這種分歧不會報錯，只會讓金額對不上。
    """
    js = open('templates/admin/event_form.html', encoding='utf-8').read()
    # JS 那份用的是 \d{1,7}，跟 Python 的 _PRICED 同一個上限
    assert r'\d{1,7}' in js, 'JS 的價格規則跟 Python 的 _PRICED 不一致'
    from routes.event_fields import _PRICED
    assert r'\d{1,7}' in _PRICED.pattern






# ══ 後台找得到嗎 ══════════════════════════════════
#
# ★ 這一段是使用者實際回報「我沒有看到收費設定在哪裡」之後補的。
#
# 功能做好了、測試也綠，但**在建立新活動時完全看不到** ——
# 因為欄位編輯器有兩份：伺服器 render 的（既有欄位）和 JS 產生的
# （新增欄位），而價格說明只加在前者。新活動的每一個欄位都是後者。
#
# 這是這個專案反覆出現的同一類 bug：兩份複製，只改了一份。

def test_there_is_a_one_click_entry_next_to_the_fee_field():
    """★ 找錢的人會先看「費用」那一格。

    分級收費藏在自訂欄位的選項框裡，而那個框要先把型別選成「單選」
    才會出現 —— 使用者在費用那格找不到，就以為系統做不到（實際發生過）。

    所以給一顆會直接建好欄位的按鈕，不是只給一行說明。
    """
    src = open('templates/admin/event_form.html', encoding='utf-8').read()
    fee_block = src.split('id="fee"')[1].split('</div>')[0]
    assert 'addTieredFeeField()' in fee_block, '費用欄位旁邊沒有分級收費的入口'
    assert 'function addTieredFeeField' in src


def test_the_one_click_entry_produces_a_usable_field():
    """按下去要直接可用：型別是分級收費、編輯器打開、範例已填好"""
    src = open('templates/admin/event_form.html', encoding='utf-8').read()
    fn = src.split('function addTieredFeeField')[1].split('function addField')[0]
    assert "type.value = 'fee'" in fn, '沒有把型別設成分級收費'
    assert 'toggleOptions(type)' in fn, '沒有把收費編輯器打開 —— 按了看起來沒反應'
    assert "['成人', 800]" in fn, '沒有填入範例項目'
    assert 'addOptionRow(row, label, price)' in fn, '沒有用列式編輯器建範例'


# ══ 選項編輯器：一列一個，不用 textarea ══════════════
#
# ★ 使用者原話：「我真的很討厭那個 TEXTBOX」「用 textarea 設定問題跟
#   分隔問題的真的很麻煩」「你這樣邏輯繞一大圈」。
#
# 換行當分隔、| 當價格分隔，都是為了「一個欄位存一串字」發明的規則 ——
# 是實作方便，不該轉嫁成使用者要記的東西。
#
# 但**存進資料庫的格式沒變**：隱藏的 .f-options 就是儲存來源，
# 每次改動都同步過去，所以送出、跳題條件那些讀它的地方一行都沒改。


def _admin():
    return open('templates/admin/event_form.html', encoding='utf-8').read()


def test_the_options_textarea_is_hidden():
    """★ textarea 還在（它是儲存來源），但不該讓人直接打字。"""
    src = _admin()
    assert src.count('class="f-options" style="display:none;"') == 2, \
        '選項 textarea 沒有藏起來（既有 / 新增各一份）'
    assert 'oninput="renderOptionPreview' not in src, '還留著要人打字的舊 textarea'


def test_both_editors_have_the_row_ui():
    """兩份模板都要有 —— 只加一份的話，新活動看不到（這個坑踩過了）"""
    src = _admin()
    assert src.count('class="opt-rows"') == 2
    assert src.count('addOptionRow(this.closest') == 2


def test_there_is_only_one_editor_now():
    """★ 收費專用的那份編輯器已經併掉了。

    留著兩套的話，改一套忘另一套 —— 這個專案反覆出現的同一類。
    """
    src = _admin()
    for gone in ('fee-area', 'fee-rows', 'addFeeRow', 'collectFeeRows',
                 'loadFeeRows', 'renderOptionPreview', 'opt-preview'):
        assert gone not in src, f'舊的收費編輯器還留著 {gone}'


def test_the_editor_writes_back_the_same_storage_format():
    """★ 存進資料庫的還是每行一個選項（收費的是「名稱|金額」）。

    改了儲存格式的話，既有活動的選項會全部失效 —— 而畫面完全正常，
    只是報名時那一題不見了。
    """
    fn = _admin().split('function syncOptionRows')[1].split('\n}')[0]
    # 沒有價格的選項 → 只寫標籤。（原本寫死比對 `lines.push(label)`，
    # 但那一行後來要多判斷「舊活動的價格要保住」，形狀變了意思沒變。）
    assert "? label :" in fn, '沒有價格的選項應該只寫回標籤'
    assert "label + '|'" in fn, '收費選項沒有寫回「名稱|金額」'
    assert "lines.push('__other__')" in fn, '「其他」選項沒有寫回去'


def test_a_blank_price_becomes_zero_not_missing():
    """★ 金額留白＝免費（0 元），不是「沒有價格」。

    沒有價格的選項在名冊上不計費，那跟免費是兩件事 ——
    差別會直接反映在應收合計上。
    """
    fn = _admin().split('function syncOptionRows')[1].split('\n}')[0]
    assert "raw === '' ? 0" in fn


def test_editing_an_existing_field_loads_the_rows_back():
    """★ 漏了這步的話，編輯舊活動會看到空白的選項編輯器 ——
    一按儲存原本的選項就全沒了，而畫面上完全正常。"""
    src = _admin()
    assert 'function loadOptionRows' in src
    assert 'if (type) toggleOptions(type);' in src, '既有欄位載入時沒有把選項拆成列'


def test_switching_type_rewrites_the_storage_format():
    """★ 單選改成收費時，儲存格式要從「葷食」變成「葷食|0」。

    少了這一步：畫面上金額欄已經出現、但送出去的還是沒價格的舊格式，
    而兩邊看起來都正常。
    """
    fn = _admin().split('function toggleOptions')[1].split('\n}')[0]
    assert 'syncOptionRows(row)' in fn


def test_a_fee_field_can_trigger_a_jump_condition():
    """★★ 這條守一個真的發生過的 bug（使用者回報「這邊跳題有問題」）。

    分級收費底下就是單選，當然可以當觸發問題。漏掉它的話：
    身分別一改成收費型別，「選了孩童才問監護人」那條跳題就再也設不起來 ——
    而畫面上只是下拉裡少了一個選項，看不出是系統不給還是自己沒建那一題。
    """
    src = _admin()
    # ★ 從 TRIGGER_TYPES 推出來，不要在這裡再寫死一份名單 ——
    #   寫死的話，之後往單一來源加型別（例如 birthday）會讓這條紅，
    #   而紅的原因跟它要守的東西無關，改法就會變成「把新型別塞進字串」。
    from routes.field_types import TRIGGER_TYPES
    expected = '[' + ', '.join(f"'{t}'" for t in TRIGGER_TYPES) + '].includes(type)'
    assert expected in src, \
        f'觸發型別白名單跟 TRIGGER_TYPES 對不上，應該是 {expected}'
    assert '分級收費' in src.split('觸發問題需為')[1][:80], \
        '提示文字沒有跟著更新，使用者會以為收費欄位不能當觸發'


def test_a_fee_field_offers_no_free_text_option():
    """★ 收費欄位不給「其他（請填寫）」。

    自由填的答案對不到任何價格，那個人的金額會算不出來 ——
    而名冊上只顯示「選項對不上」，看不出是報名者亂填還是管理員改過選項。
    """
    fn = _admin().split('function applyOptionMode')[1].split('\n}')[0]
    assert "other.style.display = fee ? 'none' : 'flex'" in fn


def test_every_form_renders_fee_fields_as_radio():
    """fee 就是帶價格的單選。少改一份表單的話，那個入口進來的人
    看不到選項（畫面完全正常，只是那一題不見了）。"""
    for path in ('templates/event_detail.html', 'templates/external_register.html'):
        src = open(path, encoding='utf-8').read()
        assert "field.field_type in ['radio', 'fee']" in src, f'{path} 不認得 fee'


def test_fee_answers_are_collected():
    """★ 收值漏掉 fee 的話會落到預設分支去找 radio 沒有的屬性 →
    回空字串 → 收費選項永遠不會被送出，而畫面完全正常。

    ★ 三個入口都要驗。外部報名就是漏了這一個，而且同時把必填檢查
      一起漏掉，結果那場活動的外部報名完全送不出去
      （選好了還是跳「請填寫所有必填欄位」）。

    用 source_bundle 而不是直接讀 .html —— 邏輯已經搬到
    static/js/form-fields.js，讀死檔案的話測試會綠得很安靜。
    """
    from tests.conftest import source_bundle
    for path in ('event_detail.html', 'external_register.html'):
        src = source_bundle(path)
        assert "type === 'radio' || type === 'fee'" in src, \
            f'{path} 的收值不認得 fee'


# ══ 資料庫的白名單 ══════════════════════════════════
#
# ★★ 這一段是使用者實際撞到之後補的（正式環境，建活動建到一半）：
#
#     建立失敗：欄位建立失敗：{'message': 'new row for relation "event_fields"
#     violates check constraint "event_fields_field_type_check"', 'code': '23514'}
#
# event_fields.field_type 有一條 CHECK 約束是白名單。程式端加了三種新型別，
# 後台下拉、前台渲染、送出、名冊全部做好、859 條測試全綠 ——
# **但沒有人記得去放寬那條約束**。
#
# ★ 為什麼測試抓不到：所有測試都 mock 掉 Supabase。那是 mock 的固有盲區 ——
#   它驗的是「我們有沒有照計畫呼叫」，不是「資料庫會不會接受」。
#   再多的單元測試也補不上這一格。
#
# 所以這裡守的是兩件補得上的事：清單只有一份、錯誤訊息看得懂。

from routes.field_types import FIELD_TYPES, TRIGGER_TYPES, translate_db_error


@pytest.mark.parametrize('idx, which', [(0, '既有欄位'), (1, '新增欄位')])
def test_the_admin_dropdown_offers_exactly_the_supported_types(idx, which):
    """★ 下拉裡有、清單裡沒有的型別 = 沒人記得它存在，
    包括「要不要放寬資料庫約束」也不會有人想到。

    ★ 兩份下拉都要檢查。只看第一份的話，加在「新增欄位」那份的型別
    完全不會被發現 —— 而新活動的每一個欄位都是走那一份。
    （第一版就只檢查了一份，變異測試抓到。）
    """
    import re
    src = open('templates/admin/event_form.html', encoding='utf-8').read()
    blocks = src.split('class="f-type"')[1:]
    assert len(blocks) == 2, f'型別下拉應該有兩份，找到 {len(blocks)} 份'
    in_ui = set(re.findall(r'<option value="([a-z_]+)"', blocks[idx].split('</select>')[0]))
    assert in_ui == set(FIELD_TYPES), (
        f'{which}的型別下拉與 FIELD_TYPES 對不上\n'
        f'下拉多的：{in_ui - set(FIELD_TYPES)}\n'
        f'清單多的：{set(FIELD_TYPES) - in_ui}')


def test_the_migration_covers_every_supported_type():
    """★ 新增型別時最容易漏的第四步：放寬資料庫的 CHECK 約束。

    migrations/ 那份是給人照著執行的 —— 它少了哪一種，
    那一種就會在「使用者按下儲存的當下」失敗。
    """
    import glob
    # ★ 不要寫死檔名。約束是「最後跑到的那一份說了算」，而每次加型別
    #   都會多一個 migration 檔 —— 寫死的話，新檔案裡加對了這條還是紅，
    #   而修法會變成「回來改檔名」，下一個人再加型別時又要改一次。
    files = sorted(f for f in glob.glob('migrations/*.sql')
                   if 'event_fields_field_type_check' in open(f, encoding='utf-8').read())
    assert files, '找不到定義 event_fields_field_type_check 的 migration'
    latest = files[-1]          # 檔名有日期前綴，依序執行，最後一份是最終狀態
    sql = open(latest, encoding='utf-8').read()
    missing = [t for t in FIELD_TYPES if f"'{t}'" not in sql]
    assert not missing, f'{latest} 的白名單少了：{missing}'


def test_fee_can_trigger_a_jump():
    """收費底下就是單選，當然能當觸發問題"""
    assert 'fee' in TRIGGER_TYPES


def test_the_constraint_error_becomes_something_actionable():
    """★ 原始訊息看得出「失敗了」，但看不出「該做什麼」——
    而看不出該做什麼的錯誤訊息，等於沒有訊息。"""
    err = {'message': 'new row for relation "event_fields" violates check '
                      'constraint "event_fields_field_type_check"', 'code': '23514'}
    msg = translate_db_error(err, 'birthday')
    assert msg and '出生日期' in msg, '沒有講清楚是哪一種欄位'
    assert 'migrations/' in msg, '沒有告訴人該去哪裡修'


def test_unrelated_errors_are_left_alone():
    """★ 什麼錯誤都翻成同一句的話，真正的問題會被蓋掉"""
    assert translate_db_error('connection timeout', 'birthday') is None
    assert translate_db_error(ValueError('欄位太長'), 'text') is None


def test_both_field_write_paths_translate_the_error():
    """建立與編輯活動是兩條路徑，只改一條的話另一條照樣噴原始訊息"""
    src = open('routes/admin.py', encoding='utf-8').read()
    assert src.count('translate_db_error(e,') == 2
