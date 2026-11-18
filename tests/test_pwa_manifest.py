"""PWA 續登的接線：manifest 對已登入的人夾帶 token、不可被快取、連結要帶 crossorigin。

真的 app 起子行程（editor_server 強制管理員 session），跟 test_check_deps_endpoint 同一招。
"""
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


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


def test_manifest_carries_a_token_when_logged_in_and_is_never_cached(base):
    with urllib.request.urlopen(base + '/manifest.json') as r:
        data = json.loads(r.read())
        headers = r.headers
    assert 'pwa_login=' in data['start_url'], '已登入卻沒有夾帶續登 token'
    assert 'no-store' in headers['Cache-Control']
    assert 'Cookie' in headers['Vary']


def test_manifest_link_sends_credentials():
    """★ 少了 crossorigin，瀏覽器抓 manifest 不帶 cookie，整套靜默失效。"""
    html = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
    html = re.sub(r'\{#.*?#\}', '', html, flags=re.S)
    link = re.search(r'<link rel="manifest"[^>]*>', html).group(0)
    assert 'crossorigin="use-credentials"' in link
