"""主日信息：影片留在 YouTube，系統只負責「找得到、記得住」

## 為什麼不是同工手動貼

這類功能最常見的死法不是壞掉，是**沒有人繼續貼**：上線頭兩個月有人維護，
之後那一頁停在六月 —— 而畫面完全正常，看起來只像是「教會最近沒有聚會」。

影片本來就會上傳到 YouTube（那是既有的流程，不是為了這個系統多做的事）。
所以這裡的作法是**去讀那個既有流程的產物**，不要求任何人多做一個動作。

## ★★ 2026-09-14：公開 RSS 被關掉了，改讀播放清單頁

原本走的是 YouTube 每個頻道／播放清單都有的那條公開 Atom feed
（`/feeds/videos.xml?playlist_id=…`）。**那條路現在整個 404 了** ——
不是我們貼錯 id：連 YouTube 自己官方頻道的 channel_id 都回 404，
而不帶參數時回的是 400（＝那支處理程式還活著，只是不肯給了）。
這個容器和正式站（Render）兩個不同的網路都一樣，所以不是我們這邊的問題。

使用者看到的症狀是：新上傳的主日信息不會出現，後台按「立刻重新抓取」
三條清單全部寫「抓不到（HTTPError）」。

**現在改成讀播放清單頁背後那支 `youtubei/v1/browse`** ——
那是 YouTube 自己的網頁在用的，一樣不需要 API 金鑰、沒有配額。

★ 仍然**不用 YouTube Data API**：那要一把存在 Render 環境變數裡、
  會過期、壞掉時沒有人知道的金鑰，而我們要的只有「影片 id ＋ 標題」。

### ★ 這條路換來的和賠掉的

| | |
|---|---|
| 賺到 | 一次拿得到**整個清單**（最多 100 部），不再只有最近十幾部 |
| 賠掉 | **拿不到上傳時間了**（那個欄位要登入才給），新影片的 `published_at` 會是空的 |

★ 賠掉的那一項**影響很小**，因為日期本來就是從標題結尾讀的
（`preached_date`，實測 43 部全都有）。但它有一個後果要記住：
標題裡沒有日期、又沒有上傳時間的那一部會落到「日期不明」那一組 ——
**那是對的**（不要猜），後台的 `date_source_report` 看得到。

### ★★ 這是在讀別人的網頁，所以「200 但解不出東西」＝ 壞了

RSS 是一份合約，`browse` 不是 —— YouTube 改版面的時候，我們會拿到
一個漂亮的 200，裡面一部影片都沒有。那跟「這個清單是空的」長得一模一樣。
所以解析器**同時認新舊兩種形狀**（`lockupViewModel` 和
`playlistVideoRenderer`），而且解不出任何影片時後台要**把兩種可能都講出來**。

## ★ 抓失敗不可以是靜悄悄的

排程在背景跑，失敗了沒有人看得到 —— 而症狀是「首頁的主日信息停在上個月」，
跟「教會這個月沒錄影」長得一模一樣。所以後台有一顆**立刻重新抓取**，
當場跑一次並把結果照實講出來（抓到幾部、新增幾部、或是哪裡錯了）。
"""
import re

TABLE = 'sermons'

#  一次最多收幾部。`browse` 一頁就是 100 部（我們**不追 continuation**：
#  一年的播放清單不會超過一頁，而追下去等於把整個頻道的歷史一次搬進來）。
#  ★ 這個數字不是分頁，是「資料壞掉時不要寫爆」的上限。
MAX_ENTRIES = 100

#  排程多久抓一次。主日一週一次，抓太密只是浪費 —— 六小時足夠讓
#  「禮拜天中午上傳、禮拜天下午就看得到」。
REFRESH_HOURS = 6

#  ── YouTube 自己的網頁在用的那支端點 ──────────────
#
#  ★ 這把 key 不是祕密，也不是「我們的」—— 它就寫在
#    youtube.com 每一頁的原始碼裡（`INNERTUBE_API_KEY`），
#    所有人拿到的都是同一把。所以它**不進環境變數**：
#    放進去會讓人以為那是一個要保管、會過期的東西。
INNERTUBE_URL = 'https://www.youtube.com/youtubei/v1/browse'
INNERTUBE_KEY = 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8'
INNERTUBE_CLIENT_VERSION = '2.20260911.01.00'


# ─────────────────────────────────────────────────────────
#  網址 → feed（純函式，不連網）
# ─────────────────────────────────────────────────────────

def uploads_list_id(channel_id):
    """頻道 ID → 那個頻道的「所有上傳」播放清單 ID。

    ★ YouTube 的老規矩：`UC…` 換成 `UU…` 就是那個頻道的上傳清單。
      這一步讓「頻道」和「播放清單」在底下變成同一件事 ——
      少了它，頻道要走另一支 API（要帶一段 base64 的 protobuf 去選
      「影片」分頁），那是另一條會壞而我們驗不到的路。
    """
    cid = (channel_id or '').strip()
    if not re.fullmatch(r'UC[A-Za-z0-9_-]{20,}', cid):
        return None
    return 'UU' + cid[2:]


