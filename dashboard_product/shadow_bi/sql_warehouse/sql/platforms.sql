CREATE OR REPLACE VIEW business.channel_record_labels AS
WITH cells AS (
 SELECT f.fact_id,f.business_line,f.metric,k.channel_group,j.key,
  CASE WHEN json_type(j.value)='ARRAY' THEN j.value ELSE json_array(j.value) END AS vals
 FROM business.facts f,json_each(f.source_record) j
 JOIN config.channel_keys k ON regexp_replace(lower(j.key),'[\s_-]+','','g')=regexp_replace(lower(k.key),'[\s_-]+','','g')
)
SELECT fact_id,business_line,metric,channel_group,
 trim(json_extract_string(x.value,'$')) AS label
FROM cells,json_each(vals) x WHERE json_type(x.value)='VARCHAR';

CREATE OR REPLACE VIEW business.channel_labels_base AS
SELECT fact_id,business_line,metric,
 CASE WHEN business_line='training' THEN CASE channel_group WHEN 'third' THEN 1 WHEN 'channel' THEN 2
  WHEN 'raw_second' THEN 3 WHEN 'second' THEN 4 WHEN 'consultation' THEN 5 ELSE 6 END
 ELSE CASE channel_group WHEN 'third' THEN 1 WHEN 'raw_second' THEN 2 WHEN 'channel' THEN 2 WHEN 'second' THEN 3 ELSE 4 END END AS layer,
 label,true AS include_brands,true AS include_categories
FROM business.channel_record_labels
UNION ALL
SELECT f.fact_id,f.business_line,f.metric,x.layer,x.label,x.include_brands,true
FROM business.facts f CROSS JOIN LATERAL (
 SELECT CASE WHEN f.business_line='training' THEN 7 ELSE 3 END AS layer,CAST(f.second_channel AS VARCHAR) AS label,true AS include_brands
 UNION ALL SELECT CASE WHEN f.business_line='training' THEN 9 ELSE 4 END,CAST(f.first_channel AS VARCHAR),f.business_line<>'training' OR f.metric<>'cash'
 UNION ALL SELECT 1,CAST(f.third_channel AS VARCHAR),true WHERE f.business_line='abroad'
 UNION ALL SELECT 2,CAST(f.raw_second_channel AS VARCHAR),true WHERE f.business_line='abroad'
) x WHERE nullif(trim(x.label),'') IS NOT NULL;

CREATE OR REPLACE VIEW business.channel_labels AS
SELECT * FROM business.channel_labels_base
UNION ALL
SELECT cash.fact_id,cash.business_line,cash.metric,8,labels.label,true,false
FROM business.facts cash JOIN business.facts orders ON
 cash.business_line='training' AND cash.metric='cash' AND orders.business_line='training' AND orders.metric='orders'
 AND cash.work_order_id=orders.work_order_id
JOIN business.channel_labels_base labels ON labels.fact_id=orders.fact_id
WHERE regexp_replace(lower(coalesce(cash.second_channel,'')),'\s+','','g') IN (SELECT label FROM config.cash_enrichment_labels)
AND NOT EXISTS (
 SELECT 1 FROM business.channel_labels_base own JOIN config.platform_aliases a ON a.kind='category' AND a.platform='合作推荐'
 AND contains(regexp_replace(lower(own.label),'\s+','','g'),a.alias)
 WHERE own.fact_id=cash.fact_id AND regexp_replace(lower(own.label),'\s+','','g') NOT IN (SELECT label FROM config.cash_enrichment_labels)
);

