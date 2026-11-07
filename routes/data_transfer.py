"""
資料匯出 / 匯入 Blueprint
超級管理員功能：將整個教會資料庫打包成 ZIP（JSON 格式），或由 ZIP 還原。
路由前綴：/admin/data

備份哪些表、匯入的順序、upsert 的衝突欄位，全部由 `backup_registry.py` 決定（單一來源）。
"""
import io
import json
import zipfile
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, send_file, jsonify
)

import backup_registry as reg
from db import supabase
from routes.audit import log_action
from routes.decorators import super_admin_required

data_transfer_bp = Blueprint('data_transfer', __name__)

TAIPEI_TZ = timezone(timedelta(hours=8))
EXPORT_VERSION = '1.1'

# 匯出頁面用的模組清單（由登記表產生；順序＝匯入順序）
EXPORT_MODULES = reg.export_modules()
EXCLUDED_TABLES = set(reg.EXCLUDED) | set(reg.VIEWS)


class ExportError(Exception):
    """匯出中止（資料庫讀取失敗）。寧可明講失敗，也不要產出一份「看起來完整」的殘缺備份。"""


# ── 輔助函式 ──────────────────────────────────────────────────────────────────

def _fetch_all(table_name: str) -> list:
    """分頁讀取整張表（Supabase 每次最多 1000 筆）。

    資料表不存在 → 回傳 None（呼叫端記成「尚未建立」）；
    其他任何失敗（網路、權限）→ 丟 ExportError，**不可以靜靜回傳讀到一半的資料**。
    """
    rows = []
    page_size = 1000
    offset = 0
    while True:
        try:
            res = supabase.table(table_name).select('*')\
                .range(offset, offset + page_size - 1).execute()
        except Exception as e:
            if reg.is_missing_table(e):
                return None
            raise ExportError(f'讀取 {table_name} 失敗：{str(e)[:160]}') from e
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        offset += page_size


def _upsert_batch(table_name: str, records: list) -> tuple[int, str | None]:
    """批次 upsert，每批 200 筆，回傳 (成功筆數, 錯誤訊息)。衝突欄位以登記表為準。"""
    if not records:
        return 0, None
    total = 0
    chunk_size = 200
    conflict = reg.CONFLICT[table_name]
    for i in range(0, len(records), chunk_size):
        chunk = records[i:i + chunk_size]
        try:
            supabase.table(table_name).upsert(chunk, on_conflict=conflict).execute()
            total += len(chunk)
        except Exception as e:
            return total, str(e)
    return total, None


def _json_default(obj):
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    raise TypeError(f'Not serializable: {type(obj)}')


def build_export(selected: list, fetch=None):
    """把選取的模組打包成 ZIP。回傳 (zip 位元組, meta)。讀取失敗丟 ExportError。"""
    fetch = fetch or _fetch_all
    selected = [m for m in selected if m in EXPORT_MODULES]
    buf = io.BytesIO()
    table_stats, not_available = {}, []

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for module_key in selected:
            for table in EXPORT_MODULES[module_key]['tables']:
                if table in table_stats or table in not_available:
                    continue
                rows = fetch(table)
                if rows is None:
                    not_available.append(table)
                    continue
                table_stats[table] = len(rows)
                zf.writestr(f'{table}.json',
                            json.dumps(rows, ensure_ascii=False, indent=2, default=_json_default))

        meta = {
            'version': EXPORT_VERSION,
            'exported_at': datetime.now(TAIPEI_TZ).isoformat(),
            'church_name': '',
            'modules': selected,
            'tables': table_stats,
            'not_available': not_available,       # 資料表還不存在（那個模組的 migration 沒跑）
            'excluded': reg.EXCLUDED,             # 刻意不備份的表與理由
            'note': '使用本系統 /admin/data-import 還原。僅適用於全新 Supabase 專案。',
        }
        zf.writestr('export_meta.json', json.dumps(meta, ensure_ascii=False, indent=2))
    return buf.getvalue(), meta


