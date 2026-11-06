"""後台權限矩陣：副標籤（服事身份）× 後台功能模塊。

移植自 event-registration-（成熟版），針對本系統調整一處：
**沒登記的 /admin 路徑對「靠副標籤授權的人」一律拒絕**（成熟版是放行）。
原因：成熟版靠「新增模塊要記得登記」加測試守著；這裡再多一道保險，
漏登記的後果是「同工進不去」（會被發現），而不是「任何有權限的人都進得去」（不會被發現）。

設計：
  - Y 軸 = 後台功能模塊（ADMIN_MODULES）；X 軸 = 副標籤群組（groups.is_primary = false）
  - 權限存在 groups.admin_modules（jsonb 陣列，放模塊 key）；只有超管能在 /admin/permissions 編輯
  - 超管／is_admin → 全部模塊；其他人 → 其所有副標籤所授予模塊的「聯集」
  - 判定只有一份實作：module_allows_path()；admin_required 與測試都走它
"""
from flask import Blueprint, jsonify, render_template, request, session

from db import supabase
from routes.audit import log_action
from routes.decorators import super_admin_required

permissions_bp = Blueprint('permissions', __name__)

# (key, 中文名稱, [對應的 URL 前綴])。新增後台功能時加一行，否則副標籤的人進不去。
ADMIN_MODULES = [
    ('events',        '活動管理',           ['/admin/events']),
    ('calendar',      '行事曆',             ['/admin/calendar', '/admin/api/calendar']),
    ('gospel',        '福音關懷',           ['/admin/gospel']),
    ('visitor_forms', '留名單',             ['/admin/visitor-forms']),
    ('courses',       '門訓課程/認證/教材', ['/admin/courses', '/admin/course-categories',
                                             '/admin/certifications', '/admin/materials']),
    ('devotional',    '禱讀本管理',         ['/admin/devotional']),
    ('backup',        '資料備份/匯出入',    ['/admin/backup', '/admin/data-export', '/admin/data-import']),
    ('members',       '會友管理',           ['/admin/users', '/admin/api/users', '/admin/api/whitelist']),
    ('groups',        '小組（標籤）管理',   ['/admin/groups', '/admin/api/groups']),
    ('cell_groups',   '小組回報管理',       ['/admin/cell-groups', '/admin/api/cell-groups',
                                             '/admin/api/users/search-for-cell']),
    ('verses',        '經文管理',           ['/admin/verses']),
    ('portal',        '首頁卡片與快捷連結', ['/admin/portal-links', '/admin/portal-cards',
                                             '/admin/portal-card-settings', '/admin/api/portal-cards']),
    ('bulletins',     '週報管理',           ['/admin/bulletins', '/admin/api/upload-bulletin']),
    ('discussions',   '小組討論',           ['/admin/group-discussions']),
    ('announcements', '公告',               ['/admin/announcements']),
    ('files',         '檔案分享管理',       ['/admin/files', '/admin/api/files']),
    ('roll_call',     '聚會點名',           ['/admin/roll-call', '/api/admin/roll-call']),
    ('staff_leave',   '全職同工差勤',       ['/admin/staff-leave', '/admin/attendance']),
    ('contact_leads', '洽詢紀錄（展示站）', ['/admin/contact-leads']),
    ('changelogs',    '更新日誌',           ['/admin/changelogs']),
    ('logs',          '操作記錄',           ['/admin/logs']),
    ('settings',      '系統設定',           ['/admin/settings']),
]

MODULE_KEYS = [m[0] for m in ADMIN_MODULES]
MODULE_LABELS = {m[0]: m[1] for m in ADMIN_MODULES}

# 既有「完整管理員」(is_admin) 後台首頁預設看得到的模塊（維持改版前的畫面）；
# 會員管理、系統設定、操作記錄等仍只有超管或被授權的副標籤才看得到。
DEFAULT_ADMIN_MODULES = {
    'events', 'calendar', 'gospel', 'visitor_forms', 'courses', 'devotional',
    'backup', 'roll_call', 'staff_leave',
}

# 不屬於任何單一模塊、但「有任一模塊權限的人」都需要的路徑
SHARED_ADMIN_PREFIXES = [
    '/admin/permissions',        # 權限矩陣本身：由超管在 view 內把關
    '/admin/api/upload-image',   # 各模塊共用的圖片上傳
]

# 刻意不交給矩陣的後台路徑：金流有自己的權限判斷（admin.py 的 _has_finance_access），
# 副標籤成員一律進不去。要開放就必須另外設計，不能因為漏登記而放行。
RESERVED_ADMIN_PREFIXES = ['/admin/payments', '/admin/settings/payment']

