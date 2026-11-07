"""依生日自動判定身分別

## 為什麼

原本讓報名者自己選身分別（成人／敬老／身障／孩童）。使用者的實際問題：
**自己選就會選錯，而對帳時查不出來** —— 名冊上「成人」和「敬老」看起來
一模一樣，只有金額差 200，要一個一個對生日才知道。

生日本來就要填（保險要用），所以讓系統自己算 —— 報名者不用做判斷，
而判斷正是出錯的地方。

## 唯一保留給使用者的

身心障礙不可能從生日推出來，一定要本人申報。勾了就覆蓋年齡判定。
"""
import re

import pytest

from routes.auto_tier import describe, is_enabled, pick_tier

# 使用者那場旅遊的實際設定
OPTIONS = [
    {'label': '成人', 'price': 800},
    {'label': '65歲以上者', 'price': 600},
    {'label': '持身障證明', 'price': 600},
    {'label': '國小以下孩童', 'price': 500},
]
RULES = {
    'enabled': True,
    'special_label': '持身障證明',
    'fallback_label': '成人',
    'ages': {
        '65歲以上者': [65, None],
        '國小以下孩童': [None, 12],
        # 成人刻意不設範圍 —— 它是「其他都算成人」，不是「18~64」
    },
}


def _pick(age, special=False):
    return pick_tier(OPTIONS, RULES, age, special)


# ── 年齡判定 ──────────────────────────

@pytest.mark.parametrize('age,expected', [
    (0, '國小以下孩童'),
    (6, '國小以下孩童'),
    (12, '國小以下孩童'),      # 上限含本數
    (13, '成人'),
    (30, '成人'),
    (64, '成人'),
    (65, '65歲以上者'),        # 下限含本數
    (90, '65歲以上者'),
])
def test_age_maps_to_the_right_tier(age, expected):
    assert _pick(age) == expected


def test_the_boundaries_are_inclusive():
    """★ 12 歲和 65 歲各差一塊錢很多。

    「12 歲以下」在中文裡含 12 —— 寫成不含的話，剛好 12 歲的孩子
    會被收成人價，而家長當場會發現。
    """
    assert _pick(12) == '國小以下孩童'
    assert _pick(13) != '國小以下孩童'
    assert _pick(65) == '65歲以上者'
    assert _pick(64) != '65歲以上者'


def test_ages_with_no_matching_range_fall_back():
    """★ 13~64 歲沒有任何範圍涵蓋 —— 要落到「沒設範圍」的那一個。

    逼管理員把成人也設成 18–64 的話，只要範圍沒接好就會有人掉進縫裡，
    而那個人的金額會是空的。
    """
    assert _pick(13) == '成人'
    assert _pick(45) == '成人'


# ── 特殊身分別 ──────────────────────────

def test_the_special_status_overrides_age():
    """★ 這是唯一系統算不出來、必須本人申報的一項。

    ★ 但只有在它**不會讓他變貴**的時候才覆蓋 —— 見
      `tests/test_special_tier_is_a_discount.py`（使用者回報的 bug：
      「嬰兒或幼童勾優待，費用會變成優待費用，更貴」）。
      這裡的 8 歲小孩就是那個情況：孩童 500 比身障 600 便宜。
    """
    assert _pick(30, special=True) == '持身障證明'      # 成人 800 → 便宜
    assert _pick(70, special=True) == '持身障證明'      # 一樣 600 → 保留申報的
    assert _pick(8, special=True) == '國小以下孩童'     # 500 < 600 → 不可以變貴


def test_the_special_option_is_never_picked_by_age():
    """★ 「持身障證明」沒有年齡條件，所以絕不能被年齡判定選中 ——
    否則會有人莫名其妙被標成身障，那比算錯錢更糟。"""
    for age in range(0, 101):
        assert _pick(age) != '持身障證明'