def list_id_for(pasted):
    """使用者貼的 YouTube 網址 → 要去讀的**播放清單 ID**。認不出來回 None。

    ★ 認不出來一定要回 None，不可以猜一個。猜錯的話會抓到 0 部，
      而症狀是「一部影片都沒有」—— 那跟「清單上真的沒有影片」一樣，
      沒有人分得出來。

    支援使用者實際會複製到的幾種形狀：

        https://www.youtube.com/playlist?list=PLxxxx        播放清單
        https://www.youtube.com/watch?v=abc&list=PLxxxx     從影片頁複製的
        https://www.youtube.com/channel/UCxxxx              頻道（→ 上傳清單）
        PLxxxx / UCxxxx                                     只貼 ID
        https://www.youtube.com/feeds/videos.xml?...        以前那條 RSS

    ★ 最後那一行是**舊設定的相容**：RSS 還在的時候，後台的提示要他
      「直接貼 feed 網址也可以」，所以有人的設定裡可能就是那個。
      不認的話，那一行會在他什麼都沒改的情況下變成紅字。

    ★ `@handle`、`/c/名字`、`/user/名字` 這三種**認不出來** ——
      它們沒有把 channel_id 寫在網址裡，要連網去查（見 `lookup_needed`）。
    """
    s = (pasted or '').strip()
    if not s:
        return None

    #  只貼 ID 的情況
    if re.fullmatch(r'PL[A-Za-z0-9_-]{10,}', s):
        return s
    if re.fullmatch(r'UU[A-Za-z0-9_-]{20,}', s):
        return s
    if re.fullmatch(r'UC[A-Za-z0-9_-]{20,}', s):
        return uploads_list_id(s)

    #  ★ 播放清單優先於頻道：`/watch?v=…&list=…` 兩個都在的時候，
    #    他貼那條連結的意思是「這個清單」，不是「這部影片所屬的頻道」。
    #    舊的 feed 網址（`?playlist_id=PL…`）也是這一條接住的。
    m = re.search(r'[?&](?:list|playlist_id)=((?:PL|UU)[A-Za-z0-9_-]{10,})', s)
    if m:
        return m.group(1)

    m = re.search(r'(?:/channel/|[?&]channel_id=)(UC[A-Za-z0-9_-]{20,})', s)
    if m:
        return uploads_list_id(m.group(1))

    return None


def feed_sources(block):
    """一整塊設定文字（一行一個清單）→ 每一行各自的狀態。

    ★ 為什麼是多條：教會的信息影片是**一年一個播放清單**
      （2026 一個、2025 一個、2024 一個）。只收一條的話，
      每年一月要有人記得回來換 —— 而忘了換的症狀是
      「首頁的主日信息停在去年十二月」，跟「最近沒有聚會」長得一樣。

    ★ 為什麼回的是每一行的狀態，不是一份乾淨的清單：
      三條裡有一條打錯時，只回「成功的那兩條」等於**默默吞掉**第三條，
      而後台看起來完全正常（有影片、有清單）。少的那一年
      要等到有人去找去年的講道才會發現。所以壞掉的那一行也要回來，
      帶著它自己的理由，畫面上就顯示在那一行旁邊。

    回 [{'raw': 原文, 'list_id': 清單 ID 或 None, 'problem': None|'lookup'|'unknown'}]
    """
    out, seen = [], set()
    for line in re.split(r'[\r\n,]+', block or ''):
        raw = line.strip()
        if not raw:
            continue
        list_id = list_id_for(raw)
        if list_id:
            problem = None
        elif lookup_needed(raw):
            problem = 'lookup'
        else:
            problem = 'unknown'
        #  同一個清單貼兩次只留一份 —— 重複抓不會壞，但畫面上
        #  兩行一模一樣會讓人以為自己看錯了
        if list_id and list_id in seen:
            continue
        if list_id:
            seen.add(list_id)
        out.append({'raw': raw, 'list_id': list_id, 'problem': problem})
    return out


def lookup_needed(pasted):
    """這是一個「要連網才查得到 channel_id」的網址嗎（@handle / c / user）。

    分成兩支是為了讓後台講得出**不一樣的話**：
    認不出來 → 「這不像 YouTube 的網址」；
    要查 → 「認得出來，我去查一下」。合成一句的話兩種情況都變成
    「網址有問題」，而其中一種其實完全正常。
    """
    s = (pasted or '').strip()
    if not s or list_id_for(s):
        return False
    return bool(re.search(r'youtube\.com/(@[^/?#]+|c/[^/?#]+|user/[^/?#]+)', s)
                or re.fullmatch(r'@[\w.-]+', s))


def channel_id_in(page_html):
    """從頻道頁的 HTML 裡挖出 channel_id。挖不到回 None。

    ★ 這是 `@handle` 唯一的解法 —— YouTube 沒有公開的「handle → id」端點，
      而 handle 正是使用者從瀏覽器網址列複製到的東西。
    """
    if not page_html:
        return None
    for pat in (r'"channelId"\s*:\s*"(UC[A-Za-z0-9_-]{20,})"',
                r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]{20,})"',
                r'/channel/(UC[A-Za-z0-9_-]{20,})'):
        m = re.search(pat, page_html)
        if m:
            return m.group(1)
    return None


