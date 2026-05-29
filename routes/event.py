# 活動相關路由
from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from db import supabase
from datetime import datetime, timezone, date, timedelta
import random
import re
from routes.notifications import create_notification
from routes.decorators import login_required


def _extract_youtube_id(url: str) -> str | None:
    """從各種 YouTube URL 格式中取出 video ID"""
    if not url:
        return None
    patterns = [
        r'youtube\.com/watch\?v=([A-Za-z0-9_-]{11})',
        r'youtu\.be/([A-Za-z0-9_-]{11})',
        r'youtube\.com/embed/([A-Za-z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

# ── 每日經文資料庫 ──────────────────────────────────────────────
DAILY_VERSES = [
    {"text": "我靠著那加給我力量的，凡事都能做。", "ref": "腓立比書 4:13"},
    {"text": "你要專心仰賴耶和華，不可倚靠自己的聰明，在你一切所行的事上都要認定他，他必指引你的路。", "ref": "箴言 3:5-6"},
    {"text": "耶和華是我的牧者，我必不至缺乏。", "ref": "詩篇 23:1"},
    {"text": "要將你的事交託耶和華，並倚靠他，他就必成全。", "ref": "詩篇 37:5"},
    {"text": "神愛世人，甚至將他的獨生子賜給他們，叫一切信他的，不至滅亡，反得永生。", "ref": "約翰福音 3:16"},
    {"text": "我的恩典夠你用的，因為我的能力是在人的軟弱上顯得完全。", "ref": "哥林多後書 12:9"},
    {"text": "應當一無掛慮，只要凡事藉著禱告、祈求，和感謝，將你們所要的告訴神。", "ref": "腓立比書 4:6"},
    {"text": "耶和華啊，你是我的力量，我的磐石，我的山寨，我的救主，我的神，我的磐石，我所投靠的。", "ref": "詩篇 18:2"},
    {"text": "你們祈求，就給你們；尋找，就尋見；叩門，就給你們開門。", "ref": "馬太福音 7:7"},
    {"text": "我是道路、真理、生命；若不藉著我，沒有人能到父那裡去。", "ref": "約翰福音 14:6"},
    {"text": "愛是恆久忍耐，又有恩慈；愛是不嫉妒；愛是不自誇，不張狂。", "ref": "哥林多前書 13:4"},
    {"text": "耶和華是我的亮光，是我的拯救，我還怕誰呢？", "ref": "詩篇 27:1"},
    {"text": "你們要先求他的國和他的義，這些東西都要加給你們了。", "ref": "馬太福音 6:33"},
    {"text": "我是葡萄樹，你們是枝子；常在我裡面的，我也常在他裡面，這人就多結果子。", "ref": "約翰福音 15:5"},
    {"text": "聖靈所結的果子，就是仁愛、喜樂、和平、忍耐、恩慈、良善、信實、溫柔、節制。", "ref": "加拉太書 5:22-23"},
    {"text": "不要憂慮，當以感恩的心，藉著禱告將你的事告訴神，神所賜出人意外的平安，必在基督耶穌裡保守你的心懷意念。", "ref": "腓立比書 4:6-7"},
    {"text": "我們曉得萬事都互相效力，叫愛神的人得益處，就是按他旨意被召的人。", "ref": "羅馬書 8:28"},
    {"text": "耶和華必為你爭戰，你只管靜默，不要作聲。", "ref": "出埃及記 14:14"},
    {"text": "你所行的，要交託耶和華，你所謀的，就必成立。", "ref": "箴言 16:3"},
    {"text": "我賜給你們一條新命令，乃是叫你們彼此相愛；我怎樣愛你們，你們也要怎樣相愛。", "ref": "約翰福音 13:34"},
    {"text": "神是我們的避難所，是我們的力量，是我們在患難中隨時的幫助。", "ref": "詩篇 46:1"},
    {"text": "要常常喜樂，不住地禱告，凡事謝恩，因為這是神在基督耶穌裡向你們所定的旨意。", "ref": "帖撒羅尼迦前書 5:16-18"},
    {"text": "你們得救是本乎恩，也因著信，這並不是出於自己，乃是神所賜的。", "ref": "以弗所書 2:8"},
    {"text": "我的神必照他榮耀的豐富，在基督耶穌裡，使你們一切所需用的都充足。", "ref": "腓立比書 4:19"},
    {"text": "你的話是我腳前的燈，是我路上的光。", "ref": "詩篇 119:105"},
    {"text": "耶穌對他說：你要盡心、盡性、盡意愛主你的神。這是誡命中的第一，且是最大的。", "ref": "馬太福音 22:37-38"},
    {"text": "我靠著主大大地歡樂，因為你們思念我的心如今又發生；你們向來就思念我，只是沒得機會。", "ref": "腓立比書 4:10"},
    {"text": "凡勞苦擔重擔的人可以到我這裡來，我就使你們得安息。", "ref": "馬太福音 11:28"},
    {"text": "你的慈愛比生命更好，我的嘴唇要讚美你。", "ref": "詩篇 63:3"},
    {"text": "你們要休息，要知道我是神！我必在外邦中被尊崇，在遍地上也被尊崇。", "ref": "詩篇 46:10"},
    {"text": "耶和華使人死，也使人活；使人下陰間，也使人從那裡上來。", "ref": "撒母耳記上 2:6"},
    {"text": "凡事謙虛、溫柔、忍耐，用愛心互相寬容，用和平彼此聯絡，竭力保守聖靈所賜合而為一的心。", "ref": "以弗所書 4:2-3"},
    {"text": "因為，凡神的兒子都是靠信心得勝世界的。", "ref": "約翰一書 5:4"},
    {"text": "我雖然行過死蔭的幽谷，也不怕遭害，因為你與我同在。", "ref": "詩篇 23:4"},
    {"text": "主耶和華是我的力量；他使我的腳快如母鹿的蹄，又使我穩行在高處。", "ref": "哈巴谷書 3:19"},
    {"text": "在日落以前要消除你們的怒氣，不可給魔鬼留地步。", "ref": "以弗所書 4:26-27"},
    {"text": "你們若有信心，不疑惑，不但可以行無花果樹上所行的事，就是對這座山說：你挪開此地，投在海裡，也必成就。", "ref": "馬太福音 21:21"},
    {"text": "信心是所望之事的實底，是未見之事的確據。", "ref": "希伯來書 11:1"},
    {"text": "你要以耶和華為樂，他就將你心裡所求的賜給你。", "ref": "詩篇 37:4"},
    {"text": "耶和華說：我知道我向你們所懷的意念是賜平安的意念，不是降災禍的意念，要叫你們末後有指望。", "ref": "耶利米書 29:11"},
    {"text": "親愛的，我願你凡事興盛，身體健壯，正如你的靈魂興盛一樣。", "ref": "約翰三書 1:2"},
    {"text": "凡你手所當做的事要盡力去做；因為在你所必去的陰間沒有工作，沒有謀算，沒有知識，也沒有智慧。", "ref": "傳道書 9:10"},
    {"text": "我的力量因你而剛強，我全心愛你，耶和華我的力量。", "ref": "詩篇 18:1"},
    {"text": "求你用神蹟奇事的膀臂救贖你的百姓，就是雅各和約瑟的眾子孫，直到永遠。", "ref": "詩篇 77:15"},
    {"text": "你們是世上的光。城造在山上，是不能隱藏的。", "ref": "馬太福音 5:14"},
    {"text": "你們是世上的鹽。鹽若失了味，怎能叫它再鹹呢？以後無用，不過丟在外面，被人踐踏了。", "ref": "馬太福音 5:13"},
    {"text": "有信心，又有行為，才是完全人。", "ref": "雅各書 2:22"},
    {"text": "弟兄們，我還有未盡的話：凡是真實的、可敬的、公義的、清潔的、可愛的、有美名的事，若有什麼德行，若有什麼稱讚，這些事你們都要思念。", "ref": "腓立比書 4:8"},
    {"text": "我能做任何事，是因基督加力量給我。", "ref": "腓立比書 4:13 (現代譯本)"},
    {"text": "你是我的幫助；你是救我脫離仇敵之手的神。", "ref": "詩篇 18:17"},
    {"text": "我的神啊，求你按你的慈愛施恩於我！", "ref": "詩篇 51:1"},
]

# ── 經文卡片主題（日期+用戶獨立隨機，不跟 verse_index 掛鉤）──────
import hashlib as _hashlib

VERSE_THEMES = [
    {"name": "紫霞",
     "gradient": "linear-gradient(145deg,#4a148c 0%,#7b1fa2 35%,#e91e63 70%,#ff6f00 100%)",
     "symbol": "✝", "deco": "circles"},
    {"name": "晴空藍",
     "gradient": "linear-gradient(135deg,#0d47a1 0%,#1565c0 40%,#0288d1 75%,#26c6da 100%)",
     "symbol": "✦", "deco": "rings"},
    {"name": "翡翠綠",
     "gradient": "linear-gradient(150deg,#1b5e20 0%,#2e7d32 45%,#00897b 75%,#26a69a 100%)",
     "symbol": "✝", "deco": "waves"},
    {"name": "夕陽橘",
     "gradient": "linear-gradient(135deg,#7f0000 0%,#c62828 30%,#ef6c00 65%,#f9a825 100%)",
     "symbol": "✝", "deco": "cross"},
    {"name": "玫瑰金",
     "gradient": "linear-gradient(145deg,#6d1b7b 0%,#c2185b 40%,#f48fb1 70%,#ffd54f 100%)",
     "symbol": "✝", "deco": "diamond"},
    {"name": "星夜",
     "gradient": "linear-gradient(160deg,#050a30 0%,#0d1b6e 40%,#1a237e 70%,#283593 100%)",
     "symbol": "✦", "deco": "stars"},
    {"name": "薰衣草",
     "gradient": "linear-gradient(135deg,#311b92 0%,#4527a0 35%,#9c27b0 65%,#e91e63 100%)",
     "symbol": "✝", "deco": "rays"},
    {"name": "極光青",
     "gradient": "linear-gradient(145deg,#004d40 0%,#006064 35%,#00838f 65%,#4db6ac 100%)",
     "symbol": "✝", "deco": "diagonal"},
    {"name": "深海靛",
     "gradient": "linear-gradient(160deg,#0a0a2e 0%,#0d2060 40%,#1a4080 65%,#1976d2 100%)",
     "symbol": "✦", "deco": "dots"},
    {"name": "熔岩金",
     "gradient": "linear-gradient(145deg,#3e1a00 0%,#bf360c 35%,#e64a19 60%,#ffa000 100%)",
     "symbol": "✝", "deco": "cross"},
    {"name": "迷霧森林",
     "gradient": "linear-gradient(150deg,#1a2a1a 0%,#2e4a2e 40%,#558b2f 70%,#9ccc65 100%)",
     "symbol": "✦", "deco": "diagonal"},
    {"name": "珊瑚粉",
     "gradient": "linear-gradient(135deg,#880e4f 0%,#c2185b 30%,#e91e63 55%,#ff8a80 100%)",
     "symbol": "✝", "deco": "rings"},
    {"name": "皇室藍金",
     "gradient": "linear-gradient(145deg,#0d0d40 0%,#1a237e 40%,#283593 65%,#c6a84b 100%)",
     "symbol": "✦", "deco": "rays"},
    {"name": "暗夜紫金",
     "gradient": "linear-gradient(150deg,#1a0030 0%,#4a0072 40%,#7b1fa2 65%,#ffd740 100%)",
     "symbol": "✝", "deco": "stars"},
]

def _pick_theme(user_id: str, today_str: str, extra: list = None) -> dict:
    """每天每人得到獨立且固定的主題；extra 為後台上傳的自訂主題清單"""
    pool = VERSE_THEMES + (extra or [])
    h = int(_hashlib.md5(f"{user_id}:{today_str}".encode()).hexdigest(), 16)
    return pool[h % len(pool)]

event_bp = Blueprint('event', __name__)


def is_registration_open(event):
    """判斷報名是否開放（手動開關 + 時間限制雙重判斷）"""
    if not event.get('is_open'):
        return False
    now = datetime.now(timezone.utc).isoformat()
    if event.get('reg_start') and event['reg_start'] > now:
        return False  # 尚未到報名開始時間
    if event.get('reg_end') and event['reg_end'] < now:
        return False  # 報名截止時間已過
    return True


@event_bp.route('/')
@login_required
def portal():
    """門戶首頁：附帶現正開放報名的活動與課程"""
    now = datetime.now(timezone.utc).isoformat()

    # 撈現正開放報名的活動
    try:
        all_events = supabase.table('events')\
            .select('id, title, event_start, location, is_open, reg_start, reg_end')\
            .order('event_start', desc=False)\
            .execute().data or []
        open_events = [e for e in all_events if is_registration_open(e)]
    except Exception:
        open_events = []

    # 懶式關閉過期課程（避免靠 DB cron）
    try:
        now_tw = datetime.now(timezone.utc).isoformat()
        supabase.table('courses').update({'is_open': False})\
            .eq('is_open', True)\
            .not_.is_('reg_deadline', 'null')\
            .lt('reg_deadline', now_tw).execute()
    except Exception:
        pass

    # 撈現正開放報名的門訓課程
    try:
        all_courses = supabase.table('courses')\
            .select('id, title, period, is_open, total_sessions, material_fee, reg_deadline')\
            .eq('is_open', True)\
            .order('created_at', desc=False)\
            .execute().data or []
        open_courses = all_courses
    except Exception:
        open_courses = []

    # 快捷連結從 DB 載入
    try:
        portal_links = supabase.table('portal_links')\
            .select('*').eq('is_active', True).order('sort_order').execute().data or []
    except Exception:
        portal_links = []

    # 同工判斷：查 user 的 group_tags 是否包含任何 is_staff=true 的小組
    group_tags = session.get('group_tags') or []
    is_staff = False
    if group_tags:
        try:
            staff_groups = supabase.table('groups')\
                .select('name').eq('is_staff', True).execute().data or []
            staff_names = {g['name'] for g in staff_groups}
            is_staff = bool(staff_names & set(group_tags))
        except Exception:
            is_staff = '同工' in group_tags  # fallback

    # 撈最新一份週報
    latest_bulletin = None
    try:
        bl = supabase.table('weekly_bulletins')\
            .select('*')\
            .order('bulletin_date', desc=True)\
            .limit(1)\
            .execute()
        if bl.data:
            latest_bulletin = bl.data[0]
    except Exception:
        pass

    # 撈使用者自己的近期已報名活動
    # 利用已撈到的 all_events，只需一個額外的 registrations query
    my_upcoming: list = []
    uid = session.get('user_id')
    if uid:
        try:
            my_regs = supabase.table('registrations')\
                .select('event_id')\
                .eq('user_id', uid)\
                .eq('status', 'registered')\
                .execute().data or []
            my_event_ids = {r['event_id'] for r in my_regs}
            today = now[:10]  # YYYY-MM-DD
            my_upcoming = [
                e for e in all_events
                if e['id'] in my_event_ids
                and (e.get('event_end') or e.get('event_start') or '') >= now
            ][:3]
        except Exception:
            pass

    # ── 本週小組討論（當週有排程才顯示）──
    group_discussion = None
    try:
        today_str = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')  # 台灣日期
        gd = supabase.table('group_discussions')\
            .select('*')\
            .eq('is_active', True)\
            .lte('display_start', today_str)\
            .gte('display_end', today_str)\
            .order('created_at', desc=True)\
            .limit(1)\
            .execute()
        if gd.data:
            import json as _json
            item = gd.data[0]
            item['video_id'] = _extract_youtube_id(item.get('youtube_url', ''))
            # questions 欄位可能是 JSON 字串，統一轉成 list
            q = item.get('questions')
            if isinstance(q, str):
                try:
                    item['questions'] = _json.loads(q)
                except Exception:
                    item['questions'] = []
            group_discussion = item
    except Exception:
        pass

    # ── 門戶卡片設定（超管可控）──
    is_super = session.get('is_super_admin', False)
    # 嘗試從 portal_cards 表載入（新系統）；失敗時回退到舊 portal_card_settings
    portal_cards_config = {}
    try:
        pc_rows = supabase.table('portal_cards').select('*').order('sort_order').execute().data or []
        if pc_rows:
            portal_cards_config = {r['key']: r for r in pc_rows}
    except Exception:
        pass

    # 舊版相容：card_settings 決定卡片顯示開關
    card_settings = {'events': True, 'courses': True, 'verse': True,
                     'prayer': True, 'bulletin': True}
    if portal_cards_config:
        for key, card in portal_cards_config.items():
            card_settings[key] = card.get('is_active', True)
    else:
        try:
            rows = supabase.table('portal_card_settings').select('*').execute().data or []
            for r in rows:
                card_settings[r['key']] = r['is_visible']
        except Exception:
            pass

    # 超管看全部連結（含隱藏的），一般人只看 is_active=True
    all_portal_links = portal_links
    if is_super:
        try:
            all_portal_links = supabase.table('portal_links')\
                .select('*').order('sort_order').execute().data or []
        except Exception:
            pass

    # ── 角色判斷：牧者、小組長、待辦週報 ──
    # 每次載入 portal 時從 DB 刷新 is_pastor / is_staff / is_super_admin，
    # 避免管理員設定後要重新登入才生效的問題。
    is_pastor = session.get('is_pastor', False)
    if uid:
        try:
            role_row = supabase.table('users')\
                .select('is_pastor, is_staff, is_super_admin')\
                .eq('id', uid).single().execute()
            if role_row.data:
                is_pastor = bool(role_row.data.get('is_pastor', False))
                session['is_pastor']      = is_pastor
                session['is_staff']       = bool(role_row.data.get('is_staff', False))
                session['is_super_admin'] = bool(role_row.data.get('is_super_admin', False))
        except Exception:
            pass
    is_group_leader = False
    pending_report = False
    leader_groups = []

    if uid:
        try:
            leader_result = supabase.table('cell_group_leaders')\
                .select('group_id, cell_groups(id, name, weekly_gather_day)')\
                .eq('user_id', uid).execute()
            if leader_result.data:
                is_group_leader = True
                leader_groups = leader_result.data
                # 依各組實際聚會日計算本週日期，再精確查詢
                today_date = date.today()
                weekday_map = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6}

                def _meeting_date(group_data, ref):
                    day_str = (group_data.get('weekly_gather_day') or '').strip()
                    target = None
                    for ch, w in weekday_map.items():
                        if ch in day_str:
                            target = w
                            break
                    if target is None:
                        target = 6  # 預設週日
                    return ref - timedelta(days=(ref.weekday() - target) % 7)

                for lg in leader_groups:
                    gid = lg['group_id']
                    group_data = lg.get('cell_groups') or {}
                    week_date = _meeting_date(group_data, today_date)
                    report_check = supabase.table('cell_reports')\
                        .select('id, is_complete, no_meeting')\
                        .eq('group_id', gid)\
                        .eq('week_date', week_date.isoformat())\
                        .execute()
                    row = report_check.data[0] if report_check.data else None
                    if not row or not (row.get('is_complete') or row.get('no_meeting')):
                        pending_report = True
                        break
        except Exception:
            pass

    # ── 聚會人數（牧者/同工/管理員在首頁顯示）──
    attendance_summary = None
    if is_pastor or is_staff or session.get('is_admin'):
        try:
            from routes.cell_report import _get_meeting_settings, _get_last_weekday_date
            mcfg = _get_meeting_settings()
            today = date.today()

            def _last_weekday_date(wd):
                days = (today.weekday() - wd) % 7
                return (today - timedelta(days=days)).isoformat()

            def _by_date(table, date_str, *cols):
                fields = ','.join(cols)
                r = supabase.table(table).select(fields).eq('date', date_str).execute()
                row = r.data[0] if r.data else {}
                row.setdefault('date', date_str)
                return row

            sunday_date   = _last_weekday_date(mcfg['adult_sunday']['weekday'])
            children_date = _last_weekday_date(mcfg['children_sunday']['weekday'])
            prayer_date   = _last_weekday_date(mcfg['prayer']['weekday'])
            morning_date  = _last_weekday_date(mcfg['morning_prayer']['weekday'])

            attendance_summary = {
                'sunday':   _by_date('sunday_reports',          sunday_date,   'date','first_service_count','second_service_count'),
                'children': _by_date('children_sunday_reports', children_date, 'date','attendance_count'),
                'prayer':   _by_date('prayer_reports',          prayer_date,   'date','attendance_count'),
                'morning':  _by_date('morning_prayer_reports',  morning_date,  'date','attendance_count'),
            }
        except Exception:
            pass

    # ── Hero 主題（與今日經文同步）──
    today_tw = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    try:
        _hc_raw = supabase.table('verse_custom_themes')\
            .select('name,image_url,symbol,text_mode')\
            .eq('is_active', True).order('sort_order').execute().data or []
        _hero_custom = [{'name': t['name'], 'image_url': t['image_url'],
                         'symbol': t['symbol'], 'text_mode': t['text_mode']} for t in _hc_raw]
    except Exception:
        _hero_custom = []
    hero_theme = _pick_theme(uid or 'guest', today_tw, _hero_custom)

    # 未讀 changelog
    from routes.changelog import get_unread_changelog
    try:
        user_row = supabase.table('users').select('last_seen_changelog_at')\
            .eq('id', uid).execute().data
        last_seen = user_row[0].get('last_seen_changelog_at') if user_row else None
    except Exception:
        last_seen = None
    unread_changelog = get_unread_changelog(last_seen) if uid else None

    # 是否為全職同工（有 staff_profiles 記錄）
    is_fulltime_staff = False
    if uid:
        try:
            sp = supabase.table('staff_profiles').select('id')\
                .eq('user_id', uid).eq('is_active', True).limit(1).execute().data
            is_fulltime_staff = bool(sp)
        except Exception:
            pass

    return render_template('portal.html',
        open_events=open_events,
        open_courses=open_courses,
        portal_links=all_portal_links,
        is_staff=is_staff,
        latest_bulletin=latest_bulletin,
        is_admin=session.get('is_admin', False),
        is_super_admin=is_super,
        my_upcoming=my_upcoming,
        group_discussion=group_discussion,
        card_settings=card_settings,
        portal_cards_config=portal_cards_config,
        hero_theme=hero_theme,
        today_tw=today_tw,
        is_pastor=is_pastor,
        is_group_leader=is_group_leader,
        pending_report=pending_report,
        leader_groups=leader_groups,
        attendance_summary=attendance_summary,
        unread_changelog=unread_changelog,
        is_fulltime_staff=is_fulltime_staff,
    )


