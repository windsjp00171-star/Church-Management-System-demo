from flask import Blueprint, session, render_template, request, jsonify, redirect, url_for
from db import supabase
from routes.decorators import login_required, admin_required
from datetime import date, datetime, timezone
from math import floor

attendance_bp = Blueprint('attendance', __name__)

LEAVE_LABELS = {
    'annual':   '特休',
    'comp':     '補休',
    'personal': '事假',
    'sick':     '病假',
    'other':    '其他',
}

# ── 勞基法特休天數（週年） ────────────────────────────
def _annual_leave_days(years: float) -> int:
    if years < 0.5:  return 0
    if years < 1:    return 3
    if years < 2:    return 7
    if years < 3:    return 10
    if years < 5:    return 14
    if years < 10:   return 15
    return min(15 + int(years - 10) + 1, 30)


def _calc_entitlement(hire_date: date, cycle: str) -> float:
    """回傳本週期應有特休時數（以小時計，1天=8小時）"""
    today = date.today()
    delta_days = (today - hire_date).days
    years = delta_days / 365.25

    if cycle == 'anniversary':
        # 以最近一個週年為基準
        full_years = floor(years)
        days = _annual_leave_days(full_years) if years >= 0.5 else 0
    else:
        # 曆年制：以今年1/1當下的年資計算
        jan1 = date(today.year, 1, 1)
        years_at_jan1 = (jan1 - hire_date).days / 365.25
        days = _annual_leave_days(floor(years_at_jan1)) if years_at_jan1 >= 0.5 else 0

    return days * 8.0


def _used_hours(user_id: str, leave_type: str, cycle: str, hire_date: date) -> float:
    """計算本週期已用時數"""
    today = date.today()
    if cycle == 'anniversary':
        # 最近一次週年日
        years = floor((today - hire_date).days / 365.25)
        period_start = date(hire_date.year + years, hire_date.month, hire_date.day)
    else:
        period_start = date(today.year, 1, 1)

    rows = supabase.table('leave_requests').select('hours')\
        .eq('user_id', user_id)\
        .eq('leave_type', leave_type)\
        .eq('status', 'approved')\
        .gte('start_date', str(period_start))\
        .execute().data or []
    return sum(float(r['hours']) for r in rows)


def _comp_balance(user_id: str, initial: float) -> float:
    """補休餘額 = 初始 + 核准加班 - 核准補休"""
    earned = supabase.table('overtime_records').select('hours')\
        .eq('user_id', user_id).eq('status', 'approved').execute().data or []
    used = supabase.table('leave_requests').select('hours')\
        .eq('user_id', user_id).eq('leave_type', 'comp').eq('status', 'approved').execute().data or []
    return initial + sum(float(r['hours']) for r in earned) - sum(float(r['hours']) for r in used)


# ── 同工個人頁面 ──────────────────────────────────────
@attendance_bp.route('/attendance')
@login_required
def my_attendance():
    uid = session['user_id']
    profile = supabase.table('staff_profiles').select('*').eq('user_id', uid).execute().data
    if not profile:
        return render_template('attendance/not_enrolled.html')
    p = profile[0]
    hire_date = date.fromisoformat(p['hire_date'])

    entitlement = _calc_entitlement(hire_date, p['leave_cycle'])
    used_annual  = _used_hours(uid, 'annual', p['leave_cycle'], hire_date)
    annual_left  = entitlement - used_annual + float(p['initial_leave_hours'])
    comp_left    = _comp_balance(uid, float(p['initial_comp_hours']))

    requests = supabase.table('leave_requests').select('*')\
        .eq('user_id', uid).order('created_at', desc=True).limit(30).execute().data or []
    overtimes = supabase.table('overtime_records').select('*')\
        .eq('user_id', uid).order('date', desc=True).limit(20).execute().data or []

    return render_template('attendance/my.html',
        profile=p,
        hire_date=hire_date,
        entitlement=entitlement,
        annual_left=annual_left,
        comp_left=comp_left,
        requests=requests,
        overtimes=overtimes,
        leave_labels=LEAVE_LABELS,
    )