def watch_url(video_id):
    return f'https://www.youtube.com/watch?v={video_id}'


def thumbnail_url(video_id):
    """縮圖用**推導**的，不存資料庫。

    YouTube 的縮圖網址是 video_id 的函數，存一份等於存一個會過期的複本 ——
    而過期的症狀是整排破圖，看起來像整個功能壞了。
    """
    return f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'


# ─────────────────────────────────────────────────────────
#  feed → 影片（純函式，不連網）
# ─────────────────────────────────────────────────────────

def _text_of(node):
    """YouTube 的 JSON 裡「一段文字」有三種形狀，一律收成字串。

    新的 view model 是 `{'content': '…'}`，舊的 renderer 是
    `{'runs': [{'text': …}]}` 或 `{'simpleText': …}`。
    ★ 三種都認：改版的時候換的是外層的名字，這一層兩種會並存一陣子。
    """
    if not isinstance(node, dict):
        return ''
    if isinstance(node.get('content'), str):
        return node['content'].strip()
    if isinstance(node.get('simpleText'), str):
        return node['simpleText'].strip()
    runs = node.get('runs')
    if isinstance(runs, list):
        return ''.join(r.get('text') or '' for r in runs
                       if isinstance(r, dict)).strip()
    return ''


def _walk(node, want, out):
    """整棵 JSON 樹裡所有 key 叫 `want` 的東西。

    ★ 用走訪而不是照著路徑取值：那條路徑（tabs[0] → sectionList →
      itemSection → …）是 YouTube 的版面結構，它比 renderer 的名字
      更常變，而**照路徑取值失敗時拿到的是 0 部影片，不是例外**。
    """
    if isinstance(node, dict):
        if want in node:
            out.append(node[want])
        for v in node.values():
            _walk(v, want, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, want, out)
    return out


def parse_playlist(data):
    """`browse` 回來的 JSON → [{video_id, title, published_at}]。

    ★ `published_at` 一律是 None —— 這條路拿不到上傳時間（見模組開頭）。
      **不要拿那個「3 天前」的相對時間去換算**：它會隨語言變、
      而且只到「個月前」的精度，換算出來的日期看起來完全正常，
      只是可能差幾十天，而分組是按週的。

    ★ 解不出來回空陣列而不是丟例外：呼叫端是排程，而「今天讀不到」
      不可以變成「把已經存好的清空」。空陣列的意思由呼叫端解讀
      （見 `refresh`：200 但 0 部要當成問題講出來）。
    """
    if not isinstance(data, dict):
        return []

    rows, seen = [], set()

    def take(vid, title):
        vid = (vid or '').strip()
        title = (title or '').strip()
        #  ★ 少了 id 或標題的那一筆整筆跳過，不要補一個假的 ——
        #    標題空白的卡片點下去會是一部不存在的影片
        if not vid or not title or vid in seen:
            return
        seen.add(vid)
        rows.append({'video_id': vid, 'title': title, 'published_at': None})

    #  新版面（2026-）：lockupViewModel
    for lv in _walk(data, 'lockupViewModel', []):
        if not isinstance(lv, dict):
            continue
        #  ★ 只收影片。同一種 lockup 也用來畫播放清單、頻道、廣告，
        #    不篩的話清單頁側邊那些東西會被當成講道存進來。
        if lv.get('contentType') != 'LOCKUP_CONTENT_TYPE_VIDEO':
            continue
        meta = (lv.get('metadata') or {}).get('lockupMetadataViewModel') or {}
        take(lv.get('contentId'), _text_of(meta.get('title')))

    #  舊版面：playlistVideoRenderer（YouTube 不是所有出口都同時改版，
    #  而且兩種並存時多認一種不會有壞處 —— `take` 自己會去重）
    for r in _walk(data, 'playlistVideoRenderer', []):
        if isinstance(r, dict):
            take(r.get('videoId'), _text_of(r.get('title')))

    return rows[:MAX_ENTRIES]


#  哪幾欄是 **YouTube 給的**（抓一次就該跟著它走），
#  哪幾欄是 **人打的**（永遠不可以被抓取蓋掉）。
#
#  ★★ 原本的規則是「只新增、不更新」，理由沒有錯（同工補的講員／經文
#    會被 YouTube 的標題默默洗掉），但它**擋得太寬**：連 YouTube 自己
#    那幾欄也不更新，於是——
#
#      使用者：「主日信息 我在原本 YouTube 標題打錯有重改
#               可是系統上面沒有跟著修改」
#
#    而標題不只是標題：**講道日期是從標題結尾讀出來的**
#    （`preached_date`）。標題裡的日期打錯又改好了，系統這邊會
#    **永遠停在錯的那一週**，而那一組看起來完全正常。
#
#  ★ 所以規則收緊成：**YouTube 的欄位跟著 YouTube 走，人打的永遠不碰。**
FEED_FIELDS = ('title', 'published_at')
HUMAN_FIELDS = ('speaker', 'scripture', 'is_hidden')


