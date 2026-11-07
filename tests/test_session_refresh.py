"""權限撤銷要立即生效：每隔 PERM_RECHECK_SECONDS 回資料庫重算 session 的權限。"""
import re
import sys
from pathlib import Path

import pytest

import structure_scan as scan

ROOT = Path(__file__).resolve().parent.parent
USER = {'id': 'u1', 'line_user_id': 'L1', 'real_name': '王', 'is_admin': True, 'is_super_admin': False,
        'is_pastor': False, 'is_staff': True, 'is_blocked': False, 'group_tags': ['敬拜'],
        'member_type': 'member', 'role': 'approved'}


class Spy:
    """包住假資料庫：記下被讀了哪些表，並可指定某張表的讀取會炸。"""
    def __init__(self, fake):
        self.fake, self.reads, self.explode = fake, [], set()

    def table(self, name):
        self.reads.append(name)
        if name in self.explode:
            raise RuntimeError('db down: ' + name)
        return self.fake.table(name)

    def __getattr__(self, k):
        return getattr(self.fake, k)


@pytest.fixture
def env(fake_db, monkeypatch):
    for m in ('routes.auth', 'routes.permissions', 'routes.decorators'):
        sys.modules.pop(m, None)
    from flask import Flask
    import routes.auth as auth
    spy = Spy(fake_db)
    monkeypatch.setattr(auth, 'supabase', spy)
    sys.modules['db'].supabase = spy
    import routes.permissions as perm
    monkeypatch.setattr(perm, 'supabase', spy)
    monkeypatch.setattr(auth.Config, 'ADMIN_LINE_USER_IDS', [], raising=False)
    fake_db.tables['users'] = [dict(USER)]
    fake_db.tables['groups'] = [{'name': '敬拜', 'admin_modules': ['events']}]
    app = Flask(__name__)
    app.secret_key = 't'
    return app, auth, spy, fake_db


def stale_session(auth, **extra):
    """一個「登入很久以前」的 session。"""
    from flask import session
    session.clear()
    base = dict(user_id='u1', is_admin=True, is_staff=True, is_pastor=False, is_super_admin=False,
                admin_modules='*', group_tags=['敬拜'], cell_group_ids=[],
                _perm_checked_at=auth._now_ts() - auth.PERM_RECHECK_SECONDS - 1)
    session.update({**base, **extra})


def test_no_session_means_no_db_access(env):
    app, auth, spy, _ = env
    with app.test_request_context():
        assert auth.refresh_session_permissions() is False
    assert spy.reads == []


def test_inside_the_interval_does_not_touch_the_db(env):
    app, auth, spy, _ = env
    with app.test_request_context():
        from flask import session
        session.update(user_id='u1', _perm_checked_at=auth._now_ts())
        assert auth.refresh_session_permissions() is False
    assert spy.reads == []


def test_force_ignores_the_interval(env):
    app, auth, spy, _ = env
    with app.test_request_context():
        from flask import session
        session.update(user_id='u1', _perm_checked_at=auth._now_ts())
        auth.refresh_session_permissions(force=True)
    assert 'users' in spy.reads


def test_a_revoked_admin_loses_access_without_logging_in_again(env):
    app, auth, spy, fake = env
    fake.tables['users'] = [dict(USER, is_admin=False, is_staff=False)]
    with app.test_request_context():
        from flask import session
        stale_session(auth)
        assert auth.refresh_session_permissions() is False
        assert session['is_admin'] is False and session['is_staff'] is False
        assert session['admin_modules'] == ['events']                 # 變成只剩副標籤授權的模塊
        assert session['_perm_checked_at'] >= auth._now_ts() - 2


def test_revoking_a_matrix_grant_takes_effect(env):
    app, auth, spy, fake = env
    fake.tables['users'] = [dict(USER, is_admin=False)]
    fake.tables['groups'] = [{'name': '敬拜', 'admin_modules': []}]   # 超管在矩陣上把授權拿掉
    with app.test_request_context():
        from flask import session
        stale_session(auth, admin_modules=['events'])
        auth.refresh_session_permissions()
        assert session['admin_modules'] == []


