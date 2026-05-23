import json
import os
from flask import Blueprint, session, jsonify, render_template
from db import supabase
from routes.decorators import login_required, super_admin_required

changelog_bp = Blueprint('changelog', __name__)

_CHANGELOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'changelogs.json')


def load_changelogs():
    try:
        with open(_CHANGELOG_PATH, encoding='utf-8') as f:
            logs = json.load(f)
        return sorted(logs, key=lambda x: x['published_at'], reverse=True)
    except Exception:
        return []


def get_unread_changelog(last_seen_at: str | None):
    """回傳最新一筆 changelog，若比 last_seen_at 還新則回傳，否則 None"""
    logs = load_changelogs()
    if not logs:
        return None
    latest = logs[0]
    if not last_seen_at:
        return latest
    if latest['published_at'] > last_seen_at[:10]:
        return latest
    return None


def _save_changelogs(logs):
    with open(_CHANGELOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def _enrich(logs):
    """為每筆 log 補上 id（用於前端操作）與 is_published 欄位"""
    from datetime import date as _date
    today = str(_date.today())
    for i, log in enumerate(logs):
        if 'id' not in log:
            log['id'] = str(i)
        if 'is_published' not in log:
            log['is_published'] = True
    return logs


@changelog_bp.route('/admin/changelogs')
@super_admin_required
def admin_changelogs():
    logs = _enrich(load_changelogs())
    return render_template('admin/changelogs.html', logs=logs)


@changelog_bp.route('/admin/changelogs/new', methods=['POST'])
@super_admin_required
def changelog_new():
    from datetime import date as _date
    data = __import__('flask').request.get_json() or {}
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    if not title or not content:
        return jsonify({'error': '請填寫標題與內容'}), 400

    logs = load_changelogs()
    new_entry = {
        'id': str(len(logs)),
        'version': (data.get('version') or '').strip() or None,
        'title': title,
        'content': content,
        'published_at': str(_date.today()),
        'is_published': bool(data.get('is_published', True)),
    }
    logs.insert(0, new_entry)
    _save_changelogs(logs)
    return jsonify({'success': True})


@changelog_bp.route('/admin/changelogs/<log_id>/edit', methods=['POST'])
@super_admin_required
def changelog_edit(log_id):
    data = __import__('flask').request.get_json() or {}
    logs = load_changelogs()
    _enrich(logs)
    for log in logs:
        if log.get('id') == log_id:
            log['version'] = (data.get('version') or '').strip() or None
            log['title'] = (data.get('title') or '').strip()
            log['content'] = (data.get('content') or '').strip()
            log['is_published'] = bool(data.get('is_published', True))
            _save_changelogs(logs)
            return jsonify({'success': True})
    return jsonify({'error': '找不到此記錄'}), 404


@changelog_bp.route('/admin/changelogs/<log_id>/delete', methods=['POST'])
@super_admin_required
def changelog_delete(log_id):
    logs = load_changelogs()
    _enrich(logs)
    new_logs = [log for log in logs if log.get('id') != log_id]
    if len(new_logs) == len(logs):
        return jsonify({'error': '找不到此記錄'}), 404
    _save_changelogs(new_logs)
    return jsonify({'success': True})


@changelog_bp.route('/api/changelogs/mark-seen', methods=['POST'])
@login_required
def mark_seen():
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    supabase.table('users').update({
        'last_seen_changelog_at': now_iso,
    }).eq('id', session['user_id']).execute()
    return jsonify({'success': True})
