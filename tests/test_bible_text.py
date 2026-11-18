"""經文內容：從使用者自己架的平台抓回來、解析、快取

守的是「畫面上有經文，但少了東西」那一類 —— 全部都不會報錯。
"""
from pathlib import Path

import pytest

from routes import bible_text as T

ROOT = Path(__file__).resolve().parent.parent


#  ★ 這是那個平台**真實**回來的樣子（詩篇 23:1-2）：
#    裡面有巢狀的標註 <span class="anno">，還有節號 <span class="verse-num">。
REAL = '''<html><body>
<nav class="booklist"><a href="/read/創世記/1">創世記</a><a href="/read/出埃及記/1">出埃及記</a></nav>
<main class="passage" id="passage">

    <p class="verse" data-v="1"><span class="verse-num">1</span><span class="verse-body"><span
       class="clause" data-clause="〔大衛的詩。">〔<span class="anno anno-person"
       data-entity="大衛">大衛</span>的詩。</span><span class="clause"
       data-clause="〕耶和華是我的牧者．我必不至缺乏。">〕<span class="anno anno-concept"
       data-entity="耶和華">耶和華</span>是我的牧者．我必不至缺乏。</span></span></p>

    <p class="verse" data-v="2"><span class="verse-num">2</span><span class="verse-body"><span
       class="clause">他使我躺臥在青草地上、</span><span class="clause">領我在可安歇的水邊。</span></span></p>

</main></body></html>'''


# ─────────────────────────────────────────────────────────
#  解析
# ─────────────────────────────────────────────────────────

def test_it_reads_the_real_markup():
    vs = T.parse_chapter(REAL)
    assert [v['v'] for v in vs] == [1, 2]
    assert vs[1]['text'] == '他使我躺臥在青草地上、領我在可安歇的水邊。'


def test_nested_annotations_stay_in_the_sentence():
    """★★ 「大衛」「耶和華」包在 <span class="anno"> 裡面。

    用正則抓 `>([^<]+)<` 的話那些字會被切掉或變成獨立的一塊 ——
    而畫面上那一節看起來只是**少了兩個字**，沒有人會發現。
    """
    vs = T.parse_chapter(REAL)
    assert vs[0]['text'] == '〔大衛的詩。〕耶和華是我的牧者．我必不至缺乏。'


def test_the_verse_number_is_not_part_of_the_text():
    """★ 節號要跳過。不跳的話每一節開頭多一個數字，
    而那看起來像經文的一部分（朗讀時還會唸出來）。"""
    for v in T.parse_chapter(REAL):
        assert not v['text'].startswith(str(v['v']))


def test_the_navigation_is_not_mistaken_for_scripture():
    """★ 那個站的側邊欄有全部書卷的目錄。整頁掃的話，
    導覽列的字會被當成經文混進去。"""
    vs = T.parse_chapter(REAL)
    joined = ' '.join(v['text'] for v in vs)
    assert '創世記' not in joined
    assert '出埃及記' not in joined


def test_full_width_punctuation_survives():
    """和合本用「．、〔〕」這種全形標點，不可以被當成空白清掉。"""
    vs = T.parse_chapter(REAL)
    assert '．' in vs[0]['text']
    assert '〔' in vs[0]['text'] and '〕' in vs[0]['text']


@pytest.mark.parametrize('junk', ['', None, '<html>找不到</html>', 'not html'])
def test_a_page_with_no_scripture_gives_an_empty_list(junk):
    """★ 回空陣列，不要丟例外 —— 呼叫端要分得出
    「這一章抓不到」和「整個功能壞了」。"""
    assert T.parse_chapter(junk) == []


def test_duplicated_verses_are_collapsed_and_sorted():
    html = ('<main class="passage">'
            '<p class="verse" data-v="2"><span class="verse-body">乙</span></p>'
            '<p class="verse" data-v="1"><span class="verse-body">甲</span></p>'
            '<p class="verse" data-v="2"><span class="verse-body">乙again</span></p>'
            '</main>')
    vs = T.parse_chapter(html)
    assert [v['v'] for v in vs] == [1, 2]
    assert vs[1]['text'] == '乙'


# ─────────────────────────────────────────────────────────
#  抓 ＋ 快取
# ─────────────────────────────────────────────────────────

