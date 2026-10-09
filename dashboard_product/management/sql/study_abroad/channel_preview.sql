-- New-source binding remains proposed. Reuse existing channel labels without
-- changing owner-based market eligibility, team attribution, or base totals.
WITH facts AS (
__STUDY_ABROAD_FACTS__
), dictionary(raw_first, raw_second, raw_third, legacy_first, legacy_second, mapping_status, mapping_rule) AS (
  VALUES
__CHANNEL_DICTIONARY__
), grade_channels(resource_id, school_channel, rule_id) AS (
  VALUES
__WORK_ORDER_GRADE_CHANNELS__
), mapped AS (
  SELECT f.*, d.legacy_first,
    COALESCE(o.school_channel, d.legacy_second) AS legacy_second,
    CASE WHEN o.rule_id IS NOT NULL THEN 'confirmed_new_source' ELSE d.mapping_status END AS mapping_status,
    COALESCE(o.rule_id, d.mapping_rule) AS mapping_rule
  FROM facts f LEFT JOIN dictionary d
    ON COALESCE(f.first_channel, '') = d.raw_first
    AND COALESCE(f.second_channel, '') = d.raw_second
    AND COALESCE(f.third_channel, '') = d.raw_third
  LEFT JOIN grade_channels o ON f.resource_id = o.resource_id
    AND d.legacy_first = '市场活动' AND d.legacy_second IS NULL
), expanded AS (
  SELECT *, 'total' AS scope, 'total' AS view_segment FROM mapped
  UNION ALL
  SELECT *, CASE WHEN team_eligible THEN 'team' ELSE 'supplemental' END, segment_id FROM mapped
)
SELECT STRFTIME(event_date, '%Y-%m') AS month, scope, view_segment AS segment_id,
  legacy_first AS first_channel, legacy_second AS second_channel,
  mapping_status, mapping_rule,
  CASE WHEN mapping_status = 'confirmed_new_source' THEN 'confirmed'
    ELSE 'proposed_source_binding' END AS binding_status,
  SUM(resource_count) AS resource_count, SUM(personal_resource_count) AS personal_resource_count,
  SUM(gross_signing_amount)::DECIMAL(38,2) AS gross_signing_amount,
  COUNT(DISTINCT CASE WHEN positive_signature AND business_line = 'study_abroad' THEN customer_key END)
    AS study_abroad_signed_customers,
  COUNT(DISTINCT CASE WHEN positive_signature AND business_line = 'small_language' THEN customer_key END)
    AS small_language_signed_customers
FROM expanded
GROUP BY month, scope, view_segment, legacy_first, legacy_second, mapping_status, mapping_rule
ORDER BY month, scope, view_segment, mapping_status, legacy_first, legacy_second
