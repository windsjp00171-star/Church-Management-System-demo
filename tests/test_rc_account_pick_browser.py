"""「是不是同一個人？」的選擇框：用真的 Chromium（手機尺寸）點，確認每顆按鈕回傳的東西對，而且按鈕夠大、不超出畫面。

以前是一連串瀏覽器的「確定／取消」框：看不出「確定」是哪個意思，按錯了回不去。
沒有 node／playwright／Chromium 時略過（不是失敗）。
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which('node')
HAVE = bool(NODE) and subprocess.run([NODE, '-e', "require('playwright')"], capture_output=True).returncode == 0

SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const [file, outPath] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto('file://' + file);
  const accounts = [{ id: 'u1', name: '王小明', reason: '姓名相同' }, { id: 'u2', name: '王曉明', reason: '姓名只差一個字' }];
  const out = {};
  for (const [label, sel] of [['first', '[data-pick="u1"]'], ['second', '[data-pick="u2"]'], ['new', '[data-pick="new"]'], ['cancel', '[data-pick=""]']]) {
    const p = page.evaluate(a => rcPickAccount('王小明', a), accounts);
    await page.waitForSelector('[role="dialog"]');
    if (label === 'first') {
      out.buttons = await page.$$eval('[role="dialog"] [data-pick]', bs => bs.map(b => {
        const r = b.getBoundingClientRect(); return { h: r.height, inside: r.left >= 0 && r.right <= window.innerWidth };
      }));
      out.focused_first = await page.evaluate(() => document.activeElement && document.activeElement.dataset.pick === 'u1');
      out.text = await page.textContent('[role="dialog"]');
    }
    await page.click(sel);
    out[label] = await p;
    out[label + '_closed'] = (await page.$('[role="dialog"]')) === null;
  }
  const p = page.evaluate(a => rcPickAccount('王小明', a), accounts);
  await page.waitForSelector('[role="dialog"]');
  await page.keyboard.press('Escape');
  out.escape = await p;
  require('fs').writeFileSync(outPath, JSON.stringify(out));
  await browser.close();
})();
"""


@pytest.mark.skipif(not HAVE, reason='沒有 node／playwright')
def test_the_choice_dialog_returns_what_was_clicked_and_is_easy_to_tap():
    js = (ROOT / 'static' / 'js' / 'rc-account-pick.js').read_text(encoding='utf-8')
    with tempfile.TemporaryDirectory() as d:
        html = Path(d) / 'p.html'
        html.write_text(f'<!doctype html><meta charset="utf-8"><body><script>{js}</script></body>', encoding='utf-8')
        runner, out = Path(d) / 'r.js', Path(d) / 'o.json'
        runner.write_text(SCRIPT, encoding='utf-8')
        env = {**__import__('os').environ,
               'NODE_PATH': subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()}
        r = subprocess.run([NODE, str(runner), str(html), str(out)], capture_output=True, text=True, timeout=120, env=env)
        assert r.returncode == 0, r.stderr
        res = json.loads(out.read_text())
    assert res['first'] == {'link_user_id': 'u1'} and res['second'] == {'link_user_id': 'u2'}
    assert res['new'] == {'new_account': True}
    assert res['cancel'] is None and res['escape'] is None, '「先不加」和 Esc 什麼都不做'
    assert all(res[k + '_closed'] for k in ('first', 'second', 'new', 'cancel')), '選完框要消失'
    assert all(b['h'] >= 44 and b['inside'] for b in res['buttons']), '按鈕要夠大、不超出手機畫面'
    assert res['focused_first'] and '就是「王小明」' in res['text'] and '另外建新的' in res['text']
