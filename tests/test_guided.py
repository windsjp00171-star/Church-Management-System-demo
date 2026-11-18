"""引導式開活動：答案 → 草稿

## 這一份守什麼

使用者的宗旨：**「引導就是協助當下開活動報名怎麽做」**。所以這裡守的不是
「問句好不好看」，是**產出的草稿對不對** —— 引導完出來的活動要跟一個
熟手自己設出來的一樣，不然引導式就是在教人設錯。

## ★ 基準案例是資料庫裡真實的那一場

`test_the_autumn_trip_comes_out_right` 拿「2026安南靈糧堂秋之旅」
（120 人、成人 800／孩童 500／長者 600／嬰兒 50、保險要身分證＋生日、
未成年要監護人、要排車桌次）走一遍。那一場是人自己設的，
引導式產出的結果要對得上。

## ★ 三種不能出現的東西

1. **重複的欄位** —— 生日被保險、分級收費、監護人三條路都要到
2. **不會生效的設定** —— 沒上限卻開候補、沒開簽到卻設模式
3. **靜靜的洞** —— 選了待定卻沒有被列出來
"""
import pytest

from routes.guided import (CUSTOM_TYPES, DEFAULTS, FIELD_TEMPLATES,
                           GUARDIAN_EVERYONE, PENDING_EFFECTS, USE_KEYS,
                           USES, build_draft, pending)


def _labels(draft):
    return [f['label'] for f in draft['fields']]


def _types(draft):
    return [f['field_type'] for f in draft['fields']]


def _by_type(draft, ftype):
    return [f for f in draft['fields'] if f['field_type'] == ftype]


# ══ 一、註冊表本身 ══════════════════════════════════

@pytest.mark.parametrize('use', USES, ids=lambda u: u['key'])
def test_every_use_adds_a_real_field(use):
    """★★ 用途要對到真的欄位樣板。

    對不到的話，勾了那個用途**什麼都不會發生** —— 而畫面上完全正常。
    這正是「把清單搬進資料庫」最危險的地方（見模組 docstring）。
    """
    assert use['adds'], f"{use['key']} 沒有加任何欄位"
    for key in use['adds']:
        assert key in FIELD_TEMPLATES, f"{use['key']} 指到不存在的欄位樣板 {key}"


@pytest.mark.parametrize('use', USES, ids=lambda u: u['key'])
def test_every_use_says_what_it_did(use):
    """★★ 系統做的推論一定要講出來。

    默默加上去的話，他不知道那個欄位為什麼在那裡 —— 下次看到會想刪掉，
    而刪掉之後保險名單就少了兩欄。
    """
    assert use['says'] and len(use['says']) >= 10, f"{use['key']} 沒有說明"


@pytest.mark.parametrize('tpl', FIELD_TEMPLATES.values(), ids=FIELD_TEMPLATES.keys())
def test_every_template_is_a_real_field_type(tpl):
    from routes.field_types import FIELD_TYPES
    assert tpl['field_type'] in FIELD_TYPES


def test_custom_types_stay_out_of_the_dependency_web():
    """★★ 自己加題目只給三種型別，而那三種**不參與任何一條依賴**。

    放進分級收費或生日的話，「自己加一題」這個出口就會把前面整理好的
    依賴弄亂 —— 例如他自己加了一個分級收費欄位，而年齡判定沒有生日可用。
    """
    from routes.setting_deps import DEPENDENCIES
    risky = {'fee', 'birthday', 'id_number', 'guardian'}
    assert not (set(CUSTOM_TYPES) & risky)
    #  依賴表確實在管那幾種 —— 不然上面那條是在防一件不存在的事
    assert any('birthday' in (d.effect + d.label) or 'birthday' in d.key
               for d in DEPENDENCIES)


# ══ 二、基準案例：秋之旅 ═══════════════════════════

AUTUMN = {
    'title': '2026安南靈糧堂秋之旅',
    'event_start': '2026-10-08T07:30', 'event_end': '2026-10-09T18:00',
    'capacity': 120, 'waitlist': False,
    'fee_mode': 'tiered',
    'tiers': [{'label': '成人', 'price': 800}, {'label': '孩童', 'price': 500},
              {'label': '長者', 'price': 600}, {'label': '嬰兒', 'price': 50},
              {'label': '優待', 'price': 600}],
    'tier_ages': {'孩童': [None, 12], '長者': [65, None], '嬰兒': [None, 2]},
    'tier_special': '優待',
    'uses': ['insurance', 'seating', 'guardian'],
    'reg_end': '2026-09-24T23:59',
    'payment_deadline_pending': True,
    'checkin': False,
    'who': 'anyone',
}


