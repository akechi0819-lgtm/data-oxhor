"""Resolve confirmed market activity channels from linked BI work-order grades."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from data_platform.query.evidence import read_query_result, resolve_file, verify_receipt
from data_platform.query.service import execute_query


GRADE_FIELDS = (
    ("grade_attr", "年级属性"),
    ("corrected_grade", "年级校正"),
    ("current_grade", "目前年级"),
    ("grade_name", "年级名称"),
)
RESOURCE_ID_FIELDS = ("资源id", "资源-资源ID")
_RESOURCE_ID_PREFIX = re.compile(r"^(?:资源\s*ID|ID)\s*[:：]\s*", re.IGNORECASE)
_RESOURCE_ID_NUMBER = re.compile(r"^\d+(?:\.0+)?$")
_SECONDARY_SCHOOL_GRADE = re.compile(r"(?<!\d)(?:[7-9]|1[0-2])年级")


def _normalize_resource_id(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text in {"/", "None", "none", "null", "nan"}:
        return None
    text = _RESOURCE_ID_PREFIX.sub("", text).strip()
    if not _RESOURCE_ID_NUMBER.fullmatch(text):
        return None
    if "." in text:
        text = text.split(".", 1)[0]
    return text


def _stages_in_value(value: Any) -> set[str]:
    if value is None:
        return set()
    text = re.sub(r"\s+", "", str(value)).casefold()
    if not text:
        return set()

    # These labels do not establish either channel, even when they contain 大学.
    if any(token in text for token in ("大学以下", "小学", "青少", "学龄前", "未确认", "待确认")):
        return set()
    if text in {"未知", "未归类", "不详", "其他", "其它", "none", "null", "nan", "n/a", "无"}:
        return set()

    stages: set[str] = set()
    if any(token in text for token in ("本科", "大专", "研究生", "硕士", "博士", "高校", "大学")):
        stages.add("college")
    if any(token in text for token in ("大一", "大二", "大三", "大四", "大五")):
        stages.add("college")
    if any(token in text for token in ("初中", "初一", "初二", "初三", "高中", "高一", "高二", "高三", "中学")):
        stages.add("middle")
    if _SECONDARY_SCHOOL_GRADE.search(text):
        stages.add("middle")
    return stages


def stage_from_values(*values: Any) -> str | None:
    """Return one recognized stage; ambiguous and unsupported values stay unknown."""
    stages: set[str] = set()
    for value in values:
        stages.update(_stages_in_value(value))
    return next(iter(stages)) if len(stages) == 1 else None


def _requested_ids(resource_ids: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in resource_ids:
        resource_id = _normalize_resource_id(raw)
        if resource_id is None:
            raise ValueError(f"资源ID无效：{raw!r}")
        if resource_id not in seen:
            result.append(resource_id)
            seen.add(resource_id)
    if not result:
        raise ValueError("至少需要一个明确资源ID")
    if len(result) > 1000:
        raise ValueError("单次最多查询1000个资源ID")
    return result


def resolve_grade_rows(rows: list[dict[str, Any]], resource_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Map requested resources to channel labels only when BI grade evidence agrees."""
    requested = _requested_ids(resource_ids)
    evidence: dict[str, dict[str, Any]] = {
        resource_id: {"stages": set(), "work_order_ids": []} for resource_id in requested
    }
    for row in rows:
        matched_ids = {
            resource_id
            for resource_id in (
                _normalize_resource_id(row.get("resource_id")),
                _normalize_resource_id(row.get("alternate_resource_id")),
            )
            if resource_id in evidence
        }
        if not matched_ids:
            continue

        work_order_id = str(row.get("work_order_id") or "").strip()
        stages: set[str] = set()
        for field, _ in GRADE_FIELDS:
            stages.update(_stages_in_value(row.get(field)))
        for resource_id in requested:
            if resource_id not in matched_ids:
                continue
            item = evidence[resource_id]
            item["stages"].update(stages)
            if work_order_id and work_order_id not in item["work_order_ids"]:
                item["work_order_ids"].append(work_order_id)

    result = {}
    for resource_id in requested:
        item = evidence[resource_id]
        stages = item["stages"]
        if len(stages) > 1:
            status, second_channel = "grade_conflict", None
        elif stages == {"college"}:
            status, second_channel = "resolved", "高校活动"
        elif stages == {"middle"}:
            status, second_channel = "resolved", "中学活动"
        else:
            status, second_channel = "grade_missing", None
        result[resource_id] = {
            "second_channel": second_channel,
            "status": status,
            "work_order_ids": item["work_order_ids"],
        }
    return result


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _header_fields(sheet: dict[str, Any]) -> dict[str, list[str]]:
    columns = sheet.get("header_columns")
    if not isinstance(columns, list):
        return {}
    result: dict[str, list[str]] = defaultdict(list)
    for column in columns:
        if not isinstance(column, dict):
            continue
        original = column.get("original_name")
        technical = column.get("technical_name")
        if isinstance(original, str) and original and isinstance(technical, str) and technical:
            result[original].append(technical)
    return dict(result)


