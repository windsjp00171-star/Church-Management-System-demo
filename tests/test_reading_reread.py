"""聖經速讀：回頭重讀已經讀過的範圍

使用者：「我是要能夠可以回到之前的某一個進度重讀」。

原本技術上做得到（每一格都能「翻開」），但走不下去：
- 入口藏在 66 卷的收合清單裡，得先知道是哪一卷
- 已讀的格子還寫著「翻開」，看不出是重讀
- 重讀完「接下來」直接跳到最前面還沒讀的地方，一段範圍要一格一格回清單點
- 沒有「回到我的進度」的路

★ 全程不動任何已讀紀錄（沒有寫入、不改資料庫）。
"""
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def _login(client):
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
        s['real_name'] = '測試'


def _day(client, day_no, done):
    _login(client)
    with patch('routes.bible_plan.done_days', return_value=set(done)), \
         patch('routes.bible_text.get_passage', return_value=[]):
        return client.get(f'/reading/{day_no}').get_data(as_text=True)


def test_reread_card_points_at_the_following_cell_when_both_are_read(client):
    html = _day(client, 1, {1, 2})
    assert 'id="rd-reread"' in html
    assert 'href="/reading/2"' in html.split('id="rd-reread"')[0][-80:] + html.split('id="rd-reread"')[1][:120]
    assert '回到我還沒讀的進度' in html, '原本那張「接下來」沒退成「回到進度」'


def test_no_reread_card_when_the_following_cell_is_unread(client):
    """★ 下一格還沒讀＝那是「繼續讀」，標成重讀是錯的。"""
    assert 'id="rd-reread"' not in _day(client, 1, {1})


def test_no_reread_card_when_this_cell_is_not_read_yet(client):
    assert 'id="rd-reread"' not in _day(client, 1, {2, 3})
    assert '繼續讀下一格' in _day(client, 1, {2, 3})


def test_day_page_does_not_have_a_misleading_all_progress_card(client):
    """★ 使用者：「你用在目前進度最下面會讓人誤會」—— 那張「全部進度」緊貼在
    「目前進度」底下，讀起來像進度總覽，不像重讀入口。重讀的入口是「我的速讀表」。"""
    html = _day(client, 1, set())
    assert 'id="rd-all"' not in html and '全部進度</span>' not in html
    assert 'href="/reading/sheet"' in html


def test_every_cell_of_the_print_list_opens_that_cell(client):
    """★★ 使用者：「不是直接從速讀列表那邊點範圍進去重讀嗎」—— 那張表顯示所有範圍，
    格子卻點不了。每一格都要連到 /reading/<第幾格>，印出來完全看不出來。"""
    import re
    _login(client)
    with patch('routes.bible_plan.done_days', return_value={1}), \
         patch('routes.bible_plan.read_dates', return_value={}):
        html = client.get('/reading/sheet').get_data(as_text=True)
    cells = re.findall(r'<a class="sh-cell[^"]*" href="(/reading/\d+)"', html)
    assert len(cells) == 365 and len(set(cells)) == 365, len(cells)
    assert '/reading/1' in cells and '/reading/365' in cells


def test_list_page_has_jump_and_labels_read_cells_as_reread(client):
    _login(client)
    with patch('routes.bible_plan.done_days', return_value={1}):
        html = client.get('/reading').get_data(as_text=True)
    assert 'id="jump-book"' in html
    assert '>重讀</a>' in html and '>翻開</a>' in html


def test_the_page_never_writes_anything(client):
    """★ 重讀只是打開來再讀一次 —— 開頁不可以標記或取消任何一格。"""
    _login(client)
    with patch('routes.bible_plan.done_days', return_value={1, 2}), \
         patch('routes.bible_text.get_passage', return_value=[]), \
         patch('routes.bible_plan.mark') as m, patch('routes.bible_plan.unmark') as u:
        client.get('/reading/1')
        client.get('/reading')
    assert not m.called and not u.called


def test_toggling_hides_the_reread_card_instead_of_guessing():
    js = (ROOT / 'static' / 'js' / 'bible-reading-day.js').read_text(encoding='utf-8')
    body = js[js.index("doneBtn.addEventListener('click'"):]
    assert 'rereadCard.hidden = true' in body, \
        '打勾／取消之後沒收起「重讀下一格」—— 下一格讀沒讀過前端不知道'


