"""365 天聖經速讀計畫

## 這一份測試的一半是在守**資料**

計畫內容是從教會發的 PDF（9 欄印刷表格）逐格解出來的。解析當下驗過四件事，
而那四件事現在留成永久的測試 —— 因為**少一格的後果沒有任何症狀**：
所有人的進度往前平移一格，而每一格看起來都還是像正常的經文範圍。
"""
import json
import re
from pathlib import Path

import pytest

from routes import bible_plan as B

ROOT = Path(__file__).resolve().parent.parent

#  正典順序 ＋ 每卷章數。★ 這一份是**獨立**寫的，不是從資料檔算出來的 ——
#  拿資料檔去驗資料檔等於自己通過。
CANON = [
    ('創世記', 50), ('出埃及記', 40), ('利未記', 27), ('民數記', 36),
    ('申命記', 34), ('約書亞記', 24), ('士師記', 21), ('路得記', 4),
    ('撒母耳記上', 31), ('撒母耳記下', 24), ('列王紀上', 22), ('列王紀下', 25),
    ('歷代志上', 29), ('歷代志下', 36), ('以斯拉記', 10), ('尼希米記', 13),
    ('以斯帖記', 10), ('約伯記', 42), ('詩篇', 150), ('箴言', 31),
    ('傳道書', 12), ('雅歌', 8), ('以賽亞書', 66), ('耶利米書', 52),
    ('耶利米哀歌', 5), ('以西結書', 48), ('但以理書', 12), ('何西阿書', 14),
    ('約珥書', 3), ('阿摩司書', 9), ('俄巴底亞書', 1), ('約拿書', 4),
    ('彌迦書', 7), ('那鴻書', 3), ('哈巴谷書', 3), ('西番雅書', 3),
    ('哈該書', 2), ('撒迦利亞書', 14), ('瑪拉基書', 4),
    ('馬太福音', 28), ('馬可福音', 16), ('路加福音', 24), ('約翰福音', 21),
    ('使徒行傳', 28), ('羅馬書', 16), ('哥林多前書', 16), ('哥林多後書', 13),
    ('加拉太書', 6), ('以弗所書', 6), ('腓立比書', 4), ('歌羅西書', 4),
    ('帖撒羅尼迦前書', 5), ('帖撒羅尼迦後書', 3), ('提摩太前書', 6),
    ('提摩太後書', 4), ('提多書', 3), ('腓利門書', 1), ('希伯來書', 13),
    ('雅各書', 5), ('彼得前書', 5), ('彼得後書', 3), ('約翰一書', 5),
    ('約翰二書', 1), ('約翰三書', 1), ('猶大書', 1), ('啟示錄', 22),
]


# ─────────────────────────────────────────────────────────
#  資料本身
# ─────────────────────────────────────────────────────────

def test_there_are_exactly_365_cells():
    """★ 少一格會讓所有人的進度往前平移一格，而畫面上完全正常。"""
    assert len(B.days()) == 365


def test_day_numbers_are_1_to_365_with_no_gaps():
    assert [d['day_no'] for d in B.days()] == list(range(1, 366))


def test_the_books_follow_the_canon():
    """★ 順序錯的話，「接下來要讀的」會把人帶去不相干的地方。"""
    seen = []
    for d in B.days():
        if not seen or seen[-1] != d['book']:
            seen.append(d['book'])
    assert seen == [b[0] for b in CANON]


@pytest.mark.parametrize('book,chapters', CANON)
def test_every_book_is_covered_end_to_end(book, chapters):
    """★★ 每一卷的章要從 1 開始、連續、蓋到最後一章。

    這條就是抓到原表漏掉哥林多前書 9-12 的那一條。
    漏掉的那幾章**不會有任何症狀** —— 照著讀完的人只是永遠沒讀到，
    而他的進度條是 365/365。
    """
    mine = [d for d in B.days() if d['book'] == book]
    assert mine, f'{book} 一格都沒有'
    cursor = 1
    for d in mine:
        if d['chapter_start'] == cursor - 1:
            continue                      # 同一章拆兩格（詩 119）
        assert d['chapter_start'] == cursor, (
            f'{book} 第 {d["day_no"]} 格從第 {d["chapter_start"]} 章開始，'
            f'上一格停在第 {cursor - 1} 章')
        cursor = d['chapter_end'] + 1
    assert cursor - 1 == chapters, f'{book} 只讀到第 {cursor - 1} 章，全卷 {chapters} 章'


