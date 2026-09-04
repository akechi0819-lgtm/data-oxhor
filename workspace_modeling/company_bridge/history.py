from __future__ import annotations

import csv
import hashlib
import json
import posixpath
import re
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
from typing import Any

from workspace_modeling.business_pack.service import validate_pack
from workspace_modeling.company_bridge.service import (
    CANDIDATE_SCHEMA_VERSION,
    REJECTION_CODES,
)


SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "runtime_state",
    "task_workspace",
    "browser_profiles",
}
TEXT_EXTENSIONS = {
    ".csv",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".sql",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
TABLE_EXTENSIONS = {".csv", ".json", ".jsonl", ".xlsx", ".xlsm"}
REPORT_MARKERS = ("周报", "日报", "周会", "报告", "分析", "缺口", "看板", "复盘", "review", "report", "analysis")
SKILL_MARKERS = ("workflow", "methodology", "方法", "工作流", "验收", "架构", "施工", "playbook", "skill")

# These locators intentionally point to the legacy Super Agent corpus being
# audited. They are evidence coordinates, not imports or current runtime paths.
HISTORICAL_DATA_LAYER_DOCS = "data_layer/docs/数据接口对齐清单.md"
HISTORICAL_DATA_LAYER_TAXONOMY = "data_layer/docs/业务口径与Taxonomy.md"
HISTORICAL_DATA_LAYER_CASH = "data_layer/marts/cash.py"
HISTORICAL_DATA_LAYER_PRODUCT = "data_layer/marts/product_taxonomy.py"

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _candidate_id(*parts: object) -> str:
    seed = "|".join(str(part) for part in parts)
    return "cand_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _locator(path: str, suffix: str = "") -> str:
    return f"{path}{suffix}"


def _source_id(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    if "bi_downloads" in parts:
        if "现金" in path.name or "cash" in name:
            return "br_cash"
        if "工单" in path.name or "order" in name:
            return "br_work_orders"
        return "br_download"
    if "raw" in parts and "jenny" in parts:
        if "报名系统操作明细" in path.as_posix():
            return "tencent_docs_signup_ops"
        if "诺访" in path.as_posix():
            return "jenny_promise_visit"
        if "工单表" in path.name or "crm_order" in name:
            return "jenny_crm_orders"
        return "jenny_raw"
    return "historical_source"


def _source_kind(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    if "bi_downloads" in parts:
        return "bi_download"
    if "raw" in parts and "jenny" in parts:
        return "jenny_export"
    return "historical_table"


def _usable_raw_table(path: Path) -> bool:
    relative = path.as_posix().lower()
    name = path.name.lower()
    excluded_markers = (
        "cookie",
        "localstorage",
        "snapshot",
        "review",
        "复盘",
        "报告",
        "看板",
        "预览",
        "dashboard",
        "manifest",
        "target",
        "目标",
        "filter",
        "_ids",
        "screenshot",
        "meta",
    )
    if any(marker in relative or marker in name for marker in excluded_markers):
        return False
    if "bi_downloads" in relative:
        return "现金" in path.name or "工单" in path.name or "cash" in name or "order" in name
    if "/raw/jenny/orders/" in relative:
        return name.startswith("crm_orders")
    if "工单表_" in path.name and "模板" not in path.name:
        return True
    if "报名系统操作明细_" in path.name:
        return True
    return False


def _usable_source_sheet(sheet: str) -> bool:
    lowered = sheet.lower()
    return not any(
        marker in lowered
        for marker in ("看板", "目标", "预览", "汇总", "反馈", "监控", "拔点", "调优", "管理", "任务")
    )


def _read_text(path: Path, limit: int = 2_000_000) -> str:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    return data[:limit].decode("utf-8", errors="replace")


def _headers_from_csv(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            row = next(csv.reader(handle), [])
    except (OSError, UnicodeError, csv.Error):
        return []
    return _clean_headers(row)


def _clean_headers(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        result.append(text[:160])
    return result[:120]


def _headers_from_json(path: Path) -> list[str]:
    try:
        document = json.loads(_read_text(path))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    rows: list[Any]
    if isinstance(document, list):
        rows = document
    elif isinstance(document, dict):
        for key in ("rows", "data", "items", "records"):
            value = document.get(key)
            if isinstance(value, list):
                rows = value
                break
        else:
            rows = [document]
    else:
        return []
    for row in rows[:5]:
        if isinstance(row, dict):
            return _clean_headers(list(row))
    return []


def _xlsx_part_target(target: str) -> str:
    target = target.replace("\\", "/")
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", target))


def _xlsx_value(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(f".//{{{NS_MAIN}}}t"))
    value = cell.find(f"{{{NS_MAIN}}}v")
    raw = "" if value is None else (value.text or "")
    if cell_type == "s" and raw.isdigit() and int(raw) < len(shared):
        return shared[int(raw)]
    return raw


def _headers_from_xlsx(path: Path) -> list[tuple[str, list[str]]]:
    result: list[tuple[str, list[str]]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            shared: list[str] = []
            shared_name = "xl/sharedStrings.xml"
            if shared_name in archive.namelist():
                shared_root = ET.fromstring(archive.read(shared_name))
                shared = [
                    "".join(text.text or "" for text in item.findall(f".//{{{NS_MAIN}}}t"))
                    for item in shared_root.findall(f"{{{NS_MAIN}}}si")
                ]
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            relmap = {
                item.attrib["Id"]: item.attrib["Target"]
                for item in rels.findall(f"{{{NS_PACKAGE_REL}}}Relationship")
            }
            sheets = workbook.find(f"{{{NS_MAIN}}}sheets")
            if sheets is None:
                return []
            for sheet in sheets:
                relation_id = sheet.attrib.get(f"{{{NS_REL}}}id")
                target = relmap.get(relation_id or "")
                if not target:
                    continue
                sheet_path = _xlsx_part_target(target)
                if sheet_path not in archive.namelist():
                    continue
                root = ET.fromstring(archive.read(sheet_path))
                rows = root.findall(f".//{{{NS_MAIN}}}sheetData/{{{NS_MAIN}}}row")
                headers: list[str] = []
                for row in rows[:20]:
                    values = [_xlsx_value(cell, shared) for cell in row.findall(f"{{{NS_MAIN}}}c")]
                    headers = _clean_headers(values)
                    if headers:
                        break
                if headers:
                    result.append((str(sheet.attrib.get("name", "Sheet")), headers))
    except (OSError, KeyError, ValueError, ET.ParseError, zipfile.BadZipFile):
        return []
    return result


def _table_shapes(path: Path) -> list[tuple[str, list[str]]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        headers = _headers_from_csv(path)
        return [("", headers)] if headers else []
    if suffix in {".json", ".jsonl"}:
        headers = _headers_from_json(path)
        return [("", headers)] if headers else []
    if suffix in {".xlsx", ".xlsm"}:
        return _headers_from_xlsx(path)
    return []


def _is_output_file(relative: str) -> bool:
    lowered = relative.lower()
    return any(part in lowered for part in ("/storage/marts/", "/outputs/", "/reports/", "weekly_inputs"))


def _is_report_or_analysis(relative: str) -> bool:
    lowered = relative.lower()
    return any(marker.lower() in lowered for marker in REPORT_MARKERS)


def _is_skill_or_workflow(relative: str) -> bool:
    lowered = relative.lower()
    return any(marker.lower() in lowered for marker in SKILL_MARKERS) or "/docs/" in lowered and not "data_layer/docs/" in lowered


def _is_bridge_rule(relative: str) -> bool:
    lowered = relative.lower()
    return (
        relative == HISTORICAL_DATA_LAYER_TAXONOMY
        or relative == HISTORICAL_DATA_LAYER_DOCS
        or "methodology/config/business_taxonomy/" in relative
    )


def _rejection(relative: str, code: str, reason: str) -> dict[str, Any]:
    if code not in REJECTION_CODES:
        code = "UNCLASSIFIED_CONTENT"
    return {
        "source_locator": relative,
        "reason_code": code,
        "reason": reason,
        "evidence_refs": [relative],
    }


def _candidate(
    *,
    candidate_type: str,
    proposal: dict[str, Any],
    source_locator: str,
    evidence_summary: str,
    evidence_refs: list[str],
    status: str = "proposed",
    decision_note: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "candidate_id": _candidate_id(candidate_type, source_locator, json.dumps(proposal, ensure_ascii=False, sort_keys=True)),
        "candidate_type": candidate_type,
        "source_locator": source_locator,
        "evidence_summary": evidence_summary,
        "proposed_mapping_or_rule": proposal,
        "status": status,
        "evidence_refs": list(dict.fromkeys(evidence_refs))[:10],
    }
    if decision_note:
        value["decision_note"] = decision_note
    return value


def _raw_source_candidates(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, tuple[str, ...]], list[tuple[str, Path]]] = {}
    for path in files:
        relative = _relative(root, path)
        if "storage/raw/" not in relative or path.suffix.lower() not in TABLE_EXTENSIONS or not _usable_raw_table(path):
            continue
        for sheet, headers in _table_shapes(path):
            if not headers or (sheet and not _usable_source_sheet(sheet)):
                continue
            key = (_source_id(path), sheet, tuple(headers))
            grouped.setdefault(key, []).append((relative, path))
    for (source_id, sheet, headers), evidence in sorted(grouped.items()):
        relative = evidence[0][0]
        sheet_suffix = f"#sheet={sheet}" if sheet else ""
        candidates.append(
            _candidate(
                candidate_type="source_contract",
                proposal={
                    "source_id": source_id,
                    "filename": Path(relative).name,
                    **({"sheet_name": sheet} if sheet else {}),
                    "field_names": list(headers),
                    "source_kind": _source_kind(evidence[0][1]),
                },
                source_locator=_locator(relative, sheet_suffix),
                evidence_summary=f"自动登记文件、Sheet 和技术表头结构；同结构样本 {len(evidence)} 个。",
                evidence_refs=[item[0] for item in evidence[:10]],
                status="confirmed",
                decision_note="仅确认客观结构，不确认企业语义映射。",
            )
        )
    return candidates


def _field_candidates() -> list[dict[str, Any]]:
    source = HISTORICAL_DATA_LAYER_DOCS
    rows = [
        ("br_cash", "clean.cash_ledger", "business_date", "dimension", "time.cash_transaction_date", "现金 canonical schema 的业务日期角色。"),
        ("br_cash", "clean.cash_ledger", "booked_cash_income", "concept", "cash.payment", "报入现金收入是现金流入候选；负数行仍需按业务形式/原因区分调整与退款。"),
        ("br_cash", "clean.cash_ledger", "cash_income", "concept", "cash.net_cash", "现金收入是净现金的有符号流水输入；不能仅凭负号认定退款。"),
        ("br_cash", "clean.cash_ledger", "campus", "dimension", "organization.campus", "现金 canonical schema 的校区字段。"),
        ("br_cash", "clean.cash_ledger", "project_name", "dimension", "offering.product", "现金 canonical schema 的产品字段。"),
        ("br_cash", "clean.cash_ledger", "student_id", "concept", "customer.student", "现金 canonical schema 的学员编号字段。"),
        ("br_cash", "clean.cash_ledger", "student_type", "dimension", "customer.student_type", "现金 canonical schema 的客户生命周期字段。"),
        ("br_work_orders", "clean.work_order_current", "assign_date", "dimension", "time.stage_occurrence_date", "工单 cohort 使用分配日期；日期角色需由企业确认。"),
        ("br_work_orders", "clean.work_order_current", "campus", "dimension", "organization.campus", "工单 canonical schema 的校区字段。"),
        ("br_work_orders", "clean.work_order_current", "order_id", "concept", "contract.training_contract", "工单 ID 与培训合同/订单关系的候选，需确认一单一行语义。"),
    ]
    return [
        _candidate(
            candidate_type="field_mapping",
            proposal={
                "source_id": source_id,
                "relation": relation,
                "field_name": field_name,
                "target_type": target_type,
                "target_id": target_id,
                "mapping_role": "historical_canonical_schema",
            },
            source_locator=f"{source}#canonical_schema.{field_name}",
            evidence_summary=summary,
            evidence_refs=[source],
        )
        for source_id, relation, field_name, target_type, target_id, summary in rows
    ]


def _daily_operation_candidates(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    """Extract direction candidates from the signup-operations daily workbook.

    The daily workbook carries the business operation and reason fields that
    are absent from the compact cash canonical schema.  This is deliberately a
    candidate-only extraction: the formal Bridge can consume these rules only
    after the Data Foundation Snapshot preserves the required normalized
    fields.
    """

    evidence: dict[str, list[str]] = {"main": [], "transfer": [], "refund": []}
    for path in files:
        if path.suffix.lower() not in {".xlsx", ".xlsm"} or not path.name.startswith("报名系统操作明细_"):
            continue
        relative = _relative(root, path)
        for sheet, headers in _table_shapes(path):
            header_set = set(headers)
            locator = f"{relative}#sheet={sheet}"
            if {"业务形式", "具体原因", "实缴金额"}.issubset(header_set):
                evidence["main"].append(locator)
            if {"业务形式", "具体原因", "退班金额", "转班金额"}.issubset(header_set):
                evidence["transfer"].append(locator)
            if {"业务类型", "退费金额", "操作备注"}.issubset(header_set):
                evidence["refund"].append(locator)

    refs = [item for kind in ("main", "transfer", "refund") for item in sorted(evidence[kind])[:2]]
    if not refs:
        return []
    common_refs = refs + [
        HISTORICAL_DATA_LAYER_CASH,
        HISTORICAL_DATA_LAYER_TAXONOMY,
    ]
    candidates: list[dict[str, Any]] = []

    if evidence["main"]:
        source_locator = f"{sorted(evidence['main'])[0]}#cash.net_cash_signed_sum"
        candidates.append(
            _candidate(
                candidate_type="normalization_rule",
                proposal={
                    "source_id": "tencent_docs_signup_ops",
                    "relation": "clean.cash_ledger",
                    "field_name": "cash_income",
                    "operation": "parse_amount",
                    "parameters": {
                        "source_field_aliases": ["现金收入", "报入现金收入", "实缴金额", "cash_income", "booked_cash_income"],
                        "signed_value_policy": "preserve",
                        "aggregation_role": "cash.net_cash",
                        "negative_value_is_not_refund_by_itself": True,
                    },
                    "target_type": "concept",
                    "target_id": "cash.net_cash",
                },
                source_locator=source_locator,
                evidence_summary="日报明细保留正负实缴金额；净现金按有符号金额直接求和，负数本身不构成退款判定。",
                evidence_refs=common_refs,
            )
        )

    refund_evidence = sorted(evidence["main"] + evidence["refund"])
    if refund_evidence:
        source_locator = f"{refund_evidence[0]}#direction=explicit_refund"
        candidates.append(
            _candidate(
                candidate_type="normalization_rule",
                proposal={
                    "source_id": "tencent_docs_signup_ops",
                    "relation": "clean.cash_ledger",
                    "field_name": "business_type",
                    "operation": "map_enum",
                    "parameters": {
                        "source_value": "explicit_refund_signal",
                        "source_field_aliases": ["业务形式", "业务类型"],
                        "amount_field_aliases": ["现金收入", "报入现金收入", "实缴金额", "退费金额"],
                        "amount_sign_policy": "not_decisive_when_explicit_refund_signal",
                        "business_form_values": ["退班退费", "储值账户退费", "返款退费", "倒优惠退费"],
                        "reason_field_aliases": ["具体原因", "备注", "操作备注"],
                        "reason_keywords": ["退班退费", "申请退费", "孩子不上了，退费", "要退费"],
                        "exclude_keywords": ["退班放储值", "返款放储值", "退费到储值", "转班", "转出", "转入", "重报", "放储值"],
                        "precedence": "explicit_refund_over_adjustment",
                        "normalized_value": "refund",
                    },
                    "target_type": "dimension",
                    "target_id": "transaction.direction",
                },
                source_locator=source_locator,
                evidence_summary="只有退班退费、储值账户退费、返款退费等明确业务类型，或排除储值/转班后的明确退费原因，才候选为退款；不按负号泛化。",
                evidence_refs=common_refs,
            )
        )
        candidates.append(
            _candidate(
                candidate_type="normalization_rule",
                proposal={
                    "source_id": "tencent_docs_signup_ops",
                    "relation": "clean.cash_ledger",
                    "field_name": "refund_reason",
                    "operation": "map_enum",
                    "parameters": {
                        "source_value": "explicit_refund_reason",
                        "source_field_aliases": ["业务形式", "业务类型", "具体原因", "备注", "操作备注"],
                        "eligible_when": "explicit_refund_signal",
                        "preserve_source_text": True,
                        "normalized_value": "confirmed_refund_reason",
                    },
                    "target_type": "dimension",
                    "target_id": "transaction.refund_reason",
                },
                source_locator=f"{refund_evidence[0]}#refund_reason=explicit_only",
                evidence_summary="退款率需要保留并按明确退费业务类型/原因分组；普通负数、转班和重报不能代替退款原因。",
                evidence_refs=common_refs,
            )
        )

    if evidence["main"] or evidence["transfer"]:
        source_locator = f"{sorted(evidence['main'] + evidence['transfer'])[0]}#direction=transfer_or_reallocation"
        candidates.append(
            _candidate(
                candidate_type="normalization_rule",
                proposal={
                    "source_id": "tencent_docs_signup_ops",
                    "relation": "clean.cash_ledger",
                    "field_name": "business_type",
                    "operation": "map_enum",
                    "parameters": {
                        "source_value": "transfer_or_reallocation_signal",
                        "source_field_aliases": ["业务形式"],
                        "amount_field_aliases": ["现金收入", "报入现金收入", "实缴金额", "退班金额", "转班金额"],
                        "business_form_values": ["转出", "转入", "退班放储值", "充入储值", "返款放储值", "组合类入班", "组合类离班"],
                        "reason_keywords": ["转班", "退班重报", "重报", "转入", "转出", "放储值"],
                        "only_when_no_explicit_refund_signal": True,
                        "normalized_value": "adjustment",
                    },
                    "target_type": "dimension",
                    "target_id": "transaction.direction",
                },
                source_locator=source_locator,
                evidence_summary="转出、转入、退班放储值、转班/退班重报等负数先作为资金调整或重报；仅在没有明确退款信号时适用。",
                evidence_refs=common_refs,
            )
        )
    return candidates


def _mapping_csv_candidates(root: Path, path: Path) -> list[dict[str, Any]]:
    relative = _relative(root, path)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error):
        return []
    candidates: list[dict[str, Any]] = []
    if path.name == "campus_mapping.csv":
        for row in rows:
            raw = str(row.get("raw_name", "")).strip()
            normalized = str(row.get("revenue_campus", "")).strip()
            display = str(row.get("ops_display_name", "")).strip()
            if not raw or not normalized:
                continue
            candidates.append(
                _candidate(
                    candidate_type="normalization_rule",
                    proposal={
                        "source_id": "br_cash",
                        "relation": "clean.cash_ledger",
                        "field_name": "campus",
                        "operation": "map_enum",
                        "parameters": {"source_value": raw, "normalized_value": normalized, "display_value": display},
                        "target_type": "dimension",
                        "target_id": "organization.campus",
                    },
                    source_locator=f"{relative}#raw_name={raw}",
                    evidence_summary="校区长期别名映射候选；未知值按原项目规则阻断正式刷新。",
                    evidence_refs=[relative],
                )
            )
    elif path.name == "channel_mapping.csv":
        for row in rows:
            source_value = str(row.get("二级渠道", "")).strip()
            merged = str(row.get("并归渠道", "")).strip()
            standard = str(row.get("标准展示渠道", "") or row.get("周会展示渠道", "")).strip()
            normalized = merged or standard
            if not source_value or not normalized:
                continue
            active_passive = str(row.get("主被动", "")).strip()
            channel_l1 = str(row.get("一级渠道", "")).strip()
            candidates.append(
                _candidate(
                    candidate_type="normalization_rule",
                    proposal={
                        "source_id": "br_work_orders",
                        "relation": "clean.work_order_current",
                        "field_name": "channel_l2",
                        "operation": "map_enum",
                        "parameters": {
                            "active_passive": active_passive,
                            "channel_l1": channel_l1,
                            "source_value": source_value,
                            "normalized_value": normalized,
                            "normalized_field": "并归渠道" if merged else "标准展示渠道",
                            "display_value": standard,
                            "is_tmk": str(row.get("是否TMK", "")).strip(),
                        },
                        "target_type": "dimension",
                        "target_id": "acquisition.channel",
                    },
                    source_locator=f"{relative}#主被动={active_passive}&一级渠道={channel_l1}&二级渠道={source_value}",
                    evidence_summary="渠道先按主被动+一级渠道+二级渠道命中，并以并归渠道作为规范值；标准展示列只作展示/回退。",
                    evidence_refs=[relative],
                )
            )
    return candidates


def _product_candidates(root: Path, path: Path) -> list[dict[str, Any]]:
    relative = _relative(root, path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    candidates: list[dict[str, Any]] = []
    in_rows = False
    current: dict[str, str] = {}
    for line in lines + ["- raw_product: __end__"]:
        stripped = line.strip()
        if stripped == "rows:":
            in_rows = True
            continue
        if not in_rows:
            continue
        if stripped.startswith("- raw_product:"):
            if current and current.get("raw_product") and current.get("product"):
                raw = current["raw_product"]
                product = current["product"]
                candidates.append(
                    _candidate(
                        candidate_type="normalization_rule",
                        proposal={
                            "source_id": "br_cash",
                            "relation": "clean.cash_ledger",
                            "field_name": "project_name",
                            "operation": "map_enum",
                            "parameters": {"source_value": raw, "normalized_value": product, "product_line": current.get("product_line", "")},
                            "target_type": "dimension",
                            "target_id": "offering.product",
                        },
                        source_locator=f"{relative}#raw_product={raw}",
                        evidence_summary="企业产品并规候选；剑五 KET/PET 等条件规则仍需单独确认。",
                        evidence_refs=[relative],
                    )
                )
            current = {"raw_product": stripped.split(":", 1)[1].strip()}
        elif current and re.match(r"^(product|product_line|product_segment|product_group):", stripped):
            key, value = stripped.split(":", 1)
            current[key] = value.strip()
    if (
        "conditional_product_rules:" in "\n".join(lines)
        and "raw_product: 剑五" in "\n".join(lines)
        and "class_type_in:" in "\n".join(lines)
        and "- KET" in "\n".join(lines)
        and "- PET" in "\n".join(lines)
    ):
        candidates.append(
            _candidate(
                candidate_type="normalization_rule",
                proposal={
                    "source_id": "br_cash",
                    "relation": "clean.cash_ledger",
                    "field_name": "project_name",
                    "operation": "map_enum",
                    "parameters": {
                        "condition": {
                            "raw_product": "剑五",
                            "class_type_in": ["KET", "PET"],
                        },
                        "set": {
                            "product_from": "class_type",
                            "product_line": "提能线",
                            "product_segment": "小高",
                            "product_group_from": "class_type",
                        },
                        "otherwise": "keep_base_taxonomy_and_warn",
                        "source_field_aliases": ["product", "project_name", "raw_product"],
                        "condition_field_aliases": ["班型", "class_type"],
                    },
                    "target_type": "dimension",
                    "target_id": "offering.product",
                },
                source_locator=f"{relative}#conditional_product_rules.raw_product=剑五",
                evidence_summary="标准现金产品字段保留 raw_product=剑五；二次读取班型 KET/PET 后拆成独立产品，其他班型保留剑五并告警。",
                evidence_refs=[
                    relative,
                    HISTORICAL_DATA_LAYER_PRODUCT,
                    HISTORICAL_DATA_LAYER_TAXONOMY,
                ],
            )
        )
    return candidates


def _unresolved_candidates() -> list[dict[str, Any]]:
    source = HISTORICAL_DATA_LAYER_TAXONOMY
    return [
        _candidate(
            candidate_type="unresolved",
            proposal={
                "source_id": "br_cash",
                "relation": "clean.cash_ledger",
                "field_name": "payer_id",
                "blocked_target_type": "concept",
                "blocked_target_id": "customer.payer",
                "reason": "当前 canonical cash schema 明确有 student_id，但未证明存在独立付款人标识；付款人数不能静默用学员代替。",
            },
            source_locator=f"{source}#cash_payer_vs_student",
            evidence_summary="付款人和学员是行业上可不同的主体，当前企业字段未形成确认映射。",
            evidence_refs=[source, HISTORICAL_DATA_LAYER_DOCS],
            status="proposed",
        ),
        _candidate(
            candidate_type="unresolved",
            proposal={
                "source_id": "br_cash",
                "relation": "clean.cash_ledger",
                "field_name": "cash_income",
                "blocked_target_type": "concept",
                "blocked_target_id": "cash.refund",
                "reason": "现金收入可按有符号金额核算净现金，但退款方向必须依赖明确业务形式/原因；负号本身不能确认 cash.refund。",
            },
            source_locator=f"{source}#cash_sign_and_refund",
            evidence_summary="净现金的符号处理已有候选，退款率所需的明确退款识别仍需确认并依赖日报业务字段。",
            evidence_refs=[source, HISTORICAL_DATA_LAYER_CASH],
            status="proposed",
        ),
    ]


def _scan_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in relative_parts):
            continue
        if path.suffix.lower() in TEXT_EXTENSIONS | {".xlsx", ".xlsm"}:
            files.append(path)
    return sorted(files, key=lambda item: item.as_posix())


def scan_history(
    *,
    root: Path,
    company_id: str,
    candidate_set_id: str,
    pack: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    root = root.resolve()
    output_path = output_path.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"historical scan root does not exist: {root}")
    if output_path == root or root in output_path.parents:
        raise ValueError("historical scan output must be outside the scanned root")
    pack_validation = validate_pack(pack)
    if pack_validation["status"] != "passed":
        raise ValueError("historical scan requires a valid Pack")

    files = _scan_files(root)
    candidates = _raw_source_candidates(root, files)
    candidates.extend(_field_candidates())
    candidates.extend(_daily_operation_candidates(root, files))
    for path in files:
        relative = _relative(root, path)
        if path.name in {"campus_mapping.csv", "channel_mapping.csv"} and "business_taxonomy" in relative:
            candidates.extend(_mapping_csv_candidates(root, path))
        if path.name == "business_taxonomy.yaml" and "business_taxonomy" in relative:
            candidates.extend(_product_candidates(root, path))
    candidates.extend(_unresolved_candidates())

    rejections: list[dict[str, Any]] = [
        _rejection(
            "data_layer/docs/数据接口对齐清单.md#canonical_schema.project_name.work_order",
            "UNCLASSIFIED_CONTENT",
            "工单 project_name 只表达咨询/资源入口意向，不能代替现金表中的最终购买产品；该内容不进入 Bridge 产品映射。",
        ),
        _rejection(
            "data_layer/docs/业务口径与Taxonomy.md#enum.student_type",
            "UNCLASSIFIED_CONTENT",
            "新生/老生是企业原始学员类型字段；不能自动翻译成新签/续费。Bridge 只保留字段映射候选，不吸收该生命周期枚举映射。",
        ),
        _rejection(
            "data_layer/docs/业务口径与Taxonomy.md#enum.transaction_type",
            "UNCLASSIFIED_CONTENT",
            "历史 canonical schema 没有被证实的 transaction_type 字段；收款、退款、转班等方向应从日报业务形式/具体原因候选中确认，不能凭宽泛枚举进入 Bridge。",
        ),
        _rejection(
            "data_layer/docs/业务口径与Taxonomy.md#new_signup_vs_renewal",
            "UNCLASSIFIED_CONTENT",
            "新签/续费不是当前企业最稳定的二分字段；续费收入可能由顾问收取，不能替代相对干净的新生/老生原始字段，也不进入 Bridge 枚举映射。",
        ),
        _rejection(
            "methodology/config/business_taxonomy/business_taxonomy.yaml#cash_headcount_rule",
            "UNCLASSIFIED_CONTENT",
            "1500 是学员+班级有效报名人头的分析侧资格门槛，不是付款人身份阈值；当前不能挂到 Pack 的 cash.payer_count，也不进入 Bridge。",
        ),
        _rejection(
            "data_layer/docs/业务口径与Taxonomy.md#section-4-default-student-filter",
            "SKILL_CONTENT",
            "默认只看新生是运行/分析筛选偏好，不是企业字段语义，按用户确认不进入 Bridge。",
        ),
    ]
    candidate_sources = {
        str(candidate.get("source_locator", "")).split("#", 1)[0]
        for candidate in candidates
        if isinstance(candidate, dict)
    }
    for path in files:
        relative = _relative(root, path)
        if _is_output_file(relative):
            rejections.append(_rejection(relative, "SINGLE_ANALYSIS_CONCLUSION", "历史结果/报表/看板只代表一次运行或一次分析，不进入 Company Bridge。"))
            continue
        if "storage/raw/" in relative and "诺访" in relative and not _usable_raw_table(path):
            rejections.append(_rejection(relative, "SKILL_CONTENT", "诺访作战、任务板和过程回访资产属于运行流程/Skill，不进入本次净现金 Bridge。"))
            continue
        if _is_skill_or_workflow(relative) and not _is_bridge_rule(relative):
            rejections.append(_rejection(relative, "SKILL_CONTENT", "分析步骤、工作流和验收说明属于 Skill/操作文档，不进入 Company Bridge。"))
            continue
        if _is_report_or_analysis(relative) and not _is_bridge_rule(relative):
            rejections.append(_rejection(relative, "ANALYSIS_REPORT", "报告、周报、异常分析和建议属于单次分析交付，不进入 Company Bridge。"))
            continue
        if _is_bridge_rule(relative) and relative not in candidate_sources:
            rejections.append(_rejection(relative, "UNCLASSIFIED_CONTENT", "该企业配置被识别为可能的 Bridge 证据，但当前没有专用抽取器，不能静默进入正式合同。"))
            continue
        if path.name == "business_taxonomy.yaml":
            try:
                taxonomy_text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                taxonomy_text = ""
            if "default_student_type:" in taxonomy_text:
                rejections.append(
                    _rejection(
                        f"{relative}#cash_headcount_rule.default_student_type",
                        "UNCLASSIFIED_CONTENT",
                        "默认新生筛选是运行/分析偏好，不进入 Company Bridge 正式口径。",
                    )
                )
        if path.suffix.lower() not in TEXT_EXTENSIONS | {".xlsx", ".xlsm"}:
            rejections.append(_rejection(relative, "UNSUPPORTED_BINARY", "扫描器只登记受控文本和表格结构，其他二进制不进入候选。"))
            continue
        if not _is_bridge_rule(relative) and "storage/raw/" not in relative and not path.name.endswith((".csv", ".xlsx", ".xlsm")):
            rejections.append(_rejection(relative, "UNCLASSIFIED_CONTENT", "未识别为企业字段、枚举、清洗规则或可验证源结构。"))

    candidates.sort(key=lambda item: item["candidate_id"])
    rejections.sort(key=lambda item: item["source_locator"])
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "candidate_set_role": "historical_scan",
        "candidate_set_id": candidate_set_id,
        "company_id": company_id,
        "pack_ref": {"pack_id": pack["pack_id"], "pack_version": pack["pack_version"]},
        "candidates": candidates,
        "rejections": rejections,
        "summary": {"candidate_count": len(candidates), "rejection_count": len(rejections)},
    }
