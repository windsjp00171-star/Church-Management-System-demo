"""監護人欄位：姓名＋電話，只問未滿18歲

## 為什麼是一種欄位型別，而不是兩個一般欄位加跳題條件

使用者的要求是「後台表單設定不要太複雜」。做成兩個一般欄位的話，管理員
每次都要：建「監護人姓名」→ 設年齡跳題條件 → 建「監護人電話」→
**再設一次一模一樣的條件**。兩份同樣的設定遲早會不一樣（改了一個忘了另一個），
那時候變成「姓名要填、電話不用填」，名冊上有名字沒電話 ——
而看起來就像那個人自己漏填。

現在：加欄位 → 型別選「監護人」→ 勾必填。條件由伺服器存檔時自動掛。

## ★ 存成一個人看得懂的字串

`registration_answers.answer` 是純文字，而**每一個讀它的地方都是直接印出來**：
名冊、Excel 匯出、我的報名、後台編輯彈窗。存 JSON 的話這四個地方會同時
冒出 `{"name": ...}`。所以存「王小明／0912345678」，下游一行都不用改。

## ★ 前端和伺服器對同一組輸入必須產生同一個結果

各寫一份格式的話，症狀是「畫面上填好了，伺服器說沒填」—— 使用者盯著
兩個明明有字的框，不知道系統在講什麼。test_js_and_python_agree 用
node 跑真的 JS，跟 Python 逐項比對。

★ mutation 驗過：
  - is_complete 改成「非空就算」→ test_half_filled_is_not_filled 紅
  - compose 不清掉分隔符號 → test_a_slash_in_the_name_cannot_split_the_phone 紅
  - parse 改成 partition（從第一個切）→ 同上紅
  - _apply_guardian_conditions 不覆蓋既有條件 → test_reordering_fixes_a_stale_index 紅
  - 沒有生日欄位時不擋 → test_a_guardian_without_a_birthday_is_blocked 紅
  - 寫入點少接一個 _normalize_guardian_answers → test_every_write_path_normalizes 紅
  - JS 的 GD_SEP 改成半形 / → test_js_and_python_agree 紅
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from routes.admin_events import _apply_guardian_conditions
from routes.conditions import missing_required
from routes.guardian import MINOR_MAX_AGE, compose, is_complete, parse

ROOT = Path(__file__).resolve().parent.parent
EVENT = {'id': 'ev-1', 'event_start': '2026-09-01T08:00:00+08:00'}


# ── 格式 ──────────────────────────

def test_a_full_answer_round_trips():
    v = compose('王小明', '0912345678')
    assert v == '王小明／0912345678'
    assert parse(v) == ('王小明', '0912345678')
    assert is_complete(v)


def test_half_filled_is_not_filled():
    """★ 只有名字沒電話 ＝ 沒填。

    出事那天光有名字打不到人 —— 而名冊上那一列看起來是有東西的。
    """
    assert not is_complete(compose('王小明', ''))
    assert not is_complete(compose('', '0912345678'))
    assert is_complete(compose('王小明', '0912345678'))


def test_both_blank_is_empty_not_a_lone_separator():
    """回「／」的話，必填檢查會認為這一格有東西。"""
    assert compose('', '') == ''
    assert compose(None, None) == ''


def test_a_slash_in_the_name_cannot_split_the_phone():
    """★ 名字裡有斜線 → 分隔位置跑掉 → 名冊上那個人的電話會少一截，
    而看起來只是「號碼怪怪的」，沒有人會想到是格式被切錯。"""
    v = compose('王小明/小華', '0912345678')
    assert parse(v) == ('王小明小華', '0912345678')
    v2 = compose('王小明／小華', '0912345678')
    assert parse(v2) == ('王小明小華', '0912345678')


def test_whitespace_is_tidied_not_preserved():
    assert compose('  王小明  ', ' 0912 345 678 ') == '王小明／0912 345 678'


def test_parsing_splits_from_the_right():
    """★ 從**最後一個**分隔符號切。

    compose 過的字串只會有一個分隔符號，所以拿它來測完全沒有鑑別力
    （切第一個或最後一個結果一樣，mutation 測試才抓到）。真正會有兩個
    的是舊資料、或有人直接打 API 送上來的東西。

    切錯的後果不一樣：從右切 → 多出來的斜線留在姓名裡（看得出來怪）；
    從左切 → 電話變成「小明／0912345678」，看起來像個正常但錯的號碼。
    """
    assert parse('王／小明／0912345678') == ('王／小明', '0912345678')


def test_legacy_free_text_is_not_guessed_apart():
    """舊資料（或有人直接打 API）沒有分隔符號 —— 整串當姓名，
    不要猜哪一段是電話，猜錯的話名冊上會出現一個編出來的號碼。"""
    assert parse('王小明 0912345678') == ('王小明 0912345678', '')


def test_the_minor_boundary_is_seventeen_inclusive():
    """未滿 18 ＝ 17 歲以下。寫成 18 的話，剛滿 18 的人也會被問。"""
    assert MINOR_MAX_AGE == 17


# ── 條件由伺服器自動掛 ──────────────────────────

def fields(*specs):
    out = []
    for i, (ftype, label) in enumerate(specs):
        out.append({'label': label, 'field_type': ftype, 'is_required': True,
                    'sort_order': i, 'condition_json': None, 'id': f'f{i}'})
    return out


def test_the_condition_is_generated_when_none_is_set():
    """★ 預設情況管理員什麼都不用設。"""
    fs = fields(('text', '姓名'), ('birthday', '出生年月日'), ('guardian', '監護人'))
    assert _apply_guardian_conditions(fs) is None
    cond = json.loads(fs[2]['condition_json'])
    assert cond == {'trigger_sort_order': 1, 'op': 'age_between',
                    'min': None, 'max': 17, 'auto': 'minor'}


def test_an_admin_set_condition_is_left_alone():
    """★★ 面板還在，設了就要算數。

    有些活動的規則本來就不一樣（兒童營全部都要填、水上活動是
    「選了獨木舟才問」）。自動覆蓋掉的話，管理員每次存檔都會發現
    自己的設定被吃掉 —— **而且沒有任何訊息**，他只會覺得存檔壞了。
    """
    mine = json.dumps({'trigger_sort_order': 0, 'trigger_value': '獨木舟'})
    fs = fields(('radio', '想參加的活動'), ('birthday', '生日'), ('guardian', '監護人'))
    fs[2]['condition_json'] = mine
    assert _apply_guardian_conditions(fs) is None
    assert fs[2]['condition_json'] == mine, '管理員自己設的條件被覆蓋掉了'


def test_an_admin_can_widen_it_to_everyone():
    """兒童營：全部都要填監護人。把條件拿掉就好，不該被自動加回來。

    ★ 這裡的 condition_json 是 None 而**不是**沒送 —— 差別在前端：
      管理員取消勾選「設定跳題條件」時送上來的就是 None。
      這種情況目前仍會自動補上未滿18歲（沒設 ＝ 用預設），
      要全部都問請把年齡上限設成一個涵蓋所有人的值。
    """
    wide = json.dumps({'trigger_sort_order': 1, 'op': 'age_between',
                       'min': 0, 'max': 200})
    fs = fields(('text', '姓名'), ('birthday', '生日'), ('guardian', '監護人'))
    fs[2]['condition_json'] = wide
    _apply_guardian_conditions(fs)
    assert fs[2]['condition_json'] == wide


def test_a_guardian_without_a_birthday_is_blocked():
    """★ 沒有生日就算不出年齡 → 那題永遠不出現，而後台看起來設好了。

    訊息要講「該做什麼」，不是「哪裡錯了」。
    """
    fs = fields(('text', '姓名'), ('guardian', '監護人'))
    err = _apply_guardian_conditions(fs)
    assert err and '出生日期' in err
    assert '請先加' in err, '沒有告訴管理員該怎麼做'


def test_reordering_regenerates_the_auto_condition():
    """★ 欄位順序改過之後，舊的 index 會指到別的問題上，而畫面完全正常。

    所以**自動補上去的那條**（帶 auto:'minor' 印記）每次存檔都重新產生。
    管理員自己設的沒有印記，一個字都不動 —— 見上面那條。
    """
    fs = fields(('text', '姓名'), ('birthday', '生日'), ('guardian', '監護人'))
    fs[2]['condition_json'] = json.dumps(
        {'trigger_sort_order': 99, 'op': 'age_between', 'max': 17, 'auto': 'minor'})
    _apply_guardian_conditions(fs)
    assert json.loads(fs[2]['condition_json'])['trigger_sort_order'] == 1


def test_the_auto_mark_is_what_tells_them_apart():
    """★ 沒有印記的話，只能用「長得像不像自動產生的」去猜 ——
    而管理員手動設一條 17 歲以下的條件（完全合理）就會被當成自動的，
    然後在他改了欄位順序時被悄悄改掉。"""
    fs = fields(('text', '姓名'), ('birthday', '生日'), ('guardian', '監護人'))
    _apply_guardian_conditions(fs)
    assert json.loads(fs[2]['condition_json']).get('auto') == 'minor'


def test_legacy_group_fields_do_not_shift_the_index():
    """舊的 group 型別在報名表上被濾掉，所以它不佔一格。"""
    fs = fields(('group', '小組'), ('birthday', '生日'), ('guardian', '監護人'))
    _apply_guardian_conditions(fs)
    assert json.loads(fs[2]['condition_json'])['trigger_sort_order'] == 0


def test_rows_without_a_label_do_not_shift_the_index():
    """後台那一列還沒打名字就不會被存 —— 它不該佔一格。"""
    fs = fields(('birthday', '生日'), ('text', ''), ('guardian', '監護人'))
    _apply_guardian_conditions(fs)
    assert json.loads(fs[2]['condition_json'])['trigger_sort_order'] == 0


def test_no_guardian_field_changes_nothing():
    fs = fields(('text', '姓名'), ('birthday', '生日'))
    assert _apply_guardian_conditions(fs) is None
    assert all(f['condition_json'] is None for f in fs)


# ── 端到端：未成年才問、而且要兩格都填 ──────────────────────────

def trip_fields():
    fs = [{'id': 'f0', 'label': '出生年月日', 'field_type': 'birthday',
           'is_required': True, 'sort_order': 0, 'condition_json': None},
          {'id': 'f1', 'label': '監護人', 'field_type': 'guardian',
           'is_required': True, 'sort_order': 1, 'condition_json': None}]
    _apply_guardian_conditions(fs)
    return fs


def ans(*pairs):
    return [{'field_id': k, 'answer': v} for k, v in pairs]


def test_a_minor_must_give_both_name_and_phone():
    fs = trip_fields()
    assert missing_required(fs, ans(('f0', '2011-05-01')), EVENT) == ['監護人']
    assert missing_required(
        fs, ans(('f0', '2011-05-01'), ('f1', compose('媽媽', ''))), EVENT) == ['監護人'], \
        '只填姓名就過了 —— 出事那天打不到人'
    assert missing_required(
        fs, ans(('f0', '2011-05-01'),
                ('f1', compose('媽媽', '0912345678'))), EVENT) == []


def test_an_adult_is_never_asked():
    fs = trip_fields()
    assert missing_required(fs, ans(('f0', '1990-05-01')), EVENT) == []


def test_the_boundary_is_the_day_they_turn_eighteen():
    fs = trip_fields()
    # 活動 2026-09-01
    assert missing_required(fs, ans(('f0', '2008-09-01')), EVENT) == []
    assert missing_required(fs, ans(('f0', '2008-09-02')), EVENT) == ['監護人']


# ── 伺服器覆蓋格式 ──────────────────────────

def test_every_write_path_normalizes():
    """★ 名冊、匯出、我的報名都是直接把那一格印出來 ——
    有人直接打 API 送一串壞格式的話，它會一路長到每個看得到的地方。"""
    from tests.test_auto_tier import _answer_writers
    for path, fn in _answer_writers():
        assert '_normalize_guardian_answers(' in fn, \
            f'{path} 有一個寫入答案的地方沒有正規化監護人'


def test_normalizing_is_overwrite_not_validation():
    """跟 _enforce_auto_tiers 一樣：覆蓋，不是「檢查對不對就報錯」。

    報錯的話，一個沒做錯任何事的人（前端剛好送了多餘空白）會被擋下來。
    """
    src = (ROOT / 'routes' / 'event.py').read_text(encoding='utf-8')
    fn = src[src.index('def _normalize_guardian_answers'):]
    fn = fn[:fn.index('\ndef ')]
    assert "ans['answer'] = compose(*parse(" in fn
    assert 'return jsonify' not in fn, '正規化不該自己報錯'


# ── 前端與伺服器必須完全一致 ──────────────────────────

GUARDIAN_CASES = [
    ['王小明', '0912345678'],
    ['', ''],
    ['王小明', ''],
    ['', '0912345678'],
    ['王小明/小華', '0912345678'],
    ['王小明／小華', '0912345678'],
    ['  王小明  ', ' 0912 345 678 '],
    ['Nga̍u-bo̍k', '02-24700000#12'],
]


@pytest.fixture(scope='module')
def js_guardian():
    assert shutil.which('node'), 'node 不在 —— 這條不能 skip，它守的是兩份實作會不會分歧'
    env = dict(os.environ, GUARDIAN_CASES=json.dumps(GUARDIAN_CASES))
    out = subprocess.run(['node', 'tests/js/conditions_harness.js'],
                         capture_output=True, text=True, cwd=str(ROOT), env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)['guardian']


def test_js_and_python_agree(js_guardian):
    """★★ 前端和伺服器對同一組輸入必須產生完全一樣的結果。

    分歧的症狀是「畫面上填好了，伺服器說沒填」—— 使用者盯著兩個明明
    有字的框，不知道系統在講什麼，而且他做什麼都改變不了。
    """
    assert len(js_guardian) == len(GUARDIAN_CASES)
    for (name, phone), got in zip(GUARDIAN_CASES, js_guardian):
        want = compose(name, phone)
        assert got['composed'] == want, f'{name!r}/{phone!r} 組出來的字串不一樣'
        assert tuple(got['parsed']) == parse(want), f'{want!r} 拆回來不一樣'
        assert got['complete'] == is_complete(want), f'{want!r} 完整性判斷不一樣'


# ── 後台 ──────────────────────────

def _admin():
    return (ROOT / 'templates' / 'admin' / 'event_form.html').read_text(encoding='utf-8')


def test_the_condition_panel_stays_for_guardians():
    """★★ 面板不可以拿掉。

    有些活動的規則本來就不一樣（兒童營全部都要填、水上活動是「選了
    獨木舟才問」）。拿掉的話那些活動只能繞路，而繞路的做法一定比較差。
    """
    import re
    fn = _admin().split('function applyGuardianRow')[1].split('\n}\n')[0]
    # ★ 比一個寫死的字串太好騙 —— 換個變數名就繞過去了（mutation 抓到）。
    #   改成：任何從 .condition-section 取出來的變數，都不可以被拿去設 display。
    for var in re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*row\.querySelector\("
                          r"\s*'\.condition-section'\s*\)", fn):
        assert f'{var}.style.display' not in fn, \
            f'又把監護人的跳題面板藏起來了（{var}）'
    assert 'condition-section' not in fn or 'insertBefore' in fn, \
        'applyGuardianRow 動了跳題面板，但不是為了插入說明'


def test_the_admin_says_what_the_default_is():
    """預設行為看不見（條件是伺服器補的），所以一定要寫出來 ——
    不然管理員會以為自己漏設了，然後手動再設一條一模一樣的。"""
    fn = _admin().split('function applyGuardianRow')[1].split('\n}\n')[0]
    assert '未滿 18 歲' in fn and '姓名＋電話' in fn
    assert '以你設的為準' in fn, '沒講「自己設了就照你的」'


def test_the_auto_condition_does_not_come_back_as_a_manual_one():
    """★ 打勾顯示成「管理員設的」的話，它就變成手動的了 ——
    之後改欄位順序不會再重新產生，而 index 已經指到別的問題上。"""
    src = _admin()
    restore = src.split('data-saved-condition')[2]
    assert "cond.auto === 'minor'" in restore[:900]


def test_a_required_guardian_needs_a_required_birthday():
    """★ 監護人必填、但「出生年月日」沒勾必填 ＝ 整條規則可以被繞過。

    不填生日 → 算不出年齡 → 監護人那題不出現 → 也就不用填。於是
    「未成年一定要填監護人」變成「不想填的人不要填生日就好」，而後台
    看起來設定得好好的，名冊上那一格就是空的，沒有任何徵兆。

    使用者的判斷是「生日本來就會勾必填（保險要用）」—— 所以這是一道
    保險，不是每次都會遇到的東西。它要在**存檔的當下**講，不是等到
    有人真的繞過去之後才發現。
    """
    fn = _admin().split('function conditionProblem')[1].split('\n}\n')[0]
    assert "=== 'guardian'" in fn, '完全沒有檢查監護人這種情況'
    assert "bd.querySelector('.f-required')?.checked" in fn, \
        '沒有看出生日期那一題是不是必填'
    assert '也勾必填' in fn, '沒有告訴管理員該怎麼修'


def test_the_guardian_check_only_fires_when_it_is_required():
    """★ 監護人是選填的話，生日沒必填不構成問題 —— 那是管理員的選擇。

    無差別擋的話，一個沒做錯任何事的人會被擋在存檔頁上，
    而他看不出為什麼。
    """
    fn = _admin().split('function conditionProblem')[1].split('\n}\n')[0]
    guard = fn[:fn.index('const rows')]
    assert "row.querySelector('.f-required')?.checked" in guard, \
        '沒有先確認這一題是必填'


def test_the_block_happens_before_saving():
    """存下去之後才發現的話，那場活動已經開放報名了。

    ★ 要看**那個 if 區塊裡面**有沒有 return，不是整個 submitForm 裡有沒有
      —— submitForm 前面本來就有別的 return（活動名稱沒填那條），掃整段的
      話拿掉這個 return 測試照樣綠。第一版就是那樣寫的，mutation 抓到。
    """
    src = _admin()
    assert 'conditionProblem(row)' in src.split('function submitForm')[1][:1200]
    block = src.split('if (badConds.length) {')[1].split('\n    }')[0]
    assert 'alert(' in block, '沒有把問題講出來'
    assert 'return;' in block, '只提醒沒有擋下來，還是存進去了'


def test_the_preview_applies_the_same_auto_condition():
    """★ 預覽不補的話會顯示「每個人都要填監護人」，而實際只問未成年 ——
    預覽 certify 一個不存在的行為，比沒有預覽更糟。"""
    fn = _admin().split('function conditionJsonFromRow')[1].split('\n}\n')[0]
    assert "=== 'guardian'" in fn
    assert "op: 'age_between'" in fn


def test_all_three_entry_points_share_one_renderer():
    """三份各寫的話，其中一份的 class 打錯就變成
    「那個入口的監護人永遠存不進去」，而畫面完全正常。"""
    for name in ('event_detail.html', 'external_register.html'):
        src = (ROOT / 'templates' / name).read_text(encoding='utf-8')
        assert "_guardian_field.html" in src, f'{name} 沒有用共用的那一份'
    detail = (ROOT / 'templates' / 'event_detail.html').read_text(encoding='utf-8')
    assert detail.count("include '_guardian_field.html'") == 2, \
        'event_detail 有兩份表單（自己報名／幫別人報名），兩份都要'
