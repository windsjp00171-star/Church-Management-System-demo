"""行事曆訂閱（.ics）

使用者：「行事曆訂閱我個人也覺得是好東西可以做」。

價值就一句話：**不用回來看** —— 訂閱之後教會的聚會直接長在他自己手機的
日曆上。所以這一份的失敗模式全部是「訂閱了，但日曆上什麼都沒有」，
而**手機不會告訴他為什麼**：不會有錯誤訊息，就是空的。下面每一條各守一種。
"""
import re
from datetime import datetime, timezone

import sys
import types

import pytest

# routes.calendar_feed 載入時會 import db；沒有真的環境變數時換成假的（端點測試另有 fixture 再換一次）
if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

from routes.calendar_feed import build_ics, esc, fold, FEED_SALT
from routes.pwa_session import issue_token

NOW = datetime(2026, 9, 11, 4, 0, tzinfo=timezone.utc)


def _ics(church=None, events=None, personal=None):
    return build_ics(church or [], events or [], personal or [], now=NOW)


# ══ 一、格式：錯了整份讀不進去 ═══════════════════════════

def test_lines_end_with_crlf():
    """★ RFC 要求 CRLF，而且真的有客戶端因為 LF 就整份不讀 ——
    症狀是「訂閱成功但空的」，沒有任何錯誤訊息。"""
    out = _ics(church=[{'id': '1', 'title': '禱告會', 'event_date': '2026-09-13'}])
    assert '\r\n' in out
    assert re.search(r'[^\r]\n', out) is None, '有一行不是 CRLF 結尾'


def test_a_long_chinese_title_is_folded_without_breaking_a_character():
    """★★ 一行不可以超過 **75 個位元組**（不是 75 個字）。

    中文一個字 3 個位元組 → 26 個字就爆了，而教會行事的標題常常更長。
    不折的話 Google 日曆會跳過那一行（整個事件不見）。
    ★ 而且折的時候**不可以把一個中文字切成兩半** —— 切壞的話
      整份 feed 變亂碼，比少一個事件更糟。
    """
    title = '安' * 40
    out = _ics(church=[{'id': '1', 'title': title, 'event_date': '2026-09-13'}])
    for line in out.split('\r\n'):
        assert len(line.encode('utf-8')) <= 75, f'這一行太長：{len(line.encode())} 位元組'
    #  折過之後把續行的前導空白接回去，內容要跟原本一模一樣（沒有切壞字）
    unfolded = out.replace('\r\n ', '')
    assert 'SUMMARY:' + title in unfolded


def test_fold_keeps_short_lines_untouched():
    assert fold('SUMMARY:abc') == 'SUMMARY:abc'


@pytest.mark.parametrize('raw,expected', [
    ('早餐,午餐', r'早餐\,午餐'),
    ('地點;二樓', r'地點\;二樓'),
    ('a\\b', 'a\\\\b'),
    ('第一行\n第二行', r'第一行\n第二行'),
])
def test_text_is_escaped(raw, expected):
    """★ 標題裡一個逗號不跳脫，就會被當成「兩個值」——
    多數客戶端的反應是**整個事件消失**，不是顯示錯誤。"""
    assert esc(raw) == expected


# ══ 二、日期：差一天沒有人看得出來 ═══════════════════════

def test_an_all_day_event_ends_the_day_after():
    """★★ 全天事件的 DTEND 是**結束日的隔天**（RFC 是不含結束日的）。

    直接放結束日的話，跨日的特會在手機上**少一天**，
    而且那一格看起來完全正常。
    """
    out = _ics(church=[{'id': '1', 'title': '特會', 'event_date': '2026-09-11',
                        'end_date': '2026-09-13'}])
    assert 'DTSTART;VALUE=DATE:20260911' in out
    assert 'DTEND;VALUE=DATE:20260914' in out, 'DTEND 要是結束日的隔天'


def test_a_single_day_event_still_has_an_end():
    out = _ics(church=[{'id': '1', 'title': '禱告會', 'event_date': '2026-09-13'}])
    assert 'DTSTART;VALUE=DATE:20260913' in out
    assert 'DTEND;VALUE=DATE:20260914' in out


def test_timed_events_go_out_as_utc():
    """★ 資料庫存的就是 UTC，直接輸出 `...Z` —— **不轉就不會錯**，
    客戶端自己會用使用者的時區顯示。

    （這一條繞開了這個專案踩過三次的時區坑：早上 8 點前的活動
      一被切字串就會掉到前一天。）
    """
    out = _ics(events=[{'id': 'e1', 'title': '秋之旅',
                        'event_start': '2026-10-04T01:30:00+00:00',
                        'event_end': '2026-10-04T09:00:00+00:00'}])
    assert 'DTSTART:20261004T013000Z' in out
    assert 'DTEND:20261004T090000Z' in out


def test_an_event_without_an_end_time_still_works():
    out = _ics(events=[{'id': 'e1', 'title': '晨禱',
                        'event_start': '2026-10-04T22:00:00+00:00'}])
    assert 'DTSTART:20261004T220000Z' in out
    assert 'DTEND:20261004T220000Z' in out


# ══ 三、壞資料不可以毀掉整份 ═════════════════════════════

def test_one_broken_row_does_not_kill_the_rest():
    """★★ 一筆算不出日期的資料，**不可以讓整份 feed 壞掉** ——
    那會讓他手機上的日曆整個變空，而那看起來像教會突然什麼都沒有了。"""
    out = _ics(church=[
        {'id': 'bad', 'title': '壞的', 'event_date': None},
        {'id': 'bad2', 'title': '也是壞的', 'event_date': '不是日期'},
        {'id': 'ok', 'title': '好的', 'event_date': '2026-09-13'},
    ])
    assert 'SUMMARY:好的' in out
    assert '壞的' not in out, '算不出日期的不要猜一天塞進去'
    assert out.count('BEGIN:VEVENT') == 1


