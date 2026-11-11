-- 与旧 Decimal 分摊保持一致：整数商构造权重，避免 DuckDB 的 / 提前转 DOUBLE。
-- 本次完整参照的分母为 1–4、金额为整分；scale 30 聚合绝对和小于 1,277,201。
-- Source identity and attribution remain SQL, including precedence between name evidence.
CREATE OR REPLACE MACRO business.pc_text(v) AS coalesce(trim(CAST(v AS VARCHAR)), '');
CREATE OR REPLACE MACRO business.pc_names(ns, txt) AS list_filter(ns, n -> contains(coalesce(txt,''),n));
CREATE OR REPLACE MACRO business.pc_match(ns, campaign, entry_person, description) AS
CASE
 WHEN coalesce(campaign,'') NOT IN ('是','否','None','','NULL') AND len(business.pc_names(ns,campaign))>0 THEN business.pc_names(ns,campaign)
 WHEN len(business.pc_names(ns,regexp_extract(coalesce(description,''),'市场人员\s*[:：]\s*([^\s,，;；]+)',1)))>0
 THEN business.pc_names(ns,regexp_extract(coalesce(description,''),'市场人员\s*[:：]\s*([^\s,，;；]+)',1))
 WHEN len(business.pc_names(ns,regexp_extract(coalesce(description,''),'([^\s,，;；/]+)市场资源',1)))>0
 THEN business.pc_names(ns,regexp_extract(coalesce(description,''),'([^\s,，;；/]+)市场资源',1))
 WHEN len(business.pc_names(ns,entry_person))>0 THEN business.pc_names(ns,entry_person)
 ELSE business.pc_names(ns,regexp_replace(coalesce(description,''),'\d{4}\.\d{2}\.\d{2}-\S+',' ','g')) END;
CREATE OR REPLACE MACRO business.pc_rid(v) AS
CASE WHEN regexp_full_match(regexp_replace(regexp_replace(business.pc_text(v),'(?i)^(资源\s*ID|ID)\s*[:：]\s*',''),'\.0$',''),'[0-9]+')
THEN regexp_replace(regexp_replace(business.pc_text(v),'(?i)^(资源\s*ID|ID)\s*[:：]\s*',''),'\.0$','') END;
CREATE OR REPLACE MACRO business.pc_owner(v, ns) AS
CASE WHEN len(list_filter(ns,n->business.pc_text(v)=n OR regexp_full_match(business.pc_text(v),n||'[0-9]+')))=1
THEN list_extract(list_filter(ns,n->business.pc_text(v)=n OR regexp_full_match(business.pc_text(v),n||'[0-9]+')),1) END;
CREATE OR REPLACE VIEW business.contribution_roster AS SELECT
 coalesce(list(name ORDER BY name),[]::VARCHAR[]) AS names,
 coalesce(list(name ORDER BY name) FILTER(WHERE business_line='training'),[]::VARCHAR[]) AS training,
 coalesce(list(name ORDER BY name) FILTER(WHERE business_line='abroad'),[]::VARCHAR[]) AS abroad,
 coalesce(list(name ORDER BY name) FILTER(WHERE list_contains(team_ids,'offline_market') OR abroad_roster),[]::VARCHAR[]) AS offline
