"""Build SQL-native training facts from controlled-query result rows.

The input rows are already returned by the controlled read-only query boundary.
This module only loads those rows and static configuration into the derived
database passed by the caller; the per-row normalization runs in DuckDB views.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dashboard_product.fallback_mapping import RULES_PATH
from dashboard_product.management.platforms import _BRANDS


_TRAINING_COLUMNS = {
    "event_date": "VARCHAR",
    "team_id": "VARCHAR",
    "business_group": "VARCHAR",
    "first_channel": "VARCHAR",
    "second_channel": "VARCHAR",
    "campaign_name": "VARCHAR",
    "work_order_campaign_name": "VARCHAR",
    "_has_work_order_campaign_name": "BOOLEAN",
    "entry_person": "VARCHAR",
    "school_name": "VARCHAR",
    "school_attribute": "VARCHAR",
    "school_attribute_status": "VARCHAR",
    "channel_school_name": "VARCHAR",
    "grade_name": "VARCHAR",
    "metric": "VARCHAR",
    "actual_value": "VARCHAR",
    "student_id": "VARCHAR",
    "cash_channel": "VARCHAR",
    "work_order_active_type": "VARCHAR",
    "cash_campaign_name": "VARCHAR",
    "source_row_number": "VARCHAR",
    "work_order_id": "VARCHAR",
    "order_status": "VARCHAR",
    "source_record": "VARCHAR",
    "cash_source_record": "VARCHAR",
    "resource_entry_person": "VARCHAR",
    "resource_description": "VARCHAR",
    "acquisition_mode": "VARCHAR",
    "class_code": "VARCHAR",
    "registration_count": "VARCHAR",
}

_ORDER_COLUMNS = {
    "work_order_id": "VARCHAR",
    "source_team": "VARCHAR",
    "adviser": "VARCHAR",
    "follow_adviser": "VARCHAR",
    "first_channel": "VARCHAR",
    "second_channel": "VARCHAR",
    "source_channel": "VARCHAR",
    "campaign_name": "VARCHAR",
    "resource_entry_person": "VARCHAR",
    "resource_description": "VARCHAR",
    "order_status": "VARCHAR",
    "source_record": "VARCHAR",
}

_SCHOOL_COLUMNS = {
    "source_row_number": "VARCHAR",
    "school_name": "VARCHAR",
    "school_attribute": "VARCHAR",
}

_TEAM_IDS = {"offline_market", "online_private", "online_platform"}
_TEAM_GROUPS = {
    "青少": "留学预备",
    "初中": "留学预备",
    "留学预备": "留学预备",
    "高中": "高中",
    "大学": "大学",
}
_UNKNOWN_ORDER_TEAMS = {
    "塘沽", "大学", "无法判断", "校区资源无法归属", "武清", "留学预备", "需要判定", "高中",
}
_COUNTRY_PLACEHOLDERS = {"", "暂无归属", "未归类", "未细分", "渠道/顾问暂无法拆分", "暂时无法识别渠道", "自然无法判定"}
_UNIVERSITY_SCHOOLS = (
    "天津师范大学", "天津商业大学", "天津科技大学", "天津财经大学",
    "天津理工大学", "天津美术学院", "天津城建大学", "天津外国语大学",
    "天津大学", "天津工业大学", "南开大学", "河北工业大学",
)


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _many(con, sql: str, rows) -> None:
    values = list(rows)
    if values:
        con.executemany(sql, values)


def _insert_rows(con, table: str, columns: dict[str, str], rows: list[dict[str, Any]], *, extra: tuple[str, ...] = ()) -> None:
    names = list(columns)
    if extra:
        names.extend(extra)
    placeholders = ", ".join("?" for _ in names)
    quoted = ", ".join('"' + name + '"' for name in names)
    if not rows:
        return
    values = []
    for index, row in enumerate(rows, start=1):
        values.append(tuple(
            index if name == "_input_order" else
            ("work_order_campaign_name" in row if name == "_has_work_order_campaign_name" else
             _json_text(row.get(name)) if name in ("source_record", "cash_source_record") else
             (None if row.get(name) is None else str(row.get(name))) if name in columns and columns[name] == "VARCHAR" else
             row.get(name))
            for name in names
        ))
    con.executemany(f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})", values)


def _people_rows(people_config: dict[str, Any], abroad_people_config: dict[str, Any]):
    known: list[str] = []
    virtual: list[str] = []
    for team in people_config.get("teams", []):
        for group in team.get("groups", []):
            for person in group.get("members", []):
                name = _text(person.get("display_name"))
                if not name or person.get("status") in {"vacant", "departed", "transferred"}:
                    continue
                if name not in known:
                    known.append(name)
                if team.get("team_id") == "online_private" and name not in virtual:
                    virtual.append(name)
    offline: list[str] = []
    for person in abroad_people_config.get("people", []):
        name = _text(person.get("display_name"))
        if name and name not in offline:
            offline.append(name)
        if name and name not in known:
            known.append(name)
    return known, virtual, offline


def _mapping_rows(adviser_mapping: Any):
    if isinstance(adviser_mapping, dict) and isinstance(adviser_mapping.get("mappings"), list):
        pairs = ((item.get("source_adviser"), item.get("labeled_team"))
                 for item in adviser_mapping["mappings"] if isinstance(item, dict))
    else:
        pairs = (adviser_mapping or {}).items()
    result = []
    for source_adviser, labeled_team in pairs:
        source, team = _text(source_adviser), _text(labeled_team)
        if source and team:
            result.append((source, team))
    return result


def _create_config_tables(con, people_config, abroad_people_config, adviser_mapping, cash_team_overrides, school_rows):
    con.execute("CREATE SCHEMA IF NOT EXISTS config")
    con.execute("CREATE OR REPLACE TABLE config.training_people (ordinal BIGINT, name VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE config.training_virtual_people (ordinal BIGINT, name VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE config.training_offline_people (ordinal BIGINT, name VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE config.adviser_mapping (source_adviser VARCHAR, labeled_team VARCHAR)")
    con.execute("""CREATE OR REPLACE TABLE config.cash_team_overrides (
        ordinal BIGINT, work_order_id VARCHAR, event_date VARCHAR, amount VARCHAR, team_id VARCHAR, note VARCHAR
    )""")
    con.execute("""CREATE OR REPLACE TABLE config.cash_channel_rules (
        ordinal BIGINT, priority INTEGER,
        resource_1 VARCHAR, resource_1_wild BOOLEAN,
        resource_2 VARCHAR, resource_2_wild BOOLEAN,
        resource_3 VARCHAR, resource_3_wild BOOLEAN,
        second_channel VARCHAR, second_channel_wild BOOLEAN,
        activity_1 VARCHAR, activity_1_wild BOOLEAN,
        activity_2 VARCHAR, activity_2_wild BOOLEAN,
        mapped_first VARCHAR, mapped_second VARCHAR, mapped_active_type VARCHAR
    )""")
    con.execute("""CREATE OR REPLACE TABLE config.cash_campaign_overrides (
        ordinal BIGINT, contains_text VARCHAR, when_second_channel VARCHAR, replace_second_channel VARCHAR
    )""")
    con.execute("CREATE OR REPLACE TABLE config.training_platform_aliases (platform VARCHAR, alias VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE config.school_rows (source_row_number VARCHAR, school_name VARCHAR, school_attribute VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE config.university_schools (ordinal BIGINT, school_name VARCHAR)")

    known, virtual, offline = _people_rows(people_config, abroad_people_config)
    _many(con, "INSERT INTO config.training_people VALUES (?, ?)", [(i, n) for i, n in enumerate(known, 1)])
    _many(con, "INSERT INTO config.training_virtual_people VALUES (?, ?)", [(i, n) for i, n in enumerate(virtual, 1)])
    _many(con, "INSERT INTO config.training_offline_people VALUES (?, ?)", [(i, n) for i, n in enumerate(offline, 1)])
    _many(con, "INSERT INTO config.adviser_mapping VALUES (?, ?)", _mapping_rows(adviser_mapping))

    overrides = cash_team_overrides.get("overrides", []) if isinstance(cash_team_overrides, dict) else []
    _many(con, "INSERT INTO config.cash_team_overrides VALUES (?, ?, ?, ?, ?, ?)", [
        (i, _text(item.get("work_order_id")), _text(item.get("event_date"))[:10],
         _text(item.get("amount")), _text(item.get("team_id")), _text(item.get("note")))
        for i, item in enumerate(overrides, 1) if isinstance(item, dict)
    ])

    rules_path = Path(RULES_PATH)
    book = json.loads(rules_path.read_text(encoding="utf-8"))
    wildcards = {str(item).strip() for item in book.get("wildcards", [])}
    fields = (
        "资源描述1", "资源描述2", "资源描述3", "二级渠道", "市场活动1", "市场活动2",
    )
    _many(con, "INSERT INTO config.cash_channel_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (i, int(rule["优先级"]),
         *tuple(value for field in fields for value in (
             None if rule.get(field) is None else str(rule.get(field)),
             rule.get(field) is None or str(rule.get(field)).strip() in wildcards,
         )),
         str(rule["新_一级渠道"]), str(rule["新_二级渠道"]), str(rule["新_主被动"]))
        for i, rule in enumerate(book.get("rules", []), 1)
    ])
    _many(con, "INSERT INTO config.cash_campaign_overrides VALUES (?, ?, ?, ?)", [
        (i, str(item["contains"]), str(item["when_second_channel"]), str(item["replace_second_channel"]))
        for i, item in enumerate(book.get("campaign_overrides", []), 1)
    ])
    aliases = [(platform, alias) for platform, platform_aliases in _BRANDS for alias in platform_aliases]
    _many(con, "INSERT INTO config.training_platform_aliases VALUES (?, ?)", aliases)
    _many(con, "INSERT INTO config.school_rows VALUES (?, ?, ?)", [
        (_text(row.get("source_row_number")), _text(row.get("school_name")), _text(row.get("school_attribute")))
        for row in school_rows if isinstance(row, dict)
    ])
    _many(con, "INSERT INTO config.university_schools VALUES (?, ?)", [
        (i, school) for i, school in enumerate(_UNIVERSITY_SCHOOLS, 1)
    ])


def _create_input_tables(con, training_rows, order_rows):
    con.execute("CREATE SCHEMA IF NOT EXISTS source")
    training_defs = [f'"{name}" {sql_type}' for name, sql_type in _TRAINING_COLUMNS.items()]
    order_defs = [f'"{name}" {sql_type}' for name, sql_type in _ORDER_COLUMNS.items()]
    con.execute(f"CREATE OR REPLACE TABLE source.training_rows (_input_order BIGINT, {', '.join(training_defs)})")
    con.execute(f"CREATE OR REPLACE TABLE source.order_rows (_input_order BIGINT, {', '.join(order_defs)})")
    _insert_rows(con, "source.training_rows", _TRAINING_COLUMNS, training_rows, extra=("_input_order",))
    _insert_rows(con, "source.order_rows", _ORDER_COLUMNS, order_rows, extra=("_input_order",))


_NORMALIZE_SQL = r"""
CREATE OR REPLACE VIEW business._training_normalized AS
WITH training_scopes AS (
    SELECT *, FALSE AS personal_qualification FROM source.training_rows
    UNION ALL
    SELECT *, TRUE AS personal_qualification
    FROM source.training_rows
    WHERE acquisition_mode IS NULL OR TRIM(acquisition_mode) = '被动'
), orders_ranked AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY NULLIF(TRIM(work_order_id), '') ORDER BY _input_order DESC
    ) AS _rn
    FROM source.order_rows
), orders_by_id AS (
    SELECT NULLIF(TRIM(work_order_id), '') AS work_order_id,
           source_team, adviser, follow_adviser, first_channel, second_channel,
           source_channel, campaign_name, resource_entry_person, resource_description,
           order_status, source_record
    FROM orders_ranked
    WHERE _rn = 1 AND NULLIF(TRIM(work_order_id), '') IS NOT NULL
), order_advisers AS (
    SELECT o.work_order_id,
           CASE WHEN o.adviser IS NOT NULL AND o.adviser <> '' THEN TRIM(o.adviser)
                ELSE TRIM(COALESCE(o.follow_adviser, '')) END AS source_adviser,
           COALESCE(NULLIF(TRIM(o.source_team), ''), m.labeled_team, '') AS resolved_source_team
    FROM orders_by_id o
    LEFT JOIN config.adviser_mapping m
      ON m.source_adviser = CASE WHEN o.adviser IS NOT NULL AND o.adviser <> '' THEN TRIM(o.adviser)
                                 ELSE TRIM(COALESCE(o.follow_adviser, '')) END
), confirmed_abroad AS (
    SELECT work_order_id FROM order_advisers WHERE resolved_source_team = '留学'
), base AS (
    SELECT t.*, o.work_order_id AS _linked_order_id,
           o.source_team AS _source_team, o.adviser AS _adviser, o.follow_adviser AS _follow_adviser,
           o.first_channel AS _order_first_channel, o.second_channel AS _order_second_channel,
           o.source_channel AS _order_source_channel, o.campaign_name AS _order_campaign_name,
           o.resource_entry_person AS _order_resource_entry_person,
           o.resource_description AS _order_resource_description,
           o.order_status AS _order_status, o.source_record AS _order_source_record,
           oa.source_adviser AS _source_adviser, oa.resolved_source_team AS _resolved_source_team,
           CASE WHEN TRIM(t.metric) = 'work_orders' THEN 'orders'
                WHEN TRIM(t.metric) = 'passive_reported_cash' THEN 'cash' END AS normalized_metric,
           CASE TRIM(t.business_group)
                WHEN '青少' THEN '留学预备' WHEN '初中' THEN '留学预备'
                WHEN '留学预备' THEN '留学预备' WHEN '高中' THEN '高中' WHEN '大学' THEN '大学'
           END AS normalized_group,
           NULLIF(TRIM(t.work_order_id), '') AS normalized_work_order_id,
           NULLIF(TRIM(t.team_id), '') AS original_team_id,
           NULLIF(TRIM(t.source_row_number), '') AS normalized_source_row_number,
           CASE WHEN t._has_work_order_campaign_name THEN t.work_order_campaign_name
                ELSE t.campaign_name END AS initial_linked_campaign
    FROM training_scopes t
    LEFT JOIN orders_by_id o ON NULLIF(TRIM(t.work_order_id), '') = o.work_order_id
    LEFT JOIN order_advisers oa ON NULLIF(TRIM(t.work_order_id), '') = oa.work_order_id
    WHERE TRIM(t.metric) IN ('work_orders', 'passive_reported_cash')
), campaign_base AS (
    SELECT *,
           CASE WHEN NULLIF(TRIM(initial_linked_campaign), '') IS NOT NULL
                     AND TRIM(initial_linked_campaign) NOT IN ('是', '否', 'None', 'NULL')
                THEN TRIM(initial_linked_campaign)
                WHEN NULLIF(TRIM(cash_campaign_name), '') IS NOT NULL
                     AND TRIM(cash_campaign_name) NOT IN ('是', '否', 'None', 'NULL')
                THEN TRIM(cash_campaign_name) END AS initial_campaign,
           CASE WHEN cash_campaign_name IS NOT NULL AND cash_campaign_name <> ''
                THEN cash_campaign_name ELSE campaign_name END AS cash_fallback_campaign,
           CASE WHEN NULLIF(TRIM(_order_campaign_name), '') IS NOT NULL
                     AND TRIM(_order_campaign_name) NOT IN ('是', '否', 'None', 'NULL')
                THEN TRIM(_order_campaign_name) END AS valid_order_campaign
    FROM base
), cash_rule_matches AS (
    SELECT b.personal_qualification, b._input_order, r.ordinal AS rule_ordinal,
           r.priority, r.mapped_first, r.mapped_second, r.mapped_active_type
    FROM campaign_base b
    JOIN config.cash_channel_rules r ON b.normalized_metric = 'cash'
    WHERE NOT (r.resource_1_wild AND r.resource_2_wild AND r.resource_3_wild
               AND r.second_channel_wild AND r.activity_1_wild AND r.activity_2_wild)
      AND (r.resource_1_wild OR
           POSITION(LOWER(r.resource_1) IN LOWER(COALESCE(b.cash_channel, ''))) > 0 OR
           POSITION(LOWER(r.resource_1) IN LOWER(COALESCE(b.cash_fallback_campaign, ''))) > 0)
      AND (r.resource_2_wild OR POSITION(LOWER(r.resource_2) IN LOWER(COALESCE(b.cash_fallback_campaign, ''))) > 0)
      AND (r.resource_3_wild OR POSITION(LOWER(r.resource_3) IN LOWER(COALESCE(b.cash_fallback_campaign, ''))) > 0)
      AND (r.second_channel_wild OR
           POSITION(LOWER(r.second_channel) IN LOWER(COALESCE(b.second_channel, ''))) > 0 OR
           POSITION(LOWER(r.second_channel) IN LOWER(COALESCE(b.cash_fallback_campaign, ''))) > 0)
      AND (r.activity_1_wild OR POSITION(LOWER(r.activity_1) IN LOWER(COALESCE(b.cash_fallback_campaign, ''))) > 0)
      AND (r.activity_2_wild OR POSITION(LOWER(r.activity_2) IN LOWER(COALESCE(b.cash_fallback_campaign, ''))) > 0)
), cash_winners AS (
    SELECT * FROM cash_rule_matches
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY personal_qualification, _input_order ORDER BY priority, rule_ordinal
    ) = 1
), cash_initial AS (
    SELECT b.*,
           (NULLIF(TRIM(b.first_channel), '') IS NOT NULL
             AND TRIM(b.first_channel) NOT IN ('', '暂无归属', '未归类', '未细分',
                 '渠道/顾问暂无法拆分', '暂时无法识别渠道', '自然无法判定')
             AND NULLIF(TRIM(b.second_channel), '') IS NOT NULL
             AND TRIM(b.second_channel) NOT IN ('', '暂无归属', '未归类', '未细分',
                 '渠道/顾问暂无法拆分', '暂时无法识别渠道', '自然无法判定')) AS has_existing_combo,
           w.priority AS winning_priority, w.mapped_first, w.mapped_second, w.mapped_active_type,
           (w.rule_ordinal IS NOT NULL AND TRIM(COALESCE(b.work_order_active_type, '')) = '被动'
              AND TRIM(COALESCE(w.mapped_active_type, '')) = '主动') AS active_conflict
    FROM campaign_base b
    LEFT JOIN cash_winners w
      ON b.personal_qualification = w.personal_qualification AND b._input_order = w._input_order
), cash_override_matches AS (
    SELECT c.personal_qualification, c._input_order, o.ordinal AS override_ordinal,
           o.replace_second_channel
    FROM cash_initial c
    JOIN config.cash_campaign_overrides o
      ON POSITION(LOWER(o.contains_text) IN LOWER(COALESCE(c.cash_fallback_campaign, ''))) > 0
     AND c.mapped_second = o.when_second_channel
    WHERE c.winning_priority IS NOT NULL AND NOT c.has_existing_combo AND NOT c.active_conflict
), cash_override_winners AS (
    SELECT * FROM cash_override_matches
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY personal_qualification, _input_order ORDER BY override_ordinal
    ) = 1
), cash_team_override_matches AS (
    SELECT c.personal_qualification, c._input_order, o.ordinal AS override_ordinal,
           o.team_id, o.note
    FROM cash_initial c
    JOIN config.cash_team_overrides o
      ON o.work_order_id = COALESCE(NULLIF(TRIM(c.work_order_id), ''), '')
     AND o.event_date = SUBSTRING(COALESCE(c.event_date, ''), 1, 10)
     AND TRY_CAST(o.amount AS DECIMAL(38, 2)) = TRY_CAST(c.actual_value AS DECIMAL(38, 2))
     AND o.team_id IN ('offline_market', 'online_private', 'online_platform')
), cash_team_override_winners AS (
    SELECT * FROM cash_team_override_matches
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY personal_qualification, _input_order ORDER BY override_ordinal
    ) = 1
), cash_resolved AS (
    SELECT c.*,
           CASE WHEN c.active_conflict THEN '自然无法判定'
                WHEN c.has_existing_combo THEN TRIM(c.first_channel)
                WHEN c.winning_priority IS NOT NULL THEN c.mapped_first
                ELSE '暂时无法识别渠道' END AS resolved_first_channel,
           CASE WHEN c.active_conflict THEN '自然无法判定'
                WHEN c.has_existing_combo THEN TRIM(c.second_channel)
                WHEN c.winning_priority IS NOT NULL THEN COALESCE(co.replace_second_channel, c.mapped_second)
                ELSE '暂时无法识别渠道' END AS resolved_second_channel,
           CASE WHEN c.active_conflict THEN '自然无法判定'
                WHEN c.has_existing_combo THEN COALESCE(NULLIF(TRIM(c.work_order_active_type), ''), c.mapped_active_type)
                WHEN c.winning_priority IS NOT NULL THEN c.mapped_active_type END AS resolved_active_type,
           tco.team_id AS cash_override_team,
           tco.note AS cash_override_note
    FROM cash_initial c
    LEFT JOIN cash_override_winners co
      ON c.personal_qualification = co.personal_qualification AND c._input_order = co._input_order
    LEFT JOIN cash_team_override_winners tco
      ON c.personal_qualification = tco.personal_qualification AND c._input_order = tco._input_order
), channels AS (
    SELECT *,
           CASE WHEN normalized_metric = 'cash' THEN resolved_first_channel ELSE first_channel END AS fact_first_channel,
           CASE WHEN normalized_metric = 'cash' THEN resolved_second_channel ELSE second_channel END AS fact_second_channel,
           (LOWER(COALESCE(cash_channel, '')) LIKE '%tmk%') AS cash_channel_is_tmk,
           (LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%线上%' OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%在线%'
             OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%官网%' OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%小程序%') AS campaign_online,
           (LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%线下%' OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%校代%'
             OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%地推%' OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%会销%'
             OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%展会%' OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%讲座%'
             OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%路展%' OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%校园%'
             OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%高招%' OR LOWER(COALESCE(cash_fallback_campaign, '')) LIKE '%中招%') AS campaign_offline
    FROM cash_resolved
), inferred AS (
    SELECT *,
        CASE WHEN TRIM(COALESCE(fact_first_channel, '')) = 'TMK激活-平台' THEN 'online_platform'
             WHEN normalized_metric = 'cash'
               AND (original_team_id IS NULL OR cash_channel_is_tmk) THEN
                CASE WHEN cash_channel_is_tmk OR STARTS_WITH(TRIM(COALESCE(fact_first_channel, '')), 'TMK激活') THEN 'offline_market'
                     WHEN active_conflict THEN original_team_id
                     WHEN TRIM(COALESCE(fact_second_channel, '')) = '虚拟人'
                       OR POSITION('虚拟人' IN COALESCE(cash_fallback_campaign, '')) > 0
                       OR POSITION('私域' IN COALESCE(cash_fallback_campaign, '')) > 0 THEN 'online_private'
                     WHEN original_team_id IN ('offline_market', 'online_private', 'online_platform') THEN original_team_id
                     WHEN TRIM(COALESCE(fact_second_channel, '')) = '线上讲座' THEN 'online_platform'
                     WHEN TRIM(COALESCE(fact_second_channel, '')) IN ('线下讲座', '线下校代') THEN 'offline_market'
                     WHEN campaign_online AND campaign_offline THEN NULL
                     WHEN campaign_online THEN 'online_platform'
                     WHEN campaign_offline THEN 'offline_market'
                     WHEN TRIM(COALESCE(fact_first_channel, '')) = '平台' THEN 'online_platform'
                     WHEN TRIM(COALESCE(fact_first_channel, '')) IN ('市场活动', 'TMK激活-市场活动', 'TMK激活') THEN 'offline_market'
                     WHEN TRIM(COALESCE(fact_first_channel, '')) = '新东方官网' THEN 'online_platform'
                END
             ELSE original_team_id END AS inferred_team_id
    FROM channels
), inferred_flags AS (
    SELECT *,
       CASE WHEN TRIM(COALESCE(fact_first_channel, '')) = 'TMK激活-平台'
            THEN original_team_id IS DISTINCT FROM 'online_platform'
            WHEN normalized_metric = 'cash' AND (original_team_id IS NULL OR cash_channel_is_tmk)
            THEN inferred_team_id IS DISTINCT FROM original_team_id
            ELSE FALSE END AS team_inferred_initial
    FROM inferred
), brand_counts AS (
    SELECT i.personal_qualification, i._input_order,
           COUNT(DISTINCT a.platform) AS brand_count,
           BOOL_OR(a.platform = '腾讯广告') AS has_tencent_ads,
           BOOL_OR(a.platform = '微信') AS has_wechat
    FROM inferred_flags i
    LEFT JOIN config.training_platform_aliases a
      ON POSITION(LOWER(a.alias) IN LOWER(TRIM(COALESCE(i._order_source_channel, '')))) > 0
    GROUP BY i.personal_qualification, i._input_order
), confirmed_teams AS (
    SELECT i.personal_qualification, i._input_order,
           CASE WHEN TRIM(COALESCE(i._order_first_channel, '')) = '市场活动'
                  AND TRIM(COALESCE(i._order_second_channel, '')) = '大学媒体投放'
                  AND TRIM(COALESCE(i._order_source_channel, '')) = '虚拟人' THEN 'online_private'
                WHEN TRIM(COALESCE(i._order_first_channel, '')) = '市场活动'
                  AND TRIM(COALESCE(i._order_second_channel, '')) = '大学媒体投放'
                  AND (bc.brand_count = 1 OR (bc.brand_count = 2 AND bc.has_tencent_ads AND bc.has_wechat))
                  THEN 'online_platform'
                WHEN TRIM(COALESCE(i._order_first_channel, '')) = '市场活动'
                  AND TRIM(COALESCE(i._order_second_channel, '')) = '异业渠道'
                  AND TRIM(COALESCE(i._order_source_channel, '')) = '全媒体平台（其他）'
                  AND POSITION('抖音咨询-线上渠道推荐' IN COALESCE(i._order_campaign_name, '')) > 0
                  THEN 'online_platform'
           END AS confirmed_team_id,
           CASE WHEN TRIM(COALESCE(i._order_first_channel, '')) = '市场活动'
                  AND TRIM(COALESCE(i._order_second_channel, '')) = '大学媒体投放'
                  AND TRIM(COALESCE(i._order_source_channel, '')) = '虚拟人'
                  THEN '经核实原渠道为虚拟人（市场活动→大学媒体投放）'
                WHEN TRIM(COALESCE(i._order_first_channel, '')) = '市场活动'
                  AND TRIM(COALESCE(i._order_second_channel, '')) = '大学媒体投放'
                  AND (bc.brand_count = 1 OR (bc.brand_count = 2 AND bc.has_tencent_ads AND bc.has_wechat))
                  THEN '经核实直接线上投放（市场活动→大学媒体投放，原渠道：' || TRIM(i._order_source_channel) || '）'
                WHEN TRIM(COALESCE(i._order_first_channel, '')) = '市场活动'
                  AND TRIM(COALESCE(i._order_second_channel, '')) = '异业渠道'
                  AND TRIM(COALESCE(i._order_source_channel, '')) = '全媒体平台（其他）'
                  AND POSITION('抖音咨询-线上渠道推荐' IN COALESCE(i._order_campaign_name, '')) > 0
                  THEN '经核实抖音咨询-线上渠道推荐（市场活动→异业渠道，全媒体平台）'
           END AS confirmed_team_reason
    FROM inferred_flags i
    LEFT JOIN brand_counts bc USING (personal_qualification, _input_order)
), overridden AS (
    SELECT i.*,
           CASE WHEN i.cash_override_team IS NOT NULL
                  AND NOT (TRIM(COALESCE(i.first_channel, '')) = 'TMK激活-平台'
                           OR TRIM(COALESCE(i.fact_first_channel, '')) = 'TMK激活-平台')
                THEN i.cash_override_team END AS applied_cash_override_team,
           CASE WHEN i.cash_override_team IS NOT NULL
                  AND NOT (TRIM(COALESCE(i.first_channel, '')) = 'TMK激活-平台'
                           OR TRIM(COALESCE(i.fact_first_channel, '')) = 'TMK激活-平台')
                THEN i.inferred_team_id END AS cash_override_before_team,
           CASE WHEN i.cash_override_team IS NOT NULL
                  AND NOT (TRIM(COALESCE(i.first_channel, '')) = 'TMK激活-平台'
                           OR TRIM(COALESCE(i.fact_first_channel, '')) = 'TMK激活-平台')
                THEN i.cash_override_note END AS applied_cash_override_note
    FROM inferred_flags i
), with_confirmed AS (
    SELECT o.*, ct.confirmed_team_id, ct.confirmed_team_reason,
           CASE WHEN TRIM(COALESCE(o.first_channel, '')) = 'TMK激活-平台'
                  OR TRIM(COALESCE(o.fact_first_channel, '')) = 'TMK激活-平台' THEN 'online_platform'
                WHEN ct.confirmed_team_id IS NOT NULL
                  AND ct.confirmed_team_id IS DISTINCT FROM COALESCE(o.applied_cash_override_team, o.inferred_team_id)
                  THEN ct.confirmed_team_id
                ELSE COALESCE(o.applied_cash_override_team, o.inferred_team_id) END AS final_team_id,
           CASE WHEN TRIM(COALESCE(o.first_channel, '')) = 'TMK激活-平台'
                  OR TRIM(COALESCE(o.fact_first_channel, '')) = 'TMK激活-平台'
                THEN o.original_team_id IS DISTINCT FROM 'online_platform'
                WHEN ct.confirmed_team_id IS NOT NULL THEN FALSE
                ELSE o.team_inferred_initial END AS final_team_inferred,
           CASE WHEN ct.confirmed_team_id IS NOT NULL
                  AND ct.confirmed_team_id IS DISTINCT FROM COALESCE(o.applied_cash_override_team, o.inferred_team_id)
                THEN COALESCE(o.applied_cash_override_team, o.inferred_team_id)
                WHEN o.applied_cash_override_team IS NOT NULL THEN o.cash_override_before_team END AS team_before_override,
           CASE WHEN ct.confirmed_team_id IS NOT NULL
                  AND ct.confirmed_team_id IS DISTINCT FROM COALESCE(o.applied_cash_override_team, o.inferred_team_id)
                THEN ct.confirmed_team_reason
                WHEN o.applied_cash_override_team IS NOT NULL THEN NULLIF(TRIM(o.applied_cash_override_note), '') END AS team_override_reason,
           (o.applied_cash_override_team IS NOT NULL OR
              (ct.confirmed_team_id IS NOT NULL
               AND ct.confirmed_team_id IS DISTINCT FROM COALESCE(o.applied_cash_override_team, o.inferred_team_id))) AS has_team_override
    FROM overridden o
    LEFT JOIN confirmed_teams ct USING (personal_qualification, _input_order)
), eligible AS (
    SELECT *,
           CASE WHEN normalized_metric = 'orders' THEN 'training:order:' || normalized_work_order_id
                ELSE 'training:cash:' || normalized_source_row_number END AS fact_id,
           COALESCE(valid_order_campaign, initial_campaign) AS final_campaign,
           NULLIF(TRIM(CASE WHEN entry_person IS NOT NULL AND entry_person <> '' THEN entry_person
                            ELSE _order_resource_entry_person END), '') AS final_entry_person,
           NULLIF(TRIM(CASE WHEN order_status IS NOT NULL AND order_status <> '' THEN order_status
                            ELSE _order_status END), '') AS final_order_status,
           CASE WHEN normalized_metric = 'orders'
                THEN CASE WHEN source_record IS NOT NULL AND source_record <> '' THEN source_record ELSE _order_source_record END
                ELSE CASE WHEN cash_source_record IS NOT NULL AND cash_source_record <> '' THEN cash_source_record ELSE source_record END
           END AS chosen_source_record
    FROM with_confirmed
    WHERE (final_team_id IS NULL OR final_team_id IN ('offline_market', 'online_private', 'online_platform'))
      AND (normalized_metric <> 'orders' OR normalized_work_order_id IS NOT NULL)
      AND (normalized_metric <> 'cash' OR normalized_source_row_number IS NOT NULL)
      AND (normalized_metric <> 'orders' OR normalized_work_order_id NOT IN (SELECT work_order_id FROM confirmed_abroad))
      AND (normalized_metric <> 'orders' OR _linked_order_id IS NULL
           OR NULLIF(TRIM(_source_team), '') IS NOT NULL
           OR (personal_qualification AND _resolved_source_team = '留学预备'))
      AND (normalized_metric <> 'orders' OR personal_qualification OR NULLIF(TRIM(_source_team), '') IS NULL
           OR TRIM(_source_team) IN ('塘沽','大学','无法判断','校区资源无法归属','武清','留学预备','需要判定','高中'))
      AND (normalized_metric <> 'orders' OR _linked_order_id IS NOT NULL OR normalized_group IS NOT NULL)
), deduplicated AS (
    SELECT * FROM eligible
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY personal_qualification, fact_id ORDER BY _input_order
    ) = 1
), attribute_rows AS (
    SELECT source_row_number, school_name,
           CASE WHEN TRIM(school_attribute) IN ('本地大学', '本地其他大学') THEN '本地大学'
                WHEN TRIM(school_attribute) IN ('归巢大学', '国外大学') THEN TRIM(school_attribute)
                ELSE '毕业及其他' END AS school_attribute
    FROM config.school_rows
), school_by_id AS (
    SELECT source_row_number, school_attribute
    FROM attribute_rows
), school_by_name AS (
    SELECT TRIM(school_name) AS school_name, COUNT(DISTINCT school_attribute) AS category_count,
           MIN(school_attribute) AS school_attribute
    FROM attribute_rows
    WHERE TRIM(COALESCE(school_name, '')) <> ''
    GROUP BY TRIM(school_name)
), school_input AS (
    SELECT d.*, regexp_replace(REPLACE(REPLACE(COALESCE(d.school_name, ''), '（', '('), '）', ')'), '[[:space:]]+', '', 'g') AS normalized_school_name
    FROM deduplicated d
), school_enriched AS (
    SELECT d.*,
           CASE WHEN d.channel_school_name IS NOT NULL THEN d.channel_school_name
                ELSE uni.school_name END AS final_channel_school_name,
           CASE WHEN d.school_attribute IS NOT NULL THEN d.school_attribute
                WHEN uni.school_name IS NOT NULL THEN '大学*'
                WHEN d.normalized_metric = 'cash' THEN by_id.school_attribute
                WHEN by_name.category_count = 1 THEN by_name.school_attribute
                ELSE '毕业及其他' END AS final_school_attribute,
           CASE WHEN d.school_attribute_status IS NOT NULL THEN d.school_attribute_status
                WHEN uni.school_name IS NOT NULL THEN '重点大学名单'
                WHEN d.normalized_metric = 'cash' THEN CASE WHEN by_id.school_attribute IS NULL THEN '现金原行' ELSE '现金原行' END
                WHEN by_name.category_count = 1 THEN '学校唯一映射'
                WHEN by_name.category_count > 1 THEN '学校属性冲突'
                ELSE '学校属性未匹配' END AS final_school_attribute_status
    FROM school_input d
    LEFT JOIN LATERAL (
        SELECT s.school_name
        FROM config.university_schools s
        WHERE d.normalized_school_name = s.school_name
           OR (STARTS_WITH(d.normalized_school_name, s.school_name)
               AND POSITION('附属' IN SUBSTRING(d.normalized_school_name, LENGTH(s.school_name) + 1)) = 0
               AND POSITION('附中' IN SUBSTRING(d.normalized_school_name, LENGTH(s.school_name) + 1)) = 0
               AND POSITION('附小' IN SUBSTRING(d.normalized_school_name, LENGTH(s.school_name) + 1)) = 0
               AND POSITION('中学' IN SUBSTRING(d.normalized_school_name, LENGTH(s.school_name) + 1)) = 0
               AND POSITION('小学' IN SUBSTRING(d.normalized_school_name, LENGTH(s.school_name) + 1)) = 0
               AND POSITION('幼儿园' IN SUBSTRING(d.normalized_school_name, LENGTH(s.school_name) + 1)) = 0
               AND POSITION('学院' IN SUBSTRING(d.normalized_school_name, LENGTH(s.school_name) + 1)) = 0
               AND (POSITION('校区' IN SUBSTRING(d.normalized_school_name, LENGTH(s.school_name) + 1)) > 0
                    OR TRIM(BOTH '()·-—' FROM SUBSTRING(d.normalized_school_name, LENGTH(s.school_name) + 1)) IN ('八里台','津南','北洋园','卫津路','泰达')))
        ORDER BY s.ordinal LIMIT 1
    ) uni ON TRUE
    LEFT JOIN school_by_id by_id ON by_id.source_row_number = d.normalized_source_row_number
    LEFT JOIN school_by_name by_name ON by_name.school_name = TRIM(COALESCE(d.school_name, ''))
), owner_lists AS (
    SELECT s.*,
           (SELECT COALESCE(LIST(p.name ORDER BY p.ordinal) FILTER (WHERE
                s.final_campaign IS NOT NULL AND POSITION(p.name IN s.final_campaign) > 0
            ), []::VARCHAR[]) FROM config.training_people p
           ) AS campaign_owners,
           (SELECT COALESCE(LIST(p.name ORDER BY p.ordinal) FILTER (WHERE
                POSITION(p.name IN regexp_extract(COALESCE(s._order_resource_description, ''), '市场人员[[:space:]]*[:：][[:space:]]*([^[:space:],，;；]+)', 1)) > 0
            ), []::VARCHAR[]) FROM config.training_people p
           ) AS labeled_resource_owners,
           (SELECT COALESCE(LIST(p.name ORDER BY p.ordinal) FILTER (WHERE
                POSITION(p.name IN regexp_extract(COALESCE(s._order_resource_description, ''), '([^[:space:],，;；/]+)市场资源', 1)) > 0
            ), []::VARCHAR[]) FROM config.training_people p
           ) AS market_resource_owners,
           (SELECT COALESCE(LIST(p.name ORDER BY p.ordinal) FILTER (WHERE
                s.final_entry_person IS NOT NULL AND POSITION(p.name IN s.final_entry_person) > 0
            ), []::VARCHAR[]) FROM config.training_people p
           ) AS entry_owners,
           (SELECT COALESCE(LIST(p.name ORDER BY p.ordinal) FILTER (WHERE
                POSITION(p.name IN regexp_replace(COALESCE(s._order_resource_description, ''), '[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[^[:space:]]+', ' ', 'g')) > 0
            ), []::VARCHAR[]) FROM config.training_people p
           ) AS embedded_campaign_owners,
           (SELECT COALESCE(LIST(v.name ORDER BY v.ordinal) FILTER (WHERE
                POSITION(v.name IN COALESCE(s.campaign_name, '')) > 0
                OR POSITION(v.name IN COALESCE(s.work_order_campaign_name, '')) > 0
                OR POSITION(v.name IN COALESCE(s.cash_campaign_name, '')) > 0
                OR POSITION(v.name IN COALESCE(s._order_campaign_name, '')) > 0
                OR POSITION(v.name IN COALESCE(s.entry_person, '')) > 0
                OR POSITION(v.name IN COALESCE(s.resource_entry_person, '')) > 0
                OR POSITION(v.name IN COALESCE(s._order_resource_entry_person, '')) > 0
                OR POSITION(v.name IN COALESCE(s.resource_description, '')) > 0
                OR POSITION(v.name IN COALESCE(s._order_resource_description, '')) > 0
            ), []::VARCHAR[]) FROM config.training_virtual_people v
           ) AS virtual_owners
    FROM school_enriched s
), owners_selected AS (
    SELECT *,
           CASE WHEN campaign_owners <> []::VARCHAR[] THEN campaign_owners
                WHEN labeled_resource_owners <> []::VARCHAR[] THEN labeled_resource_owners
                WHEN market_resource_owners <> []::VARCHAR[] THEN market_resource_owners
                WHEN entry_owners <> []::VARCHAR[] THEN entry_owners
                ELSE embedded_campaign_owners
           END AS owners
    FROM owner_lists
), final_facts AS (
    SELECT personal_qualification, fact_id, normalized_metric AS metric, 'training' AS business_line,
           NULLIF(SUBSTRING(COALESCE(event_date, ''), 1, 10), '') AS event_date,
           CASE WHEN normalized_metric = 'orders'
                THEN CAST(TRUNC(TRY_CAST(actual_value AS DECIMAL(38, 6))) AS DECIMAL(24, 2))
                ELSE CAST(ROUND_EVEN(TRY_CAST(actual_value AS DECIMAL(38, 6)), 2) AS DECIMAL(24, 2))
           END AS value,
           normalized_work_order_id AS work_order_id,
           final_order_status AS order_status,
           normalized_metric <> 'orders' OR COALESCE(final_order_status NOT IN ('删除', '回收'), TRUE) AS counts_toward_completion,
           CASE WHEN normalized_metric = 'orders' AND final_order_status = '删除' THEN 'order_status_deleted'
                WHEN normalized_metric = 'orders' AND final_order_status = '回收' THEN 'order_status_recalled' END AS exclusion_reason,
           CASE WHEN chosen_source_record IS NULL OR chosen_source_record = '' THEN NULL
                WHEN JSON_VALID(chosen_source_record) THEN TRY_CAST(chosen_source_record AS JSON)
                ELSE TO_JSON(chosen_source_record) END AS source_record,
           NULLIF(TRIM(student_id), '') AS student_id,
           CASE WHEN final_team_id IN ('offline_market', 'online_private', 'online_platform') THEN final_team_id END AS team_id,
           normalized_group AS business_group,
           NULLIF(TRIM(business_group), '') AS comparison_group,
           NULLIF(TRIM(school_name), '') AS school_name,
           final_school_attribute AS school_attribute,
           final_school_attribute_status AS school_attribute_status,
           final_channel_school_name AS channel_school_name,
           NULLIF(TRIM(grade_name), '') AS grade_name,
           final_campaign AS campaign_name,
           fact_first_channel AS first_channel,
           fact_second_channel AS second_channel,
           NULL::VARCHAR AS country,
           NULL::VARCHAR AS line,
           owners,
           virtual_owners,
           TRY_CAST(normalized_source_row_number AS BIGINT) AS source_row_number,
           NULLIF(TRIM(acquisition_mode), '') AS acquisition_mode,
           NULLIF(TRIM(class_code), '') AS class_code,
           TRY_CAST(registration_count AS DOUBLE) AS registration_count,
           final_team_inferred AS team_inferred,
           team_before_override,
           team_override_reason,
           has_team_override
    FROM owners_selected
)
SELECT * FROM final_facts;

