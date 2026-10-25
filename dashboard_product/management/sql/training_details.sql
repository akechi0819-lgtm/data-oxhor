-- V14派生逐笔事实；仅团队确认标签和保留ID/源行，不改变现金资格、金额精度或既有渠道归属。
WITH params AS (SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date,
  CAST(? AS DATE) AS attachment_start, CAST(? AS VARCHAR[]) AS study_advisers,
  CAST(? AS VARCHAR[]) AS prep_advisers, CAST(? AS VARCHAR[]) AS acquisition_modes),
normalized_orders AS (
 SELECT * REPLACE (
  CASE WHEN NULLIF(TRIM(团队),'') IS NULL AND NULLIF(TRIM(ID),'') IS NOT NULL
    AND (list_contains((SELECT study_advisers FROM params), TRIM(跟进顾问))
      OR list_contains((SELECT prep_advisers FROM params), TRIM(跟进顾问)))
  THEN CASE WHEN list_contains((SELECT prep_advisers FROM params), TRIM(跟进顾问))
    THEN '留学预备' ELSE '留学' END
  ELSE 团队 END AS 团队
 ),
 NULLIF(TRIM(src.工单状态),'') AS order_status,
 CASE WHEN DATE '1899-12-30'+CAST(TRY_CAST(src.分配时间 AS DOUBLE) AS INTEGER)
   >= (SELECT attachment_start FROM params) THEN to_json(src) END AS source_record
 FROM landing.br_work_orders__sheet_1f0596db9f25 AS src
),
orders_raw AS (
 SELECT source_row_number AS work_order_row_number, NULLIF(TRIM(ID),'') AS work_order_id,
 DATE '1899-12-30'+CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER) AS event_date,
 TRIM(团队) AS source_team,
 TRIM(顾问归属) AS adviser_belong,
 TRIM(跟进顾问) AS follow_adviser,
 TRIM(主被动) AS active_type,
 TRIM(年级校正) AS grade_correction,
 TRIM(线上线下) AS online_offline, TRIM(二级渠道) AS second_channel, NULLIF(TRIM(一级渠道),'') AS first_channel, NULLIF(TRIM(活动名称),'') AS campaign_name,
 NULLIF(TRIM(学生学校名称),'') AS school_name, NULLIF(TRIM(年级名称),'') AS grade_name, NULLIF(TRIM(COALESCE(
   NULLIF(regexp_extract(COALESCE(资源描述, ''), '市场人员[[:space:]]*[:：][[:space:]]*([^[:space:],，;；]+)', 1), ''),
   资源录入人
 )),'') AS entry_person,
 order_status,
 source_record,
 ROW_NUMBER() OVER(PARTITION BY NULLIF(TRIM(ID),'') ORDER BY source_row_number) rn
 FROM normalized_orders
), mapped_orders AS (
 SELECT *,
 CASE
  WHEN (source_team IN ('无法判断', '校区资源无法归属', '需要判定') OR source_team IS NULL OR source_team = '') AND follow_adviser = '张艺彤' THEN
   CASE
    WHEN grade_correction IN ('学龄前', '一年级', '二年级', '三年级', '四年级', '五年级')
      OR grade_correction LIKE '%小班%' OR grade_correction LIKE '%中班%' OR grade_correction LIKE '%大班%' THEN '青少'
    ELSE '初中'
   END
  WHEN source_team IN ('无法判断', '校区资源无法归属', '需要判定') OR source_team IS NULL OR source_team = '' THEN NULL
  WHEN adviser_belong IN ('武清顾问', '塘沽顾问', '塘沽学管') OR source_team IN ('武清', '塘沽') THEN
   CASE
    WHEN grade_correction IS NULL OR grade_correction IN ('', '未知') THEN '大学'
    WHEN grade_correction IN ('学龄前', '一年级', '二年级', '三年级', '四年级', '五年级', '六年级')
      OR grade_correction LIKE '%小班%' OR grade_correction LIKE '%中班%' OR grade_correction LIKE '%大班%' THEN '青少'
    WHEN grade_correction IN ('7年级（初一）', '8年级（初二）', '9年级（初三）')
      OR grade_correction LIKE '%初一%' OR grade_correction LIKE '%初二%' OR grade_correction LIKE '%初三%' THEN '初中'
    WHEN grade_correction IN ('10年级（高一）', '11年级（高二）', '12年级（高三）')
      OR grade_correction LIKE '%高一%' OR grade_correction LIKE '%高二%' OR grade_correction LIKE '%高三%' THEN '高中'
    ELSE '大学'
   END
  WHEN adviser_belong = '青少顾问' THEN '青少'
  WHEN adviser_belong = '初中顾问' THEN '初中'
  WHEN adviser_belong = '高中顾问' THEN '高中'
  WHEN adviser_belong IN ('大学顾问', '大学学管') THEN '大学'
  WHEN (adviser_belong IS NULL OR adviser_belong = '') AND source_team = '留学预备' THEN
   CASE
    WHEN grade_correction IN ('学龄前', '一年级', '二年级', '三年级', '四年级', '五年级')
      OR grade_correction LIKE '%小班%' OR grade_correction LIKE '%中班%' OR grade_correction LIKE '%大班%' THEN '青少'
    ELSE '初中'
   END
  WHEN source_team = '高中' THEN '高中'
  WHEN source_team = '大学' THEN '大学'
 END AS business_group
 FROM orders_raw
), orders_dim AS (
 SELECT work_order_id, business_group, active_type, online_offline, second_channel, first_channel, campaign_name, school_name, grade_name, entry_person, order_status,
 CASE WHEN online_offline='线下' THEN 'offline_market'
      WHEN second_channel='虚拟人' THEN 'online_private'
      WHEN online_offline='线上' THEN 'online_platform' END AS team_id
 FROM mapped_orders WHERE rn=1 AND work_order_id IS NOT NULL
), orders AS (
 SELECT r.work_order_row_number AS source_row_number, r.work_order_id, event_date, COALESCE(r.business_group, '业务组暂无法拆分') AS business_group,
 o.team_id AS team_id,
 r.first_channel, r.second_channel, r.campaign_name, r.campaign_name AS work_order_campaign_name, r.school_name, r.grade_name,
 r.entry_person AS entry_person,
 1.0::DOUBLE actual_value, 'work_orders' metric, NULL AS student_id,
 NULL AS cash_channel, r.active_type AS work_order_active_type, NULL AS cash_campaign_name,
 r.order_status, r.source_record, NULL AS cash_source_record, r.active_type AS acquisition_mode, NULL AS class_code, NULL::DOUBLE AS registration_count
 FROM mapped_orders r
 JOIN orders_dim o ON r.work_order_id = o.work_order_id
 CROSS JOIN params
 WHERE r.rn=1 AND r.work_order_id IS NOT NULL AND list_contains((SELECT acquisition_modes FROM params), r.active_type) AND event_date>=start_date AND event_date<end_date

), cash_raw AS (
 SELECT src.source_row_number AS cash_row_number, NULLIF(TRIM(src.工单ID),'') AS work_order_id,
 DATE '1899-12-30'+CAST(TRY_CAST(src.业务日期 AS DOUBLE) AS INTEGER) AS cash_date,
 CASE WHEN TRIM(src.团队)='青少' THEN '青少'
      WHEN TRIM(src.团队) IN ('初中','初中国际学科') THEN '初中'
      WHEN TRIM(src.团队) IN ('高中','ICC','国际学科') THEN '高中'
      WHEN TRIM(src.团队)='大学' THEN '大学' END AS cash_business_group,
 NULLIF(TRIM(src.班级编码),'') AS class_code, TRY_CAST(src.报名人次 AS DOUBLE) AS registration_count,
 TRIM(src.渠道) AS channel, TRIM(src.渠道属性) AS acquisition_mode,
 src.市场活动名称 AS cash_campaign_name,
 NULLIF(TRIM(src.生源校),'') AS school_name,
 NULLIF(TRIM(src.学员年级),'') AS grade_name,
 NULLIF(TRIM(src.学员编号),'') AS student_id,
 TRY_CAST(REPLACE(REPLACE(TRIM(src.报入现金收入),',',''),'￥','') AS DECIMAL(38,2)) AS cash_amount,
 CASE WHEN DATE '1899-12-30'+CAST(TRY_CAST(src.业务日期 AS DOUBLE) AS INTEGER)
   >= params.attachment_start THEN to_json(src) END AS cash_source_record
 FROM landing.br_cash__sheet_39b8dee2e4b3 AS src CROSS JOIN params
 WHERE list_contains((SELECT acquisition_modes FROM params), TRIM(src.渠道属性))
 AND TRIM(src.新老生类型)='新生'
 AND DATE '1899-12-30'+CAST(TRY_CAST(src.业务日期 AS DOUBLE) AS INTEGER)>=params.start_date
 AND DATE '1899-12-30'+CAST(TRY_CAST(src.业务日期 AS DOUBLE) AS INTEGER)<params.end_date

), cash_matched AS (
 SELECT c.cash_row_number AS source_row_number, c.work_order_id, c.cash_date AS event_date,
 o.team_id AS team_id,
 COALESCE(c.cash_business_group, '业务组暂无法拆分') AS business_group,
 CASE
  WHEN o.work_order_id IS NOT NULL THEN COALESCE(o.first_channel, '暂无归属')
  WHEN c.cash_business_group IS NULL THEN COALESCE(NULLIF(TRIM(c.channel),''), '渠道/顾问暂无法拆分')
  ELSE '渠道/顾问暂无法拆分' END AS first_channel,
 CASE
  WHEN o.work_order_id IS NOT NULL THEN COALESCE(o.second_channel, '暂无归属')
  WHEN c.cash_business_group IS NULL THEN COALESCE(NULLIF(TRIM(c.cash_campaign_name),''), NULLIF(TRIM(c.channel),''), '渠道/顾问暂无法拆分')
  ELSE '渠道/顾问暂无法拆分' END AS second_channel,
 COALESCE(o.campaign_name, c.cash_campaign_name) AS campaign_name,
 o.campaign_name AS work_order_campaign_name,
 CASE WHEN o.work_order_id IS NOT NULL THEN o.entry_person END AS entry_person,
 c.school_name,
 c.grade_name,
 c.cash_amount AS actual_value,
 'passive_reported_cash' AS metric,
 c.student_id,
 c.channel AS cash_channel,
 o.active_type AS work_order_active_type,
 c.cash_campaign_name AS cash_campaign_name,
 o.order_status, NULL AS source_record, c.cash_source_record, c.acquisition_mode, c.class_code, c.registration_count
 FROM cash_raw c
 LEFT JOIN orders_dim o
 ON c.work_order_id = o.work_order_id
)
SELECT source_row_number, work_order_id, event_date, team_id, business_group, first_channel, second_channel, campaign_name, work_order_campaign_name, entry_person, school_name, grade_name, metric, actual_value, student_id, cash_channel, work_order_active_type, cash_campaign_name, order_status, source_record, cash_source_record, acquisition_mode, class_code, registration_count FROM orders
UNION ALL
SELECT source_row_number, work_order_id, event_date, team_id, business_group, first_channel, second_channel, campaign_name, work_order_campaign_name, entry_person, school_name, grade_name, metric, actual_value, student_id, cash_channel, work_order_active_type, cash_campaign_name, order_status, source_record, cash_source_record, acquisition_mode, class_code, registration_count FROM cash_matched
ORDER BY event_date, team_id, business_group, metric, campaign_name;
