"""合併帳號：把「要刪的 users 那一列」的所有引用搬到「留下的那一列」

移植自 event-registration-（成熟版）。兩個入口共用這一份（單一來源）：
- `routes/admin.py` 的 `merge_line_account`（超級管理員，把 LINE 帳號整合進手動帳號）
- `routes/profile.py` 的 `merge_confirm`（本人確認後把新帳號的 LINE 身分移到舊帳號）

## 為什麼取代原本的 account_merge.transfer_user_records

原本每一次搬移都包在 `try/except` 只記 log，失敗的表被丟進「failed」清單，
**然後照樣刪掉 users**。核對 schema 後發現：

| 問題 | 後果 |
|---|---|
| 清單寫的是 `course_attendance`，但實際的表叫 `session_attendance`（有外鍵） | 門訓出席沒被搬，刪帳號時不是失敗就是資料消失，而畫面顯示合併「成功」 |
| `audit_logs.actor_id` 沒搬 | 「誰做的」安靜地變成空值或懸空引用 |
| `material_transactions.created_by` 不存在 | 空操作（永遠不會有人發現） |
| 搬到一半失敗 | 身分已經換過、資料搬一半、舊帳號還在 —— 沒有還原 |

## 規則

1. **REFS 是唯一的清單**。`tests/test_user_merge.py` 掃 `schema.sql` 的外鍵，漏一個就紅。
2. **失敗不可以被吞掉**：任何一步失敗就中止、**還原已經搬的**、不刪 users、丟 `MergeError`。
   PostgREST 沒有跨表交易，所以還原是我們自己做的補償（搬之前先把整批列抄下來）。
3. **唯一限制的衝突**：只有 `dedupe` 有指定的表會「取聯集、忽略重複」。
   其他表撞到唯一限制一律中止 —— 兩邊的內容不一樣（例如 `staff_profiles`、`session_attendance`、
   `course_enrollments`），默默丟掉哪一邊都是在替人做決定。
4. 不改資料庫結構。外鍵的 CASCADE / SET NULL 行為不在這裡動。

## 刻意不在清單裡的

- 聚會點名（`rc_*`）：點名與使用者帳號脫鉤；操作者欄位只是 id＋姓名快照，不是引用。
- 天父日記：以 `line_user_id`（文字）為鍵，LINE 身分移轉後自動跟隨。

## 已決定：最後仍會刪除被合併者的 users 列（沿用成熟版）
規格守衛 22（不得刪除 users 列）因此對帳號合併放寬；但**一定是全部搬完、全部確認之後才刪**，
刪除失敗會把搬過的全部還原。
"""
from collections import namedtuple

from db import supabase

PAGE = 1000          # PostgREST 一次最多回 1000 筆，一定要分頁
BATCH = 100          # in_() 一次放幾個 id（網址長度）

#  table / col：引用 users.id 的欄位
#  dedupe：撞到唯一限制時，用哪幾欄判斷「target 那邊已經有一樣的」。
#          None ＝ 不處理衝突（撞到就中止）。
#  key：還原時用哪幾欄找回那一列（沒有 id 的表要寫）。
Ref = namedtuple('Ref', 'table col dedupe key', defaults=(None, ('id',)))