def merge_new(fetched, known_ids):
    """抓回來的 － 已經存過的 ＝ 這次要新增的。"""
    known = set(known_ids or ())
    fresh, seen = [], set()
    for row in fetched:
        vid = row.get('video_id')
        if not vid or vid in known or vid in seen:
            continue
        seen.add(vid)
        fresh.append(row)
    return fresh


def merge_changed(fetched, known_rows):
    """已經存過、而且 **YouTube 那幾欄真的變了** 的，回 `(video_id, patch)`。

    `known_rows`: `{video_id: {title, published_at}}`

    ★ 只有**真的不一樣**才回 —— 一樣也照寫的話，每 6 小時就把整張表
      重寫一次，而且後台會報「更新了 60 部」，那個數字沒有意義。

    ★ `patch` 裡**只會有 `FEED_FIELDS`**。講員／經文／隱藏是人打的，
      這條路一個字都不碰（有測試守著）。
    """
    known = known_rows or {}
    out, seen = [], set()
    for row in fetched:
        vid = row.get('video_id')
        if not vid or vid in seen or vid not in known:
            continue
        seen.add(vid)
        before = known[vid] or {}
        #  ★★ 兩道：白名單（只有 FEED_FIELDS）**再加上**明確排除人打的那幾欄。
        #
        #    第二道看起來是多的 —— 兩張表本來就不相交，而且 feed 裡
        #    根本沒有 speaker／scripture。但那正是問題：
        #    **這條守衛是靠「feed 剛好沒有那些欄位」成立的**，不是靠規則。
        #    mutation 當場證明了：把 FEED_FIELDS 改成包含 speaker、
        #    測試全部還是綠的。哪天 `parse_feed` 多解析一個欄位，
        #    同工補的字就會被默默洗掉，而畫面完全正常。
        patch = {f: row.get(f) for f in FEED_FIELDS
                 if f not in HUMAN_FIELDS
                 and row.get(f) is not None and row.get(f) != before.get(f)}
        if patch:
            out.append((vid, patch))
    return out


# ─────────────────────────────────────────────────────────
#  以下會碰網路／資料庫
# ─────────────────────────────────────────────────────────

def configured_block():
    """後台設定裡那一塊（一行一個播放清單）。"""
    import settings_store
    return settings_store.get('sermon_playlists') or ''


def _http_get(url, timeout=10):
    import requests
    resp = requests.get(url, timeout=timeout, headers={
        #  ★ 不帶 UA 的話 YouTube 有時候回一頁「請確認你是人類」，
        #    而那一頁是 200 —— 解析出 0 部影片，看起來像頻道是空的。
        'User-Agent': BROWSER_UA,
    })
    resp.raise_for_status()
    return resp.text


#  ★ 這裡要裝成瀏覽器。不是為了繞過什麼 —— `youtubei` 就是瀏覽器在打的，
#    帶一個「church-registration-system」的 UA 只會拿到同意頁或 429。
BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')


def browse_payload(list_id):
    """要 POST 給 `youtubei/v1/browse` 的內容（純函式，方便測）。

    ★ `browseId` 前面那個 `VL` 是「這是一個播放清單」的意思 ——
      少了它會拿到一個 200 而裡面什麼都沒有。
    """
    return {
        'context': {'client': {
            'clientName': 'WEB',
            'clientVersion': INNERTUBE_CLIENT_VERSION,
            #  ★ 指定語言／地區：不指定的話 YouTube 會依 IP 猜，
            #    而 Render 在新加坡 —— 標題不會變，但同意頁會。
            'hl': 'zh-TW', 'gl': 'TW',
        }},
        'browseId': 'VL' + list_id,
    }


def _http_post_json(url, payload, timeout=10):
    import requests
    resp = requests.post(url, json=payload, timeout=timeout, headers={
        'User-Agent': BROWSER_UA,
        'Content-Type': 'application/json',
        'Accept-Language': 'zh-TW,zh;q=0.9',
    })
    resp.raise_for_status()
    return resp.json()


def fetch_entries(list_id, post=None):
    """一個播放清單 → [{video_id, title, published_at}]。連不上會丟例外。"""
    post = post or _http_post_json
    url = f'{INNERTUBE_URL}?key={INNERTUBE_KEY}&prettyPrint=false'
    return parse_playlist(post(url, browse_payload(list_id)))


def why(exc):
    """例外 → 一句**查得下去**的話。

    ★★ 原本這裡是 `type(e).__name__`，於是三條清單一起壞掉時，
      後台寫的是三行「抓不到（HTTPError）」—— 而那句話裡沒有任何
      可以往下查的東西。403（被擋）、404（清單不見了或網址錯）、
      429（太頻繁）三種的處理方式完全不一樣。
      推播那邊踩過同一個坑（`push.try_send_one` 現在回的是狀態碼）。
    """
    code = getattr(getattr(exc, 'response', None), 'status_code', None)
    return f'HTTP {code}' if code else type(exc).__name__