@event_bp.route('/manual')
@login_required
def manual():
    """使用手冊"""
    return render_template('manual.html')


@event_bp.route('/product-spec')
def product_spec():
    """產品說明書（公開可讀）"""
    from config import Config
    return render_template('product_spec.html', church_name=Config.CHURCH_NAME)


@event_bp.route('/my-history')
@login_required
def my_history():
    """個人歷史總覽：活動報名 + 門訓學程"""
    uid = session['user_id']

    # 撈所有活動報名記錄
    regs = supabase.table('registrations')\
        .select('*, events(id, title, event_start, location, checkin_enabled)')\
        .eq('user_id', uid)\
        .neq('status', 'cancelled')\
        .order('created_at', desc=True)\
        .execute().data or []

    # 撈完訓認證（主要顯示來源）
    try:
        certifications = supabase.table('course_certifications')\
            .select('*, course_categories(id, name)')\
            .eq('user_id', uid)\
            .order('certified_at', desc=True)\
            .execute().data or []
    except Exception:
        certifications = []

    # 撈進行中的報名（enrolled / absent 狀態，不含已完訓）
    try:
        enrollments = supabase.table('course_enrollments')\
            .select('*, courses(id, title, period, total_sessions)')\
            .eq('user_id', uid)\
            .in_('status', ['enrolled', 'absent'])\
            .order('created_at', desc=True)\
            .execute().data or []
    except Exception:
        enrollments = []

    # 每個進行中學程的出席堂次數
    for e in enrollments:
        course_id = e.get('courses', {}).get('id') if e.get('courses') else None
        if course_id:
            try:
                sessions_result = supabase.table('course_sessions')\
                    .select('id').eq('course_id', course_id).execute().data or []
                session_ids = [s['id'] for s in sessions_result]
                if session_ids:
                    att = supabase.table('session_attendance')\
                        .select('id', count='exact')\
                        .eq('user_id', uid)\
                        .in_('session_id', session_ids)\
                        .execute()
                    e['attended_count'] = att.count or 0
                else:
                    e['attended_count'] = 0
            except Exception:
                e['attended_count'] = 0
        else:
            e['attended_count'] = 0

    course_count = len(certifications) + len(enrollments)

    # 撈我的代禱紀錄
    try:
        my_prayers = supabase.table('prayers').select('*')\
            .eq('user_id', uid)\
            .neq('status', 'archived')\
            .order('created_at', desc=True)\
            .execute().data or []
    except Exception:
        my_prayers = []

    return render_template('my_history.html',
        regs=regs,
        certifications=certifications,
        enrollments=enrollments,
        course_count=course_count,
        my_prayers=my_prayers,
    )


