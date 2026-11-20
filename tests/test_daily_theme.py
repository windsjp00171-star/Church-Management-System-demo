"""首頁今日經文卡的顏色：每人每天固定，而且連續兩天一定不同色、每種顏色都輪得到。"""
import importlib
import sys
import types
from datetime import date, timedelta

import pytest


@pytest.fixture
def event(monkeypatch):
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=None))
    monkeypatch.delitem(sys.modules, 'routes.event', raising=False)
    return importlib.import_module('routes.event')


def _days(n):
    return [(date(2026, 1, 1) + timedelta(days=d)).isoformat() for d in range(n)]


@pytest.mark.parametrize('extra', [[], [{'name': '自訂底圖', 'image_url': 'x'}]])
def test_never_same_colour_two_days_in_a_row(event, extra):
    for uid in ('u1', 'guest', 'abc-123'):
        names = [event._pick_theme(uid, d, extra)['name'] for d in _days(800)]
        assert all(a != b for a, b in zip(names, names[1:]))
        assert set(names) == {t['name'] for t in event.VERSE_THEMES + extra}


def test_same_person_same_day_is_stable(event):
    assert event._pick_theme('u1', '2026-11-20') == event._pick_theme('u1', '2026-11-20')


def test_single_theme_pool(event, monkeypatch):
    monkeypatch.setattr(event, 'VERSE_THEMES', [{'name': '唯一'}])
    assert event._pick_theme('u1', '2026-11-20')['name'] == '唯一'
