"""天父日記後台的權限併進後台權限矩陣（盤點第 7 步）

原本第三層是一張 `admin_whitelist` 表 —— 沒有任何畫面，只能用 SQL 改，跟權限矩陣做同一件事。
現在副標籤被授權「天父日記後台」（`diary`）的人進得去，其他人進不去。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _check(fake_db, monkeypatch, **sess):
    from flask import Flask, session
    import routes.diary as d
    monkeypatch.delenv('ADMIN_LINE_USER_IDS', raising=False)
    app = Flask(__name__); app.secret_key = 'x'
    with app.test_request_context():
        session.update(sess)
        return d._is_diary_admin('U-someone')


def test_matrix_grant_lets_a_sub_tag_member_in(fake_db, monkeypatch):
    assert _check(fake_db, monkeypatch, admin_modules=['diary']) is True
    assert _check(fake_db, monkeypatch, admin_modules=['events']) is False
    assert _check(fake_db, monkeypatch) is False
    assert _check(fake_db, monkeypatch, is_admin=True) is True


def test_the_matrix_knows_the_diary_admin_path(fake_db):
    from routes.permissions import module_for_path
    assert module_for_path('/diary/admin') == 'diary'
    assert module_for_path('/diary/admin/update_whitelist') == 'diary'
    assert module_for_path('/diary') is None                      # 前台日記不歸矩陣管


def test_the_old_whitelist_is_gone():
    src = (ROOT / 'routes' / 'diary.py').read_text(encoding='utf-8')
    assert "table('admin_whitelist')" not in src and '/diary/admin/admin_whitelist' not in src