class _FakeTable:
    def __init__(self, store):
        self.store, self._f = store, {}

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._f[col] = val
        return self

    def in_(self, col, vals):
        self._f['__in__'] = (col, list(vals))
        return self

    def range(self, lo, hi):
        self._f['__range__'] = (lo, hi)
        return self

    def limit(self, n):
        return self

    def upsert(self, row):
        self.store[(row['book'], row['chapter'])] = row
        return self

    def execute(self):
        #  整張表（`cached_pairs` 的分頁掃描）
        if '__range__' in self._f:
            lo, hi = self._f['__range__']
            rows = [{'book': b, 'chapter': c}
                    for (b, c) in sorted(self.store)][lo:hi + 1]

            class R:
                data = rows
            return R()

        #  一格一次問完（`cached_many`）
        if '__in__' in self._f:
            _, chapters = self._f['__in__']
            book = self._f.get('book')
            rows = []
            for ch in chapters:
                row = self.store.get((book, ch))
                if row:
                    rows.append({'chapter': ch, 'verses': row['verses']})

            class R:
                data = rows
            return R()

        key = (self._f.get('book'), self._f.get('chapter'))
        row = self.store.get(key)

        class R:
            data = [{'verses': row['verses']}] if row else []
        return R()


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeTable(self.store)


def test_the_second_read_does_not_hit_the_network():
    """★★ 全部才 1189 章，抓過一次就永遠不用再抓。

    每次 render 都去抓的話，讀經頁一次要等 3-4 次外部來回，
    而且對方睡著時我們的頁面跟著空白。
    """
    store, calls = {}, []

    def fetch(url, timeout=20):
        calls.append(url)
        return REAL

    vs, err = T.get_chapter('詩篇', 23, fetch=fetch, sb=_FakeSB(store))
    assert err is None and len(vs) == 2
    assert len(calls) == 1

    vs2, err2 = T.get_chapter('詩篇', 23, fetch=fetch, sb=_FakeSB(store))
    assert err2 is None and vs2 == vs
    assert len(calls) == 1, '第二次應該走快取，不該再打一次網路'


def test_a_network_error_is_reported_not_swallowed():
    def boom(url, timeout=20):
        raise TimeoutError('慢')
    vs, err = T.get_chapter('詩篇', 23, fetch=boom, sb=_FakeSB({}))
    assert vs == []
    assert err and '連不到' in err


def test_fetched_but_unparseable_says_something_different():
    """★ 「連不上」和「抓到了但沒有經文」是**兩件事**。

    前者是網路，後者是對方改版或書名不對 ——
    講一樣的話就查不出是哪一種。
    """
    vs, err = T.get_chapter('不存在的書', 1,
                            fetch=lambda url, timeout=20: '<html>空的</html>',
                            sb=_FakeSB({}))
    assert vs == []
    assert err and '連不到' not in err and '沒有經文' in err


def test_nothing_is_cached_when_the_fetch_fails():
    """★ 失敗不可以存一筆空的進去 —— 存了的話那一章**永遠**是空的，
    因為之後每次都會命中那個空快取。"""
    store = {}
    T.get_chapter('詩篇', 23, fetch=lambda url, timeout=20: '<html></html>',
                  sb=_FakeSB(store))
    assert store == {}


def test_a_passage_spans_every_chapter_in_the_cell():
    day = {'book': '詩篇', 'chapter_start': 22, 'chapter_end': 24}
    secs = T.get_passage(day, fetch=lambda url, timeout=20: REAL, sb=_FakeSB({}))
    assert [s['chapter'] for s in secs] == [22, 23, 24]


def test_one_bad_chapter_does_not_blank_the_others():
    """★ 一章抓不到時，其他章照樣要看得到 ——
    整頁空白跟「這一格沒有經文」長得一樣。"""
    def fetch(url, timeout=20):
        if '/23' in url:
            raise TimeoutError('慢')
        return REAL
    secs = T.get_passage({'book': '詩篇', 'chapter_start': 22, 'chapter_end': 24},
                         fetch=fetch, sb=_FakeSB({}))
    assert len(secs[0]['verses']) == 2
    assert secs[1]['verses'] == [] and secs[1]['error']
    assert len(secs[2]['verses']) == 2


def test_a_broken_range_cannot_hammer_the_other_site():
    """★ 資料壞掉（章數變成 999）時不可以送出 999 個請求。"""
    calls = []

    def fetch(url, timeout=20):
        calls.append(url)
        return REAL
    T.get_passage({'book': '詩篇', 'chapter_start': 1, 'chapter_end': 999},
                  fetch=fetch, sb=_FakeSB({}))
    assert len(calls) <= T.MAX_CHAPTERS_PER_DAY


