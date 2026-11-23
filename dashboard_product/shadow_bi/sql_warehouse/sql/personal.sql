-- 与旧 Decimal 分摊保持一致：整数商构造权重，避免 DuckDB 的 / 提前转 DOUBLE。
-- 本次完整参照的分母为 1–4、金额为整分；scale 30 聚合绝对和小于 1,277,201。
CREATE OR REPLACE VIEW business.personal_weight_candidates AS
WITH names AS (
 SELECT f.*,p.name,p.business_line AS person_line,p.home_group,p.team_ids,
 p.training_roster,p.abroad_roster,list_contains(p.team_ids,'online_private') AS virtual,
 regexp_replace(coalesce(f.campaign_name,''),'（[^）]*）|\([^)]*\)',' ','g') AS outside_campaign,
 list_contains(coalesce(f.owners,[]::VARCHAR[]),p.name) AS regular_owner,
 list_contains(coalesce(f.virtual_owners,[]::VARCHAR[]),p.name) AS virtual_owner
 FROM business.personnel_facts f JOIN config.people p ON
 list_contains(list_distinct(coalesce(f.owners,[]::VARCHAR[])||coalesce(f.virtual_owners,[]::VARCHAR[])),p.name)
), marked AS (
 SELECT *,NOT virtual AND contains(outside_campaign,name) AS primary_person,
 NOT virtual AND NOT contains(outside_campaign,name) AND contains(coalesce(campaign_name,''),name) AS secondary_person
 FROM names
), groups AS (
 SELECT fact_id,count(*) FILTER(WHERE NOT virtual) AS offline_count,
 count(*) FILTER(WHERE primary_person) AS primary_count,
 count(*) FILTER(WHERE secondary_person) AS secondary_count,
 count(DISTINCT person_line) FILTER(WHERE primary_person) AS primary_lines,
 max(person_line) FILTER(WHERE primary_person) AS primary_line,
 count(*) FILTER(WHERE NOT virtual AND NOT primary_person AND NOT secondary_person) AS unmatched_count
 FROM marked GROUP BY fact_id
), counts AS (
 SELECT m.*,g.* EXCLUDE(fact_id),
 count(*) FILTER(WHERE primary_person OR secondary_person AND person_line=g.primary_line) OVER(PARTITION BY m.fact_id) AS creators,
 count(*) FILTER(WHERE secondary_person AND person_line=m.business_line AND person_line<>g.primary_line) OVER(PARTITION BY m.fact_id) AS receivers
 FROM marked m JOIN groups g USING(fact_id)
)
SELECT *,CASE
 WHEN virtual THEN 1::decimal(38,28)
 WHEN primary_count=0 OR secondary_count=0 OR primary_lines<>1 OR primary_line NOT IN ('training','abroad') OR unmatched_count<>0
 THEN CASE WHEN (offline_count)=1 THEN 1::decimal(38,28) ELSE cast('0.'||lpad((10000000000000000000000000000::hugeint//(offline_count))::varchar,28,'0') as decimal(38,28)) END
 WHEN business_line=primary_line OR receivers=0 THEN
  CASE WHEN primary_person OR secondary_person AND person_line=primary_line THEN CASE WHEN (creators)=1 THEN 1::decimal(38,28) ELSE cast('0.'||lpad((10000000000000000000000000000::hugeint//(creators))::varchar,28,'0') as decimal(38,28)) END ELSE 0 END
 WHEN primary_person OR secondary_person AND person_line=primary_line THEN CASE WHEN (creators*2)=1 THEN 1::decimal(38,28) ELSE cast('0.'||lpad((10000000000000000000000000000::hugeint//(creators*2))::varchar,28,'0') as decimal(38,28)) END
 WHEN secondary_person AND person_line=business_line THEN CASE WHEN (receivers*2)=1 THEN 1::decimal(38,28) ELSE cast('0.'||lpad((10000000000000000000000000000::hugeint//(receivers*2))::varchar,28,'0') as decimal(38,28)) END
 ELSE 0 END AS weight
FROM counts;

CREATE OR REPLACE VIEW business.personal_allocations AS
SELECT * FROM business.personal_weight_candidates
WHERE weight>0 AND coalesce(segment_id,'')<>'international_market'
 AND (NOT(metric='cash' AND coalesce(team_inferred,false)) OR virtual)
 AND (business_line='abroad' OR
  virtual AND NOT(metric='orders' AND order_status='无效') OR
  NOT virtual AND list_contains(team_ids,team_id) AND home_group IS NOT NULL AND business_group=home_group)
 AND CASE WHEN metric IN ('orders','cash') AND virtual THEN virtual_owner ELSE regular_owner END;

CREATE OR REPLACE VIEW business.personal_windows AS
SELECT p.period_id,p.kind,m.month_mode,
 CASE WHEN c.through_date<CASE WHEN m.month_mode='performance' THEN p.personal_start ELSE p.start_date END THEN 'future' ELSE 'available' END AS status,
 CASE WHEN m.month_mode='performance' THEN p.personal_start ELSE p.start_date END AS start_date,
 least(CASE WHEN m.month_mode='performance' THEN p.personal_end ELSE p.end_date END,c.through_date) AS through_date,
 CASE WHEN m.month_mode='performance' THEN p.personal_end ELSE p.end_date END AS end_date
FROM business.periods p CROSS JOIN config.clock c CROSS JOIN (VALUES ('calendar'),('performance')) m(month_mode);

-- 原状态值保留为“全部”；类型后缀仅供市场总览的新老生筛选使用。
CREATE OR REPLACE VIEW business.personal_states AS
SELECT s.order_state, t.student_type_scope,
 s.order_state || CASE WHEN t.student_type_scope='全部' THEN '' ELSE '|'||t.student_type_scope END AS state
FROM (VALUES ('00'),('01'),('10'),('11')) s(order_state)
CROSS JOIN (VALUES ('全部'),('新生'),('老生')) t(student_type_scope);

CREATE OR REPLACE VIEW business.personal_events AS
SELECT w.period_id,w.month_mode,w.start_date,w.through_date,s.state,x.comparison,a.*
FROM business.personal_windows w CROSS JOIN business.personal_states s
CROSS JOIN (VALUES ('actual'),('prior')) x(comparison)
JOIN business.personal_allocations a ON CASE WHEN x.comparison='actual'
 THEN CAST(a.event_date AS DATE) BETWEEN w.start_date AND w.through_date
 ELSE CAST(a.event_date AS DATE) BETWEEN (w.start_date-INTERVAL '1 year')::DATE AND (w.through_date-INTERVAL '1 year')::DATE END
WHERE (a.business_line<>'training' OR a.metric<>'cash' OR s.student_type_scope='全部'
 OR a.student_type=s.student_type_scope)
 AND (a.metric<>'orders' OR
 ((coalesce(a.order_status,'') NOT IN ('删除','回收') OR left(s.order_state,1)='1')
 AND (coalesce(a.order_status,'')<>'死单' OR right(s.order_state,1)='1')
 AND (a.order_status IN ('删除','回收','死单') OR coalesce(a.counts_toward_completion,true))));

CREATE OR REPLACE VIEW business.personal_values AS
SELECT period_id,month_mode,state,comparison,name,business_line,metric,
 CASE WHEN metric='cash' THEN CAST(round(sum(value*weight),2) AS DOUBLE) ELSE CAST(sum(value*weight) AS DOUBLE) END AS value
FROM business.personal_events GROUP BY period_id,month_mode,state,comparison,name,business_line,metric;

CREATE OR REPLACE VIEW business.personal_heads AS
WITH students AS (
 SELECT period_id,month_mode,state,comparison,name,business_line,student_id,max(weight) AS weight
 FROM business.personal_events
 WHERE business_line='training' AND metric='cash' AND value>0 AND nullif(trim(student_id),'') IS NOT NULL
 AND regular_owner AND NOT coalesce(team_inferred,false)
 AND (business_line='abroad' OR list_contains(team_ids,team_id) AND business_group=home_group)
 GROUP BY ALL
)
SELECT period_id,month_mode,state,comparison,name,business_line,'heads' AS metric,sum(weight) AS value
FROM students GROUP BY ALL;

CREATE OR REPLACE VIEW business.personal_abroad_heads AS
SELECT period_id,month_mode,state,comparison,name,business_line,'heads' AS metric,
 CASE WHEN count(DISTINCT CASE WHEN customer_domain IN ('study_abroad','small_language') THEN customer_domain END)>1
  THEN NULL ELSE count(DISTINCT student_id) END AS value,
 count(DISTINCT CASE WHEN customer_domain IN ('study_abroad','small_language') THEN customer_domain END)>1 AS separate_counts,
 count(DISTINCT CASE WHEN customer_domain='study_abroad' THEN student_id END) AS study_heads,
 count(DISTINCT CASE WHEN customer_domain='small_language' THEN student_id END) AS language_heads
FROM business.personal_events
WHERE business_line='abroad' AND metric='cash' AND value>0 AND nullif(trim(student_id),'') IS NOT NULL AND regular_owner
GROUP BY ALL;

CREATE OR REPLACE VIEW business.personal_month_targets AS
WITH months AS (
 SELECT strftime(DATE '2026-06-01'+i*INTERVAL '1 month','%Y-%m') AS month FROM range(12) t(i)
), base AS (
 SELECT p.name,p.home_group,p.team_ids,p.business_line AS primary_line,m.month,l.business_line,
 t.target AS own_orders,override.target AS explicit_abroad,cash.target AS cash_target
 FROM config.people p CROSS JOIN months m CROSS JOIN (VALUES ('training'),('abroad')) l(business_line)
 LEFT JOIN config.personal_targets t ON t.name=p.name AND t.business_line=p.business_line AND t.month=m.month AND t.metric='orders'
 LEFT JOIN config.personal_targets override ON override.name=p.name AND override.business_line=p.business_line AND override.month=m.month AND override.metric='study_abroad_orders'
 LEFT JOIN config.personal_targets cash ON cash.name=p.name AND cash.business_line=p.business_line AND cash.month=m.month AND cash.metric='cash'
)
SELECT *,CASE WHEN business_line=primary_line THEN round(own_orders,0)
 WHEN home_group='大学' AND (primary_line<>'training' OR list_contains(team_ids,'offline_market')) THEN
  CASE WHEN primary_line='training' AND business_line='abroad' AND month='2026-11' AND explicit_abroad IS NOT NULL
   THEN round(explicit_abroad,0) ELSE round(own_orders*.1,0) END END AS order_target
FROM base;

CREATE OR REPLACE VIEW business.personal_metrics AS
WITH all_values AS (SELECT * FROM business.personal_values UNION ALL SELECT * FROM business.personal_heads
 UNION ALL SELECT period_id,month_mode,state,comparison,name,business_line,metric,value FROM business.personal_abroad_heads),
keys AS (
 SELECT w.period_id,w.month_mode,w.start_date,w.through_date,w.end_date,w.status,p.name,l.business_line,s.state,m.metric
 FROM business.personal_windows w CROSS JOIN config.people p
 CROSS JOIN (VALUES ('training'),('abroad')) l(business_line)
 CROSS JOIN business.personal_states s
 CROSS JOIN (VALUES ('orders'),('cash'),('heads')) m(metric)
), grouped AS (
 SELECT k.*,max(v.value) FILTER(WHERE comparison='actual') AS actual,
 max(v.value) FILTER(WHERE comparison='prior') AS prior
 FROM keys k LEFT JOIN all_values v USING(period_id,month_mode,name,business_line,state,metric) GROUP BY ALL
), targets AS (
 SELECT p.period_id,t.name,t.business_line,
 CASE WHEN count(t.order_target)=count(*) THEN sum(t.order_target) END AS order_target,
 CASE WHEN count(t.cash_target)=count(*) THEN sum(t.cash_target) END AS cash_target
 FROM business.periods p JOIN business.personal_month_targets t ON
 CAST(t.month||'-01' AS DATE) BETWEEN p.start_date AND p.end_date GROUP BY ALL
)
SELECT g.* EXCLUDE(actual,prior),
 CASE WHEN g.through_date>=start_date AND NOT coalesce(h.separate_counts,false) THEN coalesce(actual,0) END AS actual,
 CASE WHEN g.through_date>=start_date THEN coalesce(prior,0) END AS prior,
 CASE metric WHEN 'orders' THEN t.order_target WHEN 'cash' THEN t.cash_target END AS target,
 CASE WHEN g.status='future' THEN 0 ELSE (date_diff('day',start_date,g.through_date)+1)::DOUBLE/(date_diff('day',start_date,end_date)+1) END AS time_progress,
 CASE WHEN g.status='future' THEN 'future'
  WHEN business_line='abroad' AND (g.through_date<c.abroad_start OR start_date>c.abroad_through) THEN 'not_covered'
  WHEN business_line='abroad' AND coalesce(h.separate_counts,false) THEN 'separate_counts'
  WHEN business_line='abroad' AND (start_date<c.abroad_start OR g.through_date>c.abroad_through) THEN 'partial'
  ELSE 'available' END AS coverage_status
 ,coalesce(h.study_heads,0) AS study_heads,coalesce(h.language_heads,0) AS language_heads,
 CASE WHEN h.separate_counts THEN '留学'||h.study_heads::VARCHAR||'人／小语种'||h.language_heads::VARCHAR||'人' END AS heads_display
FROM grouped g LEFT JOIN targets t USING(period_id,name,business_line)
 LEFT JOIN business.personal_abroad_heads h USING(period_id,month_mode,name,business_line,state,metric)
CROSS JOIN config.clock c
WHERE h.comparison IS NULL OR h.comparison='actual';