def test_chapter_ranges_are_sane():
    for d in B.days():
        assert d['chapter_start'] >= 1
        assert d['chapter_end'] >= d['chapter_start']


def test_the_correction_is_written_down_not_silently_applied():
    """★★ 改過紙本的地方要留紀錄。

    默默改掉的話，照系統讀的人和照紙本讀的人會對不上，
    **而兩邊各自看都正常**。而且下次印那張表時沒有人知道要修什麼。
    """
    plan = B.load_plan()
    corrections = plan.get('corrections') or []
    assert corrections, '改過紙本卻沒有留下 corrections'
    c = corrections[0]
    for field in ('day_no', 'printed', 'stored', 'why'):
        assert c.get(field), f'corrections 少了 {field}'
    #  那一格現在真的是修正後的樣子
    day = next(d for d in B.days() if d['day_no'] == c['day_no'])
    assert day['label'] == c['stored']


def test_the_manual_tells_people_about_the_correction():
    """★ 只寫在資料檔裡不夠 —— 手上拿著紙本的人要看得到那一處不一樣。"""
    src = (ROOT / 'templates' / 'manual.html').read_text(encoding='utf-8')
    sec = src[src.index('id="bible-reading"'):]
    sec = sec[:sec.index('{% endif %}')]
    assert '林前 9-16' in sec
    assert '9-12' in sec, '要講出紙本漏掉的是哪幾章'


# ─────────────────────────────────────────────────────────
#  經文外連
# ─────────────────────────────────────────────────────────

def test_every_cell_produces_a_link():
    """★ 每一格都要連得出網址。少一格的話那幾格只是沒有「翻開」可以按。"""
    for d in B.days():
        assert B.read_url(d), f'第 {d["day_no"]} 格產不出網址'


def test_the_link_uses_the_full_book_name():
    """★ 使用者那個平台用**書卷全名**（/read/出埃及記/25）——
    所以資料裡的 `book` 直接就能用，不需要任何簡稱對照表。

    少了對照表就少了一整類錯：「點下去是別卷書」而畫面完全正常
    （真的有一章經文，只是不是他要讀的那一章）。
    """
    from urllib.parse import quote
    day = next(d for d in B.days() if d['book'] == '出埃及記' and d['chapter_start'] == 25)
    url = B.read_url(day)
    assert quote('出埃及記', safe='') in url
    assert url.endswith('/25')


def test_the_book_name_is_url_encoded():
    """★ 不編碼的話，中文書名在 LINE 內建瀏覽器會被截掉，
    而那條連結看起來完全正常。"""
    url = B.read_url({'book': '創世記', 'chapter_start': 1})
    assert '創世記' not in url, '書名要編碼過'
    assert '%E5%89%B5' in url


def test_the_link_carries_the_starting_chapter_not_the_range():
    """★ 那些平台一次顯示一章，帶章範圍它們不認。"""
    day = next(d for d in B.days() if d['label'] == '創 1-4')
    assert B.read_url(day).endswith('/1')


def test_a_custom_template_is_honoured():
    """後台換一個聖經站，全部的連結要跟著換。"""
    url = B.read_url({'book': '創世記', 'chapter_start': 3},
                     template='https://example.com/b/{book}/c/{chapter}')
    assert url.startswith('https://example.com/b/')
    assert url.endswith('/c/3')


def test_clearing_the_setting_removes_the_button_instead_of_guessing():
    """★ 設定清空 → 回 None（那顆按鈕整個不出現）。

    退回一個寫死的網址的話，後台明明清空了，前台還是連得出去 ——
    而那正是「我明明改了它還在」。
    """
    assert B.read_url({'book': '創世記', 'chapter_start': 1}, template='') is None






