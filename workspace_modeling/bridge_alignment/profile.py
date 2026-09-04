from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any

from data_platform.connectors.xlsx import XlsxReadError, inspect_workbook
from data_platform.query.service import _connect, _require_snapshot, describe_warehouse

from workspace_modeling.bridge_alignment.workspace import AlignmentError


SUPPORTED_EVIDENCE = {".csv", ".json", ".jsonl", ".md", ".txt", ".xlsx", ".xlsm", ".yaml", ".yml"}
SKIP_DIRECTORIES = {".git", ".venv", "__pycache__", "node_modules"}


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _header_candidates(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = [
        {"column": item["name"], "label": item.get("header_label") or item["name"]}
        for item in columns
        if item.get("name") not in {"source_id", "source_sha256", "source_filename", "sheet_name", "source_row_number", "ingest_batch_id", "snapshot_id"}
    ]
    return [{"sample_position": 1, "labels": labels}] if labels else []


def profile_snapshot(
    *, warehouse: Path, snapshot_id: str, company_id: str, pack_ref: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    description = describe_warehouse(warehouse=warehouse, snapshot_id=snapshot_id)
    with _connect(warehouse) as connection:
        _require_snapshot(connection, snapshot_id)
        sheet_rows = connection.execute(
            "SELECT source_id, sheet_name, target_table FROM ingest.sheets ORDER BY source_id, sheet_name"
        ).fetchall()
        relations = []
        for source_id, sheet_name, table_name in sheet_rows:
            cursor = connection.execute(
                f"SELECT * FROM landing.{_quote(table_name)} ORDER BY source_row_number LIMIT 20"
            )
            columns = [item[0] for item in cursor.description]
            samples = [dict(zip(columns, row)) for row in cursor.fetchall()]
            relation_name = f"landing.{table_name}"
            relation_description = next(
                item for item in description["relations"]
                if item["schema"] == "landing" and item["name"] == table_name
            )
            relations.append({
                "relation": relation_name,
                "source_id": source_id,
                "sheet_name": sheet_name,
                "columns": relation_description["columns"],
                "sample_rows": samples,
                "header_candidates": _header_candidates(relation_description["columns"]),
            })
        quality_rows = connection.execute(
            "SELECT * FROM quality.issues ORDER BY source_id, sheet_name LIMIT 1000"
        ).fetchall()
        quality_columns = [item[0] for item in connection.description]
    profile = {
        "schema_version": "bridge_alignment_profile.v1",
        "company_id": company_id,
        "snapshot_id": snapshot_id,
        "pack_ref": pack_ref,
        "relations": relations,
        "supplemental_evidence": [],
        "enterprise_decisions": [],
    }
    quality = {
        "schema_version": "controlled_query_result.v1",
        "status": "passed",
        "snapshot_id": snapshot_id,
        "row_count": len(quality_rows),
        "result": {"columns": quality_columns, "rows": [list(row) for row in quality_rows]},
        "artifact": None,
        "errors": [],
    }
    return profile, description, quality


def copy_reference_files(source_root: Path, target_root: Path) -> list[str]:
    if not source_root.is_dir():
        raise AlignmentError("EVIDENCE_DIRECTORY_NOT_FOUND", "evidence path must be a readable directory")
    updated = []
    for source in sorted(source_root.rglob("*")):
        if source.is_symlink() or not source.is_file() or source.suffix.lower() not in SUPPORTED_EVIDENCE:
            continue
        relative = source.relative_to(source_root)
        if any(part.startswith(".") or part in SKIP_DIRECTORIES for part in relative.parts):
            continue
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        updated.append(relative.as_posix())
    return updated


def scan_reference_files(root: Path) -> list[dict[str, Any]]:
    entries = []
    if not root.exists():
        return entries
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.suffix.lower() in SUPPORTED_EVIDENCE):
        relative = path.relative_to(root).as_posix()
        entry: dict[str, Any] = {"locator": f"reference/{relative}", "kind": path.suffix.lower().lstrip(".")}
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            try:
                inspection = inspect_workbook(path)
                entry["sheets"] = [{"name": item["name"], "header_candidates": item["header_candidates"]} for item in inspection["sheets"]]
            except XlsxReadError as exc:
                entry["read_error"] = str(exc)
        elif path.suffix.lower() == ".csv":
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    entry["headers"] = next(csv.reader(handle), [])[:120]
            except (OSError, csv.Error, UnicodeError) as exc:
                entry["read_error"] = str(exc)
        else:
            entry["excerpt"] = path.read_text(encoding="utf-8-sig", errors="replace")[:2000]
        entries.append(entry)
    return entries
