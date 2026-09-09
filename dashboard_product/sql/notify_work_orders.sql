WITH params AS (
  SELECT
    CAST(? AS DATE) AS start_date,
    CAST(? AS DATE) AS end_date,
    CAST(? AS VARCHAR) AS team_id,
    CAST(? AS VARCHAR) AS business_group
),
classified AS (
  SELECT
    wo.*,
    DATE '1899-12-30' + CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER) AS _event_date,
    CASE
      WHEN TRIM(团队) IN ('留学预备', '高中', '大学') THEN TRIM(团队)
      WHEN TRIM(年级属性) LIKE '%留学预备%' THEN '留学预备'
      WHEN TRIM(年级属性) LIKE '%高中%' OR TRIM(年级名称) LIKE '%高中%' THEN '高中'
      WHEN TRIM(年级属性) LIKE '%大学%' OR TRIM(年级属性) LIKE '%研究生%' OR TRIM(年级名称) LIKE '%大学%' THEN '大学'
    END AS _mapped_business_group,
    CASE
      WHEN TRIM(线上线下) = '线下' THEN 'offline_market'
      WHEN TRIM(二级渠道) = '虚拟人' THEN 'online_private'
      WHEN TRIM(线上线下) = '线上' THEN 'online_platform'
    END AS _mapped_team_id
  FROM landing.br_work_orders__sheet_1f0596db9f25 wo
  WHERE TRIM(主被动) = '被动'
)
SELECT classified.* EXCLUDE (_event_date, _mapped_business_group, _mapped_team_id)
FROM classified
CROSS JOIN params
WHERE classified._mapped_team_id = params.team_id
  AND (params.business_group IS NULL OR classified._mapped_business_group = params.business_group)
  AND classified._event_date >= params.start_date
  AND classified._event_date < params.end_date
ORDER BY classified.source_row_number
