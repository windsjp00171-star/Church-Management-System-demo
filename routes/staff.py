from flask import Blueprint, render_template, session
from datetime import datetime, timezone, timedelta, time
from db import supabase
from routes.decorators import staff_required

staff_bp = Blueprint('staff', __name__)

TAIPEI_TZ = timezone(timedelta(hours=8))


@staff_bp.get('/staff')
@staff_required
def index():
    now_taipei = datetime.now(TAIPEI_TZ)
    today = now_taipei.date()
    week_later = today + timedelta(days=7)

    # 撈今天到7天內的活動
    try:
        today_start = datetime.combine(today, time.min).replace(tzinfo=TAIPEI_TZ).astimezone(timezone.utc).isoformat()
        week_end = datetime.combine(week_later, time.max).replace(tzinfo=TAIPEI_TZ).astimezone(timezone.utc).isoformat()
        events_res = supabase.table('events')\
            .select('id, title, event_start, event_end, checkin_enabled, checkin_token, is_open, capacity')\
            .gte('event_start', today_start)\
            .lte('event_start', week_end)\
            .order('event_start').execute()
        events = events_res.data or []
    except Exception:
        events = []

    # 每個活動補上報名數與簽到數
    for ev in events:
        try:
            r = supabase.table('registrations')\
                .select('id, checked_in')\
                .eq('event_id', ev['id'])\
                .in_('status', ['registered', 'walk_in'])\
                .execute()
            rows = r.data or []
            ev['reg_count'] = len(rows)
            ev['checkin_count'] = sum(1 for x in rows if x.get('checked_in'))
        except Exception:
            ev['reg_count'] = 0
            ev['checkin_count'] = 0

        # 是否為今天的活動
        try:
            start = datetime.fromisoformat(
                ev['event_start'].replace('Z', '+00:00')
            ).astimezone(TAIPEI_TZ).date()
            ev['is_today'] = (start == today)
            ev['date_label'] = start.strftime('%m/%d') + ('（今天）' if start == today else '')
        except Exception:
            ev['is_today'] = False
            ev['date_label'] = ''

    today_events = [e for e in events if e.get('is_today')]
    upcoming_events = [e for e in events if not e.get('is_today')]

    return render_template('staff/index.html',
        today_events=today_events,
        upcoming_events=upcoming_events,
        staff_name=session.get('real_name') or session.get('display_name') or '同工',
        today_label=now_taipei.strftime('%Y/%m/%d'),
    )