CREATE OR REPLACE VIEW business.training_facts AS
SELECT fact_id, metric, business_line, event_date, value, work_order_id,
       order_status, counts_toward_completion, exclusion_reason, source_record, student_id,
       team_id, business_group, comparison_group, school_name, school_attribute,
       school_attribute_status, channel_school_name, grade_name, campaign_name,
       first_channel, second_channel, country, line, owners, virtual_owners,
       source_row_number, acquisition_mode, class_code, registration_count, team_inferred,
       CASE WHEN has_team_override THEN team_before_override END AS team_before_override,
       CASE WHEN has_team_override THEN team_override_reason END AS team_override_reason
FROM business._training_normalized
WHERE NOT personal_qualification;

CREATE OR REPLACE VIEW business.training_personnel_facts AS
SELECT fact_id, metric, business_line, event_date, value, work_order_id,
       order_status, counts_toward_completion, exclusion_reason, source_record, student_id,
       team_id, business_group, comparison_group, school_name, school_attribute,
       school_attribute_status, channel_school_name, grade_name, campaign_name,
       first_channel, second_channel, country, line, owners, virtual_owners,
       source_row_number, acquisition_mode, class_code, registration_count, team_inferred,
       CASE WHEN has_team_override THEN team_before_override END AS team_before_override,
       CASE WHEN has_team_override THEN team_override_reason END AS team_override_reason
FROM business._training_normalized
WHERE personal_qualification;
"""


def install_training(
    con,
    training_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    people_config: dict[str, Any],
    abroad_people_config: dict[str, Any],
    adviser_mapping: Any,
    cash_team_overrides: Any = None,
    school_rows: list[dict[str, Any]] | None = None,
) -> None:
    """Load controlled-query result rows/config and install SQL-native views.

    ``training_personnel_facts`` applies the passive-row scope explicitly.
    Reported cash is not positivity-filtered: the legacy caller compares the raw
    metric token with ``cash``, while this query returns ``passive_reported_cash``,
    so it historically retains zero and negative cash rows. Rows without an
    acquisition mode are treated as already scoped by the caller.
    """
    con.execute("CREATE SCHEMA IF NOT EXISTS business")
    _create_input_tables(con, training_rows, order_rows)
    _create_config_tables(
        con, people_config, abroad_people_config, adviser_mapping,
        cash_team_overrides, school_rows or [],
    )
    con.execute(_NORMALIZE_SQL)
