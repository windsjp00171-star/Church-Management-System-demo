"""經文內容：從使用者自己架的平台抓回來，抓過就存著

## 為什麼是「抓一次就存起來」

使用者：「不要跳轉出去 直接在頁面顯示經文內容 會不會更簡單一點」。
對 —— 而且它換到的不只是少一次跳轉：**經文在我們頁面上，朗讀才做得到**
（瀏覽器要有文字才唸得出來），而讀完那一刻「我讀完了」就在同一頁上。

但**每次 render 都去抓**是錯的：

1. 讀經一格常常是 3-4 章 → 每次開頁面等 3-4 次外部來回
2. 那個站睡著或改版時，我們的頁面跟著空白
3. 全部才 1189 章，抓過一次就永遠不用再抓

所以：**先看快取，沒有才抓，抓到就存**。

## ★ 為什麼要真的解析 HTML，不用正則

那個平台的一節長這樣（詩篇 23:1）：

    <p class="verse" data-v="1">
      <span class="verse-num">1</span>
      <span class="verse-body">
        <span class="clause">〔<span class="anno" data-entity="大衛">大衛</span>的詩。</span>
        <span class="clause">〕耶和華是我的牧者．我必不至缺乏。</span>
      </span>
    </p>

裡面有**巢狀的標註**（人名、地名、概念）。用正則抓 `>([^<]+)<` 的話，
「大衛」會被切成獨立的一塊或整個掉出來 —— 而畫面上那一節看起來只是
少了兩個字，沒有人會發現。

★ 也不要用 `data-clause` 屬性湊 —— 那是那個站的內部實作細節，
  改版時我們會靜靜地拿到空字串。文字節點才是穩定的東西。

## ★ 抓不到不可以是空白

外部服務一定會有抓不到的時候。那時候要**照實說**，並且把「去那個站看」
的連結給他 —— 一片空白跟「這一章沒有經文」長得一模一樣。
"""
import re
import time
from html.parser import HTMLParser

TABLE = 'bible_chapters'

#  一次最多幫一格抓幾章。速讀最長的一格是 8 章（林前 9-16），
#  留一點餘裕；設上限是為了「資料壞掉時不要打爆對方的站」。
MAX_CHAPTERS_PER_DAY = 12

#  ── ★★ 讀的人**不可以**替全教會去暖快取 ────────────────────
#
#  這一段是量出來的，不是推論的（2026-09-22，使用者回報
#  「讀經模塊也比較慢」「跳 500 529」）：
#
#    | 量什麼 | 數字 |
#    |---|---|
#    | 計畫總章數 | **1190** |
#    | `bible_chapters` 已經有的 | **131（11%）** |
#    | 一格幾章 | 多數是 **3-4 章** |
#    | 那個平台冷啟動一次 | **2.3 秒**（熱的 0.2-0.5 秒） |
#
#  也就是說**89% 的「打開某一格」會在請求裡跑 3-4 次外部抓取**，
#  而每一次都佔著一條 gunicorn 執行緒（總共只有 8 條）。
#  再加上速讀提醒是**每天 09:00 推給所有人**的 —— 一百多支手機同時跳，
#  點進來的人全部落在同一頁、同時各握一條執行緒好幾秒。
#
#  ★ 所以慢的不是「經文很多」，是**這一頁在做背景該做的事**。
#    三道一起上：
#
#    1. `warm()` 由排程在背景把整份計畫抓回來 —— 抓過就永遠不用再抓
#    2. `cached_many()` 一次問完整格（原本一章一趟，4 章＝4 趟雪梨）
#    3. `INLINE_BUDGET` 封頂：就算對方今天很慢，也不可以把執行緒
#       押在那裡 —— 超過就照實說「還沒抓回來」並給外連

#  一次請求裡最多花幾秒在「去對方站抓」。★ 這是**整頁**的預算不是每章的：
#  每章各給 8 秒的話，4 章還是可以押住一條執行緒 32 秒。
INLINE_BUDGET = 6.0

