"""聖經速讀的端點：用真的 app（空資料庫、管理員身分）打一遍

單元層（計畫資料、經文解析、模板）由 test_bible_plan／test_bible_text／test_reading_reread 守；
這裡守的是**接得起來**：整個 app 啟動後頁面開得了、打勾回傳整組數字、不存在的格子被拒絕。
`/reading/<第幾格>` 不在這裡打（沒有快取時它會真的去抓別人的站），由 test_bible_text 的 render 測試守。
擋住陌生人的探針在 tests/smoke_boot.py。跟 test_guided_endpoints 一樣起子行程伺服器。
"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
H = {'Content-Type': 'application/json', 'X-CSRF-Token': 't'}


@pytest.fixture(scope='module')
def base():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    srv = subprocess.Popen([sys.executable, str(ROOT / 'tests' / 'editor_server.py'), str(port)], cwd=str(ROOT),
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        assert srv.stdout.readline().strip() == 'READY'
        time.sleep(0.3)
        yield f'http://127.0.0.1:{port}'
    finally:
        srv.kill()


def _get(base, path):
    with urllib.request.urlopen(base + path) as r:
        return r.status, r.read().decode()


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=H, method='POST')
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_progress_page_opens(base):
    status, html = _get(base, '/reading')
    assert status == 200 and '聖經速讀' in html


def test_the_printable_sheet_opens_and_shows_all_365_cells(base):
    status, html = _get(base, '/reading/sheet')
    assert status == 200
    assert html.count('href="/reading/') >= 365


def test_ticking_a_cell_returns_the_whole_set_of_numbers(base):
    status, d = _post(base, '/reading/mark', {'day_no': 1, 'done': True})
    assert status == 200 and d['ok'] is True
    assert d['stats']['total'] == 365


@pytest.mark.parametrize('day_no', [0, 366, 'x', None])
def test_a_cell_that_is_not_in_the_plan_is_refused(base, day_no):
    status, d = _post(base, '/reading/mark', {'day_no': day_no, 'done': True})
    assert status == 400 and d['error']
