"""365 天聖經速讀計畫：把教會那張印出來打勾的表做成數位版

## ★ 這張表沒有日期，所以系統不可以發明日期

教會發的是「365 天聖經速讀計畫表」——一張 9 欄的紙，上面只有小組、姓名和
365 個格子。**沒有任何一格綁定日期**，大家是讀完就打勾。

所以這裡**不做**「今天是第幾天」「你落後 12 天」。365 天計畫的頭號死因是
斷了三天就再也不回來，而「落後 12 天」正是讓人不回來的那句話。
進度只講「你讀了幾格」—— 那是一個不會倒退的數字。

★ 這不是我的偏好，是**照著那張紙原本的樣子**做。紙本不會罵人。

## ★ 計畫內容在 repo，不在資料庫

`data/bible_reading_plan_365.json`。內容是固定的（教會印好的那份），
放在 repo 裡看得到、改得到、而且有測試對著它驗
（365 格、66 卷正典順序、每卷章數連續且蓋滿）。

再存一份到資料庫只是多一個「資料庫跟 repo 說法不一致」的來源，
而不一致的時候**兩邊各自看都正常**。資料庫只存「誰讀完了哪一格」。

## ★ 原表漏了哥林多前書 9-12 章

印出來那張是 林前 1-4 → 5-8 → **13-16**，第 9-12 章沒有任何一格讀到。
使用者決定把那一格改成「林前 9-16」：天數維持 365、編號跟紙本對得上，
而且整本聖經一章不漏。這筆修正**寫在資料檔的 `corrections` 裡**，
不是默默改掉 —— 下次印那張表時才查得到要修什麼。

## ★ 經文內文不放進系統，連出去

預設連到使用者自己架的聖經互動書平台。它的網址用**書卷全名**
（`/read/出埃及記/25`），所以我們資料裡的 `book` 直接就能用 ——
不需要任何簡稱對照表，也就少了一整類「點下去是別卷書」的錯。

★ 網址是**後台可以改的設定**（`bible_reader_url`），不寫死在程式裡。
  理由跟教學影片那兩條一樣：外部網址會搬家、會壞，
  而壞掉時**畫面完全正常** —— 按鈕還在、字還在，
  只有點下去的人看到不對的東西，然後他自己想辦法或放棄，不會回報。

★ 那個平台**任何書名都回 200**，而且 `<title>` 直接照抄網址
  （「不存在的書 第1章」）—— 所以驗證書名時不可以看狀態碼或標題，
  要看頁面裡有沒有真的經文。66 卷是這樣實際打過一次驗的。
"""
import json
from pathlib import Path

PLAN_KEY = 'church365'
TABLE = 'bible_reading_progress'

_PLAN_FILE = Path(__file__).resolve().parent.parent / 'data' / 'bible_reading_plan_365.json'

#  經文連結的預設樣板。`{book}` 是書卷全名、`{chapter}` 是章數。
#  ★ 後台改得動（`site_settings.bible_reader_url`），這裡只是還沒設定時的預設。
DEFAULT_READER_URL = 'https://bibile-actionbook.vercel.app/read/{book}/{chapter}'


_cache = None


def load_plan():
    """讀 repo 裡那份計畫。整份存在記憶體（69KB，一次就好）。"""
    global _cache
    if _cache is None:
        _cache = json.loads(_PLAN_FILE.read_text(encoding='utf-8'))
    return _cache


def active_plan_key():
    """現在全教會在跑的是哪一份計畫。

    ★★ **算不出來一律回內建那一份**（`PLAN_KEY`）。使用者：
       「目前的整個教會已經再跑了 不動」—— 資料庫抖一下就把全教會
       換到別份計畫的話，每個人的進度會**看起來歸零**
       （其實還在，只是在另一個 plan_key 底下），
       那是這個功能最不能出的錯。
    """
    try:
        from routes.reading_plans import active_key
        return active_key() or PLAN_KEY
    except Exception:
        return PLAN_KEY


