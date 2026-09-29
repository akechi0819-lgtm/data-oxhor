WITH params AS (
  SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date
), raw AS (
  SELECT
    NULLIF(TRIM(ID), '') AS work_order_id,
    source_row_number,
    DATE '1899-12-30' + CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER) AS event_date,
    NULLIF(TRIM(团队), '') AS source_team,
    NULLIF(TRIM(跟进顾问), '') AS adviser,
    NULLIF(TRIM(主被动), '') AS main_active_type,
    NULLIF(TRIM(资源主被动), '') AS resource_active_type,
    NULLIF(TRIM(线上线下), '') AS online_offline,
    NULLIF(TRIM(一级渠道), '') AS first_channel,
    NULLIF(TRIM(二级渠道), '') AS second_channel,
    NULLIF(TRIM(咨询方式一级渠道), '') AS source_path,
    NULLIF(TRIM(渠道), '') AS source_channel,
    NULLIF(TRIM("意向国家/地区"), '') AS intended_country_source,
    NULL::VARCHAR AS intended_country_existing,
    NULL::VARCHAR AS corrected_line_existing,
    NULLIF(TRIM(资源描述), '') AS resource_description,
    NULLIF(TRIM(顾问归属), '') AS adviser_belong,
    NULLIF(TRIM(年级校正), '') AS grade_correction,
    NULLIF(TRIM(活动名称), '') AS campaign_name,
    NULLIF(TRIM(学生学校名称), '') AS school_name,
    NULLIF(TRIM(年级名称), '') AS grade_name,
    NULLIF(TRIM(COALESCE(
      NULLIF(regexp_extract(COALESCE(资源描述, ''), '市场人员[[:space:]]*[:：][[:space:]]*([^[:space:],，;；]+)', 1), ''),
      资源录入人
    )), '') AS entry_person,
    ROW_NUMBER() OVER (
      PARTITION BY NULLIF(TRIM(ID), '')
      ORDER BY source_row_number
    ) AS rn
  FROM landing.br_work_orders__sheet_1f0596db9f25
)
SELECT
  work_order_id, source_row_number, event_date, source_team, adviser,
  main_active_type, resource_active_type, online_offline,
  first_channel, second_channel, source_path, source_channel,
  intended_country_source, intended_country_existing, corrected_line_existing,
  resource_description, adviser_belong, grade_correction, campaign_name,
  school_name, grade_name, entry_person
FROM raw, params
WHERE rn = 1
  AND work_order_id IS NOT NULL
  AND source_team IS NULL
  AND event_date >= start_date
  AND event_date < end_date
ORDER BY event_date, source_row_number;
