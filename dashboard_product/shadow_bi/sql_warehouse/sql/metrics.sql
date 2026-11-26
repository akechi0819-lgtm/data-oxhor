CREATE OR REPLACE VIEW business.facts AS
SELECT * FROM business.training_facts UNION ALL BY NAME SELECT * FROM business.abroad_facts;

CREATE OR REPLACE VIEW business.personnel_facts AS
SELECT * FROM business.training_personnel_facts UNION ALL BY NAME SELECT * FROM business.abroad_facts;

CREATE OR REPLACE VIEW business.periods AS
WITH definitions AS (
 SELECT 'FY27' AS period_id, 'year' AS kind, DATE '2026-06-01' AS start_date, DATE '2027-05-31' AS end_date,'2027财年全年' AS label
 UNION ALL
 SELECT 'Q'||(i+1)::VARCHAR,'quarter', (DATE '2026-06-01'+i*INTERVAL '3 months')::DATE,
   (DATE '2026-06-01'+(i+1)*INTERVAL '3 months'-INTERVAL '1 day')::DATE,
   '第'||substring('一二三四',i+1,1)||'季度' FROM range(4) t(i)
 UNION ALL
 SELECT strftime(DATE '2026-06-01'+i*INTERVAL '1 month','%Y-%m'),'month',
   (DATE '2026-06-01'+i*INTERVAL '1 month')::DATE,
   (DATE '2026-06-01'+(i+1)*INTERVAL '1 month'-INTERVAL '1 day')::DATE,
   year(DATE '2026-06-01'+i*INTERVAL '1 month')::VARCHAR||'年'||month(DATE '2026-06-01'+i*INTERVAL '1 month')::VARCHAR||'月' FROM range(12) t(i)
)
SELECT d.*, CASE WHEN c.through_date>=d.start_date THEN least(d.end_date,c.through_date) END AS through_date,
 CASE WHEN c.through_date<d.start_date THEN 'future' ELSE 'available' END AS status,
 CASE WHEN c.through_date<d.start_date THEN 0 ELSE
  (date_diff('day',d.start_date,least(d.end_date,c.through_date))+1)::DOUBLE/(date_diff('day',d.start_date,d.end_date)+1) END AS time_progress,
 (date_trunc('month',d.start_date)-INTERVAL '1 month'+INTERVAL '25 days')::DATE AS personal_start,
 (date_trunc('month',d.end_date)+INTERVAL '24 days')::DATE AS personal_end
FROM definitions d CROSS JOIN config.clock c;

CREATE OR REPLACE VIEW business.scopes AS
SELECT *,NULL::INTEGER AS selection_mask FROM (VALUES
 ('total',NULL,NULL,NULL),('prep','offline_market','留学预备',NULL),
 ('high','offline_market','高中',NULL),('university','offline_market','大学','study_abroad_offline'),
 ('overview_prep',NULL,'留学预备',NULL),('overview_high',NULL,'高中',NULL),
 ('overview_university',NULL,'大学',NULL),
 ('virtual','online_private',NULL,'study_abroad_virtual'),('online','online_platform',NULL,'study_abroad_online'),
 ('international_market',NULL,NULL,'international_market'),('ssc',NULL,NULL,'ssc'),('unassigned',NULL,NULL,'unassigned'),
 ('offline_scope','offline_market',NULL,'study_abroad_offline'),('online_scope','__online__',NULL,'study_abroad_online')
) t(unit_id,source_team,business_group,abroad_segment)
UNION ALL SELECT 'selection_'||i::VARCHAR,'offline_market',NULL,NULL,i::INTEGER FROM range(1,8) t(i);

CREATE OR REPLACE VIEW business.acquisition_scopes AS
SELECT * FROM (VALUES
 ('被动','被动','全部'),('主动','主动','全部'),('全部','全部','全部'),
 ('被动|新生','被动','新生'),('被动|老生','被动','老生'),
 ('主动|新生','主动','新生'),('主动|老生','主动','老生'),
 ('全部|新生','全部','新生'),('全部|老生','全部','老生')
) t(acquisition_scope,acquisition_mode,student_type_scope);

-- Scope selection happens before class/student head qualification.
CREATE OR REPLACE VIEW business.scoped_facts AS
SELECT s.unit_id,a.acquisition_scope,f.*
FROM business.facts f JOIN business.scopes s ON
 ((s.unit_id='total' AND (f.business_line<>'abroad' OR f.segment_id IS DISTINCT FROM 'ssc'))
 OR CASE WHEN f.business_line='training' THEN
   (s.unit_id IN ('overview_prep','overview_high','overview_university') AND f.business_group=s.business_group)
   OR (s.source_team IS NOT NULL AND (f.team_id=s.source_team OR s.source_team='__online__' AND f.team_id IN ('online_private','online_platform'))
    AND f.business_group IN ('留学预备','高中','大学')
    AND (s.business_group IS NULL OR f.business_group=s.business_group)
    AND (s.selection_mask IS NULL OR
     f.comparison_group='青少' AND (s.selection_mask & 1)>0 OR
     f.comparison_group='初中' AND (s.selection_mask & 2)>0 OR
     f.comparison_group='高中' AND (s.selection_mask & 4)>0))
 ELSE s.abroad_segment IS NOT NULL AND
   (f.segment_id=s.abroad_segment OR s.unit_id IN ('online','online_scope')
    AND f.segment_id='study_abroad_virtual') END)