#  ★ 讀的人在等，所以耐心要短；背景在跑，所以耐心可以長。
INLINE_TIMEOUT = 8
WARM_TIMEOUT = 20

#  ★ 每一次排程 tick 補幾章。1059 章 ÷ 40 ≈ 27 次 tick（約 7 小時）就補完，
#    而每次 tick 的背景工作只有十幾秒。開太大會讓背景跟前台搶那 0.1 顆 CPU。
WARM_PER_TICK = 40

#  ★ 對方站掛掉時不要整輪一直撞：連續失敗這麼多次就收工，下一次 tick 再說。
WARM_GIVE_UP_AFTER = 5

#  PostgREST 一次最多回 1000 筆，而整份計畫有 1190 章。
#  ★ 不分頁的話最後那 190 章**永遠**被當成「還沒抓」，每一輪都重抓一遍，
#    而 `bible_chapters` 看起來是滿的 —— 沒有任何症狀。
_PAGE = 1000

#  超過預算而還沒抓的那幾章。★ 跟「連不到」「抓到了但沒有經文」是
#  **第三件事**：這一章沒有壞，只是還沒輪到它 —— 稍後再開就有了。
#  講成前兩種的話，他會以為那一章讀不到而跑去問。
NOT_YET = '這一章還沒抓回來，稍後再打開就有了'


