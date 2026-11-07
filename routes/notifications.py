import logging
# 站內通知系統路由
from flask import Blueprint, session, request, jsonify, render_template, redirect, url_for
from routes.decorators import login_required, admin_required, super_admin_required
from db import supabase
from datetime import datetime, timedelta, timezone

notifications_bp = Blueprint('notifications', __name__)
TAIPEI_TZ = timezone(timedelta(hours=8))




# ── 工具函式：建立通知 ─────────────────────────────────────
def create_notification(user_id, title, body=None, type='info',
                        link=None, ref_type=None, ref_id=None):
    """單一用戶建立一則通知"""
    try:
        supabase.table('notifications').insert({
            'user_id':  user_id,
            'title':    title,
            'body':     body,
            'type':     type,
            'link':     link,
            'ref_type': ref_type,
            'ref_id':   ref_id,
        }).execute()
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)  # 通知失敗不影響主流程
    # 站內通知已經寫好了，推播只是錦上添花（先站內、再推播；失敗不往上炸）
    _push([user_id], title, body, link, type)


def batch_notify(user_ids, title, body=None, type='info',
                 link=None, ref_type=None, ref_id=None):
    """批次建立通知（每批 100 筆）"""
    rows = [{
        'user_id':  uid,
        'title':    title,
        'body':     body,
        'type':     type,
        'link':     link,
        'ref_type': ref_type,
        'ref_id':   ref_id,
    } for uid in user_ids]
    for i in range(0, len(rows), 100):
        try:
            supabase.table('notifications').insert(rows[i:i+100]).execute()
        except Exception:
            logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
    _push(user_ids, title, body, link, type)
    return len(rows)


def batch_notify_rows(rows):
    """一次送出**內容各自不同**的通知。

    `batch_notify` 是「同一則發給很多人」；這一支是「每個人一則不一樣的」。

    ★ 為什麼需要它：候補遞補的通知要寫出**是誰**遞補上了
      （代報者幫五個人報名，收到五則一樣的「你已經正式報名了」
      看不出是哪一位）。但逐筆 create_notification 會變成 N 次來回 ——
      調高人數上限一次遞補 20 人就是 20 次，而那是管理員按下去等著的。

    rows: [{user_id, title, body, type, link, ref_type, ref_id}, ...]
    回實際送出的筆數。
    """
    rows = [r for r in (rows or []) if r.get('user_id') and r.get('title')]
    if not rows:
        return 0
    sent = 0
    for i in range(0, len(rows), 100):
        chunk = rows[i:i + 100]
        try:
            supabase.table('notifications').insert(chunk).execute()
            sent += len(chunk)
        except Exception:
            logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
    _push_rows(rows)
    return sent


def _push_rows(rows):
    """一批內容各自不同的通知 → **一批推播**。

    ★★ 這裡原本是 `for r in rows: _push([r['user_id']], …)` ——
      而 `_push` 會開一條背景執行線。所以聚經速讀那一則
      （114 個人）會在免費方案上瞬間開 **114 條執行線、
      114 次資料庫查詢**，而 `push.send_in_background` 自己的
      說明裡就寫著不可以這樣做（「119 條執行線會把免費
      方案的記憶體吃掉」）。

      失敗全部被背景執行線吃掉，所以症狀是
      **站內通知全部都在、手機一則都沒響** ——
      使用者：「推播測試鈕 有正確推播 但是沒有收到過
      其他的東西」（測試鈕是同步送的，不走這條路）。

    ★ 內容一樣的人先併成一組，一組只做一次 payload。
    """
    groups = {}
    for r in rows or ():
        if not r.get('user_id') or not should_push(r.get('type')):
            continue
        key = (r.get('title'), r.get('body'), r.get('link'))
        groups.setdefault(key, []).append(r['user_id'])
    jobs = [(uids, title, body or '', link or '/')
            for (title, body, link), uids in groups.items()]
    if not jobs:
        return
    try:
        from routes.push import send_many_in_background
        send_many_in_background(jobs)
    except Exception:                                  # noqa: BLE001
        pass