def test_the_html_is_decoded_as_utf8():
    """★★ 那個站沒有在 header 帶 charset，`requests` 會退回 ISO-8859-1。

    用 `.text` 的話每一個中文字都是壞的 —— 而解析器照樣跑得完，
    只是每一節都變成亂碼。（驗證書名那一輪就被這個騙過一次。）
    """
    import re
    src = (ROOT / 'routes' / 'bible_text.py').read_text(encoding='utf-8')
    body = src.split('def _http_get')[1].split('\ndef ')[0]
    #  ★ 先切掉註解再掃。不切的話，那段**在解釋為什麼不能用 resp.text**
    #    的註解會讓這條測試對著正確的實作報錯 ——
    #    這個坑這一輪已經踩到第三次了（CLAUDE.md 有記）。
    code = re.sub(r'#.*$', '', body, flags=re.M)
    assert '.content.decode' in code
    assert 'resp.text' not in code


# ─────────────────────────────────────────────────────────
#  朗讀
# ─────────────────────────────────────────────────────────

def test_speech_text_leaves_out_the_verse_numbers():
    """★ 節號不唸 —— 連續聽的時候「一、二、三」會把句子切斷，
    而那個數字對聽的人沒有意義。"""
    secs = [{'chapter': 23, 'verses': T.parse_chapter(REAL), 'error': None}]
    lines = T.speech_text(secs)
    assert len(lines) == 2
    assert not any(l[0].isdigit() for l in lines)


def _js():
    return (ROOT / 'static' / 'js' / 'bible-reading-day.js').read_text(encoding='utf-8')


def _code(src):
    """去掉註解，只留真的會執行的部分。

    ★★ 這個 helper 存在是因為**同一個坑這一輪踩了四次**：
      註解裡寫著「不可以就說『沒有中文語音』」，於是
      `body.index('沒有中文語音')` 找到的是那句註解，
      切出來的片段裡一行程式都沒有 —— 而實作完全正確。

      CLAUDE.md 記過這條規則（「掃原始碼的斷言要先切出該掃的那一段」），
      但光靠記得沒有用。所以做成函式：**掃 JS 一律先過這一層。**
    """
    import re
    return re.sub(r'//.*$', '', src, flags=re.M)


def test_speech_is_queued_one_verse_at_a_time():
    """★★ 一節一個 utterance，不是整章一個。

    Chrome 對很長的 utterance 會在十幾秒後自己斷掉（唸到一半沒聲音，
    而且不會報錯），而且整段唸下去就標不出「現在唸到哪一節」。

    ★ 佇列本身搬到 `static/js/speech-queue.js` 了（抽出去才測得到）——
      真正把它跑一遍的是 `tests/test_speech_queue.py`，那裡用假的
      speechSynthesis 逐節驗。這一條只確認**頁面這一層**還是
      「一節一句」地餵進去。
    """
    queue = _code((ROOT / 'static' / 'js' / 'speech-queue.js').read_text(encoding='utf-8'))
    assert 'speak(idx + 1)' in queue, '要一節接一節排下去'
    page = _code(_js())
    assert 'new SpeechSynthesisUtterance(text)' in page
    assert 'createSpeechQueue' in page, '頁面要走那支佇列，不要自己再寫一份'


def test_an_empty_voice_list_is_not_reported_as_no_chinese_voice():
    """★ 語音清單是非同步載入的，第一次問常常是空的。

    空的時候就說「沒有中文語音」是錯的 —— 那是還沒載完。
    """
    import re
    #  ★ 先去掉註解 —— 註解裡就寫著「不可以就說『沒有中文語音』」，
    #    不去掉的話下面那個 index() 會切在註解上（見 _code 的說明）。
    body = _code(_js()).split('function warnIfNoChineseVoice')[1].split('\n    }')[0]
    #  守的是**行為**不是變數名：清單空的時候要直接 return，
    #  不可以往下走到那句警告。
    before = body[:body.index('沒有中文語音')]
    assert re.search(r'if\s*\(!\w+\.length\)\s*return;', before), \
        '語音清單還沒載完時要先 return'
    assert 'voiceschanged' in _js(), '載完要再問一次'


def test_leaving_the_page_stops_the_voice():
    """★ 不停的話換頁之後聲音還在唸，而使用者找不到是哪裡在出聲。"""
    js = _js()
    assert 'pagehide' in js and 'cancel()' in js


def test_it_never_sends_the_text_anywhere():
    """★ 朗讀完全在裝置上做 —— 一個字都不上傳。"""
    #  ★ 這一條**不能**去註解 —— 它靠 `// ── 讀完了` 那行註解當分界。
    js = _js()
    speech = js.split('// ── 讀完了')[0]
    assert 'fetch(' not in speech


# ─────────────────────────────────────────────────────────
#  接線
# ─────────────────────────────────────────────────────────

