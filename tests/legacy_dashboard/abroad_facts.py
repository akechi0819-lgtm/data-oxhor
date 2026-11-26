from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from data_acquisition.jobs.work_order_cleaning import _resolve_line
from tests.legacy_dashboard.training_facts import _safe_country

_RESOURCE_ID_PREFIX = re.compile(r'^(?:资源\s*ID|ID)\s*[:：]\s*', re.IGNORECASE)
_RESOURCE_ID_NUMBER = re.compile(r'^\d+(?:\.0+)?$')
PENDING_CHANNEL = '渠道待确认'
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_NORMAL_MARKET_SEGMENTS = frozenset({'study_abroad_offline', 'study_abroad_online'})

def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()

def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).casefold() in {"true", "1", "yes", "是"}

def _date(value: Any) -> date:
    try:
        return date.fromisoformat(_text(value)[:10])
    except ValueError as exc:
        raise ValueError(f"留学事实日期无效：{value!r}") from exc

def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"留学正向签约金额无效：{value!r}") from exc
    if not amount.is_finite():
        raise ValueError("留学正向签约金额必须为有限数值")
    return amount.quantize(Decimal("0.01"))

def _fact_value(row: dict[str, Any], diagnostics: Counter[str]) -> tuple[str, float] | None:
    fact_type = _text(row.get("fact_type"))
    if fact_type == "resource":
        return "orders", 1
    if fact_type != "signature":
        raise ValueError(f"不支持的留学facts fact_type：{fact_type}")
    amount = _money(row.get("gross_signing_amount"))
    if not _boolean(row.get("positive_signature")) or amount <= 0:
        diagnostics["nonpositive_signatures_excluded"] += 1
        return None
    return "cash", float(amount)

def _correct_market_segment(row: dict[str, Any], first: str | None,
                            second: str | None) -> str:
    """Apply confirmed channel ownership only to regular study-abroad market rows."""
    segment = _text(row.get("segment_id"))
    if segment not in _NORMAL_MARKET_SEGMENTS:
        return segment

    raw_first = _text(row.get("first_channel"))
    raw_second = _text(row.get("second_channel"))
    third = _text(row.get("third_channel"))
    if second == "虚拟人" or raw_second == "虚拟人" or third == "虚拟人":
        return "study_abroad_virtual"
    if second == "SSC" or raw_second == "欧亚总部在线":
        return "ssc"
    if (first in {"网络资源", "TMK激活-平台"}
            or raw_first in {"网络资源", "线上运营", "网络", "TMK激活-平台"}):
        return "study_abroad_online"
    return segment

