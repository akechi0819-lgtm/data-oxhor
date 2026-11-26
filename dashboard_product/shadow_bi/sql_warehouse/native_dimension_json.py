"""Preserve native dimension traversal using query-local SQL JSON arrays."""
from __future__ import annotations

from dashboard_product.shadow_bi.sql_warehouse.common_rules import UNIVERSITY_SCHOOL_ATTRIBUTES
from dashboard_product.shadow_bi.sql_warehouse.native_school import _replace_cte


def metric_json(metric: str) -> str:
    """Aggregate one dimension metric into the existing presentation object."""
    fields = []
    for field in ('actual', 'prior', 'yoy', 'status', 'display'):
        value = f"MAX({field}) FILTER (WHERE metric='{metric}')"
        fields.extend((f"'{field}'", value))
    return 'json_object(' + ','.join(fields) + ')'


def grade_json_source(units_sql: str) -> str:
    """Supply scoped_team_periods' grade-only shape without storing JSON tables.

    The original native ROW_NUMBER runs before the outer period filter. Keep
    all periods, and let the unchanged template choose acquisition_scope.
    Parent rows retain library.tables' period/team iteration order (year,
    quarters, months; total, virtual, online). Without it, native sort ties
    change when the upstream hash aggregation emits a different parent order.
    """
    measures = ','.join(f"'{metric}',{metric_json(metric)}"
                        for metric in ('orders', 'cash', 'heads'))
    return """WITH d AS MATERIALIZED (
        SELECT * FROM business.dimension_query(NULL,""" + units_sql + """,
            ['{{ acquisition_scope }}'],['grade'])
    ), nodes AS (
        SELECT period_id,unit_id,acquisition_scope,business_line,dim1,
            json_object('name',dim1,""" + measures + """,
                'share',MAX(share) FILTER (WHERE metric='orders'),
                'cash_share',MAX(cash_share) FILTER (WHERE metric='cash')) AS node
        FROM d GROUP BY 1,2,3,4,5
    ), lines AS (
        SELECT period_id,unit_id,acquisition_scope,business_line,
            to_json(LIST(node ORDER BY dim1)) AS grades
        FROM nodes GROUP BY 1,2,3,4
    )
    SELECT period_id,unit_id AS team_id,acquisition_scope,
        json_object('grades_by_line',json_object(
            'training',MAX(grades) FILTER (WHERE business_line='training'),
            'abroad',MAX(grades) FILTER (WHERE business_line='abroad'))) AS view
    FROM lines GROUP BY 1,2,3
    ORDER BY CASE WHEN period_id LIKE 'FY%' THEN 0
                  WHEN period_id LIKE 'Q%' THEN 1 ELSE 2 END, period_id,
             CASE unit_id WHEN 'total' THEN 0 WHEN 'virtual' THEN 1
                          WHEN 'online' THEN 2 ELSE 3 END"""


def native_grade_json_sql(page: str, legacy_sql: str) -> str:
    """Keep the legacy JSON expansion and native sorting query unchanged."""
    if page == 'prep':
        units = "list_value('selection_'||CAST({{ mask }} AS VARCHAR))"
        source = grade_json_source(units)
        source = ("SELECT period_id,{{ mask }} AS selection,acquisition_scope,"
                  "json_object('view',json_object('teams',json_array(view))) AS row_json "
                  "FROM (" + source + ") selected")
        table = 'queries.scoped_selection_team_periods'
    else:
        units = {'overview': "['total','virtual','online']", 'virtual': "['virtual']",
                 'university': "['university']"}[page]
        source = grade_json_source(units)
        table = 'queries.scoped_team_periods'
    if table not in legacy_sql:
        raise ValueError('legacy grade SQL is missing its scoped source')
    return legacy_sql.replace(table, '(' + source + ')')


def channel_json_source(units_sql: str) -> str:
    """Rebuild the existing channel/child arrays inside the current query."""
    measures = ','.join(f"'{metric}',{metric_json(metric)}"
                        for metric in ('orders', 'cash', 'heads'))
    return """WITH d AS MATERIALIZED (
        SELECT * FROM business.dimension_query(NULL,""" + units_sql + """,
            ['{{ acquisition_scope }}'],['channel','channel_group'])
    ), nodes AS (
        SELECT period_id,unit_id,acquisition_scope,business_line,dimension_type,
            dim1,dim2,first_channel,
            json_object('name',CASE WHEN dimension_type='channel' THEN dim1 ELSE dim2 END,
                'business_line',business_line,
                'first_channel',CASE WHEN first_channel='∅' THEN NULL ELSE first_channel END,
                """ + measures + """,
                'share',MAX(share) FILTER (WHERE metric='orders'),
                'cash_share',MAX(cash_share) FILTER (WHERE metric='cash'),
                'channel_cash_share',MAX(channel_cash_share) FILTER (WHERE metric='cash')) AS node,
            MAX(actual) FILTER (WHERE metric='cash') AS cash,
            MAX(actual) FILTER (WHERE metric='orders') AS orders
        FROM d GROUP BY 1,2,3,4,5,6,7,8
    ), groups AS (
        SELECT period_id,unit_id,acquisition_scope,business_line,dim1,first_channel,
            to_json(LIST(node ORDER BY dim2)) AS groups
        FROM nodes WHERE dimension_type='channel_group' GROUP BY 1,2,3,4,5,6
    ), parents AS (
        SELECT p.*,json_merge_patch(p.node,json_object('groups',g.groups)) AS full_node
        FROM nodes p LEFT JOIN groups g
            USING(period_id,unit_id,acquisition_scope,business_line,dim1,first_channel)
        WHERE p.dimension_type='channel'
    )
    SELECT period_id,unit_id AS team_id,acquisition_scope,
        json_object('channels',LIST(full_node ORDER BY business_line,
            cash DESC NULLS LAST,orders DESC NULLS LAST,dim1,first_channel)) AS view
    FROM parents GROUP BY 1,2,3
    ORDER BY CASE WHEN period_id LIKE 'FY%' THEN 0
                  WHEN period_id LIKE 'Q%' THEN 1 ELSE 2 END,period_id,
             CASE unit_id WHEN 'total' THEN 0 WHEN 'virtual' THEN 1
                          WHEN 'online' THEN 2 ELSE 3 END"""


