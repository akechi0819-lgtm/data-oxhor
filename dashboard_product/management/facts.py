"""Normalize controlled-query rows into line-level management facts."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import json
import re
from typing import Any

from data_acquisition.jobs.work_order_cleaning import (
    _extract_country_with_source,
    _resolve_line,
    clean_work_order_rows,
)
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
OFFLINE_ROOTS = frozenset({"渠道合作", "市场活动", "官方合作高校", "新东方学校推荐"})
OFFLINE_DEPARTMENT_CHANNELS = frozenset({"渠道合作", "市场活动", "官方合作高校"})
NEWDONGFANG_STRONG_SIGNALS = ("市场人员", "市场双分", "【市场活动】", "【市场人员】")
NEWDONGFANG_EVENT_SIGNALS = ("讲座", "展会", "会销", "问卷")
NEWDONGFANG_CONFIRMED_PEOPLE = ("邓睿", "杨芸聿", "孙伟", "王洪霞", "吴子玄")
ONLINE_ROOTS = frozenset({"网络资源", "新媒体"})
TEAM_IDS = frozenset({"offline_market", "online_private", "online_platform"})
PARENTHESES_RE = re.compile(r"（[^）]*）|\([^)]*\)")
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


def _offline_names(config: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(
        _text(person.get("display_name"))
        for person in config.get("people", [])
        if _text(person.get("display_name"))
    ))


def _root(path: Any) -> str:
    return _text(path).split("-", 1)[0]


def _abroad_online_eligible(root: str, active: Any) -> bool:
    active = _text(active)
    return (root == "网络资源" and active in {"主动", "被动"}) or (
        root == "新媒体" and active == "被动"
    )


def _first_named(text: Any, names: list[str]) -> str | None:
    blob = _text(text)
    hits = [
        (position, -len(name), index, name)
        for index, name in enumerate(names)
        if (position := blob.find(name)) >= 0
    ]
    return min(hits)[-1] if hits else None


def _offline_claim(row: dict[str, Any], roster: list[str]) -> str | None:
    """Apply the confirmed offline study-abroad attribution priority."""
    entry = _text(row.get("resource_entry_person"))
    if entry in roster:
        return entry

    campaign = _text(row.get("campaign_name"))
    if campaign_allows_person_match(campaign) and roster:
        alternatives = "|".join(re.escape(name) for name in sorted(roster, key=len, reverse=True))
        match = re.search(rf"(?:^|[-/])({alternatives})(?:雅思|市场|渠道|-|（|$)", campaign)
        if match:
            return match.group(1)

    description = _text(row.get("resource_description"))
    labeled = re.search(r"市场人员\s*[:：]\s*([^\s,，;；]+)", description)
    if labeled:
        person = _first_named(labeled.group(1), roster)
        if person:
            return person

    provider = re.search(r"数据提供方\s*[:：]([^/\n]{0,120})", description)
    if provider:
        person = _first_named(provider.group(1), roster)
        if person:
            return person

    referrers = f"{_text(row.get('other_referrer'))} {_text(row.get('referrer'))}"
    if "不算新" not in referrers:
        referrers = PARENTHESES_RE.sub(" ", referrers)
        person = _first_named(referrers, roster)
        if person:
            return person
    return None


def _newdongfang_market_eligible(row: dict[str, Any]) -> bool:
    """Match the confirmed point-to-point market-recommended subset."""
    if _root(row.get("source_path")) != "新东方学校推荐" or _text(row.get("source_channel")) != "点对点":
        return False

    campaign = _text(row.get("campaign_name"))
    description = _text(row.get("resource_description"))
    if _text(row.get("first_channel")) == "市场活动" or any(
        signal in campaign or signal in description for signal in NEWDONGFANG_STRONG_SIGNALS
    ):
        return True
    if any(signal in campaign or signal in description for signal in NEWDONGFANG_EVENT_SIGNALS):
        return True

    people_text = " ".join(
        _text(row.get(field))
        for field in ("campaign_name", "resource_description", "resource_entry_person", "other_referrer")
    )
    return any(name in people_text for name in NEWDONGFANG_CONFIRMED_PEOPLE)


def _explicit_team(row: dict[str, Any]) -> str | None:
    online_offline = _text(row.get("online_offline"))
    second_channel = _text(row.get("second_channel"))
    if online_offline == "线下":
        return "offline_market"
    if second_channel == "虚拟人":
        return "online_private"
    if online_offline == "线上":
        return "online_platform"
    return None


def _clean_online_order(row: dict[str, Any], reference: Any) -> dict[str, Any]:
    source = {
        "ID": row.get("work_order_id"),
        # The source team is already confirmed upstream. An empty local copy
        # lets the existing cleaner apply its overlay without changing it.
        "团队": "",
        "主被动": row.get("main_active_type") or "",
        "资源主被动": row.get("resource_active_type") or "",
        "咨询方式一级渠道": row.get("source_path") or "",
        "渠道": row.get("source_channel") or "",
        "一级渠道": row.get("first_channel") or "",
        "二级渠道": row.get("second_channel") or "",
        "意向国家/地区": row.get("intended_country_source") or "",
        "资源描述": row.get("resource_description") or "",
    }
    if reference is None:
        return source
    cleaned, _ = clean_work_order_rows([source], reference, include_audit=True)
    return cleaned[0]


def normalize_facts(
    training_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    people_config: dict[str, Any],
    abroad_people_config: dict[str, Any],
    adviser_mapping: Any,
    reference: Any,
    cash_team_overrides: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return V14 training facts and confirmed study-abroad order facts.

    This function only normalizes rows already returned by the controlled
    read-only query interface. It does not execute SQL or read warehouse files.
    """
    facts: list[dict[str, Any]] = []
    diagnostics: Counter[str] = Counter(
        training_input_rows=len(training_rows), order_input_rows=len(order_rows)
    )
    seen_ids: set[str] = set()
    offline_roster = _offline_names(abroad_people_config)
    confirmed_offline_order_ids = {
        _text(work_order_id)
        for work_order_id in abroad_people_config.get("confirmed_offline_work_order_ids", [])
        if _text(work_order_id)
    }
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
            if order_source and not original_team and adviser_to_team.get(source_adviser) != "留学预备":
                diagnostics["training_unconfirmed_blank_team_excluded"] += 1
                continue
            if not order_source:
                diagnostics["training_order_source_unmatched"] += 1
                if business_group is None:
                    diagnostics["training_unknown_line_excluded"] += 1
                    continue
            elif not original_team and adviser_to_team.get(source_adviser) == "留学预备":
                diagnostics["training_confirmed_prep_order"] += 1
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
            "source_row_number": source_row_number,
            "acquisition_mode": None,
            "team_inferred": team_inferred,
        }
        if cash_override:
            fact["team_before_override"] = team_before_override
            fact["team_override_reason"] = _text(cash_override.get("note")) or None
        facts.append(fact)

    for row in order_rows:
        work_order_id = _text(row.get("work_order_id"))
        if not work_order_id:
            diagnostics["abroad_order_missing_id"] += 1
            continue
        fact_id = f"abroad:order:{work_order_id}"
        if fact_id in seen_ids:
            diagnostics["duplicate_fact_id_skipped"] += 1
            continue

        source_team = _text(row.get("source_team"))
        order_status = _text(row.get("order_status")) or None
        exclusion_reason = _completion_exclusion(order_status)
        adviser = _text(row.get("adviser") or row.get("follow_adviser"))
        labeled_team = source_team or adviser_to_team.get(adviser, "")
        if labeled_team != "留学":
            diagnostics["order_not_confirmed_as_abroad"] += 1
            continue

        root = _root(row.get("source_path"))
        campaign = _valid_campaign(row.get("campaign_name"))
        strict_offline_owner = _offline_claim(row, offline_roster)
        confirmed_offline = work_order_id in confirmed_offline_order_ids
        online = root in ONLINE_ROOTS and _abroad_online_eligible(root, row.get("resource_active_type"))
        offline_first, offline_second = _offline_channels(row)
        offline_channel_eligible = confirmed_offline or (
            offline_first in OFFLINE_DEPARTMENT_CHANNELS
            and _text(row.get("resource_active_type")) == "被动"
        ) or _newdongfang_market_eligible(row)
        offline = root in OFFLINE_ROOTS or strict_offline_owner is not None or confirmed_offline
        if not online and not offline:
            diagnostics["abroad_path_or_active_out_of_scope"] += 1
            continue
        owner_campaign = PARENTHESES_RE.sub(" ", campaign or "")
        owner_description = PARENTHESES_RE.sub(" ", _text(row.get("resource_description")))
        matched_owners = match_person_names(
            known_people,
            owner_campaign,
            row.get("resource_entry_person"),
            owner_description,
        )
        # Keep strict offline claims for personal attribution; department scope
        # is carried separately by offline_channel_eligible.
        owners = [name for name in matched_owners if name not in offline_roster]
        if strict_offline_owner and strict_offline_owner not in owners:
            owners.insert(0, strict_offline_owner)
        if offline_channel_eligible:
            team_id = "offline_market"
            business_group = "大学"
        elif online:
            team_id = "online_platform"
            business_group = None
        elif strict_offline_owner:
            team_id = "offline_market"
            business_group = "大学"
        else:
            team_id = _explicit_team(row)
            business_group = None

        cleaned = _clean_online_order(row, reference)
        raw_country, _ = _extract_country_with_source({
            "意向国家/地区": row.get("intended_country_source"),
            "资源描述": row.get("resource_description"),
        })
        country_value = _text(cleaned.get("意向国家")) or raw_country
        country, country_suspicious = _safe_country(country_value)
        if country_suspicious:
            diagnostics["abroad_country_untrusted"] += 1
        if country is None:
            diagnostics["abroad_country_unresolved"] += 1
        line = _text(cleaned.get("矫正条线")) or (
            _resolve_line(country or "", _text(row.get("source_path")), reference)
            if reference is not None else ""
        ) or None
        if root in ONLINE_ROOTS:
            first = cleaned.get("一级渠道") or root
            if cleaned.get("留学渠道清洗状态") == "已命中":
                second = cleaned.get("二级渠道")
            else:
                second = "当前规则未命中"
            if _text(second) == "其他":
                second = "SSC"
        else:
            first, second = offline_first, offline_second

        if _text(second).casefold() == "ssc":
            diagnostics["ssc_excluded"] += 1
            continue
        if _text(row.get("second_channel")).casefold() == "ssc":
            diagnostics["ssc_excluded"] += 1
            continue

        seen_ids.add(fact_id)
        if not owners:
            diagnostics["abroad_without_owner"] += 1
        if team_id is None:
            diagnostics["abroad_without_team"] += 1

        facts.append({
            "fact_id": fact_id,
            "metric": "orders",
            "business_line": "abroad",
            "event_date": _source_date(row.get("event_date")),
            "value": 1,
            "work_order_id": work_order_id,
            "order_status": order_status,
            "counts_toward_completion": exclusion_reason is None,
            "exclusion_reason": exclusion_reason,
            "source_record": _source_record(row.get("source_record")),
            "student_id": None,
            "team_id": team_id if team_id in TEAM_IDS else None,
            "business_group": business_group,
            # The orders query exposes the student and current-school fields
            # separately; retain whichever usable school label it returned.
            "school_name": (_text(row.get("school_name"))
                            or _text(row.get("student_school"))
                            or _text(row.get("current_school")) or None),
            "grade_name": (_text(row.get("grade_name"))
                           or _text(row.get("current_grade"))
                           or _text(row.get("grade_attr")) or None),
            "campaign_name": campaign,
            "first_channel": first,
            "second_channel": second,
            "country": country,
            "line": line,
            "owners": owners,
            "source_row_number": row.get("source_row_number"),
            "offline_channel_eligible": offline_channel_eligible,
            "acquisition_mode": ("offline" if confirmed_offline
                                 else "online" if root in ONLINE_ROOTS else "offline"),
            "team_inferred": False,
        })

    diagnostics["training_facts"] = sum(f["business_line"] == "training" for f in facts)
    diagnostics["abroad_facts"] = sum(f["business_line"] == "abroad" for f in facts)
    diagnostics["facts_without_owner"] = sum(not f["owners"] for f in facts)
    diagnostics["facts_without_team"] = sum(f["team_id"] is None for f in facts)
    return facts, dict(diagnostics)