# ─────────────────────────────────────────────────────────
#  進度計算（純函式）
# ─────────────────────────────────────────────────────────

def test_next_unread_is_the_first_gap_not_the_last_tick():
    """★★ 「接下來要讀的」是**第一個沒打勾的**，不是最後打勾的下一格。

    先讀新約再回頭補的人，用後者會把中間整段跳過去 ——
    而他的進度條看起來一路往前，沒有任何地方提醒他漏了。
    """
    #  他打了 1、2 和 300（跳去讀新約）
    nxt = B.next_unread({1, 2, 300})
    assert nxt['day_no'] == 3, '應該回到第一個沒打勾的那一格'


def test_next_unread_is_none_when_everything_is_done():
    assert B.next_unread(set(range(1, 366))) is None


def test_summarise_counts_cells_and_chapters():
    s = B.summarise({1, 2})          # 創 1-4 ＋ 創 5-8
    assert s['done'] == 2
    assert s['total'] == 365
    assert s['chapters'] == 8


def test_progress_from_an_old_plan_does_not_overflow():
    """★ 換過計畫留下的 day_no 不可以讓進度變成 370/365。

    那個數字沒有人看得懂，而且會讓「還剩幾格」變成負的。
    """
    s = B.summarise({1, 2, 999, 1000})
    assert s['done'] == 2
    assert s['percent'] <= 100


def test_percent_is_zero_for_a_new_reader():
    s = B.summarise(set())
    assert (s['done'], s['percent'], s['chapters']) == (0, 0, 0)


# ─────────────────────────────────────────────────────────
#  依經卷分組（使用者指定的形狀）
# ─────────────────────────────────────────────────────────

def test_grouped_by_book_not_a_flat_list_of_365():
    """使用者的話：「用經卷為單位」。"""
    books = B.by_book()
    assert len(books) == 66
    assert books[0]['book'] == '創世記'
    assert books[0]['total'] == 14, '創世記在這份計畫裡是 14 格'
    assert books[-1]['book'] == '啟示錄'


def test_each_book_counts_its_own_progress():
    done = {1, 2, 3}                 # 創世記前三格
    books = B.by_book(done)
    gen = books[0]
    assert gen['done'] == 3
    assert all(d['done'] for d in gen['days'][:3])
    assert not any(d['done'] for d in gen['days'][3:])


def test_the_grouping_keeps_the_testament_split():
    books = B.by_book()
    ot = [b for b in books if b['testament'] == '舊約']
    nt = [b for b in books if b['testament'] == '新約']
    assert len(ot) == 39 and len(nt) == 27
    assert nt[0]['book'] == '馬太福音'


def test_every_cell_in_a_group_carries_its_link():
    for b in B.by_book():
        for d in b['days']:
            assert d['url'], f'{b["book"]} 第 {d["day_no"]} 格沒有經文連結'


# ─────────────────────────────────────────────────────────
#  接線
# ─────────────────────────────────────────────────────────

def test_progress_gets_backed_up():
    """★ 「重抓就有」在這裡完全不成立 —— 弄丟了，讀了半年的人
    要從第 1 格重新打 180 次。"""
    from backup_registry import TABLES
    assert 'bible_reading_progress' in [t[0] for t in TABLES]






def test_the_plan_data_lives_in_the_repo_not_the_database():
    """★ 計畫內容是固定的，放 repo 才看得到、改得到、驗得到。

    再存一份到資料庫只是多一個「兩邊說法不一致」的來源，
    而不一致的時候兩邊各自看都正常。
    """
    assert (ROOT / 'data' / 'bible_reading_plan_365.json').exists()
    src = (ROOT / 'routes' / 'bible_plan.py').read_text(encoding='utf-8')
    #  只該碰進度表，不該有「計畫內容表」
    assert 'bible_reading_days' not in src


# ─────────────────────────────────────────────────────────
#  這一頁不可以罵人
# ─────────────────────────────────────────────────────────