def test_a_range_on_the_special_option_is_ignored():
    """★★ 管理員**真的可能**幫「持身障證明」也填一個年齡範圍
    （欄位就在那裡，順手填下去很自然）。

    那時候如果照範圍判，符合年齡的人就會被自動標成持有身心障礙證明 ——
    而名冊上那一格看起來就跟本人自己勾的一模一樣，沒有人會發現。

    特殊身分別只能自行申報，年齡範圍對它一律無效。
    （原本這條守衛沒有測試蓋到 —— mutation 測試把它拿掉之後全綠。）
    """
    rules = {
        'enabled': True,
        'special_label': '持身障證明',
        'fallback_label': '成人',
        'ages': {'65歲以上者': [65, None], '國小以下孩童': [None, 12],
                 '持身障證明': [18, 64]},          # ← 管理員順手填的
    }
    for age in (18, 30, 45, 64):
        assert pick_tier(OPTIONS, rules, age) == '成人', \
            f'{age} 歲的人被自動標成身障了'
    # 自己勾的時候當然還是要成立
    assert pick_tier(OPTIONS, rules, 30, True) == '持身障證明'


def test_special_without_a_configured_label_is_ignored():
    """沒設哪一項是特殊身分別時，勾了也不能亂指一個 —— 照年齡判"""
    rules = {'fallback_label': '成人', 'ages': {'65歲以上者': [65, None]}}
    assert pick_tier(OPTIONS, rules, 30, True) == '成人'


def test_special_label_that_no_longer_exists():
    """選項被刪掉之後，設定裡還留著舊名字 —— 不能回一個不存在的選項"""
    rules = {'special_label': '已經刪掉的選項', 'fallback_label': '成人', 'ages': {}}
    assert pick_tier(OPTIONS, rules, 30, True) == '成人'


# ── 算不出來的時候 ──────────────────────────

def test_no_birthday_means_no_answer():
    """★ 沒有生日就算不出身分別 —— 回 None，不可以猜一個。

    猜的話那個人的金額是錯的，而名冊上看起來完全正常。
    """
    assert _pick(None) is None


def test_no_options_at_all():
    assert pick_tier([], RULES, 30) is None
    assert pick_tier(None, RULES, 30) is None


def test_no_rules_at_all():
    """沒有任何設定時回 None —— 不能亂指一個，也不能炸"""
    assert pick_tier(OPTIONS, None, 30) is None
    assert pick_tier(OPTIONS, {}, None) is None


def test_no_fallback_configured_means_no_answer():
    """★ 預設項一定要明確指定。推論的話會出事（見下一條）。"""
    rules = {'special_label': '持身障證明', 'ages': {'65歲以上者': [65, None]}}
    assert pick_tier(OPTIONS, rules, 30) is None


def test_every_option_has_a_range_and_none_match():
    """全部都設了範圍、而年齡都不吻合 → 沒有預設可用，回 None 讓它跳出來"""
    rules = {'special_label': '持身障證明',
             'ages': {'成人': [18, 64], '65歲以上者': [65, None],
                      '國小以下孩童': [None, 12]}}
    assert pick_tier(OPTIONS, rules, 15) is None


def test_an_unmarked_special_option_is_never_used_as_the_fallback():
    """★★ 這條守的是這個模組最嚴重的錯：**把人自動標成身障**。

    管理員設好了年齡範圍卻忘記標「哪一項是特殊身分別」時，
    「持身障證明」就成了「第一個沒設範圍的選項」—— 也就是預設。
    於是一個 15 歲的孩子會被自動標成持有身心障礙證明。

    比算錯錢嚴重得多，而且沒有人會發現：名冊上那一格看起來
    就跟本人自己勾的一模一樣。

    所以剩兩個以上沒設範圍的選項時，一律回 None 讓它跳出來問。
    （這個 bug 是寫測試的時候自己撞到的。）
    """
    rules = {'ages': {'成人': [18, 64], '65歲以上者': [65, None],
                      '國小以下孩童': [None, 12]}}   # 沒有 special_label／fallback_label
    assert pick_tier(OPTIONS, rules, 15) is None, '15 歲的人被標成身障了'


