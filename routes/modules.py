"""功能模組登記表：各教會自己選要用哪些功能。

規則（沿用規格 PRODUCT 原則 11）：
  - 核心（人、登入、權限、稽核、通知、備份、首頁與後台外殼）**永遠開著**，不在這張表裡。
  - 選配模組可以被關閉。關掉＝**整塊消失**：網址回 404、首頁卡片與連結、後台卡片、
    權限矩陣欄位一起隱藏。**關掉不刪資料**；備份與匯出照樣包含（資料安全優先）。
  - 依賴要滿足：關掉被依賴的模組時要先關掉依賴它的；依賴未滿足不能開啟。
  - 展示站專用的功能（洽詢、展示帳號登入）只在 `DEMO_MODE` 開著時才存在，不靠資料庫開關。
  - 判定只有一份實作：`classify()` / `is_enabled()`；網址攔截、模板、後台頁面、測試都走它。

新增功能時：把它的網址前綴登記進 MODULES（`*` 可代表任一段，例如 `/events/*/pay`），
否則它會被當成核心而關不掉（有測試會掃所有路由，沒登記的選配前綴不會被發現，所以要記得）。
"""
import json
import os
import time
from collections import namedtuple

from flask import Blueprint, abort, jsonify, render_template, request

import settings_store
from config import Config
from routes.audit import log_action
from routes.decorators import super_admin_required

modules_bp = Blueprint('modules', __name__)

Module = namedtuple('Module', 'key label kind requires prefixes desc needs', defaults=((), (), '', ''))

#  kind：optional（教會自己選）／demo_only（只在 DEMO_MODE 才有）
MODULES = [
    Module('events', '活動報名與簽到', 'optional', (), (
        '/events', '/event', '/compute-age', '/checkin', '/my-history', '/admin/events'),
        '活動、報名、QR 簽到、我的出席紀錄'),
    Module('payments', '線上金流', 'optional', ('events',), (
        '/payment', '/events/*/registrations/*/pay', '/admin/payments', '/admin/settings/payment'),
        '綠界／LINE Pay 付款（第一階段規格決定不做，保留給有需要的教會）'),
    Module('calendar', '教會行事曆', 'optional', (), (
        '/calendar', '/calendar.ics', '/api/calendar', '/admin/calendar', '/admin/api/calendar'), '行事曆與個人行程'),
    Module('bulletins', '每週週報', 'optional', (), (
        '/bulletins', '/admin/bulletins', '/admin/api/upload-bulletin'), '週報與公告'),
    Module('prayer', '代禱牆', 'optional', (), ('/prayer', '/api/prayer'), '分享代禱需求、互相代禱'),
    Module('gospel', '福音探索', 'optional', (), ('/gospel', '/admin/gospel'), '福音探索問答與詢問紀錄'),
    Module('visitor_forms', '留名單', 'optional', (), (
        '/visitor-form', '/admin/visitor-forms'), '新朋友留名單照片'),
    Module('courses', '門訓學程', 'optional', (), (
        '/courses', '/my-courses', '/course-shared-checkin', '/course-checkin', '/admin/courses',
        '/admin/certifications', '/admin/materials', '/admin/course-categories'),
        '課程、出席、認證、教材庫存'),
    Module('devotional', '禱讀本訂購', 'optional', (), ('/devotional', '/admin/devotional'), '各小組登記與簽收'),
    Module('reading', '聖經速讀', 'optional', (), ('/reading',), '365 天聖經速讀計畫：打勾、經文、朗讀、列印速讀表'),
    Module('sermons', '主日信息', 'optional', (), ('/sermons', '/admin/sermons'), '教會 YouTube 主日影片，按週分組（影片自動抓進來）'),
    Module('diary', '天父日記', 'optional', (), ('/diary', '/api/diary'), '每日靈修日記'),
    Module('files', '檔案分享', 'optional', (), (
        '/files', '/folders', '/admin/files', '/admin/api/files'), '教會資料夾與檔案（需要 R2）'),
    Module('cell_report', '小組回報', 'optional', (), (
        '/cell-report', '/admin/cell-groups', '/admin/api/cell-groups'), '每週小組回報、牧者與同工查閱'),
    Module('roll_call', '聚會點名', 'optional', (), (
        '/roll-call', '/api/roll-call', '/admin/roll-call', '/api/admin/roll-call'),
        '個人點名、出席率（與使用者帳號脫鉤）'),
    Module('staff_leave', '全職同工差勤', 'optional', (), (
        '/staff-leave', '/admin/staff-leave', '/attendance', '/admin/attendance'), '請假、加班、特休'),
    Module('verses', '每日經文', 'optional', (), (
        '/verse', '/api/verse-data', '/admin/verses'), '每日抽經文與經文管理'),
    Module('discussions', '小組討論', 'optional', (), ('/admin/group-discussions',), '小組討論影片管理'),
    Module('announcements', '公告', 'optional', (), ('/admin/announcements',), '後台發布公告'),
    Module('changelogs', '更新日誌', 'optional', (), ('/admin/changelogs', '/api/changelogs'), '系統更新通知'),
    Module('demo', '展示站功能', 'demo_only', (), (
        '/auth/demo-login', '/auth/demo-reset', '/auth/contact', '/admin/contact-leads'),
        '展示帳號登入、洽詢表單與紀錄（正式教會部署不會有）'),
]
BY_KEY = {m.key: m for m in MODULES}

