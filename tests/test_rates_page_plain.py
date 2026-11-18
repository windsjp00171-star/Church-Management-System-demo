"""出席率規則頁要一般同工看得懂（使用者：「對一般人來說太過複雜了」，2026-11-18）

只想看誰常來的人先被指到「出席統計」；規則頁改成四個白話問題（單選＋例子），
日期預設這一季、聚會預設全選、名稱可不填。請假／遲到／中途加入仍然**沒有預設答案**（教會自己選）。
"""
import re


def test_page_is_plain_questions_without_preset_answers(client_as):
    html = client_as(is_admin=True).get('/admin/roll-call/rates').get_data(as_text=True)
    assert 'href="/roll-call/report"' in html                        # 簡單的那一頁先講
    for name in ('r-leave', 'r-late', 'r-window'):
        radios = re.findall(rf'<input type="radio" name="{name}"[^>]*>', html)
        assert len(radios) >= 2 and not any('checked' in r for r in radios), name   # 不替教會選
    assert '存好並計算' in html and '<select id="r-leave"' not in html


def test_blank_name_is_filled_in_and_answers_still_required():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / 'templates' / 'roll_call' / 'rates.html').read_text(encoding='utf-8')
    assert "v('r-name').trim() || `${v('r-start')}～${v('r-end')} 出席率`" in js
    from roll_call_logic import validate_rule
    import pytest
    with pytest.raises(ValueError, match='請假'):
        validate_rule({'leave_mode': None, 'late_mode': 'present', 'respect_membership_window': True,
                       'type_ids': ['t'], 'range_start': '2026-10-01', 'range_end': '2026-12-31'})
