-- 留学独立仓来源对账，按标准行中的团队分段，不做正式看板的渠道分段和团队汇总。
-- SSC 保留在来源事实中，所有经营汇总排除该分段。
WITH facts AS (
__STUDY_ABROAD_FACTS__
), expanded AS (
  SELECT *, 'total' AS scope, 'total' AS view_segment_id FROM facts WHERE segment_id IS DISTINCT FROM 'ssc'
  UNION ALL
  SELECT *, CASE WHEN team_eligible THEN 'team' ELSE 'supplemental' END,
    segment_id AS view_segment_id FROM facts WHERE segment_id IS DISTINCT FROM 'ssc'
)
SELECT STRFTIME(event_date, '%Y-%m') AS month, scope, view_segment_id AS segment_id,
  SUM(resource_count) AS resource_count,
  SUM(personal_resource_count) AS personal_resource_count,
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
FROM expanded
GROUP BY month, scope, view_segment_id
ORDER BY month, scope, view_segment_id
