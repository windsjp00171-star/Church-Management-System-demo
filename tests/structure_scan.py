"""結構守衛的掃描工具（只讀原始碼，不執行程式）。測試與基準更新腳本共用。"""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = Path(__file__).resolve().parent / 'structure_baseline.json'
ADMIN_GATES = {'admin_required', 'super_admin_required'}
ROUTE_METHODS = {'route', 'get', 'post', 'put', 'delete', 'patch'}


def py_files():
    return sorted(list((ROOT / 'routes').glob('*.py')) + [p for p in ROOT.glob('*.py')])


def rel(p):
    return str(p.relative_to(ROOT))


def strip_py(src):
    """去掉註解與 docstring 再掃，避免說明文字造成誤判。"""
    src = re.sub(r'"""[\s\S]*?"""', '', src)
    src = re.sub(r"'''[\s\S]*?'''", '', src)
    return re.sub(r'(?m)#[^\n]*', '', src)


def users_table_hits():
    """每個檔案直接 `.table('users')` 的次數。"""
    out = {}
    for f in py_files():
        n = len(re.findall(r"\.table\(\s*['\"]users['\"]\s*\)", strip_py(f.read_text(encoding='utf-8'))))
        if n:
            out[rel(f)] = n
    return out


def date_today_hits():
    """依伺服器時區取今天的寫法（`date.today()`、`datetime.now()` 不帶時區、`utcnow()`）。"""
    out = {}
    for f in py_files():
        tree = ast.parse(f.read_text(encoding='utf-8'))
        n = 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            a = node.func.attr
            if a in ('today', 'utcnow') and not node.args:
                n += 1
            elif a == 'now' and not node.args and not node.keywords:
                n += 1
        if n:
            out[rel(f)] = n
    return out


def _decorator_name(d):
    if isinstance(d, ast.Call):
        d = d.func
    if isinstance(d, ast.Name):
        return d.id
    if isinstance(d, ast.Attribute):
        return d.attr
    return None


def _route_path(d):
    if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
        return d.args[0].value
    return None


def admin_routes():
    """所有掛在 /admin 底下的路由：(檔案, 函式, 完整路徑, 裝飾器名稱集合)。"""
    found = []
    for f in sorted((ROOT / 'routes').glob('*.py')):
        tree = ast.parse(f.read_text(encoding='utf-8'))
        prefixes = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                    and _decorator_name(node.value) == 'Blueprint':
                prefix = ''
                for kw in node.value.keywords:
                    if kw.arg == 'url_prefix' and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        prefixes[t.id] = prefix
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {_decorator_name(d) for d in node.decorator_list}
            for d in node.decorator_list:
                if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and d.func.attr in ROUTE_METHODS and isinstance(d.func.value, ast.Name)):
                    continue
                path = _route_path(d)
                if path is None:
                    continue
                full = prefixes.get(d.func.value.id, '') + path
                if full.startswith('/admin') or full.startswith('/api/admin'):
                    found.append((rel(f), node.name, full, names))
    return found


def ungated_admin_routes():
    """沒有 admin_required／super_admin_required 的 /admin 路由，格式 `檔案::函式`。"""
    return sorted({f'{f}::{fn}' for f, fn, _, names in admin_routes() if not (names & ADMIN_GATES)})


INLINE_CHECK = re.compile(
    r"session\.get\(\s*['\"](is_admin|is_super_admin)['\"]\s*\)|_has_finance_access\(\)|_require_admin\(")
STAFF_GATES = {'staff_required', 'pastor_required'}


def unprotected_admin_routes():
    """/admin 路由裡，既沒有裝飾器閘門（admin／super_admin／staff／pastor）、
    函式開頭也沒有手寫的管理員檢查的。這種路由等於對任何人開放。"""
    out = []
    for f in sorted((ROOT / 'routes').glob('*.py')):
        src = f.read_text(encoding='utf-8')
        funcs = {n.name: n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)}
        for fname, fn, _, names in admin_routes():
            if fname != rel(f) or names & (ADMIN_GATES | STAFF_GATES):
                continue
            node = funcs[fn]
            head = '\n'.join(src.splitlines()[node.lineno - 1: node.lineno + 7])
            if not INLINE_CHECK.search(head):
                out.append(f'{fname}::{fn}')
    return sorted(set(out))


def or_zero_hits():
    out = {}
    for f in py_files():
        n = len(re.findall(r'\bor 0\b', strip_py(f.read_text(encoding='utf-8'))))
        if n:
            out[rel(f)] = n
    return out


def current():
    return {
        'users_table_hits': users_table_hits(),
        'date_today_hits': date_today_hits(),
        'ungated_admin_routes': ungated_admin_routes(),
        'or_zero_hits': or_zero_hits(),
    }


def load_baseline():
    return json.loads(BASELINE_FILE.read_text(encoding='utf-8'))


if __name__ == '__main__':      # python tests/structure_scan.py  → 重新產生基準（只在「減少」之後執行）
    BASELINE_FILE.write_text(json.dumps(current(), ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                             encoding='utf-8')
    print('baseline updated:', BASELINE_FILE)
