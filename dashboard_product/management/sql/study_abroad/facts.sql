-- One immutable, isolated source. Parameters are [start_date, end_date),
-- capped by the explicitly declared source cutoff in study_abroad_query.
WITH params AS (
  SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date
), resources AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY resource_id ORDER BY CAST(origin_row_number AS BIGINT)) AS key_row
  FROM landing.study_abroad_market__resources
), contracts AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY contract_id ORDER BY CAST(origin_row_number AS BIGINT)) AS key_row
  FROM landing.study_abroad_market__contracts
), combined AS (
  SELECT 'resource' AS fact_type, 'resources:' || resource_id AS fact_id,
    CASE WHEN consultation_type = '小语种' THEN 'small_language' ELSE 'study_abroad' END AS business_line,
    TRY_CAST(event_date AS DATE) AS event_date, owner, source_owner, market_group, segment_id,
    CAST(team_eligible AS BOOLEAN) AS team_eligible,
    CAST(market_eligible AS BOOLEAN) AS market_eligible,
    CAST(personal_eligible AS BOOLEAN) AS personal_eligible, roster_group, roster_status,
    resource_id, NULL::VARCHAR AS contract_id, NULL::VARCHAR AS customer_key,
    NULL::DECIMAL(38,2) AS gross_amount, status AS resource_status,
    NULL::VARCHAR AS contract_status, country, stage, first_channel, second_channel,
    third_channel, channel_source, campaign, origin_sha256, origin_filename, origin_sheet,
    CAST(origin_row_number AS BIGINT) AS origin_row_number
  FROM resources WHERE key_row = 1
  UNION ALL
  SELECT 'signature', 'contracts:' || contract_id, 'study_abroad',
    TRY_CAST(event_date AS DATE), owner, source_owner, market_group, segment_id,
    CAST(team_eligible AS BOOLEAN), CAST(market_eligible AS BOOLEAN),
    CAST(personal_eligible AS BOOLEAN), roster_group, roster_status,
    resource_id, contract_id, customer_key, CAST(amount AS DECIMAL(38,2)),
    NULL::VARCHAR, contract_status, country, stage, first_channel, second_channel,
    third_channel, NULL::VARCHAR, campaign, origin_sha256, origin_filename, origin_sheet,
    CAST(origin_row_number AS BIGINT)
  FROM contracts WHERE key_row = 1
  UNION ALL
  SELECT 'signature', 'languages:' || origin_sha256 || ':' || origin_row_number,
    'small_language', TRY_CAST(event_date AS DATE), owner, source_owner, market_group, segment_id,
    CAST(team_eligible AS BOOLEAN), CAST(market_eligible AS BOOLEAN),
    CAST(personal_eligible AS BOOLEAN), roster_group, roster_status,
    resource_id, NULL::VARCHAR, customer_key, CAST(amount AS DECIMAL(38,2)),
    NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR,
    first_channel, second_channel, third_channel, NULL::VARCHAR, NULL::VARCHAR,
    origin_sha256, origin_filename, origin_sheet, CAST(origin_row_number AS BIGINT)
  FROM landing.study_abroad_market__languages
)
SELECT c.*,
  CASE WHEN fact_type = 'resource' THEN 1 ELSE 0 END AS resource_count,
  CASE WHEN fact_type = 'resource' AND personal_eligible
    AND COALESCE(resource_status, '') <> '删除' THEN 1 ELSE 0 END AS personal_resource_count,
  CASE WHEN fact_type = 'signature' AND gross_amount > 0 THEN gross_amount
    ELSE 0::DECIMAL(38,2) END AS gross_signing_amount,
  fact_type = 'signature' AND gross_amount > 0 AS positive_signature
FROM combined c CROSS JOIN params p
WHERE c.market_eligible AND c.event_date >= p.start_date AND c.event_date < p.end_date