#  舊的環境變數開關（ENABLE_*=false）只當作「這個模組的預設值」：還沒有人在 /admin/modules 表態過時才生效，
#  已經在後台表態過的，以後台為準。這樣已經設過 ENABLE_* 的部署升級後行為不變，也不會有兩套互相打架。
ENV_DEFAULTS = {
    'courses': 'ENABLE_COURSES', 'calendar': 'ENABLE_CALENDAR', 'bulletins': 'ENABLE_BULLETIN',
    'prayer': 'ENABLE_PRAYER', 'gospel': 'ENABLE_GOSPEL', 'visitor_forms': 'ENABLE_VISITOR_FORMS',
}
#  模組需要的外部設定（給部署精靈與後台頁面顯示；沒有就不顯示）
NEEDS = {
    'files': 'Cloudflare R2（R2_* 環境變數）',
    'diary': 'AI 金鑰（GROQ_API_KEY，可選；沒有就沒有 AI 反思引導）',
    'payments': '金流商帳號與設定（綠界／LINE Pay）',
}


def default_on(key):
    var = ENV_DEFAULTS.get(key)
    return not (var and os.getenv(var, 'true').strip().lower() == 'false')


def is_on_in_state(key, state=None):
    """後台有表態用後台；沒表態用預設（環境變數或「開」）。"""
    state = _load_state() if state is None else state
    return state.get(key, default_on(key))
SETTINGS_KEY = 'modules_state'          # settings 表：JSON {模組 key: true/false}；沒寫的用預設（開）
CACHE_TTL = 30                           # 秒；儲存時會立刻清掉
_cache = {'at': 0.0, 'state': None}


def _segments(path):
    return [s for s in path.strip('/').split('/') if s != '']


def _prefix_match(path_segs, prefix):
    pre = _segments(prefix)
    if len(path_segs) < len(pre):
        return None
    for a, b in zip(path_segs, pre):
        if b != '*' and a != b:
            return None
    return len(pre)


def classify(path):
    """這個網址屬於哪個選配模組；沒有登記的一律是核心（回 None）。最長前綴勝出。"""
    segs = _segments(path)
    best, best_len = None, -1
    for m in MODULES:
        for pre in m.prefixes:
            n = _prefix_match(segs, pre)
            if n is not None and n > best_len:
                best, best_len = m.key, n
    return best


