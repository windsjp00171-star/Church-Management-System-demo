import logging
"""
小組回報 Blueprint（Flask 版，使用 Supabase）
移植自 cell_reporter（Django）。
url_prefix="/cell-report"
"""
import json
import time
import datetime
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, jsonify, abort
)

from db import supabase
from routes.decorators import (
    login_required, pastor_required, staff_required, cell_leader_required
)

cell_report_bp = Blueprint('cell_report', __name__)

# ── 聚會設定（快取）──────────────────────────────────────────
MEETING_DEFAULTS: Dict[str, Dict] = {
    'adult_sunday':    {'label': '成人主日', 'emoji': '⛪', 'weekday': 6, 'service_count': 2},
    'children_sunday': {'label': '兒童主日', 'emoji': '🧒', 'weekday': 6, 'service_count': 1},
    'prayer':          {'label': '禱告會',   'emoji': '🙏', 'weekday': 2, 'service_count': 1},
    'morning_prayer':  {'label': '晨禱',     'emoji': '🌅', 'weekday': 4, 'service_count': 1},
}
_MEETING_CFG_CACHE: Optional[Dict] = None
_MEETING_CFG_TS: float = 0.0
_MEETING_CFG_TTL = 300

# ── 模組開關設定（快取）──────────────────────────────────────────
MODULE_DEFAULTS: Dict[str, bool] = {
    'show_adult_sunday': True,
    'show_children_sunday': True,
    'show_prayer': True,
    'show_morning_prayer': True,
    'show_self_assessment': True,
    'show_group_status': True,
    'show_newcomers': True,
    'show_coworker_suggestion': True,
}
_MODULE_CFG_CACHE: Optional[Dict] = None
_MODULE_CFG_TS: float = 0.0
_MODULE_CFG_TTL = 300


def _get_meeting_settings() -> Dict[str, Dict]:
    global _MEETING_CFG_CACHE, _MEETING_CFG_TS
    now = time.time()
    if _MEETING_CFG_CACHE is not None and now - _MEETING_CFG_TS < _MEETING_CFG_TTL:
        return _MEETING_CFG_CACHE
    result = {}
    # Built-in meetings
    for key, defaults in MEETING_DEFAULTS.items():
        cfg = dict(defaults)
        try:
            res = supabase.table('settings').select('value').eq('key', f'meeting.{key}').execute()
            if res.data:
                cfg.update(json.loads(res.data[0]['value']))
        except Exception:
            logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
        result[key] = cfg
    # Custom meetings (keys stored as meeting.custom_*)
    try:
        res = supabase.table('settings').select('key,value').like('key', 'meeting.custom_%').execute()
        for row in (res.data or []):
            raw_key = row['key']          # e.g. "meeting.custom_1234"
            meeting_key = raw_key[len('meeting.'):]  # e.g. "custom_1234"
            try:
                cfg = json.loads(row['value'])
                cfg['_custom'] = True
                result[meeting_key] = cfg
            except Exception:
                logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
    _MEETING_CFG_CACHE = result
    _MEETING_CFG_TS = now
    return result


def _invalidate_meeting_cache():
    global _MEETING_CFG_CACHE
    _MEETING_CFG_CACHE = None


def _get_module_settings() -> Dict[str, bool]:
    global _MODULE_CFG_CACHE, _MODULE_CFG_TS
    now = time.time()
    if _MODULE_CFG_CACHE is not None and now - _MODULE_CFG_TS < _MODULE_CFG_TTL:
        return _MODULE_CFG_CACHE
    result = dict(MODULE_DEFAULTS)
    try:
        res = supabase.table('settings').select('key,value').like('key', 'module.%').execute()
        for row in (res.data or []):
            short_key = row['key'][len('module.'):]
            if short_key in result:
                result[short_key] = row['value'] in ('true', '1', 'on')
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
    _MODULE_CFG_CACHE = result
    _MODULE_CFG_TS = now
    return result


def _invalidate_module_cache():
    global _MODULE_CFG_CACHE
    _MODULE_CFG_CACHE = None


