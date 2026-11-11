"""SQL views that turn controlled study-abroad facts into management facts."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from data_acquisition.jobs.work_order_cleaning import (
    COUNTRY_LINE_FALLBACKS, EURASIA_PATH_MARK, WorkOrderReference,
    load_work_order_reference,
)
from dashboard_product.management.study_abroad_channels import DECISIONS_PATH, load_decisions


INPUT_VIEW = "business.abroad_source_rows"
GRADE_INPUT_VIEW = "business.abroad_grade_source_rows"
FACTS_VIEW = "business.abroad_facts"
DIAGNOSTICS_VIEW = "business.abroad_diagnostics"

# Aligned with the final SELECT of management/sql/study_abroad/facts.sql.
INPUT_COLUMNS = (
    "fact_type", "fact_id", "business_line", "event_date", "owner", "source_owner",
    "market_group", "segment_id", "team_eligible", "market_eligible", "personal_eligible",
    "roster_group", "roster_status", "resource_id", "contract_id", "customer_key",
    "gross_amount", "resource_status", "contract_status", "country", "stage",
    "first_channel", "second_channel", "third_channel", "channel_source", "campaign",
    "origin_sha256", "origin_filename", "origin_sheet", "origin_row_number",
    "resource_count", "personal_resource_count", "gross_signing_amount", "positive_signature",
)
_INPUT_TYPES = (
    "VARCHAR", "VARCHAR", "VARCHAR", "DATE", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR",
    "BOOLEAN", "BOOLEAN", "BOOLEAN", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR",
    "DECIMAL(38,2)", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR",
    "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "BIGINT",
    "BIGINT", "BIGINT", "DECIMAL(38,2)", "BOOLEAN",
)
_GRADE_COLUMNS = (
    "resource_id", "alternate_resource_id", "work_order_id", "grade_attr",
    "corrected_grade", "current_grade", "grade_name",
)
_GRADE_TYPES = ("VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR")
_UNKNOWN_COUNTRIES = ("其他", "其它", "未知", "无", "none", "null", "0", "1")
_COUNTRY_TAIL_RE = (
    r"(?i)(?:在读年级|推送方式|所在部门|来源渠道|推荐人|意向阶段|当前年级|所在学校|"
    r"学生学校|联系邮箱|电子邮箱|邮箱|联系电话|电话|转介绍人|咨询方式|工单备注|备注).*$"
)
_COUNTRY_LABEL_RE = r"^(?:意向国家(?:/地区|或地区)?|国家(?:/地区|或地区)?)\s*[:：]\s*"
_RESOURCE_ID_PREFIX_RE = r"(?i)^(资源\s*ID|ID)\s*[:：]\s*"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (date, datetime)):
        value = value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("留学SQL输入数值必须为有限值")
        return format(value, "f")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("留学SQL输入数值必须为有限值")
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _inline_view_sql(
    name: str, columns: tuple[str, ...], types: tuple[str, ...],
    rows: Iterable[Mapping[str, Any]], *, required: bool,
) -> str:
    records = list(rows)
    if not records:
        if required:
            raise ValueError("留学facts受控查询结果为空")
        projection = ", ".join(
            f"CAST(NULL AS {kind}) AS \"{column}\"" for column, kind in zip(columns, types)
        )
        return f"CREATE OR REPLACE VIEW {name} AS SELECT {projection} WHERE FALSE"
    values = []
    for number, row in enumerate(records, 1):
        if not isinstance(row, Mapping):
            raise TypeError(f"留学SQL原始行必须是映射：第{number}行")
        missing = [column for column in columns if column not in row]
        if missing:
            raise ValueError(f"留学SQL原始查询缺少字段：{', '.join(missing)}")
        values.append("(" + ", ".join(
            f"CAST({_literal(row[column])} AS {kind})" for column, kind in zip(columns, types)
        ) + ")")
    aliases = ", ".join(f'"c{i}"' for i in range(len(columns)))
    projection = ", ".join(
        f'CAST("c{i}" AS {kind}) AS "{column}"'
        for i, (column, kind) in enumerate(zip(columns, types))
    )
    return f"CREATE OR REPLACE VIEW {name} AS SELECT {projection} FROM (VALUES {', '.join(values)}) AS v({aliases})"


def _bridge_rules(bridge: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in bridge.get("normalization_rules", []):
        if (not isinstance(item, Mapping) or item.get("target_id") != "acquisition.channel"
                or item.get("status") != "confirmed"):
            continue
        params = item.get("parameters")
        if not isinstance(params, Mapping) or not isinstance(params.get("rule"), str):
            continue
        name = params["rule"]
        prior = result.get(name)
        if prior is not None and prior != dict(params):
            raise ValueError(f"留学Bridge规则冲突：{name}")
        result[name] = dict(params)
    return result


def _grade_policy(bridge: Mapping[str, Any], decisions: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        candidate["proposed_mapping_or_rule"]
        for candidate in decisions.get("candidates", [])
        if candidate.get("candidate_type") == "override" and candidate.get("status") == "confirmed"
    ]
    candidates.extend(
        item for item in bridge.get("overrides", []) if item.get("status") == "confirmed"
    )
    values = [
        item["value"] for item in candidates
        if isinstance(item, Mapping)
        and item.get("key") == "unresolved_market_activity_by_work_order_grade"
        and isinstance(item.get("value"), Mapping)
    ]
    if len(values) > 1 and any(value != values[0] for value in values[1:]):
        raise ValueError("留学市场活动年级归属规则存在冲突")
    return [dict(values[0])] if values else []


def build_abroad_config(
    *,
    bridge: Mapping[str, Any],
    reference: WorkOrderReference,
    decisions: Mapping[str, Any],
    country_line_fallbacks: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Parse fixed Bridge/reference rules into lookup rows; no facts are evaluated here."""
    exact: dict[tuple[str, str, str], tuple[str | None, str | None, str, str]] = {}

    def add_exact(raw: Any, first: Any, second: Any, status: str, rule: str) -> None:
        if not isinstance(raw, (list, tuple)) or len(raw) != 3:
            raise ValueError("留学渠道精确规则必须包含三级原始值")
        key = tuple(_text(value) for value in raw)
        target = (_text(first) or None, _text(second) or None, status, rule)
        if key in exact and exact[key] != target:
            raise ValueError(f"同一留学渠道三层组合存在冲突：{key}")
        exact[key] = target

    for candidate in decisions.get("candidates", []):
        if candidate.get("candidate_type") != "normalization_rule" or candidate.get("status") != "confirmed":
            continue
        rule = candidate.get("proposed_mapping_or_rule", {})
        params = rule.get("parameters", {})
        add_exact(
            params.get("match_values"), params.get("normalized_l1"), params.get("normalized_l2"),
            "confirmed_new_source", _text(candidate.get("candidate_id")) or "confirmed_new_source",
        )

    rules = _bridge_rules(bridge)
    for item in bridge.get("normalization_rules", []):
        if not isinstance(item, Mapping) or item.get("status") != "confirmed":
            continue
        params = item.get("parameters", {})
        if not isinstance(params, Mapping) or "match_values" not in params:
            continue
        name = _text(item.get("candidate_id")) or _text(params.get("rule")) or "confirmed_bridge_rule"
        add_exact(
            params["match_values"], params.get("normalized_l1"), params.get("normalized_l2"),
            "confirmed_new_source", name,
        )
    return {
        "channel_mappings": [
            {"raw_first_channel": key[0], "raw_second_channel": key[1], "raw_third_channel": key[2],
             "first_channel": value[0], "second_channel": value[1],
             "mapping_status": value[2], "mapping_rule": value[3]}
            for key, value in exact.items()
        ],
        "path_channels": [
            {"source_path": path, "source_third": third, "target_channel": channel}
            for (path, third), channel in reference.path_channel_to_corrected_channel.items()
        ],
        "channel_rules": rules,
        "country_lines": dict(reference.country_to_line),
        "country_line_fallbacks": dict(
            COUNTRY_LINE_FALLBACKS if country_line_fallbacks is None else country_line_fallbacks
        ),
        "grade_policy": _grade_policy(bridge, decisions),
    }