def test_the_autumn_trip_comes_out_right():
    """★★★ 引導式產出的要跟人自己設的那一場對得上。"""
    d = build_draft(AUTUMN)
    ev, labels = d['event'], _labels(d)

    assert ev['title'] == '2026安南靈糧堂秋之旅'
    assert ev['capacity'] == 120
    assert ev['allow_external_reg'] is True
    #  ★ 錢全在分級收費裡，基本費一定是 0 ——
    #    不然每個人會被多收一次（那是使用者真的踩過的坑）
    assert ev['fee'] == 0

    assert '參加者姓名' in labels
    assert '身分證字號' in labels
    assert '出生年月日' in labels
    assert '身分別' in labels
    assert '監護人' in labels
    assert any('備註' in l for l in labels)


def test_the_tier_options_carry_the_prices():
    d = build_draft(AUTUMN)
    opts = _by_type(d, 'fee')[0]['options']
    assert '成人|800' in opts and '孩童|500' in opts and '嬰兒|50' in opts


def test_the_auto_tier_is_actually_enabled():
    """★★ 只把年齡範圍存起來、沒有把 enabled 打開的話，
    自動判定不會生效 —— 而後台那一格看起來設好了。"""
    from routes.auto_tier import is_enabled
    tier = _by_type(build_draft(AUTUMN), 'fee')[0]
    assert is_enabled(tier.get('auto_tier'))
    assert tier['auto_tier']['fallback_label'] == '成人'
    assert tier['auto_tier']['special_label'] == '優待'


def test_the_special_tier_never_gets_an_age_range():
    """★ 自行申報那一項是「年齡看不出來」才存在的。
    給它年齡範圍的話，它就變成年齡判得出來的一級了。"""
    a = dict(AUTUMN, tier_ages=dict(AUTUMN['tier_ages'], **{'優待': [70, None]}))
    tier = _by_type(build_draft(a), 'fee')[0]
    #  special 仍然是 special，fallback 也還是成人（沒有被優待搶走）
    assert tier['auto_tier']['special_label'] == '優待'
    assert tier['auto_tier']['fallback_label'] == '成人'


def test_no_duplicate_birthday():
    """★★★ 生日被保險、分級收費、監護人**三條路**都要到。

    不去重的話表單上會有三題出生年月日，而每一題都必填 ——
    報名者會以為自己看錯了。
    """
    d = build_draft(AUTUMN)
    assert _types(d).count('birthday') == 1


def test_no_duplicate_phone():
    """電話同時被「要能聯絡到他」和「開放外部報名」要到。"""
    d = build_draft(dict(AUTUMN, uses=['contact'], who='anyone'))
    assert _labels(d).count('連絡電話') == 1


def test_the_name_field_is_always_there_and_named_right():
    """★★ 姓名不問、一律自動加，而且名字就叫「參加者姓名」。

    簽到名單和名冊都靠這一格認人 —— 代報的時候才不會整欄變成
    代報者的名字。
    """
    d = build_draft({'title': '隨便一場', 'uses': [], 'who': 'members'})
    assert d['fields'][0]['label'] == '參加者姓名'
    assert d['fields'][0]['is_required'] is True


# ══ 三、不會生效的設定不可以留下 ════════════════════

def test_waitlist_without_capacity_is_turned_off():
    """★★ 沒有上限就不會額滿，候補永遠不會發生 ——
    留一個打開的候補開關等於留一個假的設定。"""
    d = build_draft({'capacity_pending': True, 'waitlist': True})
    assert d['event']['waitlist_enabled'] is False


def test_checkin_mode_is_not_set_when_checkin_is_off():
    d = build_draft({'checkin': False, 'open_checkin': True})
    assert d['event']['checkin_mode'] == 'registered_only'


def test_open_checkin_survives_when_checkin_is_on():
    d = build_draft({'checkin': True, 'open_checkin': True})
    assert d['event']['checkin_mode'] == 'open'


def test_flat_fee_and_tiers_can_never_both_have_a_value():
    """★★★ 「基本費 800 ＋ 成人 800 ＝ 收 1600」那個坑，
    在引導式裡是被**問法**填掉的（三選一），不是靠檢查擋的。"""
    d = build_draft(dict(AUTUMN, fee=800))       # 就算答案裡混進了 fee
    assert d['event']['fee'] == 0                # 分級模式一律歸 0

    flat = build_draft({'fee_mode': 'flat', 'fee': 300,
                        'tiers': [{'label': '成人', 'price': 800}]})
    assert flat['event']['fee'] == 300
    assert not _by_type(flat, 'fee')             # 也不會生出分級欄位


