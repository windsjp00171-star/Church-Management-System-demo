# 教會行事曆路由
from flask import Blueprint, session, request, jsonify, redirect, render_template, url_for
from routes.decorators import login_required
from db import supabase
from datetime import date, datetime, timezone, timedelta
import calendar as cal_module

calendar_bp = Blueprint('calendar', __name__)

TAIPEI_TZ = timezone(timedelta(hours=8))

def _to_taipei(s):
    """UTC ISO 字串 → 台灣時間 datetime"""
    if not s:
        return None
    try:
        s = str(s)
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            return dt.astimezone(TAIPEI_TZ)
        return dt  # naive，直接當台灣時間
    except Exception:
        return None




# ── 行事曆頁面（所有登入用戶；管理員多出教會行事管理功能） ────────────
@calendar_bp.route('/calendar')
@login_required
def calendar_page():
    is_admin = session.get('is_admin', False)
    return render_template('calendar.html', is_admin=is_admin)


# ── 行事曆資料 API ─────────────────────────────────────────────────────
@calendar_bp.route('/api/calendar')
@login_required
def api_calendar():
    """回傳指定年月的所有事項（教會手動 + 系統活動 + 課程堂次 + 個人行程）"""
    try:
        year  = int(request.args.get('year',  date.today().year))
        month = int(request.args.get('month', date.today().month))
    except (ValueError, TypeError):
        year, month = date.today().year, date.today().month

    first_str = f"{year}-{month:02d}-01"
    last_day  = cal_module.monthrange(year, month)[1]
    last_str  = f"{year}-{month:02d}-{last_day:02d}"

    items = []

    # 1. 教會手動行事（所有人可見）
    church = supabase.table('church_events')\
        .select('id, title, event_date, description, color')\
        .gte('event_date', first_str).lte('event_date', last_str)\
        .order('event_date').execute().data or []
    for e in church:
        items.append({
            'date':        e['event_date'],
            'title':       e['title'],
            'description': e.get('description') or '',
            'color':       e.get('color') or '#7b1fa2',
            'type':        'church',
            'id':          e['id'],
        })

    # 2. 系統活動（所有人可見）
    events = supabase.table('events')\
        .select('id, title, event_start, location, is_open')\
        .gte('event_start', first_str)\
        .lte('event_start', last_str + 'T23:59:59')\
        .order('event_start').execute().data or []
    for e in events:
        d = (e['event_start'] or '')[:10]
        t = (e['event_start'] or '')[11:16]
        if d:
            items.append({
                'date':        d,
                'time':        t,
                'title':       e['title'],
                'description': e.get('location') or '',
                'color':       '#06C755',
                'type':        'event',
                'id':          e['id'],
                'is_open':     e.get('is_open', False),
                'link':        f"/event/{e['id']}",
            })

    # 3. 課程堂次（所有人可見）
    sessions = supabase.table('course_sessions')\
        .select('id, session_number, scheduled_at, courses(id, title)')\
        .gte('scheduled_at', first_str)\
        .lte('scheduled_at', last_str + 'T23:59:59')\
        .not_.is_('scheduled_at', 'null')\
        .order('scheduled_at').execute().data or []
    for s in sessions:
        dt_taipei = _to_taipei(s.get('scheduled_at'))
        d = dt_taipei.strftime('%Y-%m-%d') if dt_taipei else ''
        t = dt_taipei.strftime('%H:%M') if dt_taipei else ''
        course = s.get('courses') or {}
        if d and course:
            items.append({
                'date':        d,
                'time':        t,
                'title':       f"{course.get('title','')} 第{s['session_number']}堂",
                'description': '',
                'color':       '#1e88e5',
                'type':        'course',
                'link':        f"/courses/{course.get('id','')}",
            })

    # 4. 個人行程（只有本人可見）
    uid = session.get('user_id')
    if uid:
        personal = supabase.table('personal_events')\
            .select('id, title, event_date, description, color')\
            .eq('user_id', uid)\
            .gte('event_date', first_str).lte('event_date', last_str)\
            .order('event_date').execute().data or []
        for p in personal:
            items.append({
                'date':        p['event_date'],
                'title':       p['title'],
                'description': p.get('description') or '',
                'color':       p.get('color') or '#e65100',
                'type':        'personal',
                'id':          p['id'],
            })

    items.sort(key=lambda x: x['date'])
    return jsonify(items)


# ── 個人行程 CRUD ──────────────────────────────────────────────────────
@calendar_bp.route('/calendar/personal/new', methods=['POST'])
@login_required
def personal_event_new():
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    event_date = (data.get('event_date') or '').strip()
    if not title or not event_date:
        return jsonify({'success': False, 'error': '標題與日期為必填'})
    try:
        remind_days = int(data.get('remind_days') or 1)
    except (ValueError, TypeError):
        remind_days = 1
    supabase.table('personal_events').insert({
        'user_id':     session['user_id'],
        'title':       title,
        'event_date':  event_date,
        'description': (data.get('description') or '').strip() or None,
        'color':       data.get('color') or '#e65100',
        'remind_days': remind_days,
    }).execute()
    return jsonify({'success': True})


@calendar_bp.route('/calendar/personal/<item_id>/delete', methods=['POST'])
@login_required
def personal_event_delete(item_id):
    # 確認是本人的行程才能刪除
    result = supabase.table('personal_events')\
        .select('id').eq('id', item_id).eq('user_id', session['user_id'])\
        .execute()
    if not result.data:
        return jsonify({'success': False, 'error': '找不到或無權限'})
    supabase.table('personal_events').delete().eq('id', item_id).execute()
    return jsonify({'success': True})
