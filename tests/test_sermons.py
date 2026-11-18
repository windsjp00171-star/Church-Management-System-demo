"""主日信息：影片自動從 YouTube 抓進來

守的是這個功能特有的失敗形狀 —— 它們**全部都不會報錯**，
症狀一律是「主日信息那一頁看起來很正常，只是少了東西」。
"""
import sys
import types

# routes.sermons 載入時不碰 db，但有幾條測試會 import 到；沒有真的環境變數時換成假的
if 'db' not in sys.modules:
    _m = types.ModuleType('db')
    _m.supabase = None
    _m.create_client = None
    sys.modules['db'] = _m

import pytest

from routes import sermons as S


#  ★ 一份真的 `browse` 回應長的樣子（2026 年的 YouTube 網頁版面）。
#    影片藏在 tabs → sectionList → itemSection 底下好幾層 ——
#    測試裡故意也包這麼多層，因為解析器**刻意不照路徑取值**
#    （路徑比 renderer 的名字更常變，而照路徑取值失敗時
#    拿到的是 0 部影片，不是例外）。
def _lockup(vid, title, kind='LOCKUP_CONTENT_TYPE_VIDEO'):
    return {'lockupViewModel': {
        'contentId': vid,
        'contentType': kind,
        'metadata': {'lockupMetadataViewModel': {'title': {'content': title}}},
    }}


def _browse(*items):
    return {'contents': {'twoColumnBrowseResultsRenderer': {'tabs': [
        {'tabRenderer': {'content': {'sectionListRenderer': {'contents': [
            {'itemSectionRenderer': {'contents': list(items)}},
        ]}}}},
    ]}}}


LIST = _browse(
    _lockup('aaaaaaaaaaa', '主日信息｜靠主常常喜樂2026-09-06'),
    _lockup('bbbbbbbbbbb', '主日信息｜在曠野開道路2026-08-30'),
)

EMPTY_LIST = _browse()


# ─────────────────────────────────────────────────────────
#  貼什麼進去都要認得出來（或明確說認不出來）
# ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('pasted,expect', [
    ('https://www.youtube.com/playlist?list=PLZjKmNiLAZQc8MdHMTf6WUlNF5oVjucLa',
     'PLZjKmNiLAZQc8MdHMTf6WUlNF5oVjucLa'),
    #  手機分享出來的帶 &si=
    ('https://youtube.com/playlist?list=PLZjKmNiLAZQfEnK_J4ut-MbNO2O1cbrzV&si=Hdnv7Q1BbBM',
     'PLZjKmNiLAZQfEnK_J4ut-MbNO2O1cbrzV'),
    ('PLZjKmNiLAZQc8MdHMTf6WUlNF5oVjucLa',
     'PLZjKmNiLAZQc8MdHMTf6WUlNF5oVjucLa'),
])
def test_the_urls_people_actually_paste_are_understood(pasted, expect):
    assert S.list_id_for(pasted) == expect


def test_a_channel_is_read_through_its_uploads_playlist():
    """★ `UC…` → `UU…`（那個頻道的「所有上傳」清單）。

    少了這一步，頻道要走另一支 API（要帶一段 base64 的 protobuf 去選
    「影片」分頁）—— 那是另一條會壞、而我們手上沒有頻道可以驗的路。
    換成上傳清單之後，頻道和播放清單在底下是同一件事。
    """
    assert S.list_id_for('https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv') \
        == 'UUabcdefghijklmnopqrstuv'
    assert S.list_id_for('UCabcdefghijklmnopqrstuv') == 'UUabcdefghijklmnopqrstuv'


def test_the_old_rss_url_someone_already_pasted_still_works():
    """★★ RSS 還活著的時候，後台的提示說「直接貼 feed 網址也可以」。

    所以有人的設定裡就是那一條。不認的話，他什麼都沒改，
    那一行會自己變成紅字 —— 而他會以為是自己弄壞的。
    """
    assert S.list_id_for(
        'https://www.youtube.com/feeds/videos.xml?playlist_id=PLZjKmNiLAZQc8MdHMTf6WUlNF5oVjucLa') \
        == 'PLZjKmNiLAZQc8MdHMTf6WUlNF5oVjucLa'
    assert S.list_id_for(
        'https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv') \
        == 'UUabcdefghijklmnopqrstuv'


def test_a_video_link_that_carries_a_playlist_follows_the_playlist():
    """★ `/watch?v=…&list=…` 兩個都在時要跟**清單**走。

    他從影片頁按「分享」複製到的就是這一條。跟著影片走的話，
    抓回來的是那部片所屬**頻道**的全部內容（詩歌、活動花絮都進來），
    而後台看起來設定成功了。
    """
    got = S.list_id_for(
        'https://www.youtube.com/watch?v=abc12345678&list=PLZjKmNiLAZQc8MdHMTf6WUlNF5oVjucLa')
    assert got == 'PLZjKmNiLAZQc8MdHMTf6WUlNF5oVjucLa'


@pytest.mark.parametrize('junk', [
    '', '   ', '安南靈糧堂', 'https://example.com/videos',
    'https://www.facebook.com/watch/?v=123',
])
def test_something_that_is_not_a_youtube_list_returns_none(junk):
    """★ 認不出來一定要回 None，不可以猜一個。

    猜錯的話會抓到 0 部 —— 跟「這個清單真的沒有影片」
    在畫面上一模一樣。
    """
    assert S.list_id_for(junk) is None


def test_a_handle_is_recognised_but_needs_a_lookup():
    """@handle 認得出來，只是要連網查 —— 跟「這根本不是 YouTube」不一樣。

    合成同一種錯誤的話，一個完全正常的網址會被講成「網址有問題」。
    """
    assert S.lookup_needed('https://www.youtube.com/@annanchurch')
    assert S.list_id_for('https://www.youtube.com/@annanchurch') is None
    #  對照組：真的不是 YouTube 的東西不算「要查」
    assert not S.lookup_needed('https://example.com/abc')


# ─────────────────────────────────────────────────────────
#  多條清單：壞掉的那一行不可以被吞掉
# ─────────────────────────────────────────────────────────

def test_every_line_comes_back_with_its_own_verdict():
    """★★ 三行裡壞一行時，壞的那一行也要回來。

    只回成功的兩條等於**默默吞掉**第三條 —— 後台有影片、有清單，
    看起來完全正常，少的那一年要等到有人去找去年的講道才會發現。
    """
    block = ('https://www.youtube.com/playlist?list=PLaaaaaaaaaaaa\n'
             '我不小心貼到別的東西\n'
             'https://www.youtube.com/playlist?list=PLbbbbbbbbbbbb')
    got = S.feed_sources(block)

    assert len(got) == 3, '壞掉那一行被吞掉了'
    assert [s['problem'] for s in got] == [None, 'unknown', None]
    assert got[1]['raw'] == '我不小心貼到別的東西', '要留原文，使用者才知道是哪一行'


def test_the_same_playlist_twice_only_counts_once():
    block = ('https://www.youtube.com/playlist?list=PLaaaaaaaaaaaa\n'
             'https://youtube.com/playlist?list=PLaaaaaaaaaaaa&si=xyz')
    assert len(S.feed_sources(block)) == 1


def test_blank_lines_are_not_sources():
    assert S.feed_sources('\n\n   \n') == []


# ─────────────────────────────────────────────────────────
#  解析
# ─────────────────────────────────────────────────────────

def test_parse_playlist_reads_the_real_shape():
    rows = S.parse_playlist(LIST)
    assert [r['video_id'] for r in rows] == ['aaaaaaaaaaa', 'bbbbbbbbbbb']
    assert rows[0]['title'] == '主日信息｜靠主常常喜樂2026-09-06'