def test_the_normal_setup_still_has_a_fallback():
    """正常設定（有標特殊身分別）時，成人還是預設 —— 不能因為保守就壞掉"""
    assert _pick(45) == '成人'


# ── 開關 ──────────────────────────

def test_it_is_an_explicit_switch():
    assert is_enabled(RULES)
    assert is_enabled({'enabled': True})


def test_off_by_default():
    assert not is_enabled(None)
    assert not is_enabled({})
    assert not is_enabled({'enabled': False})


def test_leftover_age_settings_do_not_turn_it_on():
    """★ 使用者定的：不是每場活動都要按生日分級收費。

    推論式（有範圍就算開）的話，「複製一場舊活動」會靜靜地把自動判定
    一起帶過來 —— 而畫面上看不出差別，那一場就變成沒人能自己選身分別。
    """
    assert not is_enabled({'ages': {'孩童': [None, 12]}, 'fallback_label': '成人'})


# ── 講給報名者聽 ──────────────────────────

def test_the_rules_are_explained_in_plain_language():
    """★ 不講的話，報名者只看到一個自己不能改的身分別，
    會以為是系統填錯了 —— 然後打電話來問。"""
    text = describe(OPTIONS, RULES)
    assert '65 歲以上：65歲以上者' in text
    assert '12 歲以下：國小以下孩童' in text


def test_the_explanation_omits_the_special_option():
    """特殊身分別不是年齡判定的，講進去會讓人以為身障也看年齡"""
    assert '持身障證明' not in describe(OPTIONS, RULES)


def test_a_closed_range_reads_as_a_range():
    text = describe(OPTIONS, {'ages': {'成人': [18, 64]}})
    assert '18–64 歲：成人' in text


def test_the_fallback_is_explained_too():
    """只講「65 歲以上：敬老」的話，30 歲的人不知道自己為什麼是成人"""
    assert '其他年齡：成人' in describe(OPTIONS, RULES)


def test_nothing_to_explain_is_empty_not_a_crash():
    assert describe(OPTIONS, {}) == ''
    assert describe([], None) == ''


# ══ 伺服器端覆蓋（防竄改）══════════════════════════

def _src(path):
    return open(path, encoding='utf-8').read()




def _answer_writers():
    """所有會寫入 registration_answers 的函式 → [(檔名, 函式體)]。

    ★ 用「數幾次」當斷言的話，每加一個寫入點就要回來改數字 ——
      而忘記改的後果是測試紅了、有人把數字加一了事，
      真正該加的那兩道防護沒有加。

      改成列舉：新增寫入點會自動被納入。
    """
    import ast
    import glob
    out = []
    for path in sorted(glob.glob('routes/*.py')):
        src = _src(path)
        if "table('registration_answers').insert" not in src:
            continue
        lines = src.split('\n')
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.FunctionDef):
                continue
            body = '\n'.join(lines[node.lineno - 1:node.end_lineno])
            if "table('registration_answers').insert" in body:
                out.append((f'{path}::{node.name}', body))
    assert out, '找不到任何寫入報名答案的地方 —— 這條測試失效了'
    return out














def test_the_age_basis_is_the_event_date():
    """★ 使用者定的：以活動當日計算。景點是當天查驗的 ——
    用報名日算會出現「系統說他是兒童、現場查出來是成人」。"""
    src = _src('routes/auto_tier.py')
    fn = src[src.index('def event_basis_date'):]
    fn = fn[:fn.index('\ndef ')]
    assert "get('event_start')" in fn




# ══ 報名確認頁 ══════════════════════════════════════
#
# 教會的定義是「填表 ＋ 繳費」才算報名成功。系統只做得到前半段，
# 所以送出的那一刻一定要把兩件事講清楚：你填了什麼、你要繳多少給誰。



















