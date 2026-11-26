"""Period ROI datasets for the online dashboard (Superset Jinja SQL)."""


def roi_dashboard_sql(kind):
    if kind not in {'training', 'abroad', 'roi', 'cpl', 'spend', 'summary'}:
        raise ValueError(f'unknown ROI dataset: {kind}')
    table = kind in {'training', 'abroad'}
    line_filter = "AND l.business_line = '" + kind + "'" if table else ''
    period_filter = "" if table or kind == 'summary' else "AND p.kind = 'month'"
    component_rows = "UNION ALL SELECT * FROM components" if table else ''
    return r"""
{% set requested_groups = filter_values('平台业务组', remove_filter=True) %}
{% set requested_platforms = filter_values('平台', remove_filter=True) %}
{% set allowed_platforms = ['抖音', '小红书', '腾讯广告'] %}
{% set chosen = namespace(platforms=[]) %}
{% for platform in requested_platforms %}
  {% if platform in allowed_platforms %}{% set chosen.platforms = chosen.platforms + [platform] %}{% endif %}
{% endfor %}
{% if not requested_platforms %}{% set chosen.platforms = allowed_platforms %}{% endif %}
{% set group_name = requested_groups[0] if requested_groups|length == 1 and requested_groups[0] in ['高中','大学','留学预备'] else '语培整体' %}
WITH periods AS (
 SELECT p.period_id, p.start_date, p.through_date
 FROM business.periods p WHERE p.status <> 'future' AND p.kind IN ('month','quarter','year')
 """ + period_filter + r"""
), dimensions AS (
 SELECT p.*,l.business_line,platform.platform,
 CASE WHEN l.business_line='training' THEN '{{ group_name }}' ELSE '留学整体' END AS group_name
 FROM periods p CROSS JOIN (VALUES ('training'),('abroad')) l(business_line)
 CROSS JOIN (VALUES ('抖音'),('小红书'),('腾讯广告')) platform(platform)
 WHERE {% if chosen.platforms %}platform.platform IN {{ chosen.platforms|where_in }}{% else %}FALSE{% endif %}
 """ + line_filter + r"""
), business_values AS (
 SELECT d.period_id,d.business_line,d.platform,
 sum(o.orders) FILTER (WHERE o.event_date BETWEEN d.start_date AND d.through_date) AS orders,
 sum(o.cash) FILTER (WHERE o.event_date BETWEEN d.start_date AND d.through_date) AS cash,
 sum(o.orders) FILTER (WHERE o.event_date BETWEEN (d.start_date-INTERVAL '1 year')::DATE AND (d.through_date-INTERVAL '1 year')::DATE) AS prior_orders,
 sum(o.cash) FILTER (WHERE o.event_date BETWEEN (d.start_date-INTERVAL '1 year')::DATE AND (d.through_date-INTERVAL '1 year')::DATE) AS prior_cash
 FROM dimensions d LEFT JOIN business.online_daily o ON o.business_line=d.business_line AND o.platform=d.platform
 AND (d.business_line='abroad' OR d.group_name='语培整体' OR o.expense_group=d.group_name)
 AND (o.event_date BETWEEN d.start_date AND d.through_date OR o.event_date BETWEEN (d.start_date-INTERVAL '1 year')::DATE AND (d.through_date-INTERVAL '1 year')::DATE)
 GROUP BY d.period_id,d.business_line,d.platform
), spend_values AS (
 SELECT d.period_id,d.business_line,d.platform,
 CASE WHEN d.platform='腾讯广告' AND d.group_name <> '留学预备'
      THEN coalesce(sum(e.amount),0) ELSE sum(e.amount) END AS spend
 FROM dimensions d LEFT JOIN business.expense_rows e ON e.business_line=d.business_line AND e.platform=d.platform
 AND (d.business_line='abroad' OR d.group_name='语培整体' OR e.business_group=d.group_name)
 AND e.start_date >= d.start_date AND e.end_date <= d.through_date
 GROUP BY d.period_id,d.business_line,d.platform,d.group_name
), components AS (
 SELECT d.period_id,d.start_date,d.business_line,d.platform,d.group_name,s.spend,
 coalesce(b.orders,0) AS orders,coalesce(b.cash,0) AS cash,
 coalesce(b.prior_orders,0) AS prior_orders,coalesce(b.prior_cash,0) AS prior_cash
 FROM dimensions d JOIN business_values b USING(period_id,business_line,platform)
 JOIN spend_values s USING(period_id,business_line,platform)
), totals AS (
 SELECT period_id,start_date,business_line,'合计' AS platform,group_name,
 sum(spend) AS spend,sum(orders) AS orders,sum(cash) AS cash,
 sum(prior_orders) AS prior_orders,sum(prior_cash) AS prior_cash
 FROM components GROUP BY period_id,start_date,business_line,group_name
), output AS (SELECT * FROM totals
 """ + component_rows + r"""
)
SELECT period_id AS "线上期间",start_date AS "月份",
 CASE business_line WHEN 'training' THEN '语培' ELSE '留学及小语种' END AS "业务线",
 platform AS "平台",group_name AS "平台业务组",spend AS "本期花费",orders AS "本期工单",
 cash AS "本期产出",cash/nullif(spend,0) AS "ROI",spend/nullif(orders,0) AS "单条成本",
 CASE WHEN business_line='training' THEN prior_orders END AS "上年同期工单",
 CASE WHEN business_line='training' THEN prior_cash END AS "上年同期产出"
FROM output
"""
