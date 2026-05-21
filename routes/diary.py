"""
天父日記 Blueprint
整合自 tianfu-diary/app.py，以 Blueprint 模組化方式掛入整合系統。
url_prefix="/diary"（/api/diary/... 路由獨立列出）
"""
import os
import io
import json
import time
import secrets
from datetime import date, datetime, timezone, timedelta
from calendar import monthrange
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, jsonify, current_app
)

from db import supabase as sb

diary_bp = Blueprint('diary', __name__, template_folder='../templates/diary')

# =========================
# 路徑設定
# =========================
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN_PATH = os.path.join(_BASE_DIR, 'plan.xlsx')
SCRIPTURE_PATH = os.path.join(_BASE_DIR, 'scripture', 'cuv.json')

# =========================
# 聖經全文（啟動時載入一次）
# =========================
BIBLE: Dict[str, Any] = {}
if os.path.exists(SCRIPTURE_PATH):
    with open(SCRIPTURE_PATH, 'r', encoding='utf-8') as _f:
        BIBLE = json.load(_f)

# =========================
# AI 引導快取（重啟清空）
# =========================
_GUIDE_CACHE: Dict[str, List[str]] = {}
_INTRO_CACHE: Dict[str, str] = {}

# =========================
# 讀經進度快取
# =========================
_PLAN_CACHE: Optional[Dict[str, Dict[str, str]]] = None
_PLAN_CACHE_TS: float = 0.0   # DB cache 時間戳
_PLAN_MTIME: Optional[float] = None  # xlsx mtime fallback
_PLAN_CACHE_TTL = 300  # 5 分鐘

# =========================
# 時區
# =========================
TW_TZ = timezone(timedelta(hours=8))


# =========================
# 輔助函式
# =========================

def _today_tw() -> date:
    return datetime.now(TW_TZ).date()


def _today_str() -> str:
    return _today_tw().isoformat()


def _parse_date(s: str) -> date:
    return datetime.strptime(s, '%Y-%m-%d').date()


def _ym_from_month_param(p: str) -> Tuple[int, int]:
    y, m = p.split('-')
    return int(y), int(m)


def _month_param(y: int, m: int) -> str:
    return f'{y:04d}-{m:02d}'


def _shift_month(y: int, m: int, delta: int) -> Tuple[int, int]:
    nm = m + delta
    ny = y
    if nm == 0:
        nm = 12
        ny -= 1
    elif nm == 13:
        nm = 1
        ny += 1
    return ny, nm


def _safe_display_name(profile: Dict[str, Any]) -> str:
    return profile.get('display_name') or profile.get('displayName') or '朋友'


def _require_login() -> bool:
    return 'user_id' in session


def _get_user() -> Dict[str, Any]:
    """從整合系統 session 取得用戶資訊（相容 event-registration- 的 session 格式）"""
    return {
        'line_user_id': session.get('line_id', ''),
        'display_name': session.get('real_name', ''),
        'picture_url': session.get('picture_url', ''),
    }


def _is_diary_admin(line_user_id: str) -> bool:
    # 主後台 is_admin 也可進日記後台
    if session.get('is_admin'):
        return True
    admin_ids_raw = os.environ.get('ADMIN_LINE_USER_IDS', '')
    admin_ids = [s.strip() for s in admin_ids_raw.split(',') if s.strip()]
    return line_user_id in admin_ids


def _invalidate_plan_cache() -> None:
    global _PLAN_CACHE, _PLAN_CACHE_TS, _PLAN_MTIME
    _PLAN_CACHE = None
    _PLAN_CACHE_TS = 0.0
    _PLAN_MTIME = None


def load_plan_map() -> Dict[str, Dict[str, str]]:
    global _PLAN_CACHE, _PLAN_CACHE_TS, _PLAN_MTIME
    now = time.time()

    # 1. 嘗試從 DB 讀取（有 TTL 快取）
    if sb:
        if _PLAN_CACHE is not None and (now - _PLAN_CACHE_TS) < _PLAN_CACHE_TTL:
            return _PLAN_CACHE
        try:
            rows = sb.table('diary_plan').select('date,book,range').execute().data or []
            if rows:
                out: Dict[str, Dict[str, str]] = {
                    str(r['date'])[:10]: {'book': r['book'], 'range': r['range']}
                    for r in rows
                }
                _PLAN_CACHE = out
                _PLAN_CACHE_TS = now
                return _PLAN_CACHE
        except Exception:
            pass

    # 2. Fallback: 讀 xlsx（DB 是空的時候）
    if not os.path.exists(PLAN_PATH):
        return {}
    mtime = os.path.getmtime(PLAN_PATH)
    if _PLAN_CACHE is not None and _PLAN_MTIME == mtime:
        return _PLAN_CACHE
    try:
        import pandas as pd
        df = pd.read_excel(PLAN_PATH)
        out = {}
        for _, r in df.iterrows():
            d = str(r['date'])[:10]
            out[d] = {
                'book': str(r.get('book', '')).strip(),
                'range': str(r.get('range', '')).strip(),
            }
        _PLAN_CACHE = out
        _PLAN_MTIME = mtime
        return _PLAN_CACHE
    except Exception:
        return {}