def test_auto_tier_is_dropped_when_no_ages_were_given():
    """★ 沒有年齡範圍還開自動判定的話，每個人都會落到 fallback ——
    孩童被收成人價，而名冊上每一格都正常。算不出來就不要開。"""
    d = build_draft(dict(AUTUMN, tier_ages={}))
    tier = _by_type(d, 'fee')[0]
    assert not tier.get('auto_tier')
    #  ★ 也不該為了一個不存在的判定而硬加生日
    assert 'birthday' in _types(d)   # 保險那條路還是要生日
    d2 = build_draft({'fee_mode': 'tiered', 'tiers': AUTUMN['tiers'],
                      'tier_ages': {}, 'uses': [], 'who': 'members'})
    assert 'birthday' not in _types(d2)


# ══ 四、待定不可以是安靜的洞 ═══════════════════════

def test_pending_items_are_listed_with_their_consequence():
    """★★★ 只寫「待定」的話那件事會靜靜地不發生，
    而後台每一格看起來都正常。"""
    items = pending(dict(AUTUMN, reg_end_pending=True))
    keys = {i['key'] for i in items}
    assert keys == {'reg_end', 'payment_deadline'}
    for i in items:
        assert i['effect'] and len(i['effect']) >= 8, f"{i['key']} 沒寫後果"


def test_nothing_pending_means_an_empty_list():
    assert pending(dict(AUTUMN, payment_deadline_pending=False,
                        payment_deadline='2026-10-01')) == []


def test_payment_deadline_is_not_listed_for_a_free_event():
    """★ 不收費的活動根本沒問過繳費期限 ——
    列出來的話他會去找一個他沒看過的東西。"""
    items = pending({'fee_mode': 'none', 'payment_deadline_pending': True})
    assert not any(i['key'] == 'payment_deadline' for i in items)


@pytest.mark.parametrize('key', PENDING_EFFECTS)
def test_every_pending_effect_says_what_will_not_happen(key):
    """後果要寫「會怎樣」，不是重複一次「你沒設」。"""
    text = PENDING_EFFECTS[key]
    assert '不' in text, f'{key} 的後果沒有講出「不會發生什麼」'


def test_pending_becomes_a_real_null_not_a_guess():
    """★ 待定就是待定 —— 不可以偷偷塞一個預設日期進去。

    塞了的話他以為自己沒設，實際上有一個他不知道的截止日在跑。
    """
    d = build_draft({'reg_end': '2026-09-24T23:59', 'reg_end_pending': True,
                     'capacity': 80, 'capacity_pending': True})
    assert d['event']['reg_end'] is None
    assert d['event']['capacity'] is None


# ══ 五、每個人都要填家長 ═══════════════════════════

def test_guardian_for_everyone_uses_the_guardian_type_with_a_mark():
    """★★ 這條路原本走**兩個一般欄位**（「家長姓名」「家長電話」）——
    因為監護人型別那時候表達不出「每個人都問」：
    `_apply_guardian_conditions` 會把沒設條件的自動補上「未滿18歲才問」。

    那個洞補起來之後（`routes/guardian.everyone_condition`）就改回監護人
    型別了。兩個一般欄位少掉的東西是實的：**「兩格都填才算填了」不見了**
    —— 只打名字也能過必填，而名冊上那一列打不到人。
    """
    from routes.guardian import EVERYONE, condition_mark
    d = build_draft({'uses': ['guardian'], 'guardian_scope': 'everyone',
                     'who': 'members'})
    g = _by_type(d, 'guardian')
    assert len(g) == 1, '「每個人都問」那條路沒有出監護人欄位'
    assert condition_mark(g[0].get('condition_json')) == EVERYONE, \
        '沒有帶「每個人都問」的印記 —— 存下去會被補成「未滿18歲才問」'
    assert g[0]['is_required']


def test_guardian_for_everyone_does_not_need_a_birthday():
    """★★ 兒童營不想問生日。勾了「每個人都要填」就不靠年齡判斷，
    所以草稿裡不該為了它硬塞一題出生日期。"""
    d = build_draft({'uses': ['guardian'], 'guardian_scope': 'everyone',
                     'who': 'members'})
    assert 'birthday' not in _types(d)


def test_guardian_for_minors_uses_the_guardian_type():
    d = build_draft({'uses': ['guardian'], 'who': 'members'})
    assert 'guardian' in _types(d)
    assert 'birthday' in _types(d), '算年齡要用生日，沒有的話那題永遠不出現'