def _visible_text(path):
    """把註解和 docstring 拿掉，只留**人會看到的**部分。

    ★ 這一步不能省。第一版直接掃整份檔案，於是被那幾段
      「解釋為什麼不做」的註解打中 —— 對一個完全正確的實作報錯。
      這正是 CLAUDE.md 記過的形狀：**掃原始碼的斷言要先切出該掃的那一段**。
    """
    import re
    src = (ROOT / path).read_text(encoding='utf-8')
    if path.endswith('.py'):
        src = re.sub(r'"""[\s\S]*?"""', '', src)      # docstring
        src = re.sub(r'^\s*#.*$', '', src, flags=re.M)  # 整行註解
        src = re.sub(r'\s#.*$', '', src, flags=re.M)    # 行尾註解
    else:
        src = re.sub(r'\{#[\s\S]*?#\}', '', src)      # Jinja 註解
        src = re.sub(r'<!--[\s\S]*?-->', '', src)     # HTML 註解
        src = re.sub(r'//.*$', '', src, flags=re.M)   # JS 行註解
    return src


@pytest.mark.parametrize('page', ['templates/bible_reading.html',
                                  'routes/bible_plan.py',
                                  'routes/reading_nudge.py',      # 每天一則推播，最可能罵人的地方
                                  'templates/portal.html'])
def test_it_never_tells_anyone_they_are_behind(page):
    """★★ 教會那張紙沒有日期，系統就不可以發明日期。

    365 天計畫的頭號死因是斷了三天就再也不回來，
    而「落後 12 天」正是讓人不回來的那句話。
    """
    body = _visible_text(page)
    for banned in ('落後', '逾期', '遲到', '沒跟上'):
        assert banned not in body, f'{page} 出現了「{banned}」'


def test_the_guard_would_actually_catch_it():
    """★ 上面那條在切掉註解之後還看得見真正的文案嗎？

    切太多的話它會變成一條「掃空字串」的假測試 —— 永遠綠。
    """
    body = _visible_text('templates/bible_reading.html')
    assert '接下來要讀的' in body, '切過頭了，畫面上的字都不見了'
    assert '我讀完了' in body


def test_the_page_says_the_number_only_goes_forward():
    """★ 一個數字旁邊那句話會決定人怎麼看它。"""
    src = (ROOT / 'templates' / 'bible_reading.html').read_text(encoding='utf-8')
    assert '只會往前' in src


def test_unmarking_is_possible():
    """★ 按錯了要救得回來，不然那一格永遠是綠的。"""
    src = (ROOT / 'routes' / 'bible_plan.py').read_text(encoding='utf-8')
    assert 'def unmark' in src
    page = (ROOT / 'templates' / 'bible_reading.html').read_text(encoding='utf-8')
    assert 'aria-pressed' in page, '每一格要有可以切回去的開關'


# ─────────────────────────────────────────────────────────
#  印出來那張表（領證書用）
# ─────────────────────────────────────────────────────────

def _sheet():
    return (ROOT / 'templates' / 'bible_reading_sheet.html').read_text(encoding='utf-8')


def test_the_sheet_shows_all_365_cells():
    """★ 證書要對著一張**看得到全部 365 格**的表。

    「依經卷」那份是給手機捲的，印出來會變四十幾頁 ——
    沒有人會拿那個去換證書。
    """
    from routes.bible_plan import days
    src = _sheet()
    #  沒有分頁、沒有 limit —— 整份 rows 直接跑完
    assert 'for r in rows' in src
    assert len(days()) == 365


def test_the_sheet_has_the_two_boxes_from_the_paper():
    """★ 紙本上就有小組和姓名，那兩格是**拿去交的憑據**。"""
    src = _sheet()
    head = src.split('class="sh-head"')[1].split('</div>')[0]
    assert '小組' in head and '姓名' in head


def test_an_unknown_group_is_left_blank_not_guessed():
    """★ 算不出他哪一組就留白讓他自己寫 —— 印一個猜的上去，
    他會拿著一張寫錯組別的表去交。"""
    src = _sheet()
    assert "{{ group or '' }}" in src


