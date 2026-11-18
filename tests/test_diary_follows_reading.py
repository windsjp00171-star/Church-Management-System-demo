"""天父日記和聖經速讀是同一套計畫（使用者：「想讀的讀 可以只讀過 想寫的可以寫下來」，2026-11-18）

速讀開著時：日記的經文＝速讀那一格；從讀經頁按「寫下來」帶著那一格；存好日記就算讀過（順手打勾，
已經打過的不改日期）；牧者看別人的日記算不到那個人讀哪一格，寧可不顯示也不要顯示錯的。
"""
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def _plan(fake_db, d, day=None, dates=None, done=(), today='2026-11-18', on=True):
    from flask import Flask, session
    import routes.diary as dy
    import routes.bible_plan as bp
    app = Flask(__name__); app.secret_key = 'x'
    with app.test_request_context(), \
         patch.object(dy, '_reading_on', return_value=on), \
         patch.object(dy, '_today_str', return_value=today), \
         patch.object(bp, 'read_dates', return_value=dates or {}), \
         patch.object(bp, 'done_days', return_value=set(done)), \
         patch.object(dy, 'load_plan_map', return_value={d: {'book': '舊的', 'range': '1:1'}}):
        session['user_id'] = 'u1'
        return dy._plan_for(d, day)


def test_explicit_day_from_the_reading_page(fake_db):
    p = _plan(fake_db, '2026-11-18', day='1')
    assert p['day_no'] == 1 and p['book'] == '創世記' and p['label'] == '創 1-4'
    assert p['range'].startswith('1:1-4:')                         # 整章到最後一節


def test_today_without_a_day_is_the_next_unread(fake_db):
    assert _plan(fake_db, '2026-11-18', done={1, 2})['day_no'] == 3


def test_a_past_date_shows_what_was_ticked_that_day(fake_db):
    import datetime
    p = _plan(fake_db, '2026-11-10', dates={5: datetime.date(2026, 11, 10), 7: datetime.date(2026, 11, 10),
                                            6: datetime.date(2026, 11, 11)})
    assert p['day_no'] == 7                                        # 一天讀兩格：配最後讀的那一格
    assert _plan(fake_db, '2026-11-01') is None                    # 那天沒讀：不編一段


def test_psalm_119_split_keeps_its_verse_range(fake_db):
    import routes.bible_plan as bp
    no = next(d['day_no'] for d in bp.days() if d['label'].startswith('詩 119') and '89' in d['label'])
    assert _plan(fake_db, '2026-11-18', day=str(no))['range'] == '119:89-119:176'


def test_reading_off_falls_back_to_the_diary_plan(fake_db):
    assert _plan(fake_db, '2026-11-18', on=False) == {'book': '舊的', 'range': '1:1'}


def test_it_is_an_option_off_by_default(fake_db):
    """有的教會讀經和靈修是兩份進度：預設不跟，日記後台切換才跟。"""
    import routes.diary as dy
    import settings_store
    with patch('routes.modules.is_enabled', return_value=True):
        with patch.object(settings_store, 'get', return_value=None):
            assert dy._reading_on() is False
        with patch.object(settings_store, 'get', return_value='true'):
            assert dy._reading_on() is True
    with patch('routes.modules.is_enabled', return_value=False), patch.object(settings_store, 'get', return_value='true'):
        assert dy._reading_on() is False                                # 速讀關掉：一律不跟
    rd = (ROOT / 'templates' / 'bible_reading_day.html').read_text(encoding='utf-8')
    assert "module_on('diary') and diary_follows" in rd                 # 不跟的時候讀經頁沒有「寫下來」


def test_wiring():
    src = (ROOT / 'routes' / 'diary.py').read_text(encoding='utf-8')
    assert src.count("_plan_for(d, request.args.get('day'))") == 3      # 日記頁＋兩支 AI
    assert "if int(rd) not in bp.done_days(session['user_id'])" in src  # 寫下來＝讀過，不改舊日期
    assert "plan = None if _reading_on() else load_plan_map().get(d)" in src   # 牧者頁
    tpl = (ROOT / 'templates' / 'diary' / 'index.html').read_text(encoding='utf-8')
    assert 'name="reading_day" value="{{ plan.day_no }}"' in tpl
    rd = (ROOT / 'templates' / 'bible_reading_day.html').read_text(encoding='utf-8')
    assert 'href="/diary?day={{ day.day_no }}"' in rd
