"""Materialize shared native channel JSON and typed university child sources."""
from __future__ import annotations

from .native_dimension_json import channel_json_source, university_channel_json_source


TABLE = "business.scoped_team_periods_channel_cache"
UNIVERSITY_NODES_TABLE = "business.university_channel_nodes_cache"
SCOPES = tuple(mode + suffix for suffix in ("", "|新生", "|老生")
               for mode in ("被动", "主动", "全部"))
UNITS = ("total", "prep", "high", "university", "virtual", "online",
         "overview_prep", "overview_high", "overview_university")
ORDINARY_UNITS = "['total','prep','high','virtual','online','overview_prep','overview_high','overview_university']"
_UNIT_VALUES = ",".join(
    f"('{unit}',{ordinal})" for ordinal, unit in enumerate(UNITS)
)
_WIDE_NUMERIC = (
    ("工单", "orders", "actual"),
    ("工单同期", "orders", "prior"),
    ("工单同比", "orders", "yoy"),
    ("现金", "cash", "actual"),
    ("现金同期", "cash", "prior"),
    ("现金同比", "cash", "yoy"),
    ("人头", "heads", "actual"),
    ("人头同期", "heads", "prior"),
    ("人头同比", "heads", "yoy"),
    ("工单占比", "", "share"),
    ("现金占比", "", "cash_share"),
)
_WIDE_TEXT = (
    ("分域人数", "heads", "display"),
    ("工单状态", "orders", "status"),
    ("现金状态", "cash", "status"),
    ("人数状态", "heads", "status"),
)


def _node_value(alias: str, path: str) -> str:
    return f"json_extract_string({alias}, '$.{path}')"


def _status_value(alias: str, path: str) -> str:
    value = _node_value(alias, path)
    return (f"CASE {value} WHEN 'available' THEN '已提供' "
            "WHEN 'partial' THEN '部分覆盖' WHEN 'missing' THEN '未提供' "
            "WHEN 'not_covered' THEN '该期间未覆盖' WHEN 'not_connected' THEN '未接入' "
            "WHEN 'not_configured' THEN '未配置' WHEN 'future' THEN '尚未开始' "
            "WHEN 'separate_counts' THEN '分域人数' WHEN 'zero_denominator' THEN '分母为零' "
            f"ELSE {value} END")


def _university_node_insert_sql(scope: str) -> str:
    numeric_fields = []
    for label, family, field in _WIDE_NUMERIC:
        path = f"{family}.{field}" if family else field
        numeric_fields.append(
            f"TRY_CAST({_node_value('n.node', path)} AS DOUBLE) AS {_quote(label)}"
        )
    text_fields = []
    for label, family, field in _WIDE_TEXT:
        path = f"{family}.{field}"
        expression = _status_value('n.node', path) if label.endswith('状态') else _node_value('n.node', path)
        text_fields.append(f"{expression} AS {_quote(label)}")

    fields = [
        "n.acquisition_scope", "n.period_id", "n.team_id", "n.node_kind",
        "n.business_line", "n.channel", "n.first_channel", "n.group_name",
        "n.school_name", *numeric_fields, *text_fields,
        f"TRY_CAST({_node_value('n.node', 'channel_cash_share')} AS DOUBLE) AS {_quote('渠道内现金占比')}",
    ]
    return f"""
INSERT INTO {UNIVERSITY_NODES_TABLE}
WITH source_rows AS MATERIALIZED (
    SELECT acquisition_scope, period_id, team_id, CAST(view AS JSON) AS view_json
    FROM {TABLE}
    WHERE acquisition_scope={_literal(scope)} AND team_id='university'
), channels AS MATERIALIZED (
    SELECT r.acquisition_scope, r.period_id, r.team_id, c.value AS channel_node
    FROM source_rows r, json_each(r.view_json, '$.channels') c
), groups AS MATERIALIZED (
    SELECT c.acquisition_scope, c.period_id, c.team_id,
           json_extract_string(c.channel_node, '$.business_line') AS business_line,
           json_extract_string(c.channel_node, '$.name') AS channel,
           json_extract_string(c.channel_node, '$.first_channel') AS first_channel,
           g.value AS group_node,
           json_extract_string(g.value, '$.name') AS group_name
    FROM channels c, json_each(c.channel_node, '$.groups') g
), expanded AS MATERIALIZED (
    SELECT acquisition_scope, period_id, team_id, 'group'::VARCHAR AS node_kind,
           business_line, channel, first_channel, group_name,
           NULL::VARCHAR AS school_name, group_node AS node
    FROM groups
    UNION ALL
    SELECT g.acquisition_scope, g.period_id, g.team_id, 'school'::VARCHAR AS node_kind,
           g.business_line, g.channel, g.first_channel, g.group_name,
           json_extract_string(s.value, '$.name') AS school_name, s.value AS node
    FROM groups g, json_each(g.group_node, '$.schools') s
)
SELECT {', '.join(fields)}
FROM expanded n
"""


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def university_channel_node_sources(table: str = UNIVERSITY_NODES_TABLE) -> dict[str, str]:
    """Return old-shaped group/school projections from the typed cache."""
    def source(node_kind: str, *, school: bool) -> str:
        columns = [
            "period_id AS 期间",
            "CASE team_id WHEN 'total' THEN '市场总计' "
            "WHEN 'virtual' THEN '线上虚拟人' WHEN 'online' THEN '线上团队' "
            "ELSE team_id END AS 管理单元",
            "CASE business_line WHEN 'training' THEN '语培' "
            "WHEN 'abroad' THEN '留学及小语种' ELSE business_line END AS 业务线",
            "channel AS 渠道", "first_channel AS 一级渠道", "group_name AS 业务组名称",
        ]
        if school:
            columns.append("school_name AS 学校名称")
        columns.append("acquisition_scope AS 语培统计范围")
        columns.extend(_quote(label) for label, _, _ in _WIDE_NUMERIC)
        columns.extend(_quote(label) for label, _, _ in _WIDE_TEXT)
        if not school:
            columns.append("CASE WHEN \"工单同比\" IS NULL THEN '无同期同比' ELSE '可比' END AS 同期状态")
        columns.append(_quote("渠道内现金占比"))
        return ("SELECT " + ", ".join(columns) + f" FROM {table} "
                "WHERE team_id='university' "
                f"AND node_kind='{node_kind}' "
                "AND acquisition_scope='{{ acquisition_scope }}'")

    return {"groups": source("group", school=False), "schools": source("school", school=True)}


