CREATE OR REPLACE VIEW business.activities AS
WITH events AS (
 SELECT *,coalesce(nullif(trim(campaign_name),''),'未填写活动') AS activity,
 CASE WHEN business_line='training' THEN 'training' ELSE customer_domain END AS domain
 FROM business.facts CROSS JOIN config.clock c
 WHERE CAST(event_date AS DATE)<=c.through_date AND (business_line<>'training' OR acquisition_mode='被动')
), sums AS (
 SELECT activity,coalesce(sum(value) FILTER(WHERE metric='orders' AND business_line='training'),0) AS training_orders,
 coalesce(sum(value) FILTER(WHERE metric='orders' AND business_line='abroad'),0) AS abroad_orders,
 round(coalesce(sum(value) FILTER(WHERE metric='cash'),0),2) AS cash,
 CASE WHEN bool_or(business_line='training') AND bool_or(business_line='abroad') THEN 'partial' ELSE 'available' END AS cash_status
 FROM events GROUP BY activity
), head_parts AS (
 SELECT activity,domain,count(DISTINCT student_id) AS heads FROM events
 WHERE metric='cash' AND value>0 AND nullif(trim(student_id),'') IS NOT NULL GROUP BY ALL
), heads AS (
 SELECT activity,CASE WHEN count(*)>1 THEN NULL ELSE sum(heads) END AS heads,
 to_json(list(struct_pack(label:=CASE domain WHEN 'training' THEN '语培' WHEN 'study_abroad' THEN '留学' ELSE '小语种' END,actual:=heads)
  ORDER BY CASE domain WHEN 'training' THEN 1 WHEN 'study_abroad' THEN 2 ELSE 3 END)) AS heads_parts,
 CASE WHEN count(*)>1 THEN string_agg(CASE domain WHEN 'training' THEN '语培' WHEN 'study_abroad' THEN '留学' ELSE '小语种' END||heads::VARCHAR||'人','／'
 ORDER BY CASE domain WHEN 'training' THEN 1 WHEN 'study_abroad' THEN 2 ELSE 3 END) END AS heads_display
 FROM head_parts GROUP BY activity
)
SELECT s.*,training_orders+abroad_orders AS orders,
 CASE WHEN h.activity IS NULL THEN 0 ELSE h.heads END AS heads,
 coalesce(heads_parts,'[]'::JSON) AS heads_parts,heads_display
FROM sums s LEFT JOIN heads h USING(activity);

CREATE OR REPLACE VIEW business.classification AS
SELECT p.period_id,'全盘（不随管理单元筛选）' AS scope,
 CASE WHEN p.through_date IS NULL THEN NULL ELSE count(o.work_order_id) FILTER(
 WHERE CAST(o.event_date AS DATE) BETWEEN p.start_date AND p.through_date) END AS actual_unclassified,
 CASE WHEN p.through_date IS NULL THEN NULL ELSE count(o.work_order_id) FILTER(
 WHERE CAST(o.event_date AS DATE) BETWEEN (p.start_date-INTERVAL '1 year')::DATE AND (p.through_date-INTERVAL '1 year')::DATE) END AS prior_unclassified,
 '全部仅指主动＋被动；这里的未分类记录不计入两类合计。' AS note
FROM business.periods p LEFT JOIN source.order_events o ON
 o.source_team IN ('塘沽','大学','无法判断','校区资源无法归属','武清','留学预备','需要判定','高中')
 AND coalesce(o.main_active_type,'') NOT IN ('主动','被动')
GROUP BY p.period_id,p.start_date,p.through_date;
