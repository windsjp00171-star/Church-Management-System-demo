"""夠真的 Supabase 替身：有資料、會篩、會寫。

## 為什麼需要這個

原本的替身有兩種：全域那個 MagicMock（查什麼都回 MagicMock），
和 `empty_supabase()`（查什麼都回空陣列）。兩個都只能驗
「這條路由會不會爆」，**驗不了「它做對了沒有」**。

而這個專案反覆出現的那一類 bug 正是「不會爆，只是說的是假的」——
所以最需要的那一種測試，剛好是既有替身做不到的那一種。

這支撐得起「照著使用者的動作跑一遍」：報名、額滿、排候補、
取消、遞補、看名單。資料是真的存進 dict 裡，下一個查詢讀得到。

## 支援到哪裡

select / insert / update / delete，加上 eq / neq / in_ / order /
limit / count='exact'，以及 `'*, event_fields(label, field_type)'`
這種內嵌關聯（照 field_id 接起來）。

★ 不支援的就讓它**爆掉**，不要默默回空陣列 ——
  默默回空的替身會讓測試綠得很安靜，那正是要避免的東西。
"""
import itertools
import re
from datetime import datetime, timezone


PAGE_MAX = 1000    # PostgREST 的預設上限（見 execute）


class FakeSupabase:
    def __init__(self, **tables):
        # {table_name: [row, ...]}
        self.data = {k: [dict(r) for r in v] for k, v in tables.items()}
        self._seq = itertools.count(1)
        self.log = []          # 寫入動作的流水帳，測試可以拿來看順序

    # 給測試用的小工具 ────────────────────────────
    def rows(self, table):
        return self.data.setdefault(table, [])

    def new_id(self, prefix='id'):
        return f'{prefix}-{next(self._seq)}'

    def table(self, name):
        return _Query(self, name)

    # storage 不在這支的範圍內，但有些路由會順手摸一下
    @property
    def storage(self):
        raise AssertionError('這支替身不支援 storage，測到這裡表示測錯東西了')