def days():
    """目前啟用那一份計畫的格子。

    ★ 後台沒加過任何計畫時，這裡回的就是 repo 裡那一份 ——
      跟這個功能上線前**一模一樣**。
    """
    key = active_plan_key()
    if key == PLAN_KEY:
        return load_plan()['days']
    try:
        from routes.reading_plans import days_of
        return days_of(key) or load_plan()['days']
    except Exception:
        return load_plan()['days']


def _int0(v):
    """空值明確算 0（結構守衛不准寫 `or 0`）。"""
    return 0 if v is None or v == '' else int(v)


def total():
    return len(days())


def reader_template():
    """經文連結的樣板。後台沒設過就用預設。"""
    try:
        from settings_store import get
        return (get('bible_reader_url') or '').strip() or DEFAULT_READER_URL
    except Exception:
        return DEFAULT_READER_URL


def read_url(day, template=None):
    """那一格的經文連到哪裡。設定被清空就回 None（不要瞎給一個網址）。

    ★ 只帶**起始章** —— 那些平台一次顯示一章，帶章範圍它們不認。
      連到第一章、人自己往下翻，那是讀經本來的動作。

    ★ 書名要 URL 編碼。不編的話中文書名在某些瀏覽器／LINE 內建瀏覽器
      會被截掉，而那條連結看起來完全正常。
    """
    from urllib.parse import quote
    tpl = template if template is not None else reader_template()
    if not tpl:
        return None
    book = day.get('book')
    if not book:
        return None
    return (tpl.replace('{book}', quote(str(book), safe=''))
               .replace('{chapter}', str(day['chapter_start'])))


def by_book(done=None):
    """依經卷分組 —— 使用者要的是這個，不是 365 條流水帳。

    回 [{book, abbrev, testament, days:[…], done, total}]
    """
    done = set(done or ())
    groups, order = {}, []
    for d in days():
        key = d['book']
        if key not in groups:
            groups[key] = {
                'book': d['book'], 'abbrev': d['abbrev'],
                'testament': d['testament'], 'book_order': d['book_order'],
                'days': [], 'done': 0,
            }
            order.append(key)
        row = dict(d)
        row['done'] = d['day_no'] in done
        row['url'] = read_url(d)
        groups[key]['days'].append(row)
        if row['done']:
            groups[key]['done'] += 1
    out = [groups[k] for k in order]
    for g in out:
        g['total'] = len(g['days'])
    return out


def next_unread(done=None):
    """接下來要讀的那一格 —— 第一個還沒打勾的。全部讀完回 None。

    ★ 是「第一個沒打勾的」不是「最後打勾的下一格」。
      跳著讀（先讀新約）的人，用後者會把前面沒讀的整段跳過去，
      而他的進度條看起來一路往前。
    """
    done = set(done or ())
    for d in days():
        if d['day_no'] not in done:
            row = dict(d)
            row['url'] = read_url(d)
            return row
    return None


def summarise(done=None):
    """畫面最上面那幾個數字。"""
    done = set(done or ())
    all_days = days()
    valid = {d['day_no'] for d in all_days}
    #  ★ 只算計畫裡真的有的格子。舊資料留下的 day_no（換過計畫）
    #    會讓進度變成 370/365，而那個數字沒有人看得懂
    real = done & valid
    chapters = sum(d['chapter_end'] - d['chapter_start'] + 1
                   for d in all_days if d['day_no'] in real)
    return {
        'done': len(real),
        'total': len(all_days),
        'chapters': chapters,
        'percent': round(len(real) * 100 / len(all_days)) if all_days else 0,
    }


# ─────────────────────────────────────────────────────────
#  進度（碰資料庫）
# ─────────────────────────────────────────────────────────

def _sb():
    from db import supabase
    return supabase