FROM config.people;
CREATE OR REPLACE TABLE business.contribution_source AS
WITH raw AS (
 SELECT 'resources' AS source,to_json(r) AS j FROM landing.study_abroad_market__resources r
 UNION ALL SELECT 'contracts',to_json(r) FROM landing.study_abroad_market__contracts r
 UNION ALL SELECT 'languages',to_json(r) FROM landing.study_abroad_market__languages r
), parsed AS (
 SELECT source,j,j->>'origin_row_number' AS source_row_number,
 business.pc_rid(j->>'resource_id') AS resource_id,
 nullif(business.pc_text(j->>'record_key'),'') AS record_key,
 nullif(business.pc_text(j->>'contract_id'),'') AS contract_id,
 nullif(business.pc_text(j->>'work_order_id'),'') AS work_order_id,
 business.pc_owner(j->>'owner',r.names) AS owner,
 nullif(business.pc_text(j->>'source_owner'),'') AS source_owner,
 nullif(business.pc_text(j->>'market_group'),'') AS market_group,
 nullif(business.pc_text(j->>'source_group'),'') AS source_group,
 nullif(business.pc_text(j->>'segment_id'),'') AS segment_id,
 try_cast(j->>'event_date' AS DATE) AS event_date,
 CASE WHEN source='contracts' THEN substr(j->>'month',1,7) ELSE substr(j->>'event_date',1,7) END AS month,
 j->>'campaign' AS campaign,j->>'description' AS description,
 j->>'status' AS order_status,j->>'consultation_type' AS consultation_type,
 CASE WHEN source='resources' THEN 1::DECIMAL(38,6)
 ELSE try_cast(replace(replace(j->>'amount',',',''),'￥','') AS DECIMAL(38,6)) END AS value,
 lower(coalesce(j->>'market_eligible',''))<>'false' AND lower(coalesce(j->>'personal_eligible',''))<>'false'
 AND coalesce(j->>'segment_id','') NOT IN ('ssc','unassigned') AS eligible,
 source='resources' OR (lower(coalesce(j->>'amount_status',''))<>'missing' AND (j->>'amount') IS NOT NULL) AS amount_present
 FROM raw CROSS JOIN business.contribution_roster r
)
SELECT *,CASE WHEN market_group IS NOT NULL OR segment_id IS NOT NULL
 THEN (market_group IS NULL OR market_group='国际市场') AND (segment_id IS NULL OR segment_id='international_market')
 AND (market_group='国际市场' OR segment_id='international_market')
 ELSE source_group='国际市场' END AS marked,
 (market_group IS NOT NULL AND segment_id IS NOT NULL AND (market_group='国际市场')<>(segment_id='international_market'))
 OR (source_group='国际市场' AND (coalesce(market_group,'国际市场')<>'国际市场' OR coalesce(segment_id,'international_market')<>'international_market')) AS mapping_conflict
FROM parsed;
CREATE OR REPLACE TABLE business.contribution_latest_resources AS
SELECT resource_id,max(event_date) AS event_date FROM business.contribution_source WHERE source='resources' AND resource_id IS NOT NULL GROUP BY resource_id;
CREATE OR REPLACE TABLE business.contribution_resource_markers AS
SELECT s.* FROM business.contribution_source s JOIN business.contribution_latest_resources l USING(resource_id,event_date)
WHERE source='resources' AND eligible AND marked
QUALIFY row_number() OVER(PARTITION BY resource_id ORDER BY CAST(source_row_number AS BIGINT))=1;
CREATE OR REPLACE VIEW business.contribution_marker_conflicts AS
SELECT s.resource_id FROM business.contribution_source s JOIN business.contribution_latest_resources l USING(resource_id,event_date)
WHERE source='resources' AND eligible AND marked GROUP BY s.resource_id
HAVING count(DISTINCT to_json(struct_pack(source_owner:=source_owner,record_key:=record_key)))>1;
CREATE OR REPLACE TABLE business.contribution_abroad_raw_events AS
SELECT s.source||':'||CASE s.source WHEN 'resources' THEN coalesce(s.resource_id,s.record_key)
 WHEN 'contracts' THEN s.contract_id ELSE coalesce(s.record_key,s.source_row_number) END AS key,
 s.source,s.source_row_number,'abroad' AS line,
 CASE s.source WHEN 'resources' THEN CASE s.consultation_type WHEN '留学' THEN 'study_abroad' WHEN '小语种' THEN 'small_language' END
 WHEN 'contracts' THEN 'study_abroad' ELSE 'small_language' END AS product_scope,
 CASE WHEN s.source='resources' THEN 'orders' ELSE 'cash' END AS metric,s.month,
 CASE WHEN s.source='resources' THEN nullif(s.order_status,'') END AS order_status,
 s.value,s.owner,s.resource_id,s.work_order_id,s.campaign,s.description,NULL::VARCHAR AS entry_person,
 s.record_key,s.j->>'origin_sha256' AS origin_sha256,s.j->>'origin_filename' AS origin_filename,
 s.j->>'origin_sheet' AS origin_sheet,s.j->>'origin_row_number' AS origin_row_number,
 CASE WHEN s.source='resources' THEN s.marked ELSE m.marked END AS has_marker,
 CASE WHEN s.source='resources' THEN s.source_owner ELSE m.source_owner END AS marker_source_owner,
 CASE WHEN s.source='resources' THEN s.record_key ELSE m.record_key END AS marker_source_key,
 CASE WHEN s.source='resources' THEN s.source_row_number ELSE m.source_row_number END AS marker_source_row_number,
 CASE WHEN s.source='resources' THEN s.j->>'origin_sha256' ELSE m.j->>'origin_sha256' END AS marker_source_sha256,
 CASE WHEN s.source='resources' THEN s.j->>'origin_filename' ELSE m.j->>'origin_filename' END AS marker_source_filename,
 CASE WHEN s.source='resources' THEN s.j->>'origin_sheet' ELSE m.j->>'origin_sheet' END AS marker_source_sheet,
 CASE WHEN s.source='resources' THEN s.campaign ELSE m.campaign END AS marker_campaign,
 CASE WHEN s.source='resources' THEN s.description ELSE m.description END AS marker_description,
 CASE WHEN s.source='resources' THEN CASE WHEN s.market_group='国际市场' OR s.source_group='国际市场' THEN '国际市场' ELSE s.segment_id END
 ELSE CASE WHEN m.market_group='国际市场' OR m.source_group='国际市场' THEN '国际市场' ELSE m.segment_id END END AS marker_value,
 'training' AS marker_source_line,'abroad' AS marker_destination_line,
 'study_abroad_international_market' AS marker_kind,s.event_date