def resolve_list_id(source, fetch=None):
    """一筆設定 → 可以讀的播放清單 ID。回 (list_id, 錯誤說明)。

    `source` 是 `feed_sources()` 回來的那種 dict。
    `@handle` 這種要多連一次網去查 channel_id（YouTube 沒有公開的
    handle → id 端點，而 handle 正是使用者會複製到的東西）。
    """
    fetch = fetch or _http_get
    if source.get('list_id'):
        return source['list_id'], None
    if source.get('problem') == 'unknown':
        return None, '這不像 YouTube 的播放清單或頻道網址'
    raw = source['raw']
    url = raw if raw.startswith('http') else f'https://www.youtube.com/{raw.lstrip("/")}'
    try:
        cid = channel_id_in(fetch(url))
    except Exception as e:
        return None, f'連不上這個頻道頁（{why(e)}）'
    if not cid:
        return None, '這個頻道頁裡找不到頻道 ID，改貼「播放清單」的網址比較準'
    return uploads_list_id(cid), None


def known_rows(sb=None):
    """`{video_id: {title, published_at}}`。

    ★ 跟 `known_video_ids` 是**同一次查詢** —— 為了比對標題有沒有改，
      多撈兩欄就夠了，不用多跑一趟。
    """
    sb = sb or _sb()
    rows = sb.table(TABLE).select('video_id, title, published_at')\
        .execute().data or []
    return {r['video_id']: {'title': r.get('title'),
                            'published_at': r.get('published_at')}
            for r in rows if r.get('video_id')}


def known_video_ids(sb=None):
    return set(known_rows(sb))


def _sb():
    from db import supabase
    return supabase


#  一次送幾列進資料庫。
#
#  ★★ 為什麼要分批：換掉 RSS 之後一次拿得到**整個播放清單**
#    （三條加起來 140 部），而第一次抓會把沒看過的全部補進來。
#    一列一趟的話那是 140 次往返 —— 同工按下「立刻重新抓取」會等到
#    逾時，而畫面上只會是「抓取中…」卡住，看起來像功能壞了。
INSERT_CHUNK = 25


def _insert_all(sb, rows, result):
    """把新影片寫進去。整批失敗時**逐筆再試一次**。

    ★ 分批換到的是速度，但它也帶回了一個老問題：**一列壞掉整批都進不去**
      （標題有奇怪字元、某一欄超長…），而下一次抓還是同一批、還是全掛。
      所以整批失敗就退回一筆一筆寫 —— 那時候慢沒關係，重點是
      **把壞的那一筆指出來**，其他的照樣存進去。
    """
    for i in range(0, len(rows), INSERT_CHUNK):
        part = rows[i:i + INSERT_CHUNK]
        try:
            sb.table(TABLE).insert(part).execute()
            result['added'] += len(part)
            result['titles'].extend(r['title'] for r in part)
            continue
        except Exception:
            pass
        for row in part:
            try:
                sb.table(TABLE).insert(row).execute()
                result['added'] += 1
                result['titles'].append(row['title'])
            except Exception as e:
                result['problems'].append(f'{row["title"]} → 存不進去（{why(e)}）')


def refresh(block=None, fetch=None, post=None, sb=None):
    """抓一輪，把沒看過的存進來。回一份**照實說**的結果。

    ★ 回傳的東西就是後台畫面上會顯示的東西。「成功／失敗」一個布林值
      不夠用：三個清單裡有一個掛掉時，那是「大致成功」，
      而使用者要知道的是**哪一個**掛了。
    """
    fetch = fetch or _http_get
    post = post or _http_post_json
    sb = sb or _sb()
    block = configured_block() if block is None else block

    result = {'sources': 0, 'fetched': 0, 'added': 0, 'updated': 0,
              'problems': [], 'titles': [], 'updated_titles': []}
    sources = feed_sources(block)
    result['sources'] = len(sources)
    if not sources:
        result['problems'].append('還沒有設定任何播放清單')
        return result

    entries = []
    for src in sources:
        list_id, err = resolve_list_id(src, fetch=fetch)
        if err:
            result['problems'].append(f'{src["raw"]} → {err}')
            continue
        try:
            got = fetch_entries(list_id, post=post)
        except Exception as e:
            result['problems'].append(f'{src["raw"]} → 抓不到（{why(e)}）')
            continue
        if not got:
            #  ★★ 200 但一部都沒有：**兩種可能，而且處理方式相反**。
            #    清單真的是空的（他自己去 YouTube 看一眼就知道），
            #    或者 YouTube 換了版面（那要改程式）。
            #    只講其中一種的話，另一種會被當成「沒事」放著。
            result['problems'].append(
                f'{src["raw"]} → 讀到了，但沒解析出任何影片'
                '（這個清單是空的，或是 YouTube 換了版面）')
        entries.extend(got)
    result['fetched'] = len(entries)

    try:
        known = known_rows(sb)
    except Exception as e:
        result['problems'].append(f'讀不到已存的清單（{why(e)}），這次不寫入')
        return result

    _insert_all(sb, merge_new(entries, set(known)), result)

    #  ── 標題在 YouTube 上改過的，這邊跟著改 ─────────
    #
    #  ★★ 只改 `FEED_FIELDS`。講員／經文／隱藏是人打的，
    #    這條路一個字都不碰。
    #  ★ 改了要**講出來**（`updated_titles`） —— 默默改掉的話，
    #    同工下次看到不一樣的字會以為自己記錯了。
    for vid, patch in merge_changed(entries, known):
        try:
            sb.table(TABLE).update(patch).eq('video_id', vid).execute()
            result['updated'] += 1
            if 'title' in patch:
                result['updated_titles'].append(patch['title'])
        except Exception as e:
            result['problems'].append(
                f'{patch.get("title") or vid} → 改不進去（{why(e)}）')
    return result


