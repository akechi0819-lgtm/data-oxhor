-- 同一线上团队已核验的业务事实与只读费用输入。
-- 输入由宿主生成 VALUES；不读取外部文件、不重新判断工单资格。
-- 一次费用只占一个 业务线×业务组×平台×日期/周期 单元，先聚合再关联。
WITH
periods(period_id,start_date,through_date,prior_start_date,prior_through_date) AS (
  VALUES /* PERIODS */
),
business_daily(event_date,business_line,business_group,platform,orders,cash) AS (
  VALUES /* BUSINESS_DAILY */
),
expense_rows(source_id,business_line,business_group,platform,start_date,end_date,amount) AS (
  VALUES /* EXPENSE_ROWS */
),
expense_sources(source_id,business_line,business_group,platform,grain,start_date,end_date) AS (
  VALUES /* EXPENSE_SOURCES */
),
business_leaf AS (
  SELECT p.period_id,b.business_line,b.business_group,b.platform,
    SUM(CASE WHEN b.event_date BETWEEN p.start_date AND p.through_date THEN b.orders ELSE 0 END) AS orders,
    SUM(CASE WHEN b.event_date BETWEEN p.start_date AND p.through_date THEN b.cash ELSE 0 END) AS cash,
    SUM(CASE WHEN b.event_date BETWEEN p.prior_start_date AND p.prior_through_date THEN b.orders ELSE 0 END) AS prior_orders,
    SUM(CASE WHEN b.event_date BETWEEN p.prior_start_date AND p.prior_through_date THEN b.cash ELSE 0 END) AS prior_cash,
    SUM(CASE WHEN b.event_date=p.through_date THEN b.orders ELSE 0 END) AS today_orders
  FROM periods p JOIN business_daily b
    ON b.event_date BETWEEN p.start_date AND p.through_date
    OR b.event_date BETWEEN p.prior_start_date AND p.prior_through_date
  GROUP BY p.period_id,b.business_line,b.business_group,b.platform
),
expense_leaf AS (
  SELECT p.period_id,e.business_line,e.business_group,e.platform,SUM(e.amount) AS spend
  FROM periods p JOIN expense_rows e
    ON e.start_date>=p.start_date AND e.end_date<=p.through_date
  -- 周总表只有整个周期落在所选期间时才计入，不按天分摊、不外推月份。
  GROUP BY p.period_id,e.business_line,e.business_group,e.platform
),
source_coverage AS (
  SELECT p.period_id,s.source_id,s.business_line,s.business_group,s.platform,
    CASE WHEN s.grain='daily' THEN
      COUNT(DISTINCT CASE WHEN e.amount IS NOT NULL THEN e.start_date END)=date_diff('day',p.start_date,p.through_date)+1
      AND COUNT(*) FILTER (WHERE e.start_date IS NOT NULL AND e.amount IS NULL)=0
    ELSE s.start_date=p.start_date AND s.end_date=p.through_date
      AND COUNT(e.amount)=COUNT(e.start_date) AND COUNT(e.amount)>0 END AS complete
  FROM periods p CROSS JOIN expense_sources s
  LEFT JOIN expense_rows e ON e.source_id=s.source_id
    AND e.business_line=s.business_line AND e.business_group=s.business_group AND e.platform=s.platform
    AND e.start_date>=p.start_date AND e.end_date<=p.through_date
  GROUP BY p.period_id,p.start_date,p.through_date,s.source_id,s.business_line,s.business_group,s.platform,s.grain,s.start_date,s.end_date
),
coverage_leaf AS (
  SELECT period_id,business_line,business_group,platform,BOOL_AND(complete) AS complete
  FROM source_coverage GROUP BY period_id,business_line,business_group,platform
),
leaf_keys AS (
  SELECT period_id,business_line,business_group,platform FROM business_leaf
  UNION SELECT period_id,business_line,business_group,platform FROM expense_leaf
),
joined_leaf AS (
  SELECT k.*,COALESCE(b.orders,0) AS orders,COALESCE(b.cash,0) AS cash,
    COALESCE(b.prior_orders,0) AS prior_orders,COALESCE(b.prior_cash,0) AS prior_cash,
    COALESCE(b.today_orders,0) AS today_orders,e.spend,
    CASE WHEN e.spend IS NULL THEN 'missing' WHEN c.complete THEN 'complete' ELSE 'partial' END AS spend_status
  FROM leaf_keys k
  LEFT JOIN business_leaf b USING(period_id,business_line,business_group,platform)
  LEFT JOIN expense_leaf e USING(period_id,business_line,business_group,platform)
  LEFT JOIN coverage_leaf c USING(period_id,business_line,business_group,platform)
),
rollups AS (
  SELECT period_id,business_line,
    CASE WHEN GROUPING(business_group)=1 AND GROUPING(platform)=1 THEN 'line'
         WHEN GROUPING(platform)=1 THEN 'group'
         WHEN GROUPING(business_group)=1 THEN 'platform' ELSE 'leaf' END AS record_type,
    business_group,platform,SUM(orders) AS orders,SUM(cash) AS cash,
    SUM(prior_orders) AS prior_orders,SUM(prior_cash) AS prior_cash,SUM(today_orders) AS today_orders,
    SUM(spend) AS spend,
    CASE WHEN COUNT(spend)=0 THEN 'missing'
         WHEN COUNT(*) FILTER(WHERE spend_status='complete')=COUNT(*) THEN 'complete'
         ELSE 'partial' END AS spend_status
  FROM joined_leaf
  GROUP BY GROUPING SETS (
    (period_id,business_line,business_group,platform),
    (period_id,business_line,platform),
    (period_id,business_line,business_group),
    (period_id,business_line)
  )
),
days AS (
  SELECT p.period_id,CAST(d AS DATE) AS event_date
  FROM periods p CROSS JOIN LATERAL generate_series(p.start_date,p.through_date,INTERVAL '1 day') AS day_series(d)
),
daily_business AS (
  SELECT d.period_id,d.event_date,b.business_line,SUM(b.orders) AS orders,SUM(b.cash) AS cash
  FROM days d JOIN business_daily b ON b.event_date=d.event_date
  GROUP BY d.period_id,d.event_date,b.business_line
),
daily_expense AS (
  SELECT d.period_id,d.event_date,e.business_line,SUM(e.amount) AS spend
  FROM days d JOIN expense_rows e ON e.start_date=d.event_date AND e.end_date=d.event_date
  JOIN expense_sources s ON s.source_id=e.source_id AND s.business_line=e.business_line
    AND s.business_group=e.business_group AND s.platform=e.platform AND s.grain='daily'
  GROUP BY d.period_id,d.event_date,e.business_line
),
daily_scope_keys AS (
  SELECT period_id,business_line,business_group,platform FROM business_leaf WHERE orders<>0 OR cash<>0
  UNION SELECT period_id,business_line,business_group,platform FROM expense_leaf
),
daily_key_coverage AS (
  SELECT d.period_id,d.event_date,k.business_line,k.business_group,k.platform,
    COUNT(DISTINCT s.source_id)>0
      AND BOOL_AND(COALESCE(s.grain='daily' AND e.amount IS NOT NULL,FALSE)) AS complete
  FROM days d JOIN daily_scope_keys k USING(period_id)
  LEFT JOIN expense_sources s USING(business_line,business_group,platform)
  LEFT JOIN expense_rows e ON e.source_id=s.source_id AND e.business_line=s.business_line
    AND e.business_group=s.business_group AND e.platform=s.platform
    AND e.start_date=d.event_date AND e.end_date=d.event_date
  GROUP BY d.period_id,d.event_date,k.business_line,k.business_group,k.platform
),
daily_line_coverage AS (
  SELECT period_id,event_date,business_line,BOOL_AND(complete) AS complete
  FROM daily_key_coverage GROUP BY period_id,event_date,business_line
),
-- ROI只在费用流共同连续覆盖的日期计算。日报账户各自独立；期间来源按业务线/组/平台合并，
-- 使9月差额与10月当月来源可以首尾衔接。费用总量仍由上面的expense_leaf完整保留。
active_streams AS (
  SELECT DISTINCT p.period_id,r.record_type,r.business_line,r.business_group,r.platform,
    s.business_group AS stream_group,s.platform AS stream_platform,
    s.grain,CASE WHEN s.grain='daily' THEN s.source_id ELSE 'period' END AS stream_id
  FROM periods p JOIN rollups r ON r.period_id=p.period_id
  JOIN expense_sources s ON s.business_line=r.business_line
    AND (r.business_group IS NULL OR s.business_group=r.business_group)
    AND (r.platform IS NULL OR s.platform=r.platform)
  WHERE EXISTS (
    SELECT 1 FROM expense_rows e WHERE e.source_id=s.source_id
      AND e.business_line=s.business_line AND e.business_group=s.business_group AND e.platform=s.platform
      AND e.start_date<=p.through_date AND e.end_date>=p.start_date
  )
),
active_period_streams AS (
  SELECT DISTINCT period_id,record_type,business_line,business_group,platform,
    stream_group,stream_platform,grain,stream_id
  FROM active_streams
),
stream_days AS (
  SELECT st.period_id,st.record_type,st.business_line,st.business_group,st.platform,
    st.stream_group,st.stream_platform,st.grain,st.stream_id,d.event_date,
    COUNT(e.source_id)>0 AND COUNT(e.amount)=COUNT(e.source_id) AS complete
  FROM active_period_streams st
  JOIN days d USING(period_id)
  LEFT JOIN expense_sources s ON s.business_line=st.business_line
    AND s.business_group=st.stream_group AND s.platform=st.stream_platform AND s.grain=st.grain
    AND (st.grain='period' OR s.source_id=st.stream_id)
  LEFT JOIN expense_rows e ON e.source_id=s.source_id
    AND e.business_line=s.business_line AND e.business_group=s.business_group AND e.platform=s.platform
    AND ((st.grain='daily' AND e.start_date=d.event_date AND e.end_date=d.event_date)
      OR (st.grain='period' AND e.start_date<=d.event_date AND e.end_date>=d.event_date))
  GROUP BY st.period_id,st.record_type,st.business_line,st.business_group,st.platform,
    st.stream_group,st.stream_platform,st.grain,st.stream_id,d.event_date
),
scope_days AS (
  SELECT period_id,record_type,business_line,business_group,platform,event_date,
    COUNT(*)>0 AND BOOL_AND(complete) AS complete
  FROM stream_days
  GROUP BY period_id,record_type,business_line,business_group,platform,event_date
),
coverage_start AS (
  SELECT period_id,record_type,business_line,business_group,platform,
    MIN(event_date) FILTER(WHERE complete) AS roi_start_date
  FROM scope_days
  GROUP BY period_id,record_type,business_line,business_group,platform
),
coverage_bounds AS (
  SELECT c.period_id,c.record_type,c.business_line,c.business_group,c.platform,c.roi_start_date,
    CASE WHEN c.roi_start_date IS NULL THEN NULL
      ELSE COALESCE(MIN(d.event_date) FILTER(WHERE d.event_date>c.roi_start_date AND NOT d.complete)-INTERVAL '1 day',p.through_date)
    END AS roi_through_date
  FROM coverage_start c JOIN periods p USING(period_id)
  JOIN scope_days d ON d.period_id=c.period_id AND d.record_type=c.record_type
    AND d.business_line=c.business_line AND d.business_group IS NOT DISTINCT FROM c.business_group
    AND d.platform IS NOT DISTINCT FROM c.platform
  GROUP BY c.period_id,c.record_type,c.business_line,c.business_group,c.platform,c.roi_start_date,p.through_date
),
roi_windows AS (
  SELECT r.period_id,r.record_type,r.business_line,r.business_group,r.platform,
    CASE WHEN b.roi_start_date IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM expense_sources s JOIN expense_rows e ON e.source_id=s.source_id
        AND e.business_line=s.business_line AND e.business_group=s.business_group AND e.platform=s.platform
      WHERE s.business_line=r.business_line AND s.grain='period'
        AND (r.business_group IS NULL OR s.business_group=r.business_group)
        AND (r.platform IS NULL OR s.platform=r.platform)
        AND e.start_date<=CAST(b.roi_through_date AS DATE) AND e.end_date>=b.roi_start_date
        AND (e.start_date<b.roi_start_date OR e.end_date>CAST(b.roi_through_date AS DATE) OR e.amount IS NULL)
    ) THEN b.roi_start_date END AS roi_start_date,
    CASE WHEN b.roi_start_date IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM expense_sources s JOIN expense_rows e ON e.source_id=s.source_id
        AND e.business_line=s.business_line AND e.business_group=s.business_group AND e.platform=s.platform
      WHERE s.business_line=r.business_line AND s.grain='period'
        AND (r.business_group IS NULL OR s.business_group=r.business_group)
        AND (r.platform IS NULL OR s.platform=r.platform)
        AND e.start_date<=CAST(b.roi_through_date AS DATE) AND e.end_date>=b.roi_start_date
        AND (e.start_date<b.roi_start_date OR e.end_date>CAST(b.roi_through_date AS DATE) OR e.amount IS NULL)
    ) THEN CAST(b.roi_through_date AS DATE) END AS roi_through_date
  FROM rollups r LEFT JOIN coverage_bounds b ON b.period_id=r.period_id
    AND b.record_type=r.record_type AND b.business_line=r.business_line
    AND b.business_group IS NOT DISTINCT FROM r.business_group
    AND b.platform IS NOT DISTINCT FROM r.platform
),
roi_expense AS (
  SELECT w.period_id,w.record_type,w.business_line,w.business_group,w.platform,SUM(e.amount) AS roi_spend
  FROM roi_windows w JOIN expense_rows e ON e.business_line=w.business_line
    AND (w.business_group IS NULL OR e.business_group=w.business_group)
    AND (w.platform IS NULL OR e.platform=w.platform)
  JOIN expense_sources s ON s.source_id=e.source_id AND s.business_line=e.business_line
    AND s.business_group=e.business_group AND s.platform=e.platform
  WHERE w.roi_start_date IS NOT NULL AND (
    (s.grain='daily' AND e.start_date=e.end_date AND e.start_date BETWEEN w.roi_start_date AND w.roi_through_date)
    OR (s.grain='period' AND e.start_date>=w.roi_start_date AND e.end_date<=w.roi_through_date)
  )
  GROUP BY w.period_id,w.record_type,w.business_line,w.business_group,w.platform
),
roi_business AS (
  SELECT w.period_id,w.record_type,w.business_line,w.business_group,w.platform,
    SUM(b.cash) AS roi_cash,SUM(b.orders) AS roi_orders
  FROM roi_windows w JOIN business_daily b ON b.business_line=w.business_line
    AND (w.business_group IS NULL OR b.business_group=w.business_group)
    AND (w.platform IS NULL OR b.platform=w.platform)
    AND b.event_date BETWEEN w.roi_start_date AND w.roi_through_date
  WHERE w.roi_start_date IS NOT NULL
  GROUP BY w.period_id,w.record_type,w.business_line,w.business_group,w.platform
),
roi_rollups AS (
  SELECT w.period_id,w.record_type,w.business_line,w.business_group,w.platform,
    w.roi_start_date,w.roi_through_date,e.roi_spend,COALESCE(b.roi_cash,0) AS roi_cash,
    COALESCE(b.roi_orders,0) AS roi_orders
  FROM roi_windows w
  LEFT JOIN roi_expense e ON e.period_id=w.period_id AND e.record_type=w.record_type
    AND e.business_line=w.business_line AND e.business_group IS NOT DISTINCT FROM w.business_group
    AND e.platform IS NOT DISTINCT FROM w.platform
  LEFT JOIN roi_business b ON b.period_id=w.period_id AND b.record_type=w.record_type
    AND b.business_line=w.business_line AND b.business_group IS NOT DISTINCT FROM w.business_group
    AND b.platform IS NOT DISTINCT FROM w.platform
),
daily_roi_coverage AS (
  SELECT period_id,event_date,business_line,COUNT(*)>0
    AND BOOL_AND(grain='daily' AND complete) AS complete
  FROM stream_days
  WHERE record_type='line'
  GROUP BY period_id,event_date,business_line
),
result AS (
  SELECT r.record_type,r.period_id,r.business_line,r.business_group,r.platform,CAST(NULL AS DATE) AS event_date,
    r.orders,r.cash,r.prior_orders,r.prior_cash,r.today_orders,r.spend,r.spend_status,
    CASE WHEN rr.roi_spend>0 THEN rr.roi_cash/rr.roi_spend END AS roi,
    CASE WHEN rr.roi_spend IS NOT NULL AND rr.roi_orders>0 THEN rr.roi_spend/rr.roi_orders END AS cost_per_order,
    rr.roi_start_date,rr.roi_through_date,rr.roi_spend,rr.roi_cash,rr.roi_orders
  FROM rollups r LEFT JOIN roi_rollups rr ON rr.period_id=r.period_id AND rr.record_type=r.record_type
    AND rr.business_line=r.business_line AND rr.business_group IS NOT DISTINCT FROM r.business_group
    AND rr.platform IS NOT DISTINCT FROM r.platform
  UNION ALL
  SELECT 'daily',d.period_id,l.business_line,NULL,NULL,d.event_date,
    COALESCE(b.orders,0),COALESCE(b.cash,0),NULL,NULL,NULL,e.spend,
    CASE WHEN e.spend IS NULL THEN 'missing' WHEN c.complete THEN 'complete' ELSE 'partial' END,
    CASE WHEN rc.complete AND e.spend>0 THEN COALESCE(b.cash,0)/e.spend END,
    CASE WHEN rc.complete AND e.spend IS NOT NULL AND b.orders>0 THEN e.spend/b.orders END,
    CASE WHEN rc.complete THEN d.event_date END,CASE WHEN rc.complete THEN d.event_date END,
    CASE WHEN rc.complete THEN e.spend END,CASE WHEN rc.complete THEN COALESCE(b.cash,0) END,
    CASE WHEN rc.complete THEN COALESCE(b.orders,0) END
  FROM days d CROSS JOIN (VALUES ('training'),('abroad')) AS l(business_line)
  LEFT JOIN daily_business b USING(period_id,event_date,business_line)
  LEFT JOIN daily_expense e USING(period_id,event_date,business_line)
  LEFT JOIN daily_line_coverage c USING(period_id,event_date,business_line)
  LEFT JOIN daily_roi_coverage rc USING(period_id,event_date,business_line)
)
SELECT * FROM result ORDER BY period_id,business_line,record_type,business_group,platform,event_date;