FROM business.contribution_source s
LEFT JOIN business.contribution_resource_markers m ON m.resource_id=s.resource_id
LEFT JOIN business.contribution_latest_resources l ON l.resource_id=s.resource_id
WHERE s.eligible AND s.amount_present
 AND (s.source<>'contracts' OR s.contract_id IS NOT NULL)
 AND (s.source<>'resources' OR (s.resource_id IS NOT NULL OR s.record_key IS NOT NULL)
  AND (s.resource_id IS NULL OR s.event_date>=l.event_date))
 AND (s.owner IS NOT NULL OR s.source='resources' AND s.marked);
CREATE OR REPLACE VIEW business.contribution_identity_conflicts AS
SELECT key FROM business.contribution_abroad_raw_events GROUP BY key
HAVING count(DISTINCT to_json(struct_pack(product_scope:=product_scope,month:=month,owner:=owner,value:=value,
 status:=order_status,campaign:=CASE WHEN source='resources' THEN business.pc_text(campaign) ELSE '' END,
 marker_kind:=CASE WHEN has_marker THEN marker_kind END,source_owner:=marker_source_owner)))>1;
CREATE OR REPLACE VIEW business.contribution_invalid_events AS
SELECT key FROM business.contribution_abroad_raw_events WHERE event_date IS NULL OR try_cast(month||'-01' AS DATE) IS NULL OR product_scope IS NULL OR value IS NULL;
CREATE OR REPLACE TABLE business.contribution_raw_events AS
SELECT * EXCLUDE(event_date) FROM business.contribution_abroad_raw_events
QUALIFY row_number() OVER(PARTITION BY key ORDER BY CAST(source_row_number AS BIGINT))=1
UNION ALL BY NAME
SELECT f.fact_id AS key,'bi' AS source,CAST(f.source_row_number AS VARCHAR) AS source_row_number,
 'training' AS line,'training' AS product_scope,f.metric,substr(CAST(f.event_date AS VARCHAR),1,7) AS month,
 coalesce(nullif(f.order_status,''),nullif(o.order_status,'')) AS order_status,CAST(f.value AS DECIMAL(38,6)) AS value,
 NULL::VARCHAR AS owner,business.pc_rid(o.resource_id) AS resource_id,f.work_order_id,
 coalesce(nullif(o.campaign_name,''),f.campaign_name) AS campaign,o.resource_description AS description,
 o.resource_entry_person AS entry_person,o.first_channel='双分' AS has_marker,
 o.resource_entry_person AS marker_source_owner,f.work_order_id AS marker_source_key,
 CAST(coalesce(o.source_row_number,f.source_row_number) AS VARCHAR) AS marker_source_row_number,
 '双分' AS marker_value,'abroad' AS marker_source_line,'training' AS marker_destination_line,
 'bi_first_channel' AS marker_kind