def test_the_older_shape_is_still_understood():
    """★ YouTube 不是所有出口同時改版，兩種形狀會並存一陣子。

    只認新的那一種的話，哪天某一條清單回舊形狀 → 那一條抓到 0 部，
    而另外兩條正常 —— 後台看起來只是「那個清單是空的」。
    """
    old = {'contents': [{'playlistVideoRenderer': {
        'videoId': 'ccccccccccc',
        'title': {'runs': [{'text': '主日信息｜'}, {'text': '舊版面2026-08-23'}]},
    }}]}
    rows = S.parse_playlist(old)
    assert rows == [{'video_id': 'ccccccccccc',
                     'title': '主日信息｜舊版面2026-08-23',
                     'published_at': None}]


def test_only_videos_are_taken_not_the_other_cards():
    """★ 同一種 lockup 也用來畫「播放清單」「頻道」那種卡。

    不篩 contentType 的話，側邊欄那些東西會被當成講道存進來 ——
    而它們也有 id 和標題，點下去是一個不存在的影片。
    """
    mixed = _browse(
        _lockup('aaaaaaaaaaa', '真的是一部講道2026-09-06'),
        _lockup('PLsomelist', '2025 主日信息', kind='LOCKUP_CONTENT_TYPE_PLAYLIST'),
    )
    assert [r['video_id'] for r in S.parse_playlist(mixed)] == ['aaaaaaaaaaa']


def test_an_entry_without_an_id_is_skipped_not_faked():
    """★ 少了 id 的那一筆整筆跳過。

    補一個空字串進去的話，前台會多一張點下去是「影片不存在」的卡。
    """
    broken = _browse(_lockup('', '沒有 id 的那一部2026-09-06'),
                     _lockup('bbbbbbbbbbb', '正常的2026-08-30'))
    assert [r['video_id'] for r in S.parse_playlist(broken)] == ['bbbbbbbbbbb']


@pytest.mark.parametrize('junk', [None, '', 'not json at all', [], {},
                                  {'contents': None}])
def test_junk_means_no_new_videos_not_a_crash(junk):
    """★ 壞掉回空陣列。丟例外的話排程那一輪整個掛掉，
    而排程是在背景跑的 —— 沒有人看得到。"""
    assert S.parse_playlist(junk) == []


def test_the_upload_time_is_left_empty_not_guessed():
    """★★ 這條路拿不到上傳時間，那一欄就要是**空的**。

    `browse` 只給「3 天前」「2 個月前」那種相對時間 —— 換算出來的日期
    看起來完全正常，只是可能差幾十天，而這一頁是**按週分組**的。
    寧可空著（日期改從標題讀，`preached_date`），也不要一個像樣的假日期。
    """
    rows = S.parse_playlist(_browse(
        _lockup('aaaaaaaaaaa', '主日信息2026-09-06')))
    assert rows[0]['published_at'] is None

    #  ★ 而且相對時間就算出現在資料裡也不可以被拿去用
    with_ago = {'contents': [{'lockupViewModel': {
        'contentId': 'ddddddddddd',
        'contentType': 'LOCKUP_CONTENT_TYPE_VIDEO',
        'metadata': {'lockupMetadataViewModel': {
            'title': {'content': '主日信息2026-09-06'},
            'metadata': {'contentMetadataViewModel': {'metadataRows': [
                {'metadataParts': [{'text': {'content': '3 天前'}}]}]}},
        }},
    }}]}
    assert S.parse_playlist(with_ago)[0]['published_at'] is None


def test_a_broken_list_cannot_write_a_thousand_rows():
    """★ 上限是防呆不是分頁：資料壞掉時不可以一次寫爆整張表。"""
    huge = _browse(*[_lockup('v%08d' % i, '第 %d 部2026-01-01' % i)
                     for i in range(S.MAX_ENTRIES + 40)])
    assert len(S.parse_playlist(huge)) == S.MAX_ENTRIES


def test_the_status_code_is_in_the_message_not_just_httperror():
    """★★ 「抓不到（HTTPError）」裡沒有任何可以往下查的東西。

    實際發生過：RSS 被關掉那天，後台三行全部寫「抓不到（HTTPError）」，
    而 403（被擋）、404（清單不見了）、429（太頻繁）三種的
    處理方式完全不一樣。
    """
    class _Resp:
        status_code = 404

    class _Err(Exception):
        response = _Resp()

    assert S.why(_Err()) == 'HTTP 404'
    #  連不上（沒有 response）時還是要講得出是哪一種例外
    assert S.why(TimeoutError('慢')) == 'TimeoutError'


# ─────────────────────────────────────────────────────────
#  只新增、不覆蓋
# ─────────────────────────────────────────────────────────

def test_only_videos_we_have_never_seen_are_added():
    fetched = S.parse_playlist(LIST)
    fresh = S.merge_new(fetched, known_ids={'aaaaaaaaaaa'})
    assert [r['video_id'] for r in fresh] == ['bbbbbbbbbbb']


def test_the_same_video_in_two_playlists_is_added_once():
    """一部影片同時在「2026」和「精選」兩個清單裡是很正常的事。"""
    fetched = S.parse_playlist(LIST) + S.parse_playlist(LIST)
    assert len(S.merge_new(fetched, known_ids=set())) == 2


def test_an_already_known_video_produces_no_write_at_all():
    """★★ 已經存過的**完全不動它**。

    同工補的講員／經文掛在同一列上。每次抓都覆蓋的話，那些字會被
    YouTube 的標題洗掉 —— 而且是默默地洗掉，補的人下次來看
    只會覺得自己沒存到。
    """
    fetched = S.parse_playlist(LIST)
    known = {'aaaaaaaaaaa', 'bbbbbbbbbbb'}
    assert S.merge_new(fetched, known) == []


def test_the_upload_time_we_already_have_is_not_wiped_by_an_empty_one():
    """★★ 新路徑的 `published_at` 永遠是 None。

    那個 None 要是「我不知道」，不可以是「清空」—— 舊的 43 部
    上傳時間都還在資料庫裡，被洗掉的話它們會整批掉到「日期不明」，
    而每一張卡看起來都還是正常的。
    """
    known = {'aaaaaaaaaaa': {'title': '主日信息｜靠主常常喜樂2026-09-06',
                             'published_at': '2026-09-06T02:30:00+00:00'}}
    assert S.merge_changed(S.parse_playlist(LIST), known) == []


def test_thumbnails_are_derived_not_stored():
    """★ 縮圖網址是 video_id 的函數。存一份等於存一個會過期的複本，
    而過期的症狀是整排破圖 —— 看起來像整個功能壞了。"""
    assert S.thumbnail_url('aaaaaaaaaaa').endswith('/vi/aaaaaaaaaaa/hqdefault.jpg')
    #  資料表裡沒有這一欄（有的話就是有人存了一份）
    import routes.sermons as mod
    src = open(mod.__file__, encoding='utf-8').read()
    body = src.split('def parse_playlist')[1].split('def merge_new')[0]
    assert 'thumbnail' not in body, 'parse_playlist 不該把縮圖網址存下來'


# ─────────────────────────────────────────────────────────
#  抓一輪：結果要照實講
# ─────────────────────────────────────────────────────────

