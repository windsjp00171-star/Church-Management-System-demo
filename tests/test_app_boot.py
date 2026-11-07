"""整個應用能啟動，而且每一條路由在「空資料庫」下都不會 500（未登入／一般會友／超管各跑一遍）。

在子行程裡跑（tests/smoke_boot.py）：create_app() 會載入全部模組並綁定資料庫，
放在同一個行程會汙染其他測試。之前所有測試都是個別模組加替身，從來沒有真的把整個應用啟動過。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# 刻意的 5xx：沒設定 R2 時，檔案分享頁回 503「功能不可用」說明頁（不是錯誤）
EXPECTED = {('GET', '/files', 503)}


@pytest.fixture(scope='module')
def result():
    p = subprocess.run([sys.executable, str(ROOT / 'tests' / 'smoke_boot.py')], capture_output=True, text=True,
                       timeout=240, cwd=str(ROOT))
    lines = [l for l in p.stdout.splitlines() if l.startswith('{')]
    assert lines, f'應用沒有啟動成功：\n{p.stderr[-1500:]}'
    return json.loads(lines[-1])


def test_app_boots_and_every_route_survives_an_empty_database(result):
    unexpected = [b for b in result['bad'] if (b[1], b[2], b[3]) not in EXPECTED]
    assert not unexpected, unexpected


def test_the_smoke_actually_reaches_pages(result):
    """空轉會讓上面那條永遠綠：身分被擋掉的話，每條路由都只是 302／401。"""
    assert result['checked'] > 800
    assert result['ok200']['admin'] > 100 and result['ok200']['member'] > 40
    assert result['ok200']['anon'] < result['ok200']['member'] < result['ok200']['admin']


def test_protected_pages_are_not_open_to_the_wrong_people(result):
    """5xx 檢查看不到『該擋卻放行』：未登入、一般會友打開需要更高權限的頁面，不可以是 200。"""
    open_pages = [(role, url, code) for role, pages in result['probe'].items()
                  for url, code in pages.items() if code == 200]
    assert not open_pages, open_pages


def test_roll_call_has_an_entry_for_staff_and_not_for_plain_members(result):
    """點名只有後台有卡片時，同工在首頁和同工頁根本找不到它（實際部署時就發生過）。"""
    e = result['entries']
    assert all(e['/'].values()) and all(e['/staff'].values()), e
    assert not any(e['/ (member)'].values()), e          # 一般會友不該看到同工功能的入口
