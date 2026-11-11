CREATE OR REPLACE TEMP VIEW notification_channels AS
WITH source_channels(channel_order,team_id,business_line,delivery_channel_id,title) AS (VALUES
 (1,'prep','training','offline_youth','线下青少语培'),
 (2,'high','training','offline_high_school','线下高中语培'),
 (3,'high','abroad','offline_high_school','高中留学'),
 (4,'university','training','offline_university','线下大学语培'),
 (5,'university','abroad','offline_university','线下大学留学'),
 (6,'virtual','mixed','online_private','线上虚拟人'),
 (7,'online','training','online_platform','线上平台语培'),
 (8,'online','abroad','online_platform','线上平台留学')
)
SELECT *,team_id||'.'||business_line AS channel_id FROM source_channels;

CREATE OR REPLACE TEMP VIEW notification_context AS
WITH run AS (
 SELECT through_date,source_json,strftime(through_date,'%Y-%m') AS natural_month,
  strftime(date_trunc('month',through_date)+
   CASE WHEN day(through_date)>=26 THEN INTERVAL '1 month' ELSE INTERVAL '0 month' END,'%Y-%m') AS performance_month,
  json_extract_string(source_json,'$.start_date')::DATE AS source_start,
  json_extract_string(source_json,'$.through_date')::DATE AS source_through
 FROM notification_run
)
SELECT c.*,r.through_date,r.source_json,r.source_start,r.source_through,
 n.period_id AS month,n.start_date AS team_start,n.end_date AS team_end,
 n.through_date AS natural_through,n.time_progress AS team_progress,
 CASE WHEN c.team_id='online' THEN n.period_id ELSE p.period_id END AS person_month,
 CASE WHEN c.team_id='online' THEN NULL ELSE p.personal_start END AS person_start,
 CASE WHEN c.team_id='online' THEN NULL ELSE p.personal_end END AS person_end,
 CASE WHEN c.team_id='online' OR r.through_date<p.personal_start THEN NULL
  ELSE least(p.personal_end,r.through_date) END AS person_through,
 CASE WHEN c.team_id='online' THEN NULL WHEN r.through_date<p.personal_start THEN 0.0
  ELSE (date_diff('day',p.personal_start,least(p.personal_end,r.through_date))+1)::DOUBLE/
       (date_diff('day',p.personal_start,p.personal_end)+1) END AS person_progress,
 (c.team_id='high' AND c.business_line='abroad') AS personal_only,
 CASE WHEN c.business_line='mixed' THEN 'training' ELSE c.business_line END AS metric_line,
 coalesce(n.through_date,n.start_date) AS team_fact_through
FROM notification_channels c CROSS JOIN run r
JOIN business.periods n ON n.period_id=r.natural_month
JOIN business.periods p ON p.period_id=CASE WHEN c.team_id='online' THEN n.period_id ELSE r.performance_month END;

CREATE OR REPLACE TEMP VIEW notification_team_facts AS
SELECT c.channel_id,c.channel_order,c.business_line AS message_line,
 CASE WHEN f.metric='orders' THEN 'team_orders' ELSE 'team_cash' END AS ledger_name,f.fact_id
FROM notification_context c JOIN business.facts f ON
 CAST(f.event_date AS DATE) BETWEEN c.team_start AND c.team_fact_through
 AND f.metric IN ('orders','cash') AND f.business_line=c.metric_line
 AND CASE
  WHEN f.business_line='training' AND c.team_id IN ('prep','high','university') THEN
   f.team_id='offline_market' AND f.business_group IN ('留学预备','高中','大学')
   AND f.business_group=CASE c.team_id WHEN 'prep' THEN '留学预备' WHEN 'high' THEN '高中' ELSE '大学' END
  WHEN f.business_line='training' AND c.team_id='virtual' THEN
   f.team_id='online_private' AND f.business_group IN ('留学预备','高中','大学')
  WHEN f.business_line='training' AND c.team_id='online' THEN
   f.team_id='online_platform' AND f.business_group IN ('留学预备','高中','大学')
  WHEN f.business_line='abroad' AND c.team_id='university' THEN f.segment_id='study_abroad_offline'
  WHEN f.business_line='abroad' AND c.team_id='online' THEN f.segment_id='study_abroad_online'
  WHEN f.business_line='abroad' AND c.team_id='virtual' THEN f.segment_id='study_abroad_virtual'
  ELSE false END
WHERE NOT c.personal_only;

CREATE OR REPLACE TEMP VIEW notification_selected_people AS
SELECT c.channel_id,c.channel_order,c.team_id,c.business_line AS message_line,
 c.person_month,c.person_start,c.person_end,c.person_through,c.person_progress,c.through_date,
 c.source_json,c.source_start,c.source_through,c.personal_only,
 p.name,p.home_group,p.business_line,p.team_ids,p.training_roster,p.abroad_roster,
 CASE WHEN p.training_roster THEN 'training' ELSE 'abroad' END AS primary_line
FROM notification_context c JOIN config.people p ON c.team_id<>'online' AND
 ((c.team_id='virtual' AND list_contains(p.team_ids,'online_private')) OR
  (c.team_id IN ('prep','high','university') AND list_contains(p.team_ids,'offline_market')
   AND p.home_group=CASE c.team_id WHEN 'prep' THEN '留学预备' WHEN 'high' THEN '高中' ELSE '大学' END))
 AND (c.business_line='mixed' OR CASE WHEN p.training_roster THEN 'training' ELSE 'abroad' END=c.business_line);

CREATE OR REPLACE TEMP VIEW notification_person_metrics AS
SELECT p.channel_id,p.channel_order,p.team_id,p.message_line,p.person_month,p.person_start,p.person_end,
 p.person_through,p.person_progress,p.through_date,p.source_json,p.source_start,p.source_through,
 p.name,p.home_group,p.business_line,p.team_ids,p.training_roster,p.abroad_roster,p.primary_line,
 m.state,m.business_line AS metric_line,m.metric,m.actual,m.prior,m.target,m.status,
 m.start_date,m.through_date AS metric_through,m.end_date,m.time_progress,m.coverage_status,
 m.study_heads,m.language_heads
FROM notification_selected_people p JOIN business.personal_metrics m
 ON m.period_id=p.person_month AND m.month_mode='performance' AND m.name=p.name;