def done_days(user_id, sb=None):
    """這個人打過勾的 day_no。撈不到回空集合 —— 讓他看得到計畫，
    只是進度是空的（比整頁 500 好）。"""
    if not user_id:
        return set()
    sb = sb or _sb()
    try:
        rows = sb.table(TABLE).select('day_no')\
            .eq('user_id', user_id).eq('plan_key', active_plan_key()).execute().data or []
    except Exception:
        return set()
    return {r['day_no'] for r in rows}


def read_dates(user_id, sb=None):
    """`{day_no: date}` —— 那一格是**哪一天**打勾的。

    使用者：「這個表可以標記讀過的日期嗎 純粹是顯示、記錄自己
    不是催別人讀經」。

    ## ★ 資料本來就在，只是從來沒拿出來

    `mark()` 每次打勾都寫了 `read_on`（台北日期）—— 所以**他過去打的
    每一個勾都有日期**，不用重來、也沒有一段空白。`done_days()` 只
    `select('day_no')`，那一欄一直沒有人讀。

    ## ★ 沒有日期的那一格不要編一個

    萬一某一列的 `read_on` 是空的（或壞的），那一格就**不顯示日期**，
    不要退回今天或退回別的東西 —— 印在紙上的日期他會當真，
    而「那天我明明沒讀」是查不回來的。

    ★ 回的是 `datetime.date`，不是字串：字串會誘人去切
    （`raw[:10]` 那一類），而這個專案整章在講那件事。
    """
    from datetime import date as _date
    if not user_id:
        return {}
    sb = sb or _sb()
    try:
        rows = sb.table(TABLE).select('day_no, read_on')\
            .eq('user_id', user_id).eq('plan_key', active_plan_key()).execute().data or []
    except Exception:
        return {}
    out = {}
    for r in rows:
        raw = r.get('read_on')
        if not raw:
            continue
        try:
            out[r['day_no']] = raw if isinstance(raw, _date) else _date.fromisoformat(str(raw))
        except (TypeError, ValueError):
            continue          # 壞掉的那一格不顯示日期，不要猜一個
    return out


def mark(user_id, day_no, today=None, sb=None):
    """打勾。★ 主鍵是 (user_id, plan_key, day_no)，所以連按兩下
    不會長出第二列，也不必先查再寫。"""
    from routes.tw_time import TAIPEI_TZ
    from datetime import datetime
    sb = sb or _sb()
    day = today or datetime.now(TAIPEI_TZ).date().isoformat()
    sb.table(TABLE).upsert({
        'user_id': user_id, 'plan_key': active_plan_key(),
        'day_no': int(day_no), 'read_on': day,
    }).execute()


def unmark(user_id, day_no, sb=None):
    """取消打勾 —— 按錯了要救得回來，不然那一格永遠是綠的。"""
    sb = sb or _sb()
    sb.table(TABLE).delete()\
        .eq('user_id', user_id).eq('plan_key', active_plan_key())\
        .eq('day_no', int(day_no)).execute()


def reread_info(user_id, day_no, sb=None):
    """這一格的重讀紀錄 `{'count': n, 'last': date|None}`。

    ★ 查不到（欄位還沒建、資料庫抖一下、這一格根本沒打過勾）一律回 None ——
      呼叫端把 None 當成「不要畫重讀那一塊」，而不是「重讀 0 次」：
      欄位沒建時畫出一顆按了一定失敗的鈕，比不畫更糟。
    """
    from datetime import date as _date
    sb = sb or _sb()
    try:
        rows = sb.table(TABLE).select('reread_count, last_reread_on')\
            .eq('user_id', user_id).eq('plan_key', active_plan_key())\
            .eq('day_no', int(day_no)).execute().data or []
    except Exception:
        return None
    if not rows or 'reread_count' not in rows[0]:
        return None
    r = rows[0]
    last = r.get('last_reread_on')
    try:
        last = last if (last is None or isinstance(last, _date)) else _date.fromisoformat(str(last))
    except (TypeError, ValueError):
        last = None
    return {'count': _int0(r.get('reread_count')), 'last': last}


