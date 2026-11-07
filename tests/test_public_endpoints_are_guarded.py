"""公開端點的基本防護：重複、速率、蜜罐（搬自成熟版的 test_public_endpoints_are_guarded）

報名連結是公開的 —— `/event/<id>/external-register`、`compute-tier`、`compute-age` 任何人都打得到、不用登入。
真正會痛的不是資料庫塞不塞得下，是**名額**：80 個位子被腳本幾秒佔滿，真的要報名的人就報不進來，
畫面上完全正常（就是額滿）。最常發生的其實是最無辜的那種：手滑連按兩次送出。同一道防線兩種都擋。

三層，職責不同（`routes/guard.py` 開頭有完整說明）：
  蜜罐 → 照著 name 填表的笨機器人｜速率限制（每 IP）→ 手滑連按、隨手寫的迴圈｜身分證字號 → 同一個人報兩次

成熟版的測試靠 `test_waitlist_rehearsal` 的整套假資料庫與完整 app，這個 repo 的 app 不能和其他測試同一個行程，
所以：純邏輯（限流器、重複檢查）在行程內用 `FakeSupabase` 測；端點用 `tests/editor_server.py`
起子行程（真的 create_app、空資料庫），跟 `test_guided_endpoints` 同一個做法。
"""
import json
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ══ 一、純邏輯（行程內）══════════════════════════════

def test_the_limiter_forgets_old_hits():
    """滑動視窗要真的滑 —— 不然跑久了每個人都會被永久擋住。"""
    from routes.guard import reset_for_tests, too_many

    reset_for_tests()
    assert not too_many('k', 2, 60, now=1000)
    assert not too_many('k', 2, 60, now=1001)
    assert too_many('k', 2, 60, now=1002), '第三次應該要被擋'
    assert not too_many('k', 2, 60, now=1100), '視窗過了還在擋'


def test_the_bucket_table_cannot_grow_without_bound():
    """★ 防護本身不可以變成攻擊面：換 IP 灌進來會把記憶體吃光。"""
    from routes import guard

    guard.reset_for_tests()
    limit = guard._MAX_BUCKETS
    for i in range(limit + 50):
        guard.too_many(f'k{i}', 5, 1, now=1000 + i * 100)
    assert len(guard._HITS) <= limit + 10, '桶子沒有上限'
    guard.reset_for_tests()


def test_it_buckets_by_forwarded_ip():
    """★★ Render 在反向代理後面：不看 X-Forwarded-For 的話所有人共用同一個桶子，
    第一批人報完，後面的全部被擋，而畫面上只會說「太多次了」。"""
    from flask import Flask
    from routes import guard

    guard.reset_for_tests()
    app = Flask(__name__)
    limits = [(3, 60)]
    with app.test_request_context('/', headers={'X-Forwarded-For': '1.1.1.1, 10.0.0.1'}):
        assert [guard.rate_limited('x', limits) for _ in range(3)] == [None] * 3
        assert guard.rate_limited('x', limits), '同一個 IP 第四次應該被擋'
    with app.test_request_context('/', headers={'X-Forwarded-For': '2.2.2.2'}):
        assert guard.rate_limited('x', limits) is None, '別的 IP 被連帶擋了'
    guard.reset_for_tests()


def test_the_message_says_what_to_do():
    """只說「操作太頻繁」的話使用者只會一直重按。"""
    from flask import Flask
    from routes import guard

    guard.reset_for_tests()
    with Flask(__name__).test_request_context('/'):
        msg = [guard.rate_limited('y', [(1, 600)]) for _ in range(2)][1]
    assert '分鐘' in msg and '分次' in msg
    guard.reset_for_tests()


def test_the_honeypot():
    from routes.guard import HONEYPOT_FIELD, looks_automated
    assert looks_automated({HONEYPOT_FIELD: 'http://spam.example'})
    assert not looks_automated({HONEYPOT_FIELD: ''})
    assert not looks_automated({HONEYPOT_FIELD: '   '})
    assert not looks_automated({}) and not looks_automated(None)


def test_the_honeypot_is_on_the_form_and_hidden():
    """★ 藏的方式要讓人碰不到、機器人看得到。tabindex／autocomplete 少一個，
    真的使用者用鍵盤 tab 過去、或被瀏覽器自動填入就會被擋 —— 那是這一招唯一會誤傷人的方式，
    而他完全不知道發生什麼事。"""
    from routes.guard import HONEYPOT_FIELD
    src = open('templates/external_register.html', encoding='utf-8').read()
    i = src.index(f'name="{HONEYPOT_FIELD}"')
    seg = src[max(0, i - 500):i + 300]
    assert 'tabindex="-1"' in seg and 'autocomplete="off"' in seg
    assert 'left:-9999px' in seg or 'display:none' in seg
    assert HONEYPOT_FIELD in src.split('JSON.stringify')[1][:600], \
        '表單有那一格，但送出時沒有一起送 —— 蜜罐等於沒裝'


def test_no_captcha():
    """★ 刻意不做圖形驗證碼（使用者的族群有一半以上是長輩）：擋掉真的要報名的人，
    比被灌幾筆假資料嚴重得多。這條把那個決定記下來，免得哪天「順手加一個」。"""
    src = open('routes/guard.py', encoding='utf-8').read()
    code = re.sub(r'"""[\s\S]*?"""', '', src)
    assert 'captcha' not in code.lower()
    assert 'CAPTCHA' in src, '決定要寫在文件裡，不然下一個人不知道'