def _field(fields: dict[str, list[str]], original: str, *, required: bool = False) -> str | None:
    matches = fields.get(original, [])
    if len(matches) > 1:
        raise ValueError(f"Snapshot字段表头重复，不能安全选择：{original}")
    if not matches:
        if required:
            raise ValueError(f"Snapshot缺少必需字段：{original}")
        return None
    return matches[0]


def _sql_column(fields: dict[str, list[str]], original: str, alias: str) -> str:
    matches = fields.get(original, [])
    if len(matches) > 1:
        raise ValueError(f"Snapshot字段表头重复，不能安全选择：{original}")
    technical = matches[0] if matches else None
    if technical is None:
        return f"NULL::VARCHAR AS {_quote_identifier(alias)}"
    return f"NULLIF(TRIM(CAST({_quote_identifier(technical)} AS VARCHAR)), '') AS {_quote_identifier(alias)}"


def _id_variants(resource_id: str) -> list[str]:
    return [
        resource_id,
        f"{resource_id}.0",
        f"ID:{resource_id}", f"ID: {resource_id}", f"ID：{resource_id}",
        f"id:{resource_id}", f"id: {resource_id}", f"id：{resource_id}",
        f"资源ID:{resource_id}", f"资源ID：{resource_id}",
        f"资源 ID: {resource_id}", f"资源 ID：{resource_id}",
    ]


def _source_table(manifest: dict[str, Any]) -> tuple[str, dict[str, list[str]]]:
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Snapshot来源清单无效")
    matches = [row for row in sources if isinstance(row, dict) and row.get("source_id") == "br_work_orders"]
    if len(matches) != 1:
        raise ValueError("Snapshot必须且只能声明一个br_work_orders来源")
    sheets = matches[0].get("sheets")
    if not isinstance(sheets, list):
        raise ValueError("Snapshot的br_work_orders缺少sheet清单")

    candidates = []
    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue
        table = sheet.get("target_table")
        if not isinstance(table, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,63}", table):
            continue
        fields = _header_fields(sheet)
        resource_fields = [name for name in RESOURCE_ID_FIELDS if len(fields.get(name, [])) == 1]
        if (len(fields.get("ID", [])) == 1 and resource_fields
                and any(len(fields.get(original, [])) == 1 for _, original in GRADE_FIELDS)):
            candidates.append((table, fields))
    if len(candidates) != 1:
        raise ValueError("br_work_orders中必须有且只能有一个包含资源键、ID和年级字段的sheet")
    return candidates[0]


def _build_query(table: str, fields: dict[str, list[str]], resource_ids: list[str]) -> tuple[str, list[str]]:
    primary_original = next((name for name in RESOURCE_ID_FIELDS if len(fields.get(name, [])) == 1), None)
    if primary_original is None:
        raise ValueError("Snapshot缺少资源ID字段")
    alternate_original = next((
        name for name in RESOURCE_ID_FIELDS
        if name != primary_original and len(fields.get(name, [])) == 1
    ), None)
    primary_technical = _field(fields, primary_original, required=True)
    alternate_technical = _field(fields, alternate_original) if alternate_original else None
    _field(fields, "ID", required=True)

    select = [
        "source_row_number AS source_row_number",
        f"{_sql_column(fields, primary_original, 'resource_id')}",
        (f"{_sql_column(fields, alternate_original, 'alternate_resource_id')}"
         if alternate_original else 'NULL::VARCHAR AS "alternate_resource_id"'),
        f"{_sql_column(fields, 'ID', 'work_order_id')}",
    ]
    for alias, original in GRADE_FIELDS:
        select.append(_sql_column(fields, original, alias))

    key_columns = [primary_technical]
    if alternate_technical:
        key_columns.append(alternate_technical)
    variants = list(dict.fromkeys(value for resource_id in resource_ids for value in _id_variants(resource_id)))
    placeholders = ", ".join("?" for _ in variants)
    predicates = [
        f"TRIM(CAST({_quote_identifier(column)} AS VARCHAR)) IN ({placeholders})"
        for column in key_columns
    ]
    sql = (
        "SELECT " + ",\n       ".join(select) +
        f"\nFROM landing.{_quote_identifier(table)}\nWHERE " + " OR ".join(predicates) +
        "\nORDER BY source_row_number"
    )
    return sql, variants * len(key_columns)


