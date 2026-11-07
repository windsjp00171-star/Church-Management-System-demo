"""門訓課程的設定依賴

## 為什麼是課程當第二個模組

**不是因為它感覺比較複雜，是因為查過使用量。** 盤點時的實際數字：

    2 門課、14 堂次、71 筆報名、164 筆出席、265 張完訓、42 筆教材領用

跟活動同一個量級（3 場活動、160 筆報名）。而禱讀本、週報、行事曆那種
一張表幾個欄位、彼此不相干的模組，盤點了也沒有依賴可登記。

## 七條都追到實際的判斷式

不是憑印象列的 —— 每一條下面都寫了它在哪裡生效。

## ★ 最難發現的那一條

`total_sessions` 是**手填的**，而出席統計用的是實際建立的堂次數
（`courses_common.build_attendance_stats` 用 `len(sessions)`）。
兩個數字對不上時：

  - 「我的學程」的進度條 → 實際堂次（`courses.py` 用 `len(sids)`）
  - 「我的記錄」的進度條 → 手填的欄位（`my_history.html`）

**同一個學員的進度，兩頁會顯示不同的百分比，而兩頁看起來都正常。**
"""
import pytest

from routes.setting_deps import (CONFLICT, DEPENDENCIES, MISMATCH, messages,
                                 unmet)

COURSES = [d for d in DEPENDENCIES if d.module == 'courses']
KEYS = {d.key for d in COURSES}


def _ctx(course=None, sessions=0, whitelist=0, material=None, saved=True):
    return {
        'course': course or {},
        'sessions': [{'id': f's{i}'} for i in range(sessions)],
        'whitelist_count': whitelist,
        'linked_material': material,
        'saved': saved,
    }


def _fired(ctx):
    return {d.key for d in unmet('courses', ctx)}


# ══ 一、註冊表本身 ══════════════════════════════════

def test_the_inventory_is_all_here():
    assert len(COURSES) == 7, f'課程的依賴變成 {len(COURSES)} 條了'


def test_the_registry_now_has_two_modules():
    """★ 第二個模組進來，證明 `module` 那一欄不是裝飾。

    只有一個模組的話，「形狀是通用的」是一句沒有被驗證過的話。
    """
    mods = {d.module for d in DEPENDENCIES}
    assert mods == {'events', 'courses'}, mods


@pytest.mark.parametrize('dep', COURSES, ids=lambda d: d.key)
def test_nothing_here_blocks_the_save(dep):
    """★ 課程這七條**一條都不擋存檔**。

    活動那邊唯一擋的是監護人（它本來就在擋，登記進來只是為了讓
    引導式和提示也看得到）。課程這邊沒有既有的擋，
    所以也不要新增一個 —— 課程常常先建好再慢慢排堂次，
    擋下來會把人卡在一個他還沒要處理的問題上。
    """
    assert dep.blocks is False


# ══ 二、每一條都要「會響」和「不會響」═══════════════

#  (key, 會響的 ctx, 不會響的 ctx)
CASES = [
    ('total_sessions_matches_real_sessions',
     _ctx({'total_sessions': 8}, sessions=4),
     _ctx({'total_sessions': 4}, sessions=4)),

    ('absence_limit_needs_sessions',
     _ctx({'absence_limit': 2}, sessions=0),
     _ctx({'absence_limit': 2}, sessions=10)),

    ('absence_limit_below_total',
     _ctx({'absence_limit': 4}, sessions=4),
     _ctx({'absence_limit': 2}, sessions=10)),

    ('material_fee_needs_material_flag',
     _ctx({'material_fee': 145, 'has_material': False}),
     _ctx({'material_fee': 145, 'has_material': True})),

    ('material_fee_is_overridden_by_the_material',
     _ctx({'material_fee': 145, 'has_material': True},
          material={'selling_price': 200}),
     _ctx({'material_fee': 145, 'has_material': True},
          material={'selling_price': 145})),

    ('whitelist_needs_names',
     _ctx({'whitelist_enabled': True}, whitelist=0),
     _ctx({'whitelist_enabled': True}, whitelist=21)),

    ('prerequisite_course_is_ignored',
     _ctx({'prerequisite_course_id': 'a', 'prerequisite_category_id': 'b'}),
     _ctx({'prerequisite_category_id': 'b'})),
]


def test_every_dep_has_a_case():
    """★★ 沒有案例的規則等於沒被驗過 —— 而它在檔案裡看起來很完整。"""
    assert {k for k, _f, _q in CASES} == KEYS, \
        f'漏了：{KEYS - {k for k, _f, _q in CASES}}'


@pytest.mark.parametrize('key,fires,quiet', CASES, ids=lambda x: x if isinstance(x, str) else '')
def test_it_fires_when_it_should(key, fires, quiet):
    assert key in _fired(fires), f'{key} 該響卻沒響'


@pytest.mark.parametrize('key,fires,quiet', CASES, ids=lambda x: x if isinstance(x, str) else '')
def test_it_stays_quiet_when_it_should(key, fires, quiet):
    """★★ 「登記了但永遠會響」跟「永遠不響」一樣糟 ——
    每次都跳的提醒，看兩次就沒有人看了。"""
    assert key not in _fired(quiet), f'{key} 不該響卻響了'


