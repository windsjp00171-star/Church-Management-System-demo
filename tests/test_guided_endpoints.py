"""引導式開活動的端點：用真的 app（空資料庫、管理員身分）打一遍

上面 `test_guided.py` 守「答案 → 草稿」，`test_guided_page.py` 守畫面不自己判斷。
這一份守**兩半接不接得起來**：

- 頁面進得去
- 草稿端點回真的草稿、空的請求不會炸、不建立任何東西
- 草稿原封不動丟給既有的 `/admin/events/new` 會被接受 —— 壞掉的樣子是
  「引導式問完了，按下建立跳出伺服器錯誤」，走到最後一步才發現前面全部白填

不能用 admin_client 那種在行程內 patch 的做法（這個 repo 的 app 不能和其他測試同一個行程），
所以跟 test_event_editor_browser 一樣起一個子行程伺服器，用 urllib 打。
擋住陌生人／非管理員那兩條在 tests/smoke_boot.py 的 PROBES（真的三種身分打真的 app）。
"""
import json
import socket
import subprocess
import sys
import time
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


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=H, method='POST')
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


ANSWERS = {'title': '秋之旅', 'event_start': '2026-10-08T07:30', 'capacity': 120, 'fee_mode': 'tiered',
           'tiers': [{'label': '成人', 'price': 800}, {'label': '孩童', 'price': 500}],
           'tier_ages': {'孩童': [None, 12]}, 'uses': ['insurance', 'guardian', 'seating'],
           'reg_end': '2026-09-24T23:59', 'who': 'anyone'}


def test_the_page_opens(base):
    with urllib.request.urlopen(base + '/admin/events/guided') as r:
        assert r.status == 200
        assert '我陪你開一場活動' in r.read().decode()


def test_the_draft_endpoint_builds_a_real_draft(base):
    status, d = _post(base, '/admin/events/guided/draft', ANSWERS)
    assert status == 200
    labels = [f['label'] for f in d['fields']]
    assert '參加者姓名' in labels and '身分證字號' in labels
    assert d['event']['capacity'] == 120
    assert d['said'], '系統做了推論卻沒有講出來'


def test_the_draft_endpoint_survives_an_empty_body(base):
    status, d = _post(base, '/admin/events/guided/draft', {})
    assert status == 200 and 'fields' in d


def test_the_draft_is_accepted_by_the_real_create_endpoint(base):
    """★★★ 兩半接不接得起來是第三件事。"""
    _, d = _post(base, '/admin/events/guided/draft', ANSWERS)
    status, res = _post(base, '/admin/events/new', d['event'])
    assert status == 200 and res.get('success') is True, res


def test_creating_an_event_records_how_it_was_created():
    """引導式與空白表單走同一支建立端點，事後分不出來 —— 沒有這個記錄，
    「引導式有沒有人用」就只能用猜的（做了但沒人用，跟壞掉在數據上一樣）。"""
    import ast
    src = (ROOT / 'routes' / 'admin.py').read_text(encoding='utf-8')
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == 'event_new')
    body = '\n'.join(src.split('\n')[fn.lineno - 1:fn.end_lineno])
    assert '_log_how_it_was_created(event_id, data)' in body
    assert body.index('_log_how_it_was_created(') < body.index("table('event_fields').insert")
