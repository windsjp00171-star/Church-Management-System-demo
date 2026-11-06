"""聚會點名（roll_call）

點名自成一塊，與 users / LINE 帳號脫鉤：被點名的是 rc_members（點名名冊）。
操作者只用來寫稽核（id＋姓名快照），不作為被點名者。
寫入一律走資料庫函式（rc_save_record / rc_lock_session / rc_set_count），
同一交易內完成「寫紀錄＋寫稽核」。API 回傳格式：{"status", "data", "error"}。
"""
import csv
import io
from datetime import datetime, timezone

from flask import Blueprint, Response, abort, jsonify, render_template, request, session

from db import supabase
from roll_call_logic import (
    LATE_MODE_LABELS, LEAVE_MODE_LABELS, STATUS_LABELS, can_mark, compute_member_rate,
    describe_rule, parse_count, taipei_input_to_utc_iso, to_taipei, validate_rule,
    validate_status,
)
from routes.decorators import admin_required, staff_required, super_admin_required

roll_call_bp = Blueprint('roll_call', __name__)


# ── 共用 ─────────────────────────────────────────────
def _ok(data=None):
    return jsonify({'status': 200, 'data': data if data is not None else {}, 'error': None})


def _err(message, status=400):
    return jsonify({'status': status, 'data': {}, 'error': message}), status


def _db_error(e):
    """資料庫函式主動拋出的錯誤（P0001）是給使用者看的中文訊息；其他錯誤不外洩內容。"""
    if getattr(e, 'code', None) == 'P0001':
        return _err(getattr(e, 'message', None) or '操作失敗', 400)
    print(f'[roll_call] db error: {e}')
    return _err('儲存失敗，請稍後再試', 500)


def _actor():
    uid = session.get('user_id')
    name = (session.get('real_name') or session.get('display_name') or '').strip()
    return uid, (name or '未具名')


def _is_admin():
    return bool(session.get('is_admin') or session.get('is_super_admin'))


def _is_staff():
    return bool(session.get('is_staff') or session.get('is_pastor') or _is_admin())


def _load_session(sid):
    rows = supabase.table('rc_sessions').select('*').eq('id', sid).execute().data or []
    if not rows:
        abort(404)
    s = rows[0]
    t = supabase.table('rc_meeting_types').select('*').eq('id', s['type_id']).execute().data or [{}]
    s['_type'] = t[0]
    s['_local'] = to_taipei(s['starts_at'])
    return s


def _active_members():
    return supabase.table('rc_members').select('*').eq('status', 'active').order('name').execute().data or []


# ── 同工頁面 ──────────────────────────────────────────
@roll_call_bp.route('/roll-call')
@staff_required
def home():
    sessions = supabase.table('rc_sessions').select('*').eq('status', 'open')\
        .order('starts_at', desc=True).limit(30).execute().data or []
    types = {t['id']: t for t in (supabase.table('rc_meeting_types').select('*').execute().data or [])}
    for s in sessions:
        s['_type'] = types.get(s['type_id'], {})
        s['_local'] = to_taipei(s['starts_at'])
    return render_template('roll_call/home.html', sessions=sessions)


@roll_call_bp.route('/roll-call/session/<sid>')
@staff_required
def session_page(sid):
    s = _load_session(sid)
    members, records, guest = [], {}, None
    if s['_type'].get('record_mode') == 'individual':
        members = _active_members()
        recs = supabase.table('rc_records').select('*').eq('session_id', sid).execute().data or []
        records = {r['member_id']: r for r in recs}
        # 已離開但有紀錄的人也要顯示，避免鎖定後的資料看不到
        known = {m['id'] for m in members}
        extra_ids = [mid for mid in records if mid not in known]
        if extra_ids:
            members += supabase.table('rc_members').select('*').in_('id', extra_ids).execute().data or []
            members.sort(key=lambda m: m['name'])
    g = supabase.table('rc_guest_counts').select('*').eq('session_id', sid).execute().data or []
    guest = g[0]['guest_count'] if g else None
    return render_template('roll_call/session.html', s=s, members=members, records=records,
                           guest=guest, labels=STATUS_LABELS,
                           editable=can_mark(s, _is_admin(), _is_staff()),
                           locked=s['status'] == 'locked')


