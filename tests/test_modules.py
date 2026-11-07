"""功能模組登記表：關掉一個選配模組，它的網址、首頁入口、後台入口要整塊消失；核心永遠開著。"""
import json
import re
import sys
from pathlib import Path

import pytest

import structure_scan as scan

ROOT = Path(__file__).resolve().parent.parent

#  這些路徑**刻意**不屬於任何選配模組（核心：人、登入、權限、稽核、通知、備份、首頁與後台外殼、說明）。
#  新增的路由若不屬於任何模組、也不在這裡，測試會紅 —— 逼人表態：它是核心，還是某個選配模組？
CORE_PREFIXES = [
    '/', '/health', '/healthz', '/ping', '/robots.txt', '/manifest.json',
    '/auth', '/profile', '/onboarding', '/setup-wizard', '/manual', '/product-spec', '/guide', '/tutorial',
    '/staff', '/api/notifications', '/api/push', '/sw.js',
    '/admin', '/admin/api',                                   # 後台首頁與跨模組共用的 API（使用者、標籤、白名單、上傳）
    '/admin/permissions', '/admin/modules', '/admin/backup', '/admin/data-export', '/admin/data-import',
    '/admin/users', '/admin/groups', '/admin/logs',
    '/admin/portal-links', '/admin/portal-cards', '/admin/portal-card-settings',
]


@pytest.fixture
def mod(fake_db):
    for m in ('routes.modules', 'routes.decorators', 'routes.audit', 'settings_store'):
        sys.modules.pop(m, None)      # 這些在載入時就綁定了 db，要跟著這一輪的假資料庫重新載入
    import routes.modules as m
    m.bust()
    return m


def _state(fake, **kw):
    fake.tables['settings'] = [{'key': 'modules_state', 'value': json.dumps(kw)}]


# ── 登記表本身 ─────────────────────────────────────────
def test_registry_is_consistent(mod):
    keys = [m.key for m in mod.MODULES]
    assert len(keys) == len(set(keys))
    prefixes = [p for m in mod.MODULES for p in m.prefixes]
    assert len(prefixes) == len(set(prefixes)), '同一個前綴不可登記給兩個模組'
    for m in mod.MODULES:
        assert m.kind in ('optional', 'demo_only') and m.prefixes and m.desc, m.key
        for r in m.requires:
            assert r in mod.BY_KEY and mod.BY_KEY[r].kind == 'optional', f'{m.key} 依賴了不存在或不可開關的 {r}'


def test_no_dependency_cycles(mod):
    def walk(key, seen):
        assert key not in seen, f'依賴循環：{seen + [key]}'
        for r in mod.BY_KEY[key].requires:
            walk(r, seen + [key])
    for m in mod.MODULES:
        walk(m.key, [])


@pytest.mark.parametrize('path,key', [
    ('/', None), ('/auth/login', None), ('/profile', None), ('/admin', None), ('/admin/permissions', None),
    ('/admin/backup/export-all', None), ('/admin/users', None), ('/api/notifications', None),
    ('/events', 'events'), ('/event/5/register', 'events'), ('/checkin/abc', 'events'), ('/my-history', 'events'),
    ('/admin/events/1/registrations', 'events'),
    ('/events/1/registrations/2/pay', 'payments'), ('/payment/ecpay/return', 'payments'),   # 萬用段：同樣開頭但屬於金流
    ('/admin/payments', 'payments'),
    ('/cell-report/portal', 'cell_report'), ('/admin/api/cell-groups/3/leaders', 'cell_report'),
    ('/roll-call/session/1', 'roll_call'), ('/api/admin/roll-call/rules', 'roll_call'),
    ('/diary/admin', 'diary'), ('/api/diary/x', 'diary'),
    ('/staff-leave', 'staff_leave'), ('/attendance', 'staff_leave'),
    ('/admin/modules', None), ('/admin/api/files/set-limit', 'files'),
    ('/auth/demo-login/admin', 'demo'), ('/admin/contact-leads', 'demo'),
    ('/eventsx', None), ('/diaryx', None),                    # 前綴要整段比對，不是字串開頭
])
def test_classify(mod, path, key):
    assert mod.classify(path) == key