def load_abroad_config(*, workspace: Path, decision_path: Path = DECISIONS_PATH) -> dict[str, Any]:
    """Load the confirmed static inputs from the workspace and project config."""
    root = Path(workspace)
    bridge = json.loads((root / "Work/Bridge/reference.json").read_text(encoding="utf-8"))
    reference = load_work_order_reference(root / "Input/Reference/留学-FY26-资源表.xlsx")
    decisions = load_decisions(decision_path)
    if decisions.get("company_id") != bridge.get("company_id"):
        raise ValueError("留学渠道决定不属于当前客户")
    return build_abroad_config(bridge=bridge, reference=reference, decisions=decisions)


def _config_rows(config: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = config.get(key, [])
    if isinstance(value, Mapping):
        if key in {"country_lines", "country_line_fallbacks"}:
            return [{"country": name, "line": item} for name, item in value.items()]
        return [{"key": name, "value": item} for name, item in value.items()]
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise TypeError(f"留学SQL配置 {key} 必须是映射或映射列表")
    return [dict(row) for row in value]


def _static_view_sql(
    name: str, columns: tuple[str, ...], types: tuple[str, ...], rows: list[Mapping[str, Any]],
) -> str:
    return _inline_view_sql(name, columns, types, rows, required=False)


def _unique_config_rows(
    rows: list[dict[str, Any]], keys: tuple[str, ...], label: str,
) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(column) for column in keys)
        prior = unique.get(key)
        if prior is not None and prior != row:
            raise ValueError(f"留学SQL配置{label}存在冲突：{key}")
        unique[key] = row
    return list(unique.values())


