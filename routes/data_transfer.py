"""
資料匯出 / 匯入 Blueprint
超級管理員功能：將整個教會資料庫打包成 ZIP（JSON 格式），或由 ZIP 還原。
路由前綴：/admin/data
"""
import io
import json
import zipfile
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, send_file, jsonify
)

from db import supabase
from routes.decorators import super_admin_required

data_transfer_bp = Blueprint('data_transfer', __name__)

TAIPEI_TZ = timezone(timedelta(hours=8))
EXPORT_VERSION = '1.0'

# ── 模組定義 ─────────────────────────────────────────────────────────────────

EXPORT_MODULES = {
    'members': {
        'label': '👥 會友資料',
        'tables': ['users', 'user_groups', 'groups', 'group_members'],
        'description': '會友基本資料、分組歸屬（含 LINE ID，建議謹慎保管）',
        'warning': True,
    },
    'cell_groups': {
        'label': '🏠 小組牧養',
        'tables': ['cell_groups', 'cell_members', 'cell_group_leaders',
                   'cell_reports', 'cell_attendance'],
        'description': '小組、成員、組長、每週回報單、出席記錄',
    },
    'events': {
        'label': '📅 活動報名',
        'tables': ['events', 'event_fields', 'registrations',
                   'registration_answers', 'registration_whitelist'],
        'description': '活動、自訂欄位、報名紀錄',
    },
    'courses': {
        'label': '📚 門訓課程',
        'tables': ['course_categories', 'courses', 'course_sessions',
                   'course_enrollments', 'course_certifications',
                   'course_certificates', 'session_attendance'],
        'description': '課程分類、課程、場次、報名、認證記錄',
    },
    'prayer': {
        'label': '🙏 代禱麥田',
        'tables': ['prayers', 'prayer_comments', 'prayer_reactions'],
        'description': '代禱事項、回應、回饋',
    },
    'calendar': {
        'label': '🗓 教會行事曆',
        'tables': ['church_events', 'personal_events'],
        'description': '公共行事、個人私人事項',
        'warning': True,
    },
    'bulletin': {
        'label': '📰 每週週報',
        'tables': ['weekly_bulletins'],
        'description': '週報記錄（不含 PDF 檔案本體）',
    },
    'gospel': {
        'label': '✝️ 福音探索',
        'tables': ['gospel_cards', 'gospel_form_questions', 'gospel_inquiries'],
        'description': '福音卡、問卷題目、詢問記錄',
    },
    'meeting_reports': {
        'label': '📊 聚會人數',
        'tables': ['sunday_reports', 'children_sunday_reports',
                   'prayer_reports', 'morning_prayer_reports',
                   'custom_meeting_reports'],
        'description': '各場聚會出席人數歷史統計',
    },
    'settings': {
        'label': '⚙️ 系統設定',
        'tables': ['settings', 'portal_card_settings', 'portal_links'],
        'description': '聚會設定、門戶卡片、快捷連結',
    },
    'attendance_mgmt': {
        'label': '🕐 差勤管理',
        'tables': ['staff_profiles', 'leave_requests', 'overtime_records',
                   'materials', 'material_stock', 'material_transactions'],
        'description': '全職同工差勤、特休、物資管理',
    },
}

# 不開放匯出的私密資料表
EXCLUDED_TABLES = {
    'diary_entries', 'diary_plan', 'diary_share_grants',
    'verse_custom_themes', 'daily_verse_draws', 'daily_verses',
    'notifications', 'visitor_forms', 'files', 'folders',
}


# ── 輔助函式 ──────────────────────────────────────────────────────────────────

def _fetch_all(table_name: str) -> list:
    """分頁讀取整張表（Supabase 每次最多 1000 筆）。"""
    rows = []
    page_size = 1000
    offset = 0
    while True:
        try:
            res = supabase.table(table_name).select('*')\
                .range(offset, offset + page_size - 1).execute()
            batch = res.data or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        except Exception:
            break
    return rows


def _upsert_batch(table_name: str, records: list) -> tuple[int, str | None]:
    """批次 upsert，每批 200 筆，回傳 (成功筆數, 錯誤訊息)。"""
    if not records:
        return 0, None
    total = 0
    chunk_size = 200
    for i in range(0, len(records), chunk_size):
        chunk = records[i:i + chunk_size]
        try:
            supabase.table(table_name).upsert(chunk, on_conflict='id').execute()
            total += len(chunk)
        except Exception as e:
            return total, str(e)
    return total, None


def _json_default(obj):
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    raise TypeError(f'Not serializable: {type(obj)}')


# ── 匯出 ──────────────────────────────────────────────────────────────────────

@data_transfer_bp.get('/admin/data-export')
@super_admin_required
def data_export():
    return render_template('admin/data_export.html', modules=EXPORT_MODULES)


