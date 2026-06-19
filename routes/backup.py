"""
數位遺囑備份模塊（Digital Will Backup）
========================================
目標：即使系統完全停擺，負責同工能在一週內取出所有核心資料並理解系統架構。

提供三項能力：
  1. /admin/backup            統一匯出中心（各分類獨立 CSV + 全部打包 ZIP）
  2. /admin/backup/html       單一靜態 HTML 離線閱讀器（純 HTML+CSS 分頁，無 JS 依賴）
  3. HANDOVER.md（專案根目錄）  系統交接說明文件

設計原則：
  - 所有匯出功能限管理員存取（@admin_required）。
  - 若某模組資料表尚未建立（Supabase 回傳例外），略過並標註「尚未啟用」。
  - 不依賴、不改動任何現有功能；資料一律唯讀。
  - CSV 以 UTF-8 BOM 輸出，確保 Excel 正確顯示中文。
"""
import io
import csv
import html
import json
import zipfile
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

from flask import Blueprint, render_template, Response, send_file

from db import supabase
from routes.decorators import admin_required

backup_bp = Blueprint('backup', __name__, url_prefix='/admin/backup')

_TW = timezone(timedelta(hours=8))


# ── 共用輔助 ──────────────────────────────────────────────────────────────────

def _fetch(table: str):
    """分頁讀取整張表。
    回傳 list（可能為空）。若資料表不存在或查詢失敗 → 回傳 None（代表「尚未啟用」）。
    """
    rows = []
    page = 1000
    offset = 0
    try:
        while True:
            res = supabase.table(table).select('*')\
                .range(offset, offset + page - 1).execute()
            batch = res.data or []
            rows.extend(batch)
            if len(batch) < page:
                break
            offset += page
        return rows
    except Exception:
        return None


def _users_map() -> dict:
    """{ user_id: user_row }，用於把外鍵還原成可讀姓名。"""
    users = _fetch('users') or []
    return {u['id']: u for u in users}


def _user_name(user_map: dict, uid) -> str:
    u = user_map.get(uid) or {}
    return u.get('real_name') or u.get('display_name') or ''


def _fmt_dt(s, fmt='%Y-%m-%d %H:%M') -> str:
    """ISO 字串 → 台灣時間字串。"""
    if not s:
        return ''
    try:
        s = str(s)
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone(_TW)
        return dt.strftime(fmt)
    except Exception:
        return str(s)[:16].replace('T', ' ')


def _yn(v) -> str:
    return '是' if v else '否'


_STATUS_LABEL = {'pending': '待審核', 'approved': '已核准', 'rejected': '已駁回'}
_LEAVE_TYPE_LABEL = {
    'annual': '特休', 'comp': '補休', 'personal': '事假',
    'sick': '病假', 'other': '其他',
}
_PRAYER_CAT_LABEL = {
    'health': '健康', 'family': '家庭', 'work': '工作',
    'spiritual': '屬靈', 'other': '其他',
}


# ── 各分類資料建構器 ──────────────────────────────────────────────────────────
# 每個建構器回傳：
#   {'available': True, 'headers': [...], 'rows': [[...], ...]}
#   或 {'available': False}（資料表尚未建立）

def _build_members():
    users = _fetch('users')
    if users is None:
        return {'available': False}
    headers = ['真實姓名', 'LINE 暱稱', '身分別', '服事標籤', '管理員',
               '超級管理員', '牧者', '同工', '已封鎖', 'LINE User ID', '加入時間']
    rows = []
    for u in sorted(users, key=lambda x: (x.get('real_name') or '')):
        tags = u.get('group_tags') or []
        rows.append([
            u.get('real_name') or '',
            u.get('display_name') or '',
            '會友' if (u.get('member_type') or 'visitor') == 'member' else '訪客',
            '、'.join(tags) if isinstance(tags, list) else str(tags),
            _yn(u.get('is_admin')),
            _yn(u.get('is_super_admin')),
            _yn(u.get('is_pastor')),
            _yn(u.get('is_staff')),
            _yn(u.get('is_blocked')),
            u.get('line_user_id') or '',
            _fmt_dt(u.get('created_at')),
        ])
    return {'available': True, 'headers': headers, 'rows': rows}


