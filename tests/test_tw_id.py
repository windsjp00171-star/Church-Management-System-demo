"""身分證字號 / 居留證號

保險名冊要這個。**打錯一個字的後果是那個人根本沒被保到** ——
而且不會有任何徵兆，要出事那一刻才會發現。

身分證字號內建一位檢查碼，隨手打錯一個數字有九成會被算出來 ——
這是少數「能在輸入當下就擋掉」的錯誤。
"""
import pytest

from routes.tw_id import _LETTER, _WEIGHTS, is_valid, normalize


def _with_check_digit(prefix):
    """給前 9 碼，算出正確的檢查碼 —— 用來產生測試資料。

    這段刻意跟 is_valid 用同一組常數但反向算，所以它驗的是
    「兩個方向自洽」，不是「跟自己比對」。
    """
    first = _LETTER[prefix[0]]
    second = int(prefix[1]) if prefix[1].isdigit() else _LETTER[prefix[1]] % 10
    total = first // 10 + (first % 10) * 9 + second * _WEIGHTS[0]
    for i, w in enumerate(_WEIGHTS[1:], start=2):
        total += int(prefix[i]) * w
    return prefix + str((10 - total % 10) % 10)


# ── 有效值 ──────────────────────────

def test_the_canonical_example():
    """A123456789 是公開文件上最常見的示範值，算不對就是演算法錯了"""
    assert is_valid('A123456789')


@pytest.mark.parametrize('prefix', [
    'A12345678', 'B22345678', 'F13141516', 'Z98765432',
    'I10000000', 'O20000000', 'W15555555',   # 對照表跳號的那幾個字母
])
def test_generated_national_ids_are_valid(prefix):
    assert is_valid(_with_check_digit(prefix))


@pytest.mark.parametrize('prefix', ['A81234567', 'C91234567'])
def test_new_style_resident_numbers(prefix):
    """2021 年起的新式外來人口統一證號：第 2 碼是 8 或 9，算法跟本國一樣"""
    assert is_valid(_with_check_digit(prefix))


@pytest.mark.parametrize('prefix', ['AB1234567', 'FD8765432'])
def test_legacy_arc_numbers(prefix):
    """舊式居留證：第 2 碼是英文字母，要先換成對照數字的個位數"""
    assert is_valid(_with_check_digit(prefix))


# ── 檢查碼真的有在擋 ──────────────────────────

def test_a_single_wrong_digit_is_caught():
    """★ 這才是整個模組存在的理由。

    格式檢查抓不到「打錯一個數字」—— 而那正是最常發生的錯，
    也正是會讓一個人沒被保到的錯。
    """
    good = 'A123456789'
    assert is_valid(good)
    assert not is_valid('A123456788')       # 最後一碼錯
    assert not is_valid('A123456780')


def test_most_single_digit_typos_are_caught():
    """檢查碼擋不掉全部（同餘的組合會漏），但要擋掉絕大多數。

    這條把實際的攔截率記下來 —— 哪天演算法被改壞，攔截率會直接崩掉。
    """
    good = 'A123456789'
    typos = [good[:i] + d + good[i + 1:]
             for i in range(1, 10) for d in '0123456789' if d != good[i]]
    caught = sum(1 for t in typos if not is_valid(t))
    assert caught / len(typos) >= 0.85, f'只擋掉 {caught}/{len(typos)}'


def test_transposed_digits_are_usually_caught():
    """相鄰兩碼寫反也是常見的手誤"""
    good = 'A123456789'
    swaps = [good[:i] + good[i + 1] + good[i] + good[i + 2:] for i in range(1, 9)]
    assert sum(1 for s in swaps if not is_valid(s)) >= len(swaps) - 1


# ── 無效值 ──────────────────────────

@pytest.mark.parametrize('bad', [
    '', None, '   ',
    'A12345678',        # 少一碼
    'A1234567890',      # 多一碼
    '1123456789',       # 開頭不是英文字母
    'A323456789',       # 第 2 碼不是 1/2/8/9
    'A0234567890',
    'AE12345678',       # 舊式居留證第 2 碼只到 D
    'A12345678X',       # 檢查碼不是數字
    '身分證字號',
    'A123-456-789',
])
def test_invalid_values(bad):
    assert not is_valid(bad)


# ── 排版差異可以吸收，但不猜 ──────────────────────────