def _get_custom_meetings_data(mcfg: Dict, base_date=None) -> List[Dict]:
    """Build display data for custom meetings for the dashboard."""
    if base_date is None:
        base_date = datetime.date.today()
    result = []
    for key, cfg in mcfg.items():
        if not key.startswith('custom_'):
            continue
        date_obj = _get_last_weekday_date(cfg.get('weekday', 6), base_date)
        date_str = date_obj.isoformat()
        count = 0
        try:
            res = supabase.table('custom_meeting_reports').select('attendance_count')\
                .eq('date', date_str).eq('meeting_key', key).execute()
            if res.data:
                count = res.data[0].get('attendance_count', 0) or 0
        except Exception:
            logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
        result.append({
            'key': key,
            'label': cfg.get('label', '聚會'),
            'emoji': cfg.get('emoji', '✨'),
            'date': date_obj,
            'count': count,
        })
    return result


def _get_last_weekday_date(weekday: int, ref_date=None) -> datetime.date:
    """回傳最近一次指定星期幾的日期（0=週一…6=週日）。"""
    if ref_date is None:
        ref_date = datetime.date.today()
    days_since = (ref_date.weekday() - weekday) % 7
    return ref_date - datetime.timedelta(days=days_since)




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
    try:
        ins = supabase.table('cell_reports').insert({
            'group_id': group_id,
            'week_date': week_date_str,
            'is_complete': False,
            'no_meeting': False,
        }).execute()
        if ins.data:
            return ins.data[0]
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
    # Re-select in case of concurrent insert or insert returned no data
    res2 = (
        supabase.table('cell_reports')
        .select('*')
        .eq('group_id', group_id)
        .eq('week_date', week_date_str)
        .limit(1)
        .execute()
    )
    return (res2.data or [{}])[0]


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
@login_required
def portal():
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

    today = datetime.date.today()
    report_status = {}
    for g in groups:
        week_date = _get_last_meeting_date_for_group(g, today)
        res = (
            supabase.table('cell_reports')
            .select('is_complete,no_meeting,week_date')
            .eq('group_id', g['id'])
            .eq('week_date', week_date.isoformat())
            .limit(1)
            .execute()
        )
        row = (res.data or [None])[0]
        if row and (row.get('is_complete') or row.get('no_meeting')):
            report_status[str(g['id'])] = {'done': True, 'week_date': week_date}
        else:
            report_status[str(g['id'])] = {'done': False, 'week_date': week_date}

    return render_template('cell_report/portal.html', groups=groups, report_status=report_status)


@login_required
@cell_report_bp.route('/cell-report/<group_id>/section1', methods=['GET', 'POST'])
def section1(group_id):
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

        try:
            supabase.table('cell_reports').update(update_data).eq('id', report['id']).execute()
        except Exception as e:
            print(f"[section1 POST error] {e}")
            flash(f'儲存失敗，請稍後再試。（{e}）', 'error')
            return redirect(url_for('cell_report.section1', group_id=group_id))

        return redirect(url_for('cell_report.section2', group_id=group_id,
                                week_date=selected_date.isoformat()))

    report = _get_or_create_report(group_id, display_date.isoformat())

    return render_template('cell_report/section1.html',
                           group=group,
                           this_week=display_date,
                           report=report,
                           is_backfill=display_date != this_week_date)


@login_required
@cell_report_bp.route('/cell-report/<group_id>/section2', methods=['GET', 'POST'])
def section2(group_id):
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
    if not report.get('id'):
        flash('無法建立回報單，請重新整理後再試。', 'error')
        return redirect(url_for('cell_report.section1', group_id=group_id))
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


@login_required
@cell_report_bp.post('/cell-report/<group_id>/ajax/attendance')
def ajax_save_attendance(group_id):
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
    if not report.get('id'):
        return jsonify({'success': False, 'error': '無法建立回報單'}), 500

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