@attendance_bp.route('/attendance/request', methods=['POST'])
@login_required
def submit_leave():
    uid = session['user_id']
    data = request.get_json() or {}
    leave_type = data.get('leave_type', '')
    if leave_type not in LEAVE_LABELS:
        return jsonify({'error': '無效假別'}), 400
    hours = float(data.get('hours', 0))
    if hours <= 0:
        return jsonify({'error': '時數必須大於0'}), 400

    # 特休/補休檢查餘額
    profile = supabase.table('staff_profiles').select('*').eq('user_id', uid).execute().data
    if not profile:
        return jsonify({'error': '尚未建立同工資料'}), 400
    p = profile[0]

    if leave_type == 'annual':
        hire_date = date.fromisoformat(p['hire_date'])
        left = _calc_entitlement(hire_date, p['leave_cycle']) \
               - _used_hours(uid, 'annual', p['leave_cycle'], hire_date) \
               + float(p['initial_leave_hours'])
        if hours > left:
            return jsonify({'error': f'特休餘額不足（剩 {left:.1f} 小時）'}), 400
    elif leave_type == 'comp':
        left = _comp_balance(uid, float(p['initial_comp_hours']))
        if hours > left:
            return jsonify({'error': f'補休餘額不足（剩 {left:.1f} 小時）'}), 400

    supabase.table('leave_requests').insert({
        'user_id':    uid,
        'leave_type': leave_type,
        'start_date': data.get('start_date'),
        'end_date':   data.get('end_date'),
        'hours':      hours,
        'reason':     data.get('reason', '').strip() or None,
        'status':     'pending',
    }).execute()

    # 通知管理員
    try:
        admins = supabase.table('users').select('id')\
            .eq('is_super_admin', True).execute().data or []
        if admins:
            name = session.get('real_name') or session.get('display_name') or '同工'
            from routes.notifications import batch_notify
            batch_notify(
                user_ids=[a['id'] for a in admins],
                title=f'📋 請假申請 — {name}',
                body=f'{LEAVE_LABELS[leave_type]} {hours}小時，請至差勤管理確認。',
                type='attendance',
                link='/admin/attendance',
            )
    except Exception as e:
        print(f'[attendance] notify error: {e}')

    return jsonify({'success': True})


@attendance_bp.route('/attendance/overtime', methods=['POST'])
@login_required
def submit_overtime():
    uid = session['user_id']
    data = request.get_json() or {}
    hours = float(data.get('hours', 0))
    if hours <= 0:
        return jsonify({'error': '時數必須大於0'}), 400

    supabase.table('overtime_records').insert({
        'user_id': uid,
        'date':    data.get('date'),
        'hours':   hours,
        'reason':  data.get('reason', '').strip() or None,
        'status':  'pending',
    }).execute()

    try:
        admins = supabase.table('users').select('id')\
            .eq('is_super_admin', True).execute().data or []
        if admins:
            name = session.get('real_name') or session.get('display_name') or '同工'
            from routes.notifications import batch_notify
            batch_notify(
                user_ids=[a['id'] for a in admins],
                title=f'⏰ 加班登錄 — {name}',
                body=f'{data.get("date")} 加班 {hours}小時，請至差勤管理確認。',
                type='attendance',
                link='/admin/attendance',
            )
    except Exception as e:
        print(f'[attendance] notify error: {e}')

    return jsonify({'success': True})


# ── 管理員頁面 ────────────────────────────────────────
@attendance_bp.route('/admin/attendance')
@admin_required
def admin_attendance():
    # 待審核
    pending_leaves = supabase.table('leave_requests').select('*, users(real_name, display_name)')\
        .eq('status', 'pending').order('created_at').execute().data or []
    pending_ot = supabase.table('overtime_records').select('*, users(real_name, display_name)')\
        .eq('status', 'pending').order('date').execute().data or []
    # 同工列表
    profiles = supabase.table('staff_profiles').select('*, users(real_name, display_name)')\
        .eq('is_active', True).order('hire_date').execute().data or []
    return render_template('attendance/admin.html',
        pending_leaves=pending_leaves,
        pending_ot=pending_ot,
        profiles=profiles,
        leave_labels=LEAVE_LABELS,
    )


@attendance_bp.route('/admin/attendance/review/<rec_type>/<rec_id>', methods=['POST'])
@admin_required
def review(rec_type, rec_id):
    data = request.get_json() or {}
    action = data.get('action')
    if action not in ('approve', 'reject'):
        return jsonify({'error': '無效操作'}), 400
    status = 'approved' if action == 'approve' else 'rejected'
    tbl = 'leave_requests' if rec_type == 'leave' else 'overtime_records'
    supabase.table(tbl).update({
        'status': status,
        'reviewed_by': session['user_id'],
        'reviewed_at': datetime.now(timezone.utc).isoformat(),
        'review_note': data.get('note', '').strip() or None,
    }).eq('id', rec_id).execute()
    return jsonify({'success': True})


@attendance_bp.route('/admin/attendance/staff/new', methods=['POST'])
@admin_required
def add_staff():
    data = request.get_json() or {}
    user_id = data.get('user_id', '').strip()
    hire_date = data.get('hire_date', '').strip()
    if not user_id or not hire_date:
        return jsonify({'error': '請填寫必要欄位'}), 400
    supabase.table('staff_profiles').upsert({
        'user_id':             user_id,
        'hire_date':           hire_date,
        'leave_cycle':         data.get('leave_cycle', 'anniversary'),
        'initial_leave_hours': float(data.get('initial_leave_hours', 0)),
        'initial_comp_hours':  float(data.get('initial_comp_hours', 0)),
        'is_active':           True,
    }).execute()
    return jsonify({'success': True})