@roll_call_bp.route('/roll-call/session/<sid>/print')
@staff_required
def print_roster(sid):
    """A4 紙本名冊：只有姓名與勾選欄，不帶任何其他個人資料。"""
    s = _load_session(sid)
    return render_template('roll_call/print.html', s=s, members=_active_members())


@roll_call_bp.route('/api/roll-call/session/<sid>/mark', methods=['POST'])
@staff_required
def api_mark(sid):
    s = _load_session(sid)
    if not can_mark(s, _is_admin(), _is_staff()):
        return _err('此場次已鎖定，只有管理員可以修改', 403)
    data = request.get_json(silent=True) or {}
    try:
        status = validate_status(data.get('status'))
    except ValueError as e:
        return _err(str(e))
    member_id = (data.get('member_id') or '').strip()
    if not member_id:
        return _err('請選擇成員')
    uid, name = _actor()
    try:
        res = supabase.rpc('rc_save_record', {
            'p_session': sid, 'p_member': member_id, 'p_status': status,
            'p_actor': uid, 'p_actor_name': name,
            'p_reason': (data.get('reason') or '').strip() or None,
            'p_backfill': bool(data.get('backfill')),
        }).execute()
    except Exception as e:
        return _db_error(e)
    return _ok(res.data if isinstance(res.data, dict) else {})


@roll_call_bp.route('/api/roll-call/session/<sid>/mark-all-present', methods=['POST'])
@staff_required
def api_mark_all_present(sid):
    """「全到」：只對還沒有紀錄的人標為到，逐筆留稽核。必須由前端明確確認後才呼叫。"""
    s = _load_session(sid)
    if s['status'] == 'locked' or not can_mark(s, _is_admin(), _is_staff()):
        return _err('此場次已鎖定', 403)
    existing = {r['member_id'] for r in (
        supabase.table('rc_records').select('member_id').eq('session_id', sid).execute().data or [])}
    uid, name = _actor()
    done = 0
    for m in _active_members():
        if m['id'] in existing:
            continue
        try:
            supabase.rpc('rc_save_record', {
                'p_session': sid, 'p_member': m['id'], 'p_status': 'present',
                'p_actor': uid, 'p_actor_name': name, 'p_reason': None, 'p_backfill': False,
            }).execute()
            done += 1
        except Exception as e:
            return _db_error(e)
    return _ok({'marked': done})


@roll_call_bp.route('/api/roll-call/session/<sid>/count', methods=['POST'])
@staff_required
def api_count(sid):
    s = _load_session(sid)
    if not can_mark(s, _is_admin(), _is_staff()):
        return _err('此場次已鎖定，只有管理員可以修改', 403)
    data = request.get_json(silent=True) or {}
    kind = data.get('kind')
    if kind not in ('headcount', 'guest_count'):
        return _err('無效的人數種類')
    try:
        count = parse_count(data.get('count'))     # 空白一律退回，不得當 0
    except ValueError as e:
        return _err(str(e))
    uid, name = _actor()
    try:
        supabase.rpc('rc_set_count', {
            'p_session': sid, 'p_kind': kind, 'p_count': count,
            'p_actor': uid, 'p_actor_name': name,
            'p_reason': (data.get('reason') or '').strip() or None,
        }).execute()
    except Exception as e:
        return _db_error(e)
    return _ok({'count': count})