@event_bp.route('/verse')
@login_required
def daily_verse():
    """每日經文祝福卡：每人每天抽一次，抽過即鎖定"""
    uid = session['user_id']
    # 使用台灣時區（UTC+8）避免伺服器用 UTC 造成日期差一天
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()

    # 查今日是否已抽過
    existing = supabase.table('daily_verse_draws')\
        .select('verse_index')\
        .eq('user_id', uid)\
        .eq('drawn_date', today)\
        .execute().data

    # 從 DB 載入有效經文（fallback 到硬編碼陣列）
    try:
        db_verses = supabase.table('daily_verses')\
            .select('text, ref').eq('is_active', True)\
            .order('sort_order').execute().data or []
    except Exception:
        db_verses = []
    verses = db_verses if db_verses else DAILY_VERSES

    if existing:
        verse_index = existing[0]['verse_index']
    else:
        verse_index = random.randint(0, len(verses) - 1)
        try:
            supabase.table('daily_verse_draws').insert({
                'user_id': uid,
                'drawn_date': today,
                'verse_index': verse_index,
            }).execute()
        except Exception:
            pass

    verse = verses[verse_index % len(verses)]
    try:
        raw_custom = supabase.table('verse_custom_themes')\
            .select('name,image_url,symbol,text_mode')\
            .eq('is_active', True).order('sort_order').execute().data or []
    except Exception:
        raw_custom = []
    custom_themes = [{'name': t['name'], 'image_url': t['image_url'],
                      'symbol': t['symbol'], 'text_mode': t['text_mode']} for t in raw_custom]
    theme = _pick_theme(uid, today, custom_themes)
    return render_template('verse.html',
        verse=verse,
        theme=theme,
        today=today,
        user_name=session.get('real_name') or session.get('display_name', ''),
    )