FROM business.training_personnel_facts f LEFT JOIN source.order_events o ON o.work_order_id=f.work_order_id
WHERE f.business_line='training';
CREATE OR REPLACE TABLE business.contribution_marker_people AS
WITH matched AS (
 SELECT e.*,r.names,r.offline,r.training,r.abroad,
 business.pc_match(CASE marker_source_line WHEN 'training' THEN r.training ELSE r.abroad END,'',marker_source_owner,'') AS authoritative,
 business.pc_match(CASE marker_source_line WHEN 'training' THEN r.training ELSE r.abroad END,
  CASE WHEN metric='cash' AND source<>'bi' THEN coalesce(nullif(campaign,''),marker_campaign) ELSE campaign END,'',
  CASE WHEN metric='cash' AND source<>'bi' THEN coalesce(nullif(description,''),marker_description) ELSE description END) AS marker_activity
 FROM business.contribution_raw_events e CROSS JOIN business.contribution_roster r
), conflicts AS (
 SELECT *,marker_kind='study_abroad_international_market' AND len(authoritative)>0 AND len(marker_activity)>0
 AND len(list_intersect(authoritative,marker_activity))=0 AS marker_conflict FROM matched
)
SELECT *,CASE WHEN marker_conflict THEN authoritative WHEN len(authoritative)>0 THEN list_distinct(authoritative||marker_activity) ELSE []::VARCHAR[] END AS marker_creators,
 coalesce(has_marker,false) AND (metric='orders' OR source='bi' OR
 list_contains(CASE marker_source_line WHEN 'training' THEN training ELSE abroad END,owner)
 AND list_contains(CASE WHEN marker_conflict THEN authoritative WHEN len(authoritative)>0 THEN list_distinct(authoritative||marker_activity) ELSE []::VARCHAR[] END,owner)) AS apply_marker
FROM conflicts;
CREATE OR REPLACE TABLE business.contribution_events AS
SELECT * EXCLUDE(campaign,description),
 CASE WHEN apply_marker AND metric='cash' AND source<>'bi' THEN coalesce(nullif(campaign,''),marker_campaign) ELSE campaign END AS campaign,
 CASE WHEN apply_marker AND metric='cash' AND source<>'bi' THEN coalesce(nullif(description,''),marker_description) ELSE description END AS description
FROM business.contribution_marker_people;
CREATE OR REPLACE TABLE business.contribution_participants AS
WITH matched AS (
 SELECT *,business.pc_match(names,regexp_replace(coalesce(campaign,''),'（[^）]*）|\([^)]*\)',' ','g'),entry_person,
 regexp_replace(coalesce(description,''),'（[^）]*）|\([^)]*\)',' ','g')) AS matched_primary,
 business.pc_names(names,array_to_string(regexp_extract_all(coalesce(campaign,''),'（[^）]*）|\([^)]*\)'), ' ')) AS secondary,
 business.pc_match(list_intersect(offline,CASE marker_destination_line WHEN 'training' THEN training ELSE abroad END),campaign,'',description) AS marker_receivers
 FROM business.contribution_events
), base AS (
 SELECT *,CASE WHEN len(matched_primary)=0 AND owner IS NOT NULL AND NOT list_contains(secondary,owner)
 THEN [owner] ELSE matched_primary END AS primary0 FROM matched
), expanded AS (
 SELECT *,CASE WHEN len(list_intersect(primary0,training))>0 AND len(list_intersect(primary0,abroad))=0 THEN
 list_distinct(primary0||list_intersect(secondary,training))
 WHEN len(list_intersect(primary0,abroad))>0 AND len(list_intersect(primary0,training))=0 THEN
 list_distinct(primary0||list_intersect(secondary,abroad)) ELSE primary0 END AS primary_people FROM base
)
SELECT *,CASE WHEN len(list_intersect(primary_people,training))>0 AND len(list_intersect(primary_people,abroad))=0 THEN 'training'
 WHEN len(list_intersect(primary_people,abroad))>0 AND len(list_intersect(primary_people,training))=0 THEN 'abroad' END AS primary_line,
 list_intersect(primary_people,offline) AS activity_creators,
 list_intersect(list_intersect(secondary,offline),CASE line WHEN 'training' THEN training ELSE abroad END) AS activity_receivers