def test_the_cache_is_backed_up_or_deliberately_not():
    """★ 新增一張表就要表態（`BACKUP_TABLES` 或 `DERIVED`）。"""
    from backup_registry import EXCLUDED, TABLES
    assert 'bible_chapters' in {t[0] for t in TABLES} | set(EXCLUDED)


def test_the_reading_page_has_the_done_button_at_the_bottom():
    """★ 「我讀完了」要在**讀完的地方**。放最上面的話，
    按下去的時候他還沒開始讀。"""
    src = (ROOT / 'templates' / 'bible_reading_day.html').read_text(encoding='utf-8')
    body = src.split('{% block content %}')[1]
    assert body.index('rd-done') > body.index('rd-chapter'), '按鈕要在經文後面'


def test_a_chapter_that_cannot_be_fetched_still_offers_the_link_out():
    """★ 一片空白跟「這一章沒有經文」長得一樣 —— 要照實說並給他一條路。"""
    src = (ROOT / 'templates' / 'bible_reading_day.html').read_text(encoding='utf-8')
    block = src.split('class="rd-miss"')[1].split('</div>')[0]
    assert 'sec.url' in block or 'sec.error' in block


# ── 每一章底下那條「到聖經站看這一章」 ──────────────

def _render_day(sections):
    """把某一格 render 成 HTML。

    ★★ **一定要有 session** —— 這一頁有好幾塊包在 `{% if session.user_id %}`
      裡。沒有 session 的話測試看不到它要守的東西，而它照樣是綠的
      （這個專案在速讀表那一頁踩過一模一樣的坑）。
    """
    from flask import Blueprint, Flask, render_template, session
    # 這個 repo 的完整 app 不能和其他測試同一個行程，所以用簡化 app（跟 conftest 的 app 同一個做法），
    # 補上 base.html 要的模板全域
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.secret_key = 't'
    auth = Blueprint('auth', __name__)
    auth.add_url_rule('/auth/login', 'login_page', lambda: 'login')
    app.register_blueprint(auth)
    app.jinja_env.globals.update(
        csrf_token=lambda: 't', module_on=lambda *_: True, church_name='測試教會', church_short_name='測試',
        line_liff_id='', privacy_policy_url='', card_names={}, can_see=lambda *_: True,
        asset=lambda path: '/static/' + path)
    day = {'day_no': 1, 'book': '創世記', 'chapter_start': 1,
           'chapter_end': len(sections), 'label': '創世記 1–4'}
    with app.test_request_context('/reading/1'):
        session['user_id'] = 'u1'
        session['real_name'] = '測試'
        return render_template('bible_reading_day.html', day=day,
                               sections=sections, stats={'done': 3, 'total': 365},
                               is_done=False, nxt=None, url='')


def _ok_sections(n=3):
    return [{'chapter': ch,
             'verses': [{'v': 1, 'text': f'第 {ch} 章。'}],
             'error': None,
             'url': f'https://例.test/read/創世記/{ch}'}
            for ch in range(1, n + 1)]


def test_every_chapter_offers_the_way_to_the_notes():
    """★ 使用者要的是那個平台的**名詞解釋**，而一格常常四章。

    整頁只給一條的話，讀到第一章想查一個名詞，得先捲過三章 ——
    所以是**每一章後面各一條**。
    """
    html = _render_day(_ok_sections(3))
    for ch in (1, 2, 3):
        assert f'https://例.test/read/創世記/{ch}' in html, f'第 {ch} 章沒有外連'
    #  ★ 比對 `class="rd-more"` 不是 `rd-more` —— 那三個字在
    #    <style> 裡也有，掃寬一點的話「整塊不出現」那條會永遠是綠的
    assert html.count('class="rd-more"') == 3


def test_the_link_sits_after_that_chapter_not_after_all_of_them():
    """★★ 「有這條連結」和「在對的地方」是兩件事。

    掃「有沒有出現」的話，把整塊搬到頁面最下面照樣是綠的，
    而那正好是使用者要避開的東西（「每一章後面喔」）。
    這一條看的是**每一條連結和下一章標題的前後順序**。
    """
    html = _render_day(_ok_sections(3))
    for ch in (1, 2):
        link = html.index(f'/read/創世記/{ch}')
        nxt = html.index(f'第 {ch + 1} 章</h2>')
        assert link < nxt, f'第 {ch} 章的連結跑到第 {ch + 1} 章後面去了'