CREATE OR REPLACE TEMP VIEW notification_source_facts AS
SELECT 'business' AS source_set,f.fact_id,
 CASE WHEN f.business_line='training' THEN json_merge_patch(to_json(struct_pack(
  acquisition_mode:=f.acquisition_mode,business_group:=f.business_group,business_line:=f.business_line,
  campaign_name:=f.campaign_name,channel_school_name:=f.channel_school_name,class_code:=f.class_code,
  comparison_group:=f.comparison_group,country:=f.country,counts_toward_completion:=f.counts_toward_completion,
  event_date:=f.event_date,exclusion_reason:=f.exclusion_reason,fact_id:=f.fact_id,first_channel:=f.first_channel,
  grade_name:=f.grade_name,line:=f.line,metric:=f.metric,order_status:=f.order_status,owners:=f.owners,
  registration_count:=f.registration_count,school_attribute:=f.school_attribute,
  school_attribute_status:=f.school_attribute_status,school_name:=f.school_name,second_channel:=f.second_channel,
  source_record:=f.source_record,source_row_number:=f.source_row_number,student_id:=f.student_id,
  team_before_override:=f.team_before_override,team_id:=f.team_id,team_inferred:=f.team_inferred,
  team_override_reason:=f.team_override_reason,value:=f.value,virtual_owners:=f.virtual_owners,work_order_id:=f.work_order_id)),
  CASE WHEN f.team_before_override IS NULL THEN '{"team_before_override":null,"team_override_reason":null}' ELSE '{}' END)
 ELSE to_json(struct_pack(
  acquisition_mode:=f.acquisition_mode,business_group:=f.business_group,business_line:=f.business_line,
  campaign_name:=f.campaign_name,channel_mapping_rule:=f.channel_mapping_rule,
  channel_mapping_status:=f.channel_mapping_status,channel_source:=f.channel_source,contract_id:=f.contract_id,
  contract_status:=f.contract_status,country:=f.country,counts_toward_completion:=f.counts_toward_completion,
  customer_domain:=f.customer_domain,customer_key:=f.customer_key,event_date:=f.event_date,
  exclusion_reason:=f.exclusion_reason,fact_id:=f.fact_id,first_channel:=f.first_channel,grade_name:=f.grade_name,
  intended_stage:=f.intended_stage,line:=f.line,market_eligible:=f.market_eligible,metric:=f.metric,
  offline_channel_eligible:=f.offline_channel_eligible,order_status:=f.order_status,owner:=f.owner,
  owners:=f.owners,personal_eligible:=f.personal_eligible,raw_first_channel:=f.raw_first_channel,
  raw_second_channel:=f.raw_second_channel,resource_id:=f.resource_id,resource_status:=f.resource_status,
  school_name:=f.school_name,second_channel:=f.second_channel,segment_id:=f.segment_id,
  source_filename:=f.source_filename,source_kind:=f.source_kind,source_owner:=f.source_owner,
  source_product:=f.source_product,source_record:=f.source_record,source_row_number:=f.source_row_number,
  source_sha256:=f.source_sha256,source_sheet:=f.source_sheet,student_id:=f.student_id,
  team_eligible:=f.team_eligible,team_id:=f.team_id,third_channel:=f.third_channel,value:=f.value,
  virtual_owners:=f.virtual_owners,work_order_id:=f.work_order_id)) END AS fact_json
FROM business.facts f
UNION ALL
SELECT 'personal',f.fact_id,
 CASE WHEN f.business_line='training' THEN json_merge_patch(to_json(struct_pack(
  acquisition_mode:=f.acquisition_mode,business_group:=f.business_group,business_line:=f.business_line,
  campaign_name:=f.campaign_name,channel_school_name:=f.channel_school_name,class_code:=f.class_code,
  comparison_group:=f.comparison_group,country:=f.country,counts_toward_completion:=f.counts_toward_completion,
  event_date:=f.event_date,exclusion_reason:=f.exclusion_reason,fact_id:=f.fact_id,first_channel:=f.first_channel,
  grade_name:=f.grade_name,line:=f.line,metric:=f.metric,order_status:=f.order_status,owners:=f.owners,
  registration_count:=f.registration_count,school_attribute:=f.school_attribute,
  school_attribute_status:=f.school_attribute_status,school_name:=f.school_name,second_channel:=f.second_channel,
  source_record:=f.source_record,source_row_number:=f.source_row_number,student_id:=f.student_id,
  team_before_override:=f.team_before_override,team_id:=f.team_id,team_inferred:=f.team_inferred,
  team_override_reason:=f.team_override_reason,value:=f.value,virtual_owners:=f.virtual_owners,work_order_id:=f.work_order_id)),
  CASE WHEN f.team_before_override IS NULL THEN '{"team_before_override":null,"team_override_reason":null}' ELSE '{}' END)
 ELSE to_json(struct_pack(
  acquisition_mode:=f.acquisition_mode,business_group:=f.business_group,business_line:=f.business_line,
  campaign_name:=f.campaign_name,channel_mapping_rule:=f.channel_mapping_rule,
  channel_mapping_status:=f.channel_mapping_status,channel_source:=f.channel_source,contract_id:=f.contract_id,
  contract_status:=f.contract_status,country:=f.country,counts_toward_completion:=f.counts_toward_completion,
  customer_domain:=f.customer_domain,customer_key:=f.customer_key,event_date:=f.event_date,
  exclusion_reason:=f.exclusion_reason,fact_id:=f.fact_id,first_channel:=f.first_channel,grade_name:=f.grade_name,
  intended_stage:=f.intended_stage,line:=f.line,market_eligible:=f.market_eligible,metric:=f.metric,
  offline_channel_eligible:=f.offline_channel_eligible,order_status:=f.order_status,owner:=f.owner,
  owners:=f.owners,personal_eligible:=f.personal_eligible,raw_first_channel:=f.raw_first_channel,
  raw_second_channel:=f.raw_second_channel,resource_id:=f.resource_id,resource_status:=f.resource_status,
  school_name:=f.school_name,second_channel:=f.second_channel,segment_id:=f.segment_id,
  source_filename:=f.source_filename,source_kind:=f.source_kind,source_owner:=f.source_owner,
  source_product:=f.source_product,source_record:=f.source_record,source_row_number:=f.source_row_number,
  source_sha256:=f.source_sha256,source_sheet:=f.source_sheet,student_id:=f.student_id,
  team_eligible:=f.team_eligible,team_id:=f.team_id,third_channel:=f.third_channel,value:=f.value,
  virtual_owners:=f.virtual_owners,work_order_id:=f.work_order_id)) END
FROM business.personnel_facts f;

CREATE OR REPLACE TEMP VIEW notification_person_channel_rows AS
SELECT p.channel_id,p.name,s.state,
 coalesce(nullif(trim(a.first_channel),''),'一级渠道待确认') AS first_channel,
 coalesce(nullif(trim(a.second_channel),''),'二级渠道待确认') AS second_channel,
 sum(a.value*a.weight) AS actual