def mark_reread(user_id, day_no, today=None, sb=None):
    """記一次重讀。回 `{'count', 'last', 'added'}`；這一格沒打過勾回 None。

    ★ **同一格一天最多記一次**：長輩連點是常態，一次手滑不該變成「重讀三次」。
      今天已經記過就原樣回傳（added=False），不報錯。
    ★ 只動 reread_count / last_reread_on，**不碰 read_on**（第一次讀的日期）。
    """
    from datetime import datetime
    from routes.tw_time import TAIPEI_TZ
    sb = sb or _sb()
    today = today or datetime.now(TAIPEI_TZ).date()
    cur = reread_info(user_id, day_no, sb)
    if cur is None:
        return None
    if cur['last'] == today:
        return {**cur, 'added': False}
    n = cur['count'] + 1
    sb.table(TABLE).update({'reread_count': n, 'last_reread_on': today.isoformat()})\
        .eq('user_id', user_id).eq('plan_key', active_plan_key())\
        .eq('day_no', int(day_no)).execute()
    return {'count': n, 'last': today, 'added': True}


# ─────────────────────────────────────────────────────────
#  前台
# ─────────────────────────────────────────────────────────

from flask import (Blueprint, render_template, session, redirect,  # noqa: E402
                   request, url_for, jsonify)

from routes.decorators import login_required  # noqa: E402

bible_plan_bp = Blueprint('bible_plan', __name__)


@bible_plan_bp.route('/reading')
@login_required
def reading_page():
    uid = session['user_id']
    done = done_days(uid)
    return render_template('bible_reading.html',
                           plan=load_plan(),
                           stats=summarise(done),
                           nxt=next_unread(done),
                           books=by_book(done))


@bible_plan_bp.route('/reading/mark', methods=['POST'])
@login_required
def reading_mark():
    """打勾／取消打勾。

    ★ 回的是**打勾之後的整組數字**，不是一句 ok —— 前端要立刻更新
      進度條和「接下來要讀的」那一格。讓前端自己算一份的話，
      重新整理才會發現兩邊不一樣，而兩邊各自看都正常。
    """
    uid = session['user_id']
    data = request.get_json() or {}
    try:
        day_no = int(data.get('day_no'))
    except (TypeError, ValueError):
        return jsonify({'error': '沒有指定是哪一格'}), 400
    if not any(d['day_no'] == day_no for d in days()):
        return jsonify({'error': '這個計畫裡沒有這一格'}), 400

    try:
        if data.get('done'):
            mark(uid, day_no)
        else:
            unmark(uid, day_no)
    except Exception:
        return jsonify({'error': '存不進去，請再試一次'}), 500

    fresh = done_days(uid)
    nxt = next_unread(fresh)
    return jsonify({
        'ok': True,
        'stats': summarise(fresh),
        'next': ({'day_no': nxt['day_no'], 'label': nxt['label'],
                  'book': nxt['book'], 'url': nxt['url']} if nxt else None),
    })


@bible_plan_bp.route('/reading/reread', methods=['POST'])
@login_required
def reading_reread():
    """「我重讀完了」：記一次重讀（只有打過勾的格子才記得進去）。"""
    try:
        day_no = int((request.get_json() or {}).get('day_no'))
    except (TypeError, ValueError):
        return jsonify({'error': '沒有指定是哪一格'}), 400
    try:
        res = mark_reread(session['user_id'], day_no)
    except Exception:
        return jsonify({'error': '存不進去，請再試一次'}), 500
    if res is None:
        return jsonify({'error': '這一格還沒標記讀過，不能記重讀'}), 400
    return jsonify({'ok': True, 'count': res['count'],
                    'last': res['last'].isoformat() if res['last'] else None,
                    'added': res['added']})