class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, db, table):
        self.db = db
        self.table_name = table
        self._filters = []      # (op, col, value)
        self._order = None
        self._limit = None
        self._range = None
        self._count = None
        self._select = '*'
        self._op = 'select'
        self._payload = None

    # ── 動作 ──────────────────────────
    def select(self, cols='*', count=None):
        self._op, self._select, self._count = 'select', cols, count
        return self

    def insert(self, payload):
        self._op, self._payload = 'insert', payload
        return self

    def update(self, payload):
        self._op, self._payload = 'update', payload
        return self

    def delete(self):
        self._op = 'delete'
        return self

    def upsert(self, payload, on_conflict='id', **_kw):
        self._op, self._payload, self._conflict = 'upsert', payload, [c.strip() for c in on_conflict.split(',')]
        return self

    # ── 篩選 ──────────────────────────
    def eq(self, col, val):
        self._filters.append(('eq', col, val))
        return self

    def neq(self, col, val):
        self._filters.append(('neq', col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(('in', col, list(vals)))
        return self

    def gte(self, col, val):
        self._filters.append(('gte', col, val))
        return self

    def lte(self, col, val):
        self._filters.append(('lte', col, val))
        return self

    def gt(self, col, val):
        self._filters.append(('gt', col, val))
        return self

    def lt(self, col, val):
        self._filters.append(('lt', col, val))
        return self

    def ilike(self, col, pattern):
        self._filters.append(('ilike', col, pattern))
        return self

    def is_(self, col, val):
        self._filters.append(('is', col, val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def range(self, start, end):
        """PostgREST 的分頁（含頭含尾）。

        ★ 一定要模擬：真的 client 一次最多回 1000 筆，備份那類「整張表撈
          出來」的程式碼**必須**分頁。替身不支援 range 的話，那種程式碼
          在測試裡會走到 AttributeError 或一次回全部 ——
          兩種都讓「靜靜截斷 1000 筆」這個 bug 驗不到。
        """
        self._range = (start, end)
        return self

    def limit(self, n):
        self._limit = n
        return self

    # ── 執行 ──────────────────────────
    def _match(self, row):
        for op, col, val in self._filters:
            got = row.get(col)
            if op == 'eq' and got != val:
                return False
            if op == 'neq' and got == val:
                return False
            if op == 'in' and got not in val:
                return False
            if op == 'gte' and not (got is not None and got >= val):
                return False
            if op == 'lte' and not (got is not None and got <= val):
                return False
            if op == 'gt' and not (got is not None and got > val):
                return False
            if op == 'lt' and not (got is not None and got < val):
                return False
            if op == 'is':
                if (val == 'null') != (got is None):
                    return False
            if op == 'ilike':
                needle = val.strip('%').lower()
                if needle not in (got or '').lower():
                    return False
        return True

    def execute(self):
        rows = self.db.rows(self.table_name)

        if self._op == 'insert':
            payloads = (self._payload if isinstance(self._payload, list)
                        else [self._payload])
            made = []
            for p in payloads:
                row = dict(p)
                row.setdefault('id', self.db.new_id(self.table_name[:3]))
                row.setdefault('created_at',
                               datetime.now(timezone.utc).isoformat())
                rows.append(row)
                made.append(dict(row))
            self.db.log.append(('insert', self.table_name, made))
            return _Result(made)

        if self._op == 'upsert':
            payloads = (self._payload if isinstance(self._payload, list) else [self._payload])
            made = []
            for p in payloads:
                cols = self._conflict
                if any(c not in p for c in cols):
                    raise AssertionError(f'upsert 的衝突欄位 {cols} 不在資料列裡：{sorted(p)}')
                same = next((r for r in rows if all(r.get(c) == p[c] for c in cols)), None)
                if same is not None:
                    same.update(p)
                    made.append(dict(same))
                else:
                    row = dict(p)
                    if 'id' in cols:
                        row.setdefault('id', self.db.new_id(self.table_name[:3]))
                    rows.append(row)
                    made.append(dict(row))
            self.db.log.append(('upsert', self.table_name, made))
            return _Result(made)

        hit = [r for r in rows if self._match(r)]

        if self._op == 'update':
            for r in hit:
                r.update(self._payload)
            self.db.log.append(('update', self.table_name,
                                [r.get('id') for r in hit], dict(self._payload)))
            return _Result([dict(r) for r in hit])

        if self._op == 'delete':
            for r in hit:
                rows.remove(r)
            self.db.log.append(('delete', self.table_name,
                                [r.get('id') for r in hit]))
            return _Result([dict(r) for r in hit])

        # select
        if self._order:
            col, desc = self._order
            hit = sorted(hit, key=lambda r: (r.get(col) is None, r.get(col)),
                         reverse=desc)
        if self._range is not None:
            lo, hi = self._range
            hit = hit[lo:hi + 1]
        if self._limit is not None:
            hit = hit[:self._limit]
        # ★★ PostgREST **預設一次最多回 1000 筆**，沒有 range/limit 也一樣。
        #
        #   替身一定要模擬這條，不然「整張表撈出來」的程式碼忘記分頁時，
        #   測試裡會拿到全部、正式站只拿到 1000 筆 —— 而那正是備份最糟的
        #   失敗方式（靜靜少掉幾百筆，ZIP 看起來完全正常）。
        #   ★ 這個洞是 mutation 測試抓到的：把分頁整段拿掉，測試照樣全綠。
        if self._range is None and self._limit is None:
            hit = hit[:PAGE_MAX]
        out = [self._project(r) for r in hit]
        return _Result(out, count=len(out) if self._count else None)

    # ── 內嵌關聯：'*, event_fields(label, field_type)' ──
    def _project(self, row):
        out = dict(row)
        for m in re.finditer(r'(\w+)\(([^)]*)\)', self._select or ''):
            rel, cols = m.group(1), [c.strip() for c in m.group(2).split(',')]
            fk = {'event_fields': 'field_id', 'events': 'event_id',
                  'course_categories': 'category_id', 'courses': 'course_id',
                  'users': 'user_id'}.get(rel)
            if not fk:
                raise AssertionError(f'替身不知道 {rel} 要怎麼接，請補上')
            target = next((r for r in self.db.rows(rel)
                           if r.get('id') == row.get(fk)), None)
            out[rel] = {c: target.get(c) for c in cols} if target else None
        return out
