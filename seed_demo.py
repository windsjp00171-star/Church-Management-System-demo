#!/usr/bin/env python3
"""
DEMO 資料種子腳本 - 整合型教會行政系統
用法：
  python seed_demo.py          # 插入展示資料
  python seed_demo.py --clear  # 清除所有展示資料
"""
import sys, json, uuid, datetime, os, secrets
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase import create_client

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
if not SUPABASE_URL or not SUPABASE_KEY:
    print('❌  請先設定 SUPABASE_URL 和 SUPABASE_KEY 環境變數')
    sys.exit(1)

db = create_client(SUPABASE_URL, SUPABASE_KEY)
SEED_FILE = Path(__file__).parent / '.seed_ids.json'

# ── 工具函數 ──────────────────────────────────────────────────
def g():
    return str(uuid.uuid4())

def d(n=0):
    return (datetime.date.today() + datetime.timedelta(days=n)).isoformat()

def dt_str(n=0, h=10, m=0):
    base = datetime.datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    base += datetime.timedelta(days=n)
    return base.isoformat()

def load_ids():
    return json.loads(SEED_FILE.read_text()) if SEED_FILE.exists() else {}

def save_ids(ids):
    SEED_FILE.write_text(json.dumps(ids, indent=2, ensure_ascii=False))

def ok(label):
    print(f'  ✅  {label}')

def warn(label, e):
    print(f'  ⚠️   {label}: {e}')

def safe_insert(table, rows):
    try:
        if isinstance(rows, dict):
            rows = [rows]
        db.table(table).insert(rows).execute()
    except Exception as e:
        warn(f'insert {table}', e)

def safe_upsert(table, rows, on_conflict):
    try:
        if isinstance(rows, dict):
            rows = [rows]
        db.table(table).upsert(rows, on_conflict=on_conflict).execute()
    except Exception as e:
        warn(f'upsert {table}', e)