FROM expanded;
CREATE OR REPLACE TABLE business.contribution_allocation_groups AS
WITH strategy AS (
 SELECT *,CASE WHEN apply_marker THEN 'marked'
 WHEN primary_line IS NOT NULL AND primary_line<>line AND len(activity_creators)>0
 AND (source='bi' OR list_contains(list_distinct(primary_people||secondary),owner)) THEN 'handoff'
 ELSE 'ordinary' END AS strategy
 FROM business.contribution_participants
)
SELECT key,'output' AS bucket,CASE WHEN marker_conflict THEN 'source_marker_owner_authoritative'
 WHEN len(marker_receivers)>0 THEN 'source_marker_handoff' ELSE 'source_marker_independent_output' END AS rule,
 CASE WHEN marker_conflict OR len(marker_receivers)=0 THEN 1.0 ELSE .5 END AS share,
 marker_creators AS participants
FROM strategy WHERE strategy='marked' AND line=marker_destination_line AND len(marker_creators)>0
UNION ALL
SELECT key,'received',CASE WHEN len(marker_creators)>0 THEN 'source_marker_handoff' ELSE 'source_marker_without_active_source_owner' END,
 .5,marker_receivers FROM strategy WHERE strategy='marked' AND line=marker_destination_line AND NOT marker_conflict AND len(marker_receivers)>0
UNION ALL
SELECT key,'output',CASE WHEN len(activity_receivers)>0 THEN 'activity_market_handoff' ELSE 'independent_cross_output' END,
 CASE WHEN len(activity_receivers)>0 THEN .5 ELSE 1.0 END,activity_creators FROM strategy WHERE strategy='handoff'