CREATE OR REPLACE VIEW business.platform_layers AS
WITH matched AS (
 SELECT l.fact_id,l.layer,a.kind,a.platform
 FROM business.channel_labels l JOIN config.platform_aliases a ON
 (a.kind='brand' AND l.include_brands OR a.kind='category' AND l.include_categories)
 AND a.alias <> 'ssc' AND contains(regexp_replace(lower(l.label),'\s+','','g'),a.alias)
 UNION ALL
 SELECT fact_id,layer,'category','官网/自有入口' FROM business.channel_labels
 WHERE include_categories AND regexp_matches(lower(label),'(^|[^a-z0-9])app([^a-z0-9]|$)')
), grouped AS (
 SELECT fact_id,layer,list(DISTINCT platform) FILTER(WHERE kind='brand') AS brands,
 list(DISTINCT platform) FILTER(WHERE kind='category') AS categories FROM matched GROUP BY ALL
), classified AS (
 SELECT fact_id,layer,CASE
 WHEN len(brands)=2 AND list_contains(brands,'腾讯广告') AND list_contains(brands,'微信') THEN '微信'
 WHEN len(brands)>1 THEN '其他线上来源'
 WHEN len(brands)=1 THEN brands[1]
 WHEN list_contains(categories,'电话/在线咨询') THEN '电话/在线咨询'
 WHEN len(categories)>1 THEN '其他线上来源' ELSE categories[1] END AS platform,
 CASE WHEN len(brands)>1 AND NOT(len(brands)=2 AND list_contains(brands,'腾讯广告') AND list_contains(brands,'微信')) THEN 'brand_conflict'
 WHEN len(brands)>0 THEN 'brand'
 WHEN list_contains(categories,'电话/在线咨询') THEN 'category'
 WHEN len(categories)>1 THEN 'category_conflict' ELSE 'category' END AS kind
 FROM grouped
)
SELECT *,min(layer) FILTER(WHERE kind='category') OVER(PARTITION BY fact_id) AS first_category
FROM classified;

CREATE OR REPLACE VIEW business.platform_audit AS
WITH choices AS (
 SELECT *,row_number() OVER(PARTITION BY fact_id ORDER BY
  CASE WHEN kind='brand' AND platform<>'腾讯广告' OR kind='brand_conflict' OR kind='category_conflict' AND (first_category IS NULL OR layer<first_category) THEN 0
   WHEN kind='brand' AND platform='腾讯广告' THEN 1 WHEN kind='category' THEN 2 ELSE 3 END,layer) AS choice
 FROM business.platform_layers
)
SELECT f.*,
 CASE WHEN a.platform IS NOT NULL THEN a.platform
      WHEN f.business_line='abroad' AND f.metric IN ('orders','cash')
       AND c.platform IN (SELECT platform FROM config.abroad_paid_third_channels) THEN '其他线上来源'
      ELSE coalesce(c.platform,'其他线上来源') END AS platform,
 CASE WHEN a.platform IS NOT NULL THEN 'confirmed_abroad_third_channel'
      WHEN f.business_line='abroad' AND f.metric IN ('orders','cash')
       AND c.platform IN (SELECT platform FROM config.abroad_paid_third_channels) THEN 'unconfirmed_abroad_paid_channel'
      ELSE c.kind END AS classification_kind,
 CASE WHEN a.platform IS NOT NULL THEN 1 ELSE c.layer END AS classification_layer
FROM business.facts f LEFT JOIN choices c ON f.fact_id=c.fact_id AND c.choice=1
LEFT JOIN config.abroad_paid_third_channels a ON f.business_line='abroad' AND f.metric IN ('orders','cash')
 AND a.label=regexp_replace(coalesce(f.third_channel,''),'__ABROAD_PAID_CHANNEL_SEPARATORS__','','g');

CREATE OR REPLACE TABLE business.online_daily_cache AS
SELECT a.acquisition_scope,CAST(event_date AS DATE) AS event_date,business_line,
 CASE WHEN business_line='training' THEN business_group ELSE '留学整体' END AS expense_group,
 platform,sum(value) FILTER(WHERE metric='orders') AS orders,round(sum(value) FILTER(WHERE metric='cash'),2) AS cash
FROM business.platform_audit CROSS JOIN (VALUES ('被动'),('主动'),('全部')) a(acquisition_scope)
WHERE (business_line='training' AND (a.acquisition_scope='全部' OR acquisition_mode=a.acquisition_scope)
 AND team_id='online_platform' AND business_group IN ('留学预备','高中','大学'))
 OR (business_line='abroad' AND segment_id='study_abroad_online')
GROUP BY ALL;

CREATE OR REPLACE VIEW business.online_scoped_daily AS
SELECT * FROM business.online_daily_cache;

CREATE OR REPLACE VIEW business.online_daily AS
SELECT * EXCLUDE(acquisition_scope) FROM business.online_scoped_daily WHERE acquisition_scope='被动';