def _parse_range(rng: str) -> Tuple[int, int, int, int]:
    rng = str(rng).strip()
    if '-' not in rng:
        ch, v = rng.split(':')
        c = int(ch)
        vv = int(v)
        return c, vv, c, vv
    start, end = rng.split('-', 1)
    sc, sv = map(int, start.split(':'))
    if ':' in end:
        ec, ev = map(int, end.split(':'))
    else:
        ec, ev = sc, int(end)
    return sc, sv, ec, ev


def get_scripture(book: str, rng: str) -> List[str]:
    book = (book or '').strip()
    rng = (rng or '').strip()
    if not book or not rng or book not in BIBLE:
        return []
    try:
        sc, sv, ec, ev = _parse_range(rng)
    except Exception:
        return []
    verses: List[str] = []
    for ch in range(sc, ec + 1):
        chapter = BIBLE[book].get(str(ch))
        if not chapter:
            continue
        v_start = sv if ch == sc else 1
        v_end = ev if ch == ec else max(map(int, chapter.keys()))
        for v in range(v_start, v_end + 1):
            txt = chapter.get(str(v))
            if txt:
                verses.append(f'{ch}:{v} {txt}')
    return verses


# =========================
# Supabase 操作
# =========================

def sb_upsert_user(line_user_id: str, display_name: str, picture_url: str) -> None:
    if not sb:
        return
    sb.table('users').upsert(
        {
            'line_user_id': line_user_id,
            'display_name': display_name,
            'picture_url': picture_url,
            'provider': 'line',
            'provider_user_id': line_user_id,
        },
        on_conflict='line_user_id',
    ).execute()


