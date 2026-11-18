import pytest
from flask import Flask, session
from routes.decorators import login_required, admin_required


@pytest.fixture
def client():
    app = Flask(__name__)
    app.secret_key = 'x'
    from flask import Blueprint
    auth = Blueprint('auth', __name__)
    auth.add_url_rule('/login', 'login_page', lambda: 'login')
    app.register_blueprint(auth)

    app.add_url_rule('/page', 'page', admin_required(lambda: 'ok'))
    app.add_url_rule('/api/x', 'api', admin_required(lambda: 'ok'))
    app.add_url_rule('/me', 'me', login_required(lambda: 'ok'))
    return app.test_client()


def _login(c, **flags):
    with c.session_transaction() as s:
        s['user_id'] = 'u1'
        s.update(flags)


def test_anonymous_redirects_to_login(client):
    r = client.get('/page')
    assert r.status_code == 302 and '/login' in r.location


def test_anonymous_api_gets_401(client):
    assert client.get('/api/x').status_code == 401


def test_member_forbidden(client):
    _login(client)
    assert client.get('/page').status_code == 403
    assert client.get('/api/x').status_code == 403


@pytest.mark.parametrize('flag', ['is_admin', 'is_super_admin'])
def test_admin_and_super_admin_allowed(client, flag):
    _login(client, **{flag: True})
    assert client.get('/page').status_code == 200


def test_login_required_allows_member(client):
    _login(client)
    assert client.get('/me').status_code == 200
