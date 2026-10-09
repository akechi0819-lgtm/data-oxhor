-- A separate projection, never summed to obtain department customer counts.
-- Existing co-creation/transfer weights are not inferred in this source query.
WITH facts AS (
__STUDY_ABROAD_FACTS__
)
SELECT STRFTIME(event_date, '%Y-%m') AS month, owner, segment_id, roster_group,
  CASE WHEN team_eligible THEN 'team' ELSE 'supplemental' END AS scope,
  SUM(personal_resource_count) AS resource_count,
  SUM(CASE WHEN fact_type = 'resource' AND resource_status = '删除' THEN 1 ELSE 0 END) AS deleted_resources,
  SUM(gross_signing_amount)::DECIMAL(38,2) AS gross_signing_amount,
  COUNT(DISTINCT CASE WHEN positive_signature AND business_line = 'study_abroad'
    THEN customer_key END) AS study_abroad_signed_customers,
  COUNT(DISTINCT CASE WHEN positive_signature AND business_line = 'small_language'
    THEN customer_key END) AS small_language_signed_customers,
  CASE WHEN COUNT(DISTINCT CASE WHEN positive_signature THEN business_line END) > 1
    THEN NULL ELSE COUNT(DISTINCT CASE WHEN positive_signature THEN customer_key END)
  END AS signed_customer_count,
  CASE WHEN COUNT(DISTINCT CASE WHEN positive_signature THEN business_line END) > 1
    THEN 'cross_system_unaligned' ELSE 'available' END AS signed_customer_count_status
FROM facts
WHERE personal_eligible
GROUP BY month, owner, segment_id, roster_group, scope
ORDER BY month, segment_id, owner
