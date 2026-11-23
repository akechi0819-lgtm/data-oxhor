-- SQL-native replacement for management.breakdowns. Facts stay in the
-- period_events relation; this file only creates result views.
-- Preserve the existing source traversal when reproducing Python sum's
-- mixed int/float accumulation; this view stores no additional source rows.
CREATE OR REPLACE VIEW business.training_fact_order AS
SELECT CASE WHEN metric = 'work_orders' THEN 'training:order:' || TRIM(work_order_id)
            ELSE 'training:cash:' || TRIM(source_row_number) END AS fact_id,
       MIN(_input_order) AS source_order
FROM source.training_rows
WHERE metric IN ('work_orders', 'passive_reported_cash')
GROUP BY 1;

CREATE OR REPLACE MACRO business.dimension_query(periods, units, acquisitions, dimensions) AS TABLE (
WITH RECURSIVE
query_filters AS (
    SELECT COALESCE(periods, []::VARCHAR[]) AS period_ids,
        COALESCE(units, []::VARCHAR[]) AS unit_ids,
        COALESCE(acquisitions, []::VARCHAR[]) AS acquisition_ids,
        COALESCE(dimensions, []::VARCHAR[]) AS dimension_ids
),
training_scopes AS (
    SELECT p.period_id, s.unit_id, a.acquisition_scope
    FROM business.periods p
    JOIN business.scopes s ON s.unit_id IN (
        'total', 'prep', 'high', 'university', 'virtual', 'online',
        'overview_prep', 'overview_high', 'overview_university',
        'selection_1', 'selection_2', 'selection_3', 'selection_4',
        'selection_5', 'selection_6', 'selection_7', 'offline_scope', 'online_scope'
    )
    CROSS JOIN business.acquisition_scopes a
    CROSS JOIN query_filters q
    WHERE (len(q.period_ids) = 0 OR list_contains(q.period_ids, p.period_id))
      AND (len(q.unit_ids) = 0 OR list_contains(q.unit_ids, s.unit_id))
      AND (len(q.acquisition_ids) = 0 OR list_contains(q.acquisition_ids, a.acquisition_scope))
),
scope_definitions AS (
    SELECT s.unit_id, s.source_team, s.business_group, s.selection_mask
    FROM business.scopes s
),
canonical_business_groups AS (
    SELECT * FROM (VALUES ('留学预备'), ('高中'), ('大学')) t(name)
),
canonical_comparison_groups AS (
    SELECT * FROM (VALUES ('青少'), ('初中'), ('高中'), ('大学')) t(name)
),
base_events AS (
    SELECT
        e.fact_id,
        e.period_id,
        e.unit_id,
        sd.selection_mask,
        e.acquisition_scope,
        e.business_line,
        e.comparison,
        CAST(e.event_date AS DATE) AS event_date,
        e.metric,
        TRY_CAST(e.value AS DOUBLE) AS value,
        NULLIF(TRIM(CAST(e.student_id AS VARCHAR)), '') AS student_id,
        NULLIF(TRIM(CAST(e.class_code AS VARCHAR)), '') AS class_code,
        TRY_CAST(e.registration_count AS DOUBLE) AS registration_count,
        NULLIF(TRIM(CAST(e.business_group AS VARCHAR)), '') AS business_group,
        NULLIF(TRIM(CAST(e.comparison_group AS VARCHAR)), '') AS comparison_group,
        NULLIF(TRIM(CAST(e.first_channel AS VARCHAR)), '') AS first_channel,
        NULLIF(TRIM(CAST(e.second_channel AS VARCHAR)), '') AS second_channel,
        NULLIF(TRIM(CAST(e.school_name AS VARCHAR)), '') AS school_name,
        NULLIF(TRIM(CAST(e.school_attribute AS VARCHAR)), '') AS school_attribute,
        NULLIF(TRIM(CAST(e.channel_school_name AS VARCHAR)), '') AS channel_school_name,
        NULLIF(TRIM(CAST(e.grade_name AS VARCHAR)), '') AS grade_name,
        NULLIF(TRIM(CAST(e.customer_domain AS VARCHAR)), '') AS customer_domain,
        NULLIF(TRIM(CAST(e.segment_id AS VARCHAR)), '') AS segment_id,
        NULLIF(TRIM(CAST(e.country AS VARCHAR)), '') AS country,
        NULLIF(TRIM(CAST(e.line AS VARCHAR)), '') AS abroad_line
    FROM business.period_events e
    LEFT JOIN business.scopes sd USING (unit_id)
    CROSS JOIN query_filters q
    WHERE (len(q.period_ids) = 0 OR list_contains(q.period_ids, e.period_id))
      AND (len(q.unit_ids) = 0 OR list_contains(q.unit_ids, e.unit_id))
      AND (len(q.acquisition_ids) = 0 OR list_contains(q.acquisition_ids, e.acquisition_scope))
),
dimension_events AS (
    SELECT period_id, unit_id, acquisition_scope, business_line, comparison,
        'business_group' AS dimension_type,
        CASE
            WHEN unit_id LIKE 'selection_%' AND business_group = '留学预备'
                 AND COALESCE((selection_mask & 3), 0) = 1 THEN '青少'
            WHEN unit_id LIKE 'selection_%' AND business_group = '留学预备'
                 AND COALESCE((selection_mask & 3), 0) = 2 THEN '初中'
            WHEN business_group IN ('留学预备', '高中', '大学') THEN business_group
            ELSE '业务组暂无法拆分'
        END AS dim1,
        '∅' AS dim2, '∅' AS dim3, '∅' AS first_channel,
        metric, value, student_id, class_code, registration_count, customer_domain
    FROM base_events
    CROSS JOIN query_filters q
    WHERE business_line = 'training'
      AND (len(q.dimension_ids) = 0 OR list_contains(q.dimension_ids, 'business_group'))
    UNION ALL
    SELECT period_id, unit_id, acquisition_scope, business_line, comparison,
        'comparison_group',
        CASE WHEN comparison_group IN ('青少', '初中', '高中', '大学') THEN comparison_group ELSE '业务组暂无法拆分' END,
        '∅', '∅', '∅', metric, value, student_id, class_code, registration_count, customer_domain
    FROM base_events
    CROSS JOIN query_filters q
    WHERE business_line = 'training'
      AND (len(q.dimension_ids) = 0 OR list_contains(q.dimension_ids, 'comparison_group'))
    UNION ALL
    SELECT period_id, unit_id, acquisition_scope, business_line, comparison,
        'channel',
        COALESCE(second_channel, '二级渠道待确认'), '∅', '∅',
        COALESCE(first_channel, '一级渠道待确认'),
        metric, value, student_id, class_code, registration_count, customer_domain
    FROM base_events
    CROSS JOIN query_filters q
    WHERE len(q.dimension_ids) = 0 OR list_contains(q.dimension_ids, 'channel')
       OR list_contains(q.dimension_ids, 'channel_group') OR list_contains(q.dimension_ids, 'channel_school')
    UNION ALL
    SELECT period_id, unit_id, acquisition_scope, business_line, comparison,
        'channel_group',
        COALESCE(second_channel, '二级渠道待确认'),
        CASE
            WHEN unit_id = 'university' AND business_line = 'abroad' THEN '毕业及其他'
            WHEN unit_id = 'university' AND business_line = 'training' THEN
                CASE WHEN school_attribute IN ('大学*', '本地大学', '归巢大学', '国外大学', '毕业及其他')
                    THEN school_attribute ELSE '毕业及其他' END
            WHEN business_line = 'training' AND comparison_group IN ('青少', '初中', '高中', '大学') THEN comparison_group
            WHEN business_line = 'training' THEN '业务组暂无法拆分'
            WHEN business_group IN ('留学预备', '高中', '大学') THEN business_group
            ELSE '业务组暂无法拆分'
        END,
        '∅', COALESCE(first_channel, '一级渠道待确认'),
        metric, value, student_id, class_code, registration_count, customer_domain
    FROM base_events
    CROSS JOIN query_filters q
    WHERE len(q.dimension_ids) = 0 OR list_contains(q.dimension_ids, 'channel_group')
    UNION ALL
    SELECT period_id, unit_id, acquisition_scope, business_line, comparison,
        'channel_school',
        COALESCE(second_channel, '二级渠道待确认'),
        CASE
            WHEN business_line = 'abroad' THEN '毕业及其他'
            WHEN school_attribute IN ('大学*', '本地大学', '归巢大学', '国外大学', '毕业及其他')
                THEN school_attribute ELSE '毕业及其他'
        END,
        CASE WHEN business_line = 'abroad' THEN '暂无归属'
             ELSE COALESCE(channel_school_name, school_name, '暂无归属') END,
        COALESCE(first_channel, '一级渠道待确认'),
        metric, value, student_id, class_code, registration_count, customer_domain
    FROM base_events
    CROSS JOIN query_filters q
    WHERE unit_id = 'university'
      AND (len(q.dimension_ids) = 0 OR list_contains(q.dimension_ids, 'channel_school'))
    UNION ALL
    SELECT period_id, unit_id, acquisition_scope, business_line, comparison,
        'school', COALESCE(school_name, '暂无归属'), '∅', '∅', '∅',
        metric, value, student_id, class_code, registration_count, customer_domain
    FROM base_events
    CROSS JOIN query_filters q
    WHERE len(q.dimension_ids) = 0 OR list_contains(q.dimension_ids, 'school')
       OR list_contains(q.dimension_ids, 'school_grade')
    UNION ALL
    SELECT period_id, unit_id, acquisition_scope, business_line, comparison,
        'school_grade', COALESCE(school_name, '暂无归属'),
        CASE
            WHEN grade_name IS NULL OR grade_name IN ('未知', '暂无归属') THEN '年级待确认'
            WHEN grade_name = '七年级' THEN '初一'
            WHEN grade_name = '八年级' THEN '初二'
            WHEN grade_name = '九年级' THEN '初三'
            WHEN grade_name = '小班' THEN '幼儿园小班'
            WHEN grade_name = '中班' THEN '幼儿园中班'
            WHEN grade_name = '大班' THEN '幼儿园大班'
            ELSE grade_name
        END,
        '∅', '∅', metric, value, student_id, class_code, registration_count, customer_domain
    FROM base_events
    CROSS JOIN query_filters q
    WHERE len(q.dimension_ids) = 0 OR list_contains(q.dimension_ids, 'school_grade')
    UNION ALL
    SELECT period_id, unit_id, acquisition_scope, business_line, comparison,
        'grade',
        CASE
            WHEN grade_name IS NULL OR grade_name IN ('未知', '暂无归属') THEN '年级待确认'
            WHEN grade_name = '七年级' THEN '初一'
            WHEN grade_name = '八年级' THEN '初二'
            WHEN grade_name = '九年级' THEN '初三'
            WHEN grade_name = '小班' THEN '幼儿园小班'
            WHEN grade_name = '中班' THEN '幼儿园中班'
            WHEN grade_name = '大班' THEN '幼儿园大班'
            ELSE grade_name
        END,
        '∅', '∅', '∅', metric, value, student_id, class_code, registration_count, customer_domain
    FROM base_events
    CROSS JOIN query_filters q
    WHERE len(q.dimension_ids) = 0 OR list_contains(q.dimension_ids, 'grade')
),
all_dimension_keys AS (
    SELECT DISTINCT period_id, unit_id, acquisition_scope, business_line,
        dimension_type, dim1, dim2, dim3, first_channel
    FROM dimension_events
    UNION
    SELECT ts.period_id, ts.unit_id, ts.acquisition_scope, 'training', 'business_group',
        cbg.name, '∅', '∅', '∅'
    FROM training_scopes ts
    JOIN scope_definitions sd USING (unit_id)
    CROSS JOIN canonical_business_groups cbg
    WHERE (sd.unit_id NOT LIKE 'selection_%' AND
        (sd.business_group IS NULL OR sd.business_group = cbg.name))
       OR (sd.unit_id LIKE 'selection_%' AND
        (cbg.name = '留学预备' AND COALESCE((sd.selection_mask & 3), 0) = 3
         OR cbg.name = '高中' AND COALESCE((sd.selection_mask & 4), 0) > 0))
    UNION
    SELECT ts.period_id, ts.unit_id, ts.acquisition_scope, 'training', 'business_group',
        CASE WHEN (sd.selection_mask & 1) > 0 THEN '青少' ELSE '初中' END,
        '∅', '∅', '∅'
    FROM training_scopes ts
    JOIN scope_definitions sd USING (unit_id)
    WHERE sd.unit_id LIKE 'selection_%' AND COALESCE((sd.selection_mask & 3), 0) IN (1, 2)
    UNION
    SELECT ts.period_id, ts.unit_id, ts.acquisition_scope, 'training', 'business_group',
        '业务组暂无法拆分', '∅', '∅', '∅'
    FROM training_scopes ts
    WHERE ts.unit_id IN ('total', 'online_scope', 'offline_scope')
       OR EXISTS (
          SELECT 1 FROM dimension_events de
          WHERE de.period_id = ts.period_id AND de.unit_id = ts.unit_id
            AND de.acquisition_scope = ts.acquisition_scope AND de.business_line = 'training'
            AND de.dimension_type = 'business_group' AND de.dim1 = '业务组暂无法拆分'
       )
    UNION
    SELECT ts.period_id, ts.unit_id, ts.acquisition_scope, 'training', 'comparison_group',
        ccg.name, '∅', '∅', '∅'
    FROM training_scopes ts
    JOIN scope_definitions sd USING (unit_id)
    CROSS JOIN canonical_comparison_groups ccg
    WHERE sd.unit_id = 'total'
       OR sd.unit_id = 'prep' AND ccg.name IN ('青少', '初中')
       OR sd.unit_id = 'high' AND ccg.name = '高中'
       OR sd.unit_id = 'university' AND ccg.name = '大学'
       OR sd.unit_id = 'overview_prep' AND ccg.name IN ('青少', '初中')
       OR sd.unit_id = 'overview_high' AND ccg.name = '高中'
       OR sd.unit_id = 'overview_university' AND ccg.name = '大学'
       OR sd.unit_id LIKE 'selection_%' AND
          (ccg.name = '青少' AND COALESCE((sd.selection_mask & 1), 0) > 0
           OR ccg.name = '初中' AND COALESCE((sd.selection_mask & 2), 0) > 0
           OR ccg.name = '高中' AND COALESCE((sd.selection_mask & 4), 0) > 0)
       OR sd.unit_id NOT IN ('total', 'prep', 'high', 'university',
                             'overview_prep', 'overview_high', 'overview_university')
          AND sd.unit_id NOT LIKE 'selection_%'
    UNION
    SELECT ts.period_id, ts.unit_id, ts.acquisition_scope, 'training', 'comparison_group',
        '业务组暂无法拆分', '∅', '∅', '∅'
    FROM training_scopes ts
    WHERE ts.unit_id = 'total'
       OR EXISTS (
          SELECT 1 FROM dimension_events de
          WHERE de.period_id = ts.period_id AND de.unit_id = ts.unit_id
            AND de.acquisition_scope = ts.acquisition_scope AND de.business_line = 'training'
            AND de.dimension_type = 'comparison_group' AND de.dim1 = '业务组暂无法拆分'
       )
),
dimension_keys AS (
    SELECT k.*
    FROM all_dimension_keys k
    CROSS JOIN query_filters q
    WHERE len(q.dimension_ids) = 0 OR list_contains(q.dimension_ids, k.dimension_type)
       OR (k.dimension_type = 'school' AND list_contains(q.dimension_ids, 'school_grade'))
),
dimension_sums AS (
    SELECT period_id, unit_id, acquisition_scope, business_line,
        dimension_type, dim1, dim2, dim3, first_channel, metric,
        ROUND(SUM(value) FILTER (WHERE comparison = 'actual'), 2) AS actual,
        ROUND(SUM(value) FILTER (WHERE comparison = 'prior'), 2) AS prior
    FROM dimension_events
    WHERE metric IN ('orders', 'cash')
    GROUP BY ALL
),
training_head_classes AS (
    SELECT period_id, unit_id, acquisition_scope, business_line,
        dimension_type, dim1, dim2, dim3, first_channel, comparison,
        student_id, class_code
    FROM dimension_events
    WHERE business_line = 'training' AND metric = 'cash' AND student_id IS NOT NULL
    GROUP BY period_id, unit_id, acquisition_scope, business_line,
        dimension_type, dim1, dim2, dim3, first_channel, comparison, student_id, class_code
    HAVING ABS(SUM(COALESCE(value, 0))) >= 1500
       AND BOOL_OR(COALESCE(registration_count, 0) > 0)
),
training_head_values AS (
    SELECT period_id, unit_id, acquisition_scope, business_line,
        dimension_type, dim1, dim2, dim3, first_channel, comparison,
        COUNT(DISTINCT student_id)::DOUBLE AS heads,
        0::DOUBLE AS study_heads, 0::DOUBLE AS language_heads
    FROM training_head_classes
    GROUP BY ALL
),
abroad_head_domains AS (
    SELECT period_id, unit_id, acquisition_scope, business_line,
        dimension_type, dim1, dim2, dim3, first_channel, comparison,
        COUNT(DISTINCT student_id)::DOUBLE AS all_heads,
        COUNT(DISTINCT student_id) FILTER (WHERE customer_domain = 'study_abroad')::DOUBLE AS study_heads,
        COUNT(DISTINCT student_id) FILTER (WHERE customer_domain = 'small_language')::DOUBLE AS language_heads
    FROM dimension_events
    WHERE business_line = 'abroad' AND metric = 'cash' AND COALESCE(value, 0) > 0
      AND student_id IS NOT NULL
    GROUP BY ALL
),
abroad_head_values AS (
    SELECT period_id, unit_id, acquisition_scope, business_line,
        dimension_type, dim1, dim2, dim3, first_channel, comparison,
        CASE WHEN study_heads > 0 AND language_heads > 0 THEN NULL ELSE all_heads END AS heads,
        study_heads, language_heads
    FROM abroad_head_domains
),
head_values AS (
    SELECT * FROM training_head_values
    UNION ALL
    SELECT * FROM abroad_head_values
),
head_sums AS (
    SELECT period_id, unit_id, acquisition_scope, business_line,
        dimension_type, dim1, dim2, dim3, first_channel,
        MAX(heads) FILTER (WHERE comparison = 'actual') AS actual,
        MAX(heads) FILTER (WHERE comparison = 'prior') AS prior,
        MAX(study_heads) FILTER (WHERE comparison = 'actual') AS study_heads,
        MAX(language_heads) FILTER (WHERE comparison = 'actual') AS language_heads
    FROM head_values
    GROUP BY ALL
),
training_targets AS (
    SELECT business_line, business_group, team_id, period_id, metric, target
    FROM config.targets
    WHERE NOT (business_line = 'training' AND period_id = 'FY27')
    UNION ALL
    SELECT business_line, business_group, team_id, 'FY27', metric,
        CASE WHEN COUNT(*) = 4 AND COUNT(target) = 4 THEN SUM(target) END AS target
    FROM config.targets
    WHERE business_line = 'training' AND period_id IN ('Q1', 'Q2', 'Q3', 'Q4')
    GROUP BY business_line, business_group, team_id, metric
),
target_dimensions AS (
    SELECT DISTINCT k.period_id, k.unit_id, k.dim1 AS business_group
    FROM dimension_keys k
    JOIN business.scopes sd USING (unit_id)
    WHERE k.dimension_type = 'business_group' AND k.business_line = 'training'
      AND (sd.business_group IS NULL OR sd.business_group = k.dim1)
      AND (k.unit_id NOT LIKE 'selection_%' OR
           (k.dim1 = '留学预备' AND (sd.selection_mask & 3) = 3)
           OR (k.dim1 = '高中' AND (sd.selection_mask & 4) > 0))
),
target_group_keys AS (
    SELECT k.period_id, k.unit_id, k.business_group, m.metric,
        tm.team_id AS target_team, COUNT(*) OVER (
            PARTITION BY k.period_id, k.unit_id, k.business_group, m.metric
        ) AS expected_target_teams
    FROM target_dimensions k
    CROSS JOIN (VALUES ('orders'), ('cash')) m(metric)
    CROSS JOIN LATERAL (
        SELECT 'offline_market' AS team_id
        WHERE k.unit_id IN ('total', 'prep', 'high', 'university',
                            'overview_prep', 'overview_high', 'overview_university', 'offline_scope')
           OR k.unit_id LIKE 'selection_%'
        UNION ALL
        SELECT 'online_private' WHERE k.unit_id IN ('total', 'virtual', 'overview_prep',
                                                    'overview_high', 'overview_university', 'online_scope')
        UNION ALL
        SELECT 'online_platform' WHERE k.unit_id IN ('total', 'online', 'overview_prep',
                                                     'overview_high', 'overview_university', 'online_scope')
    ) tm
),
target_values AS (
    SELECT g.period_id, g.unit_id, g.business_group, g.metric,
        CASE WHEN COUNT(t.target) = MAX(g.expected_target_teams) THEN SUM(t.target) END AS target
    FROM target_group_keys g
    LEFT JOIN training_targets t ON t.business_line = 'training'
      AND t.business_group = g.business_group AND t.team_id = g.target_team
      AND t.period_id = g.period_id AND t.metric = g.metric
    GROUP BY g.period_id, g.unit_id, g.business_group, g.metric
),
market_orders_unique AS (
    SELECT NULLIF(TRIM(CAST(m.work_order_id AS VARCHAR)), '') AS work_order_id,
        TRY_CAST(m.event_date AS DATE) AS event_date,
        CAST(m.team_id AS VARCHAR) AS team_id,
        CASE WHEN TRIM(CAST(m.business_group AS VARCHAR)) IN ('青少', '初中', '高中', '大学')
            THEN TRIM(CAST(m.business_group AS VARCHAR)) ELSE '业务组暂无法拆分' END AS comparison_group,
        CASE
            WHEN TRIM(CAST(m.business_group AS VARCHAR)) IN ('青少', '初中') THEN '留学预备'
            WHEN TRIM(CAST(m.business_group AS VARCHAR)) IN ('高中', '大学') THEN TRIM(CAST(m.business_group AS VARCHAR))
            ELSE '业务组暂无法拆分'
        END AS business_group
    FROM source.market_orders m
    WHERE NULLIF(TRIM(CAST(m.work_order_id AS VARCHAR)), '') IS NOT NULL
      AND TRY_CAST(m.event_date AS DATE) IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY TRIM(CAST(m.work_order_id AS VARCHAR))
        ORDER BY TRY_CAST(m.event_date AS DATE), CAST(m.team_id AS VARCHAR),
                 CAST(m.business_group AS VARCHAR), CAST(m.first_channel AS VARCHAR),
                 CAST(m.second_channel AS VARCHAR)
    ) = 1
),
market_orders_scoped AS (
    SELECT 'total' AS unit_id, m.* FROM market_orders_unique m
    UNION ALL
    SELECT 'online_scope' AS unit_id, m.* FROM market_orders_unique m
    WHERE m.team_id IN ('online_private', 'online_platform')
    UNION ALL
    SELECT 'offline_scope' AS unit_id, m.* FROM market_orders_unique m
    WHERE m.team_id = 'offline_market'
),
market_order_groups AS (
    SELECT p.period_id, m.unit_id, m.business_group,
        COUNT(*) FILTER (WHERE m.event_date BETWEEN p.start_date AND p.through_date)::DOUBLE AS actual,
        COUNT(*) FILTER (WHERE m.event_date BETWEEN CAST(p.start_date - INTERVAL '1 year' AS DATE)
                                               AND CAST(p.through_date - INTERVAL '1 year' AS DATE))::DOUBLE AS prior
    FROM business.periods p
    JOIN market_orders_scoped m ON
        m.event_date BETWEEN p.start_date AND p.through_date
        OR m.event_date BETWEEN CAST(p.start_date - INTERVAL '1 year' AS DATE)
                             AND CAST(p.through_date - INTERVAL '1 year' AS DATE)
    GROUP BY p.period_id, m.unit_id, m.business_group
),
new_student_cash_groups AS (
    SELECT p.period_id, a.acquisition_scope,
        CASE WHEN NULLIF(TRIM(CAST(c.business_group AS VARCHAR)), '') IN ('留学预备', '高中', '大学')
             THEN TRIM(CAST(c.business_group AS VARCHAR)) ELSE '业务组暂无法拆分' END AS business_group,
        ROUND(SUM(TRY_CAST(c.cash_amount AS DECIMAL(38, 2))), 2)::DOUBLE AS denominator
    FROM business.periods p
    CROSS JOIN business.acquisition_scopes a
    JOIN source.new_student_cash c
      ON TRY_CAST(c.cash_date AS DATE) BETWEEN p.start_date AND p.through_date
     AND (a.student_type_scope = '全部' OR c.student_type = a.student_type_scope)
    WHERE TRY_CAST(c.cash_amount AS DECIMAL(38, 2)) > 0
    GROUP BY p.period_id, a.acquisition_scope, 3
),
metric_keys AS (
    SELECT k.*, m.metric
    FROM dimension_keys k
    CROSS JOIN (VALUES ('orders'), ('cash'), ('heads')) m(metric)
    WHERE NOT (k.dimension_type = 'grade' AND m.metric = 'heads')
      AND NOT (k.dimension_type = 'comparison_group'
               AND k.dim1 = '业务组暂无法拆分' AND m.metric IN ('cash', 'heads'))
),
metric_values AS (
    SELECT k.period_id, k.unit_id, k.acquisition_scope, k.business_line,
        k.dimension_type, k.dim1, k.dim2, k.dim3, k.first_channel, k.metric,
        CASE
            WHEN k.metric = 'heads' THEN hs.actual
            WHEN k.dimension_type = 'business_group' AND k.unit_id IN ('total', 'online_scope', 'offline_scope')
                 AND split_part(k.acquisition_scope, '|', 1) = '被动' AND k.metric = 'orders'
                THEN COALESCE(mog.actual, 0)
            ELSE es.actual
        END AS raw_actual,
        CASE
            WHEN k.business_line = 'abroad' THEN NULL
            WHEN k.metric = 'heads' THEN hs.prior
            WHEN k.dimension_type = 'business_group' AND k.unit_id IN ('total', 'online_scope', 'offline_scope')
                 AND split_part(k.acquisition_scope, '|', 1) = '被动' AND k.metric = 'orders'
                THEN COALESCE(mog.prior, 0)
            ELSE es.prior
        END AS raw_prior,
        CASE WHEN k.metric = 'heads' THEN hs.study_heads END AS study_heads,
        CASE WHEN k.metric = 'heads' THEN hs.language_heads END AS small_language_heads,
        CASE WHEN k.dimension_type = 'business_group' AND k.metric IN ('orders', 'cash')
                  AND split_part(k.acquisition_scope, '|', 1) = '被动'
            THEN tv.target END AS target,
        CASE WHEN k.business_line = 'abroad' AND k.unit_id IN ('prep', 'high')
             THEN 'not_configured' ELSE COALESCE(p.status, 'available') END AS base_status,
        COALESCE(p.time_progress, 0)::DOUBLE AS time_progress,
        CASE WHEN k.dimension_type = 'business_group' AND k.metric = 'cash' THEN
            CASE WHEN p.status = 'future' THEN NULL ELSE COALESCE(nsc.denominator, 0) END
        END AS cash_share_denominator
    FROM metric_keys k
    JOIN business.periods p USING (period_id)
    LEFT JOIN dimension_sums es ON es.period_id = k.period_id AND es.unit_id = k.unit_id
      AND es.acquisition_scope = k.acquisition_scope AND es.business_line = k.business_line
      AND es.dimension_type = k.dimension_type AND es.dim1 = k.dim1 AND es.dim2 = k.dim2
      AND es.dim3 = k.dim3 AND es.first_channel = k.first_channel AND es.metric = k.metric
    LEFT JOIN head_sums hs ON hs.period_id = k.period_id AND hs.unit_id = k.unit_id
      AND hs.acquisition_scope = k.acquisition_scope AND hs.business_line = k.business_line
      AND hs.dimension_type = k.dimension_type AND hs.dim1 = k.dim1 AND hs.dim2 = k.dim2
      AND hs.dim3 = k.dim3 AND hs.first_channel = k.first_channel
    LEFT JOIN target_values tv ON tv.period_id = k.period_id AND tv.unit_id = k.unit_id
      AND tv.business_group = k.dim1 AND tv.metric = k.metric
    LEFT JOIN market_order_groups mog ON mog.period_id = k.period_id AND mog.unit_id = k.unit_id
      AND mog.business_group = k.dim1
    LEFT JOIN new_student_cash_groups nsc ON nsc.period_id = k.period_id
      AND nsc.acquisition_scope = k.acquisition_scope AND nsc.business_group = k.dim1
),
marked AS (
    SELECT *,
        CASE WHEN metric = 'heads' AND business_line = 'abroad' THEN
                 CASE WHEN COALESCE(study_heads, 0) > 0 AND COALESCE(small_language_heads, 0) > 0
                      THEN 'separate_counts'
                      WHEN base_status = 'separate_counts' THEN 'available'
                      ELSE base_status END
             ELSE base_status END AS status
    FROM metric_values
),
available_values AS (
    SELECT *,
        CASE WHEN status IN ('future', 'not_covered', 'not_configured', 'not_connected') THEN NULL
             WHEN metric = 'heads' AND business_line = 'abroad'
                  AND status = 'separate_counts' THEN NULL
             ELSE COALESCE(raw_actual, 0) END AS actual,
        CASE WHEN business_line = 'abroad' OR status IN ('future', 'not_covered', 'not_configured', 'not_connected') THEN NULL
             ELSE COALESCE(raw_prior, 0) END AS prior
    FROM marked
),
with_yoy AS (
    SELECT *,
        CASE WHEN actual IS NOT NULL AND prior IS NOT NULL AND prior <> 0
             THEN actual / prior - 1 END AS yoy,
        CASE WHEN actual IS NOT NULL AND target IS NOT NULL AND target <> 0
             THEN actual / target END AS completion,
        CASE WHEN actual IS NOT NULL AND target IS NOT NULL
             THEN ROUND(actual - target, 2) END AS gap,
        CASE WHEN actual IS NOT NULL AND target IS NOT NULL
             THEN ROUND(actual - target * time_progress, 2) END AS time_gap,
        CASE WHEN metric = 'heads' AND status = 'separate_counts'
             THEN '留学' || CAST(study_heads AS BIGINT)::VARCHAR || '人／小语种' || CAST(small_language_heads AS BIGINT)::VARCHAR || '人'
             ELSE NULL END AS display,
        '' AS note
    FROM available_values
),
grade_first_facts AS (
    SELECT e.period_id, e.unit_id, e.acquisition_scope,
        CASE
            WHEN e.grade_name IS NULL OR e.grade_name IN ('未知', '暂无归属') THEN '年级待确认'
            WHEN e.grade_name = '七年级' THEN '初一'
            WHEN e.grade_name = '八年级' THEN '初二'
            WHEN e.grade_name = '九年级' THEN '初三'
            WHEN e.grade_name = '小班' THEN '幼儿园小班'
            WHEN e.grade_name = '中班' THEN '幼儿园中班'
            WHEN e.grade_name = '大班' THEN '幼儿园大班'
            ELSE e.grade_name END AS dim1,
        MIN(o.source_order) AS fact_order
    FROM base_events e JOIN business.training_fact_order o USING (fact_id)
    WHERE e.business_line = 'training'
    GROUP BY 1, 2, 3, 4
),
grade_cash_sequence AS (
    SELECT v.period_id, v.unit_id, v.acquisition_scope,
        ROW_NUMBER() OVER (PARTITION BY v.period_id, v.unit_id, v.acquisition_scope
                          ORDER BY g.fact_order) AS ordinal,
        COALESCE(v.actual, 0)::DOUBLE AS amount
    FROM with_yoy v JOIN grade_first_facts g
        USING (period_id, unit_id, acquisition_scope, dim1)
    WHERE v.business_line = 'training' AND v.dimension_type = 'grade' AND v.metric = 'cash'
),
-- _number returns int for whole amounts, float otherwise. Python 3.12 sum
-- starts float compensation only after the first int-to-float addition;
-- subsequent ints do not change compensation.
-- Preserve both this distinction and _grade_rows' first-fact bucket order.
grade_cash_accumulator AS (
    SELECT period_id, unit_id, acquisition_scope, 0::BIGINT AS ordinal,
        0::DOUBLE AS running, 0::DOUBLE AS correction, FALSE AS seen_float
    FROM grade_cash_sequence GROUP BY 1, 2, 3
    UNION ALL
    SELECT a.period_id, a.unit_id, a.acquisition_scope, v.ordinal,
        a.running + v.amount,
        CASE WHEN v.amount = TRUNC(v.amount) OR NOT a.seen_float THEN a.correction
             WHEN ABS(a.running) >= ABS(v.amount)
                THEN a.correction + ((a.running - (a.running + v.amount)) + v.amount)
             ELSE a.correction + ((v.amount - (a.running + v.amount)) + a.running)
        END
        , a.seen_float OR v.amount <> TRUNC(v.amount)
    FROM grade_cash_accumulator a JOIN grade_cash_sequence v
      ON a.period_id = v.period_id AND a.unit_id = v.unit_id
     AND a.acquisition_scope = v.acquisition_scope AND v.ordinal = a.ordinal + 1
),
grade_cash_totals AS (
    SELECT period_id, unit_id, acquisition_scope, running + correction AS cash_total
    FROM grade_cash_accumulator
    QUALIFY ROW_NUMBER() OVER (PARTITION BY period_id, unit_id, acquisition_scope
                              ORDER BY ordinal DESC) = 1
),
-- _school_grade_rows totals school cash in canonical school-name order,
-- after _number has preserved whole amounts as ints (the same mixed sum).
school_cash_sequence AS (
    SELECT period_id, unit_id, acquisition_scope, business_line,
        ROW_NUMBER() OVER (PARTITION BY period_id, unit_id, acquisition_scope, business_line
                          ORDER BY dim1) AS ordinal,
        COALESCE(actual, 0)::DOUBLE AS amount
    FROM with_yoy WHERE dimension_type = 'school' AND metric = 'cash'
),
school_cash_accumulator AS (
    SELECT period_id, unit_id, acquisition_scope, business_line, 0::BIGINT AS ordinal,
        0::DOUBLE AS running, 0::DOUBLE AS correction, FALSE AS seen_float
    FROM school_cash_sequence GROUP BY 1, 2, 3, 4
    UNION ALL
    SELECT a.period_id, a.unit_id, a.acquisition_scope, a.business_line, v.ordinal,
        a.running + v.amount,
        CASE WHEN v.amount = TRUNC(v.amount) OR NOT a.seen_float THEN a.correction
             WHEN ABS(a.running) >= ABS(v.amount)
                THEN a.correction + ((a.running - (a.running + v.amount)) + v.amount)
             ELSE a.correction + ((v.amount - (a.running + v.amount)) + a.running)
        END
        , a.seen_float OR v.amount <> TRUNC(v.amount)
    FROM school_cash_accumulator a JOIN school_cash_sequence v
      ON a.period_id = v.period_id AND a.unit_id = v.unit_id
     AND a.acquisition_scope = v.acquisition_scope AND a.business_line = v.business_line AND v.ordinal = a.ordinal + 1
),
school_cash_totals AS (
    SELECT period_id, unit_id, acquisition_scope, business_line, running + correction AS cash_total
    FROM school_cash_accumulator
    QUALIFY ROW_NUMBER() OVER (PARTITION BY period_id, unit_id, acquisition_scope, business_line
                              ORDER BY ordinal DESC) = 1
),
share_totals AS (
    SELECT period_id, unit_id, acquisition_scope, business_line, dimension_type,
        SUM(actual) FILTER (WHERE metric = 'orders') AS order_total,
        SUM(actual) FILTER (WHERE metric = 'cash') AS cash_total
    FROM with_yoy
    GROUP BY period_id, unit_id, acquisition_scope, business_line, dimension_type
),
channel_cash_totals AS (
    SELECT period_id, unit_id, acquisition_scope, business_line, first_channel, dim1,
        SUM(value) AS channel_cash
    FROM dimension_events
    WHERE dimension_type = 'channel' AND metric = 'cash' AND comparison = 'actual'
    GROUP BY period_id, unit_id, acquisition_scope, business_line, first_channel, dim1
),
share_values AS (
    SELECT v.*,
        CASE WHEN v.metric = 'orders' AND st.order_total <> 0 AND v.actual IS NOT NULL
             THEN v.actual / st.order_total END AS share,
        CASE WHEN v.metric = 'cash' AND st.cash_total <> 0 AND v.actual IS NOT NULL
             THEN v.actual / CASE WHEN v.business_line = 'training' AND v.dimension_type = 'grade'
                                 THEN gt.cash_total
                                 WHEN v.dimension_type IN ('school', 'school_grade') THEN sct.cash_total
                                 ELSE st.cash_total END END AS cash_share,
        CASE WHEN v.dimension_type IN ('channel_group', 'channel_school') AND v.metric = 'cash'
                  AND cct.channel_cash <> 0 AND v.actual IS NOT NULL
             THEN v.actual / cct.channel_cash END AS channel_cash_share,
        CASE WHEN v.dimension_type = 'business_group' AND v.metric = 'cash'
                  AND v.cash_share_denominator <> 0 AND v.actual IS NOT NULL
             THEN v.actual / v.cash_share_denominator END AS passive_cash_share,
        CASE WHEN v.dimension_type = 'business_group' AND v.metric = 'cash'
                  AND v.cash_share_denominator IS NOT NULL THEN v.actual END AS cash_share_numerator
    FROM with_yoy v
    LEFT JOIN grade_cash_totals gt USING (period_id, unit_id, acquisition_scope)
    LEFT JOIN school_cash_totals sct USING (period_id, unit_id, acquisition_scope, business_line)
    LEFT JOIN share_totals st USING (period_id, unit_id, acquisition_scope, business_line, dimension_type)
    LEFT JOIN channel_cash_totals cct ON cct.period_id = v.period_id AND cct.unit_id = v.unit_id
      AND cct.acquisition_scope = v.acquisition_scope AND cct.business_line = v.business_line
      AND cct.first_channel = v.first_channel AND cct.dim1 = v.dim1
)
SELECT v.period_id, v.unit_id, v.acquisition_scope, v.business_line,
    v.dimension_type, v.dim1, v.dim2, v.dim3, v.first_channel, v.metric,
    v.actual, v.prior, v.target, v.status, v.time_progress, v.yoy, v.completion, v.gap, v.time_gap,
    v.display, v.note, v.share, v.cash_share, v.channel_cash_share, v.passive_cash_share,
    v.cash_share_numerator, v.cash_share_denominator, v.study_heads, v.small_language_heads,
    CASE WHEN v.metric = 'cash' AND v.dimension_type = 'business_group' THEN
        CASE WHEN p.status = 'future' THEN 'future'
             WHEN v.cash_share_denominator IS NULL THEN 'unavailable'
             WHEN v.cash_share_denominator = 0 THEN 'zero_denominator'
             WHEN v.passive_cash_share > 1 THEN 'over_100_percent'
             ELSE 'available' END
    END AS passive_cash_share_status
