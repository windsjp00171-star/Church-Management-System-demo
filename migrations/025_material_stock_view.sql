-- 025：教材庫存由異動紀錄計算
--
-- 為什麼：material_stock 原本直接讀 materials.stock，但沒有任何程式會更新那一欄——
-- 庫存永遠是 0、登記銷售永遠「庫存不足」，累計銷售與進貨成本兩欄空白。
--
-- 影響：只換檢視表的算法，不改任何資料；既有的異動紀錄會立刻反映在庫存上。
-- 有人用 SQL 手動填過 materials.stock 的話，那個數字不再使用，請補一筆「庫存調整」異動。
-- 可重複執行。
-- 還原：CREATE OR REPLACE VIEW 不能減欄位，要先 DROP VIEW material_stock，再建回舊的定義。
CREATE OR REPLACE VIEW material_stock AS
    SELECT m.id, m.name, m.description, m.unit, m.selling_price, m.category_id,
           COALESCE(SUM(CASE t.type WHEN 'in' THEN t.quantity WHEN 'out' THEN -t.quantity
                                    WHEN 'adjust' THEN t.quantity END), 0)::int AS stock,
           m.is_active, m.created_at,
           COALESCE(SUM(CASE WHEN t.type = 'in' THEN t.total_cost END), 0)::int AS total_purchased_cost,
           COALESCE(SUM(CASE WHEN t.type = 'out' THEN t.quantity END), 0)::int AS total_sold_qty
    FROM materials m LEFT JOIN material_transactions t ON t.material_id = m.id
    WHERE m.is_active = TRUE
    GROUP BY m.id;