def test_no_link_when_the_setting_is_cleared():
    """★ 設定清空時 `sec.url` 是 None —— 那一整塊要消失，
    不可以留一條點了跑到錯地方（或空網址）的連結。"""
    secs = _ok_sections(2)
    for s in secs:
        s['url'] = None
    html = _render_day(secs)
    assert 'class="rd-more"' not in html


def test_the_site_is_never_hardcoded_in_the_template():
    """★ 網址一律從 `bible_reader_url` 設定來。寫死的話外部網址搬家時
    畫面完全正常，只有點下去的人看到不對的東西 —— 而他不會回報。"""
    src = (ROOT / 'templates' / 'bible_reading_day.html').read_text(encoding='utf-8')
    assert 'bibile-actionbook' not in src
    assert 'http://' not in src and 'https://' not in src


def test_a_fetched_chapter_carries_its_own_url():
    """★ 模板拿得到 `sec.url` 是因為 `get_passage` 每一章都放了一個 ——
    而且是**那一章的**，不是整格的起始章。"""
    from routes import bible_text
    day = {'book': '創世記', 'chapter_start': 1, 'chapter_end': 3}
    secs = bible_text.get_passage(
        day, fetch=lambda url: '<main class="passage">'
                               '<p class="verse" data-v="1">'
                               '<span class="verse-body">起初。</span></p></main>',
        sb=_FakeSB({}))
    assert [s['url'].rsplit('/', 1)[-1] for s in secs] == ['1', '2', '3']


# ── 聲音是裝置給的，只能讓他自己挑 ──────────────────

def test_the_voice_list_is_offered_not_guessed():
    """★★ 我們**不知道**他裝置上有什麼聲音，也沒有標準的性別屬性。

    所以要把清單攤出來讓他自己選，不是替他猜一個 ——
    猜錯的話他只會覺得「這功能就是這個聲音，改不了」。
    """
    js = _js()
    assert 'rd-voice-pick' in js
    assert 'getVoices' in js


def test_the_male_hint_only_sorts_never_decides():
    """★ 從名字猜性別一定會猜錯。猜錯的代價要是「排序不理想」，
    不是「聽到不是他選的聲音」。"""
    js = _code(_js())
    fill = js.split('function fillVoiceList')[1].split('function pickVoice')[0]
    assert 'sort' in fill, '猜測只拿來排序'
    pick = js.split('function pickVoice')[1].split('function warnIfNoChineseVoice')[0]
    assert 'MALE_HINTS' not in pick, '選聲音時不可以用猜的性別去決定'


def test_pitch_is_applied_so_the_voice_can_be_deepened():
    """使用者：「讀經要低沉有磁性的男聲」。

    ★ pitch 調低會讓同一個聲音變低 —— 它**不會**把女聲變成男聲，
      但這是不用花錢、不用金鑰能做到的部分。
    """
    js = _code(_js())
    body = js.split('function applyVoice')[1].split('function rememberChoice')[0]
    assert 'u.pitch' in body
    assert 'rd-pitch' in js


def test_the_choice_is_remembered_on_this_device_only():
    """★ 聲音清單本來就因裝置而異。存到資料庫等於把
    「我在手機上挑的男聲」帶到一台沒有那個聲音的電腦上。"""
    js = _code(_js())
    assert 'localStorage' in js
    #  ★ 讀**和**寫都要各自包 try —— 無痕視窗、關掉網站資料時
    #    `localStorage` 的存取**本身**就會丟例外，而那會讓整支 JS 停掉
    #    （朗讀、讀完了全部一起死）。
    #
    #    ★ 第一版寫的是 `js.count('try {') >= 2` —— 那是假的：
    #      別的地方也有 try，拿掉其中一個照樣過。守衛要對著**那兩個函式**。
    for fn in ('loadPref', 'savePref'):
        body = js.split('function ' + fn)[1].split('\n    }')[0]
        assert 'try' in body and 'catch' in body, f'{fn} 沒有包 try'
        assert 'localStorage' in body


def test_there_is_a_way_to_hear_it_before_committing():
    """★ 沒有試聽的話，他要調一次、播一次、停一次 —— 調三輪就放棄了。"""
    js = _js()
    assert 'rd-try' in js


def test_the_settings_panel_tells_him_how_to_get_more_voices():
    """★ 「這台裝置只有一個女聲」不是我們能修的 ——
    但**告訴他去哪裡下載**是我們能做的，而那才是真正的解法。"""
    src = (ROOT / 'templates' / 'bible_reading_day.html').read_text(encoding='utf-8')
    panel = src.split('id="rd-voice"')[1].split('{# ════ 經文 ════ #}')[0]
    assert 'iPhone' in panel and 'Android' in panel