CROSS JOIN business.acquisition_scopes a
WHERE (f.business_line<>'training' OR a.acquisition_mode='全部' OR f.acquisition_mode=a.acquisition_mode)
 AND (f.business_line<>'training' OR f.metric<>'cash' OR a.student_type_scope='全部'
      OR f.student_type=a.student_type_scope);

CREATE OR REPLACE VIEW business.period_events AS
SELECT p.period_id,p.kind,p.status,p.time_progress,f.*,w.comparison,
 CASE WHEN f.business_line='abroad' THEN greatest(p.start_date,c.abroad_start) ELSE p.start_date END AS covered_start,
 CASE WHEN f.business_line='abroad' THEN least(p.through_date,c.abroad_through) ELSE p.through_date END AS covered_through
FROM business.periods p CROSS JOIN config.clock c
CROSS JOIN (VALUES ('actual'),('prior')) w(comparison)
JOIN business.scoped_facts f ON
 CASE WHEN w.comparison='actual' THEN CAST(f.event_date AS DATE) BETWEEN p.start_date AND p.through_date
 ELSE CAST(f.event_date AS DATE) BETWEEN (p.start_date-INTERVAL '1 year')::DATE AND (p.through_date-INTERVAL '1 year')::DATE END
WHERE (f.business_line='training' OR w.comparison='actual')
 AND (f.business_line<>'abroad' OR CAST(f.event_date AS DATE) BETWEEN c.abroad_start AND c.abroad_through);

CREATE OR REPLACE VIEW business.team_values AS
WITH sums AS (
 SELECT period_id,unit_id,acquisition_scope,business_line,comparison,
  sum(value) FILTER(WHERE metric='orders') AS orders,
  round(sum(value) FILTER(WHERE metric='cash'),2) AS cash
 FROM business.period_events GROUP BY ALL
), training_classes AS (
 SELECT period_id,unit_id,acquisition_scope,business_line,comparison,student_id,class_code
 FROM business.period_events WHERE business_line='training' AND metric='cash' AND nullif(trim(student_id),'') IS NOT NULL
 GROUP BY ALL HAVING abs(sum(value))>=1500 AND bool_or(registration_count>0)
), training_heads AS (
 SELECT period_id,unit_id,acquisition_scope,business_line,comparison,count(DISTINCT student_id) AS heads
 FROM training_classes GROUP BY ALL
), abroad_heads AS (
 SELECT period_id,unit_id,acquisition_scope,business_line,comparison,
  CASE WHEN count(DISTINCT CASE WHEN customer_domain IN ('study_abroad','small_language') THEN customer_domain END)>1
   THEN NULL ELSE count(DISTINCT student_id) END AS heads,
  count(DISTINCT CASE WHEN customer_domain='study_abroad' THEN student_id END) AS study_heads,
  count(DISTINCT CASE WHEN customer_domain='small_language' THEN student_id END) AS language_heads
 FROM business.period_events WHERE business_line='abroad' AND metric='cash' AND value>0 AND nullif(trim(student_id),'') IS NOT NULL
 GROUP BY ALL
), keys AS (
 SELECT p.period_id,s.unit_id,a.acquisition_scope,l.business_line,w.comparison
 FROM business.periods p CROSS JOIN business.scopes s
 CROSS JOIN business.acquisition_scopes a
 CROSS JOIN (VALUES ('training'),('abroad')) l(business_line)
 CROSS JOIN (VALUES ('actual'),('prior')) w(comparison)
)
SELECT k.*,coalesce(s.orders,0) AS orders,coalesce(s.cash,0) AS cash,
 CASE WHEN k.business_line='training' THEN coalesce(t.heads,0)
  WHEN b.study_heads>0 AND b.language_heads>0 THEN NULL ELSE coalesce(b.heads,0) END AS heads,
 coalesce(b.study_heads,0) AS study_heads,coalesce(b.language_heads,0) AS language_heads
FROM keys k LEFT JOIN sums s USING(period_id,unit_id,acquisition_scope,business_line,comparison)
 LEFT JOIN training_heads t USING(period_id,unit_id,acquisition_scope,business_line,comparison)
 LEFT JOIN abroad_heads b USING(period_id,unit_id,acquisition_scope,business_line,comparison);