def should_push(type_):
    """推不推的規則只有一份（`routes/push.PUSH_TYPES`）。

    ★ 這裡只是轉一手，不在這裡臨時判斷 ——
      那張註冊表是使用者一項一項圈的。
      沒設金鑰等等場合回 False 也是安全的方向。
    """
    try:
        from routes.push import should_push as _sp
        return _sp(type_)
    except Exception:                                  # noqa: BLE001
        return False


def _push(user_ids, title, body, link, type=None):
    """順便推播到手機。推不推由 `push.should_push(type)` 決定（註冊表，不認得的一律不推）。

    ★ 整支包起來：推播壞掉不可以讓發通知失敗。送出丟到背景執行緒：全體廣播要打外部 HTTPS，
      同步跑會讓同工按下「發送公告」後等二十幾秒、再按一次，全教會收到兩則。
    """
    try:
        from routes.push import send_in_background, should_push
        if not should_push(type):
            return
        send_in_background(list(user_ids), title, body or '', link or '/')
    except Exception:
        pass


# ══════════════════════════════════════════
# 學員端 API
# ══════════════════════════════════════════

@notifications_bp.route('/api/notifications')
@login_required
def api_get_notifications():
    """取得用戶最新 30 則通知 + 未讀數"""
    uid = session['user_id']
    items = supabase.table('notifications')\
        .select('*').eq('user_id', uid)\
        .order('created_at', desc=True)\
        .limit(30).execute().data or []
    unread = sum(1 for n in items if not n.get('is_read'))
    return jsonify({'notifications': items, 'unread': unread})


@notifications_bp.route('/api/notifications/<notif_id>/read', methods=['POST'])
@login_required
def api_mark_read(notif_id):
    """標記單則已讀"""
    uid = session['user_id']
    supabase.table('notifications').update({'is_read': True})\
        .eq('id', notif_id).eq('user_id', uid).execute()
    return jsonify({'success': True})


@notifications_bp.route('/api/notifications/read-all', methods=['POST'])
@login_required
def api_mark_all_read():
    """全部標記已讀"""
    uid = session['user_id']
    supabase.table('notifications').update({'is_read': True})\
        .eq('user_id', uid).eq('is_read', False).execute()
    return jsonify({'success': True})


