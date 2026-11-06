"""檔案分享：密碼不可以被「分享連結」「搜尋」「直接開網址」繞過；資料夾可見性只有一份判定。"""
import importlib
import os
import sys
import types

import bcrypt
import pytest

from fake_supabase import FakeSupabase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PW = bcrypt.hashpw(b'secret', bcrypt.gensalt()).decode()


def _db():
    return FakeSupabase(
        files=[
            {'id': 'f-plain', 'name': 'a.pdf', 'file_key': 'k1', 'owner_id': 'owner', 'visibility': 'public',
             'folder_id': None, 'protection': 'none'},
            {'id': 'f-pw', 'name': 'b.pdf', 'file_key': 'k2', 'owner_id': 'owner', 'visibility': 'public',
             'folder_id': None, 'protection': 'password', 'password_hash': PW},
            {'id': 'f-nohash', 'name': 'c.pdf', 'file_key': 'k3', 'owner_id': 'owner', 'visibility': 'public',
             'folder_id': None, 'protection': 'password', 'password_hash': None},
            {'id': 'f-in-locked', 'name': 'secretdoc.pdf', 'file_key': 'k4', 'owner_id': 'owner',
             'visibility': 'public', 'folder_id': 'fo-locked', 'protection': 'none'},
            {'id': 'f-private', 'name': 'p.pdf', 'file_key': 'k5', 'owner_id': 'owner', 'visibility': 'private',
             'folder_id': None, 'protection': 'password', 'password_hash': PW},
        ],
        folders=[
            {'id': 'fo-locked', 'name': '鎖住的', 'parent_id': None, 'visibility': 'public', 'created_by': 'owner',
             'protection': 'password', 'password_hash': PW},
            {'id': 'fo-users', 'name': '指定人', 'parent_id': None, 'visibility': 'users', 'created_by': 'owner',
             'allowed_users': ['me'], 'protection': 'none'},
            {'id': 'fo-hidden', 'name': '別人的', 'parent_id': None, 'visibility': 'private', 'created_by': 'owner',
             'protection': 'none'},
        ],
        users=[], groups=[],
    )


@pytest.fixture
def env(monkeypatch):
    db = _db()
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(supabase=db))
    for n in ('routes.files', 'routes.notifications', 'storage'):
        sys.modules.pop(n, None)
    from flask import Blueprint, Flask
    files = importlib.import_module('routes.files')
    seen = {}
    monkeypatch.setattr(files, 'render_template', lambda name, **kw: seen.update(name=name, **kw) or f'T:{name}')
    monkeypatch.setattr(files, 'get_presigned_url', lambda key, expires=0: f'https://r2/{key}')
    monkeypatch.setattr(files.http_requests, 'get', lambda *a, **k: types.SimpleNamespace(
        iter_content=lambda chunk_size=0: [b'x'], status_code=200))
    monkeypatch.setitem(sys.modules, 'storage', types.SimpleNamespace(
        r2_configured=lambda: True, get_presigned_url=files.get_presigned_url,
        upload_file=None, delete_file=None))
    app = Flask(__name__)
    app.secret_key = 't'
    auth = Blueprint('auth', __name__)
    auth.add_url_rule('/auth/login', 'login_page', lambda: 'login')
    app.register_blueprint(auth)
    app.register_blueprint(files.files_bp)
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(user_id='me', real_name='我')
    return types.SimpleNamespace(c=c, seen=seen, db=db, files=files)


def _unlock(env, key):
    with env.c.session_transaction() as s:
        s[key] = True


def test_share_link_refuses_a_locked_file_but_serves_an_unlocked_or_plain_one(env):
    r = env.c.post('/files/f-pw/share-link', data={'expires': '7d'})
    assert r.status_code == 403 and 'url' not in (r.get_json() or {})
    assert env.c.post('/files/f-plain/share-link').get_json()['url'] == 'https://r2/k1'
    _unlock(env, 'file_unlocked_f-pw')
    assert env.c.post('/files/f-pw/share-link').status_code == 200


def test_locked_file_cannot_be_viewed_streamed_or_downloaded_without_unlock(env):
    assert env.c.get('/files/f-pw/view').data == b'T:files/password_prompt.html'
    assert env.c.get('/files/f-pw/stream').status_code == 403
    assert env.c.get('/files/f-pw/download').status_code == 403


def test_unlock_with_missing_hash_or_wrong_password_never_500s_and_never_unlocks(env):
    for fid, pw in (('f-nohash', 'x'), ('f-pw', 'wrong')):
        r = env.c.post(f'/files/{fid}/unlock', data={'password': pw})
        assert r.status_code == 200 and env.seen['error'] == '密碼錯誤'
        with env.c.session_transaction() as s:
            assert not s.get(f'file_unlocked_{fid}')
    r = env.c.post('/files/f-pw/unlock', data={'password': 'secret'})
    assert r.status_code == 302


def test_cannot_try_passwords_on_a_file_you_may_not_see(env):
    assert env.c.post('/files/f-private/unlock', data={'password': 'secret'}).status_code == 403


def test_unlock_is_rate_limited_in_the_source():
    import re
    src = open(os.path.join(ROOT, 'routes', 'files.py'), encoding='utf-8').read()
    for fn in ('unlock_file', 'unlock_folder'):
        head = src[:src.index(f'def {fn}(')].rsplit('@files_bp.route', 1)[1]
        assert re.search(r"@limiter\.limit\(", head), fn


def test_locked_folder_shows_prompt_until_unlocked(env):
    r = env.c.get('/files?folder_id=fo-locked')
    assert env.seen['name'] == 'files/folder_password_prompt.html'
    env.seen.clear()
    _unlock(env, 'folder_unlocked_fo-locked')
    env.c.get('/files?folder_id=fo-locked')
    assert env.seen['name'] == 'files/index.html'


def test_files_in_a_locked_folder_cannot_be_reached_around_the_folder_password(env):
    assert env.c.get('/files/f-in-locked/view').status_code == 302
    assert env.c.get('/files/f-in-locked/download').status_code == 403
    assert env.c.get('/files/f-in-locked/stream').status_code == 403
    assert env.c.post('/files/f-in-locked/share-link').status_code == 403
    env.c.get('/files?q=secretdoc')
    assert env.seen['files'] == []
    _unlock(env, 'folder_unlocked_fo-locked')
    assert env.c.get('/files/f-in-locked/download').status_code == 302
    env.c.get('/files?q=secretdoc')
    assert [f['id'] for f in env.seen['files']] == ['f-in-locked']


def test_folder_creator_is_not_locked_out_of_own_folder(env):
    with env.c.session_transaction() as s:
        s['user_id'] = 'owner'
    env.c.get('/files?folder_id=fo-locked')
    assert env.seen['name'] == 'files/index.html'


def test_folder_listing_uses_the_one_visibility_rule(env):
    env.c.get('/files')
    names = {f['name'] for f in env.seen['folders']}
    assert '指定人' in names and '鎖住的' in names and '別人的' not in names


def test_cannot_enter_or_unlock_a_folder_you_may_not_see(env):
    assert env.c.get('/files?folder_id=fo-hidden').status_code == 403
    assert env.c.post('/folders/fo-hidden/unlock', data={'password': 'x'}).status_code == 403