#  一次最多從資料庫撈幾列。整張表現在 43 列，而且一週長一列 ——
#  這個數字是「不要有一天變成撈一萬列」的上限，不是分頁。
FETCH_MAX = 500


def recent(limit=30, include_hidden=False, sb=None):
    """前台列表用：**照講道的日子**新的在前面。

    ## ★★ 為什麼不是 `order('published_at')` 了

    兩個理由，第二個是新的：

    1. `published_at` 是**上傳時間**，而這一頁回答的是「我要聽哪一週的
       講道」—— 那兩個差過三天（見 `preached_date`）。原本排序用上傳
       時間、分組用講道日期，**兩邊各自看都正常**，只有剛好跨週的
       那一部會排在錯的地方
    2. ★ 現在拿不到上傳時間了（見模組開頭），新的那幾列
       `published_at` 是 NULL。Postgres 的 `DESC` 預設把 NULL 排**最前面**
       —— 剛上傳的那部排第一剛好是對的，但**任何一部後來補進來的舊片
       也會跳到最上面**，而首頁那張「最近的主日信息」就會變成 2024 年的

    所以排序改在 Python 裡做，用的是 `preached_date`。
    ★ 整張表 43 列，撈回來排序一次的成本比「兩種日期不一致」小得多。
    """
    from datetime import date
    sb = sb or _sb()
    #  ★ 資料庫這一層照 `created_at` 取（NOT NULL，永遠排得出來），
    #    只是為了在資料異常變多時有個上限；真正的順序在下面。
    q = sb.table(TABLE).select('*')\
        .order('created_at', desc=True).limit(FETCH_MAX)
    if not include_hidden:
        q = q.eq('is_hidden', False)
    rows = q.execute().data or []
    #  算不出日期的排最後（跟 `group_by_week` 一致：不丟掉，也不亂塞）
    rows.sort(key=lambda r: preached_date(r) or date.min, reverse=True)
    rows = rows[:limit]
    for r in rows:
        r['watch_url'] = watch_url(r['video_id'])
        r['thumbnail_url'] = thumbnail_url(r['video_id'])
    return rows


def latest(sb=None):
    """首頁那一張「最近的主日信息」。沒有就回 None。"""
    rows = recent(limit=1, sb=sb)
    return rows[0] if rows else None


#  日期不明的那一組排在最後。用一個不可能跟 'YYYY-MM-DD' 相撞的 key。
UNDATED_KEY = ''
UNDATED_LABEL = '日期不明'


#  標題結尾的日期。教會的命名就是這樣：
#
#      【主日信息】主題:✟智慧的禱告✟回應詩歌♫我心屬於祢♫ 講員: 蕭夢熊 牧師2026-09-06
#
#  使用者：「每部主日影片的標題後面都是有日期的」。
#  ★ 對著三個播放清單實際抓過 43 部驗證：**43 部全都有**，一部都沒漏。
TITLE_DATE = re.compile(r'(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?\s*$')


def preached_date(row):
    """這篇道是**哪一天講的**（台北 date）。算不出來回 None。

    ## ★★ 為什麼不能直接用 `published_at`

    `published_at` 是**上傳到 YouTube 的時間**，不是講道的日子。
    同工不一定當天傳 —— 實際資料裡就有一部：

        標題寫 2025-12-07，上傳是 2025-12-10

    那一次剛好還在同一週（12/7 是主日，12/10 是週三），所以分組看不出問題。
    但**晚傳超過六天就會掉到下一週**，而那一組看起來完全正常，
    只是名字是錯的日子 —— 要去翻 YouTube 才會發現。

    ★ 標題的日期是**人打上去的、代表那個主日**，上傳時間是機器的。
      要哪一個，看這一組是拿來回答什麼問題：這裡問的是
      「我要聽**哪一週**的講道」，所以是講道的日子。

    ## ★ 抓不到就退回上傳時間，不要猜

    命名哪天改了、或有一部漏打日期時，退回上傳時間**還是大致對的**
    （同工多半當天或隔天傳）。整組丟掉或標成「日期不明」的話，
    使用者失去的是一部他明明看得到的影片。
    """
    m = TITLE_DATE.search(str(row.get('title') or ''))
    if m:
        from datetime import date
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass                      # 例如標題打成 2026-13-45
    from routes.tw_time import to_taipei
    dt = to_taipei(row.get('published_at'))
    return dt.date() if dt else None


