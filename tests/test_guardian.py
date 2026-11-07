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




# ── 後台 ──────────────────────────

def _admin():
    return (ROOT / 'templates' / 'admin' / 'event_form.html').read_text(encoding='utf-8')
















