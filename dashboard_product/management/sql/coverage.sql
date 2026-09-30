WITH orders AS (
 SELECT DATE '1899-12-30' + CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER) AS d
 FROM landing.br_work_orders__sheet_1f0596db9f25
), cash AS (
 SELECT DATE '1899-12-30' + CAST(TRY_CAST(业务日期 AS DOUBLE) AS INTEGER) AS d
 FROM landing.br_cash__sheet_39b8dee2e4b3
)
SELECT
 (SELECT CAST(MIN(d) AS VARCHAR) FROM orders) AS orders_start,
 (SELECT CAST(MAX(d) AS VARCHAR) FROM orders) AS orders_end,
 (SELECT COUNT(*) FROM orders WHERE d IS NULL) AS orders_missing_date,
 (SELECT CAST(MIN(d) AS VARCHAR) FROM cash) AS cash_start,
 (SELECT CAST(MAX(d) AS VARCHAR) FROM cash) AS cash_end,
 (SELECT COUNT(*) FROM cash WHERE d IS NULL) AS cash_missing_date;