def sb_get_entry(line_user_id: str, entry_date: str) -> Optional[Dict[str, Any]]:
    if not sb:
        return None
    res = (
        sb.table('diary_entries')
        .select('content,locked')
        .eq('line_user_id', line_user_id)
        .eq('entry_date', entry_date)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def sb_save_entry(line_user_id: str, entry_date: str, content: str) -> None:
    if not sb:
        return
    existing = sb_get_entry(line_user_id, entry_date)
    if existing:
        if existing.get('locked'):
            return
        sb.table('diary_entries').update(
            {
                'content': content,
                'locked': True,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }
        ).eq('line_user_id', line_user_id).eq('entry_date', entry_date).execute()
    else:
        sb.table('diary_entries').insert(
            {
                'line_user_id': line_user_id,
                'entry_date': entry_date,
                'content': content,
                'locked': True,
            }
        ).execute()


def sb_list_month_entries(line_user_id: str, y: int, m: int) -> Dict[str, bool]:
    if not sb:
        return {}
    start = date(y, m, 1).isoformat()
    end = date(y, m, monthrange(y, m)[1]).isoformat()
    res = (
        sb.table('diary_entries')
        .select('entry_date')
        .eq('line_user_id', line_user_id)
        .gte('entry_date', start)
        .lte('entry_date', end)
        .execute()
    )
    return {str(r['entry_date']): True for r in (res.data or [])}


def sb_is_pastor(line_user_id: str) -> bool:
    """從 session 讀取牧者身分（登入時已由 auth.py 統一寫入）。"""
    return bool(session.get('is_pastor'))


def sb_list_pastors() -> List[Dict[str, Any]]:
    """查詢有資格被授權的人：is_pastor=True 或是小組長。"""
    if not sb:
        return []
    # is_pastor=True 的人
    pastor_res = (
        sb.table('users')
        .select('line_user_id,display_name,picture_url,is_pastor')
        .eq('is_pastor', True)
        .execute()
    )
    pastor_ids = {r['line_user_id'] for r in (pastor_res.data or [])}
    # 小組長
    leader_res = sb.table('cell_group_leaders').select('user_id').execute()
    leader_user_ids = [r['user_id'] for r in (leader_res.data or [])]
    if leader_user_ids:
        leader_users = (
            sb.table('users')
            .select('line_user_id,display_name,picture_url,is_pastor')
            .in_('id', leader_user_ids)
            .execute()
        )
        for u in (leader_users.data or []):
            if u['line_user_id'] not in pastor_ids:
                pastor_ids.add(u['line_user_id'])
                pastor_res.data.append(u)
    result = [r for r in (pastor_res.data or []) if r['line_user_id'] in pastor_ids]
    result.sort(key=lambda x: x.get('display_name', ''))
    return result


def sb_list_users(limit: int = 500) -> List[Dict[str, Any]]:
    if not sb:
        return []
    res = (
        sb.table('users')
        .select('line_user_id,display_name,picture_url,created_at')
        .order('created_at', desc=True)
        .limit(limit)
        .execute()
    )
    return list(res.data or [])


def sb_set_pastor_whitelist(line_user_id: str, display_name: str, picture_url: str, active: bool) -> None:
    """更新 users 表的 is_pastor 欄位（統一角色管理，不再用 pastor_whitelist 表）。"""
    if not sb:
        return
    sb.table('users').update({'is_pastor': bool(active)})\
        .eq('line_user_id', line_user_id)\
        .execute()


def sb_get_owner_grants(owner_line_user_id: str) -> List[str]:
    if not sb:
        return []
    res = (
        sb.table('diary_share_grants')
        .select('pastor_line_user_id,revoked_at')
        .eq('owner_line_user_id', owner_line_user_id)
        .is_('revoked_at', 'null')
        .execute()
    )
    return [r['pastor_line_user_id'] for r in (res.data or [])]


def sb_grant(owner_line_user_id: str, pastor_line_user_id: str) -> None:
    if not sb:
        return
    upd = (
        sb.table('diary_share_grants')
        .update({'revoked_at': None})
        .eq('owner_line_user_id', owner_line_user_id)
        .eq('pastor_line_user_id', pastor_line_user_id)
        .execute()
    )
    if not (upd.data or []):
        sb.table('diary_share_grants').insert(
            {
                'owner_line_user_id': owner_line_user_id,
                'pastor_line_user_id': pastor_line_user_id,
                'revoked_at': None,
            }
        ).execute()


def sb_revoke(owner_line_user_id: str, pastor_line_user_id: str) -> None:
    if not sb:
        return
    sb.table('diary_share_grants').update(
        {'revoked_at': datetime.now(timezone.utc).isoformat()}
    ).eq('owner_line_user_id', owner_line_user_id).eq('pastor_line_user_id', pastor_line_user_id).execute()


def sb_list_authorized_owners_for_pastor(pastor_line_user_id: str) -> List[Dict[str, Any]]:
    if not sb:
        return []
    grants = (
        sb.table('diary_share_grants')
        .select('owner_line_user_id')
        .eq('pastor_line_user_id', pastor_line_user_id)
        .is_('revoked_at', 'null')
        .execute()
    )
    owner_ids = [g['owner_line_user_id'] for g in (grants.data or [])]
    if not owner_ids:
        return []
    users = (
        sb.table('users')
        .select('line_user_id,display_name,picture_url,created_at')
        .in_('line_user_id', owner_ids)
        .order('display_name')
        .execute()
    )
    return list(users.data or [])


# =========================
# 內部輔助：建立月曆資料
# =========================

def _build_calendar(line_user_id: str, d: str, cy: int, cm: int):
    marks = sb_list_month_entries(line_user_id, cy, cm)
    today_iso = _today_tw().isoformat()
    days_in_month = monthrange(cy, cm)[1]
    calendar_days: List[Dict[str, Any]] = []
    for day in range(1, days_in_month + 1):
        dt = date(cy, cm, day).isoformat()
        is_future = dt > today_iso
        is_written = dt in marks
        is_selected = dt == d
        status = []
        if is_future:
            status.append('future')
        else:
            status.append('written' if is_written else 'unwritten')
        if is_selected:
            status.append('selected')
        calendar_days.append({
            'date': dt,
            'day': day,
            'is_future': is_future,
            'status': ' '.join(status),
        })
    py, pm = _shift_month(cy, cm, -1)
    ny, nm = _shift_month(cy, cm, 1)
    first_day_offset = (date(cy, cm, 1).weekday() + 1) % 7
    return calendar_days, first_day_offset, _month_param(py, pm), _month_param(ny, nm)


# =========================
# 路由
# =========================

@diary_bp.get('/diary')
def index():
    if not _require_login():
        return redirect(url_for('auth.login_page'))

    user = _get_user()
    uid = user.get('line_user_id', '')

    pastor_mode = sb_is_pastor(uid)
    admin_mode = _is_diary_admin(uid)

    d = request.args.get('d') or _today_str()
    try:
        selected = _parse_date(d)
    except Exception:
        selected = _today_tw()
        d = selected.isoformat()

    month_q = request.args.get('month')
    if month_q:
        try:
            cy, cm = _ym_from_month_param(month_q)
        except Exception:
            cy, cm = selected.year, selected.month
    else:
        cy, cm = selected.year, selected.month

    plan = load_plan_map().get(d)
    verses = get_scripture(plan['book'], plan['range']) if plan else []

    try:
        from data.book_background import BOOK_BACKGROUND
        book_bg = BOOK_BACKGROUND.get(plan['book'], '') if plan and plan.get('book') else ''
    except ImportError:
        book_bg = ''

    entry = sb_get_entry(uid, d)
    calendar_days, first_day_offset, prev_month, next_month = _build_calendar(uid, d, cy, cm)

    pastors = sb_list_pastors()
    granted_ids = sb_get_owner_grants(uid)
    granted_map = {pid: True for pid in granted_ids}

    return render_template(
        'diary/index.html',
        display_name=_safe_display_name(user),
        entry_date=d,
        plan=plan,
        verses=verses,
        book_bg=book_bg,
        content=(entry.get('content') if entry else '') or '',
        completed=bool(entry and entry.get('locked')),
        calendar_days=calendar_days,
        first_day_offset=first_day_offset,
        calendar_year=cy,
        calendar_month=cm,
        prev_month=prev_month,
        next_month=next_month,
        pastor_mode=pastor_mode,
        admin_mode=admin_mode,
        pastors=pastors,
        granted_map=granted_map,
    )


@diary_bp.post('/diary/save')
def save():
    if not _require_login():
        return redirect(url_for('auth.login_page'))

    user = _get_user()
    uid = user.get('line_user_id', '')

    d = request.form.get('entry_date') or _today_str()
    content = (request.form.get('content') or '').strip()

    if not content:
        flash('內容不能是空的', 'error')
        return redirect(url_for('diary.index', d=d))

    existing = sb_get_entry(uid, d)
    if existing and existing.get('locked'):
        flash('這一天已鎖定，不能再修改（可複製）。', 'warn')
        return redirect(url_for('diary.index', d=d))

    sb_save_entry(uid, d, content)
    flash('已儲存並鎖定', 'ok')
    return redirect(url_for('diary.index', d=d))


@diary_bp.post('/diary/grant')
def grant():
    if not _require_login():
        return redirect(url_for('auth.login_page'))

    user = _get_user()
    owner_uid = user.get('line_user_id', '')

    d = request.form.get('entry_date') or _today_str()
    action = (request.form.get('action') or 'grant').strip()
    pastor_uid = (request.form.get('pastor_line_user_id') or '').strip()

    if not pastor_uid:
        flash('請先選擇要授權的牧者 / 小組長', 'error')
        return redirect(url_for('diary.index', d=d))

    if not sb_is_pastor(pastor_uid):
        flash('此人目前不在白名單中，無法授權', 'error')
        return redirect(url_for('diary.index', d=d))

    if action == 'revoke':
        sb_revoke(owner_uid, pastor_uid)
        flash('已取消授權', 'ok')
    else:
        sb_grant(owner_uid, pastor_uid)
        flash('已授權（之後會自動延續）', 'ok')

    return redirect(url_for('diary.index', d=d))


@diary_bp.get('/diary/history')
def history():
    if not _require_login():
        return redirect(url_for('auth.login_page'))

    user = _get_user()
    uid = user.get('line_user_id', '')

    plan_map = load_plan_map()

    all_books: List[str] = []
    seen: set = set()
    for info in plan_map.values():
        b = info.get('book', '').strip()
        if b and b not in seen:
            all_books.append(b)
            seen.add(b)

    selected_book = (request.args.get('book') or '').strip()
    if not selected_book or selected_book not in seen:
        selected_book = all_books[0] if all_books else ''

    book_dates: List[str] = sorted(
        [d for d, info in plan_map.items() if info.get('book', '').strip() == selected_book]
    )

    today_iso = _today_str()
    written_map: Dict[str, str] = {}
    if book_dates and sb:
        res = (
            sb.table('diary_entries')
            .select('entry_date,content')
            .eq('line_user_id', uid)
            .gte('entry_date', book_dates[0])
            .lte('entry_date', book_dates[-1])
            .execute()
        )
        written_map = {r['entry_date']: (r.get('content') or '') for r in (res.data or [])}

    date_items: List[Dict[str, Any]] = []
    for d in book_dates:
        is_future = d > today_iso
        is_written = d in written_map
        plan_info = plan_map.get(d, {})
        date_items.append({
            'date': d,
            'range': plan_info.get('range', ''),
            'is_future': is_future,
            'is_written': is_written,
            'content': written_map.get(d, ''),
        })

    return render_template(
        'diary/history.html',
        display_name=_safe_display_name(user),
        all_books=all_books,
        selected_book=selected_book,
        date_items=date_items,
    )


@diary_bp.get('/diary/guide')
def guide():
    return render_template('diary/guide.html')


@diary_bp.get('/diary/pastor')
def pastor():
    if not _require_login():
        return redirect(url_for('auth.login_page'))

    user = _get_user()
    pastor_uid = user.get('line_user_id', '')
    if not sb_is_pastor(pastor_uid):
        flash('你目前沒有查閱權限（不在白名單）', 'error')
        return redirect(url_for('diary.index'))

    owners = sb_list_authorized_owners_for_pastor(pastor_uid)
    if owners:
        return redirect(url_for('diary.pastor_view', owner_uid=owners[0]['line_user_id']))
    return render_template('diary/pastor.html', display_name=_safe_display_name(user), owners=owners)


@diary_bp.get('/diary/pastor/view/<owner_uid>')
def pastor_view(owner_uid: str):
    if not _require_login():
        return redirect(url_for('auth.login_page'))

    user = _get_user()
    pastor_uid = user.get('line_user_id', '')
    if not sb_is_pastor(pastor_uid):
        flash('你目前沒有查閱權限（不在白名單）', 'error')
        return redirect(url_for('diary.index'))

    if not sb:
        flash('資料庫連線異常', 'error')
        return redirect(url_for('diary.pastor'))

    grants = (
        sb.table('diary_share_grants')
        .select('owner_line_user_id')
        .eq('pastor_line_user_id', pastor_uid)
        .eq('owner_line_user_id', owner_uid)
        .is_('revoked_at', 'null')
        .limit(1)
        .execute()
    )
    if not (grants.data or []):
        flash('你沒有此人的查閱授權', 'error')
        return redirect(url_for('diary.pastor'))

    owner_row = (
        sb.table('users')
        .select('display_name,picture_url,line_user_id')
        .eq('line_user_id', owner_uid)
        .limit(1)
        .execute()
    )
    owner_profile = (owner_row.data or [None])[0] or {'display_name': '（未命名）'}

    d = request.args.get('d') or _today_str()
    try:
        selected = _parse_date(d)
    except Exception:
        selected = _today_tw()
        d = selected.isoformat()

    month_q = request.args.get('month')
    if month_q:
        try:
            cy, cm = _ym_from_month_param(month_q)
        except Exception:
            cy, cm = selected.year, selected.month
    else:
        cy, cm = selected.year, selected.month

    plan = load_plan_map().get(d)
    verses = get_scripture(plan['book'], plan['range']) if plan else []

    try:
        from data.book_background import BOOK_BACKGROUND
        book_bg = BOOK_BACKGROUND.get(plan['book'], '') if plan and plan.get('book') else ''
    except ImportError:
        book_bg = ''

    entry = sb_get_entry(owner_uid, d)
    calendar_days, first_day_offset, prev_month, next_month = _build_calendar(owner_uid, d, cy, cm)

    all_owners = sb_list_authorized_owners_for_pastor(pastor_uid)

    return render_template(
        'diary/pastor_view.html',
        pastor_name=_safe_display_name(user),
        owner_name=owner_profile.get('display_name') or '（未命名）',
        owner_uid=owner_uid,
        entry_date=d,
        plan=plan,
        verses=verses,
        book_bg=book_bg,
        content=(entry.get('content') if entry else '') or '',
        completed=bool(entry and entry.get('locked')),
        calendar_days=calendar_days,
        first_day_offset=first_day_offset,
        calendar_year=cy,
        calendar_month=cm,
        prev_month=prev_month,
        next_month=next_month,
        all_owners=all_owners,
    )


def _plan_stats(plan_map: Dict) -> Dict:
    """計算進度統計摘要。"""
    today = _today_str()
    if not plan_map:
        return {'min_date': None, 'max_date': None, 'total': 0,
                'today_plan': None, 'days_left': None}
    dates = sorted(plan_map.keys())
    max_date = dates[-1]
    today_plan = plan_map.get(today)
    try:
        days_left = (_parse_date(max_date) - _today_tw()).days
    except Exception:
        days_left = None
    return {
        'min_date': dates[0],
        'max_date': max_date,
        'total': len(dates),
        'today_plan': today_plan,
        'days_left': days_left,
    }


@diary_bp.get('/diary/admin')
def admin():
    if not _require_login():
        return redirect(url_for('auth.login_page'))

    user = _get_user()
    uid = user.get('line_user_id', '')
    if not _is_diary_admin(uid):
        flash('你沒有後台權限', 'error')
        return redirect(url_for('diary.index'))

    plan_map = load_plan_map()
    stats    = _plan_stats(plan_map)

    # 顯示最近 90 天（今日前後）的條目，方便快速預覽和編輯
    today = _today_str()
    today_dt = _today_tw()
    show_from = (today_dt - timedelta(days=7)).isoformat()
    show_to   = (today_dt + timedelta(days=90)).isoformat()
    upcoming  = [
        {'date': d, 'book': v['book'], 'range': v['range']}
        for d, v in sorted(plan_map.items())
        if show_from <= d <= show_to
    ]

    pastors   = sb_list_pastors()
    pastor_ids = {p['line_user_id']: True for p in pastors}
    all_users  = sb_list_users(limit=500)
    # 白名單顯示用：合併 real_name
    user_map = {u['line_user_id']: u for u in all_users}

    return render_template(
        'diary/admin.html',
        display_name=_safe_display_name(user),
        stats=stats,
        upcoming=upcoming,
        today=today,
        bible_books=list(BIBLE.keys()),
        pastors=pastors,
        pastor_ids=pastor_ids,
        all_users=all_users,
        user_map=user_map,
    )


@diary_bp.post('/diary/admin/plan/save')
def admin_plan_save():
    """新增或更新單筆進度（KEY IN 用）。"""
    if not _require_login():
        return jsonify({'error': '請先登入'}), 401
    user = _get_user()
    if not _is_diary_admin(user.get('line_user_id', '')):
        return jsonify({'error': '無權限'}), 403

    data  = request.get_json() or {}
    d     = (data.get('date') or '').strip()
    book  = (data.get('book') or '').strip()
    rng   = (data.get('range') or '').strip()
    if not d or not book or not rng:
        return jsonify({'error': '日期、書卷、章節範圍皆必填'}), 400

    try:
        sb.table('diary_plan').upsert(
            {'date': d, 'book': book, 'range': rng, 'updated_at': 'now()'},
            on_conflict='date'
        ).execute()
        _invalidate_plan_cache()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@diary_bp.post('/diary/admin/plan/delete')
def admin_plan_delete():
    """刪除單筆進度。"""
    if not _require_login():
        return jsonify({'error': '請先登入'}), 401
    user = _get_user()
    if not _is_diary_admin(user.get('line_user_id', '')):
        return jsonify({'error': '無權限'}), 403

    data = request.get_json() or {}
    d    = (data.get('date') or '').strip()
    if not d:
        return jsonify({'error': '缺少日期'}), 400
    try:
        sb.table('diary_plan').delete().eq('date', d).execute()
        _invalidate_plan_cache()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@diary_bp.get('/diary/admin/plan/download')
def admin_plan_download():
    """把目前 DB 進度表匯出成 xlsx。"""
    if not _require_login():
        return redirect(url_for('auth.login_page'))
    user = _get_user()
    if not _is_diary_admin(user.get('line_user_id', '')):
        return redirect(url_for('diary.index'))

    import pandas as pd
    plan_map = load_plan_map()
    rows = [{'date': d, 'book': v['book'], 'range': v['range']}
            for d, v in sorted(plan_map.items())]
    df = pd.DataFrame(rows, columns=['date', 'book', 'range'])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='plan')
    buf.seek(0)
    from flask import send_file
    return send_file(buf, as_attachment=True,
                     download_name='diary_plan.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@diary_bp.get('/diary/admin/plan/template')
def admin_plan_template():
    """下載空白範本 xlsx。"""
    if not _require_login():
        return redirect(url_for('auth.login_page'))

    import pandas as pd
    df = pd.DataFrame([
        {'date': '2025-01-01', 'book': '創世記', 'range': '1:1-31'},
        {'date': '2025-01-02', 'book': '創世記', 'range': '2:1-25'},
    ], columns=['date', 'book', 'range'])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='plan')
    buf.seek(0)
    from flask import send_file
    return send_file(buf, as_attachment=True,
                     download_name='diary_plan_template.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@diary_bp.post('/diary/admin/upload_plan')
def admin_upload_plan():
    if not _require_login():
        return redirect(url_for('auth.login_page'))

    user = _get_user()
    uid = user.get('line_user_id', '')
    if not _is_diary_admin(uid):
        flash('你沒有後台權限', 'error')
        return redirect(url_for('diary.index'))

    f = request.files.get('plan_file')
    if not f:
        flash('沒有選擇檔案', 'error')
        return redirect(url_for('diary.admin'))

    try:
        import pandas as pd
        raw = io.BytesIO(f.read())
        # 嘗試讀 'plan' 分頁，失敗則讀第一頁
        try:
            df = pd.read_excel(raw, sheet_name='plan')
        except Exception:
            raw.seek(0)
            df = pd.read_excel(raw)

        required = {'date', 'book', 'range'}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f'缺少欄位：{", ".join(missing)}')

        rows = []
        for _, r in df.iterrows():
            d = str(r['date'])[:10]
            rows.append({'date': d, 'book': str(r['book']).strip(), 'range': str(r['range']).strip()})

        if not rows:
            raise ValueError('檔案內沒有資料列')

        # 批次 upsert 進 DB（每次 200 筆）
        for i in range(0, len(rows), 200):
            sb.table('diary_plan').upsert(rows[i:i+200], on_conflict='date').execute()

        _invalidate_plan_cache()
        flash(f'已匯入 {len(rows)} 筆進度到資料庫', 'ok')
    except Exception as e:
        flash(f'匯入失敗：{e}', 'error')

    return redirect(url_for('diary.admin'))