FROM notification_selected_people p JOIN (VALUES ('00'),('01'),('10'),('11')) s(state) ON true
JOIN business.personal_allocations a ON a.name=p.name AND a.business_line='abroad'
 AND a.metric='orders'
 AND CAST(a.event_date AS DATE) BETWEEN p.person_start AND p.person_through
 AND (coalesce(a.order_status,'') NOT IN ('删除','回收') OR left(s.state,1)='1')
 AND (coalesce(a.order_status,'')<>'死单' OR right(s.state,1)='1')
 AND (a.order_status IN ('删除','回收','死单') OR coalesce(a.counts_toward_completion,true))
WHERE p.home_group='高中' AND p.abroad_roster
GROUP BY p.channel_id,p.name,s.state,first_channel,second_channel;

CREATE OR REPLACE TEMP VIEW notification_person_channel_json AS
WITH measures AS (
 SELECT r.*,coalesce(r.actual,0) AS actual_value,
  sum(coalesce(r.actual,0)) OVER(PARTITION BY r.channel_id,r.name,r.state) AS actual_total
 FROM notification_person_channel_rows r
), rows AS (
 SELECT *,json_object('actual',actual_value,'prior',NULL,'target',NULL,'unit','单','status','available',
  'note','','completion',NULL,'yoy',NULL,'gap',NULL,'time_gap',NULL) AS orders_json
 FROM measures
)
SELECT channel_id,name,state,
 to_json(list(json_object('name',second_channel,'first_channel',first_channel,'orders',orders_json,
  'share',CASE WHEN actual_total<>0 THEN actual_value/actual_total END)
  ORDER BY actual_value DESC,first_channel,second_channel)) AS channels_json
FROM rows GROUP BY channel_id,name,state;

CREATE OR REPLACE TEMP VIEW notification_person_abroad_head_parts AS
SELECT m.channel_id,m.name,
 max(m.study_heads) AS study_abroad,max(m.language_heads) AS small_language
FROM notification_person_metrics m
WHERE m.primary_line='abroad' AND m.state='01' AND m.metric_line='abroad' AND m.metric='heads'
GROUP BY m.channel_id,m.name;

CREATE OR REPLACE TEMP VIEW notification_person_abroad_head_parts_json AS
SELECT channel_id,name,json_array(
 json_object('label','留学','actual',study_abroad),json_object('label','小语种','actual',small_language)) AS parts_json
FROM notification_person_abroad_head_parts;

CREATE OR REPLACE TEMP VIEW notification_person_status_payloads AS
WITH values_by_state AS (
 SELECT channel_id,channel_order,team_id,message_line,person_month,person_start,person_end,person_through,
  person_progress,through_date,source_json,source_start,source_through,name,home_group,business_line,
  team_ids,training_roster,abroad_roster,primary_line,state,
  max(actual) FILTER(WHERE metric_line='training' AND metric='orders') AS training_actual,
  max(prior) FILTER(WHERE metric_line='training' AND metric='orders') AS training_prior,
  max(target) FILTER(WHERE metric_line='training' AND metric='orders') AS training_target,
  max(actual) FILTER(WHERE metric_line='abroad' AND metric='orders' AND coverage_status IN ('available','partial')) AS abroad_actual,
  max(target) FILTER(WHERE metric_line='abroad' AND metric='orders') AS abroad_target,
  max(coverage_status) FILTER(WHERE metric_line='abroad' AND metric='orders') AS abroad_coverage
 FROM notification_person_metrics GROUP BY ALL
), channel_values AS (
 SELECT v.*,coalesce(ch.channels_json,'[]'::JSON) AS abroad_channels
 FROM values_by_state v LEFT JOIN notification_person_channel_json ch USING(channel_id,name,state)
), results AS (
 SELECT *,CASE WHEN team_id='virtual' THEN training_actual
       WHEN abroad_actual IS NOT NULL THEN coalesce(training_actual,0)+abroad_actual END AS combined_actual,
  CASE WHEN team_id='virtual' THEN training_prior END AS combined_prior,
  training_target AS combined_target
 FROM channel_values
)
SELECT channel_id,channel_order,name,state,
 json_merge_patch(json_object('training_target',training_target,'training_actual',training_actual,'training_prior',training_prior,
  'training_completion',CASE WHEN training_actual IS NOT NULL AND training_target IS NOT NULL AND training_target<>0 THEN training_actual/training_target END,
  'combined_target',combined_target,'combined_actual',combined_actual,'combined_prior',combined_prior,
  'combined_completion',CASE WHEN combined_actual IS NOT NULL AND combined_target IS NOT NULL AND combined_target<>0
    AND (team_id='virtual' OR abroad_coverage='available') THEN combined_actual/combined_target END,
  'abroad_target',abroad_target,'abroad_actual',abroad_actual,'abroad_prior',NULL,
  'abroad_completion',CASE WHEN abroad_actual IS NOT NULL AND abroad_target IS NOT NULL AND abroad_target<>0
    AND abroad_coverage='available' THEN abroad_actual/abroad_target END),
  CASE WHEN home_group='高中' AND abroad_roster THEN json_object('abroad_channels',abroad_channels) ELSE '{}'::JSON END) AS view_json
FROM results;

CREATE OR REPLACE TEMP VIEW notification_person_status_json AS
SELECT channel_id,name,json_group_object(state,view_json) AS views_json
FROM notification_person_status_payloads GROUP BY channel_id,name;