#  標題裡的「主題」。教會的命名是：
#
#      【主日信息】主題:✟智慧的禱告✟回應詩歌♫我心屬於祢♫ 講員: 蕭夢熊 牧師2026-09-06
#
#  ★ 對著三個真的播放清單抓 140 部驗過：**139 部**都是這個形狀
#    （剩下那一部叫「2025-09-21受洗」，連 `主題` 兩個字都沒有）。
#  ★ 冒號要收全形和半形 —— 那是人打的，兩種都會出現。
TITLE_TOPIC = re.compile(r'主題\s*[:：]\s*✟\s*(.+?)\s*✟')


def _plain_title(title):
    """退而求其次時要顯示的字：去掉 `【主日信息】` 和**結尾的日期**。

    ★ 日期一定要去掉 —— 那一行前面已經印了一個日期（`2026/9/6`），
      不去掉的話畫面上會變成「2026/9/6 … 2026-09-06」，
      看起來像系統把同一件事講了兩次。
    """
    t = re.sub(r'^\s*【[^】]*】\s*', '', str(title or ''))
    t = TITLE_DATE.sub('', t)
    return t.strip().rstrip('，,、 ').strip()


def topic(row):
    """這一部**在講什麼**（收合起來那一行要顯示的字）。

    ## ★ 為什麼要有這一支

    使用者：「列表可以把標題弄上去嗎? 不要只有單純的日期」。
    收合起來只有一排日期時，要挑哪一週還是得一個一個展開來看 ——
    而「我要聽哪週的講道」正是這一頁存在的理由。

    ## ★★ 抓不到主題**不可以回空字串**

    那一行會退回成只有日期（＝現在這樣），而且**畫面上完全正常** ——
    沒有人會發現是這一部的命名不一樣，只會覺得這個功能時好時壞。
    所以抓不到就退回整個標題（去掉 `【】` 和結尾的日期）。

    ★ 這裡**不碰資料庫**：主題是從標題算出來的，存一份等於多一個
      「標題改了而主題沒改」的來源，而兩邊各自看都正常。
      跟 `preached_date`、`thumbnail_url` 同一條規矩。
    """
    title = str(row.get('title') or '').strip()
    if not title:
        return ''
    m = TITLE_TOPIC.search(title)
    if m:
        #  ★ 收掉多餘空白：人打的字裡面常常有「✟ 智慧的禱告✟」那種空格
        got = re.sub(r'\s+', ' ', m.group(1)).strip()
        if got:
            return got
    return _plain_title(title) or title


def date_source_report(rows):
    """每一部的日期是**從標題讀到的**、還是**退回上傳時間**的。

    ## ★★ 為什麼這一頁要看得到這件事

    `preached_date` 讀不到標題的日期時會安靜地退回 `published_at` ——
    那是對的行為（總比整組不見好），但它也代表：**教會哪天改了命名，
    整頁的日期會悄悄換一個來源**，而畫面上完全正常
    （每一組還是一個正常的日期，只是可能差幾天）。

    這正是這個專案反覆出現的那一類：沒有壞，只是說的是假的。
    所以後台照實列出來 —— 有幾部是推的、是哪幾部。

    ★ 「有幾部用推的」**不是錯誤**（偶爾一部漏打日期很正常），
      所以不要紅字。它是一個**數字**：平常是 0，哪天變成一整批，
      就知道命名改了。
    """
    out = {'from_title': 0, 'from_upload': 0, 'unknown': 0, 'guessed': []}
    for r in rows or ():
        if TITLE_DATE.search(str(r.get('title') or '')):
            out['from_title'] += 1
        elif preached_date(r):
            out['from_upload'] += 1
            out['guessed'].append(r.get('title') or r.get('video_id'))
        else:
            out['unknown'] += 1
            out['guessed'].append(r.get('title') or r.get('video_id'))
    return out


def week_start(dt):
    """那一天所屬那一週的**主日**（台北時間的 date）。

    ★ 一週從**週日**開始，不是週一：這是主日信息，那一組的名字就是
      那個主日。用 ISO 週（週一開始）的話，週日講的道會被歸到
      **前一週**，而每一組看起來都還是正常的一週。

    ★ 傳進來的是**講道的日子**（`preached_date`），不是上傳時間 ——
      理由見那一支的說明。

    ★ 收 `date` 或 `datetime` 都可以，一律回 `date`。
    """
    from datetime import datetime, timedelta
    if isinstance(dt, datetime):
        dt = dt.date()
    #  Python 的 weekday()：週一=0 … 週日=6。往回推到那一週的週日。
    return dt - timedelta(days=(dt.weekday() + 1) % 7)