class _FakeTable:
    """★★ 這份替身原本**不管 select 什麼都只回 `video_id`**。

    那等於把「我們只需要 video_id」這個假設一起編碼進測試裡 ——
    後來要比對標題有沒有改時，正式站拿得到 `title`，而測試裡永遠是
    `None`。這個專案在 `help_stats` 已經被同一種替身騙過一次
    （欄位名寫錯、整頁 500，而測試全綠）。

    現在它照實回**存進去的那一列**，而且真的支援 update。
    """

    def __init__(self, store):
        self.store = store
        self._patch = None
        self._where = {}

    def select(self, *a, **k):
        return self

    def insert(self, row):
        #  ★ 正式的 client 兩種都吃（一列 dict 或一批 list），
        #    替身只認 dict 的話「分批寫入」那條路在測試裡走不到。
        owner = getattr(self, 'owner', None)
        if owner is not None:
            owner.inserts += 1
        rows = row if isinstance(row, list) else [row]
        reject = getattr(self, 'reject', None)
        #  ★ 真的資料庫是**整批一起成功或一起失敗**。替身先驗完再寫，
        #    不然「整批失敗」在測試裡會留下半批資料，而那是真實世界
        #    不會發生的狀態 —— 照著它寫出來的程式會在正式站上壞掉。
        if reject and any(reject(r) for r in rows):
            raise RuntimeError('這一批存不進去')
        self.store.extend(dict(r) for r in rows)
        return self

    def update(self, patch):
        self._patch = dict(patch)
        return self

    def eq(self, col, val):
        self._where[col] = val
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._patch is not None:
            for r in self.store:
                if all(r.get(k) == v for k, v in self._where.items()):
                    r.update(self._patch)
            self._patch, self._where = None, {}

            class W:
                data = []
            return W()
        rows = [dict(r) for r in self.store]

        class R:
            data = rows
        return R()


class _FakeSB:
    def __init__(self, store, reject=None):
        self.store = store
        #  `reject(row) -> True` 的那一列會丟例外（模擬「某一筆壞掉」）
        self.reject = reject
        self.inserts = 0

    def table(self, name):
        t = _FakeTable(self.store)
        t.reject = self.reject
        t.owner = self
        return t


def _post(data):
    """一個「YouTube 一律回這份資料」的替身。"""
    def post(url, payload, timeout=10):
        return data
    return post


def test_refresh_reports_which_line_broke_not_just_a_failure():
    """★★ 一條掛掉時要說**哪一條**，而且其他兩條照樣抓進來。

    回一個布林值的話，使用者只知道「有問題」，
    然後要自己一行一行試 —— 而最可能的情況是他根本沒發現有三行。
    """
    store = []
    block = ('https://www.youtube.com/playlist?list=PLgoodgoodgood\n'
             '這行是亂打的\n'
             'https://www.youtube.com/playlist?list=PLalsogoodgood')

    r = S.refresh(block=block, post=_post(LIST), sb=_FakeSB(store))
    assert r['sources'] == 3
    assert r['added'] == 2, '兩條好的清單裡那兩部影片還是要進來'
    assert len(r['problems']) == 1
    assert '這行是亂打的' in r['problems'][0]


def test_a_playlist_that_times_out_does_not_stop_the_others():
    store = []
    block = ('https://www.youtube.com/playlist?list=PLbrokenbroken\n'
             'https://www.youtube.com/playlist?list=PLworkingworks')

    def post(url, payload, timeout=10):
        if 'PLbrokenbroken' in payload['browseId']:
            raise TimeoutError('連不上')
        return LIST

    r = S.refresh(block=block, post=post, sb=_FakeSB(store))
    assert r['added'] == 2
    assert any('PLbrokenbroken' in p for p in r['problems'])


def test_the_reason_it_broke_says_which_http_code():
    """★★ 使用者實際看到過的那一行：「抓不到（HTTPError）」。

    那句話對他、對我都查不下去。RSS 被關掉那天三條清單全是這一行，
    而真正的資訊（404）被吞掉了。
    """
    class _Resp:
        status_code = 403

    class _Blocked(Exception):
        response = _Resp()

    def post(url, payload, timeout=10):
        raise _Blocked()

    r = S.refresh(block='https://www.youtube.com/playlist?list=PLaaaaaaaaaaaa',
                  post=post, sb=_FakeSB([]))
    assert any('HTTP 403' in p for p in r['problems']), r['problems']


def test_nothing_new_is_not_reported_as_a_problem():
    """★ 「抓到了但都是舊的」是**完全正常**的（這週還沒上傳）。

    當成問題的話，後台每次按都紅一次，久了就沒有人相信那個紅字，
    而真的壞掉時也不會有人看。
    """
    #  ★ 標題跟 LIST 裡的一模一樣 —— 「都是舊的」才是真的都是舊的
    store = [{'video_id': 'aaaaaaaaaaa',
              'title': '主日信息｜靠主常常喜樂2026-09-06',
              'published_at': '2026-09-06T01:30:00+00:00'},
             {'video_id': 'bbbbbbbbbbb',
              'title': '主日信息｜在曠野開道路2026-08-30',
              'published_at': '2026-08-30T01:30:00+00:00'}]
    r = S.refresh(block='https://www.youtube.com/playlist?list=PLaaaaaaaaaaaa',
                  post=_post(LIST), sb=_FakeSB(store))
    assert r['added'] == 0
    assert r['problems'] == []


def test_a_200_with_no_videos_says_both_things_that_could_be_wrong():
    """★★ 讀到了但一部都沒有 —— **兩種可能，處理方式相反**。

    清單真的是空的（他自己去 YouTube 看一眼就知道），
    或者 YouTube 換了版面（那要改程式）。
    ★ 這一條在 RSS 時代只有前一種；現在是在讀別人的網頁，
      「200 但解不出東西」變成最可能的壞法，所以兩種都要講。
    """
    r = S.refresh(block='https://www.youtube.com/playlist?list=PLaaaaaaaaaaaa',
                  post=_post(EMPTY_LIST), sb=_FakeSB([]))
    assert len(r['problems']) == 1
    msg = r['problems'][0]
    assert '空的' in msg and '版面' in msg, msg


def test_no_playlists_configured_says_so():
    r = S.refresh(block='', post=_post(LIST), sb=_FakeSB([]))
    assert r['added'] == 0
    assert any('還沒有設定' in p for p in r['problems'])


# ─────────────────────────────────────────────────────────
#  第一次抓會補進整個清單 —— 寫入不可以一列一趟
# ─────────────────────────────────────────────────────────

def test_a_hundred_new_videos_are_not_a_hundred_round_trips():
    """★★ 換掉 RSS 之後一次拿得到整個播放清單（實測三條共 140 部）。

    一列一趟的話，同工按下「立刻重新抓取」要等 140 次往返 ——
    畫面上只會是「抓取中…」卡住，看起來像功能壞了。
    """
    store = []
    sb = _FakeSB(store)
    big = _browse(*[_lockup('v%08d' % i, '第 %d 部2026-01-01' % i)
                    for i in range(100)])
    r = S.refresh(block='https://www.youtube.com/playlist?list=PLaaaaaaaaaaaa',
                  post=_post(big), sb=sb)
    assert r['added'] == 100
    #  ★★ 這個上限要是**寫死的數字**，不可以寫成 `100 / S.INSERT_CHUNK`：
    #    那樣的話把 INSERT_CHUNK 改成 1（＝完全沒分批）測試照樣綠，
    #    因為上限跟著那個常數一起動。mutation 當場抓到。
    assert sb.inserts <= 10, f'寫入分了 {sb.inserts} 趟，等於沒有分批'


def test_one_bad_row_does_not_take_the_whole_batch_down():
    """★ 分批換到速度，但也帶回「一列壞掉整批都進不去」。

    整批失敗就退回一筆一筆寫 —— 那時候慢沒關係，重點是
    **把壞的那一筆指出來**，其他的照樣存進去。
    不這樣做的話，下一次抓還是同一批、還是全掛，而且永遠是同一行紅字。
    """
    store = []
    sb = _FakeSB(store, reject=lambda r: r['video_id'] == 'bbbbbbbbbbb')
    r = S.refresh(block='https://www.youtube.com/playlist?list=PLaaaaaaaaaaaa',
                  post=_post(LIST), sb=sb)
    assert r['added'] == 1
    assert [x['video_id'] for x in store] == ['aaaaaaaaaaa']
    assert any('在曠野開道路' in p and '存不進去' in p for p in r['problems']), \
        r['problems']