def test_the_group_comes_from_the_one_existing_rule():
    """★★ 「一個人算哪一組」只准有一份實作。

    一個人可能掛在兩個主標籤小組上。兩邊各自挑的話，速讀表印的組
    和收款單上的組會不一樣 —— **而兩張各自看都正常**。
    """
    src = (ROOT / 'routes' / 'bible_plan.py').read_text(encoding='utf-8')
    body = src.split('def my_group')[1].split('\n@')[0]
    assert 'collecting_group' in body, '要走 collection 那份唯一的規則'
    assert 'is_primary' not in body, '不可以自己再查一次主標籤'


def test_printing_does_not_rely_on_background_colour():
    """★★ 很多人印黑白。靠底色標「已讀」的話，灰底會把字壓掉 ——
    那一格看起來像是空的，而他明明讀過了。

    ★ 要**先去掉註解**再切。這一條自己踩過：模板裡有一段註解寫著
      「由 base.css 的 @media print 統一收掉」，於是
      `split('@media print')[1]` 切在那句註解上，切出來的片段
      一行 CSS 都沒有，而實作完全正確。
      （跟 `tests/test_bible_text.py` 的 `_code()` 同一回事。）
    """
    src = re.sub(r'/\*[\s\S]*?\*/', '', _sheet())
    print_block = src.split('@media print')[1]
    done = print_block.split('.sh-cell.done')[1].split('}')[0]
    assert 'border' in done, '印出來要靠邊框，不是底色'
    assert 'background: white' in done or 'background:white' in done


#  ★ 「浮動鈕不可以印在表上」搬去 tests/test_print_pages.py 了。
#
#    原本這裡有一條 `test_the_floating_buttons_do_not_print_over_the_table`，
#    它斷言的是「這一頁的 print 區塊裡有 `display: none`」——
#    **那是假的**：模板當時列的 `#help-button` / `#ask-help` / `.floating`
#    三個 id 一個都不存在，小舟照樣印在每一頁上，而這條一直是綠的。
#    （使用者印出來才發現：「證書連小舟都進去搶鏡頭了」。）
#
#    真正守得住的斷言是「選擇器指到的東西真的存在」，而那要對著
#    base.html 掃，不是對著這一頁 —— 所以它不屬於這個檔案。


def test_the_sheet_is_reachable():
    """★ 沒有入口的功能等於不存在 —— 這一頁尤其，
    因為它是「領證書那天」才想到要用的東西。"""
    src = (ROOT / 'templates' / 'bible_reading.html').read_text(encoding='utf-8')
    #  ★ 要比對**完整的 href**，不是子字串。
    #    `'/reading/sheet' in src` 會被 `/reading/sheet-gone` 滿足 ——
    #    連結壞掉了，而測試照樣綠。（mutation 當場抓到。）
    assert 'href="/reading/sheet"' in src


def test_the_sheet_route_does_not_collide_with_a_day():
    """★ `/reading/<int:day_no>` 用 int 轉換器，所以 `/reading/sheet`
    不會被吃掉。改成 `<day_no>`（不限型別）的話，這一頁會變成
    「找不到第 sheet 格」—— 而路由本身完全正常。"""
    src = (ROOT / 'routes' / 'bible_plan.py').read_text(encoding='utf-8')
    assert "'/reading/<int:day_no>'" in src


# ══ 讀過的日期（使用者：純粹是顯示、記錄自己） ═══════════

"""使用者：「這個表可以標記讀過的日期嗎 純粹是顯示、記錄自己
不是催別人讀經」

★ **資料本來就在。** `mark()` 從第一天起每次打勾都寫了 `read_on`
  （台北日期）—— 所以他過去打的每一個勾都有日期，不用重來、
  也沒有一段空白。只是 `done_days()` 只 `select('day_no')`，
  那一欄一直沒有人讀。

★★ 他那句「不是催別人讀經」要當成規格看：這一格是**記錄**，
   所以只印日期 —— 不算「幾天沒讀」、不留空格等著被填。
   （擋那幾個字的守衛在這個檔案上面，一直都在。）
"""


