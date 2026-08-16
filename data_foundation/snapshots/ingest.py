from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

import duckdb

from data_foundation.connectors.xlsx import (
    Cell,
    declared_dimension,
    dimension_max,
    iter_sheet_rows,
    sha256_file,
    shared_strings,
    sheet_targets,
)

SNAPSHOT_ID = re.compile(r"^snapshot_[a-z0-9][a-z0-9_-]{2,62}$")
PROVENANCE = [
    "source_id", "source_sha256", "source_filename", "sheet_name",
    "source_row_number", "ingest_batch_id", "snapshot_id",
]


class SnapshotError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _safe_name(value: str) -> str:
    ascii_name = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return ascii_name or f"sheet_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"


def _table_name(source_id: str, sheet_name: str, used: set[str]) -> str:
    base = f"{_safe_name(source_id)}__{_safe_name(sheet_name)}"[:63].rstrip("_")
    candidate = base
    suffix = 2
    while candidate in used:
        tail = f"_{suffix}"
        candidate = base[: 63 - len(tail)].rstrip("_") + tail
        suffix += 1
    used.add(candidate)
    return candidate


def _meaningful(cells: dict[int, Cell]) -> dict[int, Cell]:
    return {position: cell for position, cell in cells.items() if cell.value not in (None, "") or cell.formula is not None}


