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