def import_bundle(zf, upsert=None):
    """依登記表的順序匯入。只匯入登記表裡的資料表；其餘檔案一律略過並回報（不信任 ZIP 裡的檔名）。"""
    upsert = upsert or _upsert_batch
    names = zf.namelist()
    file_map = {n[:-5]: n for n in names if n.endswith('.json') and n != 'export_meta.json'}
    results = []
    for table in reg.TABLE_NAMES:                       # 登記表的順序＝外鍵安全的順序
        if table not in file_map:
            continue
        records = json.loads(zf.read(file_map[table]))
        count, err = upsert(table, records)
        results.append({'table': table, 'total': len(records), 'imported': count, 'error': err})
    # 匯入會直接改 settings／首頁磁磚／快捷連結那幾張被快取的表，整份快取一起清掉（匯入很少發生）
    from routes import cache
    cache.clear()
    for table in file_map:
        if table not in reg.CONFLICT:
            why = reg.EXCLUDED.get(table) or ('檢視表，不匯入' if table in reg.VIEWS else '不在備份登記表裡')
            results.append({'table': table, 'total': 0, 'imported': 0, 'error': None, 'skipped': why})
    return results


# ── 匯出 ──────────────────────────────────────────────────────────────────────

@data_transfer_bp.get('/admin/data-export')
@super_admin_required
def data_export():
    return render_template('admin/data_export.html', modules=EXPORT_MODULES, excluded=reg.EXCLUDED)


@data_transfer_bp.post('/admin/data-export/download')
@super_admin_required
def data_export_download():
    selected = [m for m in request.form.getlist('modules') if m in EXPORT_MODULES]
    if not selected:
        flash('請至少選擇一個模組', 'error')
        return redirect(url_for('data_transfer.data_export'))

    try:
        data, meta = build_export(selected)
    except ExportError as e:
        flash(f'匯出失敗，沒有產生任何檔案：{e}', 'error')
        return redirect(url_for('data_transfer.data_export'))

    log_action('data.export', target_type='data_export', detail={
        'modules': selected, 'tables': len(meta['tables']), 'not_available': meta['not_available'] or None})
    ts = datetime.now(TAIPEI_TZ).strftime('%Y%m%d_%H%M')
    return send_file(io.BytesIO(data), mimetype='application/zip', as_attachment=True,
                     download_name=f'church_export_{ts}.zip')


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
                if table not in reg.CONFLICT:           # 不在登記表（含排除的、檢視表）的不會被匯入
                    continue
                try:
                    records = json.loads(zf.read(name))
                    tables_preview.append({'table': table, 'count': len(records)})
                except Exception:
                    tables_preview.append({'table': table, 'count': '?', 'error': '解析失敗'})

        return jsonify({'meta': meta, 'tables': tables_preview})
    except zipfile.BadZipFile:
        return jsonify({'error': '無效的 ZIP 檔案'}), 400
    except Exception:
        return jsonify({'error': '預覽失敗，請確認檔案是由本系統匯出的'}), 500


@data_transfer_bp.post('/admin/data-import/execute')
@super_admin_required
def data_import_execute():
    """實際寫入資料庫，回傳各表結果。"""
    f = request.files.get('file')
    if not f or not f.filename.endswith('.zip'):
        return jsonify({'error': '請上傳 .zip 檔案'}), 400

    # 二次確認
    if request.form.get('confirm') != 'IMPORT':
        return jsonify({'error': '請輸入確認字串 IMPORT'}), 400

    results = []
    try:
        with zipfile.ZipFile(f, 'r') as zf:
            if 'export_meta.json' not in zf.namelist():
                return jsonify({'error': '檔案格式不符'}), 400
            meta = json.loads(zf.read('export_meta.json'))
            results = import_bundle(zf)
    except zipfile.BadZipFile:
        return jsonify({'error': '無效的 ZIP 檔案'}), 400
    except Exception:
        return jsonify({'error': '匯入中斷，請確認檔案是由本系統匯出的', 'results': results}), 500

    log_action('data.import', target_type='data_import', detail={
        'tables': len([r for r in results if not r.get('skipped')]),
        'errors': [r['table'] for r in results if r.get('error')] or None})
    return jsonify({'success': True, 'meta': meta, 'results': results})
