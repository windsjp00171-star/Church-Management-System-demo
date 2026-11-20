"""小組聚會日兩種寫法都看得懂（中文「五／週五／星期五」與後台舊存的數字 "5"）。

以前只認中文：後台新增的週五小組（存成 "5"），組長回報的日期被算成上個主日，畫面顯示「每週5聚會」。
"""
import datetime
import sys
import types

import pytest

from routes.gather_day import day_char, label, weekday


@pytest.mark.parametrize('value, ch', [
    ('五', '五'), ('週五', '五'), ('星期五', '五'), ('5', '五'), (5, '五'),
    ('0', '日'), ('日', '日'), ('週日', '日'), ('星期天', '日'), ('三', '三'),
    ('', ''), (None, ''), ('隨時', ''),
])
def test_day_char(value, ch):
    assert day_char(value) == ch


def test_weekday_and_label():
    assert weekday('五') == weekday('5') == 4
    assert weekday('日') == weekday('0') == 6
    assert weekday('') is None
    assert label('5') == label('週五') == '週五'      # 不再有「週週五」「每週5」
    assert label('') == ''


@pytest.mark.parametrize('stored', ['五', '週五', '5'])
def test_cell_report_meeting_date_understands_both_formats(monkeypatch, stored):
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=None))
    import routes.cell_report as cr
    friday = datetime.date(2026, 11, 20)
    assert cr._get_last_meeting_date_for_group({'weekly_gather_day': stored}, friday) == friday


def test_admin_stores_chinese_char():
    src = open('routes/admin.py', encoding='utf-8').read()
    assert "day_char(data.get('weekly_gather_day'))" in src