@event_bp.route('/api/verse-data')
@login_required
def api_verse_data():
    """首頁浮框用：回傳今日經文 + 主題（JSON）"""
    from flask import current_app
    uid = session['user_id']
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()

    existing = supabase.table('daily_verse_draws')\
        .select('verse_index').eq('user_id', uid).eq('drawn_date', today)\
        .execute().data

    try:
        db_verses = supabase.table('daily_verses')\
            .select('text, ref').eq('is_active', True)\
            .order('sort_order').execute().data or []
    except Exception:
        db_verses = []
    verses = db_verses if db_verses else DAILY_VERSES

    if existing:
        verse_index = existing[0]['verse_index']
    else:
        verse_index = random.randint(0, len(verses) - 1)
        try:
            supabase.table('daily_verse_draws').insert({
                'user_id': uid, 'drawn_date': today, 'verse_index': verse_index,
            }).execute()
        except Exception:
            pass

    verse = verses[verse_index % len(verses)]
    try:
        raw_custom = supabase.table('verse_custom_themes')\
            .select('name,image_url,symbol,text_mode').eq('is_active', True)\
            .order('sort_order').execute().data or []
    except Exception:
        raw_custom = []
    custom_themes = [{'name': t['name'], 'image_url': t['image_url'],
                      'symbol': t['symbol'], 'text_mode': t['text_mode']} for t in raw_custom]
    theme = _pick_theme(uid, today, custom_themes)

    return jsonify({
        'verse': verse,
        'theme': {
            'gradient': theme.get('gradient', ''),
            'symbol':   theme.get('symbol', '✝'),
            'text_mode': theme.get('text_mode', ''),
            'image_url': theme.get('image_url', ''),
        },
        'today': today,
        'user_name':   session.get('real_name') or session.get('display_name', ''),
        'church_name': current_app.config.get('CHURCH_NAME', ''),
    })