@login_required
@cell_report_bp.post('/cell-report/<group_id>/ajax/add-member')
def add_member_ajax(group_id):
    if not _has_group_access(group_id):
        return jsonify({'success': False, 'error': '沒有權限'}), 403

    try:
        data = json.loads(request.data.decode('utf-8'))
    except Exception:
        return jsonify({'success': False, 'error': '資料格式錯誤'}), 400

    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': '姓名不可空白'}), 400

    # 可選：同時連結系統帳號 user_id
    user_id = (data.get('user_id') or '').strip() or None

    insert_payload = {
        'group_id': group_id,
        'name': name,
        'is_active': True,
    }
    if user_id:
        insert_payload['user_id'] = user_id

    res = supabase.table('cell_members').insert(insert_payload).execute()

    if res.data:
        member = res.data[0]
        return jsonify({'success': True, 'member_id': member['id'], 'name': member['name']})
    return jsonify({'success': False, 'error': '新增失敗'}), 500


@login_required
@cell_report_bp.post('/cell-report/<group_id>/ajax/link-member/<member_id>')
def link_member_ajax(group_id, member_id):
    """連結（或解除連結）小組成員與系統帳號
    JSON body: { user_id: "uuid" | null }
    """
    if not _has_group_access(group_id):
        return jsonify({'success': False, 'error': '沒有權限'}), 403

    try:
        data = json.loads(request.data.decode('utf-8'))
    except Exception:
        return jsonify({'success': False, 'error': '資料格式錯誤'}), 400

    user_id = data.get('user_id') or None  # null 表示解除連結

    supabase.table('cell_members').update({'user_id': user_id})\
        .eq('id', member_id).eq('group_id', group_id).execute()

    return jsonify({'success': True, 'user_id': user_id})


@login_required
@cell_report_bp.post('/cell-report/<group_id>/ajax/remove-member/<member_id>')
def remove_member_ajax(group_id, member_id):
    if not _has_group_access(group_id):
        return jsonify({'success': False, 'error': '沒有權限'}), 403

    supabase.table('cell_members').update({'is_active': False}).eq('id', member_id).execute()
    return jsonify({'success': True})