UNION ALL
SELECT key,'received','activity_market_handoff',.5,activity_receivers FROM strategy WHERE strategy='handoff' AND len(activity_receivers)>0
UNION ALL
SELECT key,NULL,'ordinary_co_creation',1.0,CASE WHEN source='bi' THEN primary_people WHEN owner IS NOT NULL THEN [owner] ELSE []::VARCHAR[] END
FROM strategy WHERE strategy='ordinary';
CREATE OR REPLACE TABLE business.contribution_allocations AS
WITH members AS (
 SELECT g.* EXCLUDE(participants),p.name,p.business_line,p.team_ids,
 list_contains(p.team_ids,'online_private') AS virtual,
 count(*) FILTER(WHERE NOT list_contains(p.team_ids,'online_private') AND list_contains(p.team_ids,'offline_market')) OVER(PARTITION BY key,bucket,rule) AS denominator
 FROM business.contribution_allocation_groups g CROSS JOIN UNNEST(g.participants) AS member(name)
 JOIN config.people p ON p.name=member.name
 WHERE list_contains(p.team_ids,'online_private') OR list_contains(p.team_ids,'offline_market')
)
SELECT key,name AS person,coalesce(bucket,CASE WHEN m.business_line=e.line THEN 'self' ELSE 'output' END) AS bucket,
 CASE WHEN virtual THEN cast(share as decimal(38,28)) ELSE CASE WHEN (CASE WHEN share=.5 THEN denominator*2 ELSE denominator END)=1 THEN 1::decimal(38,28) ELSE cast('0.'||lpad((10000000000000000000000000000::hugeint//(CASE WHEN share=.5 THEN denominator*2 ELSE denominator END))::varchar,28,'0') as decimal(38,28)) END END AS weight,rule
FROM members m JOIN business.contribution_events e USING(key);
CREATE OR REPLACE VIEW business.contributions AS
SELECT e.key,e.source,try_cast(e.source_row_number AS BIGINT) AS source_row_number,e.month,e.resource_id,e.work_order_id,e.line,e.metric,e.product_scope,e.order_status,
 e.record_key,e.origin_sha256,e.origin_filename,e.origin_sheet,try_cast(e.origin_row_number AS BIGINT) AS origin_row_number,
 a.person,a.bucket,a.weight,struct_pack(
 "00":=e.metric<>'orders' OR coalesce(e.order_status,'') NOT IN ('删除','回收','死单'),
 "01":=e.metric<>'orders' OR coalesce(e.order_status,'') NOT IN ('删除','回收'),
 "10":=e.metric<>'orders' OR coalesce(e.order_status,'')<>'死单',
 "11":=true) AS inclusion,e.value AS source_value,cast(e.value as decimal(38,2))*a.weight AS credited_value,a.rule,
 e.has_marker,e.apply_marker,e.marker_kind,e.marker_value,e.marker_source_line,e.marker_destination_line,
 CASE WHEN e.has_marker THEN e.marker_source_owner END AS marker_source_owner,
 CASE WHEN e.has_marker THEN e.marker_source_key END AS marker_source_key,
 CASE WHEN e.has_marker THEN try_cast(e.marker_source_row_number AS BIGINT) END AS marker_source_row_number,
 e.marker_source_sha256,e.marker_source_filename,
 e.marker_source_sheet,e.marker_campaign,e.marker_description,
 CASE WHEN e.has_marker THEN CASE WHEN e.source='bi' THEN json_object('kind',e.marker_kind,'value',e.marker_value,
 'direction','abroad_to_training','source_business_line',e.marker_source_line,'destination_business_line',e.marker_destination_line,
 'source_owner',e.marker_source_owner,'source_key',e.marker_source_key,'source_row_number',try_cast(e.marker_source_row_number AS BIGINT))
 ELSE json_object('kind',e.marker_kind,'value',e.marker_value,'direction','training_to_abroad',
 'source_business_line',e.marker_source_line,'destination_business_line',e.marker_destination_line,
 'source_owner',e.marker_source_owner,'source_key',e.marker_source_key,'source_row_number',e.marker_source_row_number,
 'source_sha256',e.marker_source_sha256,'source_filename',e.marker_source_filename,'source_sheet',e.marker_source_sheet,
 'campaign',e.marker_campaign,'description',e.marker_description,'resource_id',e.resource_id) END END AS cross_business_marker
FROM business.contribution_events e JOIN business.contribution_allocations a USING(key)
JOIN config.people p ON p.name=a.person
WHERE (p.abroad_roster OR list_contains(p.team_ids,'offline_market'))
AND e.month IN (SELECT period_id FROM business.periods WHERE kind='month')
AND e.month<=substr(CAST((SELECT through_date FROM config.clock) AS VARCHAR),1,7);
CREATE OR REPLACE VIEW business.contribution_marker_diagnostics AS
SELECT e.*,list_sort(list_distinct(list_intersect(offline,marker_receivers||
 coalesce([business.pc_owner(marker_source_owner,CASE marker_source_line WHEN 'training' THEN training ELSE abroad END)],[]::VARCHAR[])||
 coalesce([owner],[]::VARCHAR[])))) AS affected_people,
 '标记来源人员或明确接收人员未匹配当前名单' AS reason,
 CASE source WHEN 'resources' THEN '留学资源' WHEN 'contracts' THEN '留学签约' WHEN 'languages' THEN '小语种签约'
 ELSE CASE metric WHEN 'orders' THEN '语培工单' ELSE '语培现金' END END AS source_label
FROM business.contribution_participants e
WHERE has_marker AND NOT EXISTS(SELECT 1 FROM business.contribution_allocations a WHERE a.key=e.key)
AND e.month IN (SELECT period_id FROM business.periods WHERE kind='month')
AND e.month<=substr(CAST((SELECT through_date FROM config.clock) AS VARCHAR),1,7);
CREATE OR REPLACE VIEW business.contribution_pending AS
SELECT * FROM business.contribution_marker_diagnostics WHERE len(affected_people)>0
AND (metric<>'orders' OR coalesce(order_status,'') NOT IN ('删除','回收'));
CREATE OR REPLACE VIEW business.contribution_status_ledger AS
SELECT c.*,s.state FROM business.contributions c CROSS JOIN (VALUES ('00'),('01'),('10'),('11')) s(state)
WHERE metric<>'orders' OR ((coalesce(order_status,'') NOT IN ('删除','回收') OR left(s.state,1)='1')
 AND (coalesce(order_status,'')<>'死单' OR right(s.state,1)='1'));
CREATE OR REPLACE VIEW business.contribution_totals AS
SELECT month,person,state,product_scope,metric,bucket,sum(credited_value) AS value
FROM (
 SELECT * EXCLUDE(product_scope),'all' AS product_scope FROM business.contribution_status_ledger
 UNION ALL BY NAME SELECT * FROM business.contribution_status_ledger WHERE product_scope<>'training'
 UNION ALL BY NAME SELECT * EXCLUDE(product_scope),s.product_scope FROM business.contribution_status_ledger
 CROSS JOIN (VALUES ('study_abroad'),('small_language')) s(product_scope) WHERE business.contribution_status_ledger.product_scope='training'
) GROUP BY ALL;
CREATE OR REPLACE VIEW business.contribution_coverage AS
WITH training AS (
 SELECT metric,min(CAST(event_date AS DATE)) AS start_date,max(CAST(event_date AS DATE)) AS end_date
 FROM business.training_personnel_facts WHERE business_line='training' GROUP BY metric
), months AS (SELECT period_id AS month FROM business.periods WHERE kind='month'),
metrics AS (SELECT * FROM (VALUES ('orders'),('cash')) t(metric))
SELECT m.month,x.metric,
 CASE WHEN m.month BETWEEN strftime(t.start_date,'%Y-%m') AND strftime(t.end_date,'%Y-%m')
 THEN least(t.end_date,last_day(CAST(m.month||'-01' AS DATE)),(SELECT through_date FROM config.clock)) END AS training_through,
 max(s.event_date) AS abroad_through,
 count(s.event_date)>0 AS abroad_month_connected
FROM months m CROSS JOIN metrics x LEFT JOIN training t USING(metric)
LEFT JOIN business.contribution_source s ON s.month=m.month
 AND (x.metric='orders' AND s.source='resources' AND (s.resource_id IS NOT NULL OR s.record_key IS NOT NULL)
 OR x.metric='cash' AND (s.source='contracts' AND s.contract_id IS NOT NULL OR s.source='languages'))
GROUP BY m.month,x.metric,t.start_date,t.end_date;
CREATE OR REPLACE VIEW business.contribution_capacity AS
WITH keys AS (
 SELECT period_id AS month,p.name AS person,p.business_line,p.home_group,s.state,sc.product_scope,m.metric
 FROM business.periods CROSS JOIN config.people p CROSS JOIN (VALUES ('00'),('01'),('10'),('11')) s(state)
 CROSS JOIN (VALUES ('all'),('study_abroad'),('small_language')) sc(product_scope)
 CROSS JOIN (VALUES ('orders'),('cash')) m(metric)
 WHERE kind='month' AND (p.abroad_roster OR list_contains(p.team_ids,'offline_market'))
 AND period_id<=substr(CAST((SELECT through_date FROM config.clock) AS VARCHAR),1,7)
), sums AS (
 SELECT k.*,coalesce(sum(value) FILTER(WHERE bucket='self'),0) AS self_value,
 coalesce(sum(value) FILTER(WHERE bucket='received'),0) AS received,
 coalesce(sum(value) FILTER(WHERE bucket='output'),0) AS output
 FROM keys k LEFT JOIN business.contribution_totals t USING(month,person,state,product_scope,metric) GROUP BY ALL
), history AS (
 SELECT month,name,product_scope,metric,value FROM config.contribution_history
 UNION ALL SELECT month,name,'all',metric,CASE WHEN count(value)=2 THEN sum(value) END
 FROM config.contribution_history GROUP BY month,name,metric
), prepared AS (
 SELECT s.*,t.target,(s.business_line='abroad' OR cv.training_through IS NOT NULL) AS own_connected,
 (s.business_line='training' OR cv.training_through IS NOT NULL) AS output_connected,h.name IS NOT NULL AND s.business_line='abroad' AND s.month IN ('2026-06','2026-07','2026-08') AS confirmed_history,h.value AS history_value
 FROM sums s JOIN business.contribution_coverage cv ON cv.month=s.month AND cv.metric=s.metric
 LEFT JOIN config.personal_targets t ON t.name=s.person AND t.business_line=s.business_line AND t.month=s.month AND t.metric=s.metric
 LEFT JOIN history h ON h.name=s.person AND h.month=s.month AND h.metric=s.metric AND h.product_scope=s.product_scope
)
SELECT * EXCLUDE(self_value,received,history_value,output,completion_coefficient),
 CASE WHEN NOT own_connected OR confirmed_history THEN NULL WHEN metric='cash' THEN round_even(self_value,2) ELSE self_value END AS self,
 CASE WHEN NOT own_connected OR confirmed_history THEN NULL WHEN metric='cash' THEN round_even(received,2) ELSE received END AS received,
 CASE WHEN confirmed_history THEN history_value WHEN NOT own_connected THEN NULL
 WHEN metric='cash' THEN round_even(self_value+received,2) ELSE self_value+received END AS own_total,
 CASE WHEN output_connected THEN CASE WHEN metric='cash' THEN round_even(output,2) ELSE output END END AS output,
 CASE WHEN confirmed_history OR NOT own_connected OR NOT output_connected THEN NULL
 WHEN metric='cash' THEN round_even(self_value+output,2) ELSE self_value+output END AS created_total,
 CASE WHEN confirmed_history OR NOT own_connected THEN NULL ELSE self_value/nullif(self_value+received,0) END AS self_rate,
 CAST(CAST(CAST(completion_coefficient AS decimal(38,0))*0.0000000000000000000000000001::decimal(29,28) AS varchar) AS double) AS completion
FROM (
 SELECT *,
 -- 目标遵循 DECIMAL(24,2) 合同，以分为整数系数；字符串转 DOUBLE 避免二次舍入。
 cast(replace(cast(cast(CASE WHEN confirmed_history THEN cast(history_value as decimal(38,30))
  WHEN own_connected THEN self_value+received END AS decimal(38,28)) AS varchar),'.','') AS hugeint)*100
 //cast(nullif(target,0)*100 AS hugeint) AS completion_coefficient
 FROM prepared
);
CREATE OR REPLACE VIEW business.contribution_diagnostics AS
SELECT 'international_marker_mapping_conflicts' AS diagnostic,count(*) AS value FROM business.contribution_source WHERE mapping_conflict
UNION ALL SELECT 'deleted_training_orders',count(*) FROM business.contribution_raw_events WHERE source='bi' AND metric='orders' AND order_status='删除'
UNION ALL SELECT 'deleted_abroad_orders',count(*) FROM business.contribution_abroad_raw_events WHERE metric='orders' AND order_status='删除'
UNION ALL SELECT 'exact_duplicate_abroad_rows',count(*)-count(DISTINCT key) FROM business.contribution_abroad_raw_events
UNION ALL SELECT 'unattributed_events',count(*) FROM business.contribution_events e WHERE e.month IN (SELECT period_id FROM business.periods WHERE kind='month') AND e.month<=substr(CAST((SELECT through_date FROM config.clock) AS VARCHAR),1,7) AND NOT EXISTS(SELECT 1 FROM business.contribution_allocations a WHERE a.key=e.key)
UNION ALL SELECT 'marker_outside_personnel_scope',count(*) FROM business.contribution_marker_diagnostics WHERE len(affected_people)=0;

CREATE OR REPLACE VIEW business.contribution_owner_diagnostics AS
SELECT CASE WHEN nullif(business.pc_text(j->>'owner'),'') IS NULL THEN 'blank_abroad_owner' ELSE 'owner_outside_roster' END AS diagnostic,count(*) AS value
FROM business.contribution_source
WHERE owner IS NULL AND
 (source='resources' AND (resource_id IS NOT NULL OR record_key IS NOT NULL) AND NOT coalesce(marked,false)
 OR source<>'resources' AND eligible AND amount_present AND (source<>'contracts' OR contract_id IS NOT NULL))
GROUP BY 1;
CREATE OR REPLACE VIEW business.contribution_remaining_diagnostics AS
SELECT 'diagnostics_missing_amount' AS diagnostic,count(*) AS value FROM business.contribution_source
WHERE source<>'resources' AND eligible AND NOT amount_present AND (source<>'contracts' OR contract_id IS NOT NULL)
UNION ALL SELECT 'invalid_abroad_resource_id',count(*) FROM business.contribution_source WHERE source='resources' AND resource_id IS NULL AND record_key IS NULL
UNION ALL SELECT 'superseded_abroad_resource_rows',count(*) FROM business.contribution_source s JOIN business.contribution_latest_resources l USING(resource_id)
WHERE source='resources' AND eligible AND (owner IS NOT NULL OR marked) AND s.event_date<l.event_date;