# ── 種子資料 ──────────────────────────────────────────────────
def seed():
    print('\n🌱  開始插入 DEMO 展示資料...\n')
    ids = {}
    today = datetime.date.today()

    # ────────────────────────────────────────────────────────
    # 1. 使用者
    # ────────────────────────────────────────────────────────
    print('👥  建立使用者...')
    uids = {k: g() for k in ['pastor','admin1','admin2','u1','u2','u3','u4','u5','u6','u7','u8']}
    lids = {k: f'Udemo{i:08d}' for i, k in enumerate(uids, 1)}

    def avatar(name, bg):
        return f'https://ui-avatars.com/api/?name={name}&background={bg}&color=fff&size=128'

    users = [
        {'id': uids['pastor'], 'line_user_id': lids['pastor'],
         'display_name': '林建志牧師', 'real_name': '林建志',
         'member_type': 'member', 'is_admin': True, 'is_super_admin': True, 'is_pastor': True,
         'group_tags': ['橄欖枝小組'], 'picture_url': avatar('林建志','7b1fa2')},

        {'id': uids['admin1'], 'line_user_id': lids['admin1'],
         'display_name': '陳美玲同工', 'real_name': '陳美玲',
         'member_type': 'member', 'is_admin': True,
         'group_tags': ['橄欖枝小組'], 'picture_url': avatar('陳美玲','1976d2')},

        {'id': uids['admin2'], 'line_user_id': lids['admin2'],
         'display_name': '張大偉同工', 'real_name': '張大偉',
         'member_type': 'member', 'is_admin': True,
         'group_tags': ['葡萄枝小組'], 'picture_url': avatar('張大偉','388e3c')},

        {'id': uids['u1'], 'line_user_id': lids['u1'],
         'display_name': '李靜宜', 'real_name': '李靜宜',
         'member_type': 'member', 'group_tags': ['橄欖枝小組'],
         'picture_url': avatar('李靜宜','e64a19')},

        {'id': uids['u2'], 'line_user_id': lids['u2'],
         'display_name': '王俊豪', 'real_name': '王俊豪',
         'member_type': 'member', 'group_tags': ['橄欖枝小組'],
         'picture_url': avatar('王俊豪','0097a7')},

        {'id': uids['u3'], 'line_user_id': lids['u3'],
         'display_name': '吳雅婷', 'real_name': '吳雅婷',
         'member_type': 'member', 'group_tags': ['葡萄枝小組'],
         'picture_url': avatar('吳雅婷','f57c00')},

        {'id': uids['u4'], 'line_user_id': lids['u4'],
         'display_name': '黃信義', 'real_name': '黃信義',
         'member_type': 'member', 'group_tags': ['葡萄枝小組'],
         'picture_url': avatar('黃信義','5d4037')},

        {'id': uids['u5'], 'line_user_id': lids['u5'],
         'display_name': '劉思穎', 'real_name': '劉思穎',
         'member_type': 'member', 'group_tags': ['生命活水小組'],
         'picture_url': avatar('劉思穎','455a64')},

        {'id': uids['u6'], 'line_user_id': lids['u6'],
         'display_name': '蔡明宏', 'real_name': '蔡明宏',
         'member_type': 'member', 'group_tags': ['生命活水小組'],
         'picture_url': avatar('蔡明宏','7b1fa2')},

        {'id': uids['u7'], 'line_user_id': lids['u7'],
         'display_name': '許淑芬', 'real_name': '許淑芬',
         'member_type': 'member', 'group_tags': ['以馬內利小組'],
         'picture_url': avatar('許淑芬','c62828')},

        {'id': uids['u8'], 'line_user_id': lids['u8'],
         'display_name': '鄭家豪', 'real_name': '鄭家豪',
         'member_type': 'member', 'group_tags': ['以馬內利小組'],
         'picture_url': avatar('鄭家豪','00796b')},
    ]
    safe_upsert('users', users, 'id')
    ids['uids'] = uids
    ids['lids'] = lids
    ok(f'{len(users)} 位使用者')

    # ────────────────────────────────────────────────────────
    # 2. 小組標籤（groups 表，用於禱讀本系統）
    # ────────────────────────────────────────────────────────
    print('🏷️   建立小組標籤...')
    gtids = {n: g() for n in ['橄欖枝小組','葡萄枝小組','生命活水小組','以馬內利小組']}
    group_tags = [
        {'id': gtids['橄欖枝小組'],   'name': '橄欖枝小組',   'is_primary': True, 'sort_order': 1},
        {'id': gtids['葡萄枝小組'],   'name': '葡萄枝小組',   'is_primary': True, 'sort_order': 2},
        {'id': gtids['生命活水小組'], 'name': '生命活水小組', 'is_primary': True, 'sort_order': 3},
        {'id': gtids['以馬內利小組'], 'name': '以馬內利小組', 'is_primary': True, 'sort_order': 4},
    ]
    safe_upsert('groups', group_tags, 'id')
    ids['gtids'] = gtids
    ok(f'{len(group_tags)} 個小組標籤')

    # ────────────────────────────────────────────────────────
    # 3. 活動報名（events + event_fields + registrations）
    # ────────────────────────────────────────────────────────
    print('📋  建立活動...')
    eids = {n: g() for n in ['youth','marriage','parent']}
    events_data = [
        {
            'id': eids['youth'],
            'title': '2026 暑期青年特會',
            'description': '今年主題：「向前行——在不確定的時代，穩固你的腳步」。三天兩夜，在山上一起敬拜、分享、彼此建立。名額有限，盡早報名！',
            'event_start': dt_str(14, 9, 0),
            'event_end':   dt_str(16, 17, 0),
            'location': '台灣基督長老教會烏來教育中心',
            'capacity': 80, 'fee': 2800, 'is_open': True, 'reminder_days': 7,
            'checkin_enabled': True,
            'checkin_token': secrets.token_urlsafe(16),
            'checkin_mode': 'registered_only',
            'allow_open_checkin': True,
        },
        {
            'id': eids['marriage'],
            'title': '婚姻輔導工作坊',
            'description': '邀請三對恩愛夫妻分享婚姻中的真實功課。不論結婚幾年，都值得來聽聽。免費入場，歡迎帶另一半一起來！',
            'event_start': dt_str(7, 14, 0),
            'event_end':   dt_str(7, 17, 0),
            'location': '教會多功能教室',
            'capacity': 40, 'fee': 0, 'is_open': True, 'reminder_days': 3,
            'checkin_enabled': True,
            'checkin_token': secrets.token_urlsafe(16),
            'checkin_mode': 'open',
            'allow_open_checkin': True,
        },
        {
            'id': eids['parent'],
            'title': '親子關係成長營',
            'description': '讓孩子說的話你真的有聽進去嗎？由專業基督徒輔導師帶領，幫助父母了解孩子的心，重建溫暖連結。',
            'event_start': dt_str(21, 9, 0),
            'event_end':   dt_str(21, 12, 0),
            'location': '教會兒童教室',
            'capacity': 30, 'fee': 500, 'is_open': True, 'reminder_days': 3,
            'checkin_enabled': True,
            'checkin_token': secrets.token_urlsafe(16),
            'checkin_mode': 'registered_only',
            'allow_open_checkin': False,
        },
    ]
    safe_insert('events', events_data)
    ids['eids'] = eids

    fids = {n: g() for n in ['f1','f2','f3','f4','f5','f6']}
    event_fields = [
        {'id': fids['f1'], 'event_id': eids['youth'],    'label': '真實姓名',     'field_type': 'text',  'is_required': True,  'sort_order': 1},
        {'id': fids['f2'], 'event_id': eids['youth'],    'label': '衣服尺寸',     'field_type': 'radio', 'is_required': True,  'sort_order': 2},
        {'id': fids['f3'], 'event_id': eids['marriage'], 'label': '您的姓名',     'field_type': 'text',  'is_required': True,  'sort_order': 1},
        {'id': fids['f4'], 'event_id': eids['marriage'], 'label': '是否攜伴參加', 'field_type': 'radio', 'is_required': True,  'sort_order': 2},
        {'id': fids['f5'], 'event_id': eids['parent'],   'label': '家長姓名',     'field_type': 'text',  'is_required': True,  'sort_order': 1},
        {'id': fids['f6'], 'event_id': eids['parent'],   'label': '聯絡電話',     'field_type': 'text',  'is_required': True,  'sort_order': 2},
    ]
    safe_insert('event_fields', event_fields)
    ids['fids'] = fids

    rids = {n: g() for n in ['r1','r2','r3','r4','r5','r6','r7','r8']}
    registrations = [
        {'id': rids['r1'], 'event_id': eids['youth'],    'user_id': uids['u1'],     'status': 'registered', 'payment_status': 'paid',   'checked_in': True},
        {'id': rids['r2'], 'event_id': eids['youth'],    'user_id': uids['u2'],     'status': 'registered', 'payment_status': 'paid',   'checked_in': False},
        {'id': rids['r3'], 'event_id': eids['youth'],    'user_id': uids['u3'],     'status': 'registered', 'payment_status': 'unpaid', 'checked_in': False},
        {'id': rids['r4'], 'event_id': eids['youth'],    'user_id': uids['u4'],     'status': 'registered', 'payment_status': 'unpaid', 'checked_in': False},
        {'id': rids['r5'], 'event_id': eids['marriage'], 'user_id': uids['admin1'], 'status': 'registered', 'payment_status': 'waived', 'checked_in': False},
        {'id': rids['r6'], 'event_id': eids['marriage'], 'user_id': uids['u5'],     'status': 'registered', 'payment_status': 'waived', 'checked_in': False},
        {'id': rids['r7'], 'event_id': eids['parent'],   'user_id': uids['u6'],     'status': 'registered', 'payment_status': 'unpaid', 'checked_in': False},
        {'id': rids['r8'], 'event_id': eids['parent'],   'user_id': uids['u7'],     'status': 'registered', 'payment_status': 'paid',   'checked_in': False},
    ]
    safe_insert('registrations', registrations)
    ids['rids'] = rids
    ok(f'{len(events_data)} 個活動、{len(registrations)} 筆報名')

    # ────────────────────────────────────────────────────────
    # 4. 教會行事曆（church_events）
    # ────────────────────────────────────────────────────────
    print('📅  建立教會行事曆...')
    ceids = {n: g() for n in ['retreat','christmas','thanksgiving','prayer_week','baptism']}
    church_events = [
        {
            'id': ceids['prayer_week'],
            'title': '教會禱告週',
            'event_date': d(10), 'end_date': d(17),
            'description': '七天集中禱告，每晚 7:30 在教會大廳，一起為教會、城市、國家守望禱告。',
            'color': '#1565c0', 'remind_days': 3, 'created_by': uids['pastor'],
        },
        {
            'id': ceids['baptism'],
            'title': '受洗典禮',
            'event_date': d(30),
            'description': '這次共有 5 位弟兄姊妹將要接受洗禮，歡迎全體會友出席見證新生命！',
            'color': '#00695c', 'remind_days': 7, 'created_by': uids['pastor'],
        },
        {
            'id': ceids['retreat'],
            'title': '2026 秋季退修會',
            'event_date': d(55), 'end_date': d(57),
            'description': '全教會一起停下腳步，在神面前安靜、更新。今年地點：花蓮奇萊山莊。',
            'color': '#7b1fa2', 'remind_days': 14, 'created_by': uids['pastor'],
        },
        {
            'id': ceids['thanksgiving'],
            'title': '感恩節特別崇拜',
            'event_date': d(150),
            'description': '以感恩的心來到神面前，分享這一年來的見證與恩典。',
            'color': '#e65100', 'remind_days': 7, 'created_by': uids['pastor'],
        },
        {
            'id': ceids['christmas'],
            'title': '聖誕感恩晚會',
            'event_date': d(200),
            'description': '每年最美麗的夜晚，一起唱詩、讚美、見證神的恩典。歡迎邀請未信朋友！',
            'color': '#c62828', 'remind_days': 7, 'created_by': uids['pastor'],
        },
    ]
    safe_insert('church_events', church_events)
    ids['ceids'] = ceids
    ok(f'{len(church_events)} 個教會行程')

    # ────────────────────────────────────────────────────────
    # 5. 門訓課程（courses + sessions + enrollments + attendance）
    # ────────────────────────────────────────────────────────
    print('📚  建立門訓課程...')
    cat_ids = {'new_life': g(), 'disciple': g()}
    safe_insert('course_categories', [
        {'id': cat_ids['new_life'], 'name': '新生命培育'},
        {'id': cat_ids['disciple'], 'name': '門徒訓練'},
    ])
    ids['cat_ids'] = cat_ids

    cids = {'new_life': g(), 'disciple': g()}
    safe_insert('courses', [
        {
            'id': cids['new_life'],
            'title': '新生命課程',
            'description': '專為初信者設計，幫助你建立信仰基礎、認識教會、開始屬靈操練。共六堂，每週日下午。',
            'instructor_id': uids['pastor'],
            'category_id': cat_ids['new_life'],
            'is_open': True, 'has_material': True, 'material_fee': 200, 'capacity': 20, 'reminder_days': 3,
        },
        {
            'id': cids['disciple'],
            'title': '門徒訓練班',
            'description': '針對想要更深委身的弟兄姊妹，透過聖經研讀、禱告操練、服事學習，成為能帶領他人的門徒。共十堂。',
            'instructor_id': uids['admin1'],
            'category_id': cat_ids['disciple'],
            'is_open': True, 'has_material': False, 'material_fee': 0, 'capacity': 15, 'reminder_days': 3,
            'prerequisite_category_id': cat_ids['new_life'],
        },
    ])
    ids['cids'] = cids

    topics_nl   = ['認識神', '認識聖經', '禱告的力量', '教會是什麼', '聖靈的工作', '如何服事']
    topics_disc = ['十字架的意義', '禱告的生活', '聖經如何閱讀', '如何帶領查經',
                   '門徒的紀律', '分享信仰', '服事的心態', '教會的異象', '家庭與信仰', '個人呼召']
    sess_nl   = [g() for _ in topics_nl]
    sess_disc = [g() for _ in topics_disc]

    sessions = []
    for i, sid in enumerate(sess_nl):
        sessions.append({'id': sid, 'course_id': cids['new_life'],
                         'session_number': i + 1,
                         'title': f'第 {i+1} 堂',
                         'scheduled_at': dt_str(7 * i - 35, 14, 0),
                         'location': '教會多功能教室',
                         'checkin_token': secrets.token_urlsafe(12)})
    for i, sid in enumerate(sess_disc):
        sessions.append({'id': sid, 'course_id': cids['disciple'],
                         'session_number': i + 1,
                         'title': f'第 {i+1} 堂',
                         'scheduled_at': dt_str(7 * i - 28, 19, 0),
                         'location': '教會小教室',
                         'checkin_token': secrets.token_urlsafe(12)})
    safe_insert('course_sessions', sessions)
    ids['sess_nl'] = sess_nl
    ids['sess_disc'] = sess_disc

    enroll_ids = {n: g() for n in ['e1','e2','e3','e4','e5','e6']}
    safe_insert('course_enrollments', [
        {'id': enroll_ids['e1'], 'user_id': uids['u1'], 'course_id': cids['new_life'],  'status': 'enrolled', 'payment_status': 'paid'},
        {'id': enroll_ids['e2'], 'user_id': uids['u2'], 'course_id': cids['new_life'],  'status': 'enrolled', 'payment_status': 'paid'},
        {'id': enroll_ids['e3'], 'user_id': uids['u3'], 'course_id': cids['new_life'],  'status': 'enrolled', 'payment_status': 'unpaid'},
        {'id': enroll_ids['e4'], 'user_id': uids['u4'], 'course_id': cids['new_life'],  'status': 'enrolled', 'payment_status': 'unpaid'},
        {'id': enroll_ids['e5'], 'user_id': uids['u5'], 'course_id': cids['disciple'],  'status': 'enrolled', 'payment_status': 'waived'},
        {'id': enroll_ids['e6'], 'user_id': uids['u6'], 'course_id': cids['disciple'],  'status': 'enrolled', 'payment_status': 'waived'},
    ])
    ids['enroll_ids'] = enroll_ids

    # 前4堂有出席記錄
    att_ids = []
    for sid in sess_nl[:4]:
        for uid in [uids['u1'], uids['u2'], uids['u3']]:
            aid = g()
            att_ids.append(aid)
            safe_insert('session_attendance', {'id': aid, 'session_id': sid, 'user_id': uid, 'status': 'present'})
    ids['att_ids'] = att_ids
    ok(f'2 門課程、{len(sessions)} 堂次、{len(enroll_ids)} 筆選課、{len(att_ids)} 筆出席')

    # ────────────────────────────────────────────────────────
    # 6. 代禱牧田（prayers + reactions + comments）
    # ────────────────────────────────────────────────────────
    print('🙏  建立代禱牧田...')
    pids = {n: g() for n in ['p1','p2','p3','p4','p5','p6','p7']}
    safe_insert('prayers', [
        {'id': pids['p1'], 'user_id': uids['u1'], 'title': '為媽媽的身體禱告',
         'content': '媽媽最近身體不太好，需要做進一步檢查，請大家為她代禱，求神賜下平安和醫治。',
         'category': 'health', 'is_anonymous': False, 'status': 'active'},

        {'id': pids['p2'], 'user_id': uids['u2'], 'title': '工作轉換中，需要智慧',
         'content': '正在考慮換工作，有幾個機會在評估，請為我禱告，求神給我清楚的引導，知道哪條路是祂的心意。',
         'category': 'work', 'is_anonymous': False, 'status': 'active'},

        {'id': pids['p3'], 'user_id': uids['u3'], 'title': '為婚姻關係禱告',
         'content': '最近夫妻間有些摩擦，希望神幫助我們重新找到彼此，學習更好的溝通方式。',
         'category': 'family', 'is_anonymous': True, 'status': 'active'},

        {'id': pids['p4'], 'user_id': uids['u4'], 'title': '為台灣的平安禱告',
         'content': '在這動盪的時代，為台灣禱告，求神保守這塊土地，賜下合一與智慧給領袖們。',
         'category': 'other', 'is_anonymous': False, 'status': 'active'},

        {'id': pids['p5'], 'user_id': uids['u5'], 'title': '感謝神！工作禱告蒙應允了 🎉',
         'content': '三個月前在這裡請大家代禱的工作，今天正式錄取了！神的時間最完美，感謝大家的代禱！',
         'category': 'work', 'is_anonymous': False, 'status': 'answered'},

        {'id': pids['p6'], 'user_id': uids['u6'], 'title': '為兒子的信仰禱告',
         'content': '兒子大學後就很少來教會了，請為他代禱，求神繼續在他心裡動工，讓他回轉歸向神。',
         'category': 'family', 'is_anonymous': False, 'status': 'active'},

        {'id': pids['p7'], 'user_id': uids['u7'], 'title': '為靈命成長禱告',
         'content': '感覺最近靈命有些低潮，很難靜下來讀聖經，請為我代禱，求神重新點燃我對祂的渴慕。',
         'category': 'spiritual', 'is_anonymous': False, 'status': 'active'},
    ])
    ids['pids'] = pids

    react_ids = []
    react_pairs = [
        (pids['p1'], uids['u2']), (pids['p1'], uids['u3']), (pids['p1'], uids['admin1']), (pids['p1'], uids['pastor']),
        (pids['p2'], uids['u1']), (pids['p2'], uids['u4']),
        (pids['p3'], uids['pastor']), (pids['p3'], uids['admin1']),
        (pids['p4'], uids['u1']), (pids['p4'], uids['u2']), (pids['p4'], uids['u3']),
        (pids['p5'], uids['u1']), (pids['p5'], uids['pastor']), (pids['p5'], uids['admin1']),
        (pids['p6'], uids['pastor']), (pids['p6'], uids['admin1']), (pids['p6'], uids['u2']),
        (pids['p7'], uids['u5']), (pids['p7'], uids['pastor']),
    ]
    for pid, uid in react_pairs:
        rid = g()
        react_ids.append(rid)
        safe_insert('prayer_reactions', {'id': rid, 'prayer_id': pid, 'user_id': uid, 'emoji': '🙏'})
    ids['react_ids'] = react_ids

    cmt_ids = {n: g() for n in ['c1','c2','c3','c4','c5']}
    safe_insert('prayer_comments', [
        {'id': cmt_ids['c1'], 'prayer_id': pids['p1'], 'user_id': uids['admin1'], 'content': '我們全家都在為阿姨禱告，願神的手按在她身上！'},
        {'id': cmt_ids['c2'], 'prayer_id': pids['p2'], 'user_id': uids['pastor'],  'content': '已在禱告，相信神必指引你，靜下來聽祂說話。'},
        {'id': cmt_ids['c3'], 'prayer_id': pids['p5'], 'user_id': uids['u2'],     'content': '感謝神！！！這真的太棒了，神是信實的！🙌'},
        {'id': cmt_ids['c4'], 'prayer_id': pids['p6'], 'user_id': uids['pastor'],  'content': '我們一起持續守望，神愛你的孩子比你更深。'},
        {'id': cmt_ids['c5'], 'prayer_id': pids['p7'], 'user_id': uids['admin1'], 'content': '低潮期也是神工作的時候，繼續來聚會，讓弟兄姊妹陪你。'},
    ])
    ids['cmt_ids'] = cmt_ids
    ok(f'{len(pids)} 條代禱、{len(react_ids)} 個禱告回應、{len(cmt_ids)} 條留言')

    # ────────────────────────────────────────────────────────
    # 7. 小組週報（cell_groups + members + leaders + reports）
    # ────────────────────────────────────────────────────────
    print('🏘️   建立小組週報...')
    cgids = {n: g() for n in ['olive','grape','water','immanuel']}
    safe_insert('cell_groups', [
        {'id': cgids['olive'],    'name': '橄欖枝小組',   'weekly_gather_day': '三', 'is_active': True},
        {'id': cgids['grape'],    'name': '葡萄枝小組',   'weekly_gather_day': '五', 'is_active': True},
        {'id': cgids['water'],    'name': '生命活水小組', 'weekly_gather_day': '四', 'is_active': True},
        {'id': cgids['immanuel'], 'name': '以馬內利小組', 'weekly_gather_day': '二', 'is_active': True},
    ])
    ids['cgids'] = cgids

    safe_insert('cell_group_leaders', [
        {'user_id': uids['admin1'], 'group_id': cgids['olive']},
        {'user_id': uids['admin2'], 'group_id': cgids['grape']},
        {'user_id': uids['u5'],     'group_id': cgids['water']},
        {'user_id': uids['u7'],     'group_id': cgids['immanuel']},
    ])

    cmids = {f'm{i}': g() for i in range(1, 13)}
    safe_insert('cell_members', [
        {'id': cmids['m1'],  'group_id': cgids['olive'],    'user_id': uids['u1'],  'name': '李靜宜', 'is_active': True, 'is_confirmed': True},
        {'id': cmids['m2'],  'group_id': cgids['olive'],    'user_id': uids['u2'],  'name': '王俊豪', 'is_active': True, 'is_confirmed': True},
        {'id': cmids['m3'],  'group_id': cgids['olive'],                             'name': '林小明', 'is_active': True, 'is_confirmed': True},
        {'id': cmids['m4'],  'group_id': cgids['grape'],    'user_id': uids['u3'],  'name': '吳雅婷', 'is_active': True, 'is_confirmed': True},
        {'id': cmids['m5'],  'group_id': cgids['grape'],    'user_id': uids['u4'],  'name': '黃信義', 'is_active': True, 'is_confirmed': True},
        {'id': cmids['m6'],  'group_id': cgids['grape'],                             'name': '陳建國', 'is_active': True, 'is_confirmed': True},
        {'id': cmids['m7'],  'group_id': cgids['water'],    'user_id': uids['u5'],  'name': '劉思穎', 'is_active': True, 'is_confirmed': True},
        {'id': cmids['m8'],  'group_id': cgids['water'],    'user_id': uids['u6'],  'name': '蔡明宏', 'is_active': True, 'is_confirmed': True},
        {'id': cmids['m9'],  'group_id': cgids['water'],                             'name': '方雅文', 'is_active': True, 'is_confirmed': True},
        {'id': cmids['m10'], 'group_id': cgids['immanuel'], 'user_id': uids['u7'],  'name': '許淑芬', 'is_active': True, 'is_confirmed': True},
        {'id': cmids['m11'], 'group_id': cgids['immanuel'], 'user_id': uids['u8'],  'name': '鄭家豪', 'is_active': True, 'is_confirmed': True},
        {'id': cmids['m12'], 'group_id': cgids['immanuel'],                          'name': '洪雅茹', 'is_active': True, 'is_confirmed': True},
    ])
    ids['cmids'] = cmids

    # 過去3週的週報（每組各3筆）
    week_dates = [(today - datetime.timedelta(weeks=i, days=today.weekday())).isoformat() for i in range(1, 4)]
    crids = {f'cr{i}': g() for i in range(1, 13)}
    cr_list = []
    i = 1
    for wdate in week_dates:
        for gid in [cgids['olive'], cgids['grape'], cgids['water'], cgids['immanuel']]:
            cr_list.append({'id': crids[f'cr{i}'], 'group_id': gid, 'week_date': wdate, 'is_complete': True, 'no_meeting': False})
            i += 1
    safe_insert('cell_reports', cr_list)
    ids['crids'] = crids

    # 各型態出席人數
    adult_nums    = [148, 155, 152, 143, 162, 158, 145, 151, 148, 153, 160, 157]
    children_nums = [38,  45,  41,  35,  48,  42,  39,  36,  40,  44,  46,  43]
    prayer_nums   = [28,  33,  31,  25,  35,  29,  27,  30,  26,  32,  34,  28]
    morning_nums  = [12,  16,  15,  11,  18,  14,  13,  15,  12,  17,  16,  14]

    sr_ids  = [g() for _ in range(12)]
    chr_ids = [g() for _ in range(12)]
    pr_ids  = [g() for _ in range(12)]
    mr_ids  = [g() for _ in range(12)]

    safe_insert('sunday_reports',          [{'id': sr_ids[i],  'report_id': crids[f'cr{i+1}'], 'attendance_count': adult_nums[i]}    for i in range(12)])
    safe_insert('children_sunday_reports', [{'id': chr_ids[i], 'report_id': crids[f'cr{i+1}'], 'attendance_count': children_nums[i]} for i in range(12)])
    safe_insert('prayer_reports',          [{'id': pr_ids[i],  'report_id': crids[f'cr{i+1}'], 'attendance_count': prayer_nums[i]}   for i in range(12)])
    safe_insert('morning_prayer_reports',  [{'id': mr_ids[i],  'report_id': crids[f'cr{i+1}'], 'attendance_count': morning_nums[i]}  for i in range(12)])

    ids.update({'sr_ids': sr_ids, 'chr_ids': chr_ids, 'pr_ids': pr_ids, 'mr_ids': mr_ids})
    ok(f'4 個小組、{len(cr_list)} 筆週報（成人主日 {adult_nums[0]} 人、兒童 {children_nums[0]} 人）')

    # ────────────────────────────────────────────────────────
    # 8. 天父日記（diary_plan + diary_entries + share_grants）
    # ────────────────────────────────────────────────────────
    print('📖  建立天父日記...')
    bible_plan = [
        ('創世記','1:1-31'), ('創世記','2:1-25'), ('創世記','3:1-24'), ('創世記','4:1-26'),
        ('創世記','5:1-32'), ('創世記','6:1-22'), ('創世記','7:1-24'), ('創世記','8:1-22'),
        ('創世記','9:1-29'), ('創世記','10:1-32'), ('創世記','11:1-32'), ('創世記','12:1-20'),
        ('創世記','13:1-18'), ('創世記','14:1-24'), ('創世記','15:1-21'), ('創世記','16:1-16'),
        ('創世記','17:1-27'), ('創世記','18:1-33'), ('創世記','19:1-38'), ('創世記','20:1-18'),
        ('創世記','21:1-34'), ('創世記','22:1-24'), ('創世記','23:1-20'), ('創世記','24:1-67'),
        ('創世記','25:1-34'), ('創世記','26:1-35'), ('創世記','27:1-46'), ('創世記','28:1-22'),
        ('創世記','29:1-35'), ('創世記','30:1-43'), ('創世記','31:1-55'), ('創世記','32:1-32'),
        ('出埃及記','1:1-22'), ('出埃及記','2:1-25'), ('出埃及記','3:1-22'), ('出埃及記','4:1-31'),
        ('出埃及記','5:1-23'), ('出埃及記','6:1-30'), ('出埃及記','7:1-25'), ('出埃及記','8:1-32'),
        ('出埃及記','9:1-35'), ('出埃及記','10:1-29'), ('出埃及記','11:1-10'), ('出埃及記','12:1-51'),
        ('出埃及記','13:1-22'), ('出埃及記','14:1-31'), ('出埃及記','15:1-27'), ('出埃及記','16:1-36'),
        ('詩篇','1:1-6'), ('詩篇','23:1-6'), ('詩篇','46:1-11'), ('詩篇','91:1-16'),
        ('詩篇','103:1-22'), ('詩篇','121:1-8'), ('詩篇','139:1-24'), ('詩篇','145:1-21'),
        ('約翰福音','1:1-51'), ('約翰福音','3:1-36'), ('約翰福音','10:1-42'), ('約翰福音','15:1-27'),
    ]

    plan_rows = []
    plan_dates = []
    for i in range(60):
        date_str = (today - datetime.timedelta(days=29) + datetime.timedelta(days=i)).isoformat()
        book, verse_range = bible_plan[i % len(bible_plan)]
        plan_rows.append({'date': date_str, 'book': book, 'range': verse_range})
        plan_dates.append(date_str)
    safe_upsert('diary_plan', plan_rows, 'date')
    ids['diary_plan_dates'] = plan_dates

    sample_entries = [
        '今天讀到神創造天地的故事，讓我想起自己是神手所造的。最近壓力很大，但這段經文提醒我，神在混沌中說「要有光」就有了光——祂對我生命的黑暗也能這樣說話。我要把這個職場的困境交給祂。',
        '亞伯拉罕願意獻以撒，這段讀起來很沉重。我問自己：我有沒有什麼「以撒」是我捨不得交出去的？想了很久，我覺得是我對孩子的控制慾。願神幫助我學習放手，讓孩子走在祂為他設計的路上。',
        '約瑟被哥哥們出賣，落入埃及——但整個故事的結尾是「神的美意」。我最近也有一件事感覺很不公平，但今天的靈修讓我看見，從人的眼光看是傷害，從神的眼光看可能是轉折的起點。要信任祂的時間。',
        '摩西拒絕神的呼召，說自己口齒不清。神沒有收回呼召，只是說「我會與你同在」。我常常覺得自己不夠好、不配做這件事。但神看的不是我的能力，而是祂的同在。這個提醒今天很需要。',
        '詩篇23篇「祂使我躺臥在青草地上」——牧羊人帶羊走的路，有時是安靜的水邊，有時是幽谷。今天感覺在幽谷裡，但詩人說「我不怕遭害」。我選擇相信神的杖和竿在那裡保護我。',
        '「你往哪裡去，我也往那裡去」——路得對拿俄米的話。這種忠誠讓我感動。我想到自己對教會、對家人的委身，有沒有像路得這樣，是選擇而不只是習慣？要重新思考我的承諾是什麼。',
    ]

    diary_entry_keys = []

    # 牧師有25篇（展示星空效果）
    pastor_entries = []
    for i in range(25):
        date_str = (today - datetime.timedelta(days=i)).isoformat()
        content = sample_entries[i % len(sample_entries)]
        diary_entry_keys.append([lids['pastor'], date_str])
        pastor_entries.append({'line_user_id': lids['pastor'], 'entry_date': date_str, 'content': content, 'locked': True})
    safe_upsert('diary_entries', pastor_entries, 'line_user_id,entry_date')

    # 其他人各有幾篇
    for user_key, count in [('u1', 8), ('u2', 14), ('u3', 5), ('admin1', 18), ('u5', 6)]:
        entries = []
        for i in range(count):
            date_str = (today - datetime.timedelta(days=i)).isoformat()
            content = sample_entries[i % len(sample_entries)]
            diary_entry_keys.append([lids[user_key], date_str])
            entries.append({'line_user_id': lids[user_key], 'entry_date': date_str, 'content': content, 'locked': True})
        safe_upsert('diary_entries', entries, 'line_user_id,entry_date')

    ids['diary_entry_keys'] = diary_entry_keys

    # 授權查閱（u1、u2授權給牧師）
    safe_upsert('diary_share_grants', [
        {'owner_line_user_id': lids['u1'], 'pastor_line_user_id': lids['pastor'], 'revoked_at': None},
        {'owner_line_user_id': lids['u2'], 'pastor_line_user_id': lids['pastor'], 'revoked_at': None},
    ], 'owner_line_user_id,pastor_line_user_id')
    ids['diary_share_pairs'] = [[lids['u1'], lids['pastor']], [lids['u2'], lids['pastor']]]

    total_entries = len(diary_entry_keys)
    ok(f'60天讀經進度、{total_entries} 篇靈修日記、2 份牧養授權')

    # ────────────────────────────────────────────────────────
    # 9. 禱讀本訂購（devotional_orders + registrations）
    # ────────────────────────────────────────────────────────
    print('📗  建立禱讀本訂購...')
    doids = {n: g() for n in ['order1','order2']}
    safe_insert('devotional_orders', [
        {'id': doids['order1'], 'scripture': '2026 下半年天天讀聖經',
         'author': '橄欖文化', 'price': 160, 'deadline': d(20)},
        {'id': doids['order2'], 'scripture': '荒漠甘泉（2026年版）',
         'author': '蔻瑞·坦彼得', 'price': 220, 'deadline': d(35)},
    ])
    ids['doids'] = doids

    drids = {n: g() for n in ['dr1','dr2','dr3','dr4','dr5','dr6','dr7','dr8']}
    safe_insert('devotional_registrations', [
        {'id': drids['dr1'], 'order_id': doids['order1'], 'group_name': '橄欖枝小組',   'quantity': 8,  'registered_by': uids['admin1']},
        {'id': drids['dr2'], 'order_id': doids['order1'], 'group_name': '葡萄枝小組',   'quantity': 6,  'registered_by': uids['admin2']},
        {'id': drids['dr3'], 'order_id': doids['order1'], 'group_name': '生命活水小組', 'quantity': 5,  'registered_by': uids['u5']},
        {'id': drids['dr4'], 'order_id': doids['order1'], 'group_name': '以馬內利小組', 'quantity': 4,  'registered_by': uids['u7']},
        {'id': drids['dr5'], 'order_id': doids['order2'], 'group_name': '橄欖枝小組',   'quantity': 10, 'registered_by': uids['admin1']},
        {'id': drids['dr6'], 'order_id': doids['order2'], 'group_name': '葡萄枝小組',   'quantity': 7,  'registered_by': uids['admin2']},
        {'id': drids['dr7'], 'order_id': doids['order2'], 'group_name': '生命活水小組', 'quantity': 5,  'registered_by': uids['u5']},
        {'id': drids['dr8'], 'order_id': doids['order2'], 'group_name': '以馬內利小組', 'quantity': 3,  'registered_by': uids['u7']},
    ])
    ids['drids'] = drids
    ok(f'2 批禱讀本訂購（共 {8+6+5+4} 本 / {10+7+5+3} 本）')

    # ────────────────────────────────────────────────────────
    # 10. 每週週報（weekly_bulletins）
    # ────────────────────────────────────────────────────────
    print('📰  建立每週週報...')
    bids = {n: g() for n in ['b1','b2','b3','b4']}
    PLACEHOLDER_PDF = 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf'
    bulletins = [
        {'id': bids['b1'], 'title': f'{today.strftime("%Y年%m月%d日")} 主日週報',
         'bulletin_date': d(0),  'pdf_url': PLACEHOLDER_PDF},
        {'id': bids['b2'], 'title': f'{(today - datetime.timedelta(days=7)).strftime("%Y年%m月%d日")} 主日週報',
         'bulletin_date': d(-7), 'pdf_url': PLACEHOLDER_PDF},
        {'id': bids['b3'], 'title': f'{(today - datetime.timedelta(days=14)).strftime("%Y年%m月%d日")} 主日週報',
         'bulletin_date': d(-14),'pdf_url': PLACEHOLDER_PDF},
        {'id': bids['b4'], 'title': f'{(today - datetime.timedelta(days=21)).strftime("%Y年%m月%d日")} 主日週報',
         'bulletin_date': d(-21),'pdf_url': PLACEHOLDER_PDF},
    ]
    safe_insert('weekly_bulletins', bulletins)
    ids['bids'] = bids
    ok(f'{len(bulletins)} 期週報')

    # ────────────────────────────────────────────────────────
    # 11. 站內通知（notifications）
    # ────────────────────────────────────────────────────────
    print('🔔  建立站內通知...')
    nids = [g() for _ in range(10)]
    safe_insert('notifications', [
        {'id': nids[0],  'user_id': uids['u1'],     'title': '📋 活動費用提醒', 'body': '「2026 暑期青年特會」報名費尚未繳清，請於截止前完成繳費。',       'type': 'payment_reminder',  'link': f'/event/{eids["youth"]}',   'is_read': False},
        {'id': nids[1],  'user_id': uids['u2'],     'title': '📋 活動費用提醒', 'body': '「2026 暑期青年特會」報名費尚未繳清，請於截止前完成繳費。',       'type': 'payment_reminder',  'link': f'/event/{eids["youth"]}',   'is_read': False},
        {'id': nids[2],  'user_id': uids['u3'],     'title': '📚 課程費用提醒', 'body': '「新生命課程」教材費尚未繳清，請盡快完成繳費。',                   'type': 'course_reminder',   'link': f'/courses/{cids["new_life"]}', 'is_read': False},
        {'id': nids[3],  'user_id': uids['u1'],     'title': '⛪ 教會行事 — 教會禱告週', 'body': f'活動日期：{d(10)}，歡迎全體會友參加。',               'type': 'announcement',      'link': '/calendar',                 'is_read': False},
        {'id': nids[4],  'user_id': uids['u2'],     'title': '⛪ 教會行事 — 教會禱告週', 'body': f'活動日期：{d(10)}，歡迎全體會友參加。',               'type': 'announcement',      'link': '/calendar',                 'is_read': True},
        {'id': nids[5],  'user_id': uids['u3'],     'title': '⛪ 教會行事 — 教會禱告週', 'body': f'活動日期：{d(10)}，歡迎全體會友參加。',               'type': 'announcement',      'link': '/calendar',                 'is_read': False},
        {'id': nids[6],  'user_id': uids['pastor'], 'title': '📣 系統公告',    'body': '感謝大家使用本系統！有任何功能建議歡迎直接告訴同工。',             'type': 'announcement',      'link': '/',                         'is_read': False},
        {'id': nids[7],  'user_id': uids['u5'],     'title': '📅 行程提醒',    'body': f'「2026 秋季退修會」將於 {d(55)} 開始，請提前規劃！',            'type': 'calendar_reminder', 'link': '/calendar',                 'is_read': False},
        {'id': nids[8],  'user_id': uids['u7'],     'title': '⛪ 教會行事 — 受洗典禮',  'body': f'活動日期：{d(30)}，歡迎全體會友出席見證。',             'type': 'announcement',      'link': '/calendar',                 'is_read': False},
        {'id': nids[9],  'user_id': uids['admin1'], 'title': '📋 活動費用提醒', 'body': '「親子關係成長營」有報名者尚未完成繳費，請至活動頁面查看名單。', 'type': 'payment_reminder',  'link': f'/event/{eids["parent"]}',  'is_read': False},
    ])
    ids['nids'] = nids
    ok(f'{len(nids)} 條站內通知')

    # ────────────────────────────────────────────────────────
    # 完成
    # ────────────────────────────────────────────────────────
    save_ids(ids)
    print('\n' + '='*55)
    print('✅  DEMO 資料插入完成！')
    print('='*55)
    print('\n📌  展示帳號（需由對應 LINE ID 登入，或手動調整 session）：')
    print(f'   牧師/超管：LINE ID = {lids["pastor"]}（林建志牧師）')
    print(f'   管理員：   LINE ID = {lids["admin1"]}（陳美玲同工）')
    print(f'   一般會友： LINE ID = {lids["u1"]}（李靜宜）')
    print('\n🗑️   清除資料：python seed_demo.py --clear')
    print('='*55 + '\n')