@diary_bp.post('/diary/admin/update_whitelist')
def admin_update_whitelist():
    if not _require_login():
        return redirect(url_for('auth.login_page'))

    user = _get_user()
    uid = user.get('line_user_id', '')
    if not _is_diary_admin(uid):
        flash('你沒有後台權限', 'error')
        return redirect(url_for('diary.index'))

    target_uid = (request.form.get('target_uid') or '').strip()
    action     = (request.form.get('action') or '').strip()

    if not target_uid or not sb:
        flash('操作失敗', 'error')
        return redirect(url_for('diary.admin'))

    prof = sb.table('users').select('line_user_id,display_name,picture_url')\
        .eq('line_user_id', target_uid).limit(1).execute()
    row = (prof.data or [None])[0]
    if not row:
        flash('找不到該使用者', 'error')
        return redirect(url_for('diary.admin'))

    active = (action != 'remove')
    sb_set_pastor_whitelist(row['line_user_id'], row.get('display_name', ''), row.get('picture_url', ''), active)
    flash('已更新白名單', 'ok')
    return redirect(url_for('diary.admin'))


@diary_bp.get('/diary/stars')
def stars():
    if not _require_login():
        return redirect(url_for('auth.login_page'))

    user = _get_user()
    uid = user.get('line_user_id', '')
    dates = []
    if sb:
        try:
            res = sb.table('diary_entries').select('entry_date').eq('line_user_id', uid).eq('locked', True).execute()
            if res.data:
                dates = sorted([r['entry_date'] for r in res.data if r.get('entry_date')])
        except Exception as e:
            current_app.logger.error(f'[diary.stars] Supabase error: {e}')
    return render_template(
        'diary/stars.html',
        dates=dates,
        count=len(dates),
        display_name=_safe_display_name(user),
    )


