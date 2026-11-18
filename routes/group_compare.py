"""小組對照：「標籤小組」（groups，主標籤）和「週間小組」（cell_groups）兩份名單差在哪裡。

為什麼：使用者說「在我的認知裡他是同一個小組」，但系統存成兩份互不相認的名單
（見 docs/GROUP_MERGE_ASSESSMENT.md）。合併之前要先知道正式站實際分歧到什麼程度。

★ 這一頁**只讀**：不改任何資料、不自動配對。名稱比對只用來「列出來給人看」，
  不拿去做任何決定（同名不一定是同一組，不同名也可能是同一組 —— 那要管理員判斷）。
★ 讀不到就照實講「讀不到」，不可以顯示成「兩邊一致」。
"""
from flask import Blueprint, render_template

from db import supabase
from routes.decorators import admin_required

group_compare_bp = Blueprint('group_compare', __name__)

PAGE = 1000


def _norm(name):
    return ''.join((name or '').split()).lower()


def _all(table, cols, sb, **eq):
    """分頁讀完（PostgREST 一次最多 1000 筆）；有上界，漏掉 range 時不會卡死。"""
    out, start = [], 0
    for _ in range(50):
        q = sb.table(table).select(cols)
        for k, v in eq.items():
            q = q.eq(k, v)
        rows = q.range(start, start + PAGE - 1).execute().data or []
        out += rows
        if len(rows) < PAGE:
            return out
        start += PAGE
    raise RuntimeError(f'{table} 分頁超過上界')


def compare(sb=None):
    """回傳對照結果；任何一份讀不到就丟例外（呼叫端照實顯示「讀不到」）。"""
    sb = sb or supabase
    tags = [g for g in _all('groups', 'name, is_primary', sb) if g.get('is_primary')]
    cells = _all('cell_groups', 'id, name, is_active, is_children_group', sb)
    cells = [c for c in cells if c.get('is_active', True)]
    tag_by = {_norm(g['name']): g['name'] for g in tags}
    cell_by = {_norm(c['name']): c['name'] for c in cells}
    names = {
        'both': sorted(tag_by[k] for k in tag_by.keys() & cell_by.keys()),
        'only_tag': sorted(tag_by[k] for k in tag_by.keys() - cell_by.keys()),
        'only_cell': sorted(cell_by[k] for k in cell_by.keys() - tag_by.keys()),
    }

    # 人：標籤寫在帳號上（組名文字）；週間小組看 cell_members（已確認、有連帳號的）
    users, start = [], 0                 # 直接寫出 users 查詢（結構守衛要看得到它）
    for _ in range(50):
        rows = sb.table('users').select('id, real_name, display_name, group_tags')\
            .range(start, start + PAGE - 1).execute().data or []
        users += rows
        if len(rows) < PAGE:
            break
        start += PAGE
    else:
        raise RuntimeError('users 分頁超過上界')
    members = _all('cell_members', 'group_id, name, user_id, is_active, is_confirmed', sb)
    members = [m for m in members if m.get('is_active', True) and m.get('is_confirmed', True)]
    cell_name = {c['id']: c['name'] for c in cells}
    in_cell = {}
    unlinked = {}
    for m in members:
        g = cell_name.get(m.get('group_id'))
        if not g:
            continue
        if m.get('user_id'):
            in_cell.setdefault(m['user_id'], set()).add(g)
        else:
            unlinked[g] = unlinked.get(g, 0) + 1

    tag_keys = set(tag_by)
    differ, tag_only, cell_only = [], [], []
    for u in users:
        mine_tag = {t for t in (u.get('group_tags') or []) if _norm(t) in tag_keys}
        mine_cell = in_cell.get(u['id'], set())
        name = u.get('real_name') or u.get('display_name') or '（沒有名字）'
        if mine_tag and mine_cell:
            if {_norm(x) for x in mine_tag} != {_norm(x) for x in mine_cell}:
                differ.append({'name': name, 'tag': sorted(mine_tag), 'cell': sorted(mine_cell)})
        elif mine_tag:
            tag_only.append({'name': name, 'tag': sorted(mine_tag)})
        elif mine_cell:
            cell_only.append({'name': name, 'cell': sorted(mine_cell)})
    key = lambda r: r['name']
    return {
        'names': names,
        'differ': sorted(differ, key=key),
        'tag_only': sorted(tag_only, key=key),
        'cell_only': sorted(cell_only, key=key),
        'unlinked': sorted(unlinked.items()),
        'counts': {'tags': len(tags), 'cells': len(cells)},
    }


@group_compare_bp.route('/admin/groups/compare')
@admin_required
def group_compare_page():
    try:
        data, error = compare(), None
    except Exception as e:                       # noqa: BLE001
        data, error = None, type(e).__name__
    return render_template('admin/group_compare.html', data=data, error=error)
