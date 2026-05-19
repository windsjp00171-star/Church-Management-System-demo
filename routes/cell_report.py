"""
小組回報 Blueprint（Flask 版，使用 Supabase）
移植自 cell_reporter（Django）。
url_prefix="/cell-report"
"""
import json
import datetime
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, jsonify
)

from db import supabase

cell_report_bp = Blueprint('cell_report', __name__)

# =========================
# 輔助函式
# =========================

def _require_login():
    """需要登入（整合系統以 user_id 判斷）"""
    return bool(session.get('user_id'))


def _require_pastor():
    return bool(session.get('is_pastor'))


def _require_staff():
    return bool(session.get('is_staff') or session.get('is_pastor'))


def _login_redirect():
    return redirect(url_for('auth.login_page'))


def _no_permission(msg='你沒有權限。'):
    flash(msg, 'error')
    return redirect(url_for('cell_report.portal'))


def _get_last_sunday(ref_date=None) -> datetime.date:
    if ref_date is None:
        ref_date = datetime.date.today()
    weekday = ref_date.weekday()
    days_since_sunday = (weekday - 6) % 7
    return ref_date - datetime.timedelta(days=days_since_sunday)


def _get_last_wednesday(ref_date=None) -> datetime.date:
    if ref_date is None:
        ref_date = datetime.date.today()
    weekday = ref_date.weekday()
    days_since_wed = (weekday - 2) % 7
    return ref_date - datetime.timedelta(days=days_since_wed)


def _get_last_friday(ref_date=None) -> datetime.date:
    if ref_date is None:
        ref_date = datetime.date.today()
    weekday = ref_date.weekday()
    days_since_fri = (weekday - 4) % 7
    return ref_date - datetime.timedelta(days=days_since_fri)


def _get_last_meeting_date_for_group(group: Dict, ref_date=None) -> datetime.date:
    if ref_date is None:
        ref_date = datetime.date.today()

    day_str = (group.get('weekly_gather_day') or '').strip()
    if not day_str:
        return _get_last_sunday(ref_date)

    weekday_map = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6}
    target_weekday = None
    for ch, w in weekday_map.items():
        if ch in day_str:
            target_weekday = w
            break

    if target_weekday is None:
        return _get_last_sunday(ref_date)

    current_weekday = ref_date.weekday()
    days_since = (current_weekday - target_weekday) % 7
    return ref_date - datetime.timedelta(days=days_since)


def _status_to_label(code: str) -> str:
    mapping = {
        'full': '出席',
        'late': '遲到',
        'leave': '請假',
        'absent': '未請假未出席',
    }
    return mapping.get(code or '', '未填')


# =========================
# Supabase 操作
# =========================

def _get_group(group_id) -> Optional[Dict]:
    res = supabase.table('cell_groups').select('*').eq('id', group_id).execute()
    return (res.data or [None])[0]


def _get_active_groups() -> List[Dict]:
    res = supabase.table('cell_groups').select('*').eq('is_active', True).order('name').execute()
    return res.data or []


def _get_members(group_id) -> List[Dict]:
    res = supabase.table('cell_members').select('*').eq('group_id', group_id).eq('is_active', True).order('id').execute()
    return res.data or []


