"""後台活動表單：用真的 Chromium 操作一遍（加欄位、選型別、填價格列、開自動判定、預覽、送出）

掃原始碼看得到「有沒有寫這個函式」，看不到「按下去之後存進去的東西對不對」。
這一條走完整條路：價格列 → 隱藏的 .f-options → 送出的 payload；預覽跑的是報名者那一份 JS
（填生日 → 真的打 /admin/events/preview-tier → 監護人欄位依年齡出現／消失）。

沒有 node／playwright／Chromium 時略過（不是失敗）。
"""
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which('node')
HAVE = bool(NODE) and subprocess.run([NODE, '-e', "require('playwright')"], capture_output=True).returncode == 0

SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const [base, outPath] = process.argv.slice(2);
  const b = await chromium.launch(); const pg = await b.newPage();
  const out = { errors: [], dialogs: [] }; let payload = null;
  pg.on('pageerror', e => { if (!/flatpickr/.test(e.message)) out.errors.push(e.message); });
  pg.on('dialog', d => { out.dialogs.push(d.message()); d.dismiss(); });
  await pg.route('**/*', route => {
    const u = route.request().url();
    if (!u.startsWith(base)) return route.abort();                    // 外部 CDN 一律不連
    if (route.request().method() === 'POST' && u.endsWith('/admin/events/new')) {
      payload = JSON.parse(route.request().postData());
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true,"event_id":"x"}' });
    }
    return route.continue();
  });
  await pg.goto(base + '/admin/events/new');
  await pg.evaluate(() => {
    document.getElementById('title').value = 'T';
    for (let i = 0; i < 4; i++) addField();
    const rows = [...document.querySelectorAll('.field-row')];
    const set = (r, label, type, req) => {
      r.querySelector('.f-label').value = label; const s = r.querySelector('.f-type'); s.value = type;
      s.dispatchEvent(new Event('change', { bubbles: true })); r.querySelector('.f-required').checked = !!req;
    };
    set(rows[0], '生日', 'birthday', true); set(rows[1], '身分別', 'fee', true);
    set(rows[2], '監護人', 'guardian', true); set(rows[3], '證號', 'id_number', false);
    addOptionRow(rows[1]); addOptionRow(rows[1]);
    const o = rows[1].querySelectorAll('.opt-row');
    const fill = (r, a, c) => { const ins = r.querySelectorAll('input'); ins[0].value = a; ins[1].value = c; ins[0].dispatchEvent(new Event('input', { bubbles: true })); };
    fill(o[0], '成人', '800'); fill(o[1], '孩童', '500');
    const cb = rows[1].querySelector('.f-auto-tier'); cb.checked = true; toggleAutoTier(cb);
  });
  out.options = await pg.evaluate(() => document.querySelectorAll('.field-row')[1].querySelector('.f-options').value);
  await pg.evaluate(() => openPreview());
  out.preview = await pg.evaluate(() => ({
    roc: !!document.querySelector('#preview-fields .roc-date'), gd: !!document.querySelector('#preview-fields .guardian-field'),
    at: !!document.querySelector('#preview-fields .auto-tier'), idn: !!document.querySelector('#preview-fields .id-input'),
    radios: document.querySelectorAll('#preview-fields input[type=radio]').length }));
  const gd = () => pg.evaluate(() => [...document.querySelectorAll('#preview-fields .field-wrapper')][2].style.display);
  out.guardian_before_birthday = await gd();
  const bday = async (y) => { await pg.fill('#preview-fields .roc-y', y); await pg.fill('#preview-fields .roc-m', '3'); await pg.fill('#preview-fields .roc-d', '5'); await pg.waitForTimeout(1500); };
  await bday('80');  out.guardian_adult = await gd();
  out.tier_note = await pg.evaluate(() => document.querySelector('#preview-fields .at-note').textContent);
  await bday('112'); out.guardian_minor = await gd();
  await pg.evaluate(() => closePreview());
  await pg.evaluate(() => submitForm(document.querySelector('button[onclick^="submitForm"]')));
  await pg.waitForTimeout(400);
  out.payload = payload;
  // 監護人必填、生日不必填 → 規則可以被繞過，存檔要被擋下來
  await pg.goto(base + '/admin/events/new');          // 上一次送出成功會換頁，重開一份
  await pg.evaluate(() => {
    document.getElementById('title').value = 'T'; addField(); addField();
    const rows = [...document.querySelectorAll('.field-row')];
    rows[0].querySelector('.f-label').value = '生日'; rows[0].querySelector('.f-type').value = 'birthday';
    rows[1].querySelector('.f-label').value = '監護人'; rows[1].querySelector('.f-type').value = 'guardian';
    rows[1].querySelector('.f-required').checked = true;     // 生日沒勾必填
  });
  // 開候補但沒填人數上限 → 即時提示要出現在候補那一格旁邊（dep-hints.js 打 /admin/events/check-deps）
  await pg.evaluate(() => { const w = document.getElementById('waitlist_enabled'); w.checked = true; w.dispatchEvent(new Event('change', { bubbles: true })); });
  await pg.waitForTimeout(1200);
  out.dep_hint = await pg.evaluate(() => document.querySelector('.dep-hint[data-dep="waitlist_needs_capacity"]').textContent);
  payload = null; out.dialogs.length = 0;
  await pg.evaluate(() => submitForm(document.querySelector('button[onclick^="submitForm"]')));
  await pg.waitForTimeout(400);
  out.blocked = { payload: payload, dialogs: out.dialogs.slice() };
  require('fs').writeFileSync(outPath, JSON.stringify(out));
  await b.close();
})();
"""


@pytest.fixture(scope='module')
def result(tmp_path_factory):
    if not HAVE:
        pytest.skip('沒有 node／playwright／Chromium')
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    srv = subprocess.Popen([sys.executable, str(ROOT / 'tests' / 'editor_server.py'), str(port)], cwd=str(ROOT),
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        assert srv.stdout.readline().strip() == 'READY'
        time.sleep(0.3)
        d = tmp_path_factory.mktemp('editor')
        (d / 'run.js').write_text(SCRIPT, encoding='utf-8')
        out = d / 'out.json'
        p = subprocess.run([NODE, str(d / 'run.js'), f'http://127.0.0.1:{port}', str(out)],
                           capture_output=True, text=True, timeout=120, env={**__import__('os').environ,
                           'NODE_PATH': subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()})
        assert out.exists(), p.stderr[-1500:]
        return json.loads(out.read_text(encoding='utf-8'))
    finally:
        srv.kill()


def test_no_script_errors(result):
    assert result['errors'] == []


def test_price_rows_become_the_storage_format(result):
    assert result['options'] == '成人|800\n孩童|500'


def test_preview_draws_every_new_type_with_the_real_markup(result):
    assert result['preview'] == {'roc': True, 'gd': True, 'at': True, 'idn': True, 'radios': 0}, \
        '開了自動判定的收費欄位不該在預覽裡列出選項讓人選（radios 應為 0）'


def test_preview_runs_the_real_age_condition(result):
    """生日沒填 → 藏；成人 → 藏；兒童 → 出現。年齡是伺服器算的（/compute-age），預覽跑同一支。"""
    assert result['guardian_before_birthday'] == 'none'
    assert result['guardian_adult'] == 'none'
    assert result['guardian_minor'] == 'block'


def test_preview_tier_comes_from_the_server(result):
    assert '歲' in result['tier_note']       # 「算出來是 N 歲…」是 /admin/events/preview-tier 回的


def test_the_payload_carries_everything_the_server_needs(result):
    f = {x['label']: x for x in result['payload']['fields']}
    assert [x['field_type'] for x in result['payload']['fields']] == ['birthday', 'fee', 'guardian', 'id_number']
    assert f['身分別']['options'] == '成人|800\n孩童|500'
    assert f['身分別']['auto_tier']['enabled'] is True
    cond = json.loads(f['監護人']['condition_json'])
    assert cond['op'] == 'age_between' and cond['max'] == 17 and cond['trigger_sort_order'] == 0


def test_a_required_guardian_with_an_optional_birthday_is_blocked_before_saving(result):
    assert result['blocked']['payload'] is None
    assert any('不是必填' in d for d in result['blocked']['dialogs'])


def test_the_live_dependency_hint_shows_next_to_the_setting(result):
    assert '人數上限' in result['dep_hint']