def test_blocked_user_is_logged_out(env):
    app, auth, spy, fake = env
    fake.tables['users'] = [dict(USER, is_blocked=True)]
    with app.test_request_context():
        from flask import session
        stale_session(auth)
        assert auth.refresh_session_permissions() is True
        assert 'user_id' not in session


def test_deleted_user_is_logged_out(env):
    app, auth, spy, fake = env
    fake.tables['users'] = []
    with app.test_request_context():
        from flask import session
        stale_session(auth)
        assert auth.refresh_session_permissions() is True and not session.get('user_id')


def test_db_outage_keeps_the_session_and_does_not_advance_the_clock(env):
    """Supabase 抖一下不可以把全教會登出；而且下一個請求要再試。"""
    app, auth, spy, fake = env
    spy.explode = {'users'}
    with app.test_request_context():
        from flask import session
        stale_session(auth)
        before = session['_perm_checked_at']
        assert auth.refresh_session_permissions() is False
        assert session['user_id'] == 'u1' and session['is_admin'] is True
        assert session['_perm_checked_at'] == before


def test_partial_failure_never_leaves_a_half_updated_session(env):
    """旗標算完、小組查詢失敗時，整包都不更新（不能是旗標新、模塊舊）。"""
    app, auth, spy, fake = env
    fake.tables['users'] = [dict(USER, is_admin=False)]
    spy.explode = {'cell_group_leaders'}
    with app.test_request_context():
        from flask import session
        stale_session(auth)
        before = dict(session)
        auth.refresh_session_permissions()
        assert dict(session) == before


def test_unrelated_session_keys_survive(env):
    app, auth, spy, fake = env
    with app.test_request_context():
        from flask import session
        stale_session(auth, is_demo=True, _csrf_token='tok', next_url='/x')
        auth.refresh_session_permissions()
        assert session['is_demo'] is True and session['_csrf_token'] == 'tok' and session['next_url'] == '/x'


def test_env_defined_super_admins_stay_super_admins(env):
    app, auth, spy, fake = env
    auth.Config.ADMIN_LINE_USER_IDS = ['L1']
    fake.tables['users'] = [dict(USER, is_admin=False)]
    with app.test_request_context():
        from flask import session
        stale_session(auth)
        auth.refresh_session_permissions()
        assert session['is_super_admin'] is True and session['is_admin'] is True and session['admin_modules'] == '*'


def test_login_and_refresh_share_one_implementation(env):
    """登入寫進 session 的權限格，和重算寫的必須一模一樣。"""
    app, auth, spy, fake = env
    with app.test_request_context():
        from flask import session
        auth._populate_session(dict(USER))
        assert abs(session['_perm_checked_at'] - auth._now_ts()) <= 2     # 登入那一刻就是第一次檢查
        login_view = {k: session[k] for k in auth._permission_fields(dict(USER))}
        session['_perm_checked_at'] = 0
        auth.refresh_session_permissions()
        assert {k: session[k] for k in login_view} == login_view
        assert session['_perm_checked_at'] > 0


# ── 結構守衛 ───────────────────────────────────────────
def test_only_one_place_writes_the_permission_flags():
    src = scan.strip_py((ROOT / 'routes' / 'auth.py').read_text(encoding='utf-8'))
    assert len(re.findall(r"'is_super_admin':\s*bool\(", src)) == 1, '權限旗標只准在 _permission_fields 寫一份'
    assert "session['is_admin']" not in src


def test_refresh_runs_before_the_profile_gate_and_populate_marks_the_clock():
    app = scan.strip_py((ROOT / 'app.py').read_text(encoding='utf-8'))
    assert app.index('def refresh_permissions') < app.index('def force_profile_setup')
    assert '_perm_checked_at' in scan.strip_py((ROOT / 'routes' / 'auth.py').read_text(encoding='utf-8'))