# ─────────────────────────────────────────────────────────
#  排序：照講道的日子，不是上傳時間
# ─────────────────────────────────────────────────────────

def test_the_list_is_ordered_by_the_preached_date():
    """★★ 首頁那張「最近的主日信息」就是 `recent(limit=1)`。

    照 `published_at` 排的話會出兩種錯，而**兩種都看不出來**：

    1. 上傳時間和講道日期差過三天（實際資料裡就有一部）
    2. ★ 新抓進來的那幾部 `published_at` 是 NULL，而 Postgres 的
       `DESC` 把 NULL 排**最前面** —— 一部 2024 年補進來的舊片
       會直接跳上首頁那張卡
    """
    store = [
        #  ★ 故意把「最舊的」擺在最前面（＝資料庫照 created_at 回來的順序）
        {'video_id': 'old', 'title': '兩年前那一篇2024-01-07',
         'published_at': None, 'is_hidden': False},
        {'video_id': 'new', 'title': '這個禮拜那一篇2026-09-13',
         'published_at': None, 'is_hidden': False},
    ]
    got = S.recent(limit=1, sb=_FakeSB(store))
    assert [r['video_id'] for r in got] == ['new'], \
        '首頁那張卡挑錯了 —— 排序沒有走 preached_date'


def test_a_row_with_no_date_at_all_sinks_to_the_bottom():
    """★ 算不出日期的**不丟掉**（那一部就從此看不到了），排最後。

    排最前面的話，一部標題沒寫日期的影片會霸佔首頁那張卡。
    """
    store = [
        {'video_id': 'nodate', 'title': '沒有日期的那一部', 'is_hidden': False},
        {'video_id': 'dated', 'title': '這個禮拜那一篇2026-09-13', 'is_hidden': False},
    ]
    got = S.recent(sb=_FakeSB(store))
    assert [r['video_id'] for r in got] == ['dated', 'nodate']


# ─────────────────────────────────────────────────────────
#  節流
# ─────────────────────────────────────────────────────────

def test_the_scheduler_does_not_hit_youtube_every_tick():
    """★ 排程每 15 分鐘轉一次，但主日一週才一次。

    不節流的話一天會去敲 YouTube 快 100 次，而且換不到任何東西。
    """
    S.reset_throttle_for_tests()
    assert S.due_for_refresh()
    S.refresh_throttled(block='', post=_post(LIST), sb=_FakeSB([]))
    assert not S.due_for_refresh(), '剛抓完不該馬上又到期'
    S.reset_throttle_for_tests()


def test_the_throttle_expires():
    from datetime import datetime, timedelta, timezone
    S.reset_throttle_for_tests()
    S.refresh_throttled(block='', post=_post(LIST), sb=_FakeSB([]))
    later = datetime.now(timezone.utc) + timedelta(hours=S.REFRESH_HOURS + 1)
    assert S.due_for_refresh(now=later)
    S.reset_throttle_for_tests()


# ─────────────────────────────────────────────────────────
#  接線：每一個註冊表都要登記到
# ─────────────────────────────────────────────────────────