def test_picking_a_book_opens_it_in_a_real_browser(client):
    """★ 選單的 JS 在瀏覽器裡真的要展開那一卷 —— 掃原始碼看不到它會不會動。"""
    import pytest
    pytest.importorskip('playwright', reason='沒裝 playwright')
    from playwright.sync_api import sync_playwright
    _login(client)
    with patch('routes.bible_plan.done_days', return_value={1}):
        html = client.get('/reading').get_data(as_text=True)
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
        except Exception:
            b = p.chromium.launch()
        pg = b.new_page(viewport={'width': 390, 'height': 800})
        pg.set_content(html)
        before = pg.evaluate("document.querySelectorAll('#book-list details[open]').length")
        pg.select_option('#jump-book', index=2)       # 第二卷書
        picked = pg.evaluate("document.getElementById('jump-book').value")
        opened = pg.evaluate("""() => { const d = document.querySelector(
            '#book-list details.br-book[open]'); return d ? d.dataset.book : null; }""")
        b.close()
    assert before == 0 and opened == picked, (before, picked, opened)


# ── 記錄重讀次數與日期 ──────────────────────────────────
# 欄位：bible_reading_progress.reread_count / last_reread_on（migrations/2026_bible_reread.sql）

from datetime import date, timedelta

from tests.fake_supabase import FakeSupabase


def _db(**row):
    base = {'id': 'p1', 'user_id': 'u1', 'plan_key': 'k', 'day_no': 5, 'read_on': '2026-01-01',
            'reread_count': 0, 'last_reread_on': None}
    base.update(row)
    return FakeSupabase(bible_reading_progress=[base])


def _bp(db):
    import routes.bible_plan as bp
    return bp, patch.object(bp, 'active_plan_key', return_value='k')


def test_reread_records_count_and_date_but_never_touches_the_first_read_date():
    db = _db()
    bp, pk = _bp(db)
    with pk:
        r = bp.mark_reread('u1', 5, today=date(2026, 10, 27), sb=db)
    assert r['count'] == 1 and r['last'] == date(2026, 10, 27) and r['added']
    row = db.rows('bible_reading_progress')[0]
    assert row['read_on'] == '2026-01-01', '重讀不可以改第一次讀的日期'


def test_two_taps_on_the_same_day_count_once():
    """★ 長輩連點是常態，一次手滑不該變成「重讀三次」。"""
    db = _db()
    bp, pk = _bp(db)
    with pk:
        bp.mark_reread('u1', 5, today=date(2026, 10, 27), sb=db)
        again = bp.mark_reread('u1', 5, today=date(2026, 10, 27), sb=db)
    assert again['count'] == 1 and again['added'] is False


def test_another_day_counts_again():
    db = _db()
    bp, pk = _bp(db)
    with pk:
        bp.mark_reread('u1', 5, today=date(2026, 10, 27), sb=db)
        r = bp.mark_reread('u1', 5, today=date(2026, 10, 27) + timedelta(days=3), sb=db)
    assert r['count'] == 2


def test_cell_never_marked_cannot_be_reread():
    db = FakeSupabase(bible_reading_progress=[])
    bp, pk = _bp(db)
    with pk:
        assert bp.mark_reread('u1', 5, sb=db) is None


def test_without_the_columns_everything_degrades_to_nothing():
    """★ SQL 還沒執行：不可以丟例外、不可以畫出一顆按了必失敗的鈕。"""
    db = FakeSupabase(bible_reading_progress=[
        {'user_id': 'u1', 'plan_key': 'k', 'day_no': 5, 'read_on': '2026-01-01'}])
    bp, pk = _bp(db)
    with pk:
        assert bp.reread_info('u1', 5, sb=db) is None
        assert bp.mark_reread('u1', 5, sb=db) is None


def test_day_page_draws_the_reread_box_only_when_there_is_a_record(client):
    _login(client)
    for info, shown in (({'count': 2, 'last': date(2026, 10, 1)}, True), (None, False)):
        with patch('routes.bible_plan.done_days', return_value={1}), \
             patch('routes.bible_plan.reread_info', return_value=info), \
             patch('routes.bible_text.get_passage', return_value=[]):
            html = client.get('/reading/1').get_data(as_text=True)
        assert ('id="rd-reread-btn"' in html) is shown
        if shown:
            assert '已重讀 2 次' in html and '2026-10-01' in html


def test_reread_endpoint_requires_login_and_a_read_cell(client):
    assert client.post('/reading/reread', json={'day_no': 1}).status_code == 401
    _login(client)
    with patch('routes.bible_plan.mark_reread', return_value=None):
        assert client.post('/reading/reread', json={'day_no': 1}).status_code == 400
    with patch('routes.bible_plan.mark_reread',
               return_value={'count': 3, 'last': date(2026, 10, 27), 'added': True}):
        d = client.post('/reading/reread', json={'day_no': 1}).get_json()
    assert d == {'ok': True, 'count': 3, 'last': '2026-10-27', 'added': True}
