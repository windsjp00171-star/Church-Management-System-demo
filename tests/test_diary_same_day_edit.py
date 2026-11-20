"""天父日記：當天寫的當天都能改，過了那一天才鎖定（以前一存就永遠鎖死，錯字都不能修）。"""
import importlib
import sys
import types

import pytest


@pytest.fixture
def diary(monkeypatch, fake_db):
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=fake_db))
    for n in ('routes.diary', 'routes.audit'):
        sys.modules.pop(n, None)
    mod = importlib.import_module('routes.diary')
    monkeypatch.setattr(mod, '_today_str', lambda: '2026-11-18')
    return mod


def _entry(day):
    return [{'line_user_id': 'U1', 'entry_date': day, 'content': '舊的', 'locked': True}]


def test_todays_saved_entry_can_still_be_updated(diary, fake_db):
    fake_db.tables['diary_entries'] = _entry('2026-11-18')
    diary.sb_save_entry('U1', '2026-11-18', '改過錯字')
    assert ('diary_entries', 'update') in [(t, op) for t, op, _ in fake_db.writes]
    payload = [p for t, op, p in fake_db.writes if op == 'update'][0]
    assert payload['content'] == '改過錯字' and payload['locked'] is True


def test_past_saved_entry_stays_locked(diary, fake_db):
    fake_db.tables['diary_entries'] = _entry('2026-11-17')
    diary.sb_save_entry('U1', '2026-11-17', '想偷改')
    assert fake_db.writes == []
