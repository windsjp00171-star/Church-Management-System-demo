"""引導式那一頁：入口、端點、以及「不可以自己判斷」

`tests/test_guided.py` 守的是「答案 → 草稿」對不對。
這一份守的是**畫面和路由**：

1. 進得去、擋得住不該進的人
2. 頁面**不自己判斷任何事** —— 判斷只有 `routes/guided.py` 一份
3. 建立走既有的 `/admin/events/new`，不另開一條寫入路徑
4. 入口找得到（做了但沒人知道它在，跟壞掉在數據上一樣）
"""
import re
from pathlib import Path

import pytest

from routes.guided import FIELD_TEMPLATES, USES

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / 'templates' / 'admin' / 'event_guided.html').read_text(encoding='utf-8')
LIST = (ROOT / 'templates' / 'admin' / 'events.html').read_text(encoding='utf-8')


def _strip(text):
    """★ 我在註解裡寫的字會讓掃原始碼的斷言自己通過 —— 這個專案已經
    被自己的說明騙過五次。一律先剝掉註解再掃。"""
    text = re.sub(r'\{#.*?#\}', ' ', text, flags=re.S)
    text = re.sub(r'^[ \t]*/\*.*?\*/', ' ', text, flags=re.S | re.M)
    text = re.sub(r'^\s*//.*$', ' ', text, flags=re.M)
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)
    return text


CODE = _strip(PAGE)
LIST_CODE = _strip(LIST)

GUIDED = '/admin/events/guided'
DRAFT = '/admin/events/guided/draft'
HDR = {'X-CSRF-Token': 'test-csrf-token'}


# ══ 一、路由 ═══════════════════════════════════════















# ══ 二、頁面不可以自己判斷 ═════════════════════════

@pytest.mark.parametrize('use', USES, ids=lambda u: u['key'])
def test_the_page_does_not_decide_which_fields_a_use_needs(use):
    """★★★ 「要保險 → 身分證＋生日」這件事只能有一份實作。

    前端再判一份的話，改了 `USES` 畫面不會跟 —— 而兩邊都看起來正常。
    所以頁面裡不可以出現欄位樣板的名字。
    """
    for key in use['adds']:
        label = FIELD_TEMPLATES[key]['label']
        assert label not in CODE, (
            f'頁面自己寫了「{label}」—— 欄位由 routes/guided.py 決定')


def test_the_page_does_not_hardcode_the_use_labels():
    """用途的文字從伺服器來，不是抄一份在模板裡。"""
    for use in USES:
        assert use['label'] not in CODE, f'用途「{use["label"]}」被抄進頁面了'


def test_the_page_asks_the_server_for_the_draft():
    assert DRAFT in CODE


def test_the_page_does_not_write_its_own_guardian_condition():
    """★★ 「未滿18歲才問」的條件是伺服器存檔時掛的。
    這裡再寫一份的話，「畫面上的第幾題」就有兩個算法 ——
    差一號那題就指到別的問題上，而畫面完全看不出來。"""
    assert 'age_between' not in CODE
    assert 'trigger_sort_order' not in CODE


def test_the_page_does_not_invent_a_write_path():
    """★★★ 建立一定要走既有的 /admin/events/new。

    自己開一條寫入路徑的話，必填檢查、身分證檢查碼、監護人要有生日、
    名額結算……那些伺服器端的驗證會少掉一份，
    而引導式建出來的活動看起來完全正常。
    """
    assert '/admin/events/new' in CODE
    posts = re.findall(r"fetch\(\s*'([^']+)'", CODE)
    assert set(posts) <= {DRAFT, '/admin/events/new'}, \
        f'頁面打了預期外的端點：{posts}'


def test_it_lands_on_the_edit_page_afterwards():
    """★ 「之後可以回來改」的那個地方就是編輯頁 ——
    丟回列表的話他還要自己找，而找不到＝改不到。"""
    assert re.search(r"location\.href\s*=\s*`?/admin/events/\$\{[^}]+\}/edit", CODE)


# ══ 三、兩條規矩要真的在畫面上 ═════════════════════

def test_it_says_everything_can_still_be_changed():
    """★★ 使用者定的：「只是讓他們的有地方可以回來改」。

    不講的話每一題都變成不可逆的決定，他會在小事上卡住 ——
    而卡住的人不是慢慢想，是整個退出去。
    """
    assert CODE.count('改得到') >= 2, '「之後改得到」只講了一次或沒講'


def test_every_pending_choice_states_its_consequence():
    """★★★ 只寫「待定」兩個字的話，那件事會靜靜地不發生，
    而後台每一格看起來都正常。"""
    for chunk in re.findall(r'>\s*待定<small>([^<]*)</small>', CODE):
        assert chunk.strip(), '有一個「待定」沒有寫後果'
    assert len(re.findall(r'待定<small>', CODE)) >= 2


def test_there_is_a_way_out_on_every_screen():
    """★ 沒有出口的引導式比空白表單更難用 ——
    需求不在清單上的人會被困住。"""
    assert '我自己填表單就好' in CODE


def test_the_custom_question_escape_exists():
    """★ 用途清單再怎麼補都會有漏的（「您是從哪裡得知活動消息」）。
    沒有這條路的話，那種活動一遇到就得整個退出去，而退出去的人不會再回來。"""
    assert 'A.custom.push' in CODE


# ══ 四、入口 ═══════════════════════════════════════

def test_the_entry_point_is_on_the_events_page():
    """★★ 做了但沒人知道它在 —— 這個專案最貴的一種失敗，
    而它跟「壞了」在數據上長得一模一樣。"""
    assert 'href="/admin/events/guided"' in LIST_CODE


def _header():
    """★ 先切出 page-header 那一段再掃。

    整份檔案 `index()` 的話會抓到**導覽腳本**裡的那兩個網址（在檔案最上面）
    —— 對一個完全正確的版面報錯。這個專案已經踩過一模一樣的一次
    （`test_it_sits_next_to_payment_not_attendance`）。
    """
    start = LIST_CODE.index('<div class="page-header">')
    return LIST_CODE[start:LIST_CODE.index('{% if events %}', start)]


def test_the_guided_entry_comes_first_and_is_the_primary_one():
    """★★ 第一次開活動的人不知道空白表單怎麼填。
    把引導式放第二順位的話，需要它的人正好是最不會去找它的人。"""
    head = _header()
    g = head.index('/admin/events/guided')
    n = head.index('/admin/events/new')
    assert g < n, '引導式排在「直接填表單」後面'
    assert 'btn-primary' in head[g:n], '引導式不是主要的那一顆'
    assert 'btn-primary' not in head[n:], '兩顆都是主要的＝沒有主次'


def test_the_plain_form_is_still_reachable():
    """★ 熟手（和已經知道自己要什麼的人）不該被逼著走一遍。"""
    assert 'href="/admin/events/new"' in LIST_CODE


# ══ 五、兩半真的接得起來 ═══════════════════════════