def _landing_schema(max_column: int) -> tuple[list[str], list[str]]:
    columns = list(PROVENANCE) + [f"column_{position}" for position in range(1, max_column + 1)]
    types = ["VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "BIGINT", "VARCHAR", "VARCHAR"] + ["VARCHAR"] * max_column
    return columns, types


def _landing_row(
    *, source_id: str, digest: str, filename: str, sheet_name: str, row_number: int,
    snapshot_id: str, max_column: int, cells: dict[int, Cell],
) -> list[Any]:
    values: list[Any] = [source_id, digest, filename, sheet_name, row_number, snapshot_id, snapshot_id]
    for position in range(1, max_column + 1):
        cell = cells.get(position)
        values.append(cell.value if cell else None)
    return values


def _write_landing_csv(
    *, path: Path, rows, source_id: str, digest: str, filename: str, sheet_name: str,
    snapshot_id: str, max_column: int,
) -> int:
    columns, _ = _landing_schema(max_column)
    landing_rows = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(columns)
        for row_number, cells in rows:
            if not _meaningful(cells):
                continue
            writer.writerow(
                "" if value is None else value
                for value in _landing_row(
                    source_id=source_id, digest=digest, filename=filename,
                    sheet_name=sheet_name, row_number=row_number,
                    snapshot_id=snapshot_id, max_column=max_column, cells=cells,
                )
            )
            landing_rows += 1
    return landing_rows


def _load_landing_csv(
    connection: duckdb.DuckDBPyConnection, table: str, csv_path: Path,
    columns: list[str], types: list[str],
) -> None:
    escaped_path = str(csv_path).replace("'", "''")
    projections = []
    for name, kind in zip(columns, types):
        quoted = _quote(name)
        projections.append(quoted if kind == "VARCHAR" else f"TRY_CAST({quoted} AS {kind}) AS {quoted}")
    connection.execute(
        f"CREATE TABLE landing.{_quote(table)} AS SELECT {', '.join(projections)} "
        f"FROM read_csv('{escaped_path}', header=true, all_varchar=true, nullstr='')"
    )


def _write_parquet(connection: duckdb.DuckDBPyConnection, relation: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(path).replace("'", "''")
    connection.execute(f"COPY {relation} TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)")


def publish_snapshot(
    *, run_id: str, snapshot_id: str, output_root: Path,
    manifest: dict[str, Any], bindings: dict[str, Path],
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
    used_tables: set[str] = set()
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(str(warehouse_path))
        for schema in ("ingest", "landing", "quality", "queries"):
            connection.execute(f"CREATE SCHEMA {_quote(schema)}")
        connection.execute("CREATE TABLE quality.issues (issue_code VARCHAR, severity VARCHAR, source_id VARCHAR, sheet_name VARCHAR, source_row_number BIGINT, column_name VARCHAR, raw_value VARCHAR, candidate_value VARCHAR, status VARCHAR, snapshot_id VARCHAR)")
        connection.execute("CREATE TABLE ingest.sources (source_id VARCHAR, filename VARCHAR, sha256 VARCHAR, snapshot_id VARCHAR)")
        connection.execute("CREATE TABLE ingest.sheets (source_id VARCHAR, sheet_name VARCHAR, declared_dimension VARCHAR, physical_node_rows BIGINT, meaningful_rows BIGINT, max_source_row BIGINT, target_table VARCHAR, landing_rows BIGINT, snapshot_id VARCHAR)")
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
                    table = _table_name(source_id, sheet.name, used_tables)
                    physical_rows = 0
                    meaningful_rows = 0
                    max_source_row = 0
                    max_column = 0
                    missing_formula_cache = 0
                    for row_number, cells in iter_sheet_rows(archive, sheet.target, strings):
                        physical_rows += 1
                        meaningful_rows += bool(_meaningful(cells))
                        max_source_row = max(max_source_row, row_number)
                        max_column = max(max_column, max(cells, default=0))
                        missing_formula_cache += sum(cell.formula_cache == "missing" for cell in cells.values())
                    if sheet.state != "visible":
                        quality_rows.append(("SHEET_HIDDEN", "info", source_id, sheet.name, None, None, None, None, "observed", snapshot_id))
                    if meaningful_rows == 0:
                        quality_rows.append(("SHEET_EMPTY", "info", source_id, sheet.name, None, None, None, None, "observed", snapshot_id))
                    declared = declared_dimension(archive, sheet.target)
                    declared_max = dimension_max(declared)
                    if declared_max and (max_column > declared_max[0] or max_source_row > declared_max[1]):
                        quality_rows.append(("DECLARED_DIMENSION_MISMATCH", "warning", source_id, sheet.name, None, None, declared, f"max_column={max_column};max_row={max_source_row}", "pending", snapshot_id))
                    if missing_formula_cache:
                        quality_rows.append(("FORMULA_CACHE_MISSING", "warning", source_id, sheet.name, None, None, str(missing_formula_cache), None, "pending", snapshot_id))
                    columns, types = _landing_schema(max_column)
                    csv_path = temporary / "_work" / f"{table}.csv"
                    landing_rows = _write_landing_csv(
                        path=csv_path, rows=iter_sheet_rows(archive, sheet.target, strings),
                        source_id=source_id, digest=digest, filename=path.name,
                        sheet_name=sheet.name, snapshot_id=snapshot_id, max_column=max_column,
                    )
                    _load_landing_csv(connection, table, csv_path, columns, types)
                    _write_parquet(connection, f"landing.{_quote(table)}", temporary / "landing" / f"{table}.parquet")
                    csv_path.unlink()
                    connection.execute(
                        "INSERT INTO ingest.sheets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [source_id, sheet.name, declared, physical_rows, meaningful_rows, max_source_row, table, landing_rows, snapshot_id],
                    )
                    source_summary["sheets"].append({
                        "name": sheet.name, "state": sheet.state,
                        "declared_dimension": declared,
                        "physical_node_rows": physical_rows,
                        "meaningful_rows": meaningful_rows,
                        "max_source_row": max_source_row,
                        "max_source_column": max_column,
                        "target_table": table,
                        "landing_rows": landing_rows,
                    })
            snapshot_sources.append(source_summary)
        shutil.rmtree(temporary / "_work", ignore_errors=True)
        if quality_rows:
            connection.executemany("INSERT INTO quality.issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", quality_rows)
        _write_parquet(connection, "quality.issues", temporary / "quality" / "issues.parquet")
        connection.execute("CHECKPOINT")
        connection.close()
        snapshot_manifest = {
            "schema_version": "warehouse_snapshot.v2",
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "sources": snapshot_sources,
            "artifacts": [],
        }
        for artifact in sorted(path for path in temporary.rglob("*") if path.is_file()):
            relative = artifact.relative_to(temporary).as_posix()
            snapshot_manifest["artifacts"].append({"path": relative, "sha256": sha256_file(artifact), "size_bytes": artifact.stat().st_size})
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
                artifact_entries.append({
                    "artifact_id": f"artifact_{entry['sha256'][:24]}",
                    "run_id": run_id,
                    "snapshot_id": snapshot_id,
                    "path": f"data/snapshots/{snapshot_id}/{entry['path']}",
                    "sha256": entry["sha256"],
                    "size_bytes": entry["size_bytes"],
                })
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
        return {
            "schema_version": "data_foundation_ingest.v2",
            "status": "passed",
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "snapshot_path": f"data/snapshots/{snapshot_id}",
            "artifacts": artifact_entries,
            "warnings": len(quality_rows),
            "errors": [],
        }
    except Exception:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        shutil.rmtree(temporary, ignore_errors=True)
        raise