@notifications_bp.route('/api/notifications/check-reminders', methods=['POST'])
@login_required
def api_check_reminders():
    """
    懶式觸發：用戶進入首頁時自動檢查，產生繳費提醒通知。
    - 活動：距今 ≤ reminder_days 天，有未付款報名
    - 課程：距今 ≤ reminder_days 天有堂次，有未付款報名
    同一 ref 只產生一次（去重）。
    """
    uid  = session['user_id']
    now  = datetime.now(TAIPEI_TZ)
    created = 0

    # ── 1. 活動繳費提醒 ──────────────────────────
    # 撈用戶未付款的報名（有費用的活動）
    regs = supabase.table('registrations')\
        .select('event_id, payment_status')\
        .eq('user_id', uid)\
        .eq('payment_status', 'unpaid')\
        .execute().data or []

    if regs:
        event_ids = [r['event_id'] for r in regs]
        events = supabase.table('events')\
            .select('id, title, event_start, fee, reminder_days')\
            .in_('id', event_ids)\
            .gt('fee', 0)\
            .execute().data or []

        for ev in events:
            ev_start = ev.get('event_start')
            if not ev_start:
                continue
            try:
                ev_dt = datetime.fromisoformat(ev_start.replace('Z', '+00:00')).astimezone(TAIPEI_TZ)
            except Exception:
                continue
            days = ev.get('reminder_days') or 3
            delta = (ev_dt - now).total_seconds() / 86400
            if not (0 <= delta <= days):
                continue

            # 去重：同 ref 只通知一次
            existing = supabase.table('notifications').select('id')\
                .eq('user_id', uid).eq('type', 'payment_reminder')\
                .eq('ref_type', 'event').eq('ref_id', ev['id']).execute().data
            if existing:
                continue

            ev_date = ev_start[:10]
            create_notification(
                user_id  = uid,
                title    = f'⬜ 費用待繳 — {ev["title"]}',
                body     = f'活動日期 {ev_date}，尚有費用未繳納，請盡快完成，如有疑問請洽行政同工。',
                type     = 'payment_reminder',
                link     = f'/event/{ev["id"]}',
                ref_type = 'event',
                ref_id   = ev['id'],
            )
            created += 1

    # ── 2. 課程繳費提醒 ──────────────────────────
    try:
        course_enrollments = supabase.table('course_enrollments')\
            .select('course_id, payment_status')\
            .eq('user_id', uid)\
            .eq('status', 'enrolled')\
            .eq('payment_status', 'unpaid')\
            .execute().data or []

        for ce in course_enrollments:
            cid = ce['course_id']
            course = supabase.table('courses')\
                .select('id, title, has_material, meal_options, reminder_days')\
                .eq('id', cid).execute().data
            if not course:
                continue
            c = course[0]
            has_fee = c.get('has_material') or \
                      (c.get('meal_options') and c['meal_options'].get('enabled'))
            if not has_fee:
                continue

            days = c.get('reminder_days') or 3
            # 找 reminder_days 天內有沒有堂次
            soon_str  = (now + timedelta(days=days)).strftime('%Y-%m-%dT23:59:59')
            today_str = now.strftime('%Y-%m-%dT00:00:00')
            next_sess = supabase.table('course_sessions')\
                .select('scheduled_at')\
                .eq('course_id', cid)\
                .gte('scheduled_at', today_str)\
                .lte('scheduled_at', soon_str)\
                .order('scheduled_at').limit(1).execute().data
            if not next_sess:
                continue

            existing = supabase.table('notifications').select('id')\
                .eq('user_id', uid).eq('type', 'payment_reminder')\
                .eq('ref_type', 'course').eq('ref_id', cid).execute().data
            if existing:
                continue

            sess_date = (next_sess[0].get('scheduled_at') or '')[:10]
            create_notification(
                user_id  = uid,
                title    = f'⬜ 費用待繳 — {c["title"]}',
                body     = f'近期堂次 {sess_date} 即將到來，課程含教材費/餐費，請盡快完成繳費。',
                type     = 'payment_reminder',
                link     = f'/courses/{cid}',
                ref_type = 'course',
                ref_id   = cid,
            )
            created += 1
    except Exception as e:
        print(f'[notifications] course reminders error (table may not exist): {e}')

    # ── 3. 個人行程提醒 ──────────────────────────
    try:
        personal_events = supabase.table('personal_events')\
            .select('id, title, event_date, remind_days')\
            .eq('user_id', uid).execute().data or []
        for pe in personal_events:
            event_date = pe.get('event_date')
            if not event_date:
                continue
            try:
                ev_dt = datetime.fromisoformat(event_date).replace(tzinfo=TAIPEI_TZ)
            except Exception:
                continue
            days = pe.get('remind_days') or 1
            delta = (ev_dt - now).total_seconds() / 86400
            if not (0 <= delta <= days):
                continue
            existing = supabase.table('notifications').select('id')\
                .eq('user_id', uid).eq('ref_type', 'personal_event')\
                .eq('ref_id', pe['id']).eq('is_read', False).execute().data
            if existing:
                continue
            create_notification(
                user_id  = uid,
                title    = f'📅 行程提醒 — {pe["title"]}',
                body     = f'行程日期：{event_date}',
                type     = 'calendar_reminder',
                link     = '/calendar',
                ref_type = 'personal_event',
                ref_id   = pe['id'],
            )
            created += 1
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)

    # ── 4. 教會行事曆提醒 ──────────────────────────
    try:
        church_events = supabase.table('church_events')\
            .select('id, title, event_date, remind_days').execute().data or []
        for ce in church_events:
            event_date = ce.get('event_date')
            if not event_date:
                continue
            try:
                ev_dt = datetime.fromisoformat(event_date).replace(tzinfo=TAIPEI_TZ)
            except Exception:
                continue
            days = ce.get('remind_days') or 3
            delta = (ev_dt - now).total_seconds() / 86400
            if not (0 <= delta <= days):
                continue
            existing = supabase.table('notifications').select('id')\
                .eq('user_id', uid).eq('ref_type', 'church_event')\
                .eq('ref_id', ce['id']).eq('is_read', False).execute().data
            if existing:
                continue
            create_notification(
                user_id  = uid,
                title    = f'⛪ 教會行事提醒 — {ce["title"]}',
                body     = f'活動日期：{event_date}',
                type     = 'calendar_reminder',
                link     = '/calendar',
                ref_type = 'church_event',
                ref_id   = ce['id'],
            )
            created += 1
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)

    return jsonify({'success': True, 'created': created})


