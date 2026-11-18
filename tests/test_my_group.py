"""「這個人是哪一組」只有一份：牧養小組（盤點第 6 步，2026-11-17）

以前另有「主標籤小組」（`users.group_tags` ∩ `groups.is_primary`），禱讀本、門訓名單、首頁版面、
收費提醒、第一次登入各讀各的，跟牧養小組可能不一樣。現在全部走 `routes/my_group.py`。
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent


def _sb(rows):
    c = MagicMock()
    for m in ('select', 'eq', 'in_', 'order'):
        getattr(c, m).return_value = c
    c.execute.return_value.data = rows
    return MagicMock(table=MagicMock(return_value=c)), c


def test_of_users_only_confirmed_active_and_one_group_each(fake_db):
    from routes import my_group
    sb, c = _sb([{'user_id': 'u1', 'cell_groups': {'name': '活水', 'is_active': True}},
                 {'user_id': 'u1', 'cell_groups': {'name': '第二組', 'is_active': True}},
                 {'user_id': 'u2', 'cell_groups': {'name': '已停用', 'is_active': False}}])
    with patch.object(my_group, 'supabase', sb):
        assert my_group.of_users(['u1', 'u2', None]) == {'u1': '活水'}
    c.eq.assert_any_call('is_confirmed', True)             # 自己選、還沒確認的不算
    c.eq.assert_any_call('is_active', True)


def test_db_failure_is_empty_not_a_crash(fake_db):
    from routes import my_group
    boom = MagicMock(table=MagicMock(side_effect=RuntimeError))
    with patch.object(my_group, 'supabase', boom):
        assert my_group.of_users(['u1']) == {} and my_group.names() == []


def _code(rel):
    import ast
    src = (ROOT / rel).read_text(encoding='utf-8')
    tree = ast.parse(src)
    for n in ast.walk(tree):                                 # 去掉 docstring，免得說明文字讓守衛自己通過
        if isinstance(n, (ast.FunctionDef, ast.Module)) and ast.get_docstring(n):
            n.body = n.body[1:]
    return ast.unparse(tree)


def test_no_one_reads_primary_tags_for_who_is_in_which_group():
    for rel in ('routes/devotional.py', 'routes/courses.py', 'routes/bible_plan.py', 'routes/event.py'):
        code = _code(rel)
        assert "eq('is_primary', True)" not in code and 'primary_group_names' not in code, rel
    assert 'my_group' in _code('routes/admin.py').split('def _primary_group_names_safe')[1].split('\ndef ')[0]


def test_first_login_picks_a_cell_group_not_a_primary_tag():
    for rel in ('templates/onboarding.html', 'templates/profile/setup.html'):
        tpl = (ROOT / rel).read_text(encoding='utf-8')
        assert 'id="cell-group-select"' in tpl and "cell_group_id:" in tpl, rel
        assert "selectattr('is_primary', 'ne', false)" not in tpl, rel
    code = _code('routes/profile.py')
    assert code.count('_request_cell_group(session[') == 2       # onboarding＋setup 都送申請
    assert code.count("eq('is_primary', False)") >= 2            # 標籤那一區只剩服事團隊
