"""手冊與後台說明有跟著功能走（做了但沒人知道它在，跟壞掉在數據上長得一樣）

`routes/field_types.FIELD_TYPES` 是欄位型別的單一來源。型別加到十一種、手冊停在七種的話，
漏掉的那四種（分級收費、出生日期、身分證字號、監護人）正是最需要寫進去的四種。
（成熟版這份檔案還守很多別的手冊規則，那些對應的功能這個 repo 還沒有，所以只放這一條。）
"""
import re

import pytest

from routes.field_types import FIELD_TYPES


def _strip(s):
    s = re.sub(r'\{#.*?#\}', ' ', s, flags=re.S)
    return re.sub(r'<!--.*?-->', ' ', s, flags=re.S)


MANUAL = _strip(open('templates/manual.html', encoding='utf-8').read())
FORM = _strip(open('templates/admin/event_form.html', encoding='utf-8').read())


@pytest.mark.parametrize('label', sorted(FIELD_TYPES.values()))
def test_the_manual_lists_every_field_type(label):
    # 手冊的叫法：下拉選單→下拉、多選→複選；其餘照完整名稱
    needle = {'下拉選單': '下拉', '多選': '複選'}.get(label, label)
    assert needle in MANUAL, f'手冊的活動管理沒有提到「{label}」'


@pytest.mark.parametrize('label', ['分級收費', '出生日期', '身分證字號', '監護人'])
def test_the_admin_form_says_what_the_new_types_are(label):
    assert label in FORM