def load_grade_evidence(
    *, workspace: Path, resource_ids: list[str], run_id: str, expected_company_id: str,
) -> dict[str, Any]:
    """Read only requested work-order grade evidence from the explicit BI Snapshot."""
    ws = Path(workspace).resolve()
    requested = _requested_ids(resource_ids)
    if not isinstance(expected_company_id, str) or not expected_company_id.strip():
        raise ValueError("必须提供预期company_id")

    workspace_config_path = ws / "Work/workspace.json"
    workspace_config_bytes = workspace_config_path.read_bytes()
    workspace_config = json.loads(workspace_config_bytes)
    if workspace_config.get("company_id") != expected_company_id:
        raise ValueError("BI工作区company_id与预期公司不匹配")
    snapshot_id = workspace_config.get("current_snapshot_id")
    warehouse_relative = workspace_config.get("current_warehouse_path")
    if not isinstance(snapshot_id, str) or not snapshot_id or not isinstance(warehouse_relative, str):
        raise ValueError("BI工作区缺少显式当前Snapshot指针")
    relative_path = Path(warehouse_relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("BI warehouse路径必须是工作区内显式相对路径")
    warehouse = (ws / relative_path).resolve()
    if (not warehouse.is_relative_to((ws / "Work/Runs").resolve())
            or warehouse.name != "warehouse.duckdb" or warehouse.parent.name != snapshot_id):
        raise ValueError("BI warehouse路径与显式Snapshot不匹配")
    if not warehouse.is_file():
        raise ValueError("BI warehouse文件不存在")

    manifest_path = warehouse.parent / "snapshot_manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if (manifest.get("schema_version") != "warehouse_snapshot.v2"
            or manifest.get("snapshot_id") != snapshot_id):
        raise ValueError("BI Snapshot manifest身份不匹配")
    artifacts = manifest.get("artifacts")
    warehouse_artifacts = [
        item for item in artifacts if isinstance(item, dict) and item.get("path") == "warehouse.duckdb"
    ] if isinstance(artifacts, list) else []
    if (len(warehouse_artifacts) != 1
            or not isinstance(warehouse_artifacts[0].get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", warehouse_artifacts[0]["sha256"])):
        raise ValueError("BI Snapshot manifest缺少唯一warehouse身份")
    warehouse_sha256 = warehouse_artifacts[0]["sha256"]
    table, fields = _source_table(manifest)
    sql, parameters = _build_query(table, fields, requested)
    output_root = ws / "Output/StudyAbroad"

    try:
        response = execute_query(
            warehouse=warehouse,
            snapshot_id=snapshot_id,
            sql=sql,
            run_id=run_id,
            output_root=output_root,
            parameters=parameters,
            max_rows=10_000,
            max_result_bytes=20_000_000,
        )
        if response.get("status") != "passed":
            raise ValueError("BI年级证据查询失败：" + json.dumps(response.get("errors", []), ensure_ascii=False))
        if response.get("snapshot_id") != snapshot_id or response.get("run_id") != run_id:
            raise ValueError("查询回执的Snapshot或run身份与请求不一致")
        data = read_query_result(response, output_root=output_root)
        receipt_path = resolve_file(output_root / run_id, response["receipt"])
        receipt, _ = verify_receipt(receipt_path)
        if (receipt.get("snapshot_id") != snapshot_id or receipt.get("run_id") != run_id
                or receipt.get("referenced_source_ids") != ["br_work_orders"]
                or receipt.get("referenced_relations") != [f"landing.{table}"]
                or receipt.get("snapshot_ref", {}).get("manifest_sha256") != hashlib.sha256(manifest_bytes).hexdigest()
                or receipt.get("snapshot_ref", {}).get("warehouse_sha256") != warehouse_sha256):
            raise ValueError("BI年级证据回执未绑定所选Snapshot和br_work_orders")
        rows = [dict(zip(data["columns"], values)) for values in data["rows"]]
        if any(
            not any(_normalize_resource_id(row.get(field)) in set(requested)
                    for field in ("resource_id", "alternate_resource_id"))
            for row in rows
        ):
            raise ValueError("查询返回了未请求的资源ID")
        resolution = resolve_grade_rows(rows, requested)
    finally:
        if workspace_config_path.read_bytes() != workspace_config_bytes:
            raise ValueError("读取期间BI workspace指针字节发生变化")

    return {
        "resolution": resolution,
        "rows": rows,
        "query_response": response,
        "bi_snapshot_id": snapshot_id,
        "bi_workspace_sha256": hashlib.sha256(workspace_config_bytes).hexdigest(),
    }


__all__ = ["load_grade_evidence", "resolve_grade_rows", "stage_from_values"]