# ══════════════════════════════════════════
# 管理員：手動發送活動通知
# ══════════════════════════════════════════

@notifications_bp.route('/admin/events/<event_id>/notify', methods=['POST'])
@admin_required
def admin_event_notify(event_id):
    """發送活動通知給所有已報名者"""
    data = request.get_json() or {}
    message = (data.get('message') or '').strip()

    ev = supabase.table('events')\
        .select('id, title, event_start').eq('id', event_id).execute().data
    if not ev:
        return jsonify({'error': '找不到活動'}), 404
    ev = ev[0]

    regs = supabase.table('registrations')\
        .select('user_id').eq('event_id', event_id).execute().data or []
    user_ids = list({r['user_id'] for r in regs if r.get('user_id')})
    if not user_ids:
        return jsonify({'success': True, 'count': 0, 'msg': '目前無報名者'})

    ev_date = (ev.get('event_start') or '')[:10]
    body = f'活動日期：{ev_date}' + (f'\n{message}' if message else '')
    count = batch_notify(
        user_ids = user_ids,
        title    = f'📋 活動通知 — {ev["title"]}',
        body     = body,
        type     = 'event_reminder',
        link     = f'/event/{event_id}',
        ref_type = 'event',
        ref_id   = event_id,
    )
    return jsonify({'success': True, 'count': count})


@notifications_bp.route('/admin/courses/<course_id>/notify', methods=['POST'])
@admin_required
def admin_course_notify(course_id):
    """發送課程通知給所有已報名者"""
    data = request.get_json() or {}
    message = (data.get('message') or '').strip()

    c = supabase.table('courses')\
        .select('id, title').eq('id', course_id).execute().data
    if not c:
        return jsonify({'error': '找不到課程'}), 404
    c = c[0]

    enrollments = supabase.table('course_enrollments')\
        .select('user_id').eq('course_id', course_id)\
        .eq('status', 'enrolled').execute().data or []
    user_ids = list({e['user_id'] for e in enrollments if e.get('user_id')})
    if not user_ids:
        return jsonify({'success': True, 'count': 0, 'msg': '目前無報名者'})

    count = batch_notify(
        user_ids = user_ids,
        title    = f'📖 課程通知 — {c["title"]}',
        body     = message or '請注意近期課程安排',
        type     = 'course_reminder',
        link     = f'/courses/{course_id}',
        ref_type = 'course',
        ref_id   = course_id,
    )
    return jsonify({'success': True, 'count': count})


# ══════════════════════════════════════════
# 超級管理員：公告廣播
# ══════════════════════════════════════════

@notifications_bp.route('/admin/announcements')
@super_admin_required
def admin_announcements_page():
    """公告管理頁面"""
    # 最近 20 則公告（只撈第一個 user 的，標題去重顯示）
    recent = supabase.table('notifications')\
        .select('title, body, link, created_at')\
        .eq('type', 'announcement')\
        .order('created_at', desc=True)\
        .limit(40).execute().data or []
    # 去重（同標題只留一筆）
    seen, deduped = set(), []
    for r in recent:
        key = r['title'] + (r['created_at'] or '')[:16]
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return render_template('admin/announcements.html', recent=deduped[:20])


@notifications_bp.route('/admin/announcements/send', methods=['POST'])
@super_admin_required
def admin_announcements_send():
    """廣播公告給全體用戶"""
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    body  = (data.get('body') or '').strip()
    link  = (data.get('link') or '').strip() or None
    if not title:
        return jsonify({'error': '請填寫公告標題'}), 400

    all_users = supabase.table('users').select('id').execute().data or []
    if not all_users:
        return jsonify({'success': True, 'count': 0})

    user_ids = [u['id'] for u in all_users]
    count = batch_notify(
        user_ids = user_ids,
        title    = f'📢 {title}',
        body     = body or None,
        type     = 'announcement',
        link     = link,
        ref_type = 'announcement',
    )
    return jsonify({'success': True, 'count': count})
