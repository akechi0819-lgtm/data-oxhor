-- All-history work-order rows for P2 normalization. Run as bounded, half-open
-- date windows; the caller supplies the confirmed start/end dates.
WITH params AS (
  SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date
), raw_orders AS (
  SELECT
    source_row_number,
    NULLIF(TRIM(ID), '') AS work_order_id,
    DATE '1899-12-30' + CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER) AS event_date,
    NULLIF(TRIM(团队), '') AS source_team,
    NULLIF(TRIM(跟进顾问), '') AS adviser,
    NULLIF(TRIM(顾问归属), '') AS adviser_belong,
    NULLIF(TRIM(跟进顾问), '') AS follow_adviser,
    NULLIF(TRIM(线上线下), '') AS online_offline,
    NULLIF(TRIM(主被动), '') AS main_active_type,
    NULLIF(TRIM(资源主被动), '') AS resource_active_type,
    NULLIF(TRIM(一级渠道), '') AS first_channel,
    NULLIF(TRIM(二级渠道), '') AS second_channel,
    NULLIF(TRIM(渠道), '') AS source_channel,
    NULLIF(TRIM(活动名称), '') AS campaign_name,
    NULLIF(TRIM(资源录入人), '') AS resource_entry_person,
    NULLIF(TRIM(资源描述), '') AS resource_description,
    NULLIF(TRIM(咨询方式一级渠道), '') AS source_path,
    NULLIF(TRIM(转介绍人), '') AS referrer,
    NULLIF(TRIM(其他转介绍人), '') AS other_referrer,
    NULLIF(TRIM("意向国家/地区"), '') AS intended_country_source,
    NULLIF(TRIM(学生学校名称), '') AS student_school,
    NULLIF(TRIM(所在学校), '') AS current_school,
    NULLIF(TRIM(年级属性), '') AS grade_attr,
    NULLIF(TRIM(目前年级), '') AS current_grade,
    NULLIF(TRIM(年级名称), '') AS grade_name,
    ROW_NUMBER() OVER (
      PARTITION BY NULLIF(TRIM(ID), '')
      ORDER BY source_row_number
    ) AS id_row_number
  FROM landing.br_work_orders__sheet_1f0596db9f25
), bounded AS (
  SELECT r.*
  FROM raw_orders r CROSS JOIN params p
  WHERE r.id_row_number = 1
    AND r.work_order_id IS NOT NULL
    AND r.event_date >= p.start_date
    AND r.event_date < p.end_date
)
SELECT
  source_row_number,
  work_order_id,
  event_date,
  source_team,
  adviser,
  adviser_belong,
  follow_adviser,
  online_offline,
  main_active_type,
  resource_active_type,
  first_channel,
  second_channel,
  source_channel,
  campaign_name,
  resource_entry_person,
  resource_description,
  source_path,
  referrer,
  other_referrer,
  intended_country_source,
  student_school,
  current_school,
  grade_attr,
  current_grade,
  grade_name
FROM bounded
ORDER BY event_date, work_order_id;