@event_bp.route('/events')
@login_required
def index():
    """活動列表，分為「報名中」和「即將/已結束」"""
    now = datetime.now(timezone.utc).isoformat()

    # 撈所有活動（依開始時間排序）
    result = supabase.table('events')\
        .select('*')\
        .order('event_start', desc=False)\
        .execute()
    events = result.data or []

    if not events:
        return render_template('events/list.html', open_events=[], other_events=[], reg_counts={})

    # 撈每個活動的報名人數（status = registered 或 walk_in）
    event_ids = [e['id'] for e in events]
    reg_counts = {}
    for eid in event_ids:
        count_result = supabase.table('registrations')\
            .select('id', count='exact')\
            .eq('event_id', eid)\
            .in_('status', ['registered', 'walk_in'])\
            .execute()
        reg_counts[eid] = count_result.count or 0

    # 查目前使用者已報名哪些活動
    my_regs_result = supabase.table('registrations')\
        .select('event_id, status')\
        .eq('user_id', session['user_id'])\
        .in_('status', ['registered', 'walk_in'])\
        .execute()
    my_event_ids = {r['event_id'] for r in (my_regs_result.data or [])}

    # 分類：報名開放中 vs 其他（關閉/已過期）
    open_events = []
    other_events = []
    for e in events:
        # 判斷是否已過期（活動結束時間已過）
        is_past = False
        if e.get('event_end') and e['event_end'] < now:
            is_past = True
        elif e.get('event_start') and not e.get('event_end') and e['event_start'] < now:
            # 沒有結束時間但開始時間已過 → 視為當天仍有效，不標為過期
            pass

        e['_reg_count'] = reg_counts.get(e['id'], 0)
        e['_is_past'] = is_past
        e['_is_full'] = bool(e.get('capacity') and e['_reg_count'] >= e['capacity'])
        e['_i_registered'] = e['id'] in my_event_ids

        if is_registration_open(e) and not is_past and not e['_is_full']:
            open_events.append(e)
        else:
            other_events.append(e)

    return render_template('events/list.html',
        open_events=open_events,
        other_events=other_events,
        reg_counts=reg_counts,
    )