CREATE OR REPLACE TEMP VIEW notification_person_source_json AS
WITH base AS (
 SELECT p.channel_id,p.channel_order,p.team_id,p.message_line,p.person_month,p.person_start,p.person_end,p.person_through,
  p.person_progress,p.through_date,p.source_json,p.source_start,p.source_through,p.name,p.home_group,
  p.business_line,p.team_ids,p.training_roster,p.abroad_roster,p.primary_line,
  max(actual) FILTER(WHERE metric_line='training' AND metric='orders') AS training_actual,
  max(prior) FILTER(WHERE metric_line='training' AND metric='orders') AS training_prior,
  max(target) FILTER(WHERE metric_line='training' AND metric='orders') AS training_target,
  max(actual) FILTER(WHERE metric_line='abroad' AND metric='orders' AND coverage_status IN ('available','partial')) AS abroad_actual,
  max(target) FILTER(WHERE metric_line='abroad' AND metric='orders') AS abroad_target,
  max(coverage_status) FILTER(WHERE metric_line='abroad' AND metric='orders') AS abroad_coverage,
  max(actual) FILTER(WHERE metric_line='training' AND metric='cash') AS training_cash_actual,
  max(prior) FILTER(WHERE metric_line='training' AND metric='cash') AS training_cash_prior,
  max(target) FILTER(WHERE metric_line='training' AND metric='cash') AS training_cash_target,
  max(status) FILTER(WHERE metric_line='training' AND metric='cash') AS training_cash_status,
  max(actual) FILTER(WHERE metric_line='training' AND metric='heads') AS training_heads_actual,
  max(prior) FILTER(WHERE metric_line='training' AND metric='heads') AS training_heads_prior,
  max(status) FILTER(WHERE metric_line='training' AND metric='heads') AS training_heads_status,
  max(coverage_status) FILTER(WHERE metric_line='abroad' AND metric='cash') AS abroad_cash_coverage,
  max(actual) FILTER(WHERE metric_line='abroad' AND metric='cash' AND coverage_status='available') AS abroad_cash_actual,
  max(target) FILTER(WHERE metric_line='abroad' AND metric='cash') AS abroad_cash_target,
  max(status) FILTER(WHERE metric_line='abroad' AND metric='cash') AS abroad_cash_status,
  max(coverage_status) FILTER(WHERE metric_line='abroad' AND metric='heads') AS abroad_heads_coverage,
  max(actual) FILTER(WHERE metric_line='abroad' AND metric='heads' AND coverage_status='available') AS abroad_heads_actual,
  max(prior) FILTER(WHERE metric_line='abroad' AND metric='heads' AND coverage_status='available') AS abroad_heads_prior,
  max(status) FILTER(WHERE metric_line='abroad' AND metric='heads') AS abroad_heads_status,
  max(target) FILTER(WHERE metric_line='abroad' AND metric='heads') AS abroad_heads_target
 FROM notification_person_metrics p WHERE state='01' GROUP BY ALL
), normalized AS (
 SELECT *,CASE WHEN team_id='virtual' THEN training_actual
       WHEN abroad_actual IS NOT NULL THEN coalesce(training_actual,0)+abroad_actual END AS combined_actual,
  CASE WHEN team_id='virtual' THEN training_prior END AS combined_prior,
  training_target AS combined_target,
  CASE WHEN primary_line='abroad' THEN
   CASE WHEN abroad_cash_status='future' THEN 'future' WHEN abroad_cash_coverage='not_covered' THEN 'not_covered'
        WHEN abroad_cash_coverage='partial' THEN 'partial' ELSE 'available' END
   ELSE coalesce(training_cash_status,'available') END AS cash_status,
  CASE WHEN primary_line='abroad' THEN
   CASE WHEN abroad_heads_status='future' THEN 'future' WHEN abroad_heads_coverage='not_covered' THEN 'not_covered'
        WHEN abroad_heads_coverage='partial' THEN 'partial' WHEN abroad_heads_coverage='separate_counts' THEN 'separate_counts'
        ELSE 'available' END
   ELSE coalesce(training_heads_status,'available') END AS heads_status,
  CASE WHEN primary_line='abroad' THEN abroad_cash_actual ELSE training_cash_actual END AS selected_cash_actual,
  CASE WHEN primary_line='training' THEN training_cash_prior END AS selected_cash_prior,
  CASE WHEN primary_line='abroad' THEN abroad_cash_target ELSE training_cash_target END AS selected_cash_target,
  CASE WHEN primary_line='abroad' THEN abroad_heads_actual ELSE training_heads_actual END AS selected_heads_actual,
  CASE WHEN primary_line='training' THEN training_heads_prior END AS selected_heads_prior,
  CASE WHEN primary_line='abroad' THEN abroad_heads_target END AS selected_heads_target,
  CASE WHEN source_start IS NOT NULL AND source_through IS NOT NULL
       AND source_start<=person_through AND person_start<=source_through
       THEN json_merge_patch(source_json,json_object('start_date',greatest(source_start,person_start)::VARCHAR,
          'through_date',least(source_through,person_through)::VARCHAR)) ELSE source_json END AS clipped_source
 FROM base
), metrics AS (
 SELECT n.*,coalesce(s.views_json,'{}'::JSON) AS views_json,
  coalesce(ch.channels_json,'[]'::JSON) AS default_channels,
  coalesce(hp.parts_json,'[]'::JSON) AS head_parts_json,
  CASE WHEN cash_status='available' THEN selected_cash_actual END AS final_cash_actual,
  CASE WHEN cash_status='available' THEN selected_cash_prior END AS final_cash_prior,
  CASE WHEN heads_status='available' THEN selected_heads_actual END AS final_heads_actual,
  CASE WHEN heads_status='available' THEN selected_heads_prior END AS final_heads_prior
 FROM normalized n LEFT JOIN notification_person_status_json s USING(channel_id,name)
 LEFT JOIN notification_person_channel_json ch ON ch.channel_id=n.channel_id AND ch.name=n.name AND ch.state='01'
 LEFT JOIN notification_person_abroad_head_parts_json hp USING(channel_id,name)
), jsons AS (
 SELECT *,
  json_object('actual',final_cash_actual,'prior',final_cash_prior,'target',selected_cash_target,'unit','元',
   'status',cash_status,'note','',
   'completion',CASE WHEN final_cash_actual IS NOT NULL AND selected_cash_target IS NOT NULL AND selected_cash_target<>0 THEN final_cash_actual/selected_cash_target END,
   'yoy',CASE WHEN final_cash_actual IS NOT NULL AND final_cash_prior IS NOT NULL AND final_cash_prior<>0 THEN final_cash_actual/final_cash_prior-1 END,
   'gap',CASE WHEN final_cash_actual IS NOT NULL AND selected_cash_target IS NOT NULL THEN round(final_cash_actual-selected_cash_target,2) END,
   'time_gap',CASE WHEN final_cash_actual IS NOT NULL AND selected_cash_target IS NOT NULL THEN round(final_cash_actual-selected_cash_target*person_progress,2) END) AS cash_core,
  json_object('actual',final_heads_actual,'prior',final_heads_prior,'target',NULL,'unit','人',
   'status',heads_status,'note','','completion',NULL,
   'yoy',CASE WHEN final_heads_actual IS NOT NULL AND final_heads_prior IS NOT NULL AND final_heads_prior<>0 THEN final_heads_actual/final_heads_prior-1 END,
   'gap',NULL,'time_gap',NULL) AS heads_core
 FROM metrics
), nested_metrics AS (
 SELECT *,CASE WHEN primary_line='abroad' THEN json_merge_patch(cash_core,json_object('source_coverage',clipped_source)) ELSE cash_core END AS cash_json,
  CASE WHEN primary_line='abroad' THEN json_merge_patch(heads_core,json_object('source_coverage',clipped_source,'parts',head_parts_json))
       ELSE heads_core END AS heads_json
 FROM jsons
), source_fields AS (
 SELECT *,json_object('name',name,'home_group',home_group,'business_line',business_line,
  'training_target',training_target,'training_actual',training_actual,'training_prior',training_prior,
  'training_completion',CASE WHEN training_actual IS NOT NULL AND training_target IS NOT NULL AND training_target<>0 THEN training_actual/training_target END,
  'combined_target',combined_target,'combined_actual',combined_actual,'combined_prior',combined_prior,
  'combined_completion',CASE WHEN combined_actual IS NOT NULL AND combined_target IS NOT NULL AND combined_target<>0
      AND (team_id='virtual' OR abroad_coverage='available') THEN combined_actual/combined_target END,
  'abroad_target',abroad_target,'abroad_actual',abroad_actual,'abroad_prior',NULL,
  'abroad_completion',CASE WHEN abroad_actual IS NOT NULL AND abroad_target IS NOT NULL AND abroad_target<>0
      AND abroad_coverage='available' THEN abroad_actual/abroad_target END,
  'cash_actual',cash_json,'heads_actual',heads_json,'abroad_source_coverage',source_json,
  'order_status_views',views_json) AS source_person_json
 FROM nested_metrics
)
SELECT *,CASE WHEN home_group='高中' AND abroad_roster THEN
 json_merge_patch(source_person_json,json_object('abroad_channels',default_channels)) ELSE source_person_json END AS person_json
