from __future__ import annotations

import hashlib
import csv
import json
import os
import re
import shutil
import unicodedata
import uuid
import zipfile
from pathlib import Path
from typing import Any

import duckdb

from data_foundation.connectors.xlsx import (
    CLEAN_CANDIDATE_SHEETS,
    Cell,
    declared_dimension,
    iter_sheet_rows,
    sha256_file,
    shared_strings,
    sheet_targets,
)
SNAPSHOT_ID = re.compile(r"^snapshot_[a-z0-9][a-z0-9_-]{2,62}$")
PROVENANCE = ["source_id", "source_sha256", "source_filename", "sheet_name", "source_row_number", "ingest_batch_id", "snapshot_id"]
TABLE_NAMES = {
    ("fy25_frontdesk_daily", "FY25-汇总"): "fy25_frontdesk_daily__summary",
    ("fy27_frontdesk_daily", "FY27-汇总"): "fy27_frontdesk_daily__summary",
    ("br_cash", "现金明细表"): "cash_ledger",
    ("current_work_orders", "工单分析"): "current_work_orders__analysis",
    ("current_work_orders", "新表区域"): "current_work_orders__records",
    ("archived_work_orders", "FY24"): "archived_work_orders__fy24",
    ("archived_work_orders", "FY25"): "archived_work_orders__fy25",
    ("archived_work_orders", "FY26"): "archived_work_orders__fy26",
}


class SnapshotError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _safe_name(value: str) -> str:
    ascii_name = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return ascii_name or hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _table_name(source_id: str, sheet_name: str) -> str:
    return TABLE_NAMES.get((source_id, sheet_name), f"{_safe_name(source_id)}__{_safe_name(sheet_name)}")


def _meaningful(cells: dict[int, Cell]) -> dict[int, Cell]:
    return {position: cell for position, cell in cells.items() if cell.value not in (None, "") or cell.formula is not None}


def _header_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    return normalized or None


def _headers(cells: dict[int, Cell], max_column: int) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    result = []
    for position in range(1, max_column + 1):
        cell = cells.get(position)
        original = _header_text(cell.value) if cell is not None else None
        base = original or f"column_{position}"
        seen[base] = seen.get(base, 0) + 1
        technical = base if seen[base] == 1 else f"{base}__{seen[base]}"
        result.append({"position": position, "original_name": original, "technical_name": technical})
    return result