def _build_cell_reports():
    reports = _fetch('cell_reports')
    if reports is None:
        return {'available': False}
    groups = _fetch('cell_groups') or []
    gmap = {g['id']: g.get('name') or '' for g in groups}
    headers = ['小組', '週日期', '出席人數', '是否聚會', '未聚會原因',
               '屬靈狀況', '屬靈備註', '家庭狀況', '家庭備註',
               '工作狀況', '工作備註', '健康狀況', '健康備註',
               '整體狀況', '同工建議', '新人', '更新時間']
    rows = []
    for r in sorted(reports, key=lambda x: (x.get('week_date') or ''), reverse=True):
        rows.append([
            gmap.get(r.get('group_id'), r.get('group_id') or ''),
            r.get('week_date') or '',
            r.get('attendance_count') if r.get('attendance_count') is not None else '',
            '否' if r.get('no_meeting') else '是',
            r.get('no_meeting_reason') or '',
            r.get('spiritual_status') or '',
            r.get('spiritual_note') or '',
            r.get('family_status') or '',
            r.get('family_note') or '',
            r.get('work_status') or '',
            r.get('work_note') or '',
            r.get('health_status') or '',
            r.get('health_note') or '',
            r.get('group_status') or '',
            r.get('coworker_suggestion') or '',
            r.get('newcomer_raw') or '',
            _fmt_dt(r.get('updated_at')),
        ])
    return {'available': True, 'headers': headers, 'rows': rows}


def _build_events():
    regs = _fetch('registrations')
    if regs is None:
        return {'available': False}
    events = _fetch('events') or []
    emap = {e['id']: e for e in events}
    umap = _users_map()
    _STATUS = {'registered': '已報名', 'waitlisted': '候補',
               'cancelled': '已取消', 'walk_in': '現場報名'}
    headers = ['活動名稱', '活動時間', '報名者', '聯絡電話', '狀態',
               '是否簽到', '簽到時間', '付款狀態', '報名來源', '報名時間']
    rows = []

    def _sort_key(r):
        ev = emap.get(r.get('event_id')) or {}
        return (ev.get('event_start') or '', r.get('created_at') or '')

    for r in sorted(regs, key=_sort_key, reverse=True):
        ev = emap.get(r.get('event_id')) or {}
        name = _user_name(umap, r.get('user_id')) or r.get('guest_name') or '外部來賓'
        rows.append([
            ev.get('title') or '（活動已刪除）',
            _fmt_dt(ev.get('event_start')),
            name,
            r.get('guest_phone') or '',
            _STATUS.get(r.get('status'), r.get('status') or ''),
            _yn(r.get('checked_in')),
            _fmt_dt(r.get('checked_in_at')),
            r.get('payment_status') or '',
            r.get('source') or '',
            _fmt_dt(r.get('created_at')),
        ])
    return {'available': True, 'headers': headers, 'rows': rows}


def _build_prayer():
    prayers = _fetch('prayers')
    if prayers is None:
        return {'available': False}
    umap = _users_map()
    _STATUS = {'active': '進行中', 'answered': '已蒙應允', 'archived': '已封存'}
    headers = ['標題', '內容', '分類', '發起人', '狀態', '回應數', '代禱數', '建立時間']
    rows = []
    for p in sorted(prayers, key=lambda x: (x.get('created_at') or ''), reverse=True):
        author = '（匿名）' if p.get('is_anonymous') else _user_name(umap, p.get('user_id'))
        rows.append([
            p.get('title') or '',
            p.get('content') or '',
            _PRAYER_CAT_LABEL.get(p.get('category'), p.get('category') or ''),
            author,
            _STATUS.get(p.get('status'), p.get('status') or ''),
            p.get('reaction_count') if p.get('reaction_count') is not None else '',
            p.get('comment_count') if p.get('comment_count') is not None else '',
            _fmt_dt(p.get('created_at')),
        ])
    return {'available': True, 'headers': headers, 'rows': rows}