FROM source_fields;

CREATE OR REPLACE TEMP VIEW notification_person_payloads AS
WITH source AS (
 SELECT p.*,
  CASE WHEN p.message_line='mixed' THEN p.combined_actual WHEN p.message_line='training' THEN p.training_actual ELSE p.abroad_actual END AS orders_actual,
  CASE WHEN p.message_line='mixed' THEN p.training_target WHEN p.message_line='training' THEN p.training_target ELSE p.abroad_target END AS orders_target,
  CASE WHEN p.message_line IN ('training','mixed') THEN p.training_prior END AS orders_prior,
  CASE WHEN p.message_line IN ('training','mixed') THEN
   (SELECT max(target) FROM config.personal_targets h WHERE h.name=p.name AND h.month=p.person_month AND h.metric='heads') END AS heads_target,
  CASE WHEN p.primary_line='training' THEN
   (SELECT max(actual) FROM notification_person_metrics q WHERE q.channel_id=p.channel_id AND q.name=p.name
     AND q.state='01' AND q.metric_line='training' AND q.metric='heads' AND q.status='available')
   WHEN p.primary_line='abroad' THEN
   (SELECT max(actual) FROM notification_person_metrics q WHERE q.channel_id=p.channel_id AND q.name=p.name
     AND q.state='01' AND q.metric_line='abroad' AND q.metric='heads' AND q.status='available' AND q.coverage_status='available') END AS heads_actual,
  CASE WHEN p.team_id='university' AND p.message_line='training' THEN
   (SELECT max(target) FROM notification_person_metrics q WHERE q.channel_id=p.channel_id AND q.name=p.name AND q.state='01' AND q.metric_line='abroad' AND q.metric='orders')
   WHEN p.team_id='university' AND p.message_line='abroad' THEN
   (SELECT max(target) FROM notification_person_metrics q WHERE q.channel_id=p.channel_id AND q.name=p.name AND q.state='01' AND q.metric_line='training' AND q.metric='orders') END AS secondary_target,
  CASE WHEN p.team_id='university' AND p.message_line='training' THEN
   (SELECT max(actual) FROM notification_person_metrics q WHERE q.channel_id=p.channel_id AND q.name=p.name AND q.state='01' AND q.metric_line='abroad' AND q.metric='orders' AND q.coverage_status IN ('available','partial'))
   WHEN p.team_id='university' AND p.message_line='abroad' THEN
   (SELECT max(actual) FROM notification_person_metrics q WHERE q.channel_id=p.channel_id AND q.name=p.name AND q.state='01' AND q.metric_line='training' AND q.metric='orders') END AS secondary_actual
 FROM notification_person_source_json p
), day_count AS (
 SELECT s.channel_id,s.name,count(*) FILTER(WHERE extract(isodow FROM d.day)<=5) AS remaining_workdays
 FROM source s LEFT JOIN LATERAL (SELECT unnest(generate_series(s.through_date+1,
  make_date(split_part(s.person_month,'-',1)::INTEGER,split_part(s.person_month,'-',2)::INTEGER,25),INTERVAL '1 day'))::DATE AS day) d ON true
 GROUP BY s.channel_id,s.name
), today AS (
 SELECT p.channel_id,p.name,coalesce(sum(a.value*a.weight),0) AS today_orders
 FROM notification_selected_people p LEFT JOIN business.personal_allocations a ON a.name=p.name AND a.metric='orders'
  AND CAST(a.event_date AS DATE)=p.through_date AND coalesce(a.counts_toward_completion,true)
  AND coalesce(a.order_status,'') NOT IN ('删除','回收')
  AND a.business_line IN (CASE WHEN p.message_line='mixed' THEN 'training' ELSE p.message_line END,
                          CASE WHEN p.message_line='mixed' THEN 'abroad' ELSE p.message_line END)
 GROUP BY p.channel_id,p.name
), values AS (
 SELECT s.*,d.remaining_workdays,t.today_orders,
  CASE WHEN orders_actual IS NOT NULL AND orders_target IS NOT NULL AND orders_target<>0 THEN orders_actual/orders_target END AS orders_completion,
  CASE WHEN orders_actual IS NOT NULL AND orders_target IS NOT NULL AND person_progress IS NOT NULL
       THEN cast(orders_actual AS DECIMAL(24,8))-orders_target*cast(cast(person_progress AS VARCHAR) AS DECIMAL(24,16)) END AS orders_gap,
  CASE WHEN orders_target IS NOT NULL AND person_progress IS NOT NULL
       THEN orders_target*cast(cast(person_progress AS VARCHAR) AS DECIMAL(24,16)) END AS expected_orders,
  CASE WHEN orders_actual IS NOT NULL AND orders_target IS NOT NULL THEN greatest(0,orders_target-orders_actual) END AS remaining_orders,
  CASE WHEN orders_actual IS NOT NULL AND orders_target IS NOT NULL AND orders_target<>0
       THEN orders_actual<orders_target*cast(cast(person_progress AS VARCHAR) AS DECIMAL(24,16)) END AS behind
 FROM source s JOIN day_count d USING(channel_id,name) JOIN today t USING(channel_id,name)
)
SELECT channel_id,channel_order,name,person_json AS source_person_json,
 json_object('orders_target',orders_target,'orders_actual',orders_actual,
   'orders_completion',CASE WHEN primary_line='abroad' AND NOT(person_start>=source_start AND person_end<=source_through) THEN NULL ELSE orders_completion END,
   'heads_target',heads_target,'heads_completion',CASE WHEN heads_actual IS NOT NULL AND heads_target IS NOT NULL AND heads_target<>0 THEN heads_actual/heads_target END,
   'expected_orders',CASE WHEN primary_line='abroad' AND NOT(person_start>=source_start AND person_end<=source_through) THEN NULL ELSE expected_orders END,
   'orders_gap',CASE WHEN primary_line='abroad' AND NOT(person_start>=source_start AND person_end<=source_through) THEN NULL ELSE orders_gap END,
   'remaining_orders',CASE WHEN primary_line='abroad' AND NOT(person_start>=source_start AND person_end<=source_through) THEN NULL ELSE remaining_orders END,
   'remaining_workdays',remaining_workdays,
   'today_orders',CASE WHEN primary_line='abroad' AND NOT(through_date BETWEEN source_start AND source_through) THEN NULL ELSE today_orders END,
   'daily_orders',CASE WHEN primary_line='abroad' AND NOT(person_start>=source_start AND person_end<=source_through) THEN NULL
       WHEN remaining_workdays>0 AND remaining_orders IS NOT NULL THEN remaining_orders/remaining_workdays END,
   'behind',CASE WHEN primary_line='abroad' AND NOT(person_start>=source_start AND person_end<=source_through) THEN NULL ELSE behind END) AS display_json,
 CASE WHEN team_id='university' AND home_group='大学' THEN json_object(
   'secondary_business_line',CASE WHEN message_line='training' THEN 'abroad' ELSE 'training' END,
   'secondary_orders_target',secondary_target,'secondary_orders_actual',secondary_actual,
   'secondary_orders_completion',CASE WHEN secondary_actual IS NOT NULL AND secondary_target IS NOT NULL AND secondary_target<>0 THEN secondary_actual/secondary_target END)
  END AS secondary_json
