"""行事曆日期詳情不能讓行程標題／說明變成可執行的 HTML

## 為什麼要守

行事曆的日期詳情用 innerHTML 組出來。個人行程的標題、說明是會友自己打的，
教會行事是管理員打的，活動標題來自活動報名。只要其中一個寫成
`<img src=x onerror=...>`，點開那一天的人就會執行那段腳本 —— 用的是
那個人的登入身分（管理員點到就是管理員權限）。

## 為什麼 escHtml 要連引號一起跳脫

標題同時被塞進 `href="..."` 和 `onclick="openEditChurch('...')"`。只跳脫
`& < >` 的話，一個 `"` 就能跳出屬性、自己加一個 onmouseover。

★ mutation 驗過：
  - base.html 的 escHtml 拿掉 `"` 的替換 → test_eschtml_escapes_quotes 紅
  - calendar.html 任一處改回 `${item.title}` → test_detail_never_inserts_raw_fields 紅
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
CAL = (ROOT / 'templates' / 'calendar.html').read_text(encoding='utf-8')


def _run_eschtml(value):
    fn = re.search(r'function escHtml\(s\) \{.*?\n\}', BASE, re.S)
    assert fn, 'base.html 找不到 escHtml —— 行事曆靠它跳脫'
    assert shutil.which('node'), 'node 不在 —— 這條不能 skip，它守的是真的 JS'
    js = fn.group(0) + f'\nprocess.stdout.write(escHtml({json.dumps(value)}));'
    return subprocess.run(['node', '-e', js], capture_output=True, text=True,
                          check=True, encoding='utf-8').stdout


def test_eschtml_neutralizes_tags():
    assert _run_eschtml('<img src=x onerror=alert(1)>') == '&lt;img src=x onerror=alert(1)&gt;'


def test_eschtml_escapes_quotes():
    # 不跳脫引號，標題就能跳出 href="..." / onclick="..." 屬性
    assert _run_eschtml('a"b\'c') == 'a&quot;b&#39;c'


def test_detail_never_inserts_raw_fields():
    raw = re.findall(r'\$\{item\.(?:title|description|link)\}', CAL)
    assert not raw, f'calendar.html 還有未跳脫的欄位直接進 innerHTML：{raw}'