# =========================
# AI 路由（/api/diary/...）
# =========================

@diary_bp.get('/api/diary/guide')
def api_guide():
    if not _require_login():
        return jsonify({'error': '未登入'}), 401

    d = request.args.get('d') or _today_str()
    plan = load_plan_map().get(d)
    if not plan:
        return jsonify({'error': '今日無讀經進度'}), 404

    book = plan['book']
    rng = plan['range']
    verses = get_scripture(book, rng)
    if not verses:
        return jsonify({'error': '找不到經文內容'}), 404

    try:
        from data.book_background import BOOK_BACKGROUND
        book_bg = BOOK_BACKGROUND.get(book, '')
    except ImportError:
        book_bg = ''

    scripture_text = '\n'.join(verses)
    parts = []
    if book_bg:
        parts.append(f'【書卷背景】\n{book_bg}')
    parts.append(f'【今日經文】{book} {rng}\n{scripture_text}')

    cache_key = f'{book}|{rng}'
    if cache_key in _GUIDE_CACHE:
        return jsonify({'questions': _GUIDE_CACHE[cache_key]})

    groq_client, gemini_model = _get_ai_clients()
    if not groq_client and not gemini_model:
        return jsonify({'error': 'AI 服務未設定（請設定 GROQ_API_KEY）'}), 503

    system_prompt = (
        '你是一位陪伴信徒靈修的屬靈朋友。'
        '請完全使用繁體中文回答，不可夾雜任何其他語言的文字。'
        '根據下方的經文，提出 2 到 3 個反思問題，幫助讀者在靈修中與神相遇、回應祂的話。'
        '問題必須直接根據這段經文的情境，不能是通用問題。'
        '語言要真誠、溫暖，帶著屬靈的深度，同時貼近日常生活。'
        '只輸出問題本身，每個問題單獨一行，不加編號、符號或任何其他說明。'
    )
    content = '\n\n'.join(parts)

    try:
        raw = _call_ai(groq_client, gemini_model, system_prompt, content, max_tokens=400)
        questions = [q.strip() for q in raw.splitlines() if q.strip()]
        _GUIDE_CACHE[cache_key] = questions
        return jsonify({'questions': questions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@diary_bp.get('/api/diary/passage-intro')
def api_passage_intro():
    if not _require_login():
        return jsonify({'error': '未登入'}), 401

    d = request.args.get('d') or _today_str()
    plan = load_plan_map().get(d)
    if not plan:
        return jsonify({'error': '今日無讀經進度'}), 404

    book = plan['book']
    rng = plan['range']
    verses = get_scripture(book, rng)
    if not verses:
        return jsonify({'error': '找不到經文內容'}), 404

    cache_key = f'{book}|{rng}'
    if cache_key in _INTRO_CACHE:
        return jsonify({'intro': _INTRO_CACHE[cache_key]})

    groq_client, gemini_model = _get_ai_clients()
    if not groq_client and not gemini_model:
        return jsonify({'error': 'AI 服務未設定'}), 503

    scripture_text = '\n'.join(verses[:6])
    system_prompt = (
        '你是一位熟悉聖經的引導者。'
        '請完全使用繁體中文回答，不可夾雜任何其他語言的文字。'
        '根據提供的書卷名稱、章節範圍與經文內容，用一到兩句話簡短說明這段經文的背景與處境。'
        '只輸出那一到兩句話，不加任何標題、編號、符號或額外說明。'
    )
    content = f'書卷：{book}\n章節：{rng}\n\n經文（前幾節）：\n{scripture_text}'

    try:
        raw = _call_ai(groq_client, gemini_model, system_prompt, content, max_tokens=150)
        _INTRO_CACHE[cache_key] = raw
        return jsonify({'intro': raw})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _get_ai_clients():
    """動態取得 AI 客戶端（避免啟動時強制依賴）"""
    groq_client = None
    gemini_model = None

    groq_key = os.environ.get('GROQ_API_KEY', '')
    if groq_key:
        try:
            from groq import Groq
            groq_client = Groq(api_key=groq_key)
        except Exception:
            pass

    if not groq_client:
        gemini_key = os.environ.get('GEMINI_API_KEY', '')
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                gemini_model = genai.GenerativeModel('gemini-2.0-flash')
            except Exception:
                pass

    return groq_client, gemini_model


def _call_ai(groq_client, gemini_model, system_prompt: str, content: str, max_tokens: int = 400) -> str:
    if groq_client:
        resp = groq_client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': content},
            ],
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()
    else:
        resp = gemini_model.generate_content(f'{system_prompt}\n\n{content}')
        return resp.text.strip()
