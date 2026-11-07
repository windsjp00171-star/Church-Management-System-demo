"""裝飾器順序：權限檢查（login_required、pastor_required…）必須在路由裝飾器『下面』。

Flask 的 @bp.route 把『當下這個函式』登記起來。權限裝飾器寫在它上面的話，
登記進去的是沒有包過權限檢查的原始函式 —— 程式看起來有檢查，實際完全沒有，也沒有任何錯誤。
實際發生過：牧者儀表板的 @pastor_required 寫在 @route 上面，未登入的人打開就是 200，看得到所有小組的回報。
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTE_ATTRS = {'route', 'get', 'post', 'put', 'delete', 'patch', 'before_request', 'after_request',
               'context_processor', 'errorhandler', 'app_errorhandler', 'teardown_request'}


def _is_registration(dec):
    f = dec.func if isinstance(dec, ast.Call) else dec
    return isinstance(f, ast.Attribute) and f.attr in ROUTE_ATTRS


def _py_files():
    skip = {'tests', '.git', '.codegraph', 'node_modules', '__pycache__'}
    return [p for p in ROOT.rglob('*.py') if not skip & set(p.parts)]


def test_no_decorator_sits_above_a_route_registration():
    bad = []
    for p in _py_files():
        for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                idx = [i for i, d in enumerate(node.decorator_list) if _is_registration(d)]
                if idx and idx[0] > 0:
                    bad.append(f'{p.relative_to(ROOT)}:{node.lineno} {node.name} '
                               f'（{[ast.unparse(d) for d in node.decorator_list[:idx[0]]]} 在路由裝飾器上面）')
    assert not bad, bad


def test_the_scanner_can_see_the_bug():
    """守衛自己要驗：把錯誤寫法丟給它，它必須抓得到（不然它會安靜地變瞎）。"""
    src = "@login_required\n@bp.get('/x')\ndef f():\n    pass\n"
    node = ast.parse(src).body[0]
    idx = [i for i, d in enumerate(node.decorator_list) if _is_registration(d)]
    assert idx == [1] and idx[0] > 0