def group_by_week(rows):
    """把影片按**週**分組（一組＝一個主日），新的在前面。

    使用者的原話：「主日影片應該一週一組」。

    ## ★ 我上一版做成「按月」，而那是我自己想的

    上一版的註解裡我還「論證」過按週不好（「一組剛好 1 部，那不是分組，
    是在每一部上面加一層殼」）。**那個論證是坐在這裡想出來的** ——
    而他知道教會的影片實際長什麼樣，我不知道。

    ★ 而且我想錯的地方很具體：我把「一組 1 部」想成**缺點**，
      但收合起來之後，一組 1 部正是它的價值 —— 整頁變成一條
      **一週一行的日期索引**，而那正是「我要聽哪週的講道」要的東西。
      按月的話，要先展開一個月、再在裡面找那一週。

    ## ★ 用的是**講道的日子**，不是上傳時間

    見 `preached_date`：標題結尾的日期是人打的、代表那個主日，
    `published_at` 是同工哪天傳上去的。實際資料裡就差過三天。

    退回 `published_at` 時仍然一律走 `tw_time` —— 它存的是 UTC，
    切字串的話**台北時間每天的頭 8 小時會被算成前一天**，
    而週日早上的主日信息剛好落在那個區間，會整組掉到上一週去，
    而每一組看起來都還是正常的一週。

    ## ★ 算不出日期的不丟掉，也不塞進某一週

    丟掉的話那一部**從此看不到**，而清單看起來完全正常。

    回傳 `[{'key', 'label', 'count', 'items'}]`，每一筆多一個
    `day_label`（例如 `9/6`）給畫面用。
    """
    buckets = {}
    for r in rows:
        d = preached_date(r)
        if d:
            sunday = week_start(d)
            key = sunday.isoformat()
            label = '%d/%d/%d' % (sunday.year, sunday.month, sunday.day)
            r['day_label'] = '%d/%d' % (d.month, d.day)
        else:
            key, label = UNDATED_KEY, UNDATED_LABEL
            r['day_label'] = ''
        r['topic'] = topic(r)
        buckets.setdefault(key, {'key': key, 'label': label, 'items': []})
        buckets[key]['items'].append(r)

    #  新的一週在前；日期不明那組永遠在最後（它的 key 是空字串）
    ordered = sorted((g for k, g in buckets.items() if k != UNDATED_KEY),
                     key=lambda g: g['key'], reverse=True)
    if UNDATED_KEY in buckets:
        ordered.append(buckets[UNDATED_KEY])

    for g in ordered:
        g['count'] = len(g['items'])
        #  ★ 收合那一行只放**第一部**的主題，不把兩部串在一起 ——
        #    串起來那一行會爆掉，而這一頁的價值就在於「一週一行」。
        #    有第二部時右邊那顆「2 部」就是在講這件事。
        g['topic'] = g['items'][0].get('topic') or ''
        #  ★ 一組只有一部、而且就是那個主日當天傳的 → 裡面不用再標一次日期
        #    （標題列已經寫了）。多部、或上傳日不是主日 → 標出來，
        #    不然分不出是哪一部，而「9/6 那一組裡有一部 9/9 的」也看不到。
        only = g['count'] == 1
        for it in g['items']:
            it['show_day'] = not (only and it.get('day_label') == _md(g['key']))
    return ordered


def _md(iso_key):
    """'2026-09-06' → '9/6'（給上面比對用）。"""
    if not iso_key:
        return ''
    try:
        y, m, d = iso_key.split('-')
        return '%d/%d' % (int(m), int(d))
    except ValueError:
        return ''



#  上次抓是什麼時候（行程記憶體）。跨 process 不共用，重啟會歸零 ——
#  最壞的情況是多抓幾次，而那只是三個 HTTP GET，沒有副作用
#  （`merge_new` 只新增沒看過的）。
_last_refresh = None


def due_for_refresh(now=None):
    from datetime import datetime, timedelta, timezone
    now = now or datetime.now(timezone.utc)
    return (_last_refresh is None
            or now - _last_refresh >= timedelta(hours=REFRESH_HOURS))


def refresh_throttled(**kw):
    """排程專用：跑一次並記下時間。手動那顆不走這裡（按了就要抓）。"""
    from datetime import datetime, timezone
    global _last_refresh
    _last_refresh = datetime.now(timezone.utc)
    return refresh(**kw)


def reset_throttle_for_tests():
    global _last_refresh
    _last_refresh = None


def is_configured():
    """後台設過播放清單了嗎 —— 沒設的話這個功能整個不出現。

    ★ 沒設卻留一頁空的清單，跟「教會從來沒有錄過影」長得一樣。
    """
    return bool(feed_sources(configured_block()))


# ─────────────────────────────────────────────────────────
#  前台
# ─────────────────────────────────────────────────────────

from flask import Blueprint, render_template, session, redirect, request, url_for  # noqa: E402

sermons_bp = Blueprint('sermons', __name__)


@sermons_bp.route('/sermons')
def sermon_list():
    if not session.get('user_id'):
        session['next_url'] = request.url
        return redirect(url_for('auth.login_page'))
    try:
        rows = recent(limit=60)
    except Exception:
        rows = []
    return render_template('sermons.html',
                           sermons=rows,
                           weeks=group_by_week(rows),
                           configured=is_configured(),
                           is_admin=bool(session.get('is_admin')
                                         or session.get('is_super_admin')))