ADMIN_AREAS = ('/admin', '/api/admin')


def _match(path, prefix):
    return path == prefix or path.startswith(prefix + '/')


def classify(path):
    """回傳 (種類, 模塊 key)。種類：outside（不在後台）／shared／module／reserved（刻意不交給矩陣）／unregistered。"""
    norm = (path.rstrip('/') or '/')
    if not any(_match(norm, a) for a in ADMIN_AREAS):
        return 'outside', None
    if norm == '/admin' or any(_match(norm, p) for p in SHARED_ADMIN_PREFIXES):
        return 'shared', None
    if any(_match(norm, p) for p in RESERVED_ADMIN_PREFIXES):
        return 'reserved', None
    best, best_len = None, -1
    for key, _label, prefixes in ADMIN_MODULES:
        for pre in prefixes:
            if _match(norm, pre) and len(pre) > best_len:
                best, best_len = key, len(pre)
    return ('module', best) if best else ('unregistered', None)


def module_for_path(path):
    kind, key = classify(path)
    return key if kind == 'module' else None


def compute_admin_modules(is_super, is_admin, group_tags):
    """計算使用者可進的後台模塊集合；'*' 代表全部。登入時呼叫並存進 session。"""
    if is_super or is_admin:
        return '*'
    tags = group_tags or []
    if not tags:
        return set()
    try:
        rows = supabase.table('groups').select('name, admin_modules')\
            .eq('is_primary', False).in_('name', tags).execute().data or []
    except Exception:
        rows = []          # admin_modules 欄位尚未建立時不致命：當成沒有授權（fail closed）
    mods = set()
    for r in rows:
        for k in (r.get('admin_modules') or []):
            if k in MODULE_LABELS:
                mods.add(k)
    return mods


def session_modules(sess):
    """'*' 只在「現在」仍是超管／管理員時才算數。登入時存的 '*' 可能已過期
    （例如之後被降權），所以不能單靠它放行。"""
    m = sess.get('admin_modules')
    if m == '*':
        return '*' if (sess.get('is_super_admin') or sess.get('is_admin')) else set()
    return set(m or [])


def can_access_module(sess, key):
    m = session_modules(sess)
    return m == '*' or key in m


def can_enter_admin(sess):
    """是否能進後台（超管／管理員，或任一模塊有權）。"""
    if sess.get('is_super_admin') or sess.get('is_admin'):
        return True
    return bool(session_modules(sess))


def module_allows_path(sess, path):
    """唯一的判定：這個 session 能不能進這個後台路徑。

    超管／管理員全放行；副標籤的人只能進被授權的模塊，
    **沒登記的後台路徑與後台以外的路徑一律拒絕**（fail closed）。
    """
    if sess.get('is_super_admin') or sess.get('is_admin'):
        return True
    kind, key = classify(path)
    if kind == 'shared':
        return can_enter_admin(sess)
    if kind == 'module':
        return can_access_module(sess, key)
    return False


def visible_index_modules(sess):
    """後台首頁應顯示哪些模塊卡片。"""
    if sess.get('is_super_admin'):
        return set(MODULE_KEYS)
    if sess.get('is_admin'):
        return set(DEFAULT_ADMIN_MODULES)
    m = session_modules(sess)
    return set(MODULE_KEYS) if m == '*' else set(m)


# ── 權限矩陣編輯頁（僅超管）──────────────────────────────────
@permissions_bp.route('/admin/permissions')
@super_admin_required
def permissions_matrix():
    sub_groups = supabase.table('groups').select('id, name, admin_modules, is_staff')\
        .eq('is_primary', False).order('sort_order').execute().data or []
    return render_template('admin/permissions.html', modules=ADMIN_MODULES, sub_groups=sub_groups)


@permissions_bp.route('/admin/permissions/save', methods=['POST'])
@super_admin_required
def permissions_save():
    data = request.get_json(silent=True) or {}
    matrix = data.get('matrix') or {}          # { group_id: [module_key, ...] }
    valid_keys = set(MODULE_LABELS)
    sub_groups = supabase.table('groups').select('id').eq('is_primary', False).execute().data or []
    valid_group_ids = {g['id'] for g in sub_groups}

    updated = 0
    for gid, mods in matrix.items():
        if gid not in valid_group_ids:         # 只允許更新副標籤群組
            continue
        clean = [m for m in (mods or []) if m in valid_keys]
        supabase.table('groups').update({'admin_modules': clean}).eq('id', gid).execute()
        updated += 1
    log_action('permission.update', target_type='permission_matrix', detail={'updated_groups': updated})
    return jsonify({'status': 200, 'data': {'updated': updated}, 'error': None})
