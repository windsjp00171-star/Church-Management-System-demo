"""教材庫存由異動紀錄計算。

以前 material_stock 直接讀 materials.stock，但沒有任何程式會更新那一欄：
庫存永遠是 0、登記銷售永遠「庫存不足」，頁面上的累計銷售與進貨成本是空白。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / 'schema.sql').read_text(encoding='utf-8')
MIGRATION = ROOT / 'migrations/025_material_stock_view.sql'


def _view(sql):
    return re.search(r'CREATE OR REPLACE VIEW material_stock AS(.*?);', sql, re.S).group(1)


def test_view_is_computed_from_transactions_and_has_every_column_the_pages_read():
    view = _view(SCHEMA)
    assert 'material_transactions' in view
    pages = ''.join((ROOT / 'templates/courses' / n).read_text(encoding='utf-8')
                    for n in ('admin_materials.html', 'admin_material_detail.html'))
    for col in set(re.findall(r'\b(?:m|material)\.(total_\w+)', pages)):
        assert re.search(rf'\bAS {col}\b', view), col


def test_migration_matches_schema():
    migration = _view(MIGRATION.read_text(encoding='utf-8'))
    assert re.sub(r'\s+', ' ', migration) == re.sub(r'\s+', ' ', _view(SCHEMA))


def test_view_comes_after_the_table_it_reads():
    assert SCHEMA.index('CREATE TABLE IF NOT EXISTS material_transactions') < SCHEMA.index('VIEW material_stock')


def test_old_columns_keep_their_order_so_replace_works_on_existing_sites():
    """CREATE OR REPLACE VIEW 只能在最後面加欄位，動到既有順序會整個失敗。"""
    cols = [a or b for a, b in re.findall(r'\bm\.(\w+),|AS (\w+)', _view(SCHEMA).split('FROM materials')[0])]
    assert cols[:9] == ['id', 'name', 'description', 'unit', 'selling_price',
                        'category_id', 'stock', 'is_active', 'created_at']