def test_every_route_is_a_module_or_an_explicit_core_path(mod):
    """新增的路由不屬於任何模組、也不在核心清單 → 紅。逼人表態，不會悄悄變成「關不掉的功能」。"""
    def core(path):
        segs = [s for s in path.strip('/').split('/') if s]
        return any(len(segs) == len([x for x in c.strip('/').split('/') if x])
                   and segs == [x for x in c.strip('/').split('/') if x]
                   or (c not in ('/', '/admin', '/admin/api') and segs[:len([x for x in c.strip('/').split('/') if x])]
                       == [x for x in c.strip('/').split('/') if x])
                   or (c in ('/admin', '/admin/api') and (segs == [x for x in c.strip('/').split('/') if x]
                       or (c == '/admin/api' and segs[:2] == ['admin', 'api'])))
                   for c in CORE_PREFIXES)
    loose = [(f, p) for f, p in scan.all_route_paths() if mod.classify(p) is None and not core(p)]
    assert loose == [], f'沒有歸屬的路由（要登記進 MODULES，或明確列為核心）：{sorted(loose)}'


def test_core_list_matches_reality_so_it_cannot_rot(mod):
    """核心清單裡的每一條，都至少對應一條真的存在的、且不屬於任何選配模組的路由。"""
    routes = {p for _, p in scan.all_route_paths()}
    for c in CORE_PREFIXES:
        segs = [s for s in c.strip('/').split('/') if s]
        hit = [p for p in routes if [s for s in p.strip('/').split('/') if s][:len(segs)] == segs]
        assert hit, f'核心清單有一條已經沒有對應的路由：{c}'
        assert any(mod.classify(p) is None for p in hit), f'核心清單的 {c} 底下的路由其實都已屬於選配模組'


# ── 開關與依賴 ─────────────────────────────────────────
def test_everything_is_on_by_default_except_demo(mod, fake_db, monkeypatch):
    monkeypatch.setattr(mod.Config, 'DEMO_MODE', False, raising=False)
    for m in mod.MODULES:
        assert mod.is_enabled(m.key) is (m.kind == 'optional'), m.key


def test_demo_module_follows_demo_mode_not_the_database(mod, fake_db, monkeypatch):
    _state(fake_db, demo=False)
    monkeypatch.setattr(mod.Config, 'DEMO_MODE', True, raising=False)
    assert mod.is_enabled('demo') is True
    monkeypatch.setattr(mod.Config, 'DEMO_MODE', False, raising=False)
    assert mod.is_enabled('demo') is False


def test_disabled_module_and_its_dependents_are_off(mod, fake_db):
    _state(fake_db, events=False)
    assert not mod.is_enabled('events')
    assert not mod.is_enabled('payments'), '依賴被關掉，它也要跟著不存在'
    assert mod.is_enabled('diary')


def test_core_is_never_off(mod, fake_db):
    _state(fake_db, **{m.key: False for m in mod.MODULES})
    assert mod.is_path_enabled('/') and mod.is_path_enabled('/auth/login') and mod.is_path_enabled('/admin/permissions')
    assert mod.module_on('/admin/modules') and mod.module_on('/profile')


def test_unreadable_settings_fall_back_to_defaults(mod, fake_db):
    class Boom:
        def table(self, *_):
            raise RuntimeError('db down')
    sys.modules['db'].supabase = Boom()
    for m in ('routes.modules', 'settings_store'):
        sys.modules.pop(m, None)
    import routes.modules as m2
    m2.bust()
    assert m2.is_enabled('diary')          # 連不上時維持預設（開），不讓整站因為讀不到開關而壞掉


def test_module_on_helper(mod, fake_db):
    _state(fake_db, diary=False)
    assert mod.module_on('diary') is False and mod.module_on('/diary') is False
    assert mod.module_on('/events') is True and mod.module_on('/anything') is True and mod.module_on(None) is True


# ── 網址攔截 ───────────────────────────────────────────
@pytest.fixture
def app(mod, fake_db):
    from flask import Flask, Blueprint
    app = Flask(__name__)
    app.secret_key = 't'
    bp = Blueprint('t', __name__)
    for path in ('/', '/diary', '/diary/admin', '/events', '/api/diary/x', '/auth/login', '/static/x.js'):
        bp.add_url_rule(path, 'ep' + re.sub(r'\W', '_', path), lambda: 'ok')
    app.register_blueprint(bp)
    app.before_request(mod.enforce_modules)
    return app


def test_disabled_module_urls_404_and_everything_else_works(mod, fake_db, app):
    _state(fake_db, diary=False)
    mod.bust()
    c = app.test_client()
    for path in ('/diary', '/diary/admin', '/api/diary/x'):
        assert c.get(path).status_code == 404, path
    for path in ('/', '/events', '/auth/login'):
        assert c.get(path).status_code == 200, path


def test_enabling_it_again_brings_it_back(mod, fake_db, app):
    c = app.test_client()
    _state(fake_db, diary=False); mod.bust()
    assert c.get('/diary').status_code == 404
    _state(fake_db, diary=True); mod.bust()
    assert c.get('/diary').status_code == 200


