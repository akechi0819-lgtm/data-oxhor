SELECT 'work_orders' AS source,count(*) AS rows,count(DISTINCT "ID") AS distinct_order_ids,cast(max(DATE '1899-12-30'+cast(cast("分配时间" AS DOUBLE) AS INTEGER)) AS VARCHAR) AS max_business_date,NULL AS conflicting_cash_ids FROM landing.br_work_orders__sheet_1f0596db9f25
UNION ALL
SELECT 'cash',count(*),NULL,cast(max(DATE '1899-12-30'+cast(cast("业务日期" AS DOUBLE) AS INTEGER)) AS VARCHAR),count(*) FILTER(WHERE nullif(trim("工单ID"),'') IS NOT NULL AND nullif(trim("工单ID__2"),'') IS NOT NULL AND trim("工单ID")<>trim("工单ID__2")) FROM landing.br_cash__sheet_39b8dee2e4b3
