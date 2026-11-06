"""個人日記匯出：只能匯出自己的、讀取失敗不給殘缺檔、超管匯出仍然不含日記。"""
import importlib
import os
import sys
import types

import pytest

from fake_supabase import FakeSupabase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _make(monkeypatch, db):
    from flask import Blueprint, Flask
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=db))
    for n in ('routes.diary', 'routes.audit'):
        sys.modules.pop(n, None)
    diary = importlib.import_module('routes.diary')
    app = Flask(__name__, template_folder=os.path.join(ROOT, 'templates'))
    app.secret_key = 't'
    auth = Blueprint('auth', __name__)
    auth.add_url_rule('/auth/login', 'login_page', lambda: 'login')
    app.register_blueprint(auth)
    app.register_blueprint(diary.diary_bp)
    return app, diary


def _rows():
    return {'diary_entries': (
        [{'line_user_id': 'U-me', 'entry_date': f'2026-01-{d:02d}', 'content': f'我的第{d}天', 'locked': True}
         for d in range(1, 4)]
        + [{'line_user_id': 'U-other', 'entry_date': '2026-01-01', 'content': '別人的秘密', 'locked': True}])}


def _login(c, line_id='U-me'):
    with c.session_transaction() as s:
        s.update(user_id='u1', real_name='小明', line_id=line_id)


def test_export_contains_only_my_entries(monkeypatch):
    app, _ = _make(monkeypatch, FakeSupabase(**_rows()))
    c = app.test_client(); _login(c)
    r = c.get('/diary/export')
    assert r.status_code == 200
    text = r.data.decode('utf-8-sig')
    assert '我的第1天' in text and '我的第3天' in text
    assert '別人的秘密' not in text
    assert 'attachment' in r.headers['Content-Disposition']
    assert r.headers['Cache-Control'] == 'no-store'


def test_export_ignores_any_parameter_naming_someone_else(monkeypatch):
    app, _ = _make(monkeypatch, FakeSupabase(**_rows()))
    c = app.test_client(); _login(c)
    r = c.get('/diary/export?line_user_id=U-other&uid=U-other')
    assert '別人的秘密' not in r.data.decode('utf-8-sig')


def test_export_requires_login(monkeypatch):
    app, _ = _make(monkeypatch, FakeSupabase(**_rows()))
    r = app.test_client().get('/diary/export')
    assert r.status_code == 302 and '/auth/login' in r.headers['Location']


def test_export_paginates_past_1000(monkeypatch):
    many = {'diary_entries': [{'line_user_id': 'U-me', 'entry_date': f'{2000 + i // 365}-{i % 12 + 1:02d}-{i % 28 + 1:02d}#{i}',
                               'content': f'c{i}'} for i in range(1205)]}
    _, diary = _make(monkeypatch, FakeSupabase(**many))
    assert len(diary.export_own_entries('U-me')) == 1205


def test_read_failure_gives_no_file(monkeypatch):
    class Boom(FakeSupabase):
        def table(self, name):
            if name == 'diary_entries':
                raise RuntimeError('db down')
            return super().table(name)
    app, _ = _make(monkeypatch, Boom())
    c = app.test_client(); _login(c)
    r = c.get('/diary/export')
    assert r.status_code == 302 and 'attachment' not in r.headers.get('Content-Disposition', '')


def test_audit_records_count_not_content(monkeypatch):
    db = FakeSupabase(**_rows())
    app, _ = _make(monkeypatch, db)
    c = app.test_client(); _login(c)
    c.get('/diary/export')
    logged = [w for w in db.log if w[0] == 'insert' and w[1] == 'audit_logs']
    assert logged and logged[0][2][0]['action'] == 'diary.export_self'
    assert logged[0][2][0]['detail'] == {'entries': 3}


def test_superadmin_export_still_excludes_diary():
    import backup_registry as reg
    assert 'diary_entries' in reg.EXCLUDED and 'diary_entries' not in reg.TABLE_NAMES
