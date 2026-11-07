"""聚焦式教學（RollTour）：每一步的 data-tour 目標真的存在

`tour.js` 找不到目標時只會顯示文字、不高亮 —— 執行期那樣是對的（總比卡死好），
但它讓「改版把目標拆掉」完全沒有聲音：教學照樣跑得完，只是少指了幾個地方，
而少指的正是最近才改過的那幾處。所以這裡掃**原始碼裡有沒有宣告過**。

★ 自動找出所有用 `RollTour.start` 的模板，新增的教學頁不用記得回來登記。
★ Rule 15：綁定一律用 data-tour，不用 id／class（UI 調整時改掉 id／class，教學會默默失效）。
"""
import glob
import re

import pytest

PAGES = sorted(p for p in glob.glob('templates/**/*.html', recursive=True)
               if 'RollTour.start' in open(p, encoding='utf-8').read())


def _strip(s):
    s = re.sub(r'\{#.*?#\}', ' ', s, flags=re.S)
    return re.sub(r'<!--.*?-->', ' ', s, flags=re.S)


def test_the_pages_were_found():
    names = {p.replace('\\', '/') for p in PAGES}
    for must in ('templates/admin/events.html', 'templates/admin/event_form.html', 'templates/admin/event_guided.html'):
        assert must in names, f'{must} 沒有教學'


@pytest.mark.parametrize('path', PAGES)
def test_every_step_points_at_something_real(path):
    src = _strip(open(path, encoding='utf-8').read())
    steps = src.split('RollTour.start(')[1:]
    targets = [t for s in steps for t in re.findall(r"target:\s*'([^']+)'", s.split('])')[0])]
    assert targets, path
    for t in targets:
        assert f'data-tour="{t}"' in src, f'{path} 的教學指向 {t}，但頁面上沒有 data-tour="{t}"'


@pytest.mark.parametrize('path', PAGES)
def test_the_help_button_is_there(path):
    """Rule 15：每個有教學的頁面右上角有「？ 教學」，而且按下去真的會開。"""
    src = _strip(open(path, encoding='utf-8').read())
    assert 'data-tour="help-btn"' in src and 'onclick="startTour()"' in src and 'function startTour' in src, path
