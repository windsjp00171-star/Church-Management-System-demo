import json
import os
from flask import Blueprint, session, jsonify, current_app
from db import supabase
from routes.decorators import login_required

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


@changelog_bp.route('/api/changelogs/mark-seen', methods=['POST'])
@login_required
def mark_seen():
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    supabase.table('users').update({
        'last_seen_changelog_at': now_iso,
    }).eq('id', session['user_id']).execute()
    return jsonify({'success': True})
