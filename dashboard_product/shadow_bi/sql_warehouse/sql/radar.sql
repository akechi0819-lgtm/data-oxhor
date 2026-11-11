-- 与旧 Decimal 分摊保持一致：整数商构造权重，避免 DuckDB 的 / 提前转 DOUBLE。
-- 本次完整参照的分母为 1–4、金额为整分；scale 30 聚合绝对和小于 1,277,201。
CREATE OR REPLACE VIEW business.radar_events AS
WITH matched AS (
 SELECT f.*,p.name,p.home_team,p.home_group,list_contains(p.team_ids,'online_private') AS virtual,
 CASE WHEN f.business_line='training' THEN 'training' WHEN customer_domain IN ('study_abroad','small_language') THEN customer_domain ELSE 'unmapped' END AS domain
 FROM business.personnel_facts f JOIN config.radar_people p ON f.business_line=p.business_line
 AND list_contains(list_distinct(coalesce(f.owners,[]::VARCHAR[])||
  CASE WHEN f.business_line='training' THEN coalesce(f.virtual_owners,[]::VARCHAR[]) ELSE []::VARCHAR[] END),p.name)
 CROSS JOIN config.clock c
 WHERE CAST(f.event_date AS DATE) BETWEEN DATE '2026-06-01' AND least(c.through_date,DATE '2027-05-31')
 AND (f.metric<>'orders' OR coalesce(f.counts_toward_completion,true) AND coalesce(f.order_status,'') NOT IN ('删除','回收'))
 AND (f.business_line<>'abroad' OR coalesce(f.segment_id,'') NOT IN ('international_market','ssc','unassigned') AND coalesce(f.personal_eligible,true))
), weighted AS (
 SELECT *,CASE WHEN virtual THEN 1::decimal(38,28) ELSE CASE WHEN (count(*) FILTER(WHERE NOT virtual) OVER(PARTITION BY fact_id))=1 THEN 1::decimal(38,28) ELSE cast('0.'||lpad((10000000000000000000000000000::hugeint//(count(*) FILTER(WHERE NOT virtual) OVER(PARTITION BY fact_id)))::varchar,28,'0') as decimal(38,28)) END END AS weight
 FROM matched
)
SELECT *,CASE WHEN business_line='training' THEN
 CASE WHEN contains(coalesce(first_channel,''),'TMK') THEN 'tmk'
 WHEN first_channel='市场活动' AND second_channel IN ('异业渠道','线下校代') THEN 'partner'
 WHEN first_channel='市场活动' THEN 'campaign' END
 ELSE CASE WHEN contains(upper(coalesce(first_channel,'')),'TMK') THEN 'tmk'
 WHEN first_channel='市场活动' THEN 'campaign' WHEN first_channel IN ('渠道合作','官方合作高校') THEN 'partner' END END AS cash_bucket
FROM weighted;

CREATE OR REPLACE VIEW business.radar_products AS
WITH domain_keys AS (
 SELECT p.*,d.domain FROM config.radar_people p CROSS JOIN (VALUES ('training'),('study_abroad'),('small_language'),('unmapped')) d(domain)
 WHERE p.business_line='training' AND d.domain='training' OR p.business_line='abroad' AND d.domain<>'training'
), heads AS (
 SELECT name,domain,student_id,max(weight) AS weight FROM business.radar_events
 WHERE metric='cash' AND value>0 AND nullif(trim(student_id),'') IS NOT NULL GROUP BY ALL
), head_totals AS (SELECT name,domain,sum(weight) AS heads FROM heads GROUP BY ALL),
sums AS (
 SELECT name,domain,sum(value*weight) FILTER(WHERE metric='orders') AS orders,
 sum(value*weight) FILTER(WHERE metric='cash') AS cash,
 count(*) FILTER(WHERE metric='cash' AND value>0 AND nullif(trim(student_id),'') IS NULL)>0 AS missing_identity,
 count(*) FILTER(WHERE metric='cash' AND value>0)>0 AS positive_cash
 FROM business.radar_events GROUP BY ALL
)
SELECT k.*,coalesce(s.orders,0) AS orders,coalesce(s.cash,0) AS cash,
 CASE WHEN coalesce(s.missing_identity,false) OR domain='unmapped' AND coalesce(s.positive_cash,false) THEN NULL
  ELSE coalesce(h.heads,0) END AS heads,coalesce(s.positive_cash,false) AS positive_cash
FROM domain_keys k LEFT JOIN sums s USING(name,domain) LEFT JOIN head_totals h USING(name,domain);

CREATE OR REPLACE VIEW business.radar_people AS
WITH totals AS (
 SELECT name,sum(orders) AS orders,sum(cash) AS cash,
 CASE WHEN count(*) FILTER(WHERE domain IN ('study_abroad','small_language') AND positive_cash)>1
  OR count(*) FILTER(WHERE heads IS NULL)>0 THEN NULL ELSE sum(heads) END AS heads
 FROM business.radar_products GROUP BY name
), buckets AS (
 SELECT name,sum(value*weight) FILTER(WHERE metric='cash' AND cash_bucket='partner') AS partner,
 sum(value*weight) FILTER(WHERE metric='cash' AND cash_bucket='tmk') AS tmk,
 sum(value*weight) FILTER(WHERE metric='cash' AND cash_bucket='campaign') AS campaign
 FROM business.radar_events GROUP BY name
), targets AS (
 SELECT t.name,CASE WHEN count(amount)=12 AND min(amount)>=0 THEN sum(amount) END AS cash_capacity,
 CASE WHEN count(amount)=12 AND min(amount)>=0 THEN
 sum(amount*greatest(0,least(date_diff('day',CAST(month||'-01' AS DATE),c.through_date)+1,
  day(last_day(CAST(month||'-01' AS DATE))))) / day(last_day(CAST(month||'-01' AS DATE)))) END AS target_to_date
 FROM config.radar_month_targets t CROSS JOIN config.clock c GROUP BY t.name
), result AS (
 SELECT p.*,t.orders,t.cash,t.heads,t.heads/nullif(t.orders,0) AS conversion,
 coalesce(b.partner,0) AS partner,coalesce(b.tmk,0) AS tmk,coalesce(b.campaign,0) AS campaign,
 CASE WHEN p.business_line='training' THEN cap.amount ELSE target.cash_capacity END AS cash_capacity,
 CASE WHEN p.business_line='training' THEN cap.amount*(date_diff('day',DATE '2026-06-01',least(c.through_date,DATE '2027-05-31'))+1)/365.0 ELSE target.target_to_date END AS target_to_date,
 DATE '2026-06-01' AS start_date,least(c.through_date,DATE '2027-05-31') AS through_date
 FROM config.radar_people p JOIN totals t USING(name) LEFT JOIN buckets b USING(name)
 LEFT JOIN targets target USING(name) CROSS JOIN config.radar_training_target cap CROSS JOIN config.clock c
)
SELECT *,cash/nullif(target_to_date,0) AS cash_progress_completion,
 business_line||'|'||home_group AS peer_group,
 count(*) OVER(PARTITION BY home_team,home_group,business_line) AS peer_count
FROM result;

CREATE OR REPLACE VIEW business.radar_axes AS
WITH axes AS (
 SELECT r.*,d.axis,d.label,CASE d.axis WHEN 'orders' THEN orders WHEN 'heads' THEN heads WHEN 'conversion' THEN conversion
  WHEN 'partner' THEN partner WHEN 'tmk' THEN tmk ELSE campaign END AS value
 FROM business.radar_people r CROSS JOIN (VALUES ('orders','工单数'),('heads','签约量'),('conversion','转化率'),
  ('partner','渠道／校代现金'),('tmk','TMK现金'),('campaign','活动现金')) d(axis,label)
), compared AS (
 SELECT *,-- 旧 Python 3.12 在已转 float 的同组值上 sum/len；仅此处使用补偿求和。
 fsum(value) OVER(PARTITION BY home_team,home_group,business_line,axis)/count(value) OVER(PARTITION BY home_team,home_group,business_line,axis) AS mean,
 max(value) OVER(PARTITION BY home_team,home_group,business_line,axis) AS peak FROM axes
)
SELECT name,axis,label,value,mean,value/nullif(mean,0)-1 AS relative,
 CASE WHEN peak>0 THEN peak ELSE 1 END AS scale,peer_count,start_date,through_date FROM compared;