def test_a_blank_course_is_quiet():
    """★ 剛按下「新增學程」什麼都還沒填的時候，不可以一片紅。"""
    assert messages('courses', _ctx()) == []
    assert messages('courses', {}) == []
    assert messages('courses', None) == []


# ══ 三、真實資料要是安靜的 ═══════════════════════════

@pytest.mark.parametrize('name,course,sessions,whitelist,material', [
    #  ★ 這兩門是資料庫裡**真的**存在的課，數字照抄。
    #    盤點的結論是「規則對，但沒有東西在維持它」——
    #    所以真實資料必須是安靜的，跳出提醒就是我把規則寫錯了。
    ('全人更新營',
     {'total_sessions': 4, 'absence_limit': 1, 'material_fee': 80,
      'has_material': True, 'whitelist_enabled': False},
     4, 0, {'selling_price': 80}),
    ('幸福大學上',
     {'total_sessions': 10, 'absence_limit': 2, 'material_fee': 145,
      'has_material': True, 'whitelist_enabled': True,
      'prerequisite_category_id': 'cat-1'},
     10, 21, {'selling_price': 145}),
])
def test_the_real_courses_are_quiet(name, course, sessions, whitelist, material):
    got = messages('courses', _ctx(course, sessions, whitelist, material))
    assert got == [], f'{name} 跳出提醒了：{got}'


# ══ 四、訊息的形狀 ═════════════════════════════════

def test_the_number_ones_do_not_read_like_switches():
    """★★ 「開了『共 N 堂』」不是中文。

    前兩種句型都預設那個設定是開關，而課程這邊有幾個是**數字** ——
    讀起來怪的提醒沒有人會理它，等於白做。
    """
    m = messages('courses', _ctx({'total_sessions': 8}, sessions=4))[0]
    assert '開了' not in m, f'數字型的用了開關的句型：{m}'
    assert '8' in m and '4' in m, f'沒有把兩個數字都講出來：{m}'


def test_the_mismatch_kind_is_actually_used():
    """★ 加了一種 kind 卻沒有人用的話，那是死程式碼。"""
    assert any(d.kind == MISMATCH for d in COURSES)
    assert any(d.kind == CONFLICT for d in COURSES)
    assert any(d.kind not in (MISMATCH, CONFLICT) for d in COURSES)


def test_the_material_message_names_the_real_price():
    """★ 「這裡填的不會生效」講完要說**實際會收多少** ——
    不然他知道自己錯了，但不知道學員被收了幾塊錢。"""
    m = messages('courses', _ctx({'material_fee': 145, 'has_material': True},
                                 material={'selling_price': 200}))
    assert any('200' in x for x in m), m


def test_the_whitelist_message_says_nobody_can_register():
    """★★ 這一條的後果是**全滅**（沒有人報得進來），
    而學員看到的訊息會讓他以為是自己的問題。那句話一定要寫進去。"""
    m = messages('courses', _ctx({'whitelist_enabled': True}, whitelist=0))[0]
    assert '沒有人報得進來' in m


# ══ 五、不要跨模組污染 ═══════════════════════════════

def test_course_rules_never_fire_on_an_event():
    """★★ `unmet('events', …)` 不可以吐出課程的規則。

    混在一起的話，活動表單上會冒出「缺勤上限」這種它根本沒有的設定 ——
    而那比不提醒更糟：他會去找一個不存在的欄位。
    """
    ctx = _ctx({'whitelist_enabled': True}, whitelist=0)
    assert not [d for d in unmet('events', ctx) if d.key in KEYS]


def test_event_rules_never_fire_on_a_course():
    ev_ctx = {'event': {'waitlist_enabled': True}, 'fields': [],
              'primary_groups': []}
    assert unmet('courses', ev_ctx) == []


def test_an_unknown_module_is_quiet_not_an_error():
    """★ 還沒盤點的模組要**安靜**，不是報錯 ——
    之後接禱讀本時，呼叫端可以先接上去再慢慢登記。"""
    assert unmet('devotional', _ctx()) == []
    assert messages('devotional', _ctx()) == []


# ══ 六、還沒存的課要安靜 ═══════════════════════════

@pytest.mark.parametrize('course', [
    {'absence_limit': 2},
    {'whitelist_enabled': True},
    {'absence_limit': 2, 'whitelist_enabled': True},
])
def test_an_unsaved_course_is_not_nagged_about_what_cannot_exist_yet(course):
    """★★★ 還沒存的課，堂次和白名單**一定**是空的 ——
    但那是「還沒排」，不是「設定錯了」。

    分不出來的話，他剛按下「新增學程」、才勾了缺勤上限，畫面就開始
    唸他還沒排堂次 —— 第一次用的人會以為自己做錯了什麼。

    ★ 這是測試抓到的：我原本在註解裡寫了這件事，但沒有實作。
    """
    assert messages('courses', _ctx(course, saved=False)) == []


def test_the_same_course_once_saved_does_get_the_warning():
    """★ 反面：存好之後就該講了，不然這個旗標等於把規則關掉。"""
    assert 'absence_limit_needs_sessions' in _fired(
        _ctx({'absence_limit': 2}, saved=True))
    assert 'whitelist_needs_names' in _fired(
        _ctx({'whitelist_enabled': True}, whitelist=0, saved=True))