REFS = [
    # ── 欄位名是 user_id ──────────────────────────
    Ref('cell_group_leaders', 'user_id', dedupe=('group_id',)),        # UNIQUE (user_id, group_id)
    Ref('cell_members', 'user_id'),
    Ref('course_certificates', 'user_id'),                              # UNIQUE (user_id, category_id)：內容不同就中止
    Ref('course_certifications', 'user_id'),                            # 同上
    Ref('course_enrollments', 'user_id'),                               # UNIQUE (course_id, user_id)：撞到就中止
    Ref('daily_verse_draws', 'user_id', dedupe=('drawn_date',)),        # UNIQUE (user_id, drawn_date)
    Ref('group_members', 'user_id', dedupe=('group_id',),
        key=('group_id',)),                                             # PK (group_id, user_id)，沒有 id 欄
    Ref('leave_requests', 'user_id'),
    Ref('notifications', 'user_id'),
    Ref('overtime_records', 'user_id'),
    Ref('personal_events', 'user_id'),
    Ref('prayer_comments', 'user_id'),
    Ref('prayer_reactions', 'user_id', dedupe=('prayer_id',)),          # UNIQUE (prayer_id, user_id)
    Ref('prayers', 'user_id'),
    Ref('registration_whitelist', 'user_id', dedupe=('ref_type', 'ref_id')),
    Ref('registrations', 'user_id'),
    Ref('session_attendance', 'user_id'),                               # UNIQUE (session_id, user_id)：撞到就中止
    Ref('staff_profiles', 'user_id'),                                   # UNIQUE (user_id)：兩邊都有就中止
    # ── 欄位名不是 user_id ────────────────────────
    Ref('audit_logs', 'actor_id'),                                      # 「誰做的」
    Ref('church_events', 'created_by'),
    Ref('course_certificates', 'created_by'),
    Ref('course_certifications', 'created_by'),
    Ref('courses', 'created_by'),
    Ref('devotional_registration_logs', 'changed_by'),
    Ref('devotional_registrations', 'registered_by'),
    Ref('devotional_registrations', 'confirmed_by'),
    Ref('events', 'created_by'),
    Ref('files', 'owner_id'),
    Ref('folders', 'created_by'),
    Ref('leave_requests', 'reviewed_by'),
    Ref('overtime_records', 'reviewed_by'),
    Ref('user_groups', 'created_by'),
    Ref('visitor_forms', 'created_by'),
    Ref('visitor_forms', 'uploaded_by'),
    # 聚會人數回報「誰填的」（migration 015）
    Ref('sunday_reports', 'submitted_by'),
    Ref('children_sunday_reports', 'submitted_by'),
    Ref('prayer_reports', 'submitted_by'),
    Ref('morning_prayer_reports', 'submitted_by'),
    Ref('custom_meeting_reports', 'submitted_by'),
    Ref('week_notes', 'created_by'),
    Ref('weekly_bulletins', 'created_by'),
]


class MergeError(Exception):
    """合併中止。`rolled_back` 為 False 表示還原也有失敗，需要人工檢查。"""

    def __init__(self, message, rolled_back=True, detail=None):
        super().__init__(message)
        self.message = message
        self.rolled_back = rolled_back
        self.detail = detail or {}


def label(ref):
    return f'{ref.table}.{ref.col}'


def _short(e):
    return str(e)[:200]


def _fetch(ref, uid):
    """該欄位等於 uid 的所有列（整列，分頁）。"""
    rows, start = [], 0
    order_col = ref.key[0]
    while True:
        page = (supabase.table(ref.table).select('*').eq(ref.col, uid)
                .order(order_col).range(start, start + PAGE - 1).execute().data or [])
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        start += PAGE


def _dedupe_key(ref, row):
    return tuple(row.get(c) for c in ref.dedupe)


def _where_row(q, ref, row):
    for c in ref.key:
        q = q.eq(c, row.get(c))
    return q


def plan(keep_id, drop_id):
    """預覽：每一個欄位會搬幾筆、會因重複而丟掉幾筆。讀取失敗就丟 MergeError。"""
    steps = []
    for ref in REFS:
        try:
            src = _fetch(ref, drop_id)
            dup = []
            if ref.dedupe and src:
                have = {_dedupe_key(ref, r) for r in _fetch(ref, keep_id)}
                dup = [r for r in src if _dedupe_key(ref, r) in have]
            move = [r for r in src if r not in dup]
            for r in src:
                if any(c not in r for c in ref.key):
                    raise MergeError(f'{label(ref)} 的列沒有 {ref.key} 欄位，無法保證能還原')
        except MergeError:
            raise
        except Exception as e:
            raise MergeError(f'讀取 {label(ref)} 失敗：{_short(e)}（沒有任何資料被動到）')
        steps.append((ref, move, dup))
    return steps


def summarize(steps):
    moved = {label(r): len(m) for r, m, d in steps if m}
    dropped = {label(r): len(d) for r, m, d in steps if d}
    return {'moved': moved, 'duplicates_dropped': dropped,
            'total_moved': sum(moved.values()),
            'total_duplicates_dropped': sum(dropped.values())}


def preview(keep_id, drop_id):
    return summarize(plan(keep_id, drop_id))