@login_required
@cell_report_bp.route('/cell-report/<group_id>/step3', methods=['GET', 'POST'])
def step3(group_id):
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
    mcfg = _get_module_settings()

    def _parse_newcomers(rpt):
        raw = rpt.get('newcomer_raw') if rpt else None
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    if request.method == 'POST':
        error = None
        if mcfg.get('show_self_assessment', True):
            for f in ['spiritual_status', 'family_status', 'work_status', 'health_status']:
                if not request.form.get(f, '').strip():
                    error = '請完整填寫小組長自評四大面向'
                    break
        if not error and mcfg.get('show_group_status', True):
            if not request.form.get('group_status', '').strip():
                error = '請填寫小組整體狀況'

        if error:
            return render_template('cell_report/step3.html',
                                   group=group, report=report,
                                   week_date=week_date,
                                   is_backfill=week_date != this_week_date,
                                   newcomers=_parse_newcomers(report),
                                   module_cfg=mcfg,
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

        if not report.get('id'):
            return render_template('cell_report/step3.html',
                                   group=group, report=report,
                                   week_date=week_date,
                                   is_backfill=week_date != this_week_date,
                                   newcomers=_parse_newcomers(report),
                                   module_cfg=mcfg,
                                   error='無法取得回報紀錄，請重新整理後再試。')
        try:
            supabase.table('cell_reports').update(update_data).eq('id', report['id']).execute()
        except Exception as e:
            print(f"[step3 POST error] {e}")
            return render_template('cell_report/step3.html',
                                   group=group, report=report,
                                   week_date=week_date,
                                   is_backfill=week_date != this_week_date,
                                   newcomers=_parse_newcomers(report),
                                   module_cfg=mcfg,
                                   error=f'儲存失敗，請稍後再試。（{e}）')

        return redirect(url_for('cell_report.done', group_id=group_id,
                                week_date=week_date.isoformat()))

    return render_template('cell_report/step3.html',
                           group=group, report=report,
                           week_date=week_date,
                           is_backfill=week_date != this_week_date,
                           newcomers=_parse_newcomers(report),
                           module_cfg=mcfg)


@cell_report_bp.get('/cell-report/<group_id>/done')
@login_required
def done(group_id):
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


@cell_report_bp.get('/cell-report/<group_id>/view-report')
@login_required
def view_report(group_id):
    """Read-only report detail for pastors / staff / admins."""
    if not (session.get('is_pastor') or session.get('is_admin')):
        return _no_permission()

    group = _get_group(group_id)
    if not group:
        flash('找不到小組', 'error')
        return redirect(url_for('cell_report.pastor_dashboard'))

    week_date_str = request.args.get('week_date', '')
    try:
        week_date = datetime.date.fromisoformat(week_date_str)
    except Exception:
        week_date = _get_last_meeting_date_for_group(group, datetime.date.today())

    res = (
        supabase.table('cell_reports')
        .select('*')
        .eq('group_id', group_id)
        .eq('week_date', week_date.isoformat())
        .execute()
    )
    report = (res.data or [None])[0]

    members = _get_members(group_id)
    attendance_map = {}
    if report:
        attendance_map = _get_attendance_map(group_id, report['id'])

    display_rows = []
    for m in members:
        att = attendance_map.get(str(m['id'])) or {}
        display_rows.append({
            'name': m['name'],
            'cell': _status_to_label(att.get('cell_status', '')),
            'sunday': _status_to_label(att.get('sunday_status', '')),
            'rpg': _status_to_label(att.get('rpg_status', '')),
        })

    # Newcomers
    newcomers = []
    if report and report.get('newcomer_raw'):
        try:
            parsed = json.loads(report['newcomer_raw'])
            newcomers = parsed if isinstance(parsed, list) else []
        except Exception:
            logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)

    prev_week = week_date - datetime.timedelta(days=7)
    next_week = week_date + datetime.timedelta(days=7)
    this_week = _get_last_meeting_date_for_group(group, datetime.date.today())

    back_url = url_for('cell_report.pastor_dashboard', week=week_date.isoformat()) \
        if session.get('is_pastor') \
        else url_for('cell_report.staff_dashboard', week=week_date.isoformat())
    if session.get('is_admin') and not session.get('is_pastor') and not session.get('is_staff'):
        back_url = url_for('cell_report.pastor_dashboard', week=week_date.isoformat())

    return render_template('cell_report/view_report.html',
                           group=group,
                           report=report,
                           week_date=week_date,
                           display_rows=display_rows,
                           newcomers=newcomers,
                           prev_week=prev_week,
                           next_week=next_week,
                           is_current_week=week_date == this_week,
                           back_url=back_url)