from pathlib import Path                                    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _src(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def test_it_is_an_admin_module():
    from routes.permissions import ADMIN_MODULES
    keys = {m[0] for m in ADMIN_MODULES}
    assert 'sermons' in keys, '沒登記的話權限矩陣管不到 /admin/sermons'


def test_it_gets_backed_up():
    """★ 影片重抓就有，但 speaker / scripture 是同工一筆一筆打的。

    只看「抓得回來」就跳過它的話，弄丟的正好是唯一手工的那部分。
    """
    import backup_registry as reg
    BACKUP_TABLES = {t[0] for t in reg.TABLES}
    assert 'sermons' in BACKUP_TABLES






# ─────────────────────────────────────────────────────────
#  設定：多行的那一格
# ─────────────────────────────────────────────────────────









def _save_settings_js():
    """只切出送出設定那一段，不要掃整份檔案。"""
    src = _src('templates/admin/settings.html')
    return src.split('const values = {}')[1].split('</script>')[0]






# ─────────────────────────────────────────────────────────
#  畫面：沒設定 ≠ 沒有影片
# ─────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────
#  收合那一行要講「這週在講什麼」，不是只有日期
# ─────────────────────────────────────────────────────────

TOPIC_TITLE = '【主日信息】主題:✟ 智慧的禱告✟回應詩歌♫我心屬於祢 ♫ 講員: 蕭夢熊 牧師2026-09-06'


def test_the_week_row_says_what_it_was_about():
    """★ 使用者：「列表可以把標題弄上去嗎? 不要只有單純的日期」。

    收合起來只有一排日期時，要挑哪一週還是得一個一個展開 ——
    而「我要聽哪週的講道」正是這一頁存在的理由。
    """
    (week,) = S.group_by_week([{'title': TOPIC_TITLE, 'published_at': None}])
    assert week['topic'] == '智慧的禱告'


def test_the_topic_drops_the_decorations_people_type():
    """★ `✟`、多餘的空白是人打的裝飾，不是主題的一部分。"""
    assert S.topic({'title': TOPIC_TITLE}) == '智慧的禱告'
    assert S.topic({'title': '【主日信息】主題：✟神的激動 起來行動✟ 講員:郭純敏傳道 2025-12-21'}) \
        == '神的激動 起來行動'
    #  ★ **主題中間**連按了幾個空格（或換了行）也要收成一個。
    #    只驗前後空白是假的 —— 那兩邊的正規表示式本來就吃掉了
    #    （mutation 當場抓到：把整行 normalize 拿掉，測試照樣綠）。
    assert S.topic({'title': '主題:✟神的激動   起來行動✟2025-12-21'}) == '神的激動 起來行動'


def test_a_title_that_is_not_named_that_way_still_says_something():
    """★★ 抓不到主題**不可以回空字串**。

    那一行會安靜地退回成「只有日期」（＝改之前那樣），而畫面上完全正常 ——
    沒有人會發現是這一部的命名不一樣，只會覺得這個功能時好時壞。
    ★ 這個標題是**真的**（140 部裡就這一部不合樣式）。
    """
    assert S.topic({'title': '2025-09-21受洗'}) == '2025-09-21受洗'
    (week,) = S.group_by_week([{'title': '隨手打的標題2026-09-06'}])
    assert week['topic'] == '隨手打的標題'


def test_the_row_does_not_print_the_date_twice():
    """★ 那一行前面已經有一個日期了。退回整個標題時要把結尾那個切掉，
    不然畫面上是「2026/9/6 … 2026-09-06」，看起來像講了兩次。"""
    assert S.topic({'title': '沒有主題兩個字的標題2026-09-06'}) == '沒有主題兩個字的標題'
    assert '2026' not in S.topic({'title': '【主日信息】沒有主題2026-09-06'})


def test_a_week_with_two_videos_takes_the_first_topic_and_keeps_the_count():
    """★ 兩部串在一起那一行會爆掉，而這一頁的價值就是「一週一行」。
    第二部靠右邊那顆「2 部」講出來。"""
    (week,) = S.group_by_week([
        {'title': '主題:✟神能使用的人✟ 講員:周莊碧明牧師2026-08-02'},
        {'title': '主題:✟在患難中的見証✟ 講員:周莊碧明牧師2026-08-02'},
    ])
    assert week['topic'] == '神能使用的人'
    assert week['count'] == 2


def test_a_blank_title_does_not_crash_the_page():
    assert S.topic({}) == ''
    assert S.topic({'title': None}) == ''


def test_the_page_prints_the_topic_next_to_the_date():
    src = _src('templates/sermons.html')
    head = src.split('<summary class="sm-head">')[1].split('</summary>')[0]
    assert 'g.topic' in head, '收合那一行沒有把主題印出來'
    assert 'g.label' in head, '日期還是要在（那是那一組的名字）'


def test_the_week_row_stays_one_line():
    """★★ 主題最長 14 個字。讓它換行的話 60 週變成 120 行 ——
    而這一頁收合起來的價值就是**一行一個主日**。放不下要 `…`，不是換行。"""
    src = _src('templates/sermons.html')
    rule = src.split('.sm-topic {')[1].split('}')[0]
    assert 'white-space:nowrap' in rule.replace(' ', '').replace('white-space:nowrap', 'white-space:nowrap') \
        or 'nowrap' in rule
    assert 'ellipsis' in rule, '放不下要用 … 收掉'
    assert 'min-width:0' in rule.replace(' ', ''), \
        'flex 子元素沒有 min-width:0 的話 ellipsis 不會生效，那一行會把版面撐開'


def test_an_unconfigured_page_explains_itself():
    """★ 還沒設定時給的是說明，不是一頁空清單。

    空清單跟「教會從來沒有錄過影」在畫面上一模一樣。
    """
    src = _src('templates/sermons.html')
    branch = src.split('{% if not configured %}')[1].split('{% elif not sermons %}')[0]
    assert '還沒有設定' in branch
    assert '/admin/sermons' in branch, '管理員要看得到去哪裡設定'




# ─────────────────────────────────────────────────────────
#  內嵌播放：點一下就在這一頁看，不跳去 YouTube
# ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('page', ['templates/sermons.html'])
def test_no_iframe_is_loaded_before_anyone_presses_play(page):
    """★★ 先放縮圖、按了才換播放器（facade）。

    /sermons 一次列 60 部。每一部都先放一個 iframe 的話，等於一開頁就
    同時載入 60 個 YouTube 播放器 —— 手機會卡到動不了，而且流量全花在
    使用者根本不會看的 59 部上。
    """
    src = _src(page)
    assert '<iframe' not in src, f'{page} 直接放了 iframe，應該按了才建立'


@pytest.mark.parametrize('page', ['templates/sermons.html'])
def test_every_player_keeps_a_way_out_to_youtube(page):
    """★★ 有些影片不允許嵌入（上傳者關掉的話）。

    那時候 iframe 裡是一片「無法播放」，而我們這一頁看起來完全正常 ——
    所以每一個播放器旁邊都要留一條「在 YouTube 開啟」。
    """
    src = _src(page)
    seg = (src.split('{% if latest_sermon %}')[1].split('本週小組討論')[0]
           if page.endswith('portal.html')
           else src.split('id="sermon-list"')[1].split('</script>')[0])
    assert 'data-yt=' in seg, '沒有播放器'
    assert 'watch_url' in seg and '在 YouTube 開啟' in seg


def test_the_fallback_link_is_not_swallowed_by_the_player():
    """★ JS 攔截整塊的點擊。連結也攔下來的話，不能嵌入的影片
    就變成**完全沒有路可以走** —— 按縮圖沒用、按連結也沒用。"""
    js = (ROOT / 'static' / 'js' / 'yt-embed.js').read_text(encoding='utf-8')
    assert "closest('a')" in js, '要放行「在 YouTube 開啟」那條連結'


def test_the_embed_uses_the_privacy_domain():
    js = (ROOT / 'static' / 'js' / 'yt-embed.js').read_text(encoding='utf-8')
    assert 'youtube-nocookie.com/embed/' in js


def test_the_video_id_is_escaped_into_the_embed_url():
    """★ 影片 id 是從外部 feed 抓回來的，直接串進網址等於信任它。"""
    js = (ROOT / 'static' / 'js' / 'yt-embed.js').read_text(encoding='utf-8')
    assert 'encodeURIComponent(id)' in js


# ══ 按週分組（使用者：主日影片應該一週一組） ═══════════════

"""使用者的原話，兩句，第二句推翻了我做的第一版：

    ① 要按時間條列開合 這樣才知道我要聽哪週的講道要選哪個
    ② 主日影片應該一週一組

★ 我第一版做成**按月**，而且在註解裡「論證」過按週不好
  （「一組剛好 1 部，那不是分組，是在每一部上面加一層殼」）。

★★ 那個論證是坐在這裡想出來的，而且想錯的地方很具體：
   我把「一組 1 部」當成缺點，但**收合起來之後，一組 1 部正是它的價值**
   —— 整頁變成一條一週一行的日期索引。按月的話，要先展開一個月、
   再在裡面找那一週。
"""


def _row(video_id, published_at, **kw):
    row = {'video_id': video_id, 'published_at': published_at,
           'title': 'T-' + video_id}
    row.update(kw)
    return row


def test_each_week_is_its_own_group_newest_first():
    groups = S.group_by_week([
        _row('a', '2026-09-06T02:00:00+00:00'),
        _row('b', '2026-08-30T02:00:00+00:00'),
        _row('c', '2026-08-23T02:00:00+00:00'),
    ])
    assert [g['label'] for g in groups] == ['2026/9/6', '2026/8/30', '2026/8/23']
    assert [g['count'] for g in groups] == [1, 1, 1]


def test_a_week_starts_on_sunday_not_monday():
    """★★ 這是**主日**信息 —— 那一組的名字就是那個主日。

    用 ISO 週（週一開始）的話，週日講的道會被歸到**前一週**，
    而每一組看起來都還是正常的一週。
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo('Asia/Taipei')
    #  2026-09-06 是週日
    assert datetime(2026, 9, 6, tzinfo=tz).weekday() == 6
    assert S.week_start(datetime(2026, 9, 6, 10, 0, tzinfo=tz)).isoformat() == '2026-09-06'


def test_a_video_uploaded_on_monday_stays_in_sundays_group():
    """★★ 講道是週日講的，影片常常**週一、週二才上傳**。

    用上傳日當組名的話，同一篇道會因為晚傳一天而變成「下一組」——
    而那一組看起來完全正常，只是名字是錯的日子。
    """
    groups = S.group_by_week([
        _row('sun', '2026-09-06T02:00:00+00:00'),   # 主日當天
        _row('mon', '2026-09-07T09:00:00+00:00'),   # 隔天才傳
    ])
    assert len(groups) == 1, '同一週的兩部被拆成兩組了'
    assert groups[0]['label'] == '2026/9/6'
    assert groups[0]['count'] == 2


def test_saturday_belongs_to_the_week_that_already_started():
    """★ 週六是那一週的**最後一天**，不是下一週的開始。

    （2026-09-12 是週六，它屬於 9/6 開始的那一週。）
    """
    groups = S.group_by_week([_row('x', '2026-09-12T09:00:00+00:00')])
    assert groups[0]['label'] == '2026/9/6'


def test_the_week_is_taipei_not_utc():
    """★★ `published_at` 存的是 UTC，台北是 UTC+8。

    **每天的頭 8 小時（台北）會被算成前一天** —— 而主日早上的信息
    剛好落在那個區間，整組會掉到上一週去，而每一組看起來都還是
    正常的一週。

    2026-09-06（日）早上 9 點台北 ＝ 2026-09-05（六）01:00 UTC。
    拿 UTC 算的話它會被歸到 8/30 那一週。
    """
    groups = S.group_by_week([_row('x', '2026-09-06T01:00:00+08:00')])
    assert groups[0]['label'] == '2026/9/6', '拿 UTC 當台北了'


def test_a_new_year_does_not_sort_before_an_old_december():
    """★ 排序要看**完整日期**。只比月日的話 12/28 會排在 1/4 前面 ——
    而教會是一年一個播放清單，跨年正是最常出現的情況。"""
    groups = S.group_by_week([
        _row('a', '2026-01-04T02:00:00+00:00'),
        _row('b', '2025-12-28T02:00:00+00:00'),
    ])
    assert [g['label'] for g in groups] == ['2026/1/4', '2025/12/28']


def test_the_label_carries_the_year_so_weeks_are_not_ambiguous():
    """★ 60 週橫跨好幾年（一年一個播放清單）。只寫 `9/6` 的話，
    2024 和 2026 的 9/6 在清單上長得一模一樣。"""
    groups = S.group_by_week([_row('a', '2024-09-08T02:00:00+00:00')])
    assert groups[0]['label'].startswith('2024/')


def test_a_lone_video_on_its_own_sunday_does_not_repeat_the_date():
    """★ 一組一部、又剛好是那個主日當天 → 裡面不用再標一次日期
    （標題列已經寫了）。重複的字會讓那一行看起來像有兩個日期。"""
    groups = S.group_by_week([_row('a', '2026-09-06T02:00:00+00:00')])
    assert groups[0]['items'][0]['show_day'] is False


def test_a_video_that_is_not_on_that_sunday_shows_its_own_date():
    """★ 反過來：9/6 那一組裡有一部 9/9 的，就要標出來 ——
    不標的話那件事在畫面上完全看不到。"""
    groups = S.group_by_week([_row('a', '2026-09-09T09:00:00+00:00')])
    assert groups[0]['label'] == '2026/9/6'
    assert groups[0]['items'][0]['show_day'] is True
    assert groups[0]['items'][0]['day_label'] == '9/9'


def test_two_videos_in_one_week_both_show_their_dates():
    """★ 一週兩部（例如一堂／二堂，或加場）→ 兩部都要標日期，
    不然分不出是哪一部。"""
    groups = S.group_by_week([
        _row('a', '2026-09-06T02:00:00+00:00'),
        _row('b', '2026-09-06T06:00:00+00:00'),
    ])
    assert all(s['show_day'] for s in groups[0]['items'])


def test_a_video_with_no_date_is_not_dropped_and_not_guessed():
    """★★ 算不出日期的那一部：

    - **丟掉**的話它從此看不到，而清單看起來完全正常
    - **塞進最近那一週**的話它出現在錯的地方，而那一組看起來也正常
    """
    groups = S.group_by_week([
        _row('good', '2026-09-06T02:00:00+00:00'),
        _row('bad', None),
        _row('junk', '不是時間'),
    ])
    got = {s['video_id'] for g in groups for s in g['items']}
    assert got == {'good', 'bad', 'junk'}, '有影片被吃掉了'
    assert groups[-1]['label'] == '日期不明'
    assert groups[-1]['count'] == 2
    assert groups[0]['count'] == 1, '算不出日期的被塞進某一週了'


def test_no_groups_at_all_when_there_are_no_videos():
    """前提：沒有影片時不要生出一個空的日期標題。"""
    assert S.group_by_week([]) == []


def _render_list(rows):
    """用真的模板 render 一次前台清單。

    ★ 不在測試裡重打一份 markup —— 要驗的正是「那一頁有沒有照分組畫」。
    （這個 repo 的完整 app 不能和其他測試同一個行程建立，所以用簡化 app 載入真的模板。）
    """
    import os
    from flask import Flask, render_template, session
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__, template_folder=os.path.join(root, 'templates'))
    app.secret_key = 't'
    app.jinja_env.globals.update(
        csrf_token=lambda: 't', module_on=lambda *_: True, church_name='測試教會', church_short_name='測試',
        line_liff_id='', privacy_policy_url='', card_names={}, can_see=lambda *_: True,
        asset=lambda p: '/static/' + p, push_enabled=False, assistant_name='小助手')
    with app.test_request_context('/sermons'):
        session['user_id'] = 'u'
        session['real_name'] = '測試'
        for r in rows:
            r.setdefault('watch_url', S.watch_url(r['video_id']))
            r.setdefault('thumbnail_url', S.thumbnail_url(r['video_id']))
        return render_template('sermons.html', sermons=rows,
                               weeks=S.group_by_week(rows),
                               configured=True, is_admin=False)


def _list_block(html):
    """★ 只切出清單那一塊再掃。

    整份 render 出來的頁面**還有 base.html**，而它自己就有 `<details>`。
    對整頁 `count('<details')` 的話數字永遠多幾個 —— 那條斷言等於在
    量一個跟這一頁無關的東西。（這條測試第一版就是這樣紅的。）
    """
    i = html.index('<div id="sermon-list">')
    return html[i:html.index('</body>', i)]


def test_the_page_draws_one_collapsible_row_per_week():
    html = _list_block(_render_list([
        _row('a', '2026-09-06T02:00:00+00:00'),
        _row('b', '2026-08-30T02:00:00+00:00'),
    ]))
    assert '2026/9/6' in html and '2026/8/30' in html
    assert html.count('<details') == 2, '一週要是一個可以開合的區塊'


def test_only_the_newest_week_starts_open():
    """★ 全部展開等於沒有分組（他要捲的還是那幾十部）；
    全部收起來的話，最常要的「這週的講道」也要多按一下。"""
    html = _list_block(_render_list([
        _row('a', '2026-09-06T02:00:00+00:00'),
        _row('b', '2026-08-30T02:00:00+00:00'),
        _row('c', '2026-08-23T02:00:00+00:00'),
    ]))
    assert html.count('<details class="sm-week" open>') == 1
    #  ★ 而且**開著的要是最新那一組** —— 數量對、開錯組的話畫面也正常
    opened = html.index('<details class="sm-week" open>')
    assert html.index('2026/9/6') > opened
    assert html.index('2026/9/6') < html.index('2026/8/30')


def test_a_week_with_one_video_shows_no_count_badge():
    """★ 常態是一週一部，每一行都掛一個「1 部」只是雜訊 ——
    而這一頁收起來之後的價值就在於**一行只有一個日期**。"""
    html = _list_block(_render_list([_row('a', '2026-09-06T02:00:00+00:00')]))
    assert '1 部' not in html


def test_a_week_with_two_videos_says_so():
    """★ 但一週兩部就要講 —— 不講的話收起來時第二部完全看不到。"""
    html = _list_block(_render_list([
        _row('a', '2026-09-06T02:00:00+00:00'),
        _row('b', '2026-09-06T06:00:00+00:00'),
    ]))
    assert '2 部' in html


def test_the_collapsing_needs_no_javascript():
    """★ 開合用瀏覽器內建的 <details>，不自己寫一份。

    自己寫的話：多一個會壞的地方，而且鍵盤操作和螢幕閱讀器都要重做 ——
    而「JS 沒載到」的症狀會是**整頁的影片都點不開**。
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / 'templates' / 'sermons.html').read_text(encoding='utf-8')
    assert '<details' in src and '<summary' in src
    assert 'onclick' not in src, '開合不要用 onclick'