# ── 管理員 ────────────────────────────────────────────
@roll_call_bp.route('/admin/roll-call')
@admin_required
def admin_home():
    types = supabase.table('rc_meeting_types').select('*').order('created_at').execute().data or []
    tmap = {t['id']: t for t in types}
    sessions = supabase.table('rc_sessions').select('*').order('starts_at', desc=True)\
        .limit(40).execute().data or []
    for s in sessions:
        s['_type'] = tmap.get(s['type_id'], {})
        s['_local'] = to_taipei(s['starts_at'])
    members = supabase.table('rc_members').select('*').order('status').order('name').execute().data or []
    return render_template('roll_call/admin.html', types=types, sessions=sessions, members=members)


@roll_call_bp.route('/api/admin/roll-call/types', methods=['POST'])
@admin_required
def api_add_type():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    mode = data.get('record_mode')
    if not name:
        return _err('請填寫聚會名稱')
    if mode not in ('individual', 'headcount'):
        return _err('請選擇記錄方式')
    row = supabase.table('rc_meeting_types').insert({
        'name': name, 'record_mode': mode,
        'counts_toward_rate': bool(data.get('counts_toward_rate', True)),
    }).execute().data
    return _ok(row[0] if row else {})


@roll_call_bp.route('/api/admin/roll-call/members', methods=['POST'])
@admin_required
def api_add_members():
    """名冊：每行一個姓名；與名冊內同名者略過（回報給管理員，不自動合併）。"""
    data = request.get_json(silent=True) or {}
    names = [n.strip() for n in (data.get('names') or '').splitlines() if n.strip()]
    if not names:
        return _err('請輸入至少一個姓名')
    existing = {m['name'] for m in (supabase.table('rc_members').select('name').execute().data or [])}
    added, skipped = [], []
    for n in dict.fromkeys(names):          # 去除同批重複並保序
        if n in existing:
            skipped.append(n)
        else:
            added.append({'name': n, 'source': 'import' if len(names) > 1 else 'manual',
                          'joined_on': data.get('joined_on') or None})
    if added:
        supabase.table('rc_members').insert(added).execute()
    return _ok({'added': len(added), 'skipped': skipped})


@roll_call_bp.route('/api/admin/roll-call/members/<mid>/leave', methods=['POST'])
@admin_required
def api_member_leave(mid):
    """標記離開：不刪除，歷史紀錄全部保留。"""
    data = request.get_json(silent=True) or {}
    supabase.table('rc_members').update({
        'status': 'left',
        'left_on': data.get('left_on') or datetime.now(timezone.utc).date().isoformat(),
    }).eq('id', mid).execute()
    return _ok()


@roll_call_bp.route('/api/admin/roll-call/sessions', methods=['POST'])
@admin_required
def api_add_session():
    data = request.get_json(silent=True) or {}
    type_id = (data.get('type_id') or '').strip()
    if not type_id or not data.get('date') or not data.get('time'):
        return _err('請選擇聚會類型、日期與時間')
    try:
        starts_at = taipei_input_to_utc_iso(data['date'], data['time'])    # 台北輸入 → 存 UTC
    except ValueError:
        return _err('日期或時間格式不正確')
    uid, name = _actor()
    row = supabase.table('rc_sessions').insert({
        'type_id': type_id, 'starts_at': starts_at,
        'created_by': uid, 'created_by_name': name,
    }).execute().data
    return _ok(row[0] if row else {})


@roll_call_bp.route('/api/admin/roll-call/sessions/<sid>/lock', methods=['POST'])
@admin_required
def api_lock(sid):
    uid, name = _actor()
    try:
        supabase.rpc('rc_lock_session', {'p_session': sid, 'p_actor': uid, 'p_actor_name': name}).execute()
    except Exception as e:
        return _db_error(e)
    return _ok()


@roll_call_bp.route('/api/admin/roll-call/sessions/<sid>/audit')
@admin_required
def api_audit(sid):
    rows = supabase.table('rc_audit').select('*').eq('session_id', sid).order('at').execute().data or []
    return _ok({'audit': rows})