# ── 後台儲存（僅超管）────────────────────────────────────
@pytest.fixture
def editor(mod, fake_db):
    from flask import Flask, Blueprint
    app = Flask(__name__)
    app.secret_key = 't'
    auth = Blueprint('auth', __name__)
    auth.add_url_rule('/auth/login', 'login_page', lambda: 'login')
    app.register_blueprint(auth)
    app.register_blueprint(mod.modules_bp)

    def make(**flags):
        c = app.test_client()
        with c.session_transaction() as s:
            s.update(user_id='u1', real_name='超管', **flags)
        return c
    return make, fake_db


def _saved(fake):
    w = [x for x in fake.writes if x[0] == 'settings']
    return json.loads(w[-1][2]['value']) if w else None


def test_only_super_admin_can_change_modules(editor):
    make, fake = editor
    for flags in ({'is_admin': True}, {'admin_modules': ['settings']}, {}):
        assert make(**flags).post('/admin/modules/save', json={'modules': {'diary': False}}).status_code in (302, 401, 403)
    assert _saved(fake) is None


def test_save_writes_settings_and_audits(editor, mod):
    make, fake = editor
    r = make(is_super_admin=True).post('/admin/modules/save', json={'modules': {'diary': False, 'prayer': True}})
    assert r.status_code == 200 and r.get_json()['data']['disabled'] == ['diary']
    saved = _saved(fake)                 # 儲存時把「目前實際生效的狀態」一起寫下，沒提到的模組維持原樣
    assert saved['diary'] is False and saved['prayer'] is True
    assert set(saved) == {m.key for m in mod.MODULES if m.kind == 'optional'}
    assert all(v for k, v in saved.items() if k != 'diary')
    assert any(w[0] == 'audit_logs' and w[2]['action'] == 'module.update' for w in fake.writes)


def test_save_takes_effect_immediately_not_after_the_cache_expires(editor, mod):
    make, fake = editor
    assert mod.is_enabled('diary')                               # 先把快取暖起來
    make(is_super_admin=True).post('/admin/modules/save', json={'modules': {'diary': False}})
    fake.tables['settings'] = [{'key': 'modules_state', 'value': json.dumps({'diary': False})}]
    assert not mod.is_enabled('diary')


@pytest.mark.parametrize('body,needle', [
    ({'events': False, 'payments': True}, '需要先開啟'),               # 依賴沒滿足
    ({'demo': False}, 'DEMO_MODE'),                                    # 展示站功能不能在這裡開關
    ({'no_such_module': True}, '不認得'),
    ({'diary': 'x', 'bogus': 1}, '不認得'),
])
def test_save_rejects_bad_input_and_writes_nothing(editor, body, needle):
    make, fake = editor
    r = make(is_super_admin=True).post('/admin/modules/save', json={'modules': body})
    assert r.status_code == 400 and needle in r.get_json()['error'] and _saved(fake) is None


def test_save_rejects_non_dict(editor):
    make, fake = editor
    assert make(is_super_admin=True).post('/admin/modules/save', json={'modules': ['diary']}).status_code == 400


def test_turning_off_a_required_module_together_with_its_dependent_is_fine(editor):
    make, fake = editor
    r = make(is_super_admin=True).post('/admin/modules/save', json={'modules': {'events': False, 'payments': False}})
    assert r.status_code == 200


# ── 模板：指向選配模組的入口一律要有開關守著 ─────────────────
LINK = re.compile(r'<a\b[^>]*?\bhref="(/[^"]*)"')
GUARDED_TEMPLATES = ['templates/portal.html', 'templates/staff/index.html', 'templates/admin/index.html']


@pytest.mark.parametrize('rel', GUARDED_TEMPLATES)
def test_links_to_optional_modules_are_guarded(mod, rel):
    text = (ROOT / rel).read_text(encoding='utf-8')
    unguarded = []
    for m in LINK.finditer(text):
        path = re.sub(r'\{\{.*?\}\}', 'x', m.group(1)).split('?')[0]
        if mod.classify(path) is None:
            continue
        before = text[max(0, m.start() - 160):m.start()]
        if 'module_on(' not in before and 'can_see(' not in before:
            unguarded.append(path)
    assert not unguarded, f'{rel} 有指向選配模組、但沒有開關守著的連結：{sorted(set(unguarded))}'


def test_templates_still_parse():
    import jinja2
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(ROOT / 'templates')))
    for rel in ('portal.html', 'staff/index.html', 'admin/index.html', 'admin/modules.html', 'admin/permissions.html'):
        env.get_template(rel)


