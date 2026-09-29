WITH order_dates AS (
  SELECT MAX(DATE '1899-12-30' + CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER)) AS max_date
  FROM landing.br_work_orders__sheet_1f0596db9f25
), cash_dates AS (
  SELECT MAX(DATE '1899-12-30' + CAST(TRY_CAST(业务日期 AS DOUBLE) AS INTEGER)) AS max_date
  FROM landing.br_cash__sheet_39b8dee2e4b3
)
SELECT CAST(order_dates.max_date AS VARCHAR) AS work_orders_max_date,
       CAST(cash_dates.max_date AS VARCHAR) AS cash_max_date
FROM order_dates CROSS JOIN cash_dates;
