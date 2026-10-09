"""Read and merge already-normalized study-abroad Snapshot tables."""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from data_platform.query.evidence import read_query_result
from data_platform.query.service import execute_query


_SCHEMA = "study_abroad_warehouse.v1"
_SOURCE_ID = "study_abroad_market"
_KINDS = ("resources", "contracts", "languages")
_RUN_ID = re.compile(r"^run_[a-z0-9][a-z0-9_-]{2,67}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
        data = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(f"留学{label}不可读或不是有效JSON") from None
    if not isinstance(data, dict):
        raise ValueError(f"留学{label}必须是JSON对象")
    return data, payload


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _resolve_run_file(workspace: Path, value: Any, *, runs_root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"留学{label}路径缺失")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"留学{label}路径必须是明确的工作区相对路径")
    resolved = (workspace / relative).resolve()
    if not resolved.is_relative_to(runs_root.resolve()):
        raise ValueError(f"留学{label}必须位于 Work/StudyAbroad/Runs 内")
    return resolved


def _query_run_id(run_id: str, kind: str) -> str:
    result = f"{run_id}_history_{kind}"
    if not _RUN_ID.fullmatch(result):
        raise ValueError("历史受控查询run_id无效或过长")
    return result


def load_normalized_history(workspace: Path, snapshot_id: str, run_id: str) -> dict[str, Any]:
    """Load the current normalized Snapshot through Data Platform evidence queries."""
    workspace = Path(workspace).resolve()
    workspace_config_path = workspace / "Work" / "workspace.json"
    workspace_config, workspace_config_bytes = _read_json(workspace_config_path, "workspace身份")
    company_id = workspace_config.get("company_id")
    if not isinstance(company_id, str) or not company_id:
        raise ValueError("留学工作区缺少company_id")

    pointer_path = workspace / "Work" / "StudyAbroad" / "current.json"
    pointer, pointer_bytes = _read_json(pointer_path, "Snapshot指针")
    if (pointer.get("schema_version") != _SCHEMA
            or pointer.get("company_id") != company_id):
        raise ValueError("留学Snapshot指针与当前工作区客户身份不匹配")
    if not isinstance(snapshot_id, str) or not snapshot_id or pointer.get("snapshot_id") != snapshot_id:
        raise ValueError("显式snapshot_id必须匹配当前留学Snapshot指针")
    source_run_id = pointer.get("run_id")
    if not isinstance(source_run_id, str) or not _RUN_ID.fullmatch(source_run_id):
        raise ValueError("留学Snapshot指针缺少有效source run_id")
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError("历史查询run_id无效")

    runs_root = workspace / "Work" / "StudyAbroad" / "Runs"
    warehouse = _resolve_run_file(workspace, pointer.get("warehouse"), runs_root=runs_root, label="warehouse")
    if (warehouse.name != "warehouse.duckdb" or warehouse.parent.name != snapshot_id
            or not warehouse.is_file()):
        raise ValueError("留学warehouse路径与显式Snapshot不匹配")
    snapshot_manifest_path = warehouse.parent / "snapshot_manifest.json"
    snapshot_manifest, snapshot_manifest_bytes = _read_json(snapshot_manifest_path, "Snapshot manifest")
    if snapshot_manifest.get("snapshot_id") != snapshot_id:
        raise ValueError("留学Snapshot manifest与显式snapshot_id不匹配")
    sources = snapshot_manifest.get("sources")
    normalized_sources = [
        item for item in sources if isinstance(item, dict) and item.get("source_id") == _SOURCE_ID
    ] if isinstance(sources, list) else []
    if len(normalized_sources) != 1:
        raise ValueError("Snapshot必须且只能包含一个study_abroad_market来源")

    lineage_path = _resolve_run_file(
        workspace, pointer.get("source_lineage"), runs_root=runs_root, label="source_lineage",
    )
    lineage, lineage_bytes = _read_json(lineage_path, "source_lineage")
    if (lineage.get("schema_version") != _SCHEMA
            or lineage.get("company_id") != company_id
            or lineage.get("snapshot_id") != snapshot_id
            or lineage.get("run_id") != source_run_id):
        raise ValueError("留学source_lineage与显式Snapshot身份不匹配")
    source_sha256 = pointer.get("source_sha256")
    source_hashes = lineage.get("source_hashes")
    if (not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256)
            or not isinstance(source_hashes, dict) or source_hashes.get("source") != source_sha256):
        raise ValueError("留学source_lineage与Snapshot来源SHA不匹配")

    output_root = workspace / "Output" / "StudyAbroad" / "历史查询回执"
    tables: dict[str, list[dict[str, Any]]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    query_run_ids: dict[str, str] = {}
    for kind in _KINDS:
        query_run_id = _query_run_id(run_id, kind)
        relation = f"{_SOURCE_ID}__{kind}"
        response = execute_query(
            warehouse=warehouse,
            snapshot_id=snapshot_id,
            sql=f"SELECT * FROM landing.{relation}",
            run_id=query_run_id,
            output_root=output_root,
            max_rows=100_000,
            max_result_bytes=100_000_000,
        )
        if (response.get("status") != "passed"
                or response.get("snapshot_id") != snapshot_id
                or response.get("run_id") != query_run_id):
            raise ValueError(f"留学{kind}受控历史查询回执身份不匹配")
        data = read_query_result(response, output_root=output_root)
        tables[kind] = [dict(zip(data["columns"], row)) for row in data["rows"]]
        receipts[kind] = response["receipt"]
        query_run_ids[kind] = query_run_id

    if workspace_config_path.read_bytes() != workspace_config_bytes:
        raise ValueError("工作区客户身份在读取留学历史期间发生变化")
    if pointer_path.read_bytes() != pointer_bytes:
        raise ValueError("留学Snapshot指针在读取历史期间发生变化")
    if snapshot_manifest_path.read_bytes() != snapshot_manifest_bytes:
        raise ValueError("留学Snapshot manifest在读取历史期间发生变化")
    if lineage_path.read_bytes() != lineage_bytes:
        raise ValueError("留学source_lineage在读取历史期间发生变化")

    return {
        "tables": tables,
        "source_metadata": {
            "source_snapshot_id": snapshot_id,
            "source_run_id": source_run_id,
            "company_id": company_id,
            "source_sha256": source_sha256,
            "pointer_sha256": _sha256(pointer_bytes),
            "warehouse": str(warehouse),
            "snapshot_manifest_sha256": _sha256(snapshot_manifest_bytes),
            "source_lineage_sha256": _sha256(lineage_bytes),
            "query_receipts": receipts,
            "query_run_ids": query_run_ids,
        },
    }


def _row_month(row: dict[str, Any]) -> str | None:
    value = row.get("event_date")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m")
    if isinstance(value, date):
        return value.strftime("%Y-%m")
    if not isinstance(value, str) or len(value) < 7:
        return None
    text = value.strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text[:10]).strftime("%Y-%m")
    except ValueError:
        return None


def _refresh_months(refresh_months: list[str]) -> set[str]:
    result = set()
    for month in refresh_months:
        if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
            raise ValueError("refresh_months必须使用YYYY-MM格式")
        try:
            date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise ValueError("refresh_months包含无效月份") from exc
        result.add(month)
    return result


def replace_normalized_months(
    history_tables: dict[str, list[dict[str, Any]]],
    new_tables: dict[str, list[dict[str, Any]]],
    refresh_months: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Replace only requested months while preserving normalized row fields as-is."""
    months = _refresh_months(refresh_months)
    tables: dict[str, list[dict[str, Any]]] = {}
    for kind in _KINDS:
        old_rows = history_tables.get(kind, [])
        new_rows = new_tables.get(kind, [])
        retained = [dict(row) for row in old_rows if _row_month(row) not in months]
        refreshed = [dict(row) for row in new_rows if _row_month(row) in months]
        tables[kind] = retained + refreshed
    return tables