def _install_config_views(con: Any, config: Mapping[str, Any]) -> None:
    rules = config.get("channel_rules", {})
    if not isinstance(rules, Mapping):
        raise TypeError("留学SQL配置 channel_rules 必须是映射")
    rule_rows: list[dict[str, Any]] = []
    for name, params in rules.items():
        if not isinstance(params, Mapping):
            continue
        if name == "online_root_alias":
            rule_rows.extend({"rule_name": name, "value1": value, "value2": None,
                              "target1": params.get("normalized_l1"), "target2": None}
                             for value in params.get("source_values", []))
        elif name == "newmedia_other_ssc":
            rule_rows.append({"rule_name": name, "value1": params.get("source_value"),
                              "value2": None, "target1": params.get("l1"), "target2": params.get("l2")})
        elif name == "newdongfang_l2_department":
            rule_rows.extend({"rule_name": name, "value1": value, "value2": None,
                              "target1": None, "target2": value}
                             for value in params.get("known_departments", []))
        elif name == "channel_partnership_l2":
            rule_rows.extend({"rule_name": name, "value1": key, "value2": None,
                              "target1": None, "target2": value}
                             for key, value in params.get("maps", {}).items())
        elif name == "campaign_personal_agent_cross":
            rule_rows.append({"rule_name": name, "value1": params.get("source_path"),
                              "value2": params.get("source_value"), "target1": params.get("l1"),
                              "target2": params.get("l2")})
        elif name == "campaign_l2_overlay":
            rule_rows.extend({"rule_name": "campaign_direct", "value1": key, "value2": None,
                              "target1": None, "target2": value}
                             for key, value in params.get("direct", {}).items())
            rule_rows.extend({"rule_name": "campaign_collapse", "value1": value, "value2": None,
                              "target1": None, "target2": "综合展"}
                             for value in params.get("collapse_to_综合展", []))
        elif name == "offline_other_roots_not_in_dashboard":
            rule_rows.extend({"rule_name": name, "value1": key, "value2": None,
                              "target1": value.get("l1"), "target2": value.get("l2")}
                             for key, value in params.get("maps", {}).items())

    channel_rows = _unique_config_rows(
        _config_rows(config, "channel_mappings"),
        ("raw_first_channel", "raw_second_channel", "raw_third_channel"), "渠道映射",
    )
    path_rows = _unique_config_rows(
        _config_rows(config, "path_channels"), ("source_path", "source_third"), "参考渠道",
    )
    country_rows = _unique_config_rows(
        _config_rows(config, "country_lines"), ("country",), "国家条线",
    )
    fallback_rows = _unique_config_rows(
        _config_rows(config, "country_line_fallbacks"), ("country",), "国家条线回退",
    )
    definitions = (
        ("business._abroad_channel_mappings",
         ("raw_first_channel", "raw_second_channel", "raw_third_channel", "first_channel",
          "second_channel", "mapping_status", "mapping_rule"),
         ("VARCHAR",) * 7, channel_rows),
        ("business._abroad_path_channels", ("source_path", "source_third", "target_channel"),
         ("VARCHAR",) * 3, path_rows),
        ("business._abroad_channel_rules", ("rule_name", "value1", "value2", "target1", "target2"),
         ("VARCHAR",) * 5, rule_rows),
        ("business._abroad_country_lines", ("country", "line"), ("VARCHAR",) * 2,
         country_rows),
        ("business._abroad_country_fallbacks", ("country", "line"), ("VARCHAR",) * 2,
         fallback_rows),
    )
    for name, columns, types, rows in definitions:
        con.execute(_static_view_sql(name, columns, types, rows))
    policies = config.get("grade_policy", [])
    policy = policies[0] if policies else None
    con.execute(_static_view_sql(
        "business._abroad_grade_policy", ("normalized_l1",), ("VARCHAR",),
        [{"normalized_l1": policy.get("normalized_l1")}] if policy else [],
    ))
    if "grade_rows" in config:
        con.execute(_static_view_sql(
            GRADE_INPUT_VIEW, _GRADE_COLUMNS, _GRADE_TYPES, config["grade_rows"],
        ))
    else:
        has_grade_input = con.execute("""
          SELECT COUNT(*) FROM information_schema.tables
          WHERE table_schema = 'business' AND table_name = 'abroad_grade_source_rows'
        """).fetchone()[0]
        if not has_grade_input:
            con.execute(_static_view_sql(
                GRADE_INPUT_VIEW, _GRADE_COLUMNS, _GRADE_TYPES, [],
            ))