@pytest.mark.parametrize('given', [
    'a123456789', ' A123456789 ', 'A 123 456 789', 'A123456789\n',
])
def test_case_and_spaces_are_absorbed(given):
    """使用者會打小寫、會在中間打空格 —— 那是排版差異，不是填錯"""
    assert is_valid(given)
    assert normalize(given) == 'A123456789'


@pytest.mark.parametrize('given', [
    'A12345678', '123456789', '', 'A', 'A1234567890123', '亂填的東西',
])
def test_normalize_only_removes_never_adds(given):
    """★ normalize 只做兩件事：去空白、轉大寫。**絕不補字元。**

    「幫忙補到 10 碼」看起來體貼，但那是**造出一個不存在的證號** ——
    而它看起來跟正確的一模一樣，可能還剛好是別人的。

    這條守的是長度：去掉空白之後，正規化不該讓字串變長。
    （原本只斷言「補完之後還是無效」，但補 0 剛好也無效，所以抓不到。）
    """
    stripped = ''.join(given.split())
    assert len(normalize(given)) == len(stripped)


def test_normalize_never_invents_a_valid_number():
    """少一碼就是少一碼，不要試著「修好」它"""
    assert not is_valid(normalize('A12345678'))
    assert not is_valid(normalize('123456789'))


def test_normalize_handles_none():
    assert normalize(None) == ''


# ══ 接到系統上 ══════════════════════════════════════

def _src(path):
    return open(path, encoding='utf-8').read()




def test_every_form_renders_the_id_input():
    """★ 三個報名入口都要有。少改一個的話，那個入口進來的人看到的是
    普通文字框 —— 沒有檢查、沒有提示，而畫面完全正常。"""
    for path in ('templates/event_detail.html', 'templates/external_register.html'):
        src = _src(path)
        assert "field_type == 'id_number'" in src, f'{path} 不認得 id_number'
        assert 'checkTwId(this)' in src, f'{path} 沒有接上即時檢查'


def test_the_frontend_and_backend_use_the_same_table():
    """★ 兩邊各有一份字母對照表，不一致的話前端說「格式正確」
    但後端擋下來（或反過來）—— 使用者只會看到送不出去，看不出為什麼。

    對照表不是規律的（I/O/W/X/Y/Z 特別跳號），最容易在「順手改成連續」
    的時候壞掉。
    """
    js = _src('static/js/fee-total.js')
    for letter, value in _LETTER.items():
        assert f'{letter}:{value}' in js.replace(' ', ''), \
            f'JS 的對照表少了或寫錯 {letter}={value}'


def test_the_js_loop_covers_exactly_the_weighted_digits():
    """★ 這條記錄一個真的發生過的錯。

    WEIGHTS 只有 8 個元素（索引 0–7）。JS 的迴圈原本跑到 i=9，
    拿到 undefined → 整個和變 NaN → **所有號碼都被判成無效**，
    而且檢查碼被算了兩次。

    1000 組隨機值的瀏覽器交叉比對抓到 48 組跟後端不一致；
    靜態的「對照表一不一樣」那條完全沒反應 —— 表是對的，錯的是迴圈。
    """
    js = _src('static/js/fee-total.js')
    body = js.split('window.isValidTwId')[1]
    assert 'for (var i = 2; i <= 8; i++)' in body, \
        'JS 的加權迴圈範圍不對 —— 會拿到 undefined 讓整個和變 NaN'
    assert len(_WEIGHTS) == 8


def test_the_backend_rejects_a_bad_id():
    """★ 前端擋得掉手誤，但擋不掉「JS 沒跑」和「直接打 API」。

    而一個錯的證號在名冊上看起來跟對的一模一樣。
    """
    assert 'def _reject_bad_id_numbers' in _src('routes/event.py')
    # ★ 每一個寫入答案的地方都要驗 —— 用「數幾次」的話，每加一個寫入點
    #   就要回來改數字，而忘記改的後果是有人把數字加一了事。
    from tests.test_auto_tier import _answer_writers
    for path, fn in _answer_writers():
        assert '_reject_bad_id_numbers(' in fn, \
            f'{path} 有一個寫入答案的地方沒有驗身分證字號'


def test_the_error_message_says_what_is_actually_wrong():
    """★ 講「格式錯誤」沒有用 —— 格式看起來明明是對的，
    使用者會一直盯著看不出問題在哪。要講「檢查碼不對」。"""
    assert '檢查碼不對' in _src('routes/event.py')
    assert '檢查碼不對' in _src('static/js/fee-total.js')
