-- All-channel positive reported cash, grouped by cash date, student type, and business group.
WITH params AS (
  SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date
), normalized AS (
  SELECT
    DATE '1899-12-30' + CAST(TRY_CAST(src.业务日期 AS DOUBLE) AS INTEGER) AS cash_date,
    NULLIF(TRIM(src.新老生类型), '') AS student_type,
    CASE
      WHEN TRIM(src.团队) IN ('青少', '初中', '初中国际学科') THEN '留学预备'
      WHEN TRIM(src.团队) IN ('高中', 'ICC', '国际学科') THEN '高中'
      WHEN TRIM(src.团队) = '大学' THEN '大学'
      ELSE '业务组暂无法拆分'
    END AS business_group,
    TRY_CAST(REPLACE(REPLACE(TRIM(src.报入现金收入), ',', ''), '￥', '') AS DECIMAL(38,2)) AS cash_amount
  FROM landing.br_cash__sheet_39b8dee2e4b3 AS src
  CROSS JOIN params
  WHERE TRY_CAST(REPLACE(REPLACE(TRIM(src.报入现金收入), ',', ''), '￥', '') AS DECIMAL(38,2)) > 0
    AND DATE '1899-12-30' + CAST(TRY_CAST(src.业务日期 AS DOUBLE) AS INTEGER) >= params.start_date
    AND DATE '1899-12-30' + CAST(TRY_CAST(src.业务日期 AS DOUBLE) AS INTEGER) < params.end_date
)
SELECT cash_date, student_type, business_group, SUM(cash_amount)::DECIMAL(38,2) AS cash_amount
FROM normalized
GROUP BY cash_date, student_type, business_group
ORDER BY cash_date, student_type, business_group
