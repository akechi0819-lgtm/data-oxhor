WITH params AS (
  SELECT
    CAST(? AS DATE) AS start_date,
    CAST(? AS DATE) AS end_date,
    CAST(? AS VARCHAR) AS team_id,
    CAST(? AS VARCHAR) AS business_group
),
orders_dim AS (
  SELECT
    NULLIF(TRIM(ID), '') AS work_order_id,
    CASE
      WHEN TRIM(线上线下) = '线下' THEN 'offline_market'
      WHEN TRIM(二级渠道) = '虚拟人' THEN 'online_private'
      WHEN TRIM(线上线下) = '线上' THEN 'online_platform'
    END AS team_id
  FROM (
    SELECT
      wo.*,
      ROW_NUMBER() OVER (PARTITION BY NULLIF(TRIM(ID), '') ORDER BY source_row_number) AS rn
    FROM landing.br_work_orders__sheet_1f0596db9f25 wo
    WHERE TRIM(主被动) = '被动'
  ) ranked
  WHERE rn = 1 AND NULLIF(TRIM(ID), '') IS NOT NULL
),
classified AS (
  SELECT
    cash.*,
    DATE '1899-12-30' + CAST(TRY_CAST(业务日期 AS DOUBLE) AS INTEGER) AS _cash_date,
    CASE
      WHEN o.team_id IS NOT NULL THEN o.team_id
      WHEN STRPOS(COALESCE(cash.市场活动名称, ''), '虚拟人') > 0 THEN 'online_private'
      WHEN STRPOS(COALESCE(cash.市场活动名称, ''), '线上') > 0 THEN 'online_platform'
      WHEN UPPER(COALESCE(cash.渠道, '')) LIKE '%TMK%' THEN 'offline_market'
      WHEN STRPOS(COALESCE(cash.市场活动名称, ''), '校代') > 0 THEN 'offline_market'
      ELSE 'online_platform'
    END AS _mapped_team_id,
    CASE
      WHEN TRIM(cash.团队) IN ('青少', '初中', '初中国际学科') THEN '留学预备'
      WHEN TRIM(cash.团队) IN ('高中', 'ICC', '国际学科') THEN '高中'
      WHEN TRIM(cash.团队) = '大学' THEN '大学'
    END AS _mapped_business_group
  FROM landing.br_cash__sheet_39b8dee2e4b3 cash
  LEFT JOIN orders_dim o
    ON NULLIF(TRIM(cash.工单ID), '') = o.work_order_id
  WHERE TRIM(cash.渠道属性) = '被动'
    AND TRIM(cash.新老生类型) = '新生'
    AND TRY_CAST(REPLACE(REPLACE(TRIM(cash.报入现金收入), ',', ''), '￥', '') AS DECIMAL(38, 2)) > 0
)
SELECT classified.* EXCLUDE (_cash_date, _mapped_team_id, _mapped_business_group)
FROM classified
CROSS JOIN params
WHERE classified._mapped_team_id = params.team_id
  AND (params.business_group IS NULL OR classified._mapped_business_group = params.business_group)
  AND classified._cash_date >= params.start_date
  AND classified._cash_date < params.end_date
ORDER BY classified.source_row_number