def _make_fact(row: dict[str, Any], channel: tuple[Any, ...], diagnostics: Counter[str],
               reference: Any) -> dict[str, Any] | None:
    metric_value = _fact_value(row, diagnostics)
    if metric_value is None:
        return None
    metric, value = metric_value
    business_product = _text(row.get("business_line"))
    if business_product not in {"study_abroad", "small_language"}:
        raise ValueError(f"留学facts business_line无效：{business_product}")
    fact_id = _text(row.get("fact_id"))
    if not fact_id:
        raise ValueError("留学facts缺少稳定fact_id")
    event_date = _date(row.get("event_date")).isoformat()
    source_sha256 = _text(row.get("origin_sha256"))
    if not _SHA256.fullmatch(source_sha256):
        raise ValueError("留学facts缺少有效origin_sha256")

    source_segment = _text(row.get("segment_id"))
    owner = _text(row.get("owner")) or None
    personal_eligible = _boolean(row.get("personal_eligible"))
    owners = [] if source_segment == "international_market" or not personal_eligible or not owner else [owner]
    resource_status = _text(row.get("resource_status")) or None
    is_resource = _text(row.get("fact_type")) == "resource"
    counts_toward_completion = (resource_status not in {"删除", "回收"}) if is_resource else True
    exclusion_reason = ("resource_status_deleted" if resource_status == "删除" else
                        "resource_status_recalled" if resource_status == "回收" else None)
    country, country_suspicious = _safe_country(row.get("country"))
    if country_suspicious:
        diagnostics["country_untrusted"] += 1
    if country is None:
        diagnostics["country_unresolved"] += 1

    raw_first = _text(row.get("first_channel"))
    raw_second = _text(row.get("second_channel"))
    raw_path = f"{raw_first}-{raw_second}" if raw_first and raw_second else raw_first
    line = _resolve_line(country or "", raw_path, reference)
    first, second, channel_status, channel_rule = channel
    segment = _correct_market_segment(row, first, second)
    team_id = {
        "study_abroad_online": "online_platform",
        "study_abroad_offline": "offline_market",
        "study_abroad_virtual": "online_private",
    }.get(segment)
    acquisition_mode = {
        "study_abroad_online": "online",
        "study_abroad_offline": "offline",
        "study_abroad_virtual": "online",
    }.get(segment, "supplemental")
    offline_channel_eligible = segment == "study_abroad_offline"
    if channel_status not in {"matched_existing", "confirmed_new_source"}:
        diagnostics["unresolved_channel_rows"] += 1
    if segment == "international_market":
        diagnostics["international_market_rows"] += 1
    elif segment == "ssc":
        diagnostics["ssc_rows"] += 1
    elif segment == "unassigned":
        diagnostics["unassigned_rows"] += 1
    if is_resource:
        diagnostics["resource_facts"] += 1
    else:
        diagnostics["signature_facts"] += 1
    if is_resource and not counts_toward_completion:
        diagnostics["deleted_or_recalled_resources"] += 1

    return {
        "fact_id": f"abroad-source:{fact_id}",
        "metric": metric,
        "business_line": "abroad",
        "event_date": event_date,
        "value": value,
        "work_order_id": None,
        "order_status": resource_status if is_resource else None,
        "counts_toward_completion": counts_toward_completion,
        "exclusion_reason": exclusion_reason,
        "source_record": None,
        "student_id": _text(row.get("customer_key")) or None,
        "team_id": team_id,
        "business_group": _text(row.get("roster_group")) or None,
        "school_name": None,
        "grade_name": None,
        "campaign_name": _text(row.get("campaign")) or None,
        "first_channel": first or PENDING_CHANNEL,
        "second_channel": second or PENDING_CHANNEL,
        "third_channel": _text(row.get("third_channel")) or None,
        "raw_first_channel": raw_first or None,
        "raw_second_channel": raw_second or None,
        "channel_source": _text(row.get("channel_source")) or None,
        "channel_mapping_status": channel_status,
        "channel_mapping_rule": channel_rule,
        "country": country,
        "line": line or None,
        "owners": owners,
        "virtual_owners": [],
        "source_row_number": row.get("origin_row_number"),
        "source_sha256": source_sha256,
        "source_sheet": _text(row.get("origin_sheet")) or None,
        "source_filename": _text(row.get("origin_filename")) or None,
        "source_owner": _text(row.get("source_owner")) or None,
        "owner": owner,
        "source_product": business_product,
        "customer_domain": business_product,
        "resource_id": _source_resource_id(row.get("resource_id")),
        "contract_id": _text(row.get("contract_id")) or None,
        "customer_key": _text(row.get("customer_key")) or None,
        "resource_status": resource_status,
        "contract_status": _text(row.get("contract_status")) or None,
        "segment_id": segment or None,
        "team_eligible": _boolean(row.get("team_eligible")),
        "market_eligible": _boolean(row.get("market_eligible")),
        "personal_eligible": personal_eligible,
        "offline_channel_eligible": offline_channel_eligible,
        "acquisition_mode": acquisition_mode,
        "intended_stage": _text(row.get("stage")) or None,
        "source_kind": "study_abroad_warehouse",
    }


def _source_resource_id(value: Any) -> str | None:
    text = _RESOURCE_ID_PREFIX.sub("", _text(value)).strip()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    return text or None