@data_transfer_bp.post('/admin/data-export/download')
@super_admin_required
def data_export_download():
    selected = request.form.getlist('modules')
    if not selected:
        flash('請至少選擇一個模組', 'error')
        return redirect(url_for('data_transfer.data_export'))

    # 驗證選取模組合法
    selected = [m for m in selected if m in EXPORT_MODULES]

    buf = io.BytesIO()
    table_stats = {}

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        exported_tables = set()

        for module_key in selected:
            for table in EXPORT_MODULES[module_key]['tables']:
                if table in exported_tables or table in EXCLUDED_TABLES:
                    continue
                rows = _fetch_all(table)
                table_stats[table] = len(rows)
                zf.writestr(
                    f'{table}.json',
                    json.dumps(rows, ensure_ascii=False, indent=2, default=_json_default)
                )
                exported_tables.add(table)

        meta = {
            'version': EXPORT_VERSION,
            'exported_at': datetime.now(TAIPEI_TZ).isoformat(),
            'church_name': '',
            'modules': selected,
            'tables': table_stats,
            'note': '使用本系統 /admin/data-import 還原。僅適用於全新 Supabase 專案。',
        }
        zf.writestr('export_meta.json',
                    json.dumps(meta, ensure_ascii=False, indent=2))

    buf.seek(0)
    ts = datetime.now(TAIPEI_TZ).strftime('%Y%m%d_%H%M')
    filename = f'church_export_{ts}.zip'
    return send_file(
        buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=filename,
    )


# ── 匯入 ──────────────────────────────────────────────────────────────────────

@data_transfer_bp.get('/admin/data-import')
@super_admin_required
def data_import():
    return render_template('admin/data_import.html')


@data_transfer_bp.post('/admin/data-import/preview')
@super_admin_required
def data_import_preview():
    """讀取 ZIP 並回傳預覽 JSON（各表筆數），不寫入資料庫。"""
    f = request.files.get('file')
    if not f or not f.filename.endswith('.zip'):
        return jsonify({'error': '請上傳 .zip 檔案'}), 400

    try:
        with zipfile.ZipFile(f, 'r') as zf:
            names = zf.namelist()
            if 'export_meta.json' not in names:
                return jsonify({'error': '檔案格式不符，缺少 export_meta.json'}), 400

            meta = json.loads(zf.read('export_meta.json'))

            tables_preview = []
            for name in names:
                if name == 'export_meta.json':
                    continue
                table = name.replace('.json', '')
                if table in EXCLUDED_TABLES:
                    continue
                try:
                    records = json.loads(zf.read(name))
                    tables_preview.append({'table': table, 'count': len(records)})
                except Exception:
                    tables_preview.append({'table': table, 'count': '?', 'error': '解析失敗'})

        return jsonify({'meta': meta, 'tables': tables_preview})
    except zipfile.BadZipFile:
        return jsonify({'error': '無效的 ZIP 檔案'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@data_transfer_bp.post('/admin/data-import/execute')
@super_admin_required
def data_import_execute():
    """實際寫入資料庫，回傳各表結果。"""
    f = request.files.get('file')
    if not f or not f.filename.endswith('.zip'):
        return jsonify({'error': '請上傳 .zip 檔案'}), 400

    # 二次確認
    confirm = request.form.get('confirm')
    if confirm != 'IMPORT':
        return jsonify({'error': '請輸入確認字串 IMPORT'}), 400

    results = []
    try:
        with zipfile.ZipFile(f, 'r') as zf:
            names = zf.namelist()
            if 'export_meta.json' not in names:
                return jsonify({'error': '檔案格式不符'}), 400

            meta = json.loads(zf.read('export_meta.json'))

            # 依照外鍵相依順序處理
            TABLE_ORDER = [
                'users', 'user_groups', 'groups', 'group_members',
                'settings', 'portal_card_settings', 'portal_links',
                'events', 'event_fields', 'registrations',
                'registration_answers', 'registration_whitelist',
                'course_categories', 'courses', 'course_sessions',
                'course_enrollments', 'course_certifications',
                'course_certificates', 'session_attendance',
                'cell_groups', 'cell_members', 'cell_group_leaders',
                'cell_reports', 'cell_attendance',
                'prayers', 'prayer_comments', 'prayer_reactions',
                'church_events', 'personal_events',
                'weekly_bulletins',
                'gospel_cards', 'gospel_form_questions', 'gospel_inquiries',
                'sunday_reports', 'children_sunday_reports',
                'prayer_reports', 'morning_prayer_reports',
                'custom_meeting_reports',
                'staff_profiles', 'leave_requests', 'overtime_records',
                'materials', 'material_stock', 'material_transactions',
            ]

            file_map = {n.replace('.json', ''): n
                        for n in names if n.endswith('.json') and n != 'export_meta.json'}

            # 先按 TABLE_ORDER 插入，剩餘未列的按檔名順序
            ordered = [t for t in TABLE_ORDER if t in file_map]
            remaining = [t for t in file_map if t not in ordered]
            process_order = ordered + remaining

            for table in process_order:
                if table in EXCLUDED_TABLES:
                    continue
                records = json.loads(zf.read(file_map[table]))
                count, err = _upsert_batch(table, records)
                results.append({
                    'table': table,
                    'total': len(records),
                    'imported': count,
                    'error': err,
                })

        return jsonify({'success': True, 'meta': meta, 'results': results})
    except zipfile.BadZipFile:
        return jsonify({'error': '無效的 ZIP 檔案'}), 400
    except Exception as e:
        return jsonify({'error': str(e), 'results': results}), 500