@pastor_required
@cell_report_bp.get('/cell-report/pastor-dashboard')
def pastor_dashboard():
    week_str = request.args.get('week')
    if week_str:
        try:
            base_date = datetime.date.fromisoformat(week_str)
        except Exception:
            base_date = datetime.date.today()
    else:
        base_date = datetime.date.today()

    mcfg = _get_meeting_settings()
    anchor_weekday = mcfg['adult_sunday']['weekday']
    anchor = _get_last_weekday_date(anchor_weekday, base_date)
    week_end = anchor
    week_start = anchor - datetime.timedelta(days=6)
    prev_week = week_end - datetime.timedelta(days=7)
    next_week = week_end + datetime.timedelta(days=7)

    children_date = _get_last_weekday_date(mcfg['children_sunday']['weekday'], base_date)
    prayer_date   = _get_last_weekday_date(mcfg['prayer']['weekday'], base_date)
    morning_date  = _get_last_weekday_date(mcfg['morning_prayer']['weekday'], base_date)

    adult_report    = _get_sunday_report(anchor.isoformat())
    children_report = _get_children_report(children_date.isoformat())
    prayer_rep      = _get_prayer_report(prayer_date.isoformat())
    morning_rep     = _get_morning_prayer_report(morning_date.isoformat())

    adult_first  = (adult_report or {}).get('first_service_count', 0) or 0
    adult_second = (adult_report or {}).get('second_service_count', 0) or 0
    adult_count  = adult_first + adult_second
    children_count       = (children_report or {}).get('attendance_count', 0) or 0
    prayer_count         = (prayer_rep or {}).get('attendance_count', 0) or 0
    morning_prayer_count = (morning_rep or {}).get('attendance_count', 0) or 0

    # Custom meetings
    custom_meetings = _get_custom_meetings_data(mcfg, base_date)

    groups = _get_active_groups()
    group_data = _build_group_data(groups, anchor)

    today_anchor = _get_last_weekday_date(anchor_weekday, datetime.date.today())

    return render_template('cell_report/dashboard.html',
                           sunday_date=anchor,
                           prayer_date=prayer_date,
                           morning_prayer_date=morning_date,
                           adult=adult_count,
                           adult_first=adult_first,
                           adult_second=adult_second,
                           children=children_count,
                           prayer=prayer_count,
                           morning_prayer=morning_prayer_count,
                           custom_meetings=custom_meetings,
                           groups=group_data,
                           prev_week=prev_week,
                           next_week=next_week,
                           week_start=week_start,
                           week_end=week_end,
                           is_current_week=anchor == today_anchor,
                           dashboard_title='牧者查閱',
                           is_pastor=True,
                           is_staff=False,
                           meeting_cfg=mcfg,
                           module_cfg=_get_module_settings())


@cell_report_bp.get('/cell-report/staff-dashboard')
@staff_required
def staff_dashboard():
    week_str = request.args.get('week')
    if week_str:
        try:
            base_date = datetime.date.fromisoformat(week_str)
        except Exception:
            base_date = datetime.date.today()
    else:
        base_date = datetime.date.today()

    mcfg = _get_meeting_settings()
    anchor_weekday = mcfg['adult_sunday']['weekday']
    anchor = _get_last_weekday_date(anchor_weekday, base_date)
    week_end = anchor
    week_start = anchor - datetime.timedelta(days=6)
    prev_week = week_end - datetime.timedelta(days=7)
    next_week = week_end + datetime.timedelta(days=7)

    children_date = _get_last_weekday_date(mcfg['children_sunday']['weekday'], base_date)
    prayer_date   = _get_last_weekday_date(mcfg['prayer']['weekday'], base_date)
    morning_date  = _get_last_weekday_date(mcfg['morning_prayer']['weekday'], base_date)

    adult_report    = _get_sunday_report(anchor.isoformat())
    children_report = _get_children_report(children_date.isoformat())
    prayer_rep      = _get_prayer_report(prayer_date.isoformat())
    morning_rep     = _get_morning_prayer_report(morning_date.isoformat())

    adult_first  = (adult_report or {}).get('first_service_count', 0) or 0
    adult_second = (adult_report or {}).get('second_service_count', 0) or 0
    adult_count  = adult_first + adult_second
    children_count       = (children_report or {}).get('attendance_count', 0) or 0
    prayer_count         = (prayer_rep or {}).get('attendance_count', 0) or 0
    morning_prayer_count = (morning_rep or {}).get('attendance_count', 0) or 0

    custom_meetings = _get_custom_meetings_data(mcfg, base_date)

    groups = _get_active_groups()
    group_data = _build_group_data(groups, anchor)

    today_anchor = _get_last_weekday_date(anchor_weekday, datetime.date.today())

    return render_template('cell_report/dashboard.html',
                           sunday_date=anchor,
                           prayer_date=prayer_date,
                           morning_prayer_date=morning_date,
                           adult=adult_count,
                           adult_first=adult_first,
                           adult_second=adult_second,
                           children=children_count,
                           prayer=prayer_count,
                           morning_prayer=morning_prayer_count,
                           custom_meetings=custom_meetings,
                           groups=group_data,
                           prev_week=prev_week,
                           next_week=next_week,
                           week_start=week_start,
                           week_end=week_end,
                           is_current_week=anchor == today_anchor,
                           dashboard_title='同工查閱',
                           is_pastor=False,
                           is_staff=True,
                           meeting_cfg=mcfg,
                           module_cfg=_get_module_settings())


