"""讀經頁底下的三個出口：**下一格、速讀總覽表、回首頁**

使用者：「幫我在這個頁面加上速讀總覽表的入口 回首頁跟下一篇不要做連結
**做卡片比較好**」。

原本那兩個出口是「接下來：民 9-12 →　回首頁」兩行小字連結，而且是
**打勾之後才由 JS 拼出來的** —— 讀完這一格之後唯一的路，在手機上又小又擠。

## ★★ 速讀總覽表那一張**不可以綁在「有沒有下一格」上**

365 格全部打完之後 `nxt` 是 `None`，而**那個人正是最需要那張表的人**
（讀完才去領證書）。首頁踩過一模一樣的坑：那張卡原本綁 `reading.next`，
讀完的人整張卡連同速讀表入口一起消失 —— 而**沒有任何地方會紅**，
首頁看起來只是少了一張卡（見 `CLAUDE.md`）。

## ★★ 而 `hidden` 在這裡差點又是一次「有寫但沒用」

「接下來」那張沒有下一格時掛 `hidden`。但 `.rd-navcard` 有
`display:flex` —— **它贏過 `hidden` 預設的 `display:none`**，
於是那張空的「接下來：」照樣畫出來。原始碼上完全看不出來
（`hidden` 明明寫著），是**開瀏覽器 render 才量到的**。
所以這一份最後那條問的是瀏覽器算出來的可見度，不是掃原始碼。
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / 'templates' / 'bible_reading_day.html').read_text(encoding='utf-8')
JS = (ROOT / 'static' / 'js' / 'bible-reading-day.js').read_text(encoding='utf-8')


def _code(src):
    """去掉 `//` 註解。

    ★★ 寫這一份的時候**當場又踩了一次**：`assert 'innerHTML' not in body`
      打中的是我自己那句註解 `// ★ 不用 innerHTML`，對一個完全正確的
      實作報錯。`CLAUDE.md` 記過「規則要變成程式碼，不然下一次還是會忘」——
      所以掃 JS 的斷言一律先過這一支。
    """
    import re as _re
    return _re.sub(r'(?m)//.*$', '', src)

SHEET = 'href="/reading/sheet"'
HOME = 'href="/"'


def _nav():
    """只切出 `.rd-nav` 那一塊。

    ★ 斷言要對著**該掃的那一段**，不要對整份檔案 —— 這份檔案上面還有
      一條 `/reading`（全部進度）和一堆樣式，整份掃會抓到別的東西。
      （這個專案記過的第二種假守衛。）
    """
    i = PAGE.index('<div class="rd-nav">')
    return PAGE[i:PAGE.index('</div>', PAGE.rindex('rd-navrow'))]


def test_there_is_a_nav_block_to_guard():
    """★ 前提：切不出東西的話底下每一條都會變成永遠綠的。"""
    assert len(_nav()) > 300


# ══ 一、★★ 主線：速讀總覽表的入口在這一頁 ═══════════════

def test_the_sheet_has_an_entry_on_this_page():
    """★ 比對用**完整的 href**：`'/reading/sheet' in src` 會被
    `/reading/sheet-gone` 滿足 —— 連結壞了測試照樣綠
    （這個專案記過的第三種假守衛：子字串）。"""
    assert SHEET in _nav()


def test_the_sheet_entry_is_not_tied_to_having_a_next_cell():
    """★★ 整份的重點。365 格讀完的人 `nxt` 是 `None` ——
    把速讀表塞進 `{% if nxt %}` 裡的話，**最需要那張表的人看不到它**，
    而畫面上只是少一張卡，沒有任何地方會紅。
    """
    nav = _nav()
    for m in re.finditer(r'\{%\s*if\s+nxt\s*%\}', nav):
        end = nav.find('{% endif %}', m.end())
        inside = nav[m.end():end if end != -1 else len(nav)]
        assert SHEET not in inside, (
            '速讀總覽表被關在「有下一格」的條件裡 —— 讀完 365 格的人就看不到了')


def test_going_home_does_not_depend_on_it_either():
    """★ 同一個理由：回首頁是**任何狀態**都要有的出口。"""
    nav = _nav()
    for m in re.finditer(r'\{%\s*if\s+nxt\s*%\}', nav):
        end = nav.find('{% endif %}', m.end())
        inside = nav[m.end():end if end != -1 else len(nav)]
        assert HOME not in inside


# ══ 二、是卡片，不是連結（使用者定的） ═══════════════════

@pytest.mark.parametrize('href,name', [(SHEET, '速讀總覽表'), (HOME, '回首頁')])
def test_each_exit_is_a_card(href, name):
    """★ 使用者：「回首頁跟下一篇不要做連結 做卡片比較好」。

    卡片走全站共用的 `.card-sm` —— 自己刻一個的話，
    以後改全站卡片樣式這一頁不會跟，而畫面上看不出來。
    """
    nav = _nav()
    i = nav.index(href)
    tag = nav[nav.rindex('<a', 0, i):i]
    assert 'card-sm' in tag, f'{name} 還是一條裸連結：{tag.strip()[:80]}'
    assert 'rd-navcard' in tag


def test_the_next_cell_is_a_card_too():
    nav = _nav()
    i = nav.index('id="rd-next"')
    tag = nav[nav.rindex('<a', 0, i):nav.index('>', i)]
    assert 'card-sm' in tag and 'rd-navcard' in tag


def test_the_javascript_no_longer_builds_its_own_link():
    """★★ 版面只准有一份。JS 原本自己拼
    `'接下來：<a href="/reading/' + …'` —— 留著的話改了卡片樣式
    這一段不會跟，而**兩邊各自看都正常**。
    """
    assert '<a href="/reading/' not in JS, 'JS 還在自己拼連結'
    assert '<a href="/"' not in JS
    #  改成更新那張卡
    assert "getElementById('rd-next')" in JS
    assert "getElementById('rd-next-label')" in JS


def test_the_label_is_set_as_text_not_html():
    """★ 標題從伺服器來，用 `textContent` —— `innerHTML` 要自己記得跳脫，
    而忘記跳脫在畫面上完全看不出來。"""
    #  ★ 切**更新那張卡的那一段**，不是從變數宣告往下數幾個字 ——
    #    第一版切 1200 字，而實際使用在更下面，於是對一個完全正確的
    #    實作報錯。切片要對著該掃的那一塊。
    code = _code(JS)
    i = code.index('if (nextCard && nextLabel)')
    body = code[i:code.index('} catch (e)', i)]
    assert 'nextLabel.textContent' in body
    assert 'innerHTML' not in body, '這一段又在拼 HTML 了'


# ══ 三、沒有下一格時不可以留一張空卡 ═════════════════════

def test_the_next_card_carries_a_real_destination_even_when_hidden():
    """★ 不可以寫 `href="#"` —— JS 沒載齊那一次按下去會停在原地，
    而畫面上完全正常（首頁那張小舟磚踩過同一條）。"""
    nav = _nav()
    i = nav.index('id="rd-next"')
    tag = nav[nav.rindex('<a', 0, i):nav.index('>', i)]
    assert 'href="#"' not in tag
    assert '/reading' in tag


def test_hidden_actually_hides_it():
    """★★ `.rd-navcard` 的 `display:flex` **會贏過** `hidden` 預設的
    `display:none`。少了這條規則，365 格讀完的人會看到一張
    標題是空的「接下來：」卡 —— 而原始碼上 `hidden` 明明寫著。
    """
    assert re.search(r'\.rd-navcard\[hidden\]\s*\{[^}]*display:\s*none',
                     PAGE), 'hidden 會被 display:flex 蓋掉'