class _FakeTable:
    def __init__(self, rows): self._rows = rows; self.selected = None
    def select(self, cols): self.selected = cols; return self
    def eq(self, *a, **k): return self
    def execute(self): return type('R', (), {'data': self._rows})()


class _FakeSB:
    def __init__(self, rows): self.t = _FakeTable(rows)
    def table(self, name): return self.t


def test_the_date_each_box_was_ticked_comes_back():
    from datetime import date
    sb = _FakeSB([{'day_no': 1, 'read_on': '2026-09-06'},
                  {'day_no': 2, 'read_on': '2026-09-07'}])
    assert B.read_dates('u', sb=sb) == {1: date(2026, 9, 6), 2: date(2026, 9, 7)}


def test_it_asks_the_database_for_that_column():
    """★ 前提：`done_days` 只撈 day_no。這一支不去撈 `read_on` 的話，
    它永遠回空的，而畫面上就是「一個日期都沒有」—— 看起來像
    使用者從來沒打過勾。"""
    sb = _FakeSB([])
    B.read_dates('u', sb=sb)
    assert 'read_on' in (sb.t.selected or '')


def test_a_box_with_no_date_is_left_blank_not_invented():
    """★★ 沒有日期就**不顯示**，不要退回今天或別的東西。

    印在紙上的日期他會當真，而「那天我明明沒讀」是查不回來的。
    """
    from datetime import date
    sb = _FakeSB([{'day_no': 1, 'read_on': None},
                  {'day_no': 2, 'read_on': '壞掉的日期'},
                  {'day_no': 3, 'read_on': '2026-09-08'}])
    assert B.read_dates('u', sb=sb) == {3: date(2026, 9, 8)}


def test_a_database_error_does_not_take_the_sheet_down():
    """★ 日期是附加的資訊 —— 撈不到就沒有日期，不可以連整張表一起沒了。"""
    class _Boom:
        def table(self, n): raise RuntimeError('down')
    assert B.read_dates('u', sb=_Boom()) == {}


def test_no_user_no_query():
    assert B.read_dates(None) == {}


def test_it_returns_dates_not_strings():
    """★ 回字串會誘人去切（`raw[:10]` 那一類）—— 這個專案整章在講那件事。"""
    from datetime import date
    got = B.read_dates('u', sb=_FakeSB([{'day_no': 1, 'read_on': '2026-09-06'}]))
    assert isinstance(got[1], date)


def test_the_sheet_shows_the_date_on_the_boxes_that_were_read():
    """★ 讀過的那一格印出日期；沒讀過的那一格**不留位置** ——
    留一條空線等於在說「這裡缺一個東西」，而那正是他說不要的那件事。"""
    src = (ROOT / 'templates' / 'bible_reading_sheet.html').read_text(encoding='utf-8')
    body = src[src.index('<a class="sh-cell'):]
    body = body[:body.index('{% if loop.last %}')]
    assert 'r.read_label' in body
    assert '{% if r.read_label %}' in body, '沒讀過的格子也留了位置'


def test_the_printed_date_is_not_green():
    """★ 印黑白時綠色會變成淺灰，小字直接消失 ——
    跟「打勾不可以靠底色」同一個理由。"""
    src = re.sub(r'/\*[\s\S]*?\*/', '', (ROOT / 'templates' / 'bible_reading_sheet.html')
                 .read_text(encoding='utf-8'))
    block = src.split('@media print')[1]
    when = block.split('.sh-when')[1].split('}')[0]
    assert '#000' in when, '印出來還是綠的'


def test_the_sheet_still_refuses_to_nag():
    """★★ 加了日期之後，「不催人」那條要**重新確認一次**。

    這一格是記錄，不是進度管理 —— 使用者的原話：「不是催別人讀經」。
    （擋字的那條守衛在這個檔案上面，這裡只是把它跟這個功能綁在一起，
      免得下次有人「順手」加一句「你已經 5 天沒讀」。）
    """
    src = _visible_text('templates/bible_reading_sheet.html')
    for bad in ('落後', '逾期', '遲到', '天沒讀', '中斷'):
        assert bad not in src, f'速讀表開始催人了：{bad}'
