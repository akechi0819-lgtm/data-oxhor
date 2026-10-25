"""Normalize controlled-query rows into line-level management facts."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import json
import re
from typing import Any

from dashboard_product.fallback_mapping import infer_team, resolve_cash_channel
from dashboard_product.refresh import remap_tmk_school_agent_team, TARGET_GROUP
from workspace_modeling.operations.personnel import (
    campaign_allows_person_match,
    is_displayable_person,
    match_person_names,
)


TRAINING_GROUPS = {
    "青少": "留学预备",
    "初中": "留学预备",
    "留学预备": "留学预备",
    "高中": "高中",
    "大学": "大学",
    **TARGET_GROUP,
}
TEAM_IDS = frozenset({"offline_market", "online_private", "online_platform"})
COUNTRY_TAIL_FIELD_RE = re.compile(
    r"(?:在读年级|推送方式|所在部门|来源渠道|推荐人|意向阶段|"
    r"当前年级|所在学校|学生学校|联系邮箱|电子邮箱|邮箱|联系电话|电话|"
    r"转介绍人|咨询方式|工单备注|备注)"
)
COUNTRY_LABEL_RE = re.compile(r"^(?:意向国家(?:/地区|或地区)?|国家(?:/地区|或地区)?)\s*[:：]\s*")
COUNTRY_SEPARATORS_RE = re.compile(r"[,，、/]+")
UNKNOWN_COUNTRIES = frozenset({"其他", "其它", "未知", "无", "none", "null", "0", "1"})
NON_COMPLETION_ORDER_STATUSES = {
    "删除": "order_status_deleted",
    "回收": "order_status_recalled",
}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _valid_campaign(value: Any) -> str | None:
    text = _text(value)
    return text if campaign_allows_person_match(text) else None


def _value(value: Any, metric: str) -> int | float:
    if metric == "orders":
        return int(Decimal(str(value)))
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


def _cash_team_override(row: dict[str, Any], config: Any) -> dict[str, Any] | None:
    """Find a confirmed cash-team correction by its stable business fields."""
    if not isinstance(config, dict):
        return None
    event_date = _source_date(row.get("event_date"))
    work_order_id = _text(row.get("work_order_id"))
    for override in config.get("overrides", []):
        if not isinstance(override, dict):
            continue
        if (_text(override.get("work_order_id")) != work_order_id
                or _source_date(override.get("event_date")) != event_date
                or _text(override.get("team_id")) not in TEAM_IDS):
            continue
        try:
            override_amount = Decimal(str(override.get("amount"))).quantize(Decimal("0.01"))
            row_amount = Decimal(str(row.get("actual_value"))).quantize(Decimal("0.01"))
        except (TypeError, ValueError, ArithmeticError):
            continue
        if override_amount == row_amount:
            return override
    return None


def _source_date(value: Any) -> str | None:
    text = _text(value)
    return text[:10] if text else None


def _source_record(value: Any) -> Any:
    """Decode the optional JSON row returned by the controlled query."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def _completion_exclusion(order_status: Any) -> str | None:
    return NON_COMPLETION_ORDER_STATUSES.get(_text(order_status))


def _safe_country(value: Any) -> tuple[str | None, bool]:
    """Keep only a plausible first country and reject leaked description tails."""
    raw = _text(value)
    if not raw:
        return None, False
    boundary = COUNTRY_TAIL_FIELD_RE.search(raw)
    candidate = raw[:boundary.start()] if boundary else raw
    candidate = COUNTRY_LABEL_RE.sub("", candidate.strip())
    candidate = COUNTRY_SEPARATORS_RE.split(candidate, maxsplit=1)[0].strip(" \t\r\n:：;；|·-")
    suspicious = len(candidate) > 30 or any(char in raw for char in "@<>")
    if suspicious:
        return None, True
    if candidate.casefold() in UNKNOWN_COUNTRIES:
        return None, False
    return candidate or None, False


def _mapping(value: Any) -> dict[str, str]:
    if isinstance(value, dict) and isinstance(value.get("mappings"), list):
        return {
            _text(item.get("source_adviser")): _text(item.get("labeled_team"))
            for item in value["mappings"]
            if _text(item.get("source_adviser")) and _text(item.get("labeled_team"))
        }
    return dict(value or {})


def _people(people_config: dict[str, Any]) -> list[str]:
    names = []
    for team in people_config.get("teams", []):
        for group in team.get("groups", []):
            for person in group.get("members", []):
                if is_displayable_person(person):
                    name = _text(person.get("display_name"))
                    if name and name not in names:
                        names.append(name)
    return names


