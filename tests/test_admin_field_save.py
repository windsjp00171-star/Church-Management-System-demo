"""後台存活動欄位：建立與編輯兩條路徑都要做同樣三件事

1. 存之前先套監護人的自動條件（沒有生日欄位就擋下來）
2. 把 auto_tier 一起存（漏了的話，存一次活動就把「依生日自動判定」洗掉）
3. 資料庫 CHECK 約束擋下新型別時，翻成一句能照著做的話

★ 只改一條路徑的話，另一條照樣壞，而畫面完全正常。
  所以這裡對著兩個函式本體各驗一次（AST 切出函式，不是掃整份檔案）。
"""
import ast


def _fn(name):
    src = open('routes/admin.py', encoding='utf-8').read()
    lines = src.split('\n')
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return '\n'.join(lines[n.lineno - 1:n.end_lineno])
    raise AssertionError(name)


def test_both_save_paths_apply_the_guardian_condition_before_writing():
    for name in ('event_new', 'event_edit'):
        fn = _fn(name)
        i = fn.index('_apply_guardian_conditions(fields)')
        assert i < fn.index("table('event_fields').insert"), name
        assert "return jsonify({'error': guard_err}), 400" in fn, name


def test_both_save_paths_keep_auto_tier():
    for name in ('event_new', 'event_edit', 'event_clone'):
        assert "'auto_tier':" in _fn(name), f'{name} 沒有存 auto_tier'


def test_numbering_only_counts_named_fields():
    for name in ('event_new', 'event_edit'):
        fn = _fn(name)
        assert 'enumerate(_keep)' in fn, name
        assert 'enumerate(fields)' not in fn, name