_ENRICHED_SQL = (r"""
CREATE OR REPLACE VIEW business._abroad_enriched AS
WITH source AS (
  SELECT *,
    NULLIF(TRIM(COALESCE(resource_id, '')), '') AS resource_text,
    NULLIF(TRIM(COALESCE(owner, '')), '') AS owner_text,
    NULLIF(TRIM(COALESCE(source_owner, '')), '') AS source_owner_text,
    NULLIF(TRIM(COALESCE(first_channel, '')), '') AS raw_first,
    NULLIF(TRIM(COALESCE(second_channel, '')), '') AS raw_second,
    NULLIF(TRIM(COALESCE(third_channel, '')), '') AS raw_third,
    NULLIF(TRIM(COALESCE(segment_id, '')), '') AS source_segment,
    NULLIF(TRIM(COALESCE(country, '')), '') AS country_raw,
    ROW_NUMBER() OVER (PARTITION BY fact_id ORDER BY origin_row_number NULLS LAST) AS fact_row
  FROM business.abroad_source_rows
), normalized AS (
  SELECT *,
    NULLIF(REGEXP_REPLACE(
      REGEXP_REPLACE(resource_text, '__RESOURCE_ID_PREFIX__', ''),
      '\.0+$', ''), '') AS normalized_resource_id
  FROM source WHERE fact_row = 1
), latest_resources AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY COALESCE('resource:' || normalized_resource_id, 'fact:' || fact_id)
    ORDER BY event_date DESC NULLS LAST, origin_row_number ASC NULLS LAST
  ) AS resource_row
  FROM normalized WHERE fact_type = 'resource'
), signatures AS (
  SELECT *, 1 AS resource_row FROM normalized WHERE fact_type = 'signature'
), chosen AS (
  SELECT * FROM latest_resources WHERE resource_row = 1
  UNION ALL SELECT * FROM signatures
), country_parts AS (
  SELECT *,
    REGEXP_REPLACE(country_raw, '__COUNTRY_TAIL_RE__', '') AS country_without_tail,
    CASE WHEN raw_first IS NOT NULL AND raw_second IS NOT NULL
         THEN raw_first || '-' || raw_second ELSE COALESCE(raw_first, '') END AS raw_path
  FROM chosen
), country_candidates AS (
  SELECT *,
    TRIM(TRIM(REGEXP_EXTRACT(
      REGEXP_REPLACE(TRIM(country_without_tail), '__COUNTRY_LABEL_RE__', ''),
      '^([^,，、/]+)', 1), ' \t\r\n:：;；|·-')) AS country_candidate,
    COALESCE(LENGTH(REGEXP_REPLACE(
      TRIM(country_without_tail), '__COUNTRY_LABEL_RE__', '')) > 30, FALSE)
      OR REGEXP_MATCHES(COALESCE(country_raw, ''), '[@<>]') AS country_is_untrusted
  FROM country_parts
), initial_channel AS (
  SELECT c.*,
    m.first_channel AS explicit_first, m.second_channel AS explicit_second,
    m.mapping_status AS explicit_status, m.mapping_rule AS explicit_rule,
    COALESCE(alias.target1, c.raw_first) AS channel_root,
    special.target1 AS special_first, special.target2 AS special_second,
    pc.target_channel AS reference_channel,
    nd.target2 AS known_department, partnership.target2 AS partnership_channel,
    cross_rule.target1 AS campaign_cross_first, cross_rule.target2 AS campaign_cross_second,
    direct_rule.target2 AS campaign_direct_second, collapse_rule.target2 AS campaign_collapse_second,
    other_rule.target1 AS offline_other_first, other_rule.target2 AS offline_other_second
  FROM country_candidates c
  LEFT JOIN business._abroad_channel_mappings m
    ON COALESCE(c.raw_first, '') = COALESCE(m.raw_first_channel, '')
   AND COALESCE(c.raw_second, '') = COALESCE(m.raw_second_channel, '')
   AND COALESCE(c.raw_third, '') = COALESCE(m.raw_third_channel, '')
  LEFT JOIN business._abroad_channel_rules alias
    ON alias.rule_name = 'online_root_alias' AND alias.value1 = c.raw_first
  LEFT JOIN business._abroad_channel_rules special
    ON special.rule_name = 'newmedia_other_ssc'
   AND c.raw_first = '新媒体'
   AND c.raw_first || '-' || COALESCE(c.raw_second, '') = special.value1
  LEFT JOIN business._abroad_path_channels pc
    ON pc.source_path = COALESCE(alias.target1, c.raw_first) || '-' || COALESCE(c.raw_second, '')
   AND pc.source_third = COALESCE(c.raw_third, '')
  LEFT JOIN business._abroad_channel_rules nd
    ON nd.rule_name = 'newdongfang_l2_department' AND nd.value1 = c.raw_second
  LEFT JOIN business._abroad_channel_rules partnership
    ON partnership.rule_name = 'channel_partnership_l2' AND partnership.value1 = c.raw_third
  LEFT JOIN business._abroad_channel_rules cross_rule
    ON cross_rule.rule_name = 'campaign_personal_agent_cross'
   AND cross_rule.value1 = c.raw_first || '-' || COALESCE(c.raw_second, '')
   AND cross_rule.value2 = c.raw_third
  LEFT JOIN business._abroad_channel_rules direct_rule
    ON direct_rule.rule_name = 'campaign_direct' AND direct_rule.value1 = c.raw_third
  LEFT JOIN business._abroad_channel_rules collapse_rule
    ON collapse_rule.rule_name = 'campaign_collapse' AND collapse_rule.value1 = c.raw_third
  LEFT JOIN business._abroad_channel_rules other_rule
    ON other_rule.rule_name = 'offline_other_roots_not_in_dashboard'
   AND other_rule.value1 = c.raw_first
), channel_base AS (
  SELECT *,
    CASE
      WHEN explicit_status IS NOT NULL THEN explicit_first
      WHEN channel_root IN ('网络资源', '新媒体', '官方合作高校', '新东方学校推荐', '渠道合作')
        THEN channel_root
      WHEN channel_root = '市场活动' THEN COALESCE(campaign_cross_first, channel_root)
      WHEN offline_other_first IS NOT NULL THEN offline_other_first
    END AS mapped_first,
    CASE
      WHEN explicit_status IS NOT NULL THEN explicit_second
      WHEN channel_root IN ('网络资源', '新媒体')
        THEN COALESCE(special_second, CASE WHEN reference_channel = '其他' THEN 'SSC' ELSE reference_channel END)
      WHEN channel_root = '官方合作高校' THEN channel_root
      WHEN channel_root = '新东方学校推荐' THEN COALESCE(known_department, '其他推荐')
      WHEN channel_root = '渠道合作' THEN partnership_channel
      WHEN channel_root = '市场活动'
        THEN COALESCE(campaign_cross_second, campaign_direct_second,
          CASE WHEN campaign_collapse_second IS NOT NULL
                 OR raw_second IN ('综合展', '现场注册', '部门展') THEN '综合展' END)
      WHEN offline_other_first IS NOT NULL THEN offline_other_second
    END AS mapped_second,
    CASE
      WHEN explicit_status IS NOT NULL THEN explicit_status
      WHEN channel_root IN ('网络资源', '新媒体')
        THEN CASE WHEN special_second IS NOT NULL OR reference_channel IS NOT NULL
                  THEN 'matched_existing' ELSE 'unresolved' END
      WHEN channel_root IN ('官方合作高校', '新东方学校推荐') THEN 'matched_existing'
      WHEN channel_root = '渠道合作'
        THEN CASE WHEN partnership_channel IS NULL THEN 'unresolved' ELSE 'matched_existing' END
      WHEN channel_root = '市场活动'
        THEN CASE WHEN campaign_cross_second IS NOT NULL OR campaign_direct_second IS NOT NULL
                       OR campaign_collapse_second IS NOT NULL
                       OR raw_second IN ('综合展', '现场注册', '部门展')
                  THEN 'matched_existing' ELSE 'unresolved' END
      ELSE 'outside_legacy_scope'
    END AS mapped_status,
    CASE
      WHEN explicit_status IS NOT NULL THEN explicit_rule
      WHEN channel_root IN ('网络资源', '新媒体') AND special_second IS NOT NULL THEN 'newmedia_other_ssc'
      WHEN channel_root IN ('网络资源', '新媒体') AND reference_channel IS NOT NULL THEN 'online_reference_exact'
      WHEN channel_root IN ('网络资源', '新媒体') THEN 'online_reference_unmatched'
      WHEN channel_root = '官方合作高校' THEN 'official_university_same_name'
      WHEN channel_root = '新东方学校推荐' THEN 'newdongfang_l2_department'
      WHEN channel_root = '渠道合作' AND partnership_channel IS NOT NULL THEN 'channel_partnership_l2'
      WHEN channel_root = '渠道合作' THEN 'channel_partnership_unmatched'
      WHEN channel_root = '市场活动' AND campaign_cross_second IS NOT NULL THEN 'campaign_personal_agent_cross'
      WHEN channel_root = '市场活动' AND campaign_direct_second IS NOT NULL THEN 'campaign_l2_overlay'
      WHEN channel_root = '市场活动' AND (campaign_collapse_second IS NOT NULL
        OR raw_second IN ('综合展', '现场注册', '部门展')) THEN 'campaign_l2_overlay'
      WHEN channel_root = '市场活动' THEN 'campaign_l2_unmatched'
      WHEN offline_other_first IS NOT NULL THEN 'offline_other_roots_not_in_dashboard'
      ELSE 'legacy_root_not_covered'
    END AS mapped_rule
  FROM initial_channel
), grade_field_rows AS (
  SELECT g.*, field_text,
    LOWER(REGEXP_REPLACE(COALESCE(field_text, ''), '\s+', '', 'g')) AS normalized_grade
  FROM business.abroad_grade_source_rows g
  CROSS JOIN UNNEST([g.grade_attr, g.corrected_grade, g.current_grade, g.grade_name]) AS grade_fields(field_text)
), grade_keys AS (
  SELECT resource_id,
    REGEXP_REPLACE(REGEXP_REPLACE(TRIM(COALESCE(resource_id, '')),
      '(?i)^(资源\s*ID|ID)\s*[:：]\s*', ''), '\.0+$', '') AS normalized_id,
    normalized_grade
  FROM grade_field_rows
  UNION ALL
  SELECT alternate_resource_id,
    REGEXP_REPLACE(REGEXP_REPLACE(TRIM(COALESCE(alternate_resource_id, '')),
      '(?i)^(资源\s*ID|ID)\s*[:：]\s*', ''), '\.0+$', ''),
    normalized_grade
  FROM grade_field_rows
), grade_stages AS (
  SELECT normalized_id,
    BOOL_OR(NOT (
        CONTAINS(normalized_grade, '大学以下') OR CONTAINS(normalized_grade, '小学')
        OR CONTAINS(normalized_grade, '青少') OR CONTAINS(normalized_grade, '学龄前')
        OR CONTAINS(normalized_grade, '未确认') OR CONTAINS(normalized_grade, '待确认')
        OR normalized_grade IN ('未知', '未归类', '不详', '其他', '其它', 'none', 'null', 'nan', 'n/a', '无')
      ) AND (
        CONTAINS(normalized_grade, '本科') OR CONTAINS(normalized_grade, '大专')
        OR CONTAINS(normalized_grade, '研究生') OR CONTAINS(normalized_grade, '硕士')
        OR CONTAINS(normalized_grade, '博士') OR CONTAINS(normalized_grade, '高校')
        OR CONTAINS(normalized_grade, '大学') OR REGEXP_MATCHES(normalized_grade, '大[一二三四五]')
      )) AS has_college,
    BOOL_OR(NOT (
        CONTAINS(normalized_grade, '大学以下') OR CONTAINS(normalized_grade, '小学')
        OR CONTAINS(normalized_grade, '青少') OR CONTAINS(normalized_grade, '学龄前')
        OR CONTAINS(normalized_grade, '未确认') OR CONTAINS(normalized_grade, '待确认')
        OR normalized_grade IN ('未知', '未归类', '不详', '其他', '其它', 'none', 'null', 'nan', 'n/a', '无')
      ) AND (
        CONTAINS(normalized_grade, '初中') OR CONTAINS(normalized_grade, '初一')
        OR CONTAINS(normalized_grade, '初二') OR CONTAINS(normalized_grade, '初三')
        OR CONTAINS(normalized_grade, '高中') OR CONTAINS(normalized_grade, '高一')
        OR CONTAINS(normalized_grade, '高二') OR CONTAINS(normalized_grade, '高三')
        OR CONTAINS(normalized_grade, '中学')
        OR REGEXP_MATCHES(normalized_grade, '(^|[^0-9])(?:[7-9]|1[0-2])年级')
      )) AS has_middle
  FROM grade_keys
  WHERE normalized_id <> ''
    AND REGEXP_FULL_MATCH(normalized_id, '[0-9]+')
  GROUP BY normalized_id
), grade_channels AS (
  SELECT normalized_id,
    CASE WHEN has_college AND has_middle THEN NULL
         WHEN has_college THEN '高校活动'
         WHEN has_middle THEN '中学活动' END AS grade_channel,
    CASE WHEN has_college AND has_middle THEN 'grade_conflict'
         WHEN has_college OR has_middle THEN 'resolved'
         ELSE 'grade_missing' END AS grade_status
  FROM grade_stages
), resolved AS (
  SELECT b.*,
    CASE WHEN b.mapped_first = g.normalized_l1 AND b.mapped_second IS NULL
              AND gc.grade_channel IS NOT NULL
         THEN g.normalized_l1 ELSE b.mapped_first END AS final_first,
    CASE WHEN b.mapped_first = g.normalized_l1 AND b.mapped_second IS NULL
              AND gc.grade_channel IS NOT NULL
         THEN gc.grade_channel ELSE b.mapped_second END AS final_second,
    CASE WHEN b.mapped_first = g.normalized_l1 AND b.mapped_second IS NULL
              AND gc.grade_channel IS NOT NULL
         THEN 'confirmed_new_source' ELSE b.mapped_status END AS final_status,
    CASE WHEN b.mapped_first = g.normalized_l1 AND b.mapped_second IS NULL
              AND gc.grade_channel IS NOT NULL
         THEN 'work_order_grade_school_activity'
         WHEN b.mapped_first = g.normalized_l1 AND b.mapped_second IS NULL
              AND gc.grade_status = 'grade_conflict' THEN 'market_activity_grade_conflict'
         WHEN b.mapped_first = g.normalized_l1 AND b.mapped_second IS NULL
              AND gc.grade_status = 'grade_missing' THEN 'market_activity_grade_missing'
         ELSE b.mapped_rule END AS final_rule,
    gc.grade_status
  FROM channel_base b
  LEFT JOIN grade_channels gc ON gc.normalized_id = b.normalized_resource_id
  LEFT JOIN business._abroad_grade_policy g ON TRUE
), segmented AS (
  SELECT *,
    CASE
      WHEN source_segment IN ('study_abroad_offline', 'study_abroad_online')
        AND (final_second = '虚拟人' OR raw_second = '虚拟人' OR raw_third = '虚拟人')
        THEN 'study_abroad_virtual'
      WHEN source_segment IN ('study_abroad_offline', 'study_abroad_online')
        AND (final_second = 'SSC' OR raw_second = '欧亚总部在线') THEN 'ssc'
      WHEN source_segment IN ('study_abroad_offline', 'study_abroad_online')
        AND (final_first IN ('网络资源', 'TMK激活-平台')
          OR raw_first IN ('网络资源', '线上运营', '网络', 'TMK激活-平台'))
        THEN 'study_abroad_online'
      ELSE source_segment
    END AS final_segment
  FROM resolved
), cleaned AS (
  SELECT *,
    CASE WHEN country_is_untrusted OR LOWER(country_candidate) IN ('__UNKNOWN_COUNTRIES__')
         THEN NULL ELSE NULLIF(country_candidate, '') END AS safe_country,
    CASE WHEN owner_text IS NULL OR NOT COALESCE(personal_eligible, FALSE)
              OR final_segment = 'international_market' THEN []::VARCHAR[]
         ELSE [owner_text] END AS fact_owners,
    fact_type = 'resource' AS is_resource,
    CASE WHEN fact_type = 'resource'
         THEN COALESCE(resource_status, '') NOT IN ('删除', '回收') ELSE TRUE END AS completion,
    CASE WHEN fact_type = 'resource' THEN 1::DECIMAL(38,2)
         WHEN COALESCE(positive_signature, FALSE) AND gross_signing_amount > 0
           THEN CAST(gross_signing_amount AS DECIMAL(38,2)) END AS fact_value,
    CASE WHEN final_segment IN ('study_abroad_online', 'study_abroad_virtual') THEN 'online'
         WHEN final_segment = 'study_abroad_offline' THEN 'offline'
         ELSE 'supplemental' END AS acquisition_mode,
    CASE final_segment WHEN 'study_abroad_online' THEN 'online_platform'
      WHEN 'study_abroad_offline' THEN 'offline_market'
      WHEN 'study_abroad_virtual' THEN 'online_private' END AS team_id
  FROM segmented
), line_counts AS (
  SELECT c.*,
    CASE WHEN STRPOS(raw_path, '__EURASIA_MARK__') > 0 THEN '欧亚条线'
      WHEN country_counts.line_count = 1 THEN country_counts.line
      WHEN country_counts.line_count = 0 AND fallback_counts.line_count = 1 THEN fallback_counts.line
    END AS line
  FROM cleaned c
  LEFT JOIN LATERAL (
    SELECT COUNT(DISTINCT line) AS line_count, MIN(line) AS line
    FROM business._abroad_country_lines WHERE country = c.safe_country
  ) country_counts ON TRUE
  LEFT JOIN LATERAL (
    SELECT COUNT(DISTINCT line) AS line_count, MIN(line) AS line
    FROM business._abroad_country_fallbacks WHERE country = c.safe_country
  ) fallback_counts ON TRUE
)
SELECT * FROM line_counts
""".replace("__RESOURCE_ID_PREFIX__", _RESOURCE_ID_PREFIX_RE)
    .replace("__COUNTRY_TAIL_RE__", _COUNTRY_TAIL_RE)
    .replace("__COUNTRY_LABEL_RE__", _COUNTRY_LABEL_RE)
    .replace("__UNKNOWN_COUNTRIES__", "','".join(_UNKNOWN_COUNTRIES))
    .replace("__EURASIA_MARK__", EURASIA_PATH_MARK))