FROM values;

CREATE OR REPLACE TEMP VIEW notification_person_credit_rows AS
SELECT p.channel_id,p.channel_order,p.team_id,p.name,
 CASE WHEN a.metric='orders' AND (p.message_line='mixed' OR a.business_line=p.message_line) THEN 'personal_orders'
      WHEN a.metric='cash' AND a.business_line=CASE WHEN p.message_line='mixed' THEN 'training' ELSE p.message_line END THEN 'personal_cash'
      WHEN p.team_id='university' AND a.metric='orders' AND a.business_line=CASE WHEN p.message_line='training' THEN 'abroad' ELSE 'training' END THEN 'personal_secondary_orders' END AS ledger_name,
 a.fact_id,a.business_line,a.metric,a.event_date,a.work_order_id,a.second_channel,a.value,a.weight,a.value*a.weight AS credit_value
FROM notification_selected_people p JOIN business.personal_allocations a ON a.name=p.name
 AND CAST(a.event_date AS DATE) BETWEEN p.person_start AND p.person_through
 AND ((a.metric='orders' AND (p.message_line='mixed' OR a.business_line=p.message_line)) OR
      (a.metric='cash' AND a.business_line=CASE WHEN p.message_line='mixed' THEN 'training' ELSE p.message_line END) OR
      (p.team_id='university' AND a.metric='orders' AND a.business_line=CASE WHEN p.message_line='training' THEN 'abroad' ELSE 'training' END))
WHERE p.team_id<>'online';

CREATE OR REPLACE TEMP VIEW notification_person_credit_aggregates AS
SELECT channel_id,channel_order,team_id,ledger_name,fact_id,business_line,metric,event_date,work_order_id,second_channel,
 json_group_object(name,json_object('weight',weight,'value',credit_value)) AS person_credits,
 list(name ORDER BY name) AS credited_people,sum(credit_value) AS credited_value
FROM notification_person_credit_rows WHERE ledger_name IS NOT NULL
GROUP BY channel_id,channel_order,team_id,ledger_name,fact_id,business_line,metric,event_date,work_order_id,second_channel;

CREATE OR REPLACE TEMP VIEW notification_person_ledger_json AS
SELECT a.channel_id,a.channel_order,a.ledger_name,a.event_date,a.work_order_id,a.fact_id,
 json_merge_patch(CASE WHEN a.team_id='virtual' THEN json_merge_patch(f.fact_json,json_object('owners',a.credited_people)) ELSE f.fact_json END,
  json_merge_patch('{"virtual_owners":null}',json_object('person_credits',a.person_credits))) AS fact_json
FROM notification_person_credit_aggregates a JOIN notification_source_facts f ON f.source_set='personal' AND f.fact_id=a.fact_id;

CREATE OR REPLACE TEMP VIEW notification_unassigned_cash_json AS
SELECT c.channel_id,c.channel_order,'unassigned_cash' AS ledger_name,f.event_date,f.work_order_id,f.fact_id,
 json_merge_patch(json_merge_patch(sf.fact_json,'{"virtual_owners":null}'),json_object('attribution_reason',CASE
  WHEN coalesce(f.team_inferred,false) THEN '团队归属由渠道推断'
  WHEN coalesce(array_length(CASE WHEN c.team_id='virtual' THEN f.virtual_owners ELSE f.owners END),0)=0 THEN '未匹配当前人员'
  WHEN EXISTS (SELECT 1 FROM unnest(CASE WHEN c.team_id='virtual' THEN f.virtual_owners ELSE f.owners END) o(name) JOIN config.people r ON r.name=trim(o.name))
   AND NOT EXISTS (SELECT 1 FROM unnest(CASE WHEN c.team_id='virtual' THEN f.virtual_owners ELSE f.owners END) o(name) JOIN notification_selected_people p ON p.channel_id=c.channel_id AND p.name=trim(o.name))
   THEN '归属人员不在本消息考核名单' ELSE '不满足个人计入资格' END)) AS fact_json
