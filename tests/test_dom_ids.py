"""getElementById 打錯字：全站防護

這一條守的是我們一路上抓到最多次的那一類 bug ——
**不會報錯、不會當掉、看起來就是沒反應。**

    document.getElementById('stat-checkd')   // 少一個 e

回傳 `null`。後面 `.textContent = 25` 才丟 TypeError，而且是在
**使用者按下那顆按鈕的當下**才丟，不是載入時。於是：

  - 部署不會失敗
  - 頁面打開一切正常
  - 測試全綠（我們的路由測試只看 HTTP 狀態）
  - 要等有人真的去點，而他只會覺得「怪怪的，數字沒動」，不會回報

改版最容易踩到：某人把 `id="stat-checked"` 改名或刪掉，JS 那邊沒跟著改。
HTML 和 JS 之間沒有任何東西在對帳，這條就是那個對帳。

★ 一定要展開 {% include %}：verse.html 用的 #verse-card 其實是宣告在
  _verse_card.html 裡面的。第一版沒展開就誤報了這一筆。
"""
import glob
import os
import re

import pytest

TEMPLATES = 'templates'

_GET_BY_ID = re.compile(r'''getElementById\(\s*["']([A-Za-z0-9_:.-]+)["']\s*\)''')
_ID_ATTR = re.compile(r'''\bid\s*=\s*["']([A-Za-z0-9_:.-]+)["']''')
_INCLUDE = re.compile(r'''\{%-?\s*(?:include|extends)\s+["']([^"']+)["']''')


# ★ 掃描前一定要先剝註解。
#   這個坑我們踩過四次了：測試在掃「程式碼裡有沒有 X」，
#   而我自己在旁邊寫「這裡刻意用 X」的註解，於是測試抓到自己的說明文字。
#
# ★★ 而且 JS 註解只能在 <script> 裡面剝。
#   整份檔案一起剝的話，HTML 屬性裡的 accept="image/*" 會被當成區塊註解
#   的開頭，一路吃到下一個 */（例如某段 JSDoc 的結尾）—— 實測一次吃掉
#   29KB，整份模板的 id 宣告全部消失，於是這條測試把每一個 id 都報成
#   「找不到」。假警報比漏報更糟：叫過一次沒事之後就沒有人再看了。
#
# 行末的 // 不剝（fetch('https://…') 會被切掉半截），只剝整行的註解。
_JINJA_COMMENT = re.compile(r'\{#[\s\S]*?#\}')
_SCRIPT_BLOCK = re.compile(r'(<script\b[^>]*>)([\s\S]*?)(</script>)', re.I)
_BLOCK_COMMENT = re.compile(r'/\*[\s\S]*?\*/')
_LINE_COMMENT = re.compile(r'^[ \t]*//.*$', re.MULTILINE)


def _strip_js_comments(js):
    return _LINE_COMMENT.sub('', _BLOCK_COMMENT.sub('', js))


def _strip_comments(src):
    src = _JINJA_COMMENT.sub('', src)
    src = _SCRIPT_BLOCK.sub(
        lambda m: m.group(1) + _strip_js_comments(m.group(2)) + m.group(3), src)
    # 獨立的 .js 檔沒有 <script> 標籤，整份都是 JS
    if '<script' not in src and '</script>' not in src:
        src = _strip_js_comments(src)
    return src


def _read(path):
    with open(path, encoding='utf-8') as f:
        return _strip_comments(f.read())


def _expanded(path, seen=None):
    """把 {% include %} / {% extends %} 的內容一起攤平。

    只往下一層層展開，遇到迴圈就停（seen）。動態檔名（變數）跳過 ——
    正規表示式只吃得到字面字串，這是刻意的：猜不到的就不猜。
    """
    seen = seen if seen is not None else set()
    if path in seen or not os.path.exists(path):
        return ''
    seen.add(path)
    src = _read(path)
    for rel in _INCLUDE.findall(src):
        src += '\n' + _expanded(os.path.join(TEMPLATES, rel), seen)
    return src


def _templates_using_get_by_id():
    out = []
    for path in sorted(glob.glob(f'{TEMPLATES}/**/*.html', recursive=True)):
        if _GET_BY_ID.search(_read(path)):
            out.append(path)
    return out


@pytest.mark.parametrize('path', _templates_using_get_by_id())
def test_every_get_element_by_id_has_a_matching_id(path):
    src = _expanded(path)
    wanted = set(_GET_BY_ID.findall(src))
    declared = set(_ID_ATTR.findall(src))

    # JS 自己組字串塞進 DOM 的（innerHTML = `<div id="foo">`）也算宣告過
    declared |= set(re.findall(r'''id\s*=\s*\\?["']([A-Za-z0-9_:.-]+)''', src))

    missing = sorted(wanted - declared)
    assert not missing, (
        f'{path} 的 JS 找了這些 id，但整份模板（含 include）裡沒有人宣告：{missing}\n'
        '→ getElementById 會回 null，不會報錯，使用者只會看到「按了沒反應」。'
    )


def test_the_check_actually_finds_something():
    """★ 防呆：如果哪天正規表示式壞掉、掃到 0 個檔案，
    上面那條會因為 parametrize 空清單而「全綠」—— 那是假的綠。"""
    assert len(_templates_using_get_by_id()) >= 10