def _clean_schema(headers: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    columns = list(PROVENANCE)
    types = ["VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "BIGINT", "VARCHAR", "VARCHAR"]
    for header in headers:
        columns.append(str(header["technical_name"]))
        types.append("VARCHAR")
    return columns, types


def _clean_row(
    *, source_id: str, digest: str, filename: str, sheet_name: str, row_number: int, batch_id: str,
    snapshot_id: str, headers: list[dict[str, Any]], cells: dict[int, Cell],
) -> list[Any]:
    values: list[Any] = [source_id, digest, filename, sheet_name, row_number, batch_id, snapshot_id]
    for header in headers:
        cell = cells.get(int(header["position"]))
        raw = cell.value if cell else None
        values.append(raw)
    return values


def _write_parquet(connection: duckdb.DuckDBPyConnection, relation: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(path).replace("'", "''")
    connection.execute(f"COPY {relation} TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)")


def _write_clean_csv(
    *, path: Path, rows, source_id: str, digest: str, filename: str, sheet_name: str,
    snapshot_id: str, headers: list[dict[str, Any]],
) -> int:
    columns, _ = _clean_schema(headers)
    clean_rows = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(columns)
        for row_number, cells in rows:
            if row_number == 1 or not _meaningful(cells):
                continue
            values = _clean_row(
                source_id=source_id, digest=digest, filename=filename, sheet_name=sheet_name,
                row_number=row_number, batch_id=snapshot_id, snapshot_id=snapshot_id,
                headers=headers, cells=cells,
            )
            writer.writerow("" if value is None else value for value in values)
            clean_rows += 1
    return clean_rows


def _load_clean_csv(connection: duckdb.DuckDBPyConnection, table: str, csv_path: Path, columns: list[str], types: list[str]) -> None:
    escaped_path = str(csv_path).replace("'", "''")
    projections = []
    for name, kind in zip(columns, types):
        quoted = _quote(name)
        if kind == "VARCHAR":
            projections.append(quoted)
        else:
            projections.append(f"TRY_CAST({quoted} AS {kind}) AS {quoted}")
    connection.execute(
        f"CREATE TABLE clean.{_quote(table)} AS SELECT {', '.join(projections)} "
        f"FROM read_csv('{escaped_path}', header=true, all_varchar=true, nullstr='')"
    )


def publish_snapshot(
    *, run_id: str, snapshot_id: str, output_root: Path, manifest: dict[str, Any], bindings: dict[str, Path],
) -> dict[str, Any]:
    if not SNAPSHOT_ID.fullmatch(snapshot_id):
        raise SnapshotError("SNAPSHOT_ID_INVALID", "snapshot_id is invalid")
    run_root = output_root / run_id
    snapshot_root = run_root / "data" / "snapshots" / snapshot_id
    if snapshot_root.exists():
        raise SnapshotError("SNAPSHOT_EXISTS", "snapshot already exists and cannot be overwritten")
    temporary = snapshot_root.parent / f".{snapshot_id}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True)
    warehouse_path = temporary / "warehouse.duckdb"
    artifact_entries = []
    snapshot_sources = []
    quality_rows: list[tuple[Any, ...]] = []
    ingested_clean_tables: set[tuple[str, str]] = set()
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(str(warehouse_path))
        for schema in ("ingest", "clean", "quality", "semantic", "queries"):
            connection.execute(f"CREATE SCHEMA {_quote(schema)}")
        connection.execute("CREATE TABLE quality.issues (issue_code VARCHAR, severity VARCHAR, source_id VARCHAR, sheet_name VARCHAR, source_row_number BIGINT, column_name VARCHAR, raw_value VARCHAR, candidate_value VARCHAR, status VARCHAR, snapshot_id VARCHAR)")
        connection.execute("CREATE TABLE ingest.sources (source_id VARCHAR, filename VARCHAR, sha256 VARCHAR, snapshot_id VARCHAR)")
        connection.execute("CREATE TABLE ingest.sheets (source_id VARCHAR, sheet_name VARCHAR, declared_dimension VARCHAR, physical_node_rows BIGINT, meaningful_rows BIGINT, max_source_row BIGINT, clean_candidate BOOLEAN, snapshot_id VARCHAR)")
        for source_id in sorted(bindings):
            path = bindings[source_id]
            contract = manifest["sources"][source_id]
            if not path.is_file() or path.name != contract["filename"]:
                raise SnapshotError("SOURCE_IDENTITY_INVALID", f"source identity invalid: {source_id}")
            digest = sha256_file(path)
            if digest != contract["sha256"]:
                raise SnapshotError("HASH_MISMATCH", f"source hash mismatch: {source_id}")
            copied = temporary / "source_workbooks" / source_id / path.name
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, copied)
            if sha256_file(copied) != digest:
                raise SnapshotError("HASH_MISMATCH", f"copied source hash mismatch: {source_id}")
            connection.execute("INSERT INTO ingest.sources VALUES (?, ?, ?, ?)", [source_id, path.name, digest, snapshot_id])
            source_summary = {"source_id": source_id, "filename": path.name, "sha256": digest, "sheets": []}
            with zipfile.ZipFile(path) as archive:
                strings = shared_strings(archive)
                for sheet in sheet_targets(archive):
                    physical_rows = 0
                    meaningful_rows = 0
                    max_source_row = 0
                    max_column = 0
                    header_cells: dict[int, Cell] = {}
                    for row_number, cells in iter_sheet_rows(archive, sheet.target, strings):
                        physical_rows += 1
                        meaningful_rows += bool(_meaningful(cells))
                        max_source_row = max(max_source_row, row_number)
                        max_column = max(max_column, max(cells, default=0))
                        if row_number == 1:
                            header_cells = _meaningful(cells)
                        for cell in cells.values():
                            if cell.formula_cache == "missing":
                                quality_rows.append(("FORMULA_CACHE_MISSING", "warning", source_id, sheet.name, row_number, cell.reference, None, None, "pending", snapshot_id))
                    headers = _headers(header_cells, max_column)
                    candidate = sheet.name in CLEAN_CANDIDATE_SHEETS.get(source_id, frozenset())
                    table = _table_name(source_id, sheet.name)
                    missing_headers = sum(header["original_name"] is None for header in headers)
                    duplicate_headers = len(headers) - len({header["original_name"] for header in headers if header["original_name"] is not None}) - missing_headers
                    if missing_headers:
                        quality_rows.append(("MISSING_HEADER", "warning", source_id, sheet.name, 1, None, None, None, "pending", snapshot_id))
                    if duplicate_headers:
                        quality_rows.append(("DUPLICATE_HEADER", "warning", source_id, sheet.name, 1, None, None, None, "pending", snapshot_id))
                    clean_rows = 0
                    if candidate:
                        columns, types = _clean_schema(headers)
                        csv_path = temporary / "_work" / f"{table}.csv"
                        clean_rows = _write_clean_csv(
                            path=csv_path, rows=iter_sheet_rows(archive, sheet.target, strings),
                            source_id=source_id, digest=digest, filename=path.name, sheet_name=sheet.name,
                            snapshot_id=snapshot_id, headers=headers,
                        )
                        _load_clean_csv(connection, table, csv_path, columns, types)
                        clean_relative = Path("clean") / f"{table}.parquet"
                        _write_parquet(connection, f"clean.{_quote(table)}", temporary / clean_relative)
                        csv_path.unlink()
                        ingested_clean_tables.add((source_id, sheet.name))
                    else:
                        quality_rows.append(("SHEET_NOT_CLEAN_CANDIDATE", "info", source_id, sheet.name, None, None, None, None, "pending", snapshot_id))
                    connection.execute("INSERT INTO ingest.sheets VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [source_id, sheet.name, declared_dimension(archive, sheet.target), physical_rows, meaningful_rows, max_source_row, candidate, snapshot_id])
                    source_summary["sheets"].append({"name": sheet.name, "declared_dimension": declared_dimension(archive, sheet.target), "physical_node_rows": physical_rows, "meaningful_rows": meaningful_rows, "max_source_row": max_source_row, "clean_candidate": candidate, "clean_rows": clean_rows, "headers": headers})
            snapshot_sources.append(source_summary)
        shutil.rmtree(temporary / "_work", ignore_errors=True)
        if quality_rows:
            connection.executemany("INSERT INTO quality.issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", quality_rows)
        _write_parquet(connection, "quality.issues", temporary / "quality" / "issues.parquet")
        registration_selects = []
        for fiscal_year, source_id, table in (
            ("FY25", "fy25_frontdesk_daily", "fy25_frontdesk_daily__summary"),
            ("FY27", "fy27_frontdesk_daily", "fy27_frontdesk_daily__summary"),
        ):
            if (source_id, "FY25-汇总" if fiscal_year == "FY25" else "FY27-汇总") not in ingested_clean_tables:
                continue
            registration_selects.append(
                f"""
                SELECT
                    '{fiscal_year}' AS fiscal_year,
                    source_id, source_sha256, source_filename, sheet_name,
                    source_row_number, ingest_batch_id, snapshot_id,
                    trim(\"业务形式\") AS \"业务形式\",
                    TRY_CAST(regexp_replace(\"实缴金额\", '[,￥¥元[:space:]]', '', 'g') AS DECIMAL(38, 6)) AS \"实缴金额\"
                FROM clean.{_quote(table)}
                WHERE trim(\"业务形式\") IN ('报班', '报班-预收')
                """
            )
        if registration_selects:
            connection.execute("CREATE VIEW semantic.registration_cash AS " + " UNION ALL ".join(registration_selects))
        connection.execute("CHECKPOINT")
        connection.close()
        snapshot_manifest = {"schema_version": "warehouse_snapshot.v1", "run_id": run_id, "snapshot_id": snapshot_id, "sources": snapshot_sources, "artifacts": []}
        for artifact in sorted(path for path in temporary.rglob("*") if path.is_file()):
            relative = artifact.relative_to(temporary).as_posix()
            entry = {"path": relative, "sha256": sha256_file(artifact), "size_bytes": artifact.stat().st_size}
            snapshot_manifest["artifacts"].append(entry)
        manifest_path = temporary / "snapshot_manifest.json"
        manifest_path.write_text(json.dumps(snapshot_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshot_manifest["artifacts"].append({"path": "snapshot_manifest.json", "sha256": sha256_file(manifest_path), "size_bytes": manifest_path.stat().st_size})
        snapshot_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, snapshot_root)
        artifact_manifest = run_root / "artifact_manifest.jsonl"
        artifact_manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest_exists = artifact_manifest.exists()
        original_manifest_size = artifact_manifest.stat().st_size if manifest_exists else 0
        try:
            for entry in snapshot_manifest["artifacts"]:
                artifact_entries.append({"artifact_id": f"artifact_{entry['sha256'][:24]}", "run_id": run_id, "snapshot_id": snapshot_id, "path": f"data/snapshots/{snapshot_id}/{entry['path']}", "sha256": entry["sha256"], "size_bytes": entry["size_bytes"]})
            with artifact_manifest.open("a", encoding="utf-8") as handle:
                for entry in artifact_entries:
                    handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            shutil.rmtree(snapshot_root, ignore_errors=True)
            if manifest_exists:
                with artifact_manifest.open("r+b") as handle:
                    handle.truncate(original_manifest_size)
            else:
                artifact_manifest.unlink(missing_ok=True)
            raise
        return {"schema_version": "data_foundation_ingest.v1", "status": "passed", "run_id": run_id, "snapshot_id": snapshot_id, "snapshot_path": f"data/snapshots/{snapshot_id}", "artifacts": artifact_entries, "warnings": len(quality_rows), "errors": []}
    except Exception:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        shutil.rmtree(temporary, ignore_errors=True)
        raise