def _create_output_views(con: Any) -> None:
    con.execute(_ENRICHED_SQL)
    con.execute("""
CREATE OR REPLACE VIEW business.abroad_facts AS
SELECT
  'abroad-source:' || fact_id AS fact_id,
  CASE WHEN is_resource THEN 'orders' ELSE 'cash' END AS metric,
  'abroad' AS business_line,
  event_date,
  fact_value AS value,
  NULL::VARCHAR AS work_order_id,
  CASE WHEN is_resource THEN NULLIF(TRIM(COALESCE(resource_status, '')), '') END AS order_status,
  completion AS counts_toward_completion,
  CASE WHEN is_resource AND resource_status = '删除' THEN 'resource_status_deleted'
       WHEN is_resource AND resource_status = '回收' THEN 'resource_status_recalled' END AS exclusion_reason,
  NULL::VARCHAR AS source_record,
  NULLIF(TRIM(COALESCE(customer_key, '')), '') AS student_id,
  team_id,
  NULLIF(TRIM(COALESCE(roster_group, '')), '') AS business_group,
  NULL::VARCHAR AS school_name,
  NULL::VARCHAR AS grade_name,
  NULLIF(TRIM(COALESCE(campaign, '')), '') AS campaign_name,
  COALESCE(final_first, '渠道待确认') AS first_channel,
  COALESCE(final_second, '渠道待确认') AS second_channel,
  raw_third AS third_channel,
  raw_first AS raw_first_channel,
  raw_second AS raw_second_channel,
  NULLIF(TRIM(COALESCE(channel_source, '')), '') AS channel_source,
  final_status AS channel_mapping_status,
  final_rule AS channel_mapping_rule,
  safe_country AS country,
  line,
  fact_owners AS owners,
  []::VARCHAR[] AS virtual_owners,
  origin_row_number AS source_row_number,
  origin_sha256 AS source_sha256,
  NULLIF(TRIM(COALESCE(origin_sheet, '')), '') AS source_sheet,
  NULLIF(TRIM(COALESCE(origin_filename, '')), '') AS source_filename,
  source_owner_text AS source_owner,
  owner_text AS owner,
  business_line AS source_product,
  business_line AS customer_domain,
  normalized_resource_id AS resource_id,
  NULLIF(TRIM(COALESCE(contract_id, '')), '') AS contract_id,
  NULLIF(TRIM(COALESCE(customer_key, '')), '') AS customer_key,
  NULLIF(TRIM(COALESCE(resource_status, '')), '') AS resource_status,
  NULLIF(TRIM(COALESCE(contract_status, '')), '') AS contract_status,
  final_segment AS segment_id,
  COALESCE(team_eligible, FALSE) AS team_eligible,
  COALESCE(market_eligible, FALSE) AS market_eligible,
  COALESCE(personal_eligible, FALSE) AS personal_eligible,
  final_segment = 'study_abroad_offline' AS offline_channel_eligible,
  acquisition_mode,
  NULLIF(TRIM(COALESCE(stage, '')), '') AS intended_stage,
  'study_abroad_warehouse' AS source_kind
FROM business._abroad_enriched
WHERE is_resource OR fact_value IS NOT NULL
""")
    con.execute("""
CREATE OR REPLACE VIEW business.abroad_diagnostics AS
WITH source AS (SELECT * FROM business.abroad_source_rows),
facts AS (SELECT * FROM business._abroad_enriched WHERE is_resource OR fact_value IS NOT NULL)
SELECT 'query_rows' AS diagnostic, COUNT(*)::BIGINT AS value FROM source
UNION ALL SELECT 'nonpositive_signatures_excluded', COUNT(*)::BIGINT
  FROM business._abroad_enriched WHERE NOT is_resource AND fact_value IS NULL
UNION ALL SELECT 'country_untrusted', COUNT(*)::BIGINT FROM facts WHERE country_is_untrusted
UNION ALL SELECT 'country_unresolved', COUNT(*)::BIGINT FROM facts WHERE safe_country IS NULL
UNION ALL SELECT 'unresolved_channel_rows', COUNT(*)::BIGINT
  FROM facts WHERE final_status NOT IN ('matched_existing', 'confirmed_new_source') OR final_status IS NULL
UNION ALL SELECT 'international_market_rows', COUNT(*)::BIGINT FROM facts WHERE final_segment = 'international_market'
UNION ALL SELECT 'ssc_rows', COUNT(*)::BIGINT FROM facts WHERE final_segment = 'ssc'
UNION ALL SELECT 'unassigned_rows', COUNT(*)::BIGINT FROM facts WHERE final_segment = 'unassigned'
UNION ALL SELECT 'resource_facts', COUNT(*)::BIGINT FROM facts WHERE is_resource
UNION ALL SELECT 'signature_facts', COUNT(*)::BIGINT FROM facts WHERE NOT is_resource
UNION ALL SELECT 'deleted_or_recalled_resources', COUNT(*)::BIGINT
  FROM facts WHERE is_resource AND resource_status IN ('删除', '回收')
UNION ALL SELECT 'grade_lookup_resources', COUNT(DISTINCT normalized_resource_id)::BIGINT
  FROM facts WHERE is_resource AND mapped_first = '市场活动' AND mapped_second IS NULL
    AND REGEXP_FULL_MATCH(COALESCE(normalized_resource_id, ''), '[0-9]+')
UNION ALL SELECT 'grade_lookup_grade_conflict', COUNT(DISTINCT normalized_resource_id)::BIGINT
  FROM facts WHERE is_resource AND grade_status = 'grade_conflict'
UNION ALL SELECT 'grade_lookup_resolved', COUNT(DISTINCT normalized_resource_id)::BIGINT
  FROM facts WHERE is_resource AND grade_status = 'resolved'
UNION ALL SELECT 'grade_lookup_grade_missing', COUNT(DISTINCT normalized_resource_id)::BIGINT
  FROM facts WHERE is_resource AND mapped_first = '市场活动' AND mapped_second IS NULL
    AND REGEXP_FULL_MATCH(COALESCE(normalized_resource_id, ''), '[0-9]+')
    AND (grade_status = 'grade_missing' OR grade_status IS NULL)
UNION ALL SELECT 'grade_lookup_resource_id_unavailable', COUNT(DISTINCT normalized_resource_id)::BIGINT
  FROM facts WHERE is_resource AND mapped_first = '市场活动' AND mapped_second IS NULL
    AND COALESCE(normalized_resource_id, '') <> ''
    AND NOT REGEXP_FULL_MATCH(normalized_resource_id, '[0-9]+')
UNION ALL SELECT 'facts', COUNT(*)::BIGINT FROM facts
""")