@bible_plan_bp.route('/reading/<int:day_no>')
@login_required
def reading_day(day_no):
    """一格的專屬閱讀頁：經文就在這裡，不跳出去。

    ★ 為什麼不是在首頁展開：一格常常是 100-130 節。在首頁展開的話，
      它會把下面的提醒、報名、主日信息全部推到 130 節經文之後 ——
      而那個代價每天落在**每一個人**身上，包括沒在讀速讀的人。

    ★ 「確認讀過」和「讀四章」是兩件事：前者一秒，所以留在首頁；
      後者十分鐘，需要自己的空間、常駐的朗讀控制，
      而且「我讀完了」要在**讀完的地方**（最下面）。
    """

    day = next((d for d in days() if d['day_no'] == day_no), None)
    if not day:
        from flask import abort
        abort(404)

    from routes.bible_text import get_passage
    try:
        sections = get_passage(day)
    except Exception:
        #  ★ 抓經文壞掉不可以讓這一頁打不開 —— 至少要看得到「今天讀哪裡」
        #    和外連，那樣他還讀得成
        sections = []

    uid = session['user_id']
    done = done_days(uid)
    #  ★ 重讀：這一格讀過了、而且**下一格也讀過了**，才給「重讀下一格」。
    #    下一格還沒讀的話那是「繼續讀」（走 nxt），標成重讀是錯的。
    following = next((d for d in days() if d['day_no'] == day_no + 1), None)
    reread_next = following if (following and day_no in done
                                and following['day_no'] in done) else None
    #  ★ 只有「讀過的格子 ＋ 欄位真的存在」才給重讀紀錄；其他一律 None，
    #    頁面整塊不畫（見 reread_info）。
    reread = reread_info(uid, day_no) if day_no in done else None
    return render_template('bible_reading_day.html',
                           day=day,
                           reread=reread,
                           reread_next=reread_next,
                           sections=sections,
                           url=read_url(day),
                           is_done=day_no in done,
                           stats=summarise(done),
                           nxt=next_unread(done | {day_no}))


def my_group():
    """這個人在表頭上要印哪一組。算不出來回 None（那一格就留空）。

    ★ 走 `collection.collecting_group` 那份**唯一的**規則，不自己再寫一份。
      一個人可能掛在兩個主標籤小組上 —— 兩邊各自挑的話，
      速讀表印的組和收款單上的組會不一樣，**而兩張各自看都正常**。
    """
    try:
        from routes.collection import collecting_group, _primary_group_names
        return collecting_group({'group_tags': session.get('group_tags') or []},
                                _primary_group_names())
    except Exception:
        return None


@bible_plan_bp.route('/reading/sheet')
@login_required
def reading_sheet():
    """印出來的那張表 —— 跟教會發的紙本同一個樣子。

    ★ 為什麼要做這一頁：速讀完會發證書，而證書要對著一張**看得到全部
      365 格**的表。畫面上的「依經卷」清單是給手機捲的，印出來會變成
      四十幾頁 —— 沒有人會拿那個去換證書。

    ★ 表頭要有小組和姓名，因為紙本就是這樣（那兩格是拿去交的憑據）。
    """

    uid = session['user_id']
    done = done_days(uid)
    #  ★ 每一格是哪一天讀的 —— 使用者要的是「記錄自己」，不是進度管理。
    #    所以只印日期，不算「幾天沒讀」「落後幾格」那一類的東西
    #    （那正是 365 天計畫的頭號死因，這個專案第一天就決定不做）。
    when = read_dates(uid)
    rows = []
    for d in days():
        day = when.get(d['day_no'])
        rows.append({**d, 'done': d['day_no'] in done,
                     #  沒有日期就留空 —— 不要編一個印在紙上
                     'read_label': '%d/%d' % (day.month, day.day) if day else ''})
    return render_template('bible_reading_sheet.html',
                           rows=rows,
                           stats=summarise(done),
                           group=my_group(),
                           name=session.get('real_name') or '',
                           plan=load_plan())