@event_bp.route('/event/<event_id>')
def event_detail(event_id):
    """活動詳情頁：顯示活動資訊、報名狀態、報名表單"""
    try:
        # 撈活動資料
        event_result = supabase.table('events').select('*').eq('id', event_id).execute()
        if not event_result.data:
            return '找不到此活動', 404
        event = event_result.data[0]

        # 未登入處理：開放外部報名 → 身分選擇頁；否則 → LINE 登入
        if not session.get('user_id'):
            if event.get('allow_external_reg') and is_registration_open(event):
                fields_result = supabase.table('event_fields')\
                    .select('*').eq('event_id', event_id)\
                    .eq('is_archived', False).order('sort_order').execute()
                return render_template('event_identity.html',
                    event=event,
                    fields=fields_result.data or [],
                    mode='register',
                )
            session['next_url'] = request.url
            from urllib.parse import quote
            next_param = quote(request.url, safe='')
            return redirect(url_for('auth.login_page') + f'?next={next_param}')

        # 撈自訂欄位（只顯示未封存的，讓報名者填寫）
        fields_result = supabase.table('event_fields')\
            .select('*')\
            .eq('event_id', event_id)\
            .eq('is_archived', False)\
            .order('sort_order')\
            .execute()
        fields = fields_result.data or []

        # 計算目前報名人數（狀態為 registered）
        reg_count_result = supabase.table('registrations')\
            .select('id', count='exact')\
            .eq('event_id', event_id)\
            .eq('status', 'registered')\
            .execute()
        reg_count = reg_count_result.count or 0

        # 撈目前使用者所有已報名紀錄（支援重複報名）
        user_regs_result = supabase.table('registrations')\
            .select('*')\
            .eq('event_id', event_id)\
            .eq('user_id', session['user_id'])\
            .eq('status', 'registered')\
            .order('created_at')\
            .execute()
        my_regs = user_regs_result.data or []

        # 候補名單：查詢候補總數與目前使用者的候補順位
        waitlist_count = 0
        my_waitlist_pos = None
        my_waitlist_reg_id = None
        # 候補是否已截止
        from datetime import datetime, timezone as tz
        waitlist_open = event.get('waitlist_enabled', False)
        if waitlist_open and event.get('waitlist_deadline'):
            deadline = datetime.fromisoformat(event['waitlist_deadline'].replace('Z', '+00:00'))
            if datetime.now(tz.utc) > deadline:
                waitlist_open = False
        if event.get('capacity') and event.get('waitlist_enabled'):
            wl_all = supabase.table('registrations')\
                .select('id, user_id')\
                .eq('event_id', event_id)\
                .eq('status', 'waitlisted')\
                .order('created_at')\
                .execute()
            wl_list = wl_all.data or []
            waitlist_count = len(wl_list)
            uid = session['user_id']
            for i, wl in enumerate(wl_list):
                if wl['user_id'] == uid:
                    my_waitlist_pos = i + 1
                    my_waitlist_reg_id = wl['id']
                    break

        # 撈每筆報名的自訂欄位答案 { reg_id: [{label, answer}] }
        my_answers_map = {}
        if my_regs:
            reg_ids = [r['id'] for r in my_regs]
            for reg_id_item in reg_ids:
                answers_result = supabase.table('registration_answers')\
                    .select('*, event_fields(label)')\
                    .eq('registration_id', reg_id_item)\
                    .execute()
                my_answers_map[reg_id_item] = answers_result.data or []

        # 判斷報名是否開放（含時間自動判斷）
        is_full = bool(event.get('capacity') and reg_count >= event['capacity'])
        reg_open = is_registration_open(event)
        now_str = datetime.now(timezone.utc).isoformat()

        # 白名單檢查
        uid = session['user_id']
        is_whitelisted = True  # 預設開放
        if event.get('whitelist_enabled'):
            wl = supabase.table('registration_whitelist')\
                .select('id').eq('ref_type', 'event').eq('ref_id', event_id)\
                .eq('user_id', uid).execute()
            is_whitelisted = bool(wl.data)

        # 撈用戶個人資料（供 quick_reg 顯示）
        profile_result = supabase.table('users')\
            .select('real_name, group_tags')\
            .eq('id', uid).execute()
        user_profile = profile_result.data[0] if profile_result.data else {}

        return render_template('event_detail.html',
            event=event,
            fields=fields,
            reg_count=reg_count,
            my_regs=my_regs,
            my_answers_map=my_answers_map,
            is_full=is_full,
            reg_open=reg_open,
            now_str=now_str,
            user_profile=user_profile,
            is_whitelisted=is_whitelisted,
            waitlist_count=waitlist_count,
            my_waitlist_pos=my_waitlist_pos,
            my_waitlist_reg_id=my_waitlist_reg_id,
            waitlist_open=waitlist_open,
        )
    except Exception as e:
        import traceback
        return f'<pre>活動詳情頁錯誤：\n{traceback.format_exc()}</pre>', 500