def _scoped_source(sql: str, scope: str) -> str:
    """Fill the existing SQL template's one fixed acquisition-scope token."""
    return sql.replace("{{ acquisition_scope }}", scope)


def _insert_scope_sql(scope: str) -> str:
    ordinary = _scoped_source(channel_json_source(ORDINARY_UNITS), scope)
    university = _scoped_source(university_channel_json_source(), scope)
    return f"""
INSERT INTO {TABLE}
WITH generated AS MATERIALIZED (
    SELECT period_id, team_id, acquisition_scope, view
    FROM ({ordinary}) ordinary_channels
    UNION ALL
    SELECT period_id, team_id, acquisition_scope, view
    FROM ({university}) university_channels
), grid AS MATERIALIZED (
    SELECT '{scope}'::VARCHAR AS acquisition_scope,
           p.period_id,
           u.team_id,
           p.kind,
           p.start_date,
           u.unit_order
    FROM business.periods p
    CROSS JOIN (VALUES {_UNIT_VALUES}) AS u(team_id, unit_order)
), filled AS MATERIALIZED (
    SELECT g.acquisition_scope, g.period_id, g.team_id,
           g.kind, g.start_date, g.unit_order,
           COALESCE(d.view, '{{"channels":[]}}'::JSON) AS view_json
    FROM grid g
    LEFT JOIN generated d
      USING (acquisition_scope, period_id, team_id)
)
SELECT acquisition_scope,
       period_id,
       team_id,
       CAST(view_json AS VARCHAR) AS view,
       json_object('acquisition_scope', acquisition_scope,
                   'period_id', period_id,
                   'team_id', team_id,
                   'view', view_json) AS row_json
FROM filled
ORDER BY CASE kind WHEN 'year' THEN 0 WHEN 'quarter' THEN 1 ELSE 2 END,
         start_date,
         unit_order
"""


def install_native_channel_source(con):
    """Refresh the 3-scope × 17-period × 6-unit SQL-generated JSON source.

    University rows use the school-aware channel source so their tree retains
    attribute and school leaves. Other units use the ordinary channel source.
    The table keeps the old source column names, order, and types while storing
    channel JSON needed by the native tree templates. A typed university-only
    child table is expanded from that JSON once for the nested group and school
    HTML query.
    """
    con.execute("CREATE SCHEMA IF NOT EXISTS business")
    con.execute(f"DROP TABLE IF EXISTS {TABLE}")
    con.execute(f"""CREATE TABLE {TABLE} (
        acquisition_scope VARCHAR,
        period_id VARCHAR,
        team_id VARCHAR,
        view VARCHAR,
        row_json JSON
    )""")
    for scope in SCOPES:
        con.execute(_insert_scope_sql(scope))

    con.execute(f"DROP TABLE IF EXISTS {UNIVERSITY_NODES_TABLE}")
    numeric_columns = ",\n".join(f"{_quote(label)} DOUBLE" for label, _, _ in _WIDE_NUMERIC)
    text_columns = ",\n".join(f"{_quote(label)} VARCHAR" for label, _, _ in _WIDE_TEXT)
    con.execute(f"""CREATE TABLE {UNIVERSITY_NODES_TABLE} (
        acquisition_scope VARCHAR,
        period_id VARCHAR,
        team_id VARCHAR,
        node_kind VARCHAR,
        business_line VARCHAR,
        channel VARCHAR,
        first_channel VARCHAR,
        group_name VARCHAR,
        school_name VARCHAR,
        {numeric_columns},
        {text_columns},
        {_quote('渠道内现金占比')} DOUBLE
    )""")
    for scope in SCOPES:
        con.execute(_university_node_insert_sql(scope))