# ── 重複檢查（身分證字號）──────────────────────────

ID_A, ID_B = 'A123456789', 'B222222228'          # 檢查碼正確的號碼


@pytest.fixture
def dup(monkeypatch, fake_db):
    for name in ('routes.event',):
        sys.modules.pop(name, None)
    import routes.event as ev
    from tests.fake_supabase import FakeSupabase
    db = FakeSupabase(
        event_fields=[{'id': 'f-id', 'event_id': 'e1', 'field_type': 'id_number'},
                      {'id': 'f-name', 'event_id': 'e1', 'field_type': 'text'}],
        registrations=[{'id': 'r1', 'event_id': 'e1', 'status': 'registered'},
                       {'id': 'r2', 'event_id': 'e1', 'status': 'cancelled'}],
        registration_answers=[{'registration_id': 'r1', 'field_id': 'f-id', 'answer': ID_A},
                              {'registration_id': 'r2', 'field_id': 'f-id', 'answer': ID_B}])
    monkeypatch.setattr(ev, 'supabase', db)
    return ev, db


def _ans(v):
    return [{'field_id': 'f-id', 'answer': v}]


def test_the_same_id_number_cannot_register_twice(dup):
    ev, _ = dup
    assert '已經報名過' in ev._reject_duplicate_person('e1', _ans(ID_A))


def test_the_id_is_compared_after_cleaning_it_up(dup):
    """空白、小寫不能繞過去。"""
    ev, _ = dup
    assert ev._reject_duplicate_person('e1', _ans(' a123456789 '))


def test_a_different_id_is_fine(dup):
    ev, _ = dup
    assert ev._reject_duplicate_person('e1', _ans('C100000000')) is None


def test_cancelled_registrations_do_not_block_you(dup):
    ev, _ = dup
    assert ev._reject_duplicate_person('e1', _ans(ID_B)) is None


def test_the_message_points_at_the_way_back(dup):
    """多數撞到的人不是壞人，是以為自己沒送出去。"""
    ev, _ = dup
    assert '請回到活動頁面' in ev._reject_duplicate_person('e1', _ans(ID_A))


def test_an_event_without_an_id_field_is_not_checked(dup):
    """★ 寧可少擋、不要擋錯人：沒有身分證欄位就不做這道檢查，不退回比姓名（同名的人不少）。"""
    ev, db = dup
    db.rows('event_fields')[:] = [f for f in db.rows('event_fields') if f['field_type'] != 'id_number']
    assert ev._reject_duplicate_person('e1', [{'field_id': 'f-name', 'answer': '王小明'}]) is None


def test_a_blank_id_is_not_a_key(dup):
    ev, _ = dup
    assert ev._reject_duplicate_person('e1', _ans('')) is None


def test_both_public_registration_paths_check_duplicates():
    """★ 漏掉一個寫入點，那個入口就是繞過的方法。"""
    src = open('routes/event.py', encoding='utf-8').read()
    assert src.count('_reject_duplicate_person(') == 3        # 定義一次、會員與外部各呼叫一次


# ══ 二、端點（真的 app，子行程）═══════════════════════

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


def _post(base, path, body, ip=None):
    headers = {'Content-Type': 'application/json', 'X-CSRF-Token': 't'}
    if ip:
        headers['X-Forwarded-For'] = ip
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_the_honeypot_blocks_a_filled_in_bot(base):
    assert _post(base, '/event/e1/external-register', {'guest_name': '機器人', 'nickname_confirm': 'http://spam'}) == 400


def test_a_flood_gets_cut_off_and_another_ip_is_not_dragged_down(base):
    """一支腳本灌 —— 第 61 次起要被切掉（429）；★ 換一個 IP 的人不受影響（Render 在反向代理後面，要看 X-Forwarded-For）。"""
    codes = [_post(base, '/event/e1/external-register', {'guest_name': f'甲{i}'}, ip='1.1.1.1') for i in range(70)]
    assert 429 in codes and codes.index(429) <= 61, '灌 70 次沒有被切掉'
    assert _post(base, '/event/e1/external-register', {'guest_name': '另一台手機'}, ip='2.2.2.2') != 429


def test_the_calculators_leave_room_for_a_whole_congregation(base):
    """★ 公告完一整群人同時填表，在伺服器眼裡是同一個 IP。抓太緊的後果不是「慢」，是「填不出去」。
    所以 compute-age 一分鐘 600 次內都要放行，超過才擋（一支腳本才做得到的量級）。"""
    codes = [_post(base, '/compute-age', {'birthdays': {}}, ip='3.3.3.3') for _ in range(610)]
    assert 429 not in codes[:600], '正常使用的量就被擋了'
    assert 429 in codes[600:], '一直打沒有被擋'


def test_compute_tier_is_rate_limited_too(base):
    codes = [_post(base, '/event/e1/compute-tier', {'birthday': '1990-01-01'}, ip='4.4.4.4') for _ in range(610)]
    assert 429 in codes[600:] and 429 not in codes[:600]