FROM share_values v
JOIN business.periods p ON p.period_id = v.period_id
CROSS JOIN query_filters q
WHERE len(q.dimension_ids) = 0 OR list_contains(q.dimension_ids, v.dimension_type)
);

CREATE OR REPLACE VIEW business.dimension_metrics AS
SELECT * FROM business.dimension_query(
    NULL::VARCHAR[], NULL::VARCHAR[], NULL::VARCHAR[], NULL::VARCHAR[]
);

CREATE OR REPLACE VIEW business.dimension_countries AS
WITH country_rows AS (
    SELECT e.period_id, e.unit_id, e.acquisition_scope,
        COALESCE(NULLIF(TRIM(CAST(e.line AS VARCHAR)), ''), '条线待确认') AS line,
        COALESCE(NULLIF(TRIM(CAST(e.country AS VARCHAR)), ''), '国家待确认') AS country,
        SUM(e.value) FILTER (WHERE e.segment_id = 'study_abroad_online') AS online,
        SUM(e.value) FILTER (WHERE e.segment_id = 'study_abroad_offline') AS offline,
        SUM(e.value) FILTER (WHERE e.segment_id NOT IN ('study_abroad_online', 'study_abroad_offline')
                                  OR e.segment_id IS NULL) AS unassigned
    FROM business.period_events e
    WHERE e.business_line = 'abroad' AND e.comparison = 'actual' AND e.metric = 'orders'
      AND e.unit_id NOT LIKE 'selection_%'
    GROUP BY e.period_id, e.unit_id, e.acquisition_scope, line, country
    UNION ALL
    SELECT e.period_id, s.unit_id, e.acquisition_scope,
        COALESCE(NULLIF(TRIM(CAST(e.line AS VARCHAR)), ''), '条线待确认') AS line,
        COALESCE(NULLIF(TRIM(CAST(e.country AS VARCHAR)), ''), '国家待确认') AS country,
        SUM(e.value) FILTER (WHERE e.segment_id = 'study_abroad_online') AS online,
        SUM(e.value) FILTER (WHERE e.segment_id = 'study_abroad_offline') AS offline,
        SUM(e.value) FILTER (WHERE e.segment_id NOT IN ('study_abroad_online', 'study_abroad_offline')
                                  OR e.segment_id IS NULL) AS unassigned
    FROM business.period_events e
    JOIN business.scopes s ON s.unit_id LIKE 'selection_%'
    WHERE e.unit_id = 'total' AND e.business_line = 'abroad'
      AND e.comparison = 'actual' AND e.metric = 'orders'
    GROUP BY e.period_id, s.unit_id, e.acquisition_scope, line, country
)
SELECT period_id, unit_id, acquisition_scope, line, country,
    COALESCE(online, 0)::DOUBLE AS online,
    COALESCE(offline, 0)::DOUBLE AS offline,
    COALESCE(unassigned, 0)::DOUBLE AS unassigned,
    (COALESCE(online, 0) + COALESCE(offline, 0) + COALESCE(unassigned, 0))::DOUBLE AS total
FROM country_rows;

CREATE OR REPLACE VIEW business.dimension_country_groups AS
SELECT period_id, unit_id, acquisition_scope, line,
    SUM(online)::DOUBLE AS online,
    SUM(offline)::DOUBLE AS offline,
    SUM(unassigned)::DOUBLE AS unassigned,
    SUM(total)::DOUBLE AS total
FROM business.dimension_countries
GROUP BY period_id, unit_id, acquisition_scope, line;