# ══ 講道的日子 vs 上傳的時間 ═══════════════════════════════

"""使用者：「每部主日影片的標題後面都是有日期的」。

★ 這不是聽說的 —— 對著三個真的播放清單抓了 **43 部**驗過：

    【主日信息】主題:✟智慧的禱告✟回應詩歌♫我心屬於祢♫ 講員: 蕭夢熊 牧師2026-09-06

  43 部**全都**在標題結尾有日期，一部都沒漏。
  而且其中**有一部標題的日期跟上傳日期差三天**（講 12/07、12/10 才傳）——
  那一部證明了「上傳時間不是講道的日子」不是假設性的顧慮。
"""

REAL = ('【主日信息】主題:✟認識說「不」的意義與價值! ✟回應詩歌'
        '♫我是個得勝者♫ 講員:張靜蓉院長2025-12-07')


def test_the_date_comes_from_the_title_not_the_upload_time():
    """★★ 真實資料裡的那一部：標題寫 12/07，YouTube 上傳是 12/10。

    用上傳時間的話，那一組的名字會是錯的日子 —— 而那一組看起來
    完全正常，要去翻 YouTube 才發現。
    """
    from datetime import date
    row = {'video_id': 'x', 'title': REAL,
           'published_at': '2025-12-10T05:00:00+00:00'}
    assert S.preached_date(row) == date(2025, 12, 7)


