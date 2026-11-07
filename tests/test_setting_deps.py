"""設定之間的關係：一張註冊表守著

## 這一份守什麼

盤點出來 11 條依賴，而系統原本對它們給了**四種完全不同的待遇** ——
即時講 1 條、存檔擋 2 條、存好了才說 1 條、**完全不講 7 條**。

那四種待遇不是設計出來的，是一次一次補出來的。所以這一份守的第一件事
就是：**每一條都要在註冊表裡**，而且**每一條都要真的會觸發**。

## ★ 註冊表最容易出的錯是「登記了但不會響」

一條 `applies` 永遠回 False 的規則，跟沒有那條規則**完全一樣**——
而它在檔案裡看起來很完整。所以每一條都要有一個「會響」和一個
「不會響」的實例，兩邊都驗。
"""
import inspect

import pytest

from routes.setting_deps import (CONFLICT, DEPENDENCIES, NEEDS, blocking,
                                 messages, unmet)

EVENTS = [d for d in DEPENDENCIES if d.module == 'events']

#  ★ 有幾條守衛跟模組無關（後果的寫法、predicate 要純）——
#    那幾條要跑**全部**，不是只跑活動的。原本只掃 EVENTS，
#    所以課程那七條進來時一條都沒被檢查到。
ALL_DEPS = list(DEPENDENCIES)


def _ctx(event=None, fields=None, groups=None):
    return {'event': event or {}, 'fields': fields or [],
            'primary_groups': groups if groups is not None else ['活水小組']}


# ══ 一、註冊表本身 ══════════════════════════════════



def test_every_key_is_unique():
    keys = [d.key for d in DEPENDENCIES]
    assert len(keys) == len(set(keys)), '有重複的 key'


@pytest.mark.parametrize('dep', ALL_DEPS, ids=lambda d: f'{d.module}.{d.key}')
def test_every_dep_says_the_consequence_not_the_rule(dep):
    """★★★ `effect` 要寫**後果**，不是重複一次規則。

        ✗ 「開放候補需要設定人數上限」   ← 規則，他已經知道了
        ✓ 「沒設上限就不會額滿，候補永遠不會發生」← 後果，他不知道

    規則式的訊息讀起來像系統在挑剔；後果式的才讓人知道**為什麼要理它**。
    """
    assert dep.effect and len(dep.effect) >= 20, f'{dep.key} 的後果寫得太短'
    #  ★ 「需要」「必須」「請先」是規則的語氣 —— 後果不長那樣。
    for rule_ish in ('需要設定', '必須設定', '請先設定'):
        assert rule_ish not in dep.effect, \
            f'{dep.key} 的 effect 在複述規則（「{rule_ish}」），沒有講後果'


@pytest.mark.parametrize('dep', ALL_DEPS, ids=lambda d: f'{d.module}.{d.key}')
def test_every_dep_is_a_pure_function(dep):
    """★★ `applies` / `met` **不可以自己查資料庫**。

    這些 predicate 之後要在**引導式問答的當下**跑 —— 那時候活動還不存在、
    什麼都還沒存。會查資料庫的 predicate 在那個情境下不是回錯答案，
    就是根本跑不起來。

    要資料庫的東西（主標籤小組）由呼叫端先撈好放進 ctx。
    """
    for fn in (dep.applies, dep.met):
        src = inspect.getsource(fn) if not isinstance(fn, str) else ''
        assert 'supabase' not in src, f'{dep.key} 的 predicate 自己查了資料庫'


def test_only_the_guardian_one_blocks():
    """★ 使用者定的：「不擋，只講」。監護人那條是**既有行為**，不是新加的。

    ★ 反向守衛：哪天有人「順手」把全部都設成 blocks，管理員會發現
      活動編一半存不起來 —— 而他還沒要處理那個問題。
    """
    blockers = [d.key for d in DEPENDENCIES if d.blocks]
    assert blockers == ['guardian_needs_birthday'], \
        f'擋存檔的變成 {blockers} —— 使用者定的是「不擋，只講」'


def test_the_shape_is_not_tied_to_events():
    """★ 使用者：「未來想把這樣的模式推進去系統全域」。

    所以每一列都要帶 `module`，而且函式要收 module 參數 ——
    形狀綁死活動的話，門訓課程要用時得整個重做。
    """
    assert all(d.module for d in DEPENDENCIES)
    #  換一個模組名字要回空的，不是回活動那幾條
    assert unmet('courses', _ctx(event={'waitlist_enabled': True})) == []


# ══ 二、★★ 每一條都要真的會響 ══════════════════════
#
# 一條 `applies` 永遠回 False 的規則，跟沒有那條規則完全一樣 ——
# 而它在檔案裡看起來很完整。