# ── 清除 ──────────────────────────────────────────────────────
def clear():
    print('\n🗑️   清除 DEMO 展示資料...\n')
    ids = load_ids()
    if not ids:
        print('找不到 .seed_ids.json，沒有資料可清除。')
        return

    def flat(v):
        if isinstance(v, dict):
            return list(v.values())
        return v or []

    def del_by_ids(table, id_list, col='id'):
        id_list = [x for x in flat(id_list) if x]
        if not id_list:
            return
        for i in range(0, len(id_list), 50):
            chunk = id_list[i:i+50]
            try:
                db.table(table).delete().in_(col, chunk).execute()
            except Exception as e:
                warn(f'delete {table}', e)
        print(f'  🗑   {table} ({len(id_list)})')

    del_by_ids('notifications',            ids.get('nids', []))
    del_by_ids('weekly_bulletins',         ids.get('bids', {}))
    del_by_ids('devotional_registrations', ids.get('drids', {}))
    del_by_ids('devotional_orders',        ids.get('doids', {}))

    # Diary entries（用 line_user_id + entry_date）
    pairs = ids.get('diary_entry_keys') or []
    for line_uid, entry_date in pairs:
        try:
            db.table('diary_entries').delete()\
              .eq('line_user_id', line_uid).eq('entry_date', entry_date).execute()
        except Exception:
            pass
    if pairs:
        print(f'  🗑   diary_entries ({len(pairs)})')

    # Diary share grants
    for pair in (ids.get('diary_share_pairs') or []):
        try:
            db.table('diary_share_grants').delete()\
              .eq('owner_line_user_id', pair[0]).eq('pastor_line_user_id', pair[1]).execute()
        except Exception:
            pass

    # Diary plan
    plan_dates = ids.get('diary_plan_dates', [])
    for i in range(0, len(plan_dates), 50):
        try:
            db.table('diary_plan').delete().in_('date', plan_dates[i:i+50]).execute()
        except Exception as e:
            warn('diary_plan', e)
    if plan_dates:
        print(f'  🗑   diary_plan ({len(plan_dates)})')

    del_by_ids('morning_prayer_reports',   ids.get('mr_ids', []))
    del_by_ids('prayer_reports',           ids.get('pr_ids', []))
    del_by_ids('children_sunday_reports',  ids.get('chr_ids', []))
    del_by_ids('sunday_reports',           ids.get('sr_ids', []))
    del_by_ids('cell_reports',             ids.get('crids', {}))
    del_by_ids('cell_members',             ids.get('cmids', {}))

    # Cell group leaders（by group_id）
    for gid in flat(ids.get('cgids', {})):
        try:
            db.table('cell_group_leaders').delete().eq('group_id', gid).execute()
        except Exception:
            pass
    del_by_ids('cell_groups', ids.get('cgids', {}))

    del_by_ids('prayer_comments',  ids.get('cmt_ids', {}))
    del_by_ids('prayer_reactions', ids.get('react_ids', []))
    del_by_ids('prayers',          ids.get('pids', {}))

    del_by_ids('session_attendance',   ids.get('att_ids', []))
    del_by_ids('course_enrollments',   ids.get('enroll_ids', {}))
    all_sess = (ids.get('sess_nl') or []) + (ids.get('sess_disc') or [])
    del_by_ids('course_sessions', all_sess)
    del_by_ids('courses',           ids.get('cids', {}))
    del_by_ids('course_categories', ids.get('cat_ids', {}))

    del_by_ids('registrations', ids.get('rids', {}))
    del_by_ids('event_fields',  ids.get('fids', {}))
    del_by_ids('events',        ids.get('eids', {}))

    del_by_ids('church_events', ids.get('ceids', {}))
    del_by_ids('groups',        ids.get('gtids', {}))
    del_by_ids('users',         ids.get('uids', {}))

    SEED_FILE.unlink(missing_ok=True)
    print('\n✅  所有 DEMO 資料已清除\n')


if __name__ == '__main__':
    if '--clear' in sys.argv:
        clear()
    else:
        seed()
