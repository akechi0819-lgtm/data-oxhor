"""Build primary-business six-axis capacity comparisons for FY27."""
from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from dashboard_product.capacity import cash_contribution_bucket
from . import aggregate as a
from workspace_modeling.operations.personnel import co_creation_weights


FISCAL_START = date(2026, 6, 1)
FISCAL_END = date(2027, 5, 31)
RADAR_DIMS = (
    ("orders", "工单数"),
    ("heads", "签约量"),
    ("conversion", "转化率"),
    ("partner", "渠道／校代现金"),
    ("tmk", "TMK现金"),
    ("campaign", "活动现金"),
)
_CASH_BUCKETS = ("partner", "tmk", "campaign")
_ABROAD_DOMAINS = ("study_abroad", "small_language")
_NON_PERSONAL_SEGMENTS = frozenset({"international_market", "ssc", "unassigned"})
_FISCAL_MONTHS = tuple(
    [f"2026-{month:02d}" for month in range(6, 13)]
    + [f"2027-{month:02d}" for month in range(1, 6)]
)


def _configured_amount(value: Any) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _training_annual_target(config: dict[str, Any] | None) -> Decimal | None:
    if not isinstance(config, dict) or config.get("schema_version") != "dashboard_capacity_targets.v1":
        return None
    return _configured_amount(config.get("annual_cash_by_person"))


def _abroad_month_targets(person: dict[str, Any]) -> dict[str, Decimal] | None:
    monthly = person.get("monthly_targets")
    if not isinstance(monthly, dict):
        return None
    values = []
    for month in _FISCAL_MONTHS:
        target = monthly.get(month)
        if not isinstance(target, dict) or "cash" not in target:
            return None
        amount = _configured_amount(target.get("cash"))
        if amount is None:
            return None
        values.append((month, amount))
    return dict(values)