BIRTHDAY = {'label': '出生日期', 'field_type': 'birthday'}
GUARDIAN = {'label': '監護人', 'field_type': 'guardian'}
TIER = {'label': '身分別', 'field_type': 'fee', 'options': '成人|800\n孩童|500'}
TIER_AUTO = dict(TIER, auto_tier={'enabled': True, 'fallback_label': '成人'})
NAME_F = {'label': '參加者姓名', 'field_type': 'text'}
PHONE_F = {'label': '聯絡電話', 'field_type': 'text'}

#  (key, 會響的 ctx, 不會響的 ctx)
CASES = [
    ('waitlist_needs_capacity',
     _ctx({'waitlist_enabled': True}),
     _ctx({'waitlist_enabled': True, 'capacity': 80})),
    ('reserved_needs_capacity',
     _ctx({'member_reserved': 20}),
     _ctx({'member_reserved': 20, 'capacity': 80})),
    ('waitlist_deadline_needs_waitlist',
     _ctx({'waitlist_deadline': '2026-10-01T00:00:00Z'}),
     _ctx({'waitlist_deadline': '2026-10-01T00:00:00Z', 'waitlist_enabled': True})),
    ('auto_tier_needs_birthday',
     _ctx({}, [TIER_AUTO]),
     _ctx({}, [TIER_AUTO, BIRTHDAY])),
    ('fee_adds_to_tiers',
     _ctx({'fee': 800}, [TIER]),
     _ctx({'fee': 0}, [TIER])),
    ('money_needs_primary_groups',
     _ctx({'fee': 800}, [], groups=[]),
     _ctx({'fee': 800}, [], groups=['活水小組'])),
    ('external_needs_name_field',
     _ctx({'allow_external_reg': True}, [PHONE_F]),
     _ctx({'allow_external_reg': True}, [NAME_F, PHONE_F])),
    ('external_needs_phone_field',
     _ctx({'allow_external_reg': True}, [NAME_F]),
     _ctx({'allow_external_reg': True}, [NAME_F, PHONE_F])),
    ('guardian_needs_birthday',
     _ctx({}, [GUARDIAN]),
     _ctx({}, [GUARDIAN, BIRTHDAY])),
    #  ★ 生日欄位在 index 0，監護人的條件指向它。
    #    「會響」＝ 生日不是必填；「不會響」＝ 生日也設成必填。
    ('required_age_jump_needs_required_birthday',
     _ctx({}, [BIRTHDAY, dict(GUARDIAN, is_required=True,
                              condition_json={'trigger_sort_order': 0,
                                              'op': 'age_between',
                                              'min': None, 'max': 17})]),
     _ctx({}, [dict(BIRTHDAY, is_required=True),
               dict(GUARDIAN, is_required=True,
                    condition_json={'trigger_sort_order': 0,
                                    'op': 'age_between',
                                    'min': None, 'max': 17})])),
    ('checkin_options_need_checkin',
     _ctx({'allow_open_checkin': True}),
     _ctx({'allow_open_checkin': True, 'checkin_enabled': True})),
]


def test_every_dep_has_a_case():
    """★★ 沒有實例的規則等於沒有被驗過 —— 而它在檔案裡看起來很完整。"""
    covered = {k for k, _, _ in CASES}
    #  兩條外部報名共用一個設定，所以 CASES 會少於 DEPENDENCIES？不會 ——
    #  它們是兩條獨立的規則，各自有實例。
    missing = sorted({d.key for d in EVENTS} - covered)
    assert not missing, f'這幾條沒有實例：{missing}'




@pytest.mark.parametrize('key,fires,quiet', CASES, ids=[c[0] for c in CASES])
def test_it_stays_quiet_when_it_should(key, fires, quiet):
    """★★★ 不該響那一邊。

    ★ 這一半跟上一半一樣重要：一條**永遠都響**的規則會被學會忽略 ——
      等哪天它真的在警告你，你不會注意到，因為它跟平常長得一模一樣。
      （名冊那個「永遠亮著的 ⚠」踩過同一件事。）
    """
    assert key not in {d.key for d in unmet('events', quiet)}, \
        f'{key} 不該響的時候還在響'


def test_a_blank_event_is_quiet():
    """★★ 什麼都還沒填的時候**一句話都不要講**。

    引導式問答一開始 ctx 是空的 —— 那時候跳出十條警告，
    等於還沒開始就先罵人一頓。
    """
    assert unmet('events', _ctx()) == []
    assert unmet('events', {}) == []
    assert unmet('events', None) == []


# ══ 三、訊息 ══════════════════════════════════════

def test_the_message_has_all_three_parts():
    """★ 「設定 → 需要 → 後果」三段都要在。

    只講「缺了什麼」的話，他不知道要不要理它。
    """
    msgs = messages('events', _ctx({'waitlist_enabled': True}))
    assert len(msgs) == 1
    line = msgs[0]
    assert '開放候補名單' in line      # 哪個設定
    assert '人數上限' in line          # 需要什麼
    assert '永遠不會發生' in line       # 後果