def _load_state():
    """讀開關；讀不到就當全部使用預設（開）——連不上資料庫時整站本來就不能用，不必在這裡再擋一層。"""
    now = time.time()
    if _cache['state'] is not None and now - _cache['at'] < CACHE_TTL:
        return _cache['state']
    try:
        raw = settings_store.get(SETTINGS_KEY)
        state = {k: bool(v) for k, v in (json.loads(raw) if raw else {}).items() if k in BY_KEY}
    except Exception:
        state = {}
    _cache.update(at=now, state=state)
    return state


def bust():
    # 開關存在 settings 表，而 settings_store 也有一層快取：兩層一起清，才是真的「重新讀」
    from routes import cache
    cache.bust('settings_all')
    _cache.update(at=0.0, state=None)


def is_enabled(key):
    m = BY_KEY.get(key)
    if m is None:
        return True                      # 核心：永遠開著
    if m.kind == 'demo_only':
        return bool(Config.DEMO_MODE)
    if not is_on_in_state(key):
        return False
    return all(is_enabled(r) for r in m.requires)     # 依賴關掉了，它也跟著不存在


def is_path_enabled(path):
    key = classify(path)
    return key is None or is_enabled(key)


def module_on(path_or_key):
    """給模板用：`module_on('/diary')` 或 `module_on('diary')`。核心／沒登記的一律 True。"""
    if path_or_key in BY_KEY:
        return is_enabled(path_or_key)
    if isinstance(path_or_key, str) and path_or_key.startswith('/'):
        return is_path_enabled(path_or_key)
    return True


def enforce_modules():
    """before_request：關掉的模組，網址一律 404（不是 403，也不導去登入頁）。"""
    path = request.path
    if path.startswith('/static'):
        return None
    if not is_path_enabled(path):
        abort(404)


def validate(new_state):
    """回傳錯誤訊息清單（空＝可以儲存）。"""
    errors = []
    for key in new_state:
        m = BY_KEY.get(key)
        if m is None:
            errors.append(f'不認得的模組：{key}')
        elif m.kind == 'demo_only':
            errors.append(f'「{m.label}」由 DEMO_MODE 控制，不能在這裡開關')
    if errors:
        return errors
    eff = {m.key: new_state.get(m.key, is_on_in_state(m.key))
           for m in MODULES if m.kind == 'optional'}
    for m in MODULES:
        if m.kind == 'optional' and eff[m.key]:
            for r in m.requires:
                if BY_KEY[r].kind == 'optional' and not eff[r]:
                    errors.append(f'「{m.label}」需要先開啟「{BY_KEY[r].label}」')
    return errors


# ── 後台：選用功能模組（僅超管）──────────────────────────────
@modules_bp.route('/admin/modules')
@super_admin_required
def modules_page():
    state = _load_state()
    rows = [{'m': m, 'on': is_on_in_state(m.key, state), 'requires': [BY_KEY[r].label for r in m.requires],
             'needs': NEEDS.get(m.key, '')} for m in MODULES if m.kind == 'optional']
    return render_template('admin/modules.html', rows=rows, demo_mode=bool(Config.DEMO_MODE))


@modules_bp.route('/admin/modules/save', methods=['POST'])
@super_admin_required
def modules_save():
    data = (request.get_json(silent=True) or {}).get('modules')
    if not isinstance(data, dict):
        return jsonify({'status': 400, 'data': {}, 'error': '資料格式錯誤'}), 400
    new_state = {k: bool(v) for k, v in data.items()}
    errors = validate(new_state)
    if errors:
        return jsonify({'status': 400, 'data': {}, 'error': '；'.join(errors)}), 400
    merged = {**{m.key: is_on_in_state(m.key) for m in MODULES if m.kind == 'optional'}, **new_state}
    try:
        settings_store.set(SETTINGS_KEY, json.dumps(merged, ensure_ascii=False, sort_keys=True))
    except Exception:
        return jsonify({'status': 500, 'data': {}, 'error': '儲存失敗，請稍後再試'}), 500
    bust()
    log_action('module.update', target_type='modules', detail={
        'disabled': sorted(k for k, v in merged.items() if not v)})
    return jsonify({'status': 200, 'data': {'disabled': sorted(k for k, v in merged.items() if not v)},
                    'error': None})
