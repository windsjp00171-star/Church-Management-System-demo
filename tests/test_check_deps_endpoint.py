"""活動表單的即時提示端點 `/admin/events/check-deps`：用真的 app 打一遍

規則本身（11 條裡這個 repo 有的那幾條）由 `test_setting_deps*.py` 守；這裡守的是
「草稿送上來 → 伺服器用註冊表回提示」這條路接得起來，而且**不寫任何東西**。
（成熟版這幾條靠 admin_client 在行程內 patch，這個 repo 的 app 不能和其他測試同一個行程，
所以跟 test_guided_endpoints 一樣起子行程伺服器。擋陌生人那一條在 tests/smoke_boot.py 的 PROBES。）
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


def _deps(base, body):
    req = urllib.request.Request(base + '/admin/events/check-deps', data=json.dumps(body).encode(), headers=H, method='POST')
    with urllib.request.urlopen(req) as r:
        assert r.status == 200
        return {d['key']: d for d in json.loads(r.read())['deps']}


def test_an_unmet_dep_is_reported_with_its_key_and_words(base):
    d = _deps(base, {'waitlist_enabled': True, 'capacity': None, 'fields': []})
    assert 'waitlist_needs_capacity' in d
    assert '候補' in d['waitlist_needs_capacity']['text']


def test_nothing_is_said_when_the_dep_is_met(base):
    assert 'waitlist_needs_capacity' not in _deps(base, {'waitlist_enabled': True, 'capacity': 50, 'fields': []})


def test_the_custom_fields_are_read_too(base):
    d = _deps(base, {'fields': [{'label': '監護人', 'field_type': 'guardian', 'is_required': True}]})
    assert 'guardian_needs_birthday' in d


def test_an_empty_body_does_not_break_it(base):
    assert isinstance(_deps(base, {}), dict)