def test_wiring_in_the_app_and_the_admin_pages(mod):
    app_src = scan.strip_py((ROOT / 'app.py').read_text(encoding='utf-8'))
    assert re.search(r'app\.before_request\(\s*enforce_modules\s*\)', app_src), '網址攔截沒有掛上'
    assert "globals['module_on']" in app_src and 'register_blueprint(modules_bp)' in app_src
    assert 'module_on' in scan.strip_py((ROOT / 'routes' / 'admin.py').read_text(encoding='utf-8'))
    assert 'module_on' in scan.strip_py((ROOT / 'routes' / 'permissions.py').read_text(encoding='utf-8'))


# ── 舊的 ENABLE_* 環境變數：只當預設值，後台表態後以後台為準 ───────────────
@pytest.mark.parametrize('var,key', [('ENABLE_COURSES', 'courses'), ('ENABLE_CALENDAR', 'calendar'),
                                     ('ENABLE_BULLETIN', 'bulletins'), ('ENABLE_PRAYER', 'prayer'),
                                     ('ENABLE_GOSPEL', 'gospel'), ('ENABLE_VISITOR_FORMS', 'visitor_forms')])
def test_old_env_switches_are_only_defaults(mod, fake_db, monkeypatch, var, key):
    assert mod.ENV_DEFAULTS[key] == var
    monkeypatch.setenv(var, 'false')
    mod.bust()
    assert mod.is_enabled(key) is False                          # 沒表態：照舊的環境變數
    _state(fake_db, **{key: True}); mod.bust()
    assert mod.is_enabled(key) is True                           # 後台表態：以後台為準
    _state(fake_db, **{key: False}); monkeypatch.setenv(var, 'true'); mod.bust()
    assert mod.is_enabled(key) is False


def test_old_env_switch_is_off_in_the_admin_page_and_the_dependency_check(mod, fake_db, monkeypatch):
    monkeypatch.setenv('ENABLE_COURSES', 'false'); mod.bust()
    assert mod.is_on_in_state('courses') is False and mod.is_on_in_state('diary') is True


def test_blueprints_are_always_registered_so_links_never_break():
    """舊做法：ENABLE_*=false 時整個藍圖不註冊，模板裡的 url_for 會直接爆。現在一律註冊，由登記表攔截。"""
    app_src = scan.strip_py((ROOT / 'app.py').read_text(encoding='utf-8'))
    assert 'Config.ENABLE_' not in app_src
    for bp in ('courses_bp', 'calendar_bp', 'bulletin_bp', 'prayer_bp', 'gospel_bp', 'visitor_forms_bp'):
        assert f'register_blueprint({bp})' in app_src and not re.search(rf'if [^\n]*:\s*\n\s*from[^\n]*\n\s*app\.register_blueprint\({bp}\)', app_src)


def test_nobody_reads_the_removed_config_flags():
    for f in scan.py_files():
        assert 'Config.ENABLE_' not in scan.strip_py(f.read_text(encoding='utf-8')), scan.rel(f)


def test_guide_and_tutorial_follow_the_registry(mod, fake_db, monkeypatch):
    for f in ('routes/guide.py', 'routes/tutorial.py'):
        assert 'is_enabled(' in scan.strip_py((ROOT / f).read_text(encoding='utf-8')), f


def test_setup_wizard_lists_the_registry_not_the_dead_env_block():
    tpl = (ROOT / 'templates' / 'setup_wizard' / 'index.html').read_text(encoding='utf-8')
    assert 'module_rows' in tpl and '/admin/modules' in tpl
    assert "('ENABLE_PRAYER', '代禱牆')" not in tpl
    assert 'module_rows' in scan.strip_py((ROOT / 'routes' / 'setup_wizard.py').read_text(encoding='utf-8'))


def test_setup_wizard_passes_the_current_module_state(mod, fake_db, monkeypatch):
    from flask import Flask
    sys.modules.pop('routes.setup_wizard', None)
    import routes.setup_wizard as wiz
    seen = {}
    monkeypatch.setattr(wiz, 'render_template', lambda name, **kw: seen.update(kw) or 'ok')
    monkeypatch.setattr(wiz.Config, 'SUPABASE_URL', None, raising=False)       # 尚未設定：精靈不要求登入
    _state(fake_db, diary=False); mod.bust()
    app = Flask(__name__)
    app.secret_key = 't'
    app.register_blueprint(wiz.setup_wizard_bp)
    assert app.test_client().get('/setup-wizard').status_code == 200
    rows = {r['label']: r for r in seen['module_rows']}
    assert rows['天父日記']['on'] is False and rows['代禱牆']['on'] is True
    assert '天父日記' in rows and rows['檔案分享']['needs'] and rows['天父日記']['needs']
    assert all(r['label'] != mod.BY_KEY['demo'].label for r in seen['module_rows'])    # 展示站專用的不給教會選
