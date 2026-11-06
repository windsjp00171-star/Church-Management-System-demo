"""手冊／導覽／教學：關掉的模組，說明也要整塊消失（不能讓人照著說明去點一個 404）。"""
import json
import re
import sys
from pathlib import Path

import jinja2
import pytest

ROOT = Path(__file__).resolve().parent.parent
MANUAL = (ROOT / 'templates' / 'manual.html').read_text(encoding='utf-8')
PATHLESS = {'每週週報': 'bulletins', '聚會人數回報': 'cell_report', '現場簽到': 'events', '系統更新通知': 'changelogs'}


_DB_BOUND = ('routes.modules', 'settings_store', 'routes.guide', 'routes.tutorial', 'routes.admin',
             'routes.audit', 'routes.decorators')


@pytest.fixture
def mod(fake_db):
    for m in _DB_BOUND:
        sys.modules.pop(m, None)
    import routes.modules as m
    m.bust()
    yield m
    for name in _DB_BOUND:          # 這些在載入時綁住了這一輪的假資料庫，別留給下一個測試用
        sys.modules.pop(name, None)


def _off(fake_db, mod, *keys):
    fake_db.tables['settings'] = [{'key': 'modules_state', 'value': json.dumps({k: False for k in keys})}]
    mod.bust()


def _render_manual(mod):
    env = jinja2.Environment(loader=jinja2.ChoiceLoader([
        jinja2.DictLoader({'base.html': '{% block title %}{% endblock %}{% block extra_css %}{% endblock %}'
                                        '{% block content %}{% endblock %}'}),
        jinja2.FileSystemLoader(str(ROOT / 'templates'))]))
    env.globals['module_on'] = mod.module_on
    return env.get_template('manual.html').render(user_roles=['member', 'admin'], from_path='')


def _blocks():
    """(標題, 路徑或None, 歸屬模組或None) —— 歸屬照登記表（手冊裡沒有路徑的用 PATHLESS）。"""
    import routes.modules as m
    out = []
    for mt in re.finditer(r'<div class="feature-block">', MANUAL):
        start, depth = mt.start(), 0
        for t in re.finditer(r'<div\b|</div>', MANUAL[start:]):
            depth += 1 if t.group() != '</div>' else -1
            if depth == 0:
                blk = MANUAL[start:start + t.end()]
                break
        h = re.search(r'<h3>(.*?)</h3>', blk, re.S)
        if not h:
            continue
        title = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', h.group(1).split('<span')[0])).strip()
        pm = re.search(r'badge-gray[^>]*>(/[^<]*)<', blk)
        key = m.classify(pm.group(1)) if pm else None
        for k, v in PATHLESS.items():
            if k in title:
                key = v
        out.append((title, pm.group(1) if pm else None, key))
    return out


def test_every_block_of_an_optional_module_is_wrapped(mod):
    for title, path, key in _blocks():
        if key:
            assert f"{{% if module_on('{key}') %}}" in MANUAL, (title, key)


@pytest.mark.parametrize('key', [m for m in ('events', 'courses', 'diary', 'prayer', 'calendar', 'bulletins',
                                              'gospel', 'cell_report', 'staff_leave', 'changelogs')])
def test_manual_drops_the_blocks_of_a_disabled_module(mod, fake_db, key):
    full = _render_manual(mod)
    _off(fake_db, mod, key)
    html = _render_manual(mod)
    blocks = _blocks()
    mine = [b for b in blocks if b[2] == key]
    assert mine, key
    for title, path, _ in mine:
        assert title in full, title                                  # 全開時在
        assert title not in html, (key, title)                       # 關掉就不在
    for title, path, k in blocks:
        if k and k != key and title not in {t for t, _, kk in mine}:
            assert title in html, (key, title)                       # 沒關的不受影響


def test_leader_section_and_its_nav_pill_go_with_cell_report(mod, fake_db):
    assert 'id="leader"' in _render_manual(mod)
    _off(fake_db, mod, 'cell_report')
    html = _render_manual(mod)
    assert 'id="leader"' not in html and 'href="#leader"' not in html
    for sid in ('member', 'staff', 'pastor', 'admin', 'qa'):
        assert f'id="{sid}"' in html                                   # 其他區塊沒被牽連（結構沒被弄壞）


def test_everything_on_renders_every_block(mod):
    html = _render_manual(mod)
    assert html.count('class="feature-block"') == MANUAL.count('<div class="feature-block">')


def _steps(mod):
    from flask import Flask
    import routes.guide as g
    import routes.tutorial as t
    app = Flask(__name__)
    app.secret_key = 'x'
    with app.test_request_context():
        from flask import session
        session.update(user_id='u', is_admin=True, is_super_admin=True)
        return g._front_steps() + g._admin_steps(), t._build_lessons()


@pytest.mark.parametrize('key', ['events', 'courses', 'diary', 'prayer', 'calendar', 'bulletins', 'gospel',
                                  'cell_report', 'devotional', 'staff_leave', 'verses', 'discussions',
                                  'announcements', 'payments'])
def test_guide_and_tutorial_drop_every_step_of_a_disabled_module(mod, fake_db, key):
    full_g, full_t = _steps(mod)
    assert any(mod.classify(s['url']) == key for s in full_g), key       # 全開時真的有這個模組的步驟
    _off(fake_db, mod, key)
    g, t = _steps(mod)
    assert not [s['url'] for s in g if mod.classify(s['url']) == key]
    assert not [s['url'] for s in t if mod.classify(s['url']) == key]
    assert len(g) < len(full_g) and len(t) < len(full_t)