FROM notification_context c JOIN business.facts f ON CAST(f.event_date AS DATE) BETWEEN c.person_start AND c.person_through
JOIN notification_source_facts sf ON sf.source_set='business' AND sf.fact_id=f.fact_id
 AND f.metric='cash' AND f.business_line=c.metric_line AND NOT c.personal_only AND c.team_id<>'online'
 AND CASE
  WHEN f.business_line='training' AND c.team_id IN ('prep','high','university') THEN f.team_id='offline_market' AND f.business_group IN ('留学预备','高中','大学') AND f.business_group=CASE c.team_id WHEN 'prep' THEN '留学预备' WHEN 'high' THEN '高中' ELSE '大学' END
  WHEN f.business_line='training' AND c.team_id='virtual' THEN f.team_id='online_private' AND f.business_group IN ('留学预备','高中','大学')
  WHEN f.business_line='training' AND c.team_id='online' THEN f.team_id='online_platform' AND f.business_group IN ('留学预备','高中','大学')
  WHEN f.business_line='abroad' AND c.team_id='university' THEN f.segment_id='study_abroad_offline'
  WHEN f.business_line='abroad' AND c.team_id='online' THEN f.segment_id='study_abroad_online'
  WHEN f.business_line='abroad' AND c.team_id='virtual' THEN f.segment_id='study_abroad_virtual'
  ELSE false END
 AND NOT EXISTS (SELECT 1 FROM notification_person_credit_aggregates x WHERE x.channel_id=c.channel_id AND x.ledger_name='personal_cash' AND x.fact_id=f.fact_id);

CREATE OR REPLACE TEMP VIEW notification_ledger_json AS
SELECT t.channel_id,t.channel_order,t.ledger_name,b.event_date,b.work_order_id,b.fact_id,
 json_merge_patch(sf.fact_json,'{"virtual_owners":null}') AS fact_json
FROM notification_team_facts t JOIN business.facts b USING(fact_id)
JOIN notification_source_facts sf ON sf.source_set='business' AND sf.fact_id=t.fact_id
UNION ALL SELECT * FROM notification_person_ledger_json
UNION ALL SELECT * FROM notification_unassigned_cash_json;

CREATE OR REPLACE TEMP VIEW notification_channel_shares AS
WITH inputs AS (
 SELECT t.channel_id,coalesce(nullif(trim(f.second_channel),''),'二级渠道待确认') AS name,
  f.value::DOUBLE AS month,CASE WHEN CAST(f.event_date AS DATE)=c.through_date THEN f.value::DOUBLE ELSE 0.0 END AS today
 FROM notification_team_facts t JOIN business.facts f USING(fact_id) JOIN notification_context c USING(channel_id)
 WHERE t.ledger_name='team_orders'
 UNION ALL
 SELECT x.channel_id,coalesce(nullif(trim(x.second_channel),''),'二级渠道待确认'),sum(x.credited_value)::DOUBLE,
  sum(CASE WHEN CAST(x.event_date AS DATE)=c.through_date THEN x.credited_value ELSE 0 END)::DOUBLE
 FROM notification_person_credit_aggregates x JOIN notification_context c USING(channel_id)
 WHERE c.personal_only AND x.ledger_name='personal_orders'
 GROUP BY x.channel_id,coalesce(nullif(trim(x.second_channel),''),'二级渠道待确认'),c.through_date
), grouped AS (SELECT channel_id,name,sum(month) AS month,sum(today) AS today FROM inputs GROUP BY ALL)
SELECT channel_id,name,month,today,month/nullif(sum(month) OVER(PARTITION BY channel_id),0) AS share
FROM grouped;

CREATE OR REPLACE TEMP VIEW notification_team_abroad_head_parts AS
SELECT t.channel_id,
 count(DISTINCT f.student_id) FILTER(WHERE coalesce(f.customer_domain,f.source_product)='study_abroad') AS study_heads,
 count(DISTINCT f.student_id) FILTER(WHERE coalesce(f.customer_domain,f.source_product)='small_language') AS language_heads
FROM notification_team_facts t JOIN business.facts f USING(fact_id)
WHERE t.ledger_name='team_cash' AND f.business_line='abroad' AND f.value>0
 AND nullif(trim(f.student_id),'') IS NOT NULL
GROUP BY t.channel_id;