def _offline_channels(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Reproduce the existing offline-market channel buckets from raw path fields."""
    source_path = _text(row.get("source_path"))
    root = _root(source_path)
    rest = source_path[len(root) + 1:] if source_path.startswith(root + "-") else ""
    source_channel = _text(row.get("source_channel"))

    if root == "官方合作高校":
        first = second = "官方合作高校"
    elif root == "新东方学校推荐":
        first = root
        second = rest if rest in {"国外考试部", "大学事业部", "大客服", "高中部", "青少部", "国游营地", "其他推荐"} else "其他推荐"
    elif root == "渠道合作":
        first = root
        if source_channel == "分公司个人代理":
            second = "个人渠道"
        elif source_channel in {"分公司对公合作", "留学监理网"}:
            second = "对公渠道（三方）"
        else:
            second = "其他"
    elif root == "市场活动" and rest == "高校" and source_channel == "个人代理":
        first, second = "渠道合作", "个人渠道"
    elif root == "市场活动":
        first = root
        if (rest == "高校" and source_channel == "高校活动") or (not rest and source_channel == "市场活动"):
            second = "高校活动"
        elif rest == "中学" and source_channel == "中学活动":
            second = "中学活动"
        elif rest == "地推" and source_channel == "地推":
            second = "地推"
        elif rest in {"综合展", "现场注册", "部门展"} or source_channel in {
            "综合展", "信息收集", "条线专展", "F活动邀约", "其他"
        }:
            second = "综合展"
        else:
            second = "其他"
    else:
        first, second = "其他", "其他"
    return first or None, second or None