@event_bp.route('/event/<event_id>/register', methods=['POST'])
@login_required
def event_register(event_id):
    """報名活動"""
    try:
     return _do_event_register(event_id)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': '系統錯誤，請稍後再試'}), 500

def _do_event_register(event_id):
    # 再次確認活動存在且開放
    event_result = supabase.table('events').select('*').eq('id', event_id).execute()
    if not event_result.data:
        return jsonify({'error': '找不到此活動'}), 404
    event = event_result.data[0]

    if not is_registration_open(event):
        return jsonify({'error': '此活動報名已關閉或不在報名時段內'}), 400

    # 白名單檢查
    if event.get('whitelist_enabled'):
        wl = supabase.table('registration_whitelist')\
            .select('id').eq('ref_type', 'event').eq('ref_id', event_id)\
            .eq('user_id', session['user_id']).execute()
        if not wl.data:
            return jsonify({'error': '你不在此活動的報名名單中，請聯絡管理員'}), 403

    # 檢查人數上限（不論是否允許重複報名都要檢查）
    is_event_full = False
    if event.get('capacity'):
        count_result = supabase.table('registrations')\
            .select('id', count='exact')\
            .eq('event_id', event_id)\
            .eq('status', 'registered')\
            .execute()
        if (count_result.count or 0) >= event['capacity']:
            is_event_full = True

    if is_event_full:
        # 額滿時加入候補（不支援 allow_multiple 活動的候補）
        if not event.get('waitlist_enabled'):
            return jsonify({'error': '報名人數已達上限'}), 400
        if event.get('waitlist_deadline'):
            from datetime import datetime, timezone as tz
            deadline = datetime.fromisoformat(event['waitlist_deadline'].replace('Z', '+00:00'))
            if datetime.now(tz.utc) > deadline:
                return jsonify({'error': '候補名單已截止'}), 400
        if event.get('allow_multiple'):
            return jsonify({'error': '此活動已額滿'}), 400
        existing = supabase.table('registrations')\
            .select('id, status')\
            .eq('event_id', event_id)\
            .eq('user_id', session['user_id'])\
            .execute()
        if existing.data:
            s = existing.data[0]['status']
            if s == 'registered':
                return jsonify({'error': '您已經報名此活動了'}), 400
            if s == 'waitlisted':
                return jsonify({'error': '您已在候補名單中'}), 400
            # 之前取消過，改為候補
            supabase.table('registrations').update({'status': 'waitlisted'}).eq('id', existing.data[0]['id']).execute()
        else:
            supabase.table('registrations').insert({
                'event_id': event_id,
                'user_id': session['user_id'],
                'status': 'waitlisted',
                'checked_in': False,
            }).execute()
        return jsonify({'success': True, 'waitlisted': True})

    if event.get('allow_multiple'):
        # 允許重複報名：直接建立新紀錄
        reg_result = supabase.table('registrations').insert({
            'event_id': event_id,
            'user_id': session['user_id'],
            'status': 'registered',
            'checked_in': False,
        }).execute()
        reg_id = reg_result.data[0]['id']
    else:
        # 不允許重複報名：檢查是否已有紀錄（優先找 registered/waitlisted，其次最新 cancelled）
        existing = supabase.table('registrations')\
            .select('id, status')\
            .eq('event_id', event_id)\
            .eq('user_id', session['user_id'])\
            .order('created_at', desc=True)\
            .execute()

        if existing.data:
            # 優先用 registered / waitlisted 紀錄；沒有才用最新的
            existing_reg = next(
                (r for r in existing.data if r['status'] in ('registered', 'waitlisted')),
                existing.data[0]
            )
            if existing_reg['status'] == 'registered':
                return jsonify({'error': '您已經報名此活動了'}), 400
            if existing_reg['status'] == 'waitlisted':
                return jsonify({'error': '您已在候補名單中，名額開放時將自動升為正式報名'}), 400
            # 若之前取消過，改回 registered
            reg_id = existing_reg['id']
            supabase.table('registrations').update({'status': 'registered'}).eq('id', reg_id).execute()
            # 刪掉舊答案重新寫入
            supabase.table('registration_answers').delete().eq('registration_id', reg_id).execute()
        else:
            # 建立新報名紀錄
            reg_result = supabase.table('registrations').insert({
                'event_id': event_id,
                'user_id': session['user_id'],
                'status': 'registered',
                'checked_in': False,
            }).execute()
            reg_id = reg_result.data[0]['id']

    # 寫入自訂欄位答案
    data = request.get_json() or {}
    answers = data.get('answers', [])  # [{ field_id, answer }]
    for ans in answers:
        if ans.get('field_id') and ans.get('answer', '') != '':
            supabase.table('registration_answers').insert({
                'registration_id': reg_id,
                'field_id': ans['field_id'],
                'answer': str(ans['answer']),
            }).execute()

    # 餐點選擇：計算費用並更新報名記錄
    meal_selections = data.get('meal_selections') or []
    meal_total = 0
    meal_opts_cfg = event.get('meal_options') or {}
    if meal_selections and meal_opts_cfg.get('enabled'):
        price_map = {o['id']: o.get('price', 0)
                     for o in meal_opts_cfg.get('options', []) if o.get('enabled')}
        meal_total = sum(price_map.get(mid, 0) for mid in meal_selections)
    if meal_selections:
        supabase.table('registrations').update({
            'meal_selections': meal_selections,
            'meal_total': meal_total,
        }).eq('id', reg_id).execute()

    # ── 報名成功通知 ──────────────────────────
    ev_date = (event.get('event_start') or '')[:10]
    body_parts = [f'活動日期：{ev_date}' if ev_date else '']
    if event.get('fee'):
        body_parts.append(f'費用：${event["fee"]} 元，請記得繳費')
    create_notification(
        user_id  = session['user_id'],
        title    = f'📋 報名成功 — {event["title"]}',
        body     = '\n'.join(p for p in body_parts if p) or None,
        type     = 'enrollment',
        link     = f'/event/{event_id}',
        ref_type = 'event',
        ref_id   = event_id,
    )

    return jsonify({'success': True})


