"""點名單的搜尋欄：用真的 Chromium（手機、平板尺寸）打字，確認 300 個人也找得到、找不到時能直接加新朋友。

掃原始碼看得到「有沒有寫這個 input」，看不到「打字之後名單真的只剩符合的人」。
沒有 node／playwright／Chromium 時略過（不是失敗）。
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

NODE = shutil.which('node')
HAVE = False
if NODE:
    HAVE = subprocess.run([NODE, '-e', "require('playwright')"], capture_output=True).returncode == 0

SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const [file, outPath] = process.argv.slice(2);
  const browser = await chromium.launch();
  const out = {};
  for (const [name, size] of [['phone', {width: 390, height: 844}], ['tablet', {width: 820, height: 1180}]]) {
    const page = await browser.newPage({ viewport: size });
    await page.route('**/*', r => r.request().url().startsWith('file:') || r.request().url().startsWith('data:') ? r.continue() : r.abort());
    await page.goto('file://' + file);
    const rows = () => page.$$eval('tbody tr[data-name]', t => t.filter(r => r.style.display !== 'none').length);
    const r = { total: await rows() };
    await page.fill('#sh-search', '王');   r.after_wang = await rows();
    await page.fill('#sh-search', '０００７'); r.after_fullwidth = await rows();            // 全形數字也要找得到
    await page.fill('#sh-search', '不存在的人'); r.after_nomatch = await rows();
    r.none_visible = await page.isVisible('#sh-none');
    r.none_text = await page.textContent('#sh-none-q');
    await page.fill('#sh-search', '');     r.after_clear = await rows();
    r.none_hidden_again = !(await page.isVisible('#sh-none'));
    // 搜尋欄固定在最上面：捲到很下面還看得到
    await page.evaluate(() => window.scrollTo(0, 100000));
    r.search_visible_after_scroll = await page.evaluate(() => { const b = document.getElementById('sh-search').getBoundingClientRect(); return b.top >= 0 && b.bottom <= window.innerHeight; });
    r.no_horizontal_page_scroll = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    out[name] = r;
    await page.close();
  }
  require('fs').writeFileSync(outPath, JSON.stringify(out));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.mark.skipif(not HAVE, reason='沒有 node／playwright')
def test_search_filters_300_people_on_phone_and_tablet(fake_db, client_as):
    names = [f'王{i:04d}' if i % 3 == 0 else f'李{i:04d}' for i in range(300)]
    fake_db.tables.update(
        rc_meeting_types=[{'id': 't1', 'name': '主日', 'record_mode': 'individual', 'created_at': '2026-01-01'}],
        rc_sessions=[{'id': 's1', 'type_id': 't1', 'starts_at': '2026-11-08T02:00:00+00:00', 'status': 'open'}],
        rc_members=[{'id': f'm{i}', 'name': n, 'status': 'active'} for i, n in enumerate(names)])
    html = client_as(is_staff=True).get('/roll-call').get_data(as_text=True)
    assert html.count('data-name=') == 300
    with tempfile.TemporaryDirectory() as d:
        page, script, out = Path(d, 'sheet.html'), Path(d, 'run.js'), Path(d, 'out.json')
        page.write_text(html, encoding='utf-8')
        script.write_text(SCRIPT, encoding='utf-8')
        p = subprocess.run([NODE, str(script), str(page), str(out)], capture_output=True, text=True, timeout=120,
                           env={**__import__('os').environ,
                                'NODE_PATH': subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip()})
        if p.returncode != 0 and 'Executable doesn' in p.stderr:
            pytest.skip('沒有 Chromium')
        assert p.returncode == 0, p.stderr[-800:]
        res = json.loads(out.read_text())
    for size in ('phone', 'tablet'):
        r = res[size]
        assert r['total'] == 300, (size, r)
        assert r['after_wang'] == 100, (size, r)                      # 王開頭 100 位
        assert r['after_fullwidth'] == 1, (size, r)                   # 全形「０００７」找得到 李0007
        assert r['after_nomatch'] == 0 and r['none_visible'] and r['none_text'] == '不存在的人', (size, r)
        assert r['after_clear'] == 300 and r['none_hidden_again'], (size, r)
        assert r['search_visible_after_scroll'], (size, r)            # 300 人捲到底，搜尋欄還在
        assert r['no_horizontal_page_scroll'], (size, r)              # 整頁不可以左右晃（表格自己捲）