def _build_gospel():
    inquiries = _fetch('gospel_inquiries')
    if inquiries is None:
        return {'available': False}
    headers = ['姓名', '聯絡方式', '訊息', '額外回答', '狀態', '負責人', '備註', '建立時間']
    rows = []
    for g in sorted(inquiries, key=lambda x: (x.get('created_at') or ''), reverse=True):
        extra = g.get('extra_answers')
        if isinstance(extra, (dict, list)):
            extra_str = json.dumps(extra, ensure_ascii=False)
        else:
            extra_str = extra or ''
        rows.append([
            g.get('name') or '',
            g.get('contact') or '',
            g.get('message') or '',
            extra_str,
            g.get('status') or '',
            g.get('assigned_to') or '',
            g.get('notes') or '',
            _fmt_dt(g.get('created_at')),
        ])
    return {'available': True, 'headers': headers, 'rows': rows}


def _build_attendance():
    leaves = _fetch('leave_requests')
    overtime = _fetch('overtime_records')
    if leaves is None and overtime is None:
        return {'available': False}
    umap = _users_map()
    headers = ['類型', '同工', '假別', '開始日', '結束日', '時數',
               '原因', '狀態', '審核者', '審核時間']
    rows = []
    for lv in (leaves or []):
        rows.append([
            '請假',
            _user_name(umap, lv.get('user_id')),
            _LEAVE_TYPE_LABEL.get(lv.get('leave_type'), lv.get('leave_type') or ''),
            lv.get('start_date') or '',
            lv.get('end_date') or '',
            lv.get('hours') if lv.get('hours') is not None else '',
            lv.get('reason') or '',
            _STATUS_LABEL.get(lv.get('status'), lv.get('status') or ''),
            _user_name(umap, lv.get('reviewed_by')),
            _fmt_dt(lv.get('reviewed_at')),
        ])
    for ot in (overtime or []):
        rows.append([
            '加班',
            _user_name(umap, ot.get('user_id')),
            '—',
            ot.get('date') or '',
            ot.get('date') or '',
            ot.get('hours') if ot.get('hours') is not None else '',
            ot.get('reason') or '',
            _STATUS_LABEL.get(ot.get('status'), ot.get('status') or ''),
            _user_name(umap, ot.get('reviewed_by')),
            _fmt_dt(ot.get('reviewed_at')),
        ])
    return {'available': True, 'headers': headers, 'rows': rows}


# 分類註冊表（決定頁面按鈕、CSV 檔名、HTML 分頁順序）
CATEGORIES = {
    'cell_reports': {'label': '小組回報記錄', 'icon': '🏠',
                     'filename': 'cell-reports.csv', 'builder': _build_cell_reports},
    'events':       {'label': '活動報名與簽到記錄', 'icon': '🎉',
                     'filename': 'event-registrations.csv', 'builder': _build_events},
    'prayer':       {'label': '代禱事項清單', 'icon': '🙏',
                     'filename': 'prayers.csv', 'builder': _build_prayer},
    'gospel':       {'label': '福音探索記錄', 'icon': '✝️',
                     'filename': 'gospel-inquiries.csv', 'builder': _build_gospel},
    'attendance':   {'label': '差勤記錄', 'icon': '🕐',
                     'filename': 'attendance.csv', 'builder': _build_attendance},
    'members':      {'label': '成員 / 使用者清單', 'icon': '👥',
                     'filename': 'members.csv', 'builder': _build_members},
}


# ── CSV 產生 ──────────────────────────────────────────────────────────────────

def _csv_bytes(headers, rows) -> bytes:
    buf = io.StringIO()
    buf.write('﻿')  # UTF-8 BOM，讓 Excel 正確辨識中文
    writer = csv.writer(buf)
    writer.writerow(headers)
    for r in rows:
        writer.writerow(['' if c is None else c for c in r])
    return buf.getvalue().encode('utf-8')