@event_bp.route('/event/<event_id>/cancel', methods=['POST'])
@login_required
def event_cancel(event_id):
    """取消報名（可傳 reg_id 指定取消哪一筆，用於重複報名活動）"""
    body = request.get_json() or {}
    target_reg_id = body.get('reg_id')

    query = supabase.table('registrations')\
        .select('id, status')\
        .eq('event_id', event_id)\
        .eq('user_id', session['user_id'])

    if target_reg_id:
        query = query.eq('id', target_reg_id)

    result = query.execute()

    if not result.data:
        return jsonify({'error': '找不到報名紀錄'}), 400

    # 找第一筆 registered 的
    target = next((r for r in result.data if r['status'] == 'registered'), None)
    if not target:
        return jsonify({'error': '您尚未報名此活動'}), 400

    supabase.table('registrations').update({'status': 'cancelled'}).eq('id', target['id']).execute()

    # 取消後自動晉升候補名單第一位
    event_result = supabase.table('events').select('capacity').eq('id', event_id).execute()
    if event_result.data and event_result.data[0].get('capacity'):
        first_wl = supabase.table('registrations')\
            .select('id')\
            .eq('event_id', event_id)\
            .eq('status', 'waitlisted')\
            .order('created_at')\
            .limit(1)\
            .execute()
        if first_wl.data:
            supabase.table('registrations').update({'status': 'registered'})\
                .eq('id', first_wl.data[0]['id']).execute()

    return jsonify({'success': True})


@event_bp.route('/event/<event_id>/external-form')
def event_external_form(event_id):
    """外部報名表單頁（無需 LINE 登入）"""
    event_result = supabase.table('events').select('*').eq('id', event_id).execute()
    if not event_result.data:
        return '找不到此活動', 404
    event = event_result.data[0]

    if not event.get('allow_external_reg'):
        return redirect(url_for('auth.login_page'))

    if not is_registration_open(event):
        return render_template('external_register.html', event=event, fields=[], closed=True)

    fields_result = supabase.table('event_fields')\
        .select('*').eq('event_id', event_id)\
        .eq('is_archived', False).order('sort_order').execute()
    return render_template('external_register.html',
        event=event,
        fields=fields_result.data or [],
    )


@event_bp.route('/event/<event_id>/external-register', methods=['POST'])
def event_external_register(event_id):
    """外部人士報名（無需 LINE 登入）"""
    try:
     return _do_external_register(event_id)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': '系統錯誤，請稍後再試'}), 500

def _do_external_register(event_id):
    event_result = supabase.table('events').select('*').eq('id', event_id).execute()
    if not event_result.data:
        return jsonify({'error': '找不到此活動'}), 404
    event = event_result.data[0]

    if not event.get('allow_external_reg'):
        return jsonify({'error': '此活動不開放外部報名'}), 403

    if not is_registration_open(event):
        return jsonify({'error': '此活動報名已關閉'}), 400

    data = request.get_json() or {}
    guest_name = (data.get('guest_name') or '').strip()
    if not guest_name:
        return jsonify({'error': '請填寫姓名'}), 400

    # 檢查人數上限，決定狀態
    reg_status = 'registered'
    if event.get('capacity'):
        count_result = supabase.table('registrations')\
            .select('id', count='exact')\
            .eq('event_id', event_id).eq('status', 'registered').execute()
        if (count_result.count or 0) >= event['capacity']:
            if not event.get('waitlist_enabled'):
                return jsonify({'error': '報名人數已達上限'}), 400
            if event.get('waitlist_deadline'):
                from datetime import datetime, timezone as tz
                deadline = datetime.fromisoformat(
                    event['waitlist_deadline'].replace('Z', '+00:00'))
                if datetime.now(tz.utc) > deadline:
                    return jsonify({'error': '候補名單已截止'}), 400
            reg_status = 'waitlisted'

    # 建立外部報名紀錄
    reg_result = supabase.table('registrations').insert({
        'event_id': event_id,
        'user_id': None,
        'guest_name': guest_name,
        'status': reg_status,
        'checked_in': False,
        'source': 'external',
    }).execute()
    reg_id = reg_result.data[0]['id']

    # 寫入自訂欄位答案
    for ans in (data.get('answers') or []):
        if ans.get('field_id') and ans.get('answer', '') != '':
            supabase.table('registration_answers').insert({
                'registration_id': reg_id,
                'field_id': ans['field_id'],
                'answer': str(ans['answer']),
            }).execute()

    return jsonify({'success': True, 'waitlisted': reg_status == 'waitlisted'})


@event_bp.route('/event/<event_id>/cancel_waitlist', methods=['POST'])
@login_required
def event_cancel_waitlist(event_id):
    """退出候補名單"""
    result = supabase.table('registrations')\
        .select('id')\
        .eq('event_id', event_id)\
        .eq('user_id', session['user_id'])\
        .eq('status', 'waitlisted')\
        .execute()
    if not result.data:
        return jsonify({'error': '您不在此活動的候補名單中'}), 400
    supabase.table('registrations').update({'status': 'cancelled'})\
        .eq('id', result.data[0]['id']).execute()
    return jsonify({'success': True})