CREATE OR REPLACE TEMP VIEW notification_team_metric_json AS
WITH metrics AS (
 SELECT c.channel_id,c.channel_order,c.team_id,c.business_line,c.metric_line,c.through_date,c.team_start,c.team_end,
  c.team_progress,c.source_json,c.source_start,c.source_through,c.personal_only,
  m.metric,m.actual,m.prior,coalesce(m.target,t.target) AS target,m.status,m.time_progress
 FROM notification_context c JOIN business.team_metrics m
  ON m.period_id=c.month AND m.unit_id=c.team_id AND m.acquisition_scope='全部' AND m.business_line=c.metric_line
 LEFT JOIN business.team_targets t
  ON t.period_id=m.period_id AND t.unit_id=m.unit_id AND t.business_line=m.business_line AND t.metric=m.metric
 WHERE NOT c.personal_only
), daily AS (
 SELECT t.channel_id,sum(f.value) FILTER(WHERE CAST(f.event_date AS DATE)=c.through_date) AS daily_actual
 FROM notification_team_facts t JOIN business.facts f USING(fact_id) JOIN notification_context c USING(channel_id)
 WHERE t.ledger_name='team_orders' GROUP BY t.channel_id
), coverage AS (
 SELECT m.*,coalesce(h.study_heads,0) AS study_heads,coalesce(h.language_heads,0) AS language_heads,
  CASE WHEN business_line='abroad' AND team_id NOT IN ('prep','high') THEN
   CASE WHEN status IN ('not_covered','future') THEN source_json
    WHEN source_start<=coalesce(team_end,team_start) AND team_start<=source_through THEN
     json_merge_patch(source_json,json_object('start_date',greatest(team_start,source_start)::VARCHAR,
       'through_date',least(coalesce(team_end,team_start),source_through)::VARCHAR)) ELSE source_json END END AS clipped_source
 FROM metrics m LEFT JOIN notification_team_abroad_head_parts h USING(channel_id)
), calc AS (
 SELECT c.*,CASE WHEN metric='orders' AND clipped_source IS NOT NULL AND NOT(through_date BETWEEN source_start AND source_through) THEN NULL
       WHEN metric='orders' THEN coalesce(d.daily_actual,0) END AS daily_actual,
  CASE WHEN metric='orders' THEN greatest(1,date_diff('day',team_start,through_date)+1) END AS elapsed_days,
  CASE WHEN metric='orders' THEN greatest(0,date_diff('day',through_date,team_end)) END AS remaining_days
 FROM coverage c LEFT JOIN daily d USING(channel_id)
), calculated AS (
 SELECT *,CASE WHEN metric='orders' AND actual IS NOT NULL THEN actual/elapsed_days END AS daily_average,
  CASE WHEN metric='orders' AND actual IS NOT NULL AND target IS NOT NULL AND remaining_days>0 THEN greatest(0,target-actual)/remaining_days END AS daily_required,
  CASE WHEN metric='orders' AND actual IS NOT NULL AND target IS NOT NULL AND target<>0 THEN actual<target*time_progress END AS behind
 FROM calc
), output AS (
 SELECT *,CASE
  WHEN metric='orders' AND clipped_source IS NOT NULL THEN json_object(
   'actual',CASE WHEN status IN ('future','not_covered','not_configured') THEN NULL ELSE actual END,
   'prior',CASE WHEN status IN ('future','not_covered','not_configured') THEN NULL ELSE prior END,
   'target',target,'unit','单','status',status,
   'note',CASE WHEN status='not_configured' THEN '本部门暂不统计留学完成；贡献见人员产能。' ELSE '' END,
   'completion',CASE WHEN actual IS NOT NULL AND target IS NOT NULL AND target<>0 THEN actual/target END,
   'yoy',CASE WHEN actual IS NOT NULL AND prior IS NOT NULL AND prior<>0 THEN actual/prior-1 END,
   'gap',CASE WHEN actual IS NOT NULL AND target IS NOT NULL THEN round(actual-target,2) END,
   'time_gap',CASE WHEN actual IS NOT NULL AND target IS NOT NULL THEN round(actual-target*time_progress,2) END,
   'source_coverage',clipped_source,'daily_actual',daily_actual,
   'daily_average',CASE WHEN status<>'available' THEN NULL ELSE daily_average END,
   'daily_required',CASE WHEN status<>'available' THEN NULL ELSE daily_required END,
   'behind',CASE WHEN status<>'available' THEN NULL ELSE behind END)
  WHEN metric='orders' THEN json_object(
   'actual',CASE WHEN status IN ('future','not_covered','not_configured') THEN NULL ELSE actual END,
   'prior',CASE WHEN status IN ('future','not_covered','not_configured') THEN NULL ELSE prior END,
   'target',target,'unit','单','status',status,
   'note',CASE WHEN status='not_configured' THEN '本部门暂不统计留学完成；贡献见人员产能。' ELSE '' END,
   'completion',CASE WHEN actual IS NOT NULL AND target IS NOT NULL AND target<>0 THEN actual/target END,
   'yoy',CASE WHEN actual IS NOT NULL AND prior IS NOT NULL AND prior<>0 THEN actual/prior-1 END,
   'gap',CASE WHEN actual IS NOT NULL AND target IS NOT NULL THEN round(actual-target,2) END,
   'time_gap',CASE WHEN actual IS NOT NULL AND target IS NOT NULL THEN round(actual-target*time_progress,2) END,
   'daily_actual',daily_actual,'daily_average',daily_average,'daily_required',daily_required,'behind',behind)
  WHEN metric='heads' AND business_line='abroad' AND status IN ('available','partial','separate_counts') AND actual IS NULL THEN json_object(
   'actual',NULL,'prior',NULL,'target',target,'unit','人','status','separate_counts','note','',
   'completion',NULL,'yoy',NULL,'gap',NULL,'time_gap',NULL,'source_coverage',clipped_source,
   'parts',json_array(json_object('label','留学','actual',study_heads),json_object('label','小语种','actual',language_heads)),
   'display','留学'||study_heads::VARCHAR||'人／小语种'||language_heads::VARCHAR||'人')
  WHEN metric='heads' AND business_line='abroad' AND status IN ('available','partial','separate_counts') THEN json_object(
   'actual',actual,'prior',prior,'target',target,'unit','人','status',status,'note','',
   'completion',CASE WHEN actual IS NOT NULL AND target IS NOT NULL AND target<>0 THEN actual/target END,
   'yoy',CASE WHEN actual IS NOT NULL AND prior IS NOT NULL AND prior<>0 THEN actual/prior-1 END,
   'gap',CASE WHEN actual IS NOT NULL AND target IS NOT NULL THEN round(actual-target,2) END,
   'time_gap',CASE WHEN actual IS NOT NULL AND target IS NOT NULL THEN round(actual-target*time_progress,2) END,
   'source_coverage',clipped_source,
   'parts',json_array(json_object('label','留学','actual',study_heads),json_object('label','小语种','actual',language_heads)))
  WHEN clipped_source IS NOT NULL THEN json_object(
   'actual',CASE WHEN status IN ('future','not_covered','not_configured') THEN NULL ELSE actual END,
   'prior',CASE WHEN status IN ('future','not_covered','not_configured') THEN NULL ELSE prior END,
   'target',target,'unit',CASE metric WHEN 'cash' THEN '元' ELSE '人' END,'status',status,
   'note',CASE WHEN status='not_configured' THEN '本部门暂不统计留学完成；贡献见人员产能。' ELSE '' END,
   'completion',CASE WHEN actual IS NOT NULL AND target IS NOT NULL AND target<>0 THEN actual/target END,
   'yoy',CASE WHEN actual IS NOT NULL AND prior IS NOT NULL AND prior<>0 THEN actual/prior-1 END,
   'gap',CASE WHEN actual IS NOT NULL AND target IS NOT NULL THEN round(actual-target,2) END,
   'time_gap',CASE WHEN actual IS NOT NULL AND target IS NOT NULL THEN round(actual-target*time_progress,2) END,
   'source_coverage',clipped_source)
  ELSE json_object(
   'actual',CASE WHEN status IN ('future','not_covered','not_configured') THEN NULL ELSE actual END,
   'prior',CASE WHEN status IN ('future','not_covered','not_configured') THEN NULL ELSE prior END,
   'target',target,'unit',CASE metric WHEN 'cash' THEN '元' ELSE '人' END,'status',status,
   'note',CASE WHEN status='not_configured' THEN '本部门暂不统计留学完成；贡献见人员产能。' ELSE '' END,
   'completion',CASE WHEN actual IS NOT NULL AND target IS NOT NULL AND target<>0 THEN actual/target END,
   'yoy',CASE WHEN actual IS NOT NULL AND prior IS NOT NULL AND prior<>0 THEN actual/prior-1 END,
   'gap',CASE WHEN actual IS NOT NULL AND target IS NOT NULL THEN round(actual-target,2) END,
   'time_gap',CASE WHEN actual IS NOT NULL AND target IS NOT NULL THEN round(actual-target*time_progress,2) END)
  END AS metric_json
 FROM calculated
)
SELECT channel_id,channel_order,metric,metric_json FROM output;