def _validate_identity(con: Any) -> None:
    unsupported = con.execute(
        f"SELECT fact_type FROM {INPUT_VIEW} WHERE fact_type IS NULL OR fact_type NOT IN ('resource', 'signature') LIMIT 1"
    ).fetchone()
    if unsupported:
        raise ValueError(f"不支持的留学facts fact_type：{unsupported[0]}")

    invalid = con.execute(f"""
      SELECT fact_type, fact_id FROM {INPUT_VIEW}
      WHERE (fact_type = 'resource' OR (fact_type = 'signature'
        AND COALESCE(positive_signature, FALSE) AND gross_signing_amount > 0))
        AND (NULLIF(TRIM(COALESCE(fact_id, '')), '') IS NULL OR event_date IS NULL
          OR business_line IS NULL OR business_line NOT IN ('study_abroad', 'small_language')
          OR origin_sha256 IS NULL OR NOT REGEXP_MATCHES(origin_sha256, '^[0-9a-f]{{64}}$'))
      LIMIT 1
    """).fetchone()
    if invalid:
        raise ValueError(f"留学facts缺少有效身份、日期、产品域或来源SHA：{invalid[1]}")

    invalid_amount = con.execute(f"""
      SELECT fact_id FROM {INPUT_VIEW}
      WHERE fact_type = 'signature' AND gross_signing_amount IS NULL LIMIT 1
    """).fetchone()
    if invalid_amount:
        raise ValueError(f"留学正向签约金额无效：{invalid_amount[0]}")

    conflict = con.execute(f"""
      SELECT fact_id FROM (
        SELECT fact_id, COUNT(DISTINCT TO_JSON(STRUCT_PACK(
          fact_type := fact_type, business_line := business_line, event_date := event_date,
          owner := owner, source_owner := source_owner, segment_id := segment_id,
          resource_id := resource_id, contract_id := contract_id, customer_key := customer_key,
          gross_signing_amount := gross_signing_amount, resource_status := resource_status,
          country := country, first_channel := first_channel, second_channel := second_channel,
          third_channel := third_channel, channel_source := channel_source, campaign := campaign,
          stage := stage, team_eligible := team_eligible, market_eligible := market_eligible,
          personal_eligible := personal_eligible, roster_group := roster_group,
          roster_status := roster_status, gross_amount := gross_amount,
          contract_status := contract_status, positive_signature := positive_signature,
          origin_sha256 := origin_sha256, origin_filename := origin_filename,
          origin_sheet := origin_sheet
        ))) AS versions
        FROM {INPUT_VIEW}
        WHERE fact_type = 'resource' OR (fact_type = 'signature'
          AND COALESCE(positive_signature, FALSE) AND gross_signing_amount > 0)
        GROUP BY fact_id
      ) WHERE versions > 1 LIMIT 1
    """).fetchone()
    if conflict:
        raise ValueError(f"留学facts存在重复fact_id身份冲突：{conflict[0]}")

    resource_conflict = con.execute(f"""
      WITH resources AS (
        SELECT *, NULLIF(REGEXP_REPLACE(
          REGEXP_REPLACE(TRIM(COALESCE(resource_id, '')), '{_RESOURCE_ID_PREFIX_RE}',
            ''), '\\.0+$', ''), '') AS rid
        FROM {INPUT_VIEW} WHERE fact_type = 'resource'
      ), latest AS (
        SELECT rid, MAX(event_date) AS event_date FROM resources
        WHERE rid IS NOT NULL GROUP BY rid
      ), identities AS (
        SELECT r.rid, COUNT(DISTINCT TO_JSON(STRUCT_PACK(
          event_date := r.event_date, owner := r.owner, source_owner := r.source_owner,
          market_group := r.market_group, segment_id := r.segment_id,
          business_line := r.business_line, resource_status := r.resource_status,
          country := r.country, first_channel := r.first_channel, second_channel := r.second_channel,
          third_channel := r.third_channel, origin_sha256 := r.origin_sha256,
          origin_sheet := r.origin_sheet
        ))) AS versions
        FROM resources r JOIN latest l USING (rid, event_date)
        GROUP BY r.rid
      ) SELECT rid FROM identities WHERE versions > 1 LIMIT 1
    """).fetchone()
    if resource_conflict:
        raise ValueError(f"同一留学资源的最新分单日存在身份冲突：{resource_conflict[0]}")