def _csv_attachment(data: bytes, filename: str) -> Response:
    return Response(
        data,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# ── 路由 ──────────────────────────────────────────────────────────────────────

@backup_bp.get('/')
@admin_required
def index():
    """統一匯出中心頁面。先探測各模組是否啟用、各有幾筆。"""
    overview = []
    for key, meta in CATEGORIES.items():
        result = meta['builder']()
        overview.append({
            'key': key,
            'label': meta['label'],
            'icon': meta['icon'],
            'available': result.get('available', False),
            'count': len(result.get('rows', [])) if result.get('available') else 0,
        })
    return render_template('admin/backup.html', overview=overview)


@backup_bp.get('/export/<category>')
@admin_required
def export_category(category):
    """單一分類 CSV 下載。"""
    meta = CATEGORIES.get(category)
    if not meta:
        return '未知的匯出分類', 404
    result = meta['builder']()
    if not result.get('available'):
        return f"「{meta['label']}」模組尚未啟用，無資料可匯出。", 404
    data = _csv_bytes(result['headers'], result['rows'])
    return _csv_attachment(data, meta['filename'])


@backup_bp.get('/export-all')
@admin_required
def export_all():
    """全部打包成 church-admin-backup-YYYYMMDD.zip。"""
    buf = io.BytesIO()
    summary_lines = [
        '整合型教會行政系統 — 資料備份包',
        f'匯出時間：{datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")} (台灣時間)',
        '',
        '本壓縮檔包含以下 CSV（UTF-8 BOM，可直接用 Excel 開啟）：',
        '',
    ]
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for key, meta in CATEGORIES.items():
            result = meta['builder']()
            if not result.get('available'):
                summary_lines.append(f'  ✗ {meta["label"]}：尚未啟用（略過）')
                continue
            data = _csv_bytes(result['headers'], result['rows'])
            zf.writestr(meta['filename'], data)
            summary_lines.append(f'  ✓ {meta["label"]}：{len(result["rows"])} 筆 → {meta["filename"]}')
        summary_lines += [
            '',
            '若需可離線閱讀的完整快照，請於後台「資料備份中心」下載 HTML 離線閱讀器。',
            '系統交接說明請參閱專案根目錄的 HANDOVER.md。',
        ]
        zf.writestr('README.txt', '\n'.join(summary_lines).encode('utf-8'))

    buf.seek(0)
    filename = f'church-admin-backup-{datetime.now(_TW).strftime("%Y%m%d")}.zip'
    return send_file(buf, mimetype='application/zip',
                     as_attachment=True, download_name=filename)


# ── HTML 離線閱讀器 ───────────────────────────────────────────────────────────

def _render_table_html(result) -> str:
    if not result.get('available'):
        return ('<div class="notice">⚠️ 此模組尚未啟用（對應資料表尚未建立），無資料快照。</div>')
    headers = result['headers']
    rows = result['rows']
    if not rows:
        return '<div class="notice">（目前沒有任何資料）</div>'
    parts = ['<div class="meta">共 ', str(len(rows)), ' 筆</div>',
             '<div class="table-wrap"><table><thead><tr>']
    for h in headers:
        parts.append(f'<th>{html.escape(str(h))}</th>')
    parts.append('</tr></thead><tbody>')
    for row in rows:
        parts.append('<tr>')
        for cell in row:
            parts.append(f'<td>{html.escape("" if cell is None else str(cell))}</td>')
        parts.append('</tr>')
    parts.append('</tbody></table></div>')
    return ''.join(parts)


def _build_offline_html() -> str:
    now_str = datetime.now(_TW).strftime('%Y-%m-%d %H:%M:%S')
    keys = list(CATEGORIES.keys())

    radios, labels, panels = [], [], []
    for i, key in enumerate(keys):
        meta = CATEGORIES[key]
        result = meta['builder']()
        checked = ' checked' if i == 0 else ''
        status_dot = '' if result.get('available') else ' <span class="off">尚未啟用</span>'
        radios.append(f'<input type="radio" name="tabs" id="tab-{key}"{checked}>')
        labels.append(
            f'<label for="tab-{key}" class="tab-label">'
            f'{meta["icon"]} {html.escape(meta["label"])}{status_dot}</label>'
        )
        panels.append(
            f'<section class="panel" id="panel-{key}">'
            f'<h2>{meta["icon"]} {html.escape(meta["label"])}</h2>'
            f'{_render_table_html(result)}</section>'
        )

    # 純 CSS 分頁：radio:checked 控制對應 panel 的顯示與 label 高亮
    tab_css = '\n'.join(
        f'#tab-{k}:checked ~ .tabs label[for="tab-{k}"]{{background:#06C755;color:#fff;}}\n'
        f'#tab-{k}:checked ~ .panels #panel-{k}{{display:block;}}'
        for k in keys
    )

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>教會行政系統 — 離線資料快照 {now_str}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft JhengHei", sans-serif;
         margin:0; background:#f5f6f8; color:#1a1a1a; line-height:1.5; }}
  header {{ background:#0f2027; color:#fff; padding:24px 20px; }}
  header h1 {{ margin:0 0 6px; font-size:1.3rem; }}
  header p {{ margin:0; font-size:.85rem; color:#9fb3c8; }}
  .wrap {{ max-width:1200px; margin:0 auto; padding:20px; }}
  .intro {{ background:#fff8e1; border-left:4px solid #f59e0b; padding:12px 16px;
            border-radius:8px; font-size:.85rem; color:#78350f; margin-bottom:20px; }}
  /* 隱藏 radio 本體 */
  input[name="tabs"] {{ position:absolute; opacity:0; pointer-events:none; }}
  .tabs {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }}
  .tab-label {{ display:inline-block; padding:8px 14px; background:#fff; border:1px solid #ddd;
               border-radius:20px; font-size:.85rem; cursor:pointer; user-select:none; }}
  .off {{ font-size:.7rem; background:#9ca3af; color:#fff; border-radius:6px;
          padding:1px 6px; margin-left:4px; }}
  .panel {{ display:none; background:#fff; border-radius:12px; padding:20px;
            box-shadow:0 1px 4px rgba(0,0,0,.06); }}
  .panel h2 {{ margin:0 0 12px; font-size:1.1rem; }}
  .meta {{ font-size:.8rem; color:#888; margin-bottom:10px; }}
  .notice {{ padding:16px; background:#f3f4f6; border-radius:8px; color:#666; font-size:.9rem; }}
  .table-wrap {{ overflow-x:auto; }}
  table {{ border-collapse:collapse; width:100%; font-size:.82rem; }}
  th, td {{ border:1px solid #e5e7eb; padding:6px 10px; text-align:left;
            vertical-align:top; white-space:pre-wrap; word-break:break-word; }}
  th {{ background:#f0fdf4; font-weight:700; position:sticky; top:0; }}
  tbody tr:nth-child(even) {{ background:#fafafa; }}
  footer {{ text-align:center; color:#999; font-size:.78rem; padding:30px 20px; }}
{tab_css}
</style>
</head>
<body>
<header>
  <h1>⛪ 整合型教會行政系統 — 離線資料快照</h1>
  <p>產生時間：{now_str}（台灣時間）｜本檔為單一靜態 HTML，可離線開啟、長期保存</p>
</header>
<div class="wrap">
  <div class="intro">
    本檔案是系統資料的唯讀快照，供緊急交接或離線查閱使用。資料即時性以產生時間為準；
    最新資料請至線上系統查看。完整交接說明請參閱專案的 <strong>HANDOVER.md</strong>。
  </div>
  {''.join(radios)}
  <div class="tabs">{''.join(labels)}</div>
  <div class="panels">{''.join(panels)}</div>
</div>
<footer>整合型教會行政系統 · 數位遺囑備份模塊產生</footer>
</body>
</html>"""


@backup_bp.get('/html')
@admin_required
def offline_html():
    """產生單一靜態 HTML 離線閱讀器並下載。"""
    content = _build_offline_html()
    filename = f'church-backup-{datetime.now(_TW).strftime("%Y%m%d")}.html'
    return Response(
        content.encode('utf-8'),
        mimetype='text/html; charset=utf-8',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
