-- All-history work-order rows for P2 normalization. Run as bounded, half-open
-- date windows; the third parameter limits full source JSON to attachment dates.
WITH params AS (
  SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date,
    CAST(? AS DATE) AS attachment_start
), raw_orders AS (
  SELECT
    src.source_row_number,
    NULLIF(TRIM(src.ID), '') AS work_order_id,
    DATE '1899-12-30' + CAST(TRY_CAST(src.分配时间 AS DOUBLE) AS INTEGER) AS event_date,
    NULLIF(TRIM(src.团队), '') AS source_team,
    NULLIF(TRIM(src.跟进顾问), '') AS adviser,
    NULLIF(TRIM(src.顾问归属), '') AS adviser_belong,
    NULLIF(TRIM(src.跟进顾问), '') AS follow_adviser,
    NULLIF(TRIM(src.线上线下), '') AS online_offline,
    NULLIF(TRIM(src.主被动), '') AS main_active_type,
    NULLIF(TRIM(src.资源主被动), '') AS resource_active_type,
    NULLIF(TRIM(src.一级渠道), '') AS first_channel,
    NULLIF(TRIM(src.二级渠道), '') AS second_channel,
    NULLIF(TRIM(src.渠道), '') AS source_channel,
    NULLIF(TRIM(src.活动名称), '') AS campaign_name,
    NULLIF(TRIM(src.资源录入人), '') AS resource_entry_person,
    NULLIF(TRIM(src.资源描述), '') AS resource_description,
    NULLIF(TRIM(src.咨询方式一级渠道), '') AS source_path,
    NULLIF(TRIM(src.转介绍人), '') AS referrer,
    NULLIF(TRIM(src.其他转介绍人), '') AS other_referrer,
    NULLIF(TRIM(src."意向国家/地区"), '') AS intended_country_source,
    NULLIF(TRIM(src.学生学校名称), '') AS student_school,
    NULLIF(TRIM(src.所在学校), '') AS current_school,
    NULLIF(TRIM(src.年级属性), '') AS grade_attr,
    NULLIF(TRIM(src.目前年级), '') AS current_grade,
    NULLIF(TRIM(src.年级名称), '') AS grade_name,
    NULLIF(TRIM(src.工单状态), '') AS order_status,
    CASE WHEN DATE '1899-12-30' + CAST(TRY_CAST(src.分配时间 AS DOUBLE) AS INTEGER)
      >= p.attachment_start THEN to_json(src) END AS source_record,
    ROW_NUMBER() OVER (
      PARTITION BY NULLIF(TRIM(src.ID), '')
      ORDER BY src.source_row_number
    ) AS id_row_number
  FROM landing.br_work_orders__sheet_1f0596db9f25 AS src
  CROSS JOIN params AS p
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
  grade_name,
  order_status,
  source_record
FROM bounded
ORDER BY event_date, work_order_id;