def test_a_late_upload_still_lands_on_its_own_sunday():
    """★ 晚傳**超過六天**的話，用上傳時間就會掉到下一週 ——
    而那一組看起來完全正常。"""
    groups = S.group_by_week([
        {'video_id': 'late', 'title': '主日信息 講員:某某2026-09-06',
         'published_at': '2026-09-16T05:00:00+00:00'},   # 晚傳 10 天
    ])
    assert groups[0]['label'] == '2026/9/6', '用上傳日算了，掉到別週去'


def test_without_a_date_in_the_title_it_falls_back_to_the_upload_time():
    """★ 命名哪天改了、或有一部漏打日期時，退回上傳時間**還是大致對的**
    （同工多半當天或隔天傳）。

    整組丟掉或標成「日期不明」的話，使用者失去的是一部他明明看得到的影片。
    """
    from datetime import date
    row = {'video_id': 'x', 'title': '主日信息（沒有日期）',
           'published_at': '2026-09-06T02:00:00+00:00'}
    assert S.preached_date(row) == date(2026, 9, 6)


def test_a_nonsense_date_in_the_title_does_not_crash():
    """★ 標題打錯（2026-13-45）要退回上傳時間，不是丟例外 ——
    一部打錯的標題不可以讓整頁開不起來。"""
    from datetime import date
    row = {'video_id': 'x', 'title': '主日信息 2026-13-45',
           'published_at': '2026-09-06T02:00:00+00:00'}
    assert S.preached_date(row) == date(2026, 9, 6)


def test_the_date_must_be_at_the_end_of_the_title():
    """★ 只認**結尾**的日期。

    標題中間可能出現別的數字（經文章節、詩歌名、年份），
    在整串標題裡亂找一個日期的話，抓到的可能是完全無關的東西 ——
    而那一組的名字看起來還是一個正常的日期。
    """
    from datetime import date
    row = {'video_id': 'x', 'title': '2020-01-01 那年的回顧 主日信息',
           'published_at': '2026-09-06T02:00:00+00:00'}
    assert S.preached_date(row) == date(2026, 9, 6), '抓到標題中間的數字了'


@pytest.mark.parametrize('tail', ['2026-09-06', '2026/09/06', '2026.9.6',
                                  '2026年9月6日', '2026-09-06  '])
def test_the_common_ways_of_writing_the_date_are_understood(tail):
    """★ 命名是人打的，寫法會飄。認得寬一點，代價只是多認幾種格式；
    認太窄的話那一部會悄悄退回上傳時間。"""
    from datetime import date
    row = {'video_id': 'x', 'title': '【主日信息】主題:某某 講員:某某' + tail,
           'published_at': '2026-01-01T00:00:00+00:00'}
    assert S.preached_date(row) == date(2026, 9, 6)


def test_no_date_anywhere_is_still_not_dropped():
    """★ 兩邊都算不出來 → 「日期不明」那一組，不是消失。"""
    groups = S.group_by_week([{'video_id': 'x', 'title': '沒日期',
                               'published_at': None}])
    assert groups[-1]['label'] == '日期不明'
    assert groups[-1]['items'][0]['video_id'] == 'x'


# ══ 命名改了要看得見（後台） ═══════════════════════════════

"""使用者：「你要自己辨識嗎 那未來有新增是不是又要讓你辨識日期一次，
這樣太奇怪了，系統要能自己抓才對啊」

★ 系統**本來就是自己抓**（`preached_date` 是程式，每次開頁面都跑一次，
  新影片進來自動適用）—— 我只是**去抓了 43 部真的影片驗證格式**，
  沒有手工標任何一筆。

★ 但他這個擔心指到一個真的風險：**命名哪天改了**，`preached_date`
  會安靜地退回上傳時間，而畫面上完全正常。所以後台要看得見。
"""


def test_the_report_counts_where_each_date_came_from():
    rep = S.date_source_report([
        {'video_id': 'a', 'title': '主日信息2026-09-06',
         'published_at': '2026-09-06T02:00:00+00:00'},
        {'video_id': 'b', 'title': '沒有日期',
         'published_at': '2026-09-06T02:00:00+00:00'},
        {'video_id': 'c', 'title': '都沒有', 'published_at': None},
    ])
    assert rep['from_title'] == 1
    assert rep['from_upload'] == 1
    assert rep['unknown'] == 1


def test_the_report_names_the_videos_that_had_to_be_guessed():
    """★ 只給數字的話，「有 3 部用推的」查不下去 —— 要講是哪幾部。"""
    rep = S.date_source_report([
        {'video_id': 'b', 'title': '這部沒有日期',
         'published_at': '2026-09-06T02:00:00+00:00'},
    ])
    assert rep['guessed'] == ['這部沒有日期']


def test_a_healthy_feed_has_nothing_to_report():
    """★ 平常應該是 0 —— 這個數字的用途就是「平常是 0，變成一批就知道」。"""
    rep = S.date_source_report([
        {'video_id': 'a', 'title': '【主日信息】主題:某某 講員:某某2026-09-06',
         'published_at': '2026-09-07T02:00:00+00:00'},
    ])
    assert rep['from_upload'] == 0 and rep['unknown'] == 0
    assert rep['guessed'] == []


def test_the_admin_page_shows_where_the_dates_came_from():
    """★ 命名改了要**看得見** —— 不然整頁日期悄悄換一個來源，
    而每一組還是一個正常的日期。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / 'templates' / 'admin' / 'sermons.html').read_text(encoding='utf-8')
    assert 'dates.from_title' in src
    assert 'dates.from_upload' in src
    assert 'dates.guessed' in src, '只給數字的話查不下去'


def test_the_admin_route_passes_the_report():
    """★ 模板畫得出來但路由沒傳的話，那一塊會靜靜地空著。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / 'routes' / 'admin_sermons.py').read_text(encoding='utf-8')
    assert 'date_source_report' in src


# ══ YouTube 上改了標題，這邊要跟著改 ═════════════════════
#
#  使用者：「主日信息 我在原本 YOUTUBE 標題打錯有重改
#           可是系統上面沒有跟著修改」
#
#  ★★ 原本的規則是「只新增、不更新」。那個理由**沒有錯**（同工補的
#    講員／經文會被 YouTube 的標題默默洗掉），但它**擋得太寬** ——
#    連 YouTube 自己那幾欄都不更新。
#
#  而標題不只是標題：**講道日期是從標題結尾讀出來的**。標題裡的日期
#  打錯又改好了，系統這邊會**永遠停在錯的那一週**，
#  而那一組看起來完全正常。

def _one(video_id='aaaaaaaaaaa', **over):
    row = {'video_id': video_id, 'title': '舊的標題 2026-09-06',
           'published_at': '2026-09-06T01:30:00+00:00',
           'speaker': '蕭夢熊 牧師', 'scripture': '腓立比書 4:4',
           'is_hidden': False}
    row.update(over)
    return row


def test_a_corrected_title_is_picked_up():
    """★★ 這就是使用者回報的那件事。"""
    store = [_one()]
    S.refresh(block='https://www.youtube.com/playlist?list=PLaaaaaaaaaaaa',
              post=_post(LIST), sb=_FakeSB(store))
    assert store[0]['title'] == '主日信息｜靠主常常喜樂2026-09-06', \
        'YouTube 上改過的標題沒有跟著改'


