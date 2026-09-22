WITH params AS (
  SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date
), orders_raw AS (
  SELECT
    NULLIF(TRIM(ID), '') AS work_order_id,
    DATE '1899-12-30' + CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER) AS event_date,
    NULLIF(TRIM(团队), '') AS source_team,
    NULLIF(TRIM(主被动), '') AS active_type,
    NULLIF(TRIM(资源主被动), '') AS resource_active_type,
    NULLIF(TRIM(一级渠道), '') AS first_channel,
    NULLIF(TRIM(二级渠道), '') AS second_channel,
    NULLIF(TRIM(意向国家), '') AS intended_country,
    NULLIF(TRIM(矫正条线), '') AS corrected_line,
    NULLIF(TRIM(留学渠道清洗状态), '') AS channel_cleaning_status,
    NULLIF(TRIM(咨询方式一级渠道), '') AS source_path,
    NULLIF(TRIM(渠道), '') AS source_channel,
    source_row_number,
    ROW_NUMBER() OVER (
      PARTITION BY NULLIF(TRIM(ID), '')
      ORDER BY source_row_number
    ) AS rn
  FROM landing.br_work_orders__sheet_1f0596db9f25
), scoped AS (
  SELECT
    *,
    SPLIT_PART(COALESCE(source_path, ''), '-', 1) AS source_root
  FROM orders_raw
)
SELECT
  event_date,
  CASE source_root
    WHEN '网络资源' THEN '网络资源'
    WHEN '新媒体' THEN '新媒体'
  END AS channel_group,
  first_channel,
  CASE
    WHEN channel_cleaning_status = '已命中' THEN second_channel
    ELSE '当前规则未命中'
  END AS second_channel,
  intended_country,
  corrected_line,
  resource_active_type AS active_type,
  1.0 AS actual_value,
  'work_orders' AS metric
FROM scoped, params
WHERE rn = 1
  AND work_order_id IS NOT NULL
  AND source_team IS NULL
  AND source_root IN ('网络资源', '新媒体')
  AND (
    (source_root = '网络资源' AND resource_active_type IN ('被动', '主动'))
    OR (source_root = '新媒体' AND resource_active_type = '被动')
  )
  AND event_date >= start_date
  AND event_date < end_date
ORDER BY event_date, channel_group, second_channel, first_channel;