@cell_report_bp.route('/cell-report/sunday', methods=['GET', 'POST'])
def sunday():
    cfg = _get_meeting_settings()['adult_sunday']
    date_obj = _get_last_weekday_date(cfg['weekday'])
    date_str = date_obj.isoformat()
    service_count = cfg.get('service_count', 2)

    if request.method == 'POST':
        try:
            data = json.loads(request.data.decode('utf-8'))
            first = int(data.get('first_service_count', 0))
            second = int(data.get('second_service_count', 0)) if service_count >= 2 else 0
        except Exception:
            first = second = 0

        try:
            report = _get_or_create_sunday_report(date_str)
            from datetime import timezone
            supabase.table('sunday_reports').update({
                'first_service_count': first,
                'second_service_count': second,
                'submitted_by': session.get('user_id'),
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', report['id']).execute()
            return jsonify({'success': True})
        except Exception as e:
            print(f"[sunday POST error] {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    report = _get_sunday_report(date_str)
    submitter_name = _get_submitter_name(report)
    return render_template('cell_report/sunday_form.html',
                           report=report or {}, date=date_obj,
                           service_count=service_count,
                           label=cfg.get('label', '成人主日'),
                           submitter_name=submitter_name)


@cell_report_bp.route('/cell-report/children', methods=['GET', 'POST'])
def children():
    cfg = _get_meeting_settings()['children_sunday']
    date_obj = _get_last_weekday_date(cfg['weekday'])
    date_str = date_obj.isoformat()

    if request.method == 'POST':
        try:
            data = json.loads(request.data.decode('utf-8'))
            count = int(data.get('attendance_count', 0))
        except Exception:
            count = 0

        try:
            from datetime import timezone
            report = _get_or_create_children_report(date_str)
            supabase.table('children_sunday_reports').update({
                'attendance_count': count,
                'submitted_by': session.get('user_id'),
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', report['id']).execute()
            return jsonify({'success': True})
        except Exception as e:
            print(f"[children POST error] {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    report = _get_children_report(date_str)
    submitter_name = _get_submitter_name(report)
    return render_template('cell_report/children_sunday_form.html',
                           report=report or {}, date=date_obj,
                           label=cfg.get('label', '兒童主日'),
                           submitter_name=submitter_name)


@cell_report_bp.route('/cell-report/prayer', methods=['GET', 'POST'])
def prayer():
    cfg = _get_meeting_settings()['prayer']
    date_obj = _get_last_weekday_date(cfg['weekday'])
    date_str = date_obj.isoformat()

    if request.method == 'POST':
        try:
            data = json.loads(request.data.decode('utf-8'))
            count = int(data.get('attendance_count', 0))
        except Exception:
            count = 0

        try:
            from datetime import timezone
            report = _get_or_create_prayer_report(date_str)
            supabase.table('prayer_reports').update({
                'attendance_count': count,
                'submitted_by': session.get('user_id'),
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', report['id']).execute()
            return jsonify({'success': True})
        except Exception as e:
            print(f"[prayer POST error] {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    report = _get_prayer_report(date_str)
    submitter_name = _get_submitter_name(report)
    return render_template('cell_report/prayer_form.html',
                           report=report or {}, date=date_obj,
                           label=cfg.get('label', '禱告會'),
                           submitter_name=submitter_name)


@cell_report_bp.route('/cell-report/morning-prayer', methods=['GET', 'POST'])
def morning_prayer():
    cfg = _get_meeting_settings()['morning_prayer']
    date_obj = _get_last_weekday_date(cfg['weekday'])
    date_str = date_obj.isoformat()

    if request.method == 'POST':
        try:
            data = json.loads(request.data.decode('utf-8'))
            count = int(data.get('attendance_count', 0))
        except Exception:
            count = 0

        try:
            from datetime import timezone
            report = _get_or_create_morning_prayer_report(date_str)
            supabase.table('morning_prayer_reports').update({
                'attendance_count': count,
                'submitted_by': session.get('user_id'),
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', report['id']).execute()
            return jsonify({'success': True})
        except Exception as e:
            print(f"[morning_prayer POST error] {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    report = _get_morning_prayer_report(date_str)
    submitter_name = _get_submitter_name(report)
    return render_template('cell_report/morning_prayer_form.html',
                           report=report or {}, date=date_obj,
                           label=cfg.get('label', '晨禱'),
                           submitter_name=submitter_name)


# ── 聚會設定後台 ─────────────────────────────────────────────
@cell_report_bp.route('/cell-report/admin/meeting-settings', methods=['GET', 'POST'])
@login_required
def admin_meeting_settings():
    if not (session.get('is_admin') or session.get('is_pastor')):
        abort(403)

    WEEKDAY_NAMES = ['週一', '週二', '週三', '週四', '週五', '週六', '週日']

    if request.method == 'POST':
        # Built-in meetings
        keys = ['adult_sunday', 'children_sunday', 'prayer', 'morning_prayer']
        for key in keys:
            weekday = int(request.form.get(f'{key}_weekday', 6))
            service_count = int(request.form.get(f'{key}_service_count', 1))
            label = (request.form.get(f'{key}_label') or MEETING_DEFAULTS[key]['label']).strip()
            emoji = (request.form.get(f'{key}_emoji') or MEETING_DEFAULTS[key]['emoji']).strip()
            payload = json.dumps({
                'weekday': weekday,
                'service_count': service_count,
                'label': label,
                'emoji': emoji,
            }, ensure_ascii=False)
            supabase.table('settings').upsert({'key': f'meeting.{key}', 'value': payload}).execute()

        # Custom meetings: submitted as custom_keys[] (list of active keys)
        active_custom_keys = set(request.form.getlist('custom_keys[]'))

        # Delete removed custom meetings from settings
        try:
            existing = supabase.table('settings').select('key').like('key', 'meeting.custom_%').execute()
            for row in (existing.data or []):
                meeting_key = row['key'][len('meeting.'):]  # e.g. "custom_1234"
                if meeting_key not in active_custom_keys:
                    supabase.table('settings').delete().eq('key', row['key']).execute()
        except Exception:
            logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)

        # Upsert active custom meetings
        for meeting_key in active_custom_keys:
            if not meeting_key.startswith('custom_'):
                continue
            weekday = int(request.form.get(f'{meeting_key}_weekday', 6))
            label = (request.form.get(f'{meeting_key}_label') or '').strip()
            emoji = (request.form.get(f'{meeting_key}_emoji') or '✨').strip()
            if not label:
                continue
            payload = json.dumps({
                'weekday': weekday,
                'label': label,
                'emoji': emoji,
                'service_count': 1,
                '_custom': True,
            }, ensure_ascii=False)
            supabase.table('settings').upsert({'key': f'meeting.{meeting_key}', 'value': payload}).execute()

        _invalidate_meeting_cache()

        # 模組開關
        for key in MODULE_DEFAULTS:
            val = 'true' if request.form.get(f'module_{key}') else 'false'
            supabase.table('settings').upsert({'key': f'module.{key}', 'value': val}).execute()
        _invalidate_module_cache()

        flash('設定已儲存', 'success')
        return redirect(url_for('cell_report.admin_meeting_settings'))

    settings = _get_meeting_settings()
    module_cfg = _get_module_settings()
    return render_template('cell_report/admin_meeting_settings.html',
                           settings=settings,
                           weekday_names=WEEKDAY_NAMES,
                           defaults=MEETING_DEFAULTS,
                           module_cfg=module_cfg)


@cell_report_bp.route('/cell-report/custom-meeting/<meeting_key>', methods=['GET', 'POST'])
@login_required
def custom_meeting(meeting_key):
    if not meeting_key.startswith('custom_'):
        abort(404)
    mcfg = _get_meeting_settings()
    if meeting_key not in mcfg:
        abort(404)
    cfg = mcfg[meeting_key]
    date_obj = _get_last_weekday_date(cfg.get('weekday', 6))
    date_str = date_obj.isoformat()

    if request.method == 'POST':
        try:
            data = json.loads(request.data.decode('utf-8'))
            count = int(data.get('attendance_count', 0))
        except Exception:
            count = 0
        try:
            from datetime import timezone
            uid = session.get('user_id')
            now_iso = datetime.now(timezone.utc).isoformat()
            existing = supabase.table('custom_meeting_reports').select('id')\
                .eq('date', date_str).eq('meeting_key', meeting_key).execute()
            if existing.data:
                supabase.table('custom_meeting_reports').update({
                    'attendance_count': count,
                    'submitted_by': uid,
                    'updated_at': now_iso,
                }).eq('id', existing.data[0]['id']).execute()
            else:
                supabase.table('custom_meeting_reports').insert({
                    'date': date_str, 'meeting_key': meeting_key,
                    'attendance_count': count, 'submitted_by': uid,
                }).execute()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    try:
        res = supabase.table('custom_meeting_reports').select('*')\
            .eq('date', date_str).eq('meeting_key', meeting_key).execute()
        report = (res.data or [None])[0]
    except Exception:
        report = None

    submitter_name = _get_submitter_name(report)
    return render_template('cell_report/custom_meeting_form.html',
                           report=report or {}, date=date_obj,
                           label=cfg.get('label', '聚會'),
                           emoji=cfg.get('emoji', '✨'),
                           meeting_key=meeting_key,
                           submitter_name=submitter_name)


# =========================
# 聚會報告 helper
# =========================

def _get_submitter_name(report: Optional[Dict]) -> Optional[str]:
    """從 report 的 submitted_by 查詢用戶名稱"""
    if not report:
        return None
    uid = report.get('submitted_by')
    if not uid:
        return None
    try:
        res = supabase.table('users').select('real_name, display_name').eq('id', uid).execute()
        if res.data:
            u = res.data[0]
            return u.get('real_name') or u.get('display_name') or '未知'
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
    return None


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
    try:
        res = supabase.table('sunday_reports').insert(
            {'date': date_str, 'first_service_count': 0, 'second_service_count': 0}
        ).execute()
        if res.data:
            return res.data[0]
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
    return _get_sunday_report(date_str) or {}


def _get_or_create_children_report(date_str: str) -> Dict:
    existing = _get_children_report(date_str)
    if existing:
        return existing
    try:
        res = supabase.table('children_sunday_reports').insert({'date': date_str, 'attendance_count': 0}).execute()
        if res.data:
            return res.data[0]
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
    return _get_children_report(date_str) or {}


def _get_or_create_prayer_report(date_str: str) -> Dict:
    existing = _get_prayer_report(date_str)
    if existing:
        return existing
    try:
        res = supabase.table('prayer_reports').insert({'date': date_str, 'attendance_count': 0}).execute()
        if res.data:
            return res.data[0]
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
    return _get_prayer_report(date_str) or {}


def _get_or_create_morning_prayer_report(date_str: str) -> Dict:
    existing = _get_morning_prayer_report(date_str)
    if existing:
        return existing
    try:
        res = supabase.table('morning_prayer_reports').insert({'date': date_str, 'attendance_count': 0}).execute()
        if res.data:
            return res.data[0]
    except Exception:
        logging.getLogger(__name__).warning('忽略非關鍵錯誤', exc_info=True)
    return _get_morning_prayer_report(date_str) or {}


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
            'report_id': report['id'] if report else None,
            'week_date': meet_date.isoformat(),
            'attend': attend,
            'has_report': has_report,
            'no_meeting': no_meeting,
            'no_meeting_reason': no_meeting_reason,
        })

    return result