def _training_roster(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for team in config.get("teams", []):
        team_id = team.get("team_id")
        if team_id not in ("offline_market", "online_private"):
            continue
        for group in team.get("groups", []):
            for person in group.get("members", []):
                if not a.is_displayable_person(person):
                    continue
                name = a._text(person.get("display_name"))
                if not name:
                    continue
                row = result.setdefault(name, {
                    "name": name,
                    "business_line": "training",
                    "home_group": a._business_group(group.get("display_name"), person),
                    "team_ids": set(),
                    "training_roster": True,
                    "monthly_targets": person.get("monthly_targets") or {},
                    "status": person.get("status"),
                })
                row["team_ids"].add(team_id)
                if not row["home_group"]:
                    row["home_group"] = a._business_group(group.get("display_name"), person)
    return result


def _abroad_roster(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    source_team = config.get("team_id")
    team_id = {
        "study_abroad_offline": "offline_market",
        "study_abroad_online": "online_platform",
    }.get(source_team, "offline_market")
    for person in config.get("people", []):
        if not a.is_displayable_person(person):
            continue
        name = a._text(person.get("display_name"))
        if not name:
            continue
        result[name] = {
            "name": name,
            "business_line": "abroad",
            # This matches the current contribution table's abroad|留学 selector.
            "home_group": "留学",
            "roster_group": a._text(person.get("business_group")) or None,
            "team_ids": {team_id},
            "training_roster": False,
            "monthly_targets": person.get("monthly_targets") or {},
            "status": person.get("status"),
        }
    return result


def _abroad_bucket(first_channel: Any) -> str | None:
    first = a._text(first_channel)
    if "TMK" in first.upper():
        return "tmk"
    if first == "市场活动":
        return "campaign"
    if first in {"渠道合作", "官方合作高校"}:
        return "partner"
    return None


def _month_fractional_target(annual_targets: dict[str, Decimal], through: date) -> Decimal:
    total = Decimal(0)
    for month, target in annual_targets.items():
        year, number = map(int, month.split("-"))
        days = monthrange(year, number)[1]
        month_start = date(year, number, 1)
        if through < month_start:
            continue
        covered_days = min(days, (through - month_start).days + 1)
        total += target * Decimal(covered_days) / Decimal(days)
    return total


def _fact_domain(fact: dict[str, Any]) -> str | None:
    if fact.get("business_line") == "training":
        return "training"
    domain = a._text(fact.get("customer_domain"))
    return domain if domain in _ABROAD_DOMAINS else None


def _heads_parts(person: str, cash_domains: dict[str, set[str]],
                 heads_by_domain: dict[str, dict[str, dict[str, Decimal]]],
                 missing_identity: dict[str, set[str]], domains: tuple[str, ...]) -> dict[str, float | None]:
    result = {}
    for domain in domains:
        if domain in missing_identity.get(person, set()):
            result[domain] = None
        elif domain in cash_domains.get(person, set()):
            result[domain] = float(sum(heads_by_domain.get(person, {}).get(domain, {}).values(), Decimal(0)))
        else:
            result[domain] = 0.0
    return result


def _target_for(person: dict[str, Any], training_target: Decimal | None) -> Decimal | None:
    if person["business_line"] == "training":
        return training_target
    values = _abroad_month_targets(person)
    if values is None:
        return None
    return sum(values.values(), Decimal(0))


def build_radar(facts: list[dict[str, Any]], people: dict[str, Any],
                abroad_people: dict[str, Any], through: Any,
                capacity_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return source-covered FY27 radar rows, split by each person's primary business.

    Training roster members use BI training facts; study-abroad roster members
    use only the independent abroad facts. Empty-but-covered windows produce
    zeros. Customer heads remain separate by customer_domain and are left
    aggregate-missing when both study_abroad and small_language cash exist.
    """
    end = min(a._date(through), FISCAL_END)
    if end < FISCAL_START:
        raise ValueError("产能雷达截止日早于FY27起始日")
    roster = _training_roster(people)
    abroad = _abroad_roster(abroad_people)
    overlap = set(roster) & set(abroad)
    if overlap:
        raise ValueError("同一人员同时配置为语培与留学主业务，需先消除名单冲突")
    roster.update(abroad)
    if not roster:
        return []

    training_target = _training_annual_target(capacity_config)
    line_rosters = {
        line: {name: person for name, person in roster.items() if person["business_line"] == line}
        for line in ("training", "abroad")
    }
    attribution_roster = {
        name: {"name": name, "team_ids": set(person["team_ids"]), "status": person.get("status")}
        for name, person in roster.items()
    }
    valid = [fact for fact in a._valid_facts(facts, end)
             if FISCAL_START <= fact["event_date"] <= end]

    values: dict[str, dict[str, Any]] = {}
    for name, person in roster.items():
        values[name] = {
            "orders": Decimal(0),
            "cash": Decimal(0),
            "training_orders": Decimal(0),
            "training_cash": Decimal(0),
            "abroad_orders": Decimal(0),
            "abroad_cash": Decimal(0),
            "buckets": {bucket: Decimal(0) for bucket in _CASH_BUCKETS},
            "product_orders": {domain: Decimal(0) for domain in _ABROAD_DOMAINS},
            "product_cash": {domain: Decimal(0) for domain in _ABROAD_DOMAINS},
            "cash_domains": set(),
            "heads_by_domain": {domain: {} for domain in _ABROAD_DOMAINS},
            "heads_training": {},
            "missing_identity": set(),
            "training_missing_identity": False,
            "unknown_cash_domain": False,
            "unknown_orders": Decimal(0),
            "unknown_cash": Decimal(0),
            "has_activity": False,
        }

    for fact in valid:
        line = fact["business_line"]
        if line not in line_rosters:
            continue
        if line == "abroad" and (
            fact.get("segment_id") in _NON_PERSONAL_SEGMENTS
            or fact.get("personal_eligible") is False
        ):
            continue
        domain = _fact_domain(fact)
        fact_names = list(fact.get("owners") or [])
        if line == "training":
            fact_names.extend(fact.get("virtual_owners") or [])
        eligible_roster = line_rosters[line]
        fact_names = [name for name in fact_names if name in eligible_roster]
        weights = co_creation_weights(fact_names, attribution_roster)
        if not weights:
            continue
        amount = Decimal(str(fact["value"]))
        for name, weight in weights.items():
            row = values[name]
            row["has_activity"] = True
            if fact["metric"] == "orders":
                row["orders"] += amount * weight
                if line == "training":
                    row["training_orders"] += amount * weight
                else:
                    row["abroad_orders"] += amount * weight
                    if domain in row["product_orders"]:
                        row["product_orders"][domain] += amount * weight
                    else:
                        row["unknown_orders"] += amount * weight
                continue

            row["cash"] += amount * weight
            if line == "training":
                row["training_cash"] += amount * weight
                bucket = cash_contribution_bucket(fact.get("first_channel"), fact.get("second_channel"))
            else:
                row["abroad_cash"] += amount * weight
                if domain in row["product_cash"]:
                    row["product_cash"][domain] += amount * weight
                else:
                    row["unknown_cash"] += amount * weight
                bucket = _abroad_bucket(fact.get("first_channel"))
            if bucket in row["buckets"]:
                row["buckets"][bucket] += amount * weight

            if line == "training":
                if amount <= 0:
                    continue
                student_id = a._text(fact.get("student_id"))
                if not student_id:
                    row["training_missing_identity"] = True
                else:
                    row["heads_training"][student_id] = max(
                        row["heads_training"].get(student_id, Decimal(0)), weight,
                    )
                continue

            if amount <= 0 or domain not in _ABROAD_DOMAINS:
                if amount > 0 and line == "abroad":
                    row["unknown_cash_domain"] = True
                continue
            row["cash_domains"].add(domain)
            student_id = a._text(fact.get("student_id"))
            if not student_id:
                row["missing_identity"].add(domain)
            else:
                heads = row["heads_by_domain"][domain]
                heads[student_id] = max(heads.get(student_id, Decimal(0)), weight)

    elapsed_days = (end - FISCAL_START).days + 1
    fiscal_days = (FISCAL_END - FISCAL_START).days + 1
    rows = []
    for name, person in sorted(roster.items()):
        totals = values[name]
        line = person["business_line"]
        home_team = sorted(person["team_ids"])[0] if person["team_ids"] else ""
        home_group = person["home_group"]
        cash_capacity = _target_for(person, training_target)
        if line == "training":
            target_to_date = (cash_capacity * Decimal(elapsed_days) / Decimal(fiscal_days)
                              if cash_capacity is not None else None)
            heads = (None if totals["training_missing_identity"] else float(
                sum(totals["heads_training"].values(), Decimal(0))))
            conversion = heads / float(totals["orders"]) if heads is not None and totals["orders"] else None
            product_parts = {
                "training": {
                    "orders": float(totals["training_orders"]),
                    "cash": float(totals["training_cash"]),
                    "heads": heads,
                    "conversion": conversion,
                }
            }
        else:
            target_values = _abroad_month_targets(person)
            target_to_date = (_month_fractional_target(target_values, end)
                              if cash_capacity is not None and target_values is not None else None)
            heads_parts = _heads_parts(
                name, {name: totals["cash_domains"]}, {name: totals["heads_by_domain"]},
                {name: totals["missing_identity"]}, _ABROAD_DOMAINS,
            )
            orders_parts = {domain: float(totals["product_orders"][domain]) for domain in _ABROAD_DOMAINS}
            conversion_parts = {
                domain: (heads_parts[domain] / orders_parts[domain]
                         if heads_parts[domain] is not None and orders_parts[domain] else None)
                for domain in _ABROAD_DOMAINS
            }
            if totals["unknown_cash_domain"] or len(totals["cash_domains"]) > 1:
                heads = None
                conversion = None
            elif len(totals["cash_domains"]) == 1:
                domain = next(iter(totals["cash_domains"]))
                heads = heads_parts[domain]
                conversion = heads / float(totals["orders"]) if heads is not None and totals["orders"] else None
            else:
                heads = 0.0
                conversion = 0.0 if totals["orders"] else None
            product_parts = {
                domain: {
                    "orders": orders_parts[domain],
                    "cash": float(totals["product_cash"][domain]),
                    "heads": heads_parts[domain],
                    "conversion": conversion_parts[domain],
                }
                for domain in _ABROAD_DOMAINS
            }
            product_parts["unmapped"] = {
                "orders": float(totals["unknown_orders"]),
                "cash": float(totals["unknown_cash"]),
                "heads": None if totals["unknown_cash_domain"] else 0.0,
                "conversion": None,
            }

        raw_buckets = {key: float(totals["buckets"][key]) for key in _CASH_BUCKETS}
        radar_values = {
            "orders": float(totals["orders"]),
            "heads": heads,
            "conversion": conversion,
            **raw_buckets,
        }
        progress = (float(totals["cash"] / target_to_date)
                    if target_to_date is not None and target_to_date > 0 else None)
        display_peer_group = f"{line}|{home_group}"
        rows.append({
            "name": name,
            "business_line": line,
            "home_team": home_team,
            "home_group": home_group,
            "peer_group": display_peer_group,
            "comparison_group": (home_team, home_group, line),
            "start_date": FISCAL_START.isoformat(),
            "through_date": end.isoformat(),
            "orders": radar_values["orders"],
            "cash": float(totals["cash"]),
            "heads": heads,
            "conversion": conversion,
            "partner": raw_buckets["partner"],
            "tmk": raw_buckets["tmk"],
            "campaign": raw_buckets["campaign"],
            "cash_capacity": float(cash_capacity) if cash_capacity is not None else None,
            "cash_progress_completion": progress,
            "product_parts": product_parts,
            "radar_values": radar_values,
        })

    peers = defaultdict(list)
    for row in rows:
        peers[row["comparison_group"]].append(row)
    for row in rows:
        axes = []
        for key, label in RADAR_DIMS:
            values_for_axis = [peer["radar_values"][key] for peer in peers[row["comparison_group"]]
                               if peer["radar_values"][key] is not None]
            value = row["radar_values"][key]
            mean = sum(values_for_axis) / len(values_for_axis) if values_for_axis else None
            axes.append({
                "key": key,
                "label": label,
                "value": value,
                "mean": mean,
                "relative": value / mean - 1 if value is not None and mean else None,
                "scale": max(values_for_axis) if values_for_axis and max(values_for_axis) > 0 else 1,
            })
        row["radar"] = {
            "scope": "语培六维；FY27累计" if row["business_line"] == "training" else "留学六维；FY27累计",
            "axes": axes,
            "peer_count": len(peers[row["comparison_group"]]),
        }
    for row in rows:
        del row["radar_values"]
        del row["comparison_group"]
    return rows


__all__ = ["RADAR_DIMS", "build_radar"]