def _get_or_create_report(group_id, week_date_str: str) -> Dict:
    res = (
        supabase.table('cell_reports')
        .select('*')
        .eq('group_id', group_id)
        .eq('week_date', week_date_str)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    ins = supabase.table('cell_reports').insert({
        'group_id': group_id,
        'week_date': week_date_str,
        'is_complete': False,
        'no_meeting': False,
    }).execute()
    return ins.data[0] if ins.data else {}


def _get_attendance_map(group_id, report_id) -> Dict[str, Dict]:
    members = _get_members(group_id)
    if not members:
        return {}
    member_ids = [str(m['id']) for m in members]
    res = (
        supabase.table('cell_attendance')
        .select('*')
        .eq('report_id', report_id)
        .in_('member_id', member_ids)
        .execute()
    )
    return {str(a['member_id']): a for a in (res.data or [])}


def _has_group_access(group_id) -> bool:
    if session.get('is_pastor') or session.get('is_staff'):
        return True
    user_id = session.get('user_id')
    res = (
        supabase.table('cell_group_leaders')
        .select('id')
        .eq('user_id', user_id)
        .eq('group_id', group_id)
        .execute()
    )
    return bool(res.data)


# =========================
# 路由
# =========================

@cell_report_bp.get('/cell-report/portal')
def portal():
    if not _require_login():
        return _login_redirect()

    user_id = session.get('user_id')

    if session.get('is_pastor') or session.get('is_staff'):
        groups = _get_active_groups()
    else:
        res = (
            supabase.table('cell_group_leaders')
            .select('group_id')
            .eq('user_id', user_id)
            .execute()
        )
        group_ids = [r['group_id'] for r in (res.data or [])]
        groups = []
        for gid in group_ids:
            g = _get_group(gid)
            if g and g.get('is_active'):
                groups.append(g)

    return render_template('cell_report/portal.html', groups=groups)


@cell_report_bp.route('/cell-report/<group_id>/section1', methods=['GET', 'POST'])
def section1(group_id):
    if not _require_login():
        return _login_redirect()

    group = _get_group(group_id)
    if not group:
        flash('找不到小組', 'error')
        return redirect(url_for('cell_report.portal'))

    if not _has_group_access(group_id):
        return _no_permission()

    today = datetime.date.today()
    this_week_date = _get_last_meeting_date_for_group(group, today)

    prefill_date_str = request.args.get('prefill_date')
    if prefill_date_str:
        try:
            display_date = datetime.date.fromisoformat(prefill_date_str)
        except ValueError:
            display_date = this_week_date
    else:
        display_date = this_week_date

    if request.method == 'POST':
        date_str = request.form.get('week_date')
        no_meeting = request.form.get('no_meeting') == 'on'
        no_meeting_reason = (request.form.get('no_meeting_reason') or '').strip()

        try:
            selected_date = datetime.date.fromisoformat(date_str)
        except Exception:
            selected_date = this_week_date

        session['week_date'] = selected_date.isoformat()

        report = _get_or_create_report(group_id, selected_date.isoformat())
        update_data: Dict[str, Any] = {'no_meeting': no_meeting}

        if no_meeting:
            update_data['no_meeting_reason'] = no_meeting_reason
            update_data['attendance_count'] = None
            update_data['is_complete'] = True
        else:
            attendance_raw = request.form.get('attendance_count', '').strip()
            try:
                update_data['attendance_count'] = int(attendance_raw or 0)
            except ValueError:
                update_data['attendance_count'] = 0
            update_data['no_meeting_reason'] = ''
            update_data['is_complete'] = False

        supabase.table('cell_reports').update(update_data).eq('id', report['id']).execute()

        return redirect(url_for('cell_report.section2', group_id=group_id,
                                week_date=selected_date.isoformat()))

    report = _get_or_create_report(group_id, display_date.isoformat())

    return render_template('cell_report/section1.html',
                           group=group,
                           this_week=display_date,
                           report=report,
                           is_backfill=display_date != this_week_date)


@cell_report_bp.route('/cell-report/<group_id>/section2', methods=['GET', 'POST'])
def section2(group_id):
    if not _require_login():
        return _login_redirect()

    group = _get_group(group_id)
    if not group:
        flash('找不到小組', 'error')
        return redirect(url_for('cell_report.portal'))

    if not _has_group_access(group_id):
        return _no_permission()

    week_date = request.args.get('week_date') or session.get('week_date')
    if not week_date:
        flash('缺少週報日期，請先從 Section1 進入。', 'error')
        return redirect(url_for('cell_report.section1', group_id=group_id))

    try:
        week_date_obj = datetime.date.fromisoformat(week_date)
    except Exception:
        flash('週報日期錯誤', 'error')
        return redirect(url_for('cell_report.section1', group_id=group_id))

    report = _get_or_create_report(group_id, week_date_obj.isoformat())
    members = _get_members(group_id)
    attendance_map = _get_attendance_map(group_id, report['id'])

    display_map = {}
    for m in members:
        att = attendance_map.get(str(m['id']))
        if att:
            display_map[str(m['id'])] = {
                'cell': _status_to_label(att.get('cell_status', '')),
                'sunday': _status_to_label(att.get('sunday_status', '')),
                'rpg': _status_to_label(att.get('rpg_status', '')),
            }
        else:
            display_map[str(m['id'])] = {'cell': '未填', 'sunday': '未填', 'rpg': '未填'}

    this_week_date = _get_last_meeting_date_for_group(group, datetime.date.today())

    return render_template('cell_report/section2.html',
                           group=group,
                           members=members,
                           attendance_map=attendance_map,
                           display_map=display_map,
                           week_date=week_date_obj,
                           report=report,
                           is_no_meeting=bool(report.get('no_meeting')),
                           is_backfill=week_date_obj != this_week_date)


@cell_report_bp.post('/cell-report/<group_id>/ajax/attendance')
def ajax_save_attendance(group_id):
    if not _require_login():
        return jsonify({'success': False, 'error': '未登入'}), 401

    if not _has_group_access(group_id):
        return jsonify({'success': False, 'error': '沒有權限'}), 403

    try:
        data = json.loads(request.data.decode('utf-8'))
    except Exception:
        return jsonify({'success': False, 'error': '資料格式錯誤'}), 400

    member_id = data.get('member_id')
    week_date_str = data.get('week_date')
    field = data.get('field')
    value = data.get('value', '')

    allowed_fields = {'cell_status', 'sunday_status', 'rpg_status'}
    if field not in allowed_fields:
        return jsonify({'success': False, 'error': '欄位錯誤'}), 400

    try:
        datetime.date.fromisoformat(week_date_str)
    except Exception:
        return jsonify({'success': False, 'error': '日期格式錯誤'}), 400

    report = _get_or_create_report(group_id, week_date_str)

    res = (
        supabase.table('cell_attendance')
        .select('id')
        .eq('report_id', report['id'])
        .eq('member_id', member_id)
        .execute()
    )

    if res.data:
        supabase.table('cell_attendance').update({field: value}).eq('id', res.data[0]['id']).execute()
    else:
        supabase.table('cell_attendance').insert({
            'report_id': report['id'],
            'member_id': member_id,
            field: value,
        }).execute()

    return jsonify({'success': True})


@cell_report_bp.post('/cell-report/<group_id>/ajax/add-member')
def add_member_ajax(group_id):
    if not _require_login():
        return jsonify({'success': False, 'error': '未登入'}), 401

    if not _has_group_access(group_id):
        return jsonify({'success': False, 'error': '沒有權限'}), 403

    try:
        data = json.loads(request.data.decode('utf-8'))
    except Exception:
        return jsonify({'success': False, 'error': '資料格式錯誤'}), 400

    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': '姓名不可空白'}), 400

    res = supabase.table('cell_members').insert({
        'group_id': group_id,
        'name': name,
        'is_active': True,
    }).execute()

    if res.data:
        member = res.data[0]
        return jsonify({'success': True, 'member_id': member['id'], 'name': member['name']})
    return jsonify({'success': False, 'error': '新增失敗'}), 500


@cell_report_bp.post('/cell-report/<group_id>/ajax/remove-member/<member_id>')
def remove_member_ajax(group_id, member_id):
    if not _require_login():
        return jsonify({'success': False, 'error': '未登入'}), 401

    if not _has_group_access(group_id):
        return jsonify({'success': False, 'error': '沒有權限'}), 403

    supabase.table('cell_members').update({'is_active': False}).eq('id', member_id).execute()
    return jsonify({'success': True})


@cell_report_bp.route('/cell-report/<group_id>/step3', methods=['GET', 'POST'])
def step3(group_id):
    if not _require_login():
        return _login_redirect()

    group = _get_group(group_id)
    if not group:
        flash('找不到小組', 'error')
        return redirect(url_for('cell_report.portal'))

    if not _has_group_access(group_id):
        return _no_permission()

    week_date_str = request.args.get('week_date') or session.get('week_date')
    if not week_date_str:
        flash('缺少週報日期，請先從 Step1 進入。', 'error')
        return redirect(url_for('cell_report.section1', group_id=group_id))

    try:
        week_date = datetime.date.fromisoformat(week_date_str)
    except Exception:
        flash('週報日期格式錯誤。', 'error')
        return redirect(url_for('cell_report.section1', group_id=group_id))

    report = _get_or_create_report(group_id, week_date.isoformat())
    this_week_date = _get_last_meeting_date_for_group(group, datetime.date.today())

    if request.method == 'POST':
        required_fields = ['spiritual_status', 'family_status', 'work_status', 'health_status']
        error = None
        for f in required_fields:
            if not request.form.get(f, '').strip():
                error = '請完整填寫小組長自評四大面向'
                break
        if not error and not request.form.get('group_status', '').strip():
            error = '請填寫小組整體狀況'

        if error:
            return render_template('cell_report/step3.html',
                                   group=group, report=report,
                                   week_date=week_date,
                                   is_backfill=week_date != this_week_date,
                                   error=error)

        newcomers_json = request.form.get('newcomers_json', '[]')
        try:
            newcomer_raw = json.loads(newcomers_json)
        except Exception:
            newcomer_raw = []

        update_data = {
            'spiritual_status': request.form.get('spiritual_status', ''),
            'spiritual_note': request.form.get('spiritual_note', ''),
            'family_status': request.form.get('family_status', ''),
            'family_note': request.form.get('family_note', ''),
            'work_status': request.form.get('work_status', ''),
            'work_note': request.form.get('work_note', ''),
            'health_status': request.form.get('health_status', ''),
            'health_note': request.form.get('health_note', ''),
            'group_status': request.form.get('group_status', ''),
            'coworker_suggestion': request.form.get('coworker_suggestion', ''),
            'newcomer_raw': json.dumps(newcomer_raw, ensure_ascii=False),
            'is_complete': True,
        }

        supabase.table('cell_reports').update(update_data).eq('id', report['id']).execute()

        return redirect(url_for('cell_report.done', group_id=group_id,
                                week_date=week_date.isoformat()))

    return render_template('cell_report/step3.html',
                           group=group, report=report,
                           week_date=week_date,
                           is_backfill=week_date != this_week_date)


@cell_report_bp.get('/cell-report/<group_id>/done')
def done(group_id):
    if not _require_login():
        return _login_redirect()

    group = _get_group(group_id)
    if not group:
        flash('找不到小組', 'error')
        return redirect(url_for('cell_report.portal'))

    week_date_str = request.args.get('week_date', '')
    try:
        week_date = datetime.date.fromisoformat(week_date_str)
    except Exception:
        week_date = datetime.date.today()

    this_week_date = _get_last_meeting_date_for_group(group, datetime.date.today())

    return render_template('cell_report/done.html',
                           group=group,
                           week_date=week_date,
                           is_backfill=week_date != this_week_date)


@cell_report_bp.get('/cell-report/pastor-dashboard')
def pastor_dashboard():
    if not _require_login():
        return _login_redirect()

    if not _require_pastor():
        flash('你沒有牧者權限', 'error')
        return redirect(url_for('cell_report.portal'))

    week_str = request.args.get('week')
    if week_str:
        try:
            base_date = datetime.date.fromisoformat(week_str)
        except Exception:
            base_date = datetime.date.today()
    else:
        base_date = datetime.date.today()

    sunday = _get_last_sunday(base_date)
    week_end = sunday
    week_start = sunday - datetime.timedelta(days=6)
    prev_week = week_end - datetime.timedelta(days=7)
    next_week = week_end + datetime.timedelta(days=7)

    adult_report = _get_sunday_report(sunday.isoformat())
    children_report = _get_children_report(sunday.isoformat())
    prayer_rep = _get_prayer_report(_get_last_wednesday(sunday).isoformat())
    morning_rep = _get_morning_prayer_report(_get_last_friday(sunday).isoformat())

    adult_first = (adult_report or {}).get('first_service_count', 0) or 0
    adult_second = (adult_report or {}).get('second_service_count', 0) or 0
    adult_count = adult_first + adult_second
    children_count = (children_report or {}).get('attendance_count', 0) or 0
    prayer_count = (prayer_rep or {}).get('attendance_count', 0) or 0
    morning_prayer_count = (morning_rep or {}).get('attendance_count', 0) or 0

    groups = _get_active_groups()
    group_data = _build_group_data(groups, sunday)

    today_sunday = _get_last_sunday(datetime.date.today())

    return render_template('cell_report/dashboard.html',
                           sunday_date=sunday,
                           prayer_date=_get_last_wednesday(sunday),
                           morning_prayer_date=_get_last_friday(sunday),
                           adult=adult_count,
                           adult_first=adult_first,
                           adult_second=adult_second,
                           children=children_count,
                           prayer=prayer_count,
                           morning_prayer=morning_prayer_count,
                           groups=group_data,
                           prev_week=prev_week,
                           next_week=next_week,
                           week_start=week_start,
                           week_end=week_end,
                           is_current_week=sunday == today_sunday,
                           dashboard_title='牧者週報總覽',
                           is_pastor=True,
                           is_staff=False)


@cell_report_bp.get('/cell-report/staff-dashboard')
def staff_dashboard():
    if not _require_login():
        return _login_redirect()

    if not _require_staff():
        flash('你沒有同工權限', 'error')
        return redirect(url_for('cell_report.portal'))

    week_str = request.args.get('week')
    if week_str:
        try:
            base_date = datetime.date.fromisoformat(week_str)
        except Exception:
            base_date = datetime.date.today()
    else:
        base_date = datetime.date.today()

    sunday = _get_last_sunday(base_date)
    week_end = sunday
    week_start = sunday - datetime.timedelta(days=6)
    prev_week = week_end - datetime.timedelta(days=7)
    next_week = week_end + datetime.timedelta(days=7)

    adult_report = _get_sunday_report(sunday.isoformat())
    children_report = _get_children_report(sunday.isoformat())
    prayer_rep = _get_prayer_report(_get_last_wednesday(sunday).isoformat())
    morning_rep = _get_morning_prayer_report(_get_last_friday(sunday).isoformat())

    adult_first = (adult_report or {}).get('first_service_count', 0) or 0
    adult_second = (adult_report or {}).get('second_service_count', 0) or 0
    adult_count = adult_first + adult_second
    children_count = (children_report or {}).get('attendance_count', 0) or 0
    prayer_count = (prayer_rep or {}).get('attendance_count', 0) or 0
    morning_prayer_count = (morning_rep or {}).get('attendance_count', 0) or 0

    groups = _get_active_groups()
    group_data = _build_group_data(groups, sunday)

    today_sunday = _get_last_sunday(datetime.date.today())

    return render_template('cell_report/dashboard.html',
                           sunday_date=sunday,
                           prayer_date=_get_last_wednesday(sunday),
                           morning_prayer_date=_get_last_friday(sunday),
                           adult=adult_count,
                           adult_first=adult_first,
                           adult_second=adult_second,
                           children=children_count,
                           prayer=prayer_count,
                           morning_prayer=morning_prayer_count,
                           groups=group_data,
                           prev_week=prev_week,
                           next_week=next_week,
                           week_start=week_start,
                           week_end=week_end,
                           is_current_week=sunday == today_sunday,
                           dashboard_title='同工管理中心',
                           is_pastor=False,
                           is_staff=True)


@cell_report_bp.route('/cell-report/sunday', methods=['GET', 'POST'])
def sunday():
    """主日報告（公開，無需登入）"""
    date_obj = _get_last_sunday()
    date_str = date_obj.isoformat()

    if request.method == 'POST':
        try:
            data = json.loads(request.data.decode('utf-8'))
            first = int(data.get('first_service_count', 0))
            second = int(data.get('second_service_count', 0))
        except Exception:
            first = second = 0

        report = _get_or_create_sunday_report(date_str)
        supabase.table('sunday_reports').update({
            'first_service_count': first,
            'second_service_count': second,
        }).eq('id', report['id']).execute()
        return jsonify({'success': True})

    report = _get_sunday_report(date_str)
    return render_template('cell_report/sunday_form.html', report=report or {}, date=date_obj)


@cell_report_bp.route('/cell-report/children', methods=['GET', 'POST'])
def children():
    """兒童主日報告（公開，無需登入）"""
    date_obj = _get_last_sunday()
    date_str = date_obj.isoformat()

    if request.method == 'POST':
        try:
            data = json.loads(request.data.decode('utf-8'))
            count = int(data.get('attendance_count', 0))
        except Exception:
            count = 0

        report = _get_or_create_children_report(date_str)
        supabase.table('children_sunday_reports').update({'attendance_count': count}).eq('id', report['id']).execute()
        return jsonify({'success': True})

    report = _get_children_report(date_str)
    return render_template('cell_report/children_sunday_form.html', report=report or {}, date=date_obj)


@cell_report_bp.route('/cell-report/prayer', methods=['GET', 'POST'])
def prayer():
    """禱告會報告（公開，無需登入）"""
    date_obj = _get_last_wednesday()
    date_str = date_obj.isoformat()

    if request.method == 'POST':
        try:
            data = json.loads(request.data.decode('utf-8'))
            count = int(data.get('attendance_count', 0))
        except Exception:
            count = 0

        report = _get_or_create_prayer_report(date_str)
        supabase.table('prayer_reports').update({'attendance_count': count}).eq('id', report['id']).execute()
        return jsonify({'success': True})

    report = _get_prayer_report(date_str)
    return render_template('cell_report/prayer_form.html', report=report or {}, date=date_obj)


@cell_report_bp.route('/cell-report/morning-prayer', methods=['GET', 'POST'])
def morning_prayer():
    """晨禱報告（公開，無需登入）"""
    date_obj = _get_last_friday()
    date_str = date_obj.isoformat()

    if request.method == 'POST':
        try:
            data = json.loads(request.data.decode('utf-8'))
            count = int(data.get('attendance_count', 0))
        except Exception:
            count = 0

        report = _get_or_create_morning_prayer_report(date_str)
        supabase.table('morning_prayer_reports').update({'attendance_count': count}).eq('id', report['id']).execute()
        return jsonify({'success': True})

    report = _get_morning_prayer_report(date_str)
    return render_template('cell_report/morning_prayer_form.html', report=report or {}, date=date_obj)


# =========================
# 聚會報告 helper
# =========================

def _get_sunday_report(date_str: str) -> Optional[Dict]:
    res = supabase.table('sunday_reports').select('*').eq('date', date_str).execute()
    return (res.data or [None])[0]


def _get_children_report(date_str: str) -> Optional[Dict]:
    res = supabase.table('children_sunday_reports').select('*').eq('date', date_str).execute()
    return (res.data or [None])[0]


def _get_prayer_report(date_str: str) -> Optional[Dict]:
    res = supabase.table('prayer_reports').select('*').eq('date', date_str).execute()
    return (res.data or [None])[0]


def _get_morning_prayer_report(date_str: str) -> Optional[Dict]:
    res = supabase.table('morning_prayer_reports').select('*').eq('date', date_str).execute()
    return (res.data or [None])[0]


def _get_or_create_sunday_report(date_str: str) -> Dict:
    existing = _get_sunday_report(date_str)
    if existing:
        return existing
    res = supabase.table('sunday_reports').insert({'date': date_str,
                                                   'first_service_count': 0,
                                                   'second_service_count': 0}).execute()
    return res.data[0] if res.data else {}


def _get_or_create_children_report(date_str: str) -> Dict:
    existing = _get_children_report(date_str)
    if existing:
        return existing
    res = supabase.table('children_sunday_reports').insert({'date': date_str, 'attendance_count': 0}).execute()
    return res.data[0] if res.data else {}


def _get_or_create_prayer_report(date_str: str) -> Dict:
    existing = _get_prayer_report(date_str)
    if existing:
        return existing
    res = supabase.table('prayer_reports').insert({'date': date_str, 'attendance_count': 0}).execute()
    return res.data[0] if res.data else {}


def _get_or_create_morning_prayer_report(date_str: str) -> Dict:
    existing = _get_morning_prayer_report(date_str)
    if existing:
        return existing
    res = supabase.table('morning_prayer_reports').insert({'date': date_str, 'attendance_count': 0}).execute()
    return res.data[0] if res.data else {}


def _build_group_data(groups: List[Dict], sunday: datetime.date) -> List[Dict]:
    result = []
    for g in groups:
        meet_date = _get_last_meeting_date_for_group(g, sunday)
        res = (
            supabase.table('cell_reports')
            .select('*')
            .eq('group_id', g['id'])
            .eq('week_date', meet_date.isoformat())
            .execute()
        )
        report = (res.data or [None])[0]

        if report:
            has_report = report.get('is_complete') or bool(report.get('no_meeting'))
            no_meeting = bool(report.get('no_meeting'))
            no_meeting_reason = (report.get('no_meeting_reason') or '').strip()
            attend = None if no_meeting else report.get('attendance_count')
        else:
            attend = None
            has_report = False
            no_meeting = False
            no_meeting_reason = ''

        result.append({
            'group': g,
            'meet_date': meet_date,
            'attend': attend,
            'has_report': has_report,
            'no_meeting': no_meeting,
            'no_meeting_reason': no_meeting_reason,
        })

    return result
