"""內建排程：時間到了自己跑（Render 免費方案沒有 cron，靠進來的請求與 UptimeRobot 的 ping 當心跳）。"""
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    sys.modules['db'] = _m

from routes import quiet_hours, tasks

ROOT = Path(__file__).resolve().parent.parent
TW = timezone(timedelta(hours=8))


@pytest.fixture(autouse=True)
def _reset():
    tasks._last_run, tasks._running = None, False
    yield
    tasks._last_run, tasks._running = None, False


def test_the_jobs_are_registered():
    assert [n for n, _ in tasks.JOBS] == ['warm_bible_chapters', 'reading_nudge', 'close_expired_courses', 'fetch_sermons']


def test_one_failing_job_does_not_stop_the_others(monkeypatch):
    calls = []

    def boom():
        raise RuntimeError('x')
    monkeypatch.setattr(tasks, 'JOBS', [('a', boom), ('b', lambda: calls.append('b') or 'ok')])
    res = tasks.run_jobs()
    assert 'error' in res['a'] and calls == ['b']


def test_the_job_reaches_the_reading_nudge(monkeypatch):
    from routes import reading_nudge
    monkeypatch.setattr(reading_nudge, 'run', lambda: 'ran')
    assert dict(tasks.JOBS)['reading_nudge']() == 'ran'


def test_it_is_throttled_to_one_tick_per_interval(monkeypatch):
    started = []
    monkeypatch.setattr(tasks.threading, 'Thread',
                        lambda target, daemon: types.SimpleNamespace(start=lambda: started.append(1)))
    assert tasks.maybe_run_scheduled_tasks() is True
    tasks._running = False                       # 上一輪跑完了
    assert tasks.maybe_run_scheduled_tasks() is False, '15 分鐘內不可以再跑一次'
    assert len(started) == 1


def test_a_run_in_progress_is_not_started_twice(monkeypatch):
    monkeypatch.setattr(tasks.threading, 'Thread', lambda **k: types.SimpleNamespace(start=lambda: None))
    tasks._running = True
    assert tasks.maybe_run_scheduled_tasks() is False


@pytest.mark.parametrize('hour,ok', [(6, False), (7, True), (12, True), (20, True), (21, False), (0, False)])
def test_quiet_hours_are_21_to_7(hour, ok):
    assert quiet_hours.in_window(datetime(2026, 9, 12, hour, 5, tzinfo=TW)) is ok


def test_the_manual_trigger_needs_the_token(monkeypatch):
    from flask import Flask
    from config import Config
    app = Flask(__name__)
    app.register_blueprint(tasks.tasks_bp)
    c = app.test_client()
    monkeypatch.setattr(Config, 'TASK_TOKEN', '')
    assert c.get('/tasks/tick').status_code == 503
    monkeypatch.setattr(Config, 'TASK_TOKEN', 'secret')
    assert c.get('/tasks/tick').status_code == 403
    assert c.get('/tasks/tick?token=wrong').status_code == 403
    monkeypatch.setattr(tasks, 'JOBS', [])
    assert c.get('/tasks/tick?token=secret').status_code == 200


def test_the_app_really_wires_the_scheduler_up():
    """★ 寫好了但沒接上＝沒有做，而症狀是「推播從來沒響過」，畫面完全正常。
    先去掉註解再掃（註解裡就寫著這些字）。"""
    code = re.sub(r'(?m)#.*$', '', (ROOT / 'app.py').read_text(encoding='utf-8'))
    assert 'register_blueprint(tasks_bp)' in code
    body = code[code.index('def run_scheduled_tasks'):]
    body = body[:body.index('app.before_request(enforce_modules)')]
    assert 'maybe_run_scheduled_tasks()' in body
