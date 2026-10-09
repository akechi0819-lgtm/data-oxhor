-- Diagnostics retain excluded rows and non-positive amounts for audit.
WITH params AS (
  SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date
), combined AS (
  SELECT 'resources' AS source_kind, TRY_CAST(event_date AS DATE) AS event_date,
    CAST(market_eligible AS BOOLEAN) AS market_eligible, owner, segment_id,
    NULL::DECIMAL(38,2) AS amount, status AS resource_status
  FROM landing.study_abroad_market__resources
  UNION ALL
  SELECT 'contracts', TRY_CAST(event_date AS DATE), CAST(market_eligible AS BOOLEAN),
    owner, segment_id, CAST(amount AS DECIMAL(38,2)), NULL::VARCHAR
  FROM landing.study_abroad_market__contracts
  UNION ALL
  SELECT 'languages', TRY_CAST(event_date AS DATE), CAST(market_eligible AS BOOLEAN),
    owner, segment_id, CAST(amount AS DECIMAL(38,2)), NULL::VARCHAR
  FROM landing.study_abroad_market__languages
)
SELECT source_kind, COUNT(*) AS source_rows,
  SUM(CASE WHEN market_eligible THEN 1 ELSE 0 END) AS market_rows,
  SUM(CASE WHEN COALESCE(owner, '') = '' THEN 1 ELSE 0 END) AS blank_owner_rows,
  SUM(CASE WHEN NOT market_eligible AND COALESCE(owner, '') <> '' THEN 1 ELSE 0 END) AS non_market_rows,
  SUM(CASE WHEN market_eligible AND segment_id = 'unassigned' THEN 1 ELSE 0 END) AS unmapped_owner_rows,
  SUM(CASE WHEN market_eligible AND resource_status = '删除' THEN 1 ELSE 0 END) AS deleted_resource_rows,
  SUM(CASE WHEN market_eligible AND amount = 0 THEN 1 ELSE 0 END) AS zero_amount_rows,
  SUM(CASE WHEN market_eligible AND amount < 0 THEN 1 ELSE 0 END) AS negative_amount_rows,
  SUM(CASE WHEN market_eligible AND source_kind <> 'resources' AND amount IS NULL THEN 1 ELSE 0 END) AS missing_amount_rows,
  MIN(event_date) AS first_date, MAX(event_date) AS last_date
FROM combined c CROSS JOIN params p
WHERE c.event_date >= p.start_date AND c.event_date < p.end_date
GROUP BY source_kind ORDER BY source_kind
