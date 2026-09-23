WITH params AS (
 SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date
), orders_raw AS (
 SELECT
  NULLIF(TRIM(ID),'') AS work_order_id,
  DATE '1899-12-30'+CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER) AS event_date,
  source_row_number,
  TRIM(团队) AS source_team,
  TRIM(主被动) AS active_type,
  TRIM(线上线下) AS online_offline,
  TRIM(二级渠道) AS second_channel,
  NULLIF(TRIM(一级渠道),'') AS first_channel,
  NULLIF(TRIM(活动名称),'') AS campaign_name,
  ROW_NUMBER() OVER(PARTITION BY NULLIF(TRIM(ID),'') ORDER BY source_row_number) rn
 FROM landing.br_work_orders__sheet_1f0596db9f25
), orders_dim AS (
 SELECT *,
  CASE WHEN online_offline='线下' THEN 'offline_market'
       WHEN second_channel='虚拟人' THEN 'online_private'
       WHEN online_offline='线上' THEN 'online_platform' END AS team_id
 FROM orders_raw
 WHERE rn=1 AND work_order_id IS NOT NULL
), unassigned_orders AS (
 SELECT
  o.event_date,
  o.source_row_number,
  'work_orders' AS metric,
  o.work_order_id,
  o.source_team,
  o.online_offline,
  COALESCE(o.first_channel,'未归类') AS first_channel,
  COALESCE(o.second_channel,'未细分') AS second_channel,
  o.campaign_name,
  CASE
   WHEN NULLIF(TRIM(o.online_offline),'') IS NULL THEN '线上线下字段为空，且二级渠道不是虚拟人'
   ELSE '线上线下字段“'||TRIM(o.online_offline)||'”未匹配，且二级渠道不是虚拟人'
  END AS team_reason,
  1.0::DOUBLE AS actual_value
 FROM orders_dim o CROSS JOIN params
 WHERE o.team_id IS NULL
  AND o.active_type='被动'
  AND o.event_date>=start_date AND o.event_date<end_date
), cash_raw AS (
 SELECT
  NULLIF(TRIM(工单ID),'') AS work_order_id,
  DATE '1899-12-30'+CAST(TRY_CAST(业务日期 AS DOUBLE) AS INTEGER) AS cash_date,
  source_row_number,
  TRIM(团队) AS source_team,
  CASE WHEN TRIM(团队)='青少' THEN '青少'
       WHEN TRIM(团队) IN ('初中','初中国际学科') THEN '初中'
       WHEN TRIM(团队) IN ('高中','ICC','国际学科') THEN '高中'
       WHEN TRIM(团队)='大学' THEN '大学' END AS cash_business_group,
  TRIM(渠道) AS channel,
  市场活动名称 AS cash_campaign_name,
  TRY_CAST(REPLACE(REPLACE(TRIM(报入现金收入),',',''),'￥','') AS DECIMAL(38,2)) AS cash_amount
 FROM landing.br_cash__sheet_39b8dee2e4b3, params
 WHERE TRIM(渠道属性)='被动'
  AND TRIM(新老生类型)='新生'
  AND TRY_CAST(REPLACE(REPLACE(TRIM(报入现金收入),',',''),'￥','') AS DECIMAL(38,2))>0
  AND DATE '1899-12-30'+CAST(TRY_CAST(业务日期 AS DOUBLE) AS INTEGER)>=start_date
  AND DATE '1899-12-30'+CAST(TRY_CAST(业务日期 AS DOUBLE) AS INTEGER)<end_date
), unassigned_cash AS (
 SELECT
  c.cash_date AS event_date,
  c.source_row_number,
  'passive_reported_cash' AS metric,
  c.work_order_id,
  c.source_team,
  o.online_offline,
  CASE
   WHEN o.work_order_id IS NOT NULL THEN COALESCE(o.first_channel,'暂无归属')
   WHEN c.cash_business_group IS NULL THEN COALESCE(NULLIF(TRIM(c.channel),''),'渠道/顾问暂无法拆分')
   ELSE '渠道/顾问暂无法拆分'
  END AS first_channel,
  CASE
   WHEN o.work_order_id IS NOT NULL THEN COALESCE(o.second_channel,'暂无归属')
   WHEN c.cash_business_group IS NULL THEN COALESCE(NULLIF(TRIM(c.cash_campaign_name),''),NULLIF(TRIM(c.channel),''),'渠道/顾问暂无法拆分')
   ELSE '渠道/顾问暂无法拆分'
  END AS second_channel,
  COALESCE(o.campaign_name,c.cash_campaign_name) AS campaign_name,
  CASE
   WHEN c.work_order_id IS NULL THEN '现金工单ID为空，无法匹配团队'
   WHEN o.work_order_id IS NULL THEN '现金工单ID未匹配有效工单'
   WHEN NULLIF(TRIM(o.online_offline),'') IS NULL THEN '已匹配工单，但线上线下字段为空且二级渠道不是虚拟人'
   ELSE '已匹配工单，但线上线下字段“'||TRIM(o.online_offline)||'”未匹配且二级渠道不是虚拟人'
  END AS team_reason,
  c.cash_amount::DOUBLE AS actual_value
 FROM cash_raw c
 LEFT JOIN orders_dim o ON c.work_order_id=o.work_order_id
 WHERE o.team_id IS NULL
)
SELECT event_date,source_row_number,metric,work_order_id,source_team,online_offline,first_channel,second_channel,campaign_name,team_reason,actual_value
FROM unassigned_orders
UNION ALL
SELECT event_date,source_row_number,metric,work_order_id,source_team,online_offline,first_channel,second_channel,campaign_name,team_reason,actual_value
FROM unassigned_cash
ORDER BY event_date,metric,work_order_id,source_row_number;
