-- 原语培市场总盘：按原表被动工单和业务组映射统计，含删除/回收，按ID去重；不套用留学专项SSC排除。
WITH params AS (SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date),
orders_raw AS (
 SELECT NULLIF(TRIM(ID),'') AS work_order_id,
 DATE '1899-12-30'+CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER) AS event_date,
 TRIM(团队) AS source_team,
 TRIM(顾问归属) AS adviser_belong,
 TRIM(跟进顾问) AS follow_adviser,
 TRIM(主被动) AS active_type, TRIM(工单状态) AS order_status,
 TRIM(年级校正) AS grade_correction,
 TRIM(线上线下) AS online_offline, TRIM(二级渠道) AS second_channel, NULLIF(TRIM(一级渠道),'') AS first_channel, NULLIF(TRIM(活动名称),'') AS campaign_name,
 NULLIF(TRIM(学生学校名称),'') AS school_name, NULLIF(TRIM(年级名称),'') AS grade_name, NULLIF(TRIM(COALESCE(
   NULLIF(regexp_extract(COALESCE(资源描述, ''), '市场人员[[:space:]]*[:：][[:space:]]*([^[:space:],，;；]+)', 1), ''),
   资源录入人
 )),'') AS entry_person,
 ROW_NUMBER() OVER(PARTITION BY NULLIF(TRIM(ID),'') ORDER BY source_row_number) rn
 FROM landing.br_work_orders__sheet_1f0596db9f25
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
 SELECT work_order_id, business_group, active_type, online_offline, second_channel, first_channel, campaign_name, school_name, grade_name, entry_person,
 CASE WHEN online_offline='线下' THEN 'offline_market'
      WHEN second_channel='虚拟人' THEN 'online_private'
      WHEN online_offline='线上' THEN 'online_platform' END AS team_id
 FROM mapped_orders WHERE rn=1 AND work_order_id IS NOT NULL
), orders AS (
 SELECT r.work_order_id, event_date, COALESCE(r.business_group, '业务组暂无法拆分') AS business_group,
 o.team_id AS team_id,
 r.first_channel, r.second_channel, r.campaign_name, r.school_name, r.grade_name,
 r.entry_person AS entry_person,
 1.0::DOUBLE actual_value, 'work_orders' metric, NULL AS student_id,
 NULL AS cash_channel, r.active_type AS work_order_active_type, NULL AS cash_campaign_name
 FROM mapped_orders r
 JOIN orders_dim o ON r.work_order_id = o.work_order_id
 CROSS JOIN params
 WHERE r.rn=1 AND r.work_order_id IS NOT NULL AND r.active_type='被动' AND event_date>=start_date AND event_date<end_date
)
SELECT * FROM orders ORDER BY event_date, work_order_id