def test_every_event_has_a_stable_uid():
    """★ UID 不穩定的話，每次更新客戶端都當成新事件 ——
    訂閱一個月之後他的日曆上會有三十份一樣的聚會。"""
    a = _ics(church=[{'id': 'x', 'title': '禱告會', 'event_date': '2026-09-13'}])
    b = _ics(church=[{'id': 'x', 'title': '禱告會（改名）', 'event_date': '2026-09-13'}])
    uid = re.search(r'UID:(\S+)', a).group(1)
    assert uid == re.search(r'UID:(\S+)', b).group(1)
    assert 'x' in uid


def test_the_three_kinds_do_not_share_uids():
    """★ 三種來源的 id 可能撞號（各自的表各自編）——
    撞到的話其中一個會把另一個蓋掉，而少掉的那個不會有任何徵兆。"""
    out = _ics(church=[{'id': '1', 'title': 'A', 'event_date': '2026-09-13'}],
               personal=[{'id': '1', 'title': 'B', 'event_date': '2026-09-13'}])
    uids = re.findall(r'UID:(\S+)', out)
    assert len(uids) == 2 and len(set(uids)) == 2, uids


def test_it_tells_clients_how_often_to_come_back():
    """★ 不講的話 Google 可能一天只抓一次 ——
    臨時改的聚會時間會晚一天才到他手機上。"""
    out = _ics()
    assert 'REFRESH-INTERVAL' in out and 'X-PUBLISHED-TTL' in out


# ══ 四、端點與身分 ═══════════════════════════════════════

URL = '/calendar.ics'


@pytest.fixture
def app(fake_db):
    from flask import Flask
    import routes.calendar_feed as cf
    a = Flask(__name__)
    a.secret_key = 'test'
    a.register_blueprint(cf.calendar_feed_bp)
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def test_no_token_is_refused_not_redirected(client):
    """★★ **不可以導去登入頁**：日曆客戶端不會登入，它只會一直拿到
    一頁 HTML，然後顯示「訂閱成功但沒有東西」—— 而那跟「教會最近沒有
    聚會」在畫面上一模一樣。回 403 才看得出是壞的。"""
    r = client.get(URL)
    assert r.status_code == 403
    assert r.status_code not in (301, 302)


def test_a_forged_token_is_refused(client):
    assert client.get(URL + '?t=not-a-real-token').status_code == 403


def test_a_login_token_cannot_read_the_calendar(client, app):
    """★ 續登的 token 跟訂閱的 token **salt 不同** ——
    共用一個的話，PWA 的續登網址外流就等於行事曆也外流。"""
    login_token = issue_token(app.secret_key, 'u1')       # 預設 salt
    assert client.get(URL + f'?t={login_token}').status_code == 403


def test_a_valid_token_gets_a_calendar(client, app):
    from unittest.mock import MagicMock, patch
    token = issue_token(app.secret_key, 'u1', FEED_SALT)
    sb = MagicMock()
    sb.table.return_value.select.return_value.gte.return_value.lte.return_value\
        .order.return_value.execute.return_value.data = []
    sb.table.return_value.select.return_value.eq.return_value.gte.return_value\
        .lte.return_value.order.return_value.execute.return_value.data = []
    with patch('routes.calendar_feed.supabase', sb):
        r = client.get(URL + f'?t={token}')
    assert r.status_code == 200
    assert 'text/calendar' in r.headers['Content-Type']
    assert r.get_data(as_text=True).startswith('BEGIN:VCALENDAR')
    # ★ 不可被快取擋住：教會剛改的時間，日曆回來抓時要拿到最新的
    assert 'no-cache' in r.headers['Cache-Control']


def test_personal_events_are_filtered_to_the_owner(client, app):
    """★★ 個人行程一定要用 token 裡的 user_id 去撈。

    少了那個條件的話，**每個人的訂閱都會拿到全教會的個人行程** ——
    而他自己的日曆上看起來只是多了一些不認識的行程。
    """
    src = (__import__('pathlib').Path(__file__).resolve().parent.parent
           / 'routes' / 'calendar_feed.py').read_text(encoding='utf-8')
    body = src[src.index("personal = supabase"):]
    body = body[:body.index('except Exception')]
    assert ".eq('user_id', uid)" in body, '個人行程沒有綁使用者'


# ── 真的 app（子行程）：頁面給的網址，真的打得開 ──────────────

def test_the_calendar_page_hands_out_a_url_that_really_serves_a_calendar():
    import re
    import socket
    import subprocess
    import time
    import urllib.request
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    with socket.socket() as so:
        so.bind(('127.0.0.1', 0))
        port = so.getsockname()[1]
    srv = subprocess.Popen([sys.executable, str(root / 'tests' / 'editor_server.py'), str(port)], cwd=str(root),
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        assert srv.stdout.readline().strip() == 'READY'
        time.sleep(0.3)
        base = f'http://127.0.0.1:{port}'
        html = urllib.request.urlopen(base + '/calendar').read().decode()
        m = re.search(r'id="cal-feed-url"[^>]*value="([^"]+)"', html)
        assert m, '行事曆頁沒有給訂閱網址'
        url = m.group(1).replace('&amp;', '&')
        assert url.startswith(base + '/calendar.ics?t=')
        # 不帶 cookie（日曆客戶端就是這樣來抓）
        r = urllib.request.urlopen(url)
        assert r.status == 200 and 'text/calendar' in r.headers['Content-Type']
        assert r.read().decode().startswith('BEGIN:VCALENDAR')
    finally:
        srv.kill()