# ── 出席率（伺服器計算）─────────────────────────────────
@roll_call_bp.route('/admin/roll-call/rates')
@admin_required
def rates_page():
    types = supabase.table('rc_meeting_types').select('*').eq('record_mode', 'individual').execute().data or []
    rules = supabase.table('rc_rate_rules').select('*').order('name').order('version', desc=True)\
        .execute().data or []
    result, rule = None, None
    rule_id = request.args.get('rule_id')
    if rule_id:
        result, rule = _compute_all(rule_id)
    return render_template('roll_call/rates.html', types=types, rules=rules, result=result, rule=rule,
                           leave_labels=LEAVE_MODE_LABELS, late_labels=LATE_MODE_LABELS,
                           rule_note=describe_rule(rule) if rule else None)


def _compute_all(rule_id):
    rows = supabase.table('rc_rate_rules').select('*').eq('id', rule_id).execute().data or []
    if not rows:
        abort(404)
    rule = rows[0]
    sessions = supabase.table('rc_sessions').select('id, type_id, starts_at, status')\
        .eq('status', 'locked').execute().data or []
    recs = supabase.table('rc_records').select('session_id, member_id, status').execute().data or []
    records = {(r['session_id'], r['member_id']): r['status'] for r in recs}
    members = supabase.table('rc_members').select('*').order('name').execute().data or []
    out = [{'member': m, **compute_member_rate(m, sessions, records, rule)} for m in members]
    return out, rule


@roll_call_bp.route('/api/admin/roll-call/rules', methods=['POST'])
@admin_required
def api_add_rule():
    """規則不可改；同名規則再送出就是新版本。"""
    data = request.get_json(silent=True) or {}
    rule = {
        'name': (data.get('name') or '').strip(),
        'type_ids': data.get('type_ids') or [],
        'range_start': data.get('range_start'),
        'range_end': data.get('range_end'),
        'leave_mode': data.get('leave_mode'),
        'late_mode': data.get('late_mode'),
        'respect_membership_window': data.get('respect_membership_window'),
        'note': (data.get('note') or '').strip() or None,
    }
    if not rule['name']:
        return _err('請填寫規則名稱')
    try:
        validate_rule(rule)
    except ValueError as e:
        return _err(str(e))
    prev = supabase.table('rc_rate_rules').select('version').eq('name', rule['name'])\
        .order('version', desc=True).limit(1).execute().data or []
    uid, name = _actor()
    rule.update(version=(prev[0]['version'] + 1) if prev else 1, created_by=uid, created_by_name=name)
    row = supabase.table('rc_rate_rules').insert(rule).execute().data
    return _ok(row[0] if row else {})


@roll_call_bp.route('/admin/roll-call/rates/export')
@super_admin_required
def rates_export():
    """CSV 匯出（另外授權、每次留記錄）；附規則版本與逐場次依據，讓遴選小組可核對。"""
    result, rule = _compute_all(request.args.get('rule_id', ''))
    uid, name = _actor()
    supabase.table('rc_audit').insert({
        'action': 'export', 'new_value': {'rule_id': rule['id'], 'rule': rule['name'],
                                          'version': rule['version']},
        'actor_id': uid, 'actor_name': name,
    }).execute()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['計算依據', describe_rule(rule)])
    w.writerow([])
    w.writerow(['姓名', '狀態', '加入日', '離開日', '分子', '分母', '出席率(%)'])
    for r in result:
        m = r['member']
        w.writerow([m['name'], m['status'], m.get('joined_on') or '', m.get('left_on') or '',
                    str(r['numerator']), str(r['denominator']),
                    '' if r['percent'] is None else r['percent']])
    w.writerow([])
    w.writerow(['逐場次明細'])
    w.writerow(['姓名', '日期', '狀態', '是否計入', '分子', '分母'])
    for r in result:
        for d in r['details']:
            w.writerow([r['member']['name'], d['date'], STATUS_LABELS.get(d['status'], d['status']),
                        '是' if d['counted'] else '否', d['numerator'], d['denominator']])
    body = '﻿' + buf.getvalue()           # UTF-8 BOM，Excel 才不會亂碼
    return Response(body, mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=roll_call_rates.csv'})
