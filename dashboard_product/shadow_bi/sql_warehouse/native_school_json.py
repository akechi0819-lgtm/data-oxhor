"""Rebuild the native school-tree JSON relation from dimension SQL."""
from __future__ import annotations

from dashboard_product.shadow_bi.sql_warehouse.native_dimension_json import metric_json


_TEAM_UNITS = "['total','prep','high','university','virtual','online']"
_ACQUISITION_SCOPES = "['全部','主动','被动']"


def _metric_json_without_display(metric: str) -> str:
    fields = []
    for field in ('actual', 'prior', 'yoy', 'status'):
        fields.extend((f"'{field}'", f"MAX({field}) FILTER (WHERE metric='{metric}')"))
    return 'json_object(' + ','.join(fields) + ')'


def school_json_source(
    units_sql: str = _TEAM_UNITS,
    scopes_sql: str = _ACQUISITION_SCOPES,
) -> str:
    """Return the legacy ``period_id,team_id,acquisition_scope,view`` shape.

    The JSON keeps the old line→school→grade hierarchy. Parent rows follow the
    source producer order (acquisition scope, year, quarter, month, then legacy
    unit order), while schools sort by work orders and name and grades by label.
    """
    if not units_sql.strip() or not scopes_sql.strip():
        raise ValueError('school JSON units and acquisition scopes must be SQL expressions')

    return f"""WITH dimension_rows AS MATERIALIZED (
        SELECT * FROM business.dimension_query(
            NULL::VARCHAR[], ({units_sql})::VARCHAR[], ({scopes_sql})::VARCHAR[],
            ['school','school_grade']::VARCHAR[])
    ), wide AS (
        SELECT period_id,unit_id,acquisition_scope,business_line,dimension_type,
            dim1 AS school,dim2 AS grade,
            MAX(actual) FILTER (WHERE metric='orders') AS orders_actual,
            MAX(prior) FILTER (WHERE metric='orders') AS orders_prior,
            MAX(yoy) FILTER (WHERE metric='orders') AS orders_yoy,
            MAX(status) FILTER (WHERE metric='orders') AS orders_status,
            MAX(actual) FILTER (WHERE metric='cash') AS cash_actual,
            MAX(prior) FILTER (WHERE metric='cash') AS cash_prior,
            MAX(yoy) FILTER (WHERE metric='cash') AS cash_yoy,
            MAX(status) FILTER (WHERE metric='cash') AS cash_status,
            MAX(actual) FILTER (WHERE metric='heads') AS heads_actual,
            MAX(prior) FILTER (WHERE metric='heads') AS heads_prior,
            MAX(yoy) FILTER (WHERE metric='heads') AS heads_yoy,
            MAX(status) FILTER (WHERE metric='heads') AS heads_status,
            MAX(display) FILTER (WHERE metric='heads') AS heads_display,
            MAX(share) FILTER (WHERE metric='orders') AS orders_share,
            MAX(cash_share) FILTER (WHERE metric='cash') AS cash_share,
            {_metric_json_without_display('orders')} AS orders_json,
            {_metric_json_without_display('cash')} AS cash_json,
            {metric_json('heads')} AS heads_json
        FROM dimension_rows
        WHERE dimension_type IN ('school','school_grade')
          AND metric IN ('orders','cash','heads')
        GROUP BY period_id,unit_id,acquisition_scope,business_line,dimension_type,dim1,dim2
    ), grade_nodes AS (
        SELECT period_id,unit_id,acquisition_scope,business_line,school,
            to_json(LIST(json_object(
                'name',grade,
                'orders',orders_json,
                'cash',cash_json,
                'heads',heads_json,
                'share',orders_share,'cash_share',cash_share
            ) ORDER BY grade ASC)) AS grades
        FROM wide
        WHERE dimension_type='school_grade'
        GROUP BY period_id,unit_id,acquisition_scope,business_line,school
    ), school_nodes AS (
        SELECT p.period_id,p.unit_id,p.acquisition_scope,p.business_line,p.school,
            p.orders_actual,
            json_object(
                'name',p.school,
                'orders',json_object('actual',p.orders_actual,'prior',p.orders_prior,
                    'yoy',p.orders_yoy,'status',p.orders_status),
                'cash',json_object('actual',p.cash_actual,'prior',p.cash_prior,
                    'yoy',p.cash_yoy,'status',p.cash_status),
                'heads',json_object('actual',p.heads_actual,'prior',p.heads_prior,
                    'yoy',p.heads_yoy,'status',p.heads_status,'display',p.heads_display),
                'share',p.orders_share,'cash_share',p.cash_share,
                'grades',COALESCE(g.grades,'[]'::JSON)
            ) AS school_node
        FROM wide p LEFT JOIN grade_nodes g
          USING(period_id,unit_id,acquisition_scope,business_line,school)
        WHERE p.dimension_type='school'
    ), line_nodes AS (
        SELECT period_id,unit_id,acquisition_scope,business_line,
            to_json(LIST(school_node ORDER BY orders_actual DESC NULLS LAST,school ASC)) AS school_array
        FROM school_nodes
        GROUP BY period_id,unit_id,acquisition_scope,business_line
    ), scope_views AS (
        SELECT k.period_id,k.unit_id,k.acquisition_scope,
            json_object('schools_by_line',json_object(
                'abroad',COALESCE(FIRST(l.school_array) FILTER (WHERE l.business_line='abroad'),'[]'::JSON),
                'training',COALESCE(FIRST(l.school_array) FILTER (WHERE l.business_line='training'),'[]'::JSON)
            )) AS view
        FROM (
            SELECT p.period_id,u.unit_id,s.acquisition_scope
            FROM business.periods p
            CROSS JOIN UNNEST(({units_sql})::VARCHAR[]) u(unit_id)
            CROSS JOIN UNNEST(({scopes_sql})::VARCHAR[]) s(acquisition_scope)
        ) k
        LEFT JOIN line_nodes l USING(period_id,unit_id,acquisition_scope)
        GROUP BY k.period_id,k.unit_id,k.acquisition_scope
    )
    SELECT v.period_id,v.unit_id AS team_id,v.acquisition_scope,v.view
    FROM scope_views v JOIN business.periods p USING(period_id)
    ORDER BY CASE v.acquisition_scope WHEN '被动' THEN 1 WHEN '主动' THEN 2 WHEN '全部' THEN 3 ELSE 4 END,
        CASE p.kind WHEN 'year' THEN 1 WHEN 'quarter' THEN 2 WHEN 'month' THEN 3 ELSE 4 END,
        p.start_date,
        CASE v.unit_id WHEN 'total' THEN 1 WHEN 'prep' THEN 2 WHEN 'high' THEN 3
            WHEN 'university' THEN 4 WHEN 'virtual' THEN 5 WHEN 'online' THEN 6
            WHEN 'selection_1' THEN 1 WHEN 'selection_2' THEN 2 WHEN 'selection_3' THEN 3
            WHEN 'selection_4' THEN 4 WHEN 'selection_5' THEN 5 WHEN 'selection_6' THEN 6
            WHEN 'selection_7' THEN 7 ELSE 8 END,
        CASE v.acquisition_scope WHEN '被动' THEN 1 WHEN '主动' THEN 2 WHEN '全部' THEN 3 ELSE 4 END"""


def native_school_json_sql(page: str, legacy_sql: str) -> str:
    """Replace one scoped legacy source while preserving its native tree SQL."""
    if page == 'university':
        source_name = 'queries.scoped_team_periods'
        source = school_json_source("['university']", "['{{ acquisition_scope }}']")
    else:
        raise ValueError(f'unsupported native school JSON page: {page!r}')
    count = legacy_sql.count(source_name)
    if count != 1:
        raise ValueError(f'{page} native school SQL must contain one {source_name} reference, got {count}')
    return legacy_sql.replace(source_name, '(' + source + ')', 1)
