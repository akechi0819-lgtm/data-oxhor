"""Adapt the isolated study-abroad Snapshot into management fact rows."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from data_acquisition.jobs.work_order_cleaning import _resolve_line, load_work_order_reference
from dashboard_product.management.facts import _safe_country
from dashboard_product.management.study_abroad_channels import (
    DECISIONS_PATH, legacy_channel, load_decisions,
)
from dashboard_product.management.study_abroad_grade import load_grade_evidence
from dashboard_product.management.study_abroad_query import SQL_ROOT, query_sample
from data_platform.query.evidence import read_query_result, resolve_file, verify_receipt


SOURCE_ID = "study_abroad_market"
SOURCE_SCHEMA = "study_abroad_warehouse.v1"
START_DATE = date(2026, 6, 1)
PENDING_CHANNEL = "渠道待确认"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RESOURCE_ID_PREFIX = re.compile(r"^(?:资源\s*ID|ID)\s*[:：]\s*", re.IGNORECASE)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _source_resource_id(value: Any) -> str | None:
    text = _RESOURCE_ID_PREFIX.sub("", _text(value)).strip()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    return text or None


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).casefold() in {"true", "1", "yes", "是"}


def _date(value: Any) -> date:
    try:
        return date.fromisoformat(_text(value)[:10])
    except ValueError as exc:
        raise ValueError(f"留学事实日期无效：{value!r}") from exc


def _safe_relative(root: Path, value: Any, *, allowed_root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"留学{label}路径缺失")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"留学{label}路径必须是明确相对路径")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(allowed_root.resolve()):
        raise ValueError(f"留学{label}路径越界")
    return resolved


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"来源JSON必须是对象：{path}")
    return value, raw


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen = set()
    for path in paths:
        resolved = Path(path).resolve()
        key = str(resolved)
        if key not in seen:
            result.append(resolved)
            seen.add(key)
    return result


def _snapshot_sources(workspace: Path, snapshot_id: str, expected_company_id: str) -> dict[str, Any]:
    workspace_config_path = workspace / "Work/workspace.json"
    workspace_config, workspace_config_bytes = _read_json(workspace_config_path)
    if workspace_config.get("company_id") != expected_company_id:
        raise ValueError("工作区company_id与留学仓不一致")

    pointer_path = workspace / "Work/StudyAbroad/current.json"
    pointer, pointer_bytes = _read_json(pointer_path)
    if (pointer.get("schema_version") != SOURCE_SCHEMA
            or pointer.get("company_id") != expected_company_id
            or pointer.get("snapshot_id") != snapshot_id):
        raise ValueError("显式Snapshot必须匹配当前留学仓指针和客户身份")
    source_sha256 = pointer.get("source_sha256")
    if not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256):
        raise ValueError("留学仓source_sha256无效")
    source_through = _date(pointer.get("through_date"))

    isolated_root = workspace / "Work/StudyAbroad"
    runs_root = isolated_root / "Runs"
    warehouse = _safe_relative(
        workspace, pointer.get("warehouse"), allowed_root=runs_root, label="warehouse",
    )
    if warehouse.name != "warehouse.duckdb" or warehouse.parent.name != snapshot_id or not warehouse.is_file():
        raise ValueError("留学warehouse路径与显式Snapshot不匹配")
    snapshot_manifest_path = warehouse.parent / "snapshot_manifest.json"
    snapshot_manifest, snapshot_manifest_bytes = _read_json(snapshot_manifest_path)
    if snapshot_manifest.get("snapshot_id") != snapshot_id:
        raise ValueError("留学Snapshot manifest身份不匹配")
    prepared_sources = [
        row for row in snapshot_manifest.get("sources", [])
        if isinstance(row, dict) and row.get("source_id") == SOURCE_ID
    ]
    if len(prepared_sources) != 1:
        raise ValueError("Snapshot必须且只能包含一个study_abroad_market来源")

    lineage_path = _safe_relative(
        workspace, pointer.get("source_lineage"), allowed_root=runs_root, label="source_lineage",
    )
    lineage, lineage_bytes = _read_json(lineage_path)
    if (lineage.get("schema_version") != SOURCE_SCHEMA
            or lineage.get("company_id") != expected_company_id
            or lineage.get("snapshot_id") != snapshot_id
            or lineage.get("run_id") != pointer.get("run_id")
            or lineage.get("through_date") != pointer.get("through_date")):
        raise ValueError("留学source_lineage身份不匹配")
    source_hashes = lineage.get("source_hashes")
    if not isinstance(source_hashes, dict) or source_hashes.get("source") != source_sha256:
        raise ValueError("留学source_lineage与当前来源SHA不匹配")

    run_root = lineage_path.parent
    raw_source = _safe_relative(run_root, lineage.get("origin_file"), allowed_root=run_root,
                                label="原始工作簿")
    prepared_source = _safe_relative(run_root, lineage.get("prepared_file"), allowed_root=run_root,
                                     label="规范化来源")
    roster_files = lineage.get("roster_files")
    if not isinstance(roster_files, dict):
        raise ValueError("留学source_lineage缺少冻结花名册路径")
    people_roster = _safe_relative(run_root, roster_files.get("people"), allowed_root=run_root,
                                    label="people roster")
    abroad_roster = _safe_relative(run_root, roster_files.get("abroad_people"), allowed_root=run_root,
                                    label="abroad roster")
    project_root = Path(__file__).resolve().parents[2]
    normalizer_path = project_root / "data_acquisition/jobs/build_study_abroad_warehouse.py"
    reader_path = project_root / "workspace_modeling/operations/study_abroad_source.py"
    lineage_files = {
        "source": raw_source,
        "people": people_roster,
        "abroad_people": abroad_roster,
        "normalizer": normalizer_path,
        "reader": reader_path,
    }
    for kind, path in lineage_files.items():
        if source_hashes.get(kind) != _sha256(path):
            raise ValueError(f"留学冻结来源hash与source_lineage不一致：{kind}")
    snapshot_source_sha = prepared_sources[0].get("sha256")
    if not isinstance(snapshot_source_sha, str) or _sha256(prepared_source) != snapshot_source_sha:
        raise ValueError("Snapshot规范化来源SHA与source_lineage不一致")

    bridge_path = workspace / "Work/Bridge/reference.json"
    bridge, _ = _read_json(bridge_path)
    if bridge.get("company_id") != expected_company_id:
        raise ValueError("旧Bridge不属于当前客户")
    reference_path = workspace / "Input/Reference/留学-FY26-资源表.xlsx"
    decision_path = Path(DECISIONS_PATH).resolve()
    sql_path = SQL_ROOT / "facts.sql"
    source_paths = _unique_paths([
        workspace_config_path, pointer_path, lineage_path, snapshot_manifest_path,
        raw_source, prepared_source, people_roster, abroad_roster,
        normalizer_path, reader_path,
        bridge_path, reference_path, decision_path, sql_path,
        Path(__file__), Path(__file__).with_name("study_abroad_channels.py"),
        Path(__file__).with_name("study_abroad_query.py"),
        Path(__file__).with_name("study_abroad_grade.py"),
        Path(__file__).with_name("facts.py"),
        Path(__file__).resolve().parents[2] / "data_acquisition/jobs/work_order_cleaning.py",
    ])
    fingerprints = {path: _sha256(path) for path in source_paths}
    return {
        "workspace_config_path": workspace_config_path,
        "workspace_config_bytes": workspace_config_bytes,
        "workspace_config": workspace_config,
        "pointer_path": pointer_path,
        "pointer_bytes": pointer_bytes,
        "pointer": pointer,
        "lineage_path": lineage_path,
        "lineage_bytes": lineage_bytes,
        "lineage": lineage,
        "warehouse": warehouse,
        "snapshot_manifest_path": snapshot_manifest_path,
        "snapshot_manifest_bytes": snapshot_manifest_bytes,
        "bridge": bridge,
        "reference_path": reference_path,
        "decision_path": decision_path,
        "source_paths": source_paths,
        "fingerprints": fingerprints,
        "source_through": source_through,
        "source_sha256": source_sha256,
    }


def _assert_sources_unchanged(context: dict[str, Any]) -> None:
    if context["workspace_config_path"].read_bytes() != context["workspace_config_bytes"]:
        raise ValueError("BI workspace身份/指针在留学facts读取期间发生变化")
    if context["pointer_path"].read_bytes() != context["pointer_bytes"]:
        raise ValueError("留学仓Snapshot指针在facts读取期间发生变化")
    if context["lineage_path"].read_bytes() != context["lineage_bytes"]:
        raise ValueError("留学source_lineage在facts读取期间发生变化")
    if context["snapshot_manifest_path"].read_bytes() != context["snapshot_manifest_bytes"]:
        raise ValueError("留学Snapshot manifest在facts读取期间发生变化")
    for path, before_sha in context["fingerprints"].items():
        if _sha256(path) != before_sha:
            raise ValueError(f"留学facts来源在读取期间发生变化：{path.name}")


def _validate_query_response(response: dict[str, Any], *, workspace: Path, run_id: str,
                             snapshot_id: str, manifest_bytes: bytes) -> dict[str, Any]:
    output_root = workspace / "Output/StudyAbroad"
    if (response.get("status") != "passed" or response.get("run_id") != run_id
            or response.get("snapshot_id") != snapshot_id):
        raise ValueError("留学facts受控查询回执身份不匹配")
    data = read_query_result(response, output_root=output_root)
    receipt_path = resolve_file(output_root / run_id, response["receipt"])
    receipt, _ = verify_receipt(receipt_path)
    expected_relations = {
        f"landing.{SOURCE_ID}__resources",
        f"landing.{SOURCE_ID}__contracts",
        f"landing.{SOURCE_ID}__languages",
    }
    if (receipt.get("run_id") != run_id or receipt.get("snapshot_id") != snapshot_id
            or receipt.get("referenced_source_ids") != [SOURCE_ID]
            or set(receipt.get("referenced_relations", [])) != expected_relations
            or receipt.get("snapshot_ref", {}).get("manifest_sha256") != hashlib.sha256(manifest_bytes).hexdigest()):
        raise ValueError("留学facts回执未绑定所选Snapshot和独立来源")
    return data


def _channel_result(row: dict[str, Any], *, bridge: dict[str, Any], reference: Any,
                    decisions: dict[str, Any], grade_resolution: dict[str, Any] | None = None):
    return legacy_channel(
        row.get("first_channel"), row.get("second_channel"), row.get("third_channel"),
        bridge, reference, decisions=decisions, grade_resolution=grade_resolution,
    )


def _is_ambiguous_market_activity(row: dict[str, Any], mapped: tuple[Any, ...]) -> bool:
    return (mapped[0] == "市场活动" and mapped[1] is None
            and _source_resource_id(row.get("resource_id")) is not None)


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

    segment = _text(row.get("segment_id"))
    team_id = {
        "study_abroad_online": "online_platform",
        "study_abroad_offline": "offline_market",
    }.get(segment)
    acquisition_mode = {
        "study_abroad_online": "online",
        "study_abroad_offline": "offline",
    }.get(segment, "supplemental")
    offline_channel_eligible = segment == "study_abroad_offline"
    owner = _text(row.get("owner")) or None
    personal_eligible = _boolean(row.get("personal_eligible"))
    owners = [] if segment == "international_market" or not personal_eligible or not owner else [owner]
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


def load_study_abroad_facts(*, workspace: Path, snapshot_id: str, run_id: str,
                            as_of_date: str) -> dict[str, Any]:
    """Read isolated study-abroad facts, retaining unresolved rows for reconciliation."""
    ws = Path(workspace).resolve()
    as_of = date.fromisoformat(as_of_date)
    if as_of <= START_DATE:
        raise ValueError("留学facts截止日必须晚于2026-06-01")
    company_config_path = ws / "Work/workspace.json"
    company_config, company_config_bytes = _read_json(company_config_path)
    company_id = _text(company_config.get("company_id"))
    if not company_id:
        raise ValueError("主工作区缺少company_id")
    context = _snapshot_sources(ws, snapshot_id, company_id)
    reference = load_work_order_reference(context["reference_path"])
    decisions = load_decisions(context["decision_path"])
    if decisions.get("company_id") != company_id:
        raise ValueError("留学渠道决定不属于当前客户")

    response = query_sample(
        workspace=ws,
        snapshot_id=snapshot_id,
        run_id=run_id,
        start_date=START_DATE.isoformat(),
        end_date=as_of.isoformat(),
        query_name="facts",
    )
    rows_data = _validate_query_response(
        response,
        workspace=ws,
        run_id=run_id,
        snapshot_id=snapshot_id,
        manifest_bytes=context["snapshot_manifest_bytes"],
    )
    source_rows = [dict(zip(rows_data["columns"], values)) for values in rows_data["rows"]]
    if not source_rows:
        raise ValueError("留学facts查询范围为空；不回退到BI留学明细")
    source_hashes = {_text(row.get("origin_sha256")) for row in source_rows}
    if source_hashes != {context["source_sha256"]}:
        raise ValueError("留学facts行来源SHA与当前隔离Snapshot指针不一致")

    diagnostics: Counter[str] = Counter(query_rows=len(source_rows))
    mapped_rows: list[tuple[dict[str, Any], tuple[Any, ...]]] = []
    grade_ids = []
    seen_grade_ids = set()
    for row in source_rows:
        initial = _channel_result(row, bridge=context["bridge"], reference=reference, decisions=decisions)
        mapped_rows.append((row, initial))
        if _is_ambiguous_market_activity(row, initial):
            resource_id = _source_resource_id(row.get("resource_id"))
            if resource_id and resource_id.isdigit() and resource_id not in seen_grade_ids:
                grade_ids.append(resource_id)
                seen_grade_ids.add(resource_id)
            elif resource_id and not resource_id.isdigit():
                diagnostics["grade_lookup_resource_id_unavailable"] += 1

    grade_evidence = None
    grade_resolutions: dict[str, dict[str, Any]] = {}
    receipts = [response]
    if grade_ids:
        grade_evidence = load_grade_evidence(
            workspace=ws,
            resource_ids=grade_ids,
            run_id=run_id,
            expected_company_id=company_id,
        )
        if grade_evidence.get("bi_workspace_sha256") != hashlib.sha256(company_config_bytes).hexdigest():
            raise ValueError("工单年级证据所用BI workspace与facts读取期间的主工作区不一致")
        grade_resolutions = grade_evidence["resolution"]
        receipts.append(grade_evidence["query_response"])
        diagnostics["grade_lookup_resources"] = len(grade_ids)
        for result in grade_resolutions.values():
            diagnostics[f"grade_lookup_{result['status']}"] += 1
        diagnostics["grade_lookup_bi_snapshot_id"] = grade_evidence["bi_snapshot_id"]

    facts: list[dict[str, Any]] = []
    seen_fact_ids: set[str] = set()
    event_dates = []
    for row, initial in mapped_rows:
        resource_id = _source_resource_id(row.get("resource_id"))
        channel = initial
        if _is_ambiguous_market_activity(row, initial) and resource_id in grade_resolutions:
            channel = _channel_result(
                row, bridge=context["bridge"], reference=reference, decisions=decisions,
                grade_resolution=grade_resolutions[resource_id],
            )
        fact = _make_fact(row, channel, diagnostics, reference)
        if fact is None:
            continue
        if fact["fact_id"] in seen_fact_ids:
            raise ValueError(f"留学facts存在重复fact_id：{fact['fact_id']}")
        seen_fact_ids.add(fact["fact_id"])
        if fact["event_date"] > min(context["source_through"], as_of - timedelta(days=1)).isoformat():
            raise ValueError("留学facts行超出显式来源截止日")
        event_dates.append(date.fromisoformat(fact["event_date"]))
        facts.append(fact)
    if not facts:
        raise ValueError("留学facts有效范围为空；不回退到BI留学明细")

    _assert_sources_unchanged(context)
    if company_config_path.read_bytes() != company_config_bytes:
        raise ValueError("主工作区身份在留学facts读取期间发生变化")
    cutoff = min(context["source_through"], as_of - timedelta(days=1))
    earliest = min(event_dates)
    coverage = {
        "snapshot_id": snapshot_id,
        "source_sha256": context["source_sha256"],
        "start_date": earliest.replace(day=1).isoformat(),
        "through_date": cutoff.isoformat(),
        "no_yoy": True,
        "cross_system_customers": "not_aligned",
    }
    diagnostics["facts"] = len(facts)
    diagnostics["resource_facts"] = diagnostics.get("resource_facts", 0)
    diagnostics["signature_facts"] = diagnostics.get("signature_facts", 0)
    return {
        "facts": facts,
        "coverage": coverage,
        "query_receipts": receipts,
        "source_paths": context["source_paths"],
        "diagnostics": dict(diagnostics),
    }


__all__ = ["load_study_abroad_facts"]