def _virtual_people(people_config: dict[str, Any]) -> list[str]:
    """Return only displayable members of the configured virtual team."""
    names = []
    for team in people_config.get("teams", []):
        if team.get("team_id") != "online_private":
            continue
        for group in team.get("groups", []):
            for person in group.get("members", []):
                if not is_displayable_person(person):
                    continue
                name = _text(person.get("display_name"))
                if name and name not in names:
                    names.append(name)
    return names


def _virtual_owner_matches(names: list[str], *fields: Any) -> list[str]:
    """Match every virtual roster name appearing in any supplied source text."""
    text = "\n".join(_text(value) for value in fields if _text(value))
    return [name for name in names if name in text]


def _offline_names(config: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(
        _text(person.get("display_name"))
        for person in config.get("people", [])
        if _text(person.get("display_name"))
    ))


def normalize_facts(
    training_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    people_config: dict[str, Any],
    abroad_people_config: dict[str, Any],
    adviser_mapping: Any,
    cash_team_overrides: Any = None,
    *, personal_qualification: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return training facts from the controlled BI queries only.

    This function only normalizes rows already returned by the controlled
    read-only query interface. It does not execute SQL or read warehouse files.
    """
    facts: list[dict[str, Any]] = []
    diagnostics: Counter[str] = Counter(
        training_input_rows=len(training_rows), order_input_rows=len(order_rows)
    )
    seen_ids: set[str] = set()
    virtual_roster = _virtual_people(people_config)
    offline_roster = _offline_names(abroad_people_config)
    known_people = list(dict.fromkeys(_people(people_config) + offline_roster))
    adviser_to_team = _mapping(adviser_mapping)
    orders_by_id = {
        _text(row.get("work_order_id")): row
        for row in order_rows
        if _text(row.get("work_order_id"))
    }
    confirmed_abroad_ids = {
        order_id
        for order_id, row in orders_by_id.items()
        if (_text(row.get("source_team")) or adviser_to_team.get(
            _text(row.get("adviser") or row.get("follow_adviser")), ""
        )) == "留学"
    }
    offline_training_names = {
        _text(person.get("display_name"))
        for team in people_config.get("teams", [])
        if team.get("team_id") == "offline_market"
        for group in team.get("groups", [])
        for person in group.get("members", [])
        if is_displayable_person(person)
    }

    # Preserve the P1 cash-channel fallback and the accepted TMK school-agent
    # remap while retaining each source cash row as its own fact.
    for row in training_rows:
        raw_metric = _text(row.get("metric"))
        if raw_metric == "work_orders":
            metric = "orders"
        elif raw_metric == "passive_reported_cash":
            metric = "cash"
        else:
            diagnostics["training_unsupported_metric"] += 1
            continue

        group = _text(row.get("business_group"))
        business_group = TRAINING_GROUPS.get(group)
        team_id = _text(row.get("team_id")) or None
        first = row.get("first_channel")
        second = row.get("second_channel")
        cash_campaign = row.get("cash_campaign_name")
        linked_campaign = row.get("work_order_campaign_name", row.get("campaign_name"))
        campaign = _valid_campaign(linked_campaign) or _valid_campaign(cash_campaign)

        team_inferred = False
        cash_override = None
        if metric == "cash":
            # Match P1's pure fallback contract: the raw cash activity is the
            # primary fallback evidence for channel inference.
            fallback_campaign = cash_campaign or row.get("campaign_name")
            resolved = resolve_cash_channel(
                row.get("cash_channel"), fallback_campaign, first, second,
                row.get("work_order_active_type"),
            )
            first, second = resolved["first_channel"], resolved["second_channel"]
            if not team_id or "TMK" in _text(row.get("cash_channel")).upper():
                original_team_id = team_id
                team_id, _ = infer_team(
                    team_id, row.get("cash_channel"), fallback_campaign, first, second,
                    resolved["decision"],
                )
                team_inferred = team_id != original_team_id
            team_id = remap_tmk_school_agent_team(
                team_id, first, campaign, row.get("entry_person"), offline_training_names
            )
            cash_override = _cash_team_override(row, cash_team_overrides)
            if cash_override:
                team_before_override = team_id
                team_id = _text(cash_override.get("team_id"))
                team_inferred = False
        elif team_id in TEAM_IDS:
            team_id = remap_tmk_school_agent_team(
                team_id, first, campaign, row.get("entry_person"), offline_training_names
            )

        source_row_number = row.get("source_row_number")
        work_order_id = _text(row.get("work_order_id")) or None
        order_source = orders_by_id.get(work_order_id or "", {})
        if metric == "orders":
            if not work_order_id:
                diagnostics["training_order_missing_id"] += 1
                continue
            if work_order_id in confirmed_abroad_ids:
                diagnostics["training_study_order_excluded"] += 1
                continue
            original_team = _text(order_source.get("source_team"))
            source_adviser = _text(order_source.get("adviser") or order_source.get("follow_adviser"))
            if order_source and not original_team and (not personal_qualification or adviser_to_team.get(source_adviser) != "留学预备"):
                diagnostics["training_unconfirmed_blank_team_excluded"] += 1
                continue
            if not personal_qualification and original_team and original_team not in {"塘沽", "大学", "无法判断", "校区资源无法归属", "武清", "留学预备", "需要判定", "高中"}:
                diagnostics["training_guanyuan_team_excluded"] += 1
                continue
            if not order_source:
                diagnostics["training_order_source_unmatched"] += 1
                if business_group is None:
                    diagnostics["training_unknown_line_excluded"] += 1
                    continue
            elif original_team and original_team in {"留学", "留学预备"}:
                diagnostics["training_study_or_prep_team_seen"] += 1
            if business_group is None:
                diagnostics["training_unknown_group_facts"] += 1
            fact_id = f"training:order:{work_order_id}"
        else:
            if source_row_number in (None, ""):
                diagnostics["training_cash_missing_source_row"] += 1
                continue
            fact_id = f"training:cash:{source_row_number}"
            if business_group is None:
                diagnostics["training_unknown_group_facts"] += 1
        if fact_id in seen_ids:
            diagnostics["duplicate_fact_id_skipped"] += 1
            continue
        seen_ids.add(fact_id)

        linked_campaign = _valid_campaign(order_source.get("campaign_name"))
        campaign = linked_campaign or campaign
        entry_person = row.get("entry_person") or order_source.get("resource_entry_person")
        description = order_source.get("resource_description")
        row_people = match_person_names(known_people, campaign, entry_person, description)
        order_status = _text(row.get("order_status") or order_source.get("order_status")) or None
        exclusion_reason = _completion_exclusion(order_status) if metric == "orders" else None
        source_record = (row.get("source_record") or order_source.get("source_record")
                         if metric == "orders" else
                         row.get("cash_source_record") or row.get("source_record"))
        fact = {
            "fact_id": fact_id,
            "metric": metric,
            "business_line": "training",
            "event_date": _source_date(row.get("event_date")),
            "value": _value(row.get("actual_value"), metric),
            "work_order_id": work_order_id,
            "order_status": order_status,
            "counts_toward_completion": exclusion_reason is None,
            "exclusion_reason": exclusion_reason,
            "source_record": _source_record(source_record),
            "student_id": _text(row.get("student_id")) or None,
            "team_id": team_id if team_id in TEAM_IDS else None,
            "business_group": business_group,
            # Keep the source group for the accepted 青少/初中 comparison.
            # business_group remains the normalized target bucket above.
            "comparison_group": _text(row.get("business_group")) or None,
            "school_name": _text(row.get("school_name")) or None,
            "grade_name": _text(row.get("grade_name")) or None,
            "campaign_name": campaign,
            "first_channel": first,
            "second_channel": second,
            "country": None,
            "line": None,
            "owners": row_people,
            "virtual_owners": _virtual_owner_matches(
                virtual_roster,
                row.get("campaign_name"), row.get("work_order_campaign_name"),
                row.get("cash_campaign_name"), order_source.get("campaign_name"),
                row.get("entry_person"), row.get("resource_entry_person"),
                order_source.get("resource_entry_person"),
                row.get("resource_description"), order_source.get("resource_description"),
            ),
            "source_row_number": source_row_number,
            "acquisition_mode": _text(row.get("acquisition_mode")) or None,
            "class_code": row.get("class_code"),
            "registration_count": row.get("registration_count"),
            "team_inferred": team_inferred,
        }
        if cash_override:
            fact["team_before_override"] = team_before_override
            fact["team_override_reason"] = _text(cash_override.get("note")) or None
        facts.append(fact)

    diagnostics["training_facts"] = sum(f["business_line"] == "training" for f in facts)
    diagnostics["facts_without_owner"] = sum(not f["owners"] for f in facts)
    diagnostics["facts_without_team"] = sum(f["team_id"] is None for f in facts)
    return facts, dict(diagnostics)
