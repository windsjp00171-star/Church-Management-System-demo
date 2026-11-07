"""名冊與 Excel 匯出：生日印民國（存的是西元）

生日欄位存西元（算年齡、排序都要），但名冊和保險公司看的是民國 —— 同一個人名冊印 `1999-03-05`、
匯出印 `088/03/05` 的話，兩邊各自看都正常，對起來才發現不一樣。兩邊走同一支 `routes.roc.to_roc`。
（成熟版靠整套 rig 渲染整頁；這個 repo 的完整 app 不能和其他測試同一個行程，所以：
 名冊那一格直接把模板裡那一段切出來真的 render，匯出用 AST 切出函式檢查。）
"""
import ast
import re
from pathlib import Path

import pytest
from jinja2 import Environment

ROOT = Path(__file__).resolve().parent.parent
TPL = (ROOT / 'templates' / 'admin' / 'registrations.html').read_text(encoding='utf-8')


def _cell_template():
    seg = TPL[TPL.index('<!-- 自訂欄位答案 -->'):TPL.index('<!-- 報名時間 -->')]
    from app_filters import roc_short
    env = Environment()
    env.filters['roc_short'] = roc_short
    return env.from_string(seg)


@pytest.fixture(scope='module')
def render():
    import sys
    import types
    # 名冊用的 roc_short 定義在 create_app() 裡；這裡用同一支 routes.roc.to_roc 組一個等價的
    from routes.roc import to_roc
    mod = types.ModuleType('app_filters')
    mod.roc_short = lambda iso: to_roc(iso) or (iso or '')
    sys.modules['app_filters'] = mod
    tpl = _cell_template()
    return lambda fields, answers: re.sub(r'\s+', ' ', tpl.render(fields=fields, my_answers=answers)).strip()


def test_a_birthday_prints_in_roc_years(render):
    out = render([{'id': 'b', 'field_type': 'birthday'}], {'b': '1999-03-05'})
    assert '088/03/05' in out and '1999' not in out


def test_other_fields_are_left_alone(render):
    out = render([{'id': 'n', 'field_type': 'text'}], {'n': '1999-03-05'})
    assert '1999-03-05' in out, '只有生日型別才轉民國 —— 一般文字欄位剛好填了日期不能被改'


def test_an_unparseable_birthday_is_kept_as_is(render):
    assert '亂填的' in render([{'id': 'b', 'field_type': 'birthday'}], {'b': '亂填的'})


def test_a_date_before_the_republic_is_not_turned_into_a_negative_year(render):
    """★ 民國前的日期回空字串比印一個負數安全：負數會被當成正常年份印到保險名冊上。"""
    out = render([{'id': 'b', 'field_type': 'birthday'}], {'b': '1900-01-01'})
    assert '1900-01-01' in out and not re.search(r'-\d{1,3}/', out)       # 原樣印回去，沒有變成「-11/01/01」


def test_a_missing_birthday_still_shows_a_dash(render):
    assert '—' in render([{'id': 'b', 'field_type': 'birthday'}], {})


def test_the_app_registers_the_filter_the_roster_uses():
    src = (ROOT / 'app.py').read_text(encoding='utf-8')
    assert "filters['roc_short']" in src
    assert 'to_roc(' in src.split('def _roc_short')[1].split('app.jinja_env.filters')[0]


def test_the_export_converts_birthdays_with_the_same_function():
    src = (ROOT / 'routes' / 'admin.py').read_text(encoding='utf-8')
    lines = src.split('\n')
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == 'export_registrations')
    body = '\n'.join(lines[fn.lineno - 1:fn.end_lineno])
    assert "field.get('field_type') == 'birthday'" in body
    assert 'from routes.roc import to_roc' in body and 'to_roc(value)' in body


def test_the_edit_modal_resets_before_it_fills():
    """★ 這個彈窗是重複使用的，prefillFields 只填「有答案的」欄位（沒有的跳過，不是清空）。
    不先 resetFields 的話，換一個人打開會看到上一位的生日和選項 —— 整格看起來正常，
    只是有一半是別人的資料，同工按儲存就存成這個人的。（先剝掉註解再比：說明文字裡也寫了這兩個名字。）"""
    fn = TPL[TPL.index('function openEditModal('):]
    fn = fn[:fn.index('\nfunction ')]
    code = re.sub(r'/\*[\s\S]*?\*/', '', fn)
    code = re.sub(r'(?m)//.*$', '', code)
    assert 'resetFields(' in code and 'prefillFields(' in code
    assert code.index('resetFields(') < code.index('prefillFields(')