def test_a_guardian_field_never_ships_without_a_birthday():
    """★★★ 靠年齡判斷的監護人欄位一定要跟出生日期一起出現，
    **任何答案組合都是**。

    少了生日的話，`_apply_guardian_conditions` 會**擋下整個建立** ——
    使用者走完七題、按下「建立活動」，跳出一個他看不懂的錯誤，
    前面全部白填。

    ★ 勾了「每個人都要填」的那一種不靠年齡，所以不在這條的範圍內
      （它反而**不該**帶生日 —— 見上面那條）。分不出來的話，
      這條會逼兒童營多問一題他們不想問的出生日期。

    ★ 這一條是逐一組合跑的，不是抽一個例子：生日有三個來源
      （保險、分級收費的年齡判定、監護人自己），拿掉其中一個
      另外兩個還會補上 —— 單一例子的測試**驗不出**是哪一條在作用。
    """
    import itertools
    modes = [{'fee_mode': 'none'},
             {'fee_mode': 'flat', 'fee': 300},
             {'fee_mode': 'tiered', 'tiers': [{'label': '成人', 'price': 800},
                                              {'label': '孩童', 'price': 500}],
              'tier_ages': {'孩童': [None, 12]}},
             {'fee_mode': 'tiered', 'tiers': [{'label': '成人', 'price': 800}],
              'tier_ages': {}}]
    for n in range(len(USE_KEYS) + 1):
        for uses in itertools.combinations(USE_KEYS, n):
            for mode in modes:
                for scope in ('minor', 'everyone'):
                    a = dict(mode, uses=list(uses), guardian_scope=scope,
                             who='members')
                    d = build_draft(a)
                    guards = _by_type(d, 'guardian')
                    if not guards:
                        continue
                    from routes.guardian import EVERYONE, condition_mark
                    if all(condition_mark(g.get('condition_json')) == EVERYONE
                           for g in guards):
                        continue          # 不靠年齡的那一種
                    assert 'birthday' in _types(d), (
                        f'uses={uses} mode={mode["fee_mode"]} scope={scope}：'
                        '有監護人卻沒有生日 —— 這場活動建立時會被擋下來')


def test_the_guardian_condition_is_left_to_the_server():
    """★★ 「未滿18歲才問」那個條件這裡一個字都不寫。

    寫一份的話，`trigger_sort_order`（畫面上的第幾題）就有兩個來源 ——
    差一號就指到別的問題上，而畫面完全看不出來。
    """
    d = build_draft({'uses': ['guardian'], 'who': 'members'})
    g = _by_type(d, 'guardian')[0]
    assert not g.get('condition_json')


# ══ 六、自己加的題目 ═══════════════════════════════

def test_custom_questions_are_appended_last():
    """★ 自己加的排最後 —— 插在中間的話，
    伺服器算出來的跳題 index 會跟他預期的不一樣。"""
    d = build_draft(dict(AUTUMN, custom=[
        {'label': '您是從哪裡得知活動消息呢', 'field_type': 'radio',
         'options': '教會門外海報\n親友告知'}]))
    assert d['fields'][-1]['label'] == '您是從哪裡得知活動消息呢'
    assert d['fields'][-1]['options'] == '教會門外海報\n親友告知'


def test_a_custom_question_cannot_smuggle_in_a_risky_type():
    """★★ 只給三種型別是規則，不是 UI 的裝飾 ——
    直接打 API 的話也要擋。"""
    d = build_draft({'custom': [{'label': '身分別', 'field_type': 'fee',
                                 'options': '成人|800'}]})
    assert d['fields'][-1]['field_type'] == 'text'


def test_a_custom_question_without_a_label_is_dropped():
    d = build_draft({'who': 'members',
                     'custom': [{'label': '   ', 'field_type': 'text'}]})
    assert _labels(d) == ['參加者姓名']


# ══ 七、不問的那些有預設 ═══════════════════════════

def test_the_defaults_are_all_applied():
    """★ 「不問」不等於「不見了」。"""
    ev = build_draft({})['event']
    for key, val in DEFAULTS.items():
        assert ev[key] == val, f'{key} 的預設沒有套上'


def test_proxy_registration_is_on_by_default():
    """★ 代報是常態（小組長幫長輩報名）。關著的話他幫第二個人報名會被擋，
    而那個錯誤訊息看起來像系統壞了。"""
    assert build_draft({})['event']['allow_multiple'] is True


def test_it_survives_a_half_answered_draft():
    """★ 引導式問到一半就送出是正常的（他中途退出）—— 不可以炸。"""
    for a in ({}, None, {'uses': None}, {'tiers': [{}]}, {'fee_mode': 'tiered'},
              {'custom': [{}]}, {'tier_ages': {'x': None}}):
        d = build_draft(a)
        assert d['fields'][0]['label'] == '參加者姓名'


def test_the_answers_never_reach_the_database_from_here():
    """★ `build_draft` 是純函式 —— 引導問到一半時活動還不存在，
    會自己查資料庫的函式在那個情境下跑不起來。"""
    import inspect

    import routes.guided as g
    src = inspect.getsource(g)
    assert 'supabase' not in src, 'guided.py 不該碰資料庫'


def test_use_keys_match_the_registry():
    assert USE_KEYS == [u['key'] for u in USES]
    assert len(set(USE_KEYS)) == len(USE_KEYS)
    assert GUARDIAN_EVERYONE, '「每個人都問」那條路沒有欄位可用'