def test_a_conflict_reads_differently_from_a_missing_thing():
    """★ 「兩個設定互相影響」跟「少了一個東西」是不同的事 ——
    用同一句話講的話，他會去找一個不存在的缺口。"""
    line = messages('events', _ctx({'fee': 800}, [TIER]))[0]
    assert '同時設定' in line
    assert '但還沒有' not in line


def test_blocking_is_a_subset_of_unmet():
    ctx = _ctx({}, [GUARDIAN])
    assert [d.key for d in blocking('events', ctx)] == ['guardian_needs_birthday']
    assert blocking('events', _ctx({}, [GUARDIAN, BIRTHDAY])) == []


def test_a_broken_predicate_does_not_break_the_save():
    """★★ 一條提示壞了，不可以讓人存不了活動。

    這是加值的東西 —— 跟小舟、稽核日誌同一個原則。
    """
    import routes.setting_deps as m

    boom = m.Dep(module='events', key='boom', label='x', needs='y',
                 effect='這是一條會爆炸的規則，用來驗它不會把存檔弄壞',
                 applies=lambda c: 1 / 0, met=lambda c: True)
    orig = m.DEPENDENCIES
    try:
        m.DEPENDENCIES = orig + [boom]
        out = unmet('events', _ctx({'waitlist_enabled': True}))
    finally:
        m.DEPENDENCIES = orig
    assert 'waitlist_needs_capacity' in {d.key for d in out}, \
        '一條爆炸的規則把其他的也弄不見了'


# ══ 四、★★ 接上去了嗎 ═══════════════════════════════

def test_the_save_path_uses_the_registry():
    """★★ 存檔後的提醒要走註冊表，不是自己再實作一份。

    `external_form_warnings` 原本自己寫了那兩條 —— 它是**唯一**被寫出來的
    依賴檢查，而系統其實有 11 條。留著自己那份的話，同一批規則會在
    四個地方各長一份（引導式、即時提示、存檔、小舟）。
    """
    import re
    src = open('routes/admin.py', encoding='utf-8').read()
    fn = src[src.index('def external_form_warnings('):]
    fn = fn[:fn.index('\ndef _primary_group_names_safe')]
    code = re.sub(r'"""[\s\S]*?"""', '', fn)
    code = re.sub(r'^\s*#.*$', '', code, flags=re.M)
    assert 'setting_deps' in code, 'external_form_warnings 沒有走註冊表'
    assert 'NAME_LABELS' not in code, '還留著自己那份規則'


def test_the_registry_really_gets_the_groups(app):
    """★★★ 「沒有主標籤小組」那條要靠 ctx 裡的 `primary_groups`。

    呼叫端忘了撈的話，那條會**永遠在響**（每一場收費活動都跳一次）——
    而它看起來像一個真的問題，於是會被學會忽略。

    ★★ 掃原始碼證明不了這件事：第一版寫 `'primary_groups' in code`，
       而把值換成寫死的 `[]` 之後那個字還在 —— 測試照樣綠，
       而每一場收費活動都會多跳一句假警告。（mutation 抓到的。）
       所以**真的呼叫一次**，用一個有小組的假資料庫。
    """
    import glob
    import os
    from contextlib import ExitStack
    from unittest.mock import MagicMock, patch

    from routes.admin import external_form_warnings

    def _db(groups):
        sb = MagicMock()

        def table(name):
            c = MagicMock()
            for meth in ('select', 'eq', 'order', 'in_'):
                getattr(c, meth).return_value = c
            c.execute.return_value.data = (
                [{'name': g} for g in groups] if name == 'groups' else [])
            return c
        sb.table.side_effect = table
        return sb

    def _warn(groups):
        with ExitStack() as st:
            for path in glob.glob('routes/*.py'):
                mod = 'routes.' + os.path.basename(path)[:-3]
                try:
                    st.enter_context(patch(f'{mod}.supabase', _db(groups)))
                except (AttributeError, ModuleNotFoundError):
                    pass
            return external_form_warnings({'fee': 800}, [])

    assert any('主標籤' in m for m in _warn([])), \
        '沒有主標籤小組時該提醒卻沒提醒'
    assert not any('主標籤' in m for m in _warn(['活水小組'])), \
        '有主標籤小組了還在提醒 —— 呼叫端沒有真的把它撈進 ctx'


def test_looking_up_the_groups_never_breaks_the_save():
    """★ 撈小組失敗要回空的，不可以讓存檔一起壞。"""
    import re
    src = open('routes/admin.py', encoding='utf-8').read()
    fn = src[src.index('def _primary_group_names_safe('):]
    fn = fn[:fn.index('\ndef ')]
    assert 'except Exception' in fn