class _VerseParser(HTMLParser):
    """把 `<p class="verse" data-v="N">` 裡 `.verse-body` 的**純文字**取出來。

    ★ 只收 `.verse-body` 底下的文字，`.verse-num` 那個節號要跳過 ——
      不跳的話每一節開頭會多一個數字，而那看起來像經文的一部分。
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.verses = []
        self._v = None          # 目前在第幾節
        self._depth = 0         # 在 <p class="verse"> 裡的巢狀深度
        self._body = 0          # 在 .verse-body 裡的巢狀深度（0 = 不在）
        self._skip = 0          # 在 .verse-num 裡的巢狀深度
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get('class') or '').split()
        if self._v is None:
            if tag == 'p' and 'verse' in cls:
                try:
                    self._v = int(a.get('data-v'))
                except (TypeError, ValueError):
                    self._v = None
                    return
                self._depth = 1
                self._body = 0
                self._skip = 0
                self._buf = []
            return
        self._depth += 1
        if self._body:
            self._body += 1
        elif 'verse-body' in cls:
            self._body = 1
        if self._skip:
            self._skip += 1
        elif 'verse-num' in cls:
            self._skip = 1

    def handle_endtag(self, tag):
        if self._v is None:
            return
        if self._skip:
            self._skip -= 1
        if self._body:
            self._body -= 1
        self._depth -= 1
        if self._depth <= 0:
            text = _tidy(''.join(self._buf))
            if text:
                self.verses.append({'v': self._v, 'text': text})
            self._v = None
            self._buf = []

    def handle_data(self, data):
        #  ★ `self._body` 在 `.verse-body` 那一層是 1，更深是 2、3…
        #    只要 >0 就是在裡面。節號那段（_skip>0）不收。
        if self._v is not None and self._body and not self._skip:
            self._buf.append(data)


def _tidy(s):
    """把 HTML 排版帶來的空白收乾淨，但**不動經文本身的標點**。

    ★ 和合本用的是「．、」這種全形標點，不可以當成空白處理。
    """
    s = s.replace('　', ' ')
    s = re.sub(r'[ \t\r\n]+', ' ', s)
    return s.strip()


def parse_chapter(html):
    """整頁 HTML → [{'v': 1, 'text': '…'}, …]。解不出來回空陣列。

    ★ 回空陣列而不是丟例外：呼叫端要能分辨「這一章抓不到」和
      「整個功能壞了」，前者只影響一頁，後者不該讓人打不開網站。
    """
    if not html:
        return []
    #  只看 <main class="passage"> 那一段 —— 那個站的側邊欄裡有全部書卷的
    #  目錄，整頁掃的話會把導覽列的字也當成經文
    m = re.search(r'<main[^>]*class="[^"]*passage[^"]*"[^>]*>(.*?)</main>',
                  html, re.S | re.I)
    body = m.group(1) if m else html
    p = _VerseParser()
    try:
        p.feed(body)
        p.close()
    except Exception:
        return []
    #  ★ 照節號排序並去重：同一節出現兩次的話取第一次
    seen, out = set(), []
    for v in sorted(p.verses, key=lambda x: x['v']):
        if v['v'] in seen:
            continue
        seen.add(v['v'])
        out.append(v)
    return out


def chapter_url(book, chapter):
    """那一章在外部平台上的網址（走同一個後台設定）。"""
    from routes.bible_plan import read_url
    return read_url({'book': book, 'chapter_start': chapter})


# ─────────────────────────────────────────────────────────
#  抓 ＋ 快取
# ─────────────────────────────────────────────────────────

def _sb():
    from db import supabase
    return supabase


def _http_get(url, timeout=20):
    import requests
    resp = requests.get(url, timeout=timeout, headers={
        'User-Agent': 'church-registration-system/1.0',
    })
    resp.raise_for_status()
    #  ★ 一律自己用 UTF-8 解。那個站沒有在 header 帶 charset，
    #    `resp.text` 會退回 ISO-8859-1，拿到的每一個中文字都是壞的 ——
    #    而解析器照樣跑得完，只是每一節都變成亂碼。
    return resp.content.decode('utf-8', errors='replace')


def cached(book, chapter, sb=None):
    """快取裡有嗎。沒有或撈不到都回 None。"""
    sb = sb or _sb()
    try:
        rows = sb.table(TABLE).select('verses')\
            .eq('book', book).eq('chapter', int(chapter)).limit(1).execute().data or []
    except Exception:
        return None
    return rows[0]['verses'] if rows else None


def cached_many(book, chapters, sb=None):
    """一次問完這一格要的每一章。回 `{章: verses}`，撈不到就回 `{}`。

    ★★ 原本是一章一趟（`cached()`）—— 一格 4 章就是 **4 趟雪梨**，
      而那 4 趟是**串起來等的**。改成一趟之後這一頁少掉 3 次往返，
      而畫面上完全看不出差別（那正是往返次數危險的地方）。

    ★ 撈失敗回 `{}` 不是丟例外：退回「每一章各自再問一次」那條老路，
      慢一點但讀得到。這一頁的價值是經文，不是速度。
    """
    sb = sb or _sb()
    try:
        want = [int(c) for c in chapters]
    except (TypeError, ValueError):
        return {}
    if not want:
        return {}
    try:
        rows = sb.table(TABLE).select('chapter, verses')\
            .eq('book', book).in_('chapter', want).execute().data or []
    except Exception:
        return {}
    out = {}
    for r in rows:
        try:
            ch = int(r.get('chapter'))
        except (TypeError, ValueError):
            continue
        #  ★ 空的不算命中 —— 存進一筆空的本來就是禁止的（見 `store`），
        #    但萬一有一筆髒資料，當成命中的話那一章會**永遠**是空的。
        if r.get('verses'):
            out[ch] = r['verses']
    return out


def _int0(v):
    """空值明確算 0（結構守衛不准寫 `or 0`）。"""
    return 0 if v is None or v == '' else int(v)


def store(book, chapter, verses, url, sb=None):
    sb = sb or _sb()
    try:
        sb.table(TABLE).upsert({
            'book': book, 'chapter': int(chapter),
            'verses': verses, 'source': url,
        }).execute()
        return True
    except Exception:
        #  存不進去不影響這一次的閱讀 —— 下次再抓一遍就好
        return False


def get_chapter(book, chapter, fetch=None, sb=None, timeout=INLINE_TIMEOUT):
    """一章的經文。回 (verses, 錯誤說明)。

    先看快取；沒有才去抓，抓到就存起來。
    """
    hit = cached(book, chapter, sb=sb)
    if hit:
        return hit, None
    return fetch_chapter(book, chapter, fetch=fetch, sb=sb, timeout=timeout)


def fetch_chapter(book, chapter, fetch=None, sb=None, timeout=INLINE_TIMEOUT):
    """**不看快取**，直接去抓那一章（`get_passage` 和 `warm()` 共用）。

    ★ 抽出來是因為整格的快取已經一次問完了（`cached_many`）——
      再走 `get_chapter` 的話每一章會**又問一次**，等於白省。
    """
    url = chapter_url(book, chapter)
    if not url:
        return [], '還沒有設定經文來源網址'
    try:
        html = (fetch or _http_get)(url, timeout=timeout)
    except Exception as e:
        return [], f'連不到經文來源（{type(e).__name__}）'

    verses = parse_chapter(html)
    if not verses:
        #  ★ 抓到了但解不出來，跟連不上是**兩件事** —— 前者是對方改版
        #    或書名不對，後者是網路。講一樣的話就查不出是哪一種。
        return [], '抓到了，但這一頁裡沒有經文（書名或章數可能不對）'
    store(book, chapter, verses, url, sb=sb)
    return verses, None


def get_passage(day, fetch=None, sb=None, budget=INLINE_BUDGET):
    """一格（可能好幾章）的全部經文。

    回 [{'chapter': n, 'verses': [...], 'error': None|str, 'url': …}, …]

    ★ 一章抓不到不影響其他章 —— 讀經那一頁上會看到
      「創 1、創 2 有、創 3 這一章讀不到」，而不是整頁空白。

    ★★ **快取一次問完**（`cached_many`），沒抓過的才現抓，
      而且現抓**整格加起來**最多花 `budget` 秒。超過的照實說
      「還沒抓回來」並給外連 —— 背景的 `warm()` 會把它補上。

      沒有這道封頂的話：對方站今天很慢（冷啟動實測 2.3 秒），
      4 章就是一條 gunicorn 執行緒被押住十秒。全站只有 8 條，
      而速讀提醒是**同一個時間推給所有人**的。
    """
    book = day.get('book')
    lo = _int0(day.get('chapter_start'))
    hi = int(day.get('chapter_end') or lo)
    if not book or lo < 1:
        return []
    hi = min(hi, lo + MAX_CHAPTERS_PER_DAY - 1)
    wanted = list(range(lo, hi + 1))

    have = cached_many(book, wanted, sb=sb)
    started = time.monotonic()

    out = []
    for ch in wanted:
        verses, err = have.get(ch), None
        if not verses:
            if budget is not None and time.monotonic() - started >= budget:
                #  ★ 不是壞掉，是還沒輪到它。措辭要分得出來（見 NOT_YET）。
                verses, err = [], NOT_YET
            else:
                verses, err = fetch_chapter(book, ch, fetch=fetch, sb=sb)
        out.append({
            'chapter': ch,
            'verses': verses,
            'error': err,
            'url': chapter_url(book, ch),
        })
    return out


# ─────────────────────────────────────────────────────────
#  ★★ 背景暖快取：讀的人不該替全教會去抓
#
#  這一層的價值不是「快一點」，是**讓那一頁不再依賴另一個站活著**。
#  抓過一次就永遠不用再抓（1190 章，一次就好）——
#  模組開頭本來就是這樣寫的，只是一直沒有人去補，
#  於是它一個一個由**讀的人**補，而每個人都在等。
# ─────────────────────────────────────────────────────────

_warm_cursor = 0


def reset_for_tests():
    """清掉那個走到哪裡的游標（測試用；它活在行程記憶體裡）。"""
    global _warm_cursor
    _warm_cursor = 0


def plan_chapters(plan=None):
    """計畫裡的每一章，照計畫的順序。回 [(書, 章), …]

    ★ 照順序很重要：大家是從第一格往後讀的，所以**照順序補**
      等於總是先補到最多人明天要讀的那幾章。
    """
    if plan is None:
        from routes.bible_plan import days
        plan = days()
    seen, out = set(), []
    for d in plan or ():
        book = d.get('book')
        try:
            lo = _int0(d.get('chapter_start'))
        except (TypeError, ValueError):
            continue
        try:
            hi = int(d.get('chapter_end') or lo)
        except (TypeError, ValueError):
            hi = lo
        if not book or lo < 1:
            continue
        hi = min(hi, lo + MAX_CHAPTERS_PER_DAY - 1)
        for ch in range(lo, hi + 1):
            if (book, ch) not in seen:
                seen.add((book, ch))
                out.append((book, ch))
    return out


def cached_pairs(sb=None):
    """已經抓回來的每一章。回 `{(書, 章), …}`，撈不到回 `None`。

    ★★ **一定要分頁**：PostgREST 一次最多回 1000 筆，而整份計畫有 1190 章。
      不分頁的話最後那 190 章永遠被當成「還沒抓」，每一輪重抓一遍 ——
      而 `bible_chapters` 是滿的、畫面完全正常，沒有任何症狀。

    ★ 撈失敗回 `None` 不是空集合：空集合的意思是「一章都還沒抓」，
      那會讓這一輪把已經有的 40 章再抓一次。
      （同這個專案的老規矩：查不到 ≠ 0。）
    """
    sb = sb or _sb()
    out, start = set(), 0
    while True:
        try:
            rows = sb.table(TABLE).select('book, chapter')\
                .range(start, start + _PAGE - 1).execute().data or []
        except Exception:
            return None
        for r in rows:
            try:
                out.add((r.get('book'), int(r.get('chapter'))))
            except (TypeError, ValueError):
                continue
        if len(rows) < _PAGE:
            return out
        start += _PAGE


def warm(limit=WARM_PER_TICK, fetch=None, sb=None, plan=None):
    """把計畫裡還沒抓的章補回來（排程在背景叫）。

    ★★ 游標**一定要往前存**（`_warm_cursor = i`），而且是走過的都算，
      不是只算成功的：一章永遠抓不到時（書名不對之類），
      每一輪都會從它開始重撞，而後面的永遠補不到 ——
      `bible_chapters` 每一輪確實有在長，看起來完全正常。
      （這條是 mutation 驗過的：把 `i = _warm_cursor % total` 改成
      `i = 0`，或把存回去那一行拿掉，測試都會紅。）

    ★ 對方站掛掉時不要整輪一直撞（`WARM_GIVE_UP_AFTER`）——
      下一次 tick 是 15 分鐘以後，等得起。
    """
    global _warm_cursor
    chapters = plan_chapters(plan)
    if not chapters:
        return {'skipped': '讀不到計畫'}
    have = cached_pairs(sb=sb)
    if have is None:
        #  ★ 問不到「已經有哪些」就整輪不跑。當成空的話，
        #    這一輪會把已經抓過的再抓 40 章 —— 純浪費，而且會打對方的站。
        return {'skipped': '問不到已經抓過哪些章'}

    total = len(chapters)
    missing = sum(1 for c in chapters if c not in have)
    tried = stored = failed = 0
    misses = 0
    i = _warm_cursor % total
    for _ in range(total):
        if tried >= limit or misses >= WARM_GIVE_UP_AFTER:
            break
        book, ch = chapters[i]
        i = (i + 1) % total
        if (book, ch) in have:
            continue
        tried += 1
        verses, err = fetch_chapter(book, ch, fetch=fetch, sb=sb,
                                    timeout=WARM_TIMEOUT)
        if verses:
            stored += 1
            misses = 0
        else:
            failed += 1
            misses += 1
    _warm_cursor = i
    return {'total': total, 'missing': missing,
            'tried': tried, 'stored': stored, 'failed': failed}


def speech_text(sections):
    """朗讀要唸的整段文字（節號不唸）。

    ★ 節號不唸：連續聽的時候「一、二、三」會把句子切斷，
      而那個數字對聽的人沒有任何意義。
    """
    lines = []
    for s in sections:
        for v in s.get('verses') or []:
            t = (v.get('text') or '').strip()
            if t:
                lines.append(t)
    return lines
