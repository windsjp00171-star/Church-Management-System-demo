"""後台首頁：依「要做的事」分區，每張卡各自判斷權限

原本「會員管理／系統設定」兩區整塊包在 `is_super_admin or 副標籤成員` 裡 ——
**一般管理員**（`is_admin`）明明有聚會點名、全職同工差勤的權限（`DEFAULT_ADMIN_MODULES`），
後台首頁卻看不到那兩張卡，只能自己打網址。現在每張卡只看自己的 `can_see()`。
（完整 app 不能和其他測試同一個行程，所以把 content 區塊切出來真的 render。）
"""
import re
from pathlib import Path

from jinja2 import Environment

ROOT = Path(__file__).resolve().parent.parent
TPL = (ROOT / 'templates' / 'admin' / 'index.html').read_text(encoding='utf-8')
SECTIONS = ['活動與報名', '牧養與小組', '門訓與學程', '內容與公告', '人員與同工', '首頁與系統']


def _render(sess, finance=False):
    from routes.permissions import module_for_path, visible_index_modules
    seg = TPL[TPL.index('{% block content %}') + len('{% block content %}'):TPL.rindex('{% endblock %}')]
    visible = visible_index_modules(sess)

    def can_see(path):
        mod = module_for_path(path)
        return mod is None or mod in visible
    env = Environment()
    env.globals.update(can_see=can_see, module_on=lambda *_: True, session=sess, card_names={},
                       url_for=lambda ep, **_: '/' + ep, config={'DEMO_MODE': False}, church_name='教會',
                       has_finance_access=finance)
    return env.from_string(seg).render()


def _names(html):
    return re.findall(r'admin-card-name"[^>]*>(.*?)</div>', html)


def test_plain_admin_sees_the_cards_they_are_allowed_into(fake_db):
    names = _names(_render({'is_admin': True}))
    assert '聚會點名' in names and '全職同工差勤' in names
    assert '選用功能模組' not in names and '權限矩陣' not in names and '部署精靈' not in names


def test_super_admin_sees_every_section_in_order(fake_db):
    html = _render({'is_admin': True, 'is_super_admin': True})
    pos = [html.index(f'section-label">{s}<') for s in SECTIONS]
    assert pos == sorted(pos)
    names = _names(html)
    assert len(names) == len(set(names)), '同一張卡出現兩次'
    assert '資料匯出' not in names and '資料匯入' not in names     # 併進「資料備份與搬家」
    assert '小組總覽' not in names and '門訓出席（依小組）' in names


def test_finance_cards_only_with_finance_access(fake_db):
    assert '金流設定' not in _names(_render({'is_super_admin': True}))
    assert '金流設定' in _names(_render({'is_super_admin': True}, finance=True))


def test_a_section_with_no_visible_card_hides_its_heading(fake_db):
    assert '.admin-section:not(:has(.admin-card)) { display:none; }' in TPL