def university_channel_json_source() -> str:
    """Rebuild the native university channel→attribute→school JSON tree."""
    attributes = '[' + ','.join(
        "'" + value.replace("'", "''") + "'"
        for value in UNIVERSITY_SCHOOL_ATTRIBUTES
    ) + ']'
    measures = ','.join(f"'{metric}',{metric_json(metric)}"
                        for metric in ('orders', 'cash', 'heads'))
    return """WITH d AS MATERIALIZED (
        SELECT * FROM business.dimension_query(NULL,['university'],
            ['{{ acquisition_scope }}'],['channel','channel_group','channel_school'])
    ), nodes AS (
        SELECT period_id,unit_id,acquisition_scope,business_line,dimension_type,
            dim1,dim2,dim3,first_channel,
            json_object('name',CASE dimension_type
                    WHEN 'channel' THEN dim1
                    WHEN 'channel_group' THEN dim2
                    ELSE dim3 END,
                'business_line',business_line,
                'first_channel',CASE WHEN first_channel='∅' THEN NULL ELSE first_channel END,
                """ + measures + """,
                'share',MAX(share) FILTER (WHERE metric='orders'),
                'cash_share',MAX(cash_share) FILTER (WHERE metric='cash'),
                'channel_cash_share',MAX(channel_cash_share) FILTER (WHERE metric='cash')) AS node,
            MAX(actual) FILTER (WHERE metric='cash') AS cash,
            MAX(actual) FILTER (WHERE metric='orders') AS orders
        FROM d
        GROUP BY 1,2,3,4,5,6,7,8,9
    ), schools AS (
        SELECT period_id,unit_id,acquisition_scope,business_line,dim1,dim2,first_channel,
            to_json(LIST(node ORDER BY dim3)) AS schools
        FROM nodes
        WHERE dimension_type='channel_school'
        GROUP BY 1,2,3,4,5,6,7
    ), groups AS (
        SELECT g.period_id,g.unit_id,g.acquisition_scope,g.business_line,g.dim1,g.first_channel,
            to_json(LIST(json_merge_patch(g.node,json_object('schools',s.schools))
                ORDER BY list_position(""" + attributes + """,g.dim2))) AS groups
        FROM nodes g
        LEFT JOIN schools s USING(period_id,unit_id,acquisition_scope,business_line,dim1,dim2,first_channel)
        WHERE g.dimension_type='channel_group'
        GROUP BY 1,2,3,4,5,6
    ), parents AS (
        SELECT p.*,json_merge_patch(p.node,json_object('groups',g.groups)) AS full_node
        FROM nodes p
        LEFT JOIN groups g USING(period_id,unit_id,acquisition_scope,business_line,dim1,first_channel)
        WHERE p.dimension_type='channel'
    )
    SELECT period_id,unit_id AS team_id,acquisition_scope,
        json_object('channels',LIST(full_node ORDER BY business_line,
            cash DESC NULLS LAST,orders DESC NULLS LAST,dim1,first_channel)) AS view
    FROM parents
    GROUP BY 1,2,3
    ORDER BY CASE WHEN period_id LIKE 'FY%' THEN 0
                  WHEN period_id LIKE 'Q%' THEN 1 ELSE 2 END,period_id"""


def native_channel_json_sql(
    page: str,
    legacy_sql: str,
    *,
    university_channel_node_sources: dict[str, str] | None = None,
) -> str:
    """Reuse the original native channel tree, including its traversal order."""
    if page == 'prep':
        units = "list_value('selection_'||CAST({{ mask }} AS VARCHAR))"
        source = channel_json_source(units)
        source = ("SELECT period_id,{{ mask }} AS selection,acquisition_scope,"
                  "json_object('view',json_object('teams',json_array(view))) AS row_json "
                  "FROM (" + source + ") selected")
        table = 'queries.scoped_selection_team_periods'
    elif page in ('overview', 'virtual', 'university'):
        table = 'queries.scoped_team_periods'
        if table not in legacy_sql:
            raise ValueError('legacy channel SQL is missing its scoped source')
        adapted = legacy_sql.replace(table, 'business.scoped_team_periods_channel_cache')
        if page == 'university' and university_channel_node_sources is not None:
            for cte_name in ('groups', 'schools'):
                try:
                    source = university_channel_node_sources[cte_name]
                except KeyError as exc:
                    raise ValueError(f'university channel node sources missing {cte_name!r}') from exc
                scope_predicate = "AND acquisition_scope='{{ acquisition_scope }}'"
                if source.count(scope_predicate) != 1:
                    raise ValueError(f'university {cte_name} source must filter the selected scope once')
                source = source.replace(
                    scope_predicate,
                    scope_predicate + " {% if periods %} AND period_id IN {{ periods|where_in }} {% endif %}",
                    1,
                )
                adapted = _replace_cte(adapted, cte_name, source)
        return adapted
    else:
        raise ValueError(f'unsupported native channel page: {page!r}')
    if table not in legacy_sql:
        raise ValueError('legacy channel SQL is missing its scoped source')
    return legacy_sql.replace(table, '(' + source + ')')