def install_abroad(
    con: Any,
    rows: Iterable[Mapping[str, Any]] | None,
    config: Mapping[str, Any],
    *,
    grade_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, str]:
    """Install fact views over controlled-query rows; transformation runs in DuckDB SQL.

    Supply controlled facts.sql rows for fixtures and reconciliation. In the
    production connection, the parent may create INPUT_VIEW directly over the
    same facts.sql query and pass rows=None. Grade補证 input, when present, must
    be raw rows from the controlled grade query; stage resolution is also SQL.
    """
    con.execute("CREATE SCHEMA IF NOT EXISTS business")
    if rows is not None:
        con.execute(_inline_view_sql(INPUT_VIEW, INPUT_COLUMNS, _INPUT_TYPES, rows, required=True))
    else:
        has_input = con.execute("""
          SELECT COUNT(*) FROM information_schema.views
          WHERE table_schema = 'business' AND table_name = 'abroad_source_rows'
        """).fetchone()[0]
        if not has_input:
            raise ValueError(f"必须先创建输入视图 {INPUT_VIEW}")

    config = dict(config)
    if grade_rows is not None:
        config["grade_rows"] = list(grade_rows)
    _install_config_views(con, config)
    _validate_identity(con)
    _create_output_views(con)
    return {"facts_view": FACTS_VIEW, "diagnostics_view": DIAGNOSTICS_VIEW}


__all__ = [
    "INPUT_VIEW", "INPUT_COLUMNS", "GRADE_INPUT_VIEW", "FACTS_VIEW", "DIAGNOSTICS_VIEW",
    "build_abroad_config", "load_abroad_config", "install_abroad",
]