CREATE OR REPLACE VIEW business.team_targets AS
WITH source AS (
 SELECT * FROM config.targets
 UNION ALL
 SELECT business_line,business_group,team_id,'FY27',metric,
   CASE WHEN count(*)=4 AND count(target)=4 THEN sum(target) END
 FROM config.targets WHERE business_line='training' AND period_id IN ('Q1','Q2','Q3','Q4') GROUP BY ALL
), mapped AS (
 SELECT p.period_id,s.unit_id,t.business_line,t.metric,
   CASE WHEN t.business_line='training' THEN
    CASE WHEN s.selection_mask IS NOT NULL AND (s.selection_mask & 3) IN (1,2) THEN NULL
    WHEN count(t.target)=CASE WHEN s.unit_id='total' THEN 9 WHEN s.unit_id='online_scope' THEN 6
      WHEN s.unit_id IN ('overview_prep','overview_high','overview_university') THEN 3
      WHEN s.selection_mask IS NOT NULL THEN (CASE WHEN (s.selection_mask & 3)=3 THEN 1 ELSE 0 END+CASE WHEN (s.selection_mask & 4)>0 THEN 1 ELSE 0 END)
      WHEN s.business_group IS NULL THEN 3 ELSE 1 END THEN sum(t.target) END
   ELSE CASE WHEN count(t.target)=count(*) THEN sum(t.target) END END AS target
 FROM business.periods p CROSS JOIN business.scopes s JOIN source t ON t.period_id=p.period_id
 AND ((t.business_line='training' AND
   ((s.unit_id='total') OR
    ((t.team_id=s.source_team OR s.source_team='__online__' AND t.team_id IN ('online_private','online_platform')
      OR s.unit_id IN ('overview_prep','overview_high','overview_university')
       AND t.team_id IN ('offline_market','online_private','online_platform'))
     AND (s.business_group IS NULL OR t.business_group=s.business_group)
     AND (s.selection_mask IS NULL OR t.business_group='留学预备' AND (s.selection_mask & 3)=3 OR t.business_group='高中' AND (s.selection_mask & 4)>0))))
   OR (t.business_line='abroad' AND t.team_id=s.unit_id))
 GROUP BY p.period_id,s.unit_id,s.business_group,s.selection_mask,t.business_line,t.metric
)
SELECT * FROM mapped;

CREATE OR REPLACE VIEW business.team_metrics AS
WITH measures AS (
 SELECT v.*,m.metric,CASE m.metric WHEN 'orders' THEN v.orders WHEN 'cash' THEN v.cash ELSE v.heads END AS value
 FROM business.team_values v CROSS JOIN (VALUES ('orders'),('cash'),('heads')) m(metric)
), pivoted AS (
 SELECT period_id,unit_id,acquisition_scope,business_line,metric,
  max(value) FILTER(WHERE comparison='actual') AS actual,
  max(value) FILTER(WHERE comparison='prior') AS prior
 FROM measures GROUP BY ALL
), marked AS (
 SELECT x.*,p.time_progress,t.target,
 CASE WHEN business_line='abroad' AND unit_id IN ('overview_prep','overview_high','overview_university') THEN 'not_configured'
  WHEN business_line='abroad' AND starts_with(unit_id,'selection_') THEN 'not_configured'
  WHEN p.status='future' THEN 'future'
  WHEN business_line='abroad' AND (unit_id IN ('prep','high') OR starts_with(unit_id,'selection_')) THEN 'not_configured'
  WHEN business_line='abroad' AND (p.through_date<c.abroad_start OR p.start_date>c.abroad_through) THEN 'not_covered'
  WHEN business_line='abroad' AND metric='heads' AND actual IS NULL THEN 'separate_counts'
  WHEN business_line='abroad' AND (p.start_date<c.abroad_start OR p.through_date>c.abroad_through) THEN 'partial'
  ELSE 'available' END AS status
 FROM pivoted x JOIN business.periods p USING(period_id) CROSS JOIN config.clock c
 LEFT JOIN business.team_targets t USING(period_id,unit_id,business_line,metric)
)
SELECT * EXCLUDE(actual,prior,target),
 CASE WHEN status IN ('future','not_configured','not_covered') THEN NULL ELSE actual END AS actual,
 CASE WHEN business_line='abroad' OR status='future' THEN NULL ELSE prior END AS prior,
 CASE WHEN business_line='training' AND (split_part(acquisition_scope,'|',1)<>'被动' OR unit_id='total' AND metric='orders')
  OR status='not_configured' THEN NULL ELSE target END AS target,
 CASE WHEN business_line='abroad' AND unit_id IN ('prep','high') THEN '本部门暂不统计留学完成；贡献见人员产能。'
  WHEN business_line='abroad' AND starts_with(unit_id,'selection_') THEN '不纳部门留学考核；个人贡献单独展示。'
  WHEN business_line='training' AND starts_with(unit_id,'selection_') AND metric IN ('orders','cash') AND target IS NULL AND status<>'future'
   THEN '所选组合未单独下达目标，不按比例拆分留学预备整体目标。' ELSE '' END AS note
FROM marked;

CREATE OR REPLACE VIEW business.school_channels AS
SELECT period_id,unit_id,acquisition_scope,business_line,comparison,
 coalesce(first_channel,'一级来源待确认') AS channel,
 coalesce(school_attribute,'学校类别待确认') AS school_category,
 coalesce(channel_school_name,school_name,'学校待确认') AS school,
 sum(value) FILTER(WHERE metric='orders') AS orders,
 round(sum(value) FILTER(WHERE metric='cash'),2) AS cash
FROM business.period_events GROUP BY ALL;