# ── 還原 ───────────────────────────────────────
def _undo_move(ref, rows, keep_id, drop_id):
    if ref.key == ('id',):
        ids = [r['id'] for r in rows]
        for i in range(0, len(ids), BATCH):
            (supabase.table(ref.table).update({ref.col: drop_id})
             .eq(ref.col, keep_id).in_('id', ids[i:i + BATCH]).execute())
    else:
        for r in rows:
            _where_row(supabase.table(ref.table).update({ref.col: drop_id})
                       .eq(ref.col, keep_id), ref, r).execute()


def _undo_delete(ref, rows):
    for i in range(0, len(rows), BATCH):
        supabase.table(ref.table).insert(rows[i:i + BATCH]).execute()


def _rollback(done, keep_id, drop_id):
    """倒著還原。回傳還原失敗的清單（空 ＝ 完整還原）。"""
    failures = []
    for kind, ref, rows in reversed(done):
        try:
            if kind == 'moved':
                _undo_move(ref, rows, keep_id, drop_id)
            elif kind == 'deleted':
                _undo_delete(ref, rows)
            elif kind == 'identity':
                keep_before, drop_before = rows
                supabase.table('users').update(keep_before).eq('id', keep_id).execute()
                supabase.table('users').update(drop_before).eq('id', drop_id).execute()
        except Exception as e:
            failures.append(f'{kind} {label(ref) if ref else "users"}：{_short(e)}')
    return failures


def _delete_rows(ref, rows, drop_id):
    if ref.key == ('id',):
        ids = [r['id'] for r in rows]
        for i in range(0, len(ids), BATCH):
            supabase.table(ref.table).delete().in_('id', ids[i:i + BATCH]).execute()
    else:
        for r in rows:
            _where_row(supabase.table(ref.table).delete().eq(ref.col, drop_id), ref, r).execute()


def merge_users(keep_id, drop_id, keep_before, drop_before, new_identity):
    """把 drop_id 併進 keep_id，最後刪掉 drop_id 那一列。

    keep_before / drop_before：users 兩列「身分欄位」合併前的值
        （line_user_id / display_name / picture_url），失敗時用來還原。
    new_identity：要寫到 keep 的 line_user_id / display_name / picture_url。
    成功回傳 summarize() 的結果；失敗丟 MergeError（已盡力還原）。
    """
    steps = plan(keep_id, drop_id)         # 讀取失敗在這裡就停，什麼都還沒動
    done = []

    def fail(message):
        failures = _rollback(done, keep_id, drop_id)
        if failures:
            raise MergeError(f'{message}；而且還原有失敗，請人工檢查：' + '；'.join(failures),
                             rolled_back=False, detail={'rollback_failures': failures})
        raise MergeError(f'{message}。已全部還原，沒有刪除任何帳號。', rolled_back=True)

    # 1. LINE 身分：先清 drop 的（避免 UNIQUE 衝突），再寫到 keep
    try:
        supabase.table('users').update({'line_user_id': None}).eq('id', drop_id).execute()
        done.append(('identity', None, (keep_before, drop_before)))
        supabase.table('users').update(new_identity).eq('id', keep_id).execute()
    except Exception as e:
        fail(f'更新 LINE 身分失敗：{_short(e)}')

    # 2. 搬引用
    for ref, move, dup in steps:
        try:
            if dup:
                _delete_rows(ref, dup, drop_id)
                done.append(('deleted', ref, dup))
            if move:
                supabase.table(ref.table).update({ref.col: keep_id}).eq(ref.col, drop_id).execute()
                done.append(('moved', ref, move))
            if move or dup:
                left = (supabase.table(ref.table).select(ref.key[0]).eq(ref.col, drop_id)
                        .limit(1).execute().data or [])
                if left:
                    raise RuntimeError('搬完後仍有資料指向舊帳號')
        except Exception as e:
            fail(f'搬移 {label(ref)} 失敗：{_short(e)}')

    # 3. 最後才刪 users
    try:
        supabase.table('users').delete().eq('id', drop_id).execute()
    except Exception as e:
        fail(f'刪除舊帳號失敗：{_short(e)}')

    return summarize(steps)