def test_the_feed_cannot_reach_the_hand_typed_fields_even_if_it_carries_them():
    """★★ 上面那條走的是真的抓取結果（裡面沒有那幾欄），所以它守不到規則本身。
    這一條直接把那幾欄塞進來。"""
    store = [_one()]
    S.merge_changed  # noqa: B018 — 讓讀的人知道下面驗的是同一支
    fetched = [{'video_id': 'aaaaaaaaaaa', 'title': '改過的標題',
                'published_at': 'B', 'speaker': '冒牌', 'is_hidden': True}]
    for vid, patch in S.merge_changed(fetched, {
            'aaaaaaaaaaa': {'title': store[0]['title'],
                            'published_at': store[0]['published_at']}}):
        assert 'speaker' not in patch and 'is_hidden' not in patch, patch


def test_the_hand_typed_fields_are_never_touched():
    """★★ 這是原本那條規則真正要守的東西，**不可以因為修上面那件事而丟掉**。

    講員／經文是同工一筆一筆打的，YouTube 上沒有那些字 ——
    被覆蓋的話補的人下次來看只會覺得自己沒存到。
    """
    store = [_one()]
    S.refresh(block='https://www.youtube.com/playlist?list=PLaaaaaaaaaaaa',
              post=_post(LIST), sb=_FakeSB(store))
    assert store[0]['speaker'] == '蕭夢熊 牧師'
    assert store[0]['scripture'] == '腓立比書 4:4'
    assert store[0]['is_hidden'] is False


def test_hiding_a_video_survives_the_next_fetch():
    """★ 同工把一部藏起來，下一次抓取不可以把它變回來 ——
    那會讓「藏起來」這個動作看起來根本沒作用。"""
    store = [_one(is_hidden=True)]
    S.refresh(block='https://www.youtube.com/playlist?list=PLaaaaaaaaaaaa',
              post=_post(LIST), sb=_FakeSB(store))
    assert store[0]['is_hidden'] is True


def test_a_patch_only_ever_carries_feed_fields():
    """★★ 餵一筆**帶著人打欄位**的資料進去 —— 它們一個都不可以進 patch。

    ★ 第一版這一條是**假的**：抓回來的資料本來就沒有 speaker／scripture，
      所以把 `FEED_FIELDS` 改成包含它們，測試照樣全綠
      （mutation 當場抓到）。守衛不可以靠「輸入剛好沒有那個欄位」成立。
    """
    fetched = [{'video_id': 'v1', 'title': '新的', 'published_at': 'B',
                #  ★ 假裝哪天 parse_playlist 多解析了這幾欄
                'speaker': '別人', 'scripture': '別卷', 'is_hidden': True}]
    known = {'v1': {'title': '舊的', 'published_at': 'A',
                    'speaker': '蕭夢熊 牧師', 'scripture': '腓立比書 4:4',
                    'is_hidden': False}}
    (vid, patch), = S.merge_changed(fetched, known)
    assert vid == 'v1'
    assert set(patch) == {'title', 'published_at'}, patch
    assert not (set(patch) & set(S.HUMAN_FIELDS)), \
        f'人打的欄位跑進 patch 了：{patch}'


def test_nothing_changed_means_no_write():
    """★★ 一樣也照寫的話，每 6 小時就把整張表重寫一次，
    而且後台會報「更新了 60 部」—— 那個數字沒有意義，
    久了就沒有人看那一行。"""
    same = [{'video_id': 'v1', 'title': '一樣', 'published_at': 'A'}]
    known = {'v1': {'title': '一樣', 'published_at': 'A'}}
    assert S.merge_changed(same, known) == []


def test_a_video_we_have_never_seen_is_not_an_update():
    """★ 沒存過的那一部要走 insert，不可以在這裡變成一筆改不到的 update。"""
    fetched = [{'video_id': 'newnewnewnew', 'title': '新片', 'published_at': 'A'}]
    assert S.merge_changed(fetched, {'v1': {'title': 'x'}}) == []


def test_the_refresh_report_says_how_many_were_corrected():
    """★ 改了要**講出來**。默默改掉的話，同工下次看到不一樣的字
    會以為自己記錯了。"""
    store = [_one()]
    r = S.refresh(block='https://www.youtube.com/playlist?list=PLaaaaaaaaaaaa',
                  post=_post(LIST), sb=_FakeSB(store))
    assert r['updated'] == 1
    assert any('靠主常常喜樂' in t for t in r['updated_titles'])


def test_a_fixed_date_in_the_title_moves_the_sermon_to_the_right_week():
    """★★ 這是「標題跟著改」真正要緊的地方。

    `preached_date` 是從標題結尾讀出來的 —— 標題的日期打錯又改好了，
    而系統不跟的話，那一篇會**永遠留在錯的那一週**，
    而畫面上那一組看起來完全正常。
    """
    from datetime import date
    wrong = {'title': '主日信息 2026-09-16', 'published_at': '2026-09-06T01:30:00+00:00'}
    right = {'title': '主日信息 2026-09-06', 'published_at': '2026-09-06T01:30:00+00:00'}
    assert S.preached_date(wrong) == date(2026, 9, 16)
    assert S.preached_date(right) == date(2026, 9, 6)


# ─────────────────────────────────────────────────────────
#  接線：寫好了但沒接上＝沒有做，而畫面看起來只是「教會沒有錄影」
# ─────────────────────────────────────────────────────────

def test_the_real_app_serves_both_pages():
    """★ 真的 create_app（子行程）：前台與後台兩個藍圖都註冊了。"""
    import socket
    import subprocess
    import time
    import urllib.request
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    with socket.socket() as so:
        so.bind(('127.0.0.1', 0))
        port = so.getsockname()[1]
    srv = subprocess.Popen([sys.executable, str(root / 'tests' / 'editor_server.py'), str(port)], cwd=str(root),
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        assert srv.stdout.readline().strip() == 'READY'
        time.sleep(0.3)
        base = f'http://127.0.0.1:{port}'
        front = urllib.request.urlopen(base + '/sermons').read().decode()
        assert '主日信息' in front
        admin = urllib.request.urlopen(base + '/admin/sermons').read().decode()
        assert 'id="playlist-block"' in admin and 'btn-refresh' in admin
    finally:
        srv.kill()


def test_the_home_tile_follows_the_playlist_setting():
    """★ 磁磚的條件是「設定了播放清單」，不是「已經抓到影片」—— 設好但還沒抓到第一部之前，
    前台才不會完全沒有入口（沒有入口的功能等於不存在）。"""
    import re
    root = Path(__file__).resolve().parent.parent
    html = re.sub(r'\{#.*?#\}', '', (root / 'templates' / 'portal.html').read_text(encoding='utf-8'), flags=re.S)
    block = html[html.index('data-key="sermons"') - 200:html.index('data-key="sermons"')]
    assert '{% if sermons_on' in block and 'latest_sermon' not in block
    py = re.sub(r'(?m)#.*$', '', (root / 'routes' / 'event.py').read_text(encoding='utf-8'))
    assert 'sermons_on=sermons_on' in py and 'is_configured' in py


def test_the_scheduled_job_skips_until_it_is_due_and_configured(monkeypatch):
    from routes import tasks
    calls = []
    monkeypatch.setattr(S, 'refresh_throttled', lambda **k: calls.append(1) or {'ok': True})
    monkeypatch.setattr(S, 'due_for_refresh', lambda *a, **k: False)
    assert 'skipped' in tasks._job_fetch_sermons() and not calls
    monkeypatch.setattr(S, 'due_for_refresh', lambda *a, **k: True)
    monkeypatch.setattr(S, 'is_configured', lambda: False)
    assert 'skipped' in tasks._job_fetch_sermons() and not calls
    monkeypatch.setattr(S, 'is_configured', lambda: True)
    assert tasks._job_fetch_sermons() == {'ok': True} and calls == [1]
