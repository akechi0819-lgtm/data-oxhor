from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import duckdb

from data_foundation.connectors.xlsx import XlsxReadError, inspect_workbook, sha256_file
from data_foundation.snapshots.ingest import SnapshotError, publish_snapshot
from data_foundation.query.service import (
    QueryError,
    describe_warehouse,
    execute_query,
    promote_query,
    quality_issues,
    run_saved_query,
)

RUN_ID = re.compile(r"^run_[a-z0-9][a-z0-9_-]{2,67}$")


def _error(code: str, message: str, source_id: str | None = None) -> dict[str, str]:
    result = {"code": code, "message": message}
    if source_id is not None:
        result["source_id"] = source_id
    return result


def _bindings(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        source_id, separator, raw_path = value.partition("=")
        if not separator or not source_id or not raw_path or source_id in result:
            raise ValueError("each --source must be a unique SOURCE_ID=PATH binding")
        result[source_id] = Path(raw_path)
    return result


def inspect_sources(*, run_id: str, manifest_path: Path, source_values: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "data_foundation_inspection.v2",
        "status": "passed",
        "run_id": run_id,
        "sources": [],
        "warnings": [],
        "errors": [],
    }
    if not RUN_ID.fullmatch(run_id):
        result["status"] = "failed"
        result["errors"].append(_error("RUN_ID_INVALID", "run_id must match run_[a-z0-9][a-z0-9_-]{2,67}"))
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bindings = _bindings(source_values)
        expected_sources = manifest["sources"]
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        result["status"] = "failed"
        result["errors"].append(_error("CONTRACT_INVALID", str(exc)))
        return result
    if set(bindings) != set(expected_sources):
        result["status"] = "failed"
        result["errors"].append(
            _error("SOURCE_BINDINGS_INVALID", f"required source IDs: {sorted(expected_sources)}; provided: {sorted(bindings)}")
        )
        return result
    for source_id in sorted(expected_sources):
        path = bindings[source_id]
        contract = expected_sources[source_id]
        if not path.is_file():
            result["errors"].append(_error("SOURCE_NOT_FOUND", "source file does not exist", source_id))
            continue
        if path.name != contract["filename"]:
            result["errors"].append(_error("SOURCE_FILENAME_MISMATCH", "source filename does not match manifest", source_id))
            continue
        try:
            digest = sha256_file(path)
        except OSError:
            result["errors"].append(_error("SOURCE_UNREADABLE", "source file cannot be read", source_id))
            continue
        if digest != contract["sha256"]:
            result["errors"].append(_error("HASH_MISMATCH", "source hash does not match manifest", source_id))
            continue
        try:
            inspection = inspect_workbook(path)
        except (XlsxReadError, ET.ParseError) as exc:
            result["errors"].append(_error("INVALID_XLSX", str(exc), source_id))
            continue
        result["sources"].append(
            {
                "source_id": source_id,
                "filename": path.name,
                "sha256": digest,
                "sheets": inspection["sheets"],
                "quality": inspection["quality"],
            }
        )
        result["warnings"].extend(
            {"source_id": source_id, **issue} for issue in inspection["quality"]
        )
    if result["errors"]:
        result["status"] = "failed"
    elif result["warnings"]:
        result["status"] = "passed_with_warnings"
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data-foundation")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect", help="inspect manifest-bound XLSX sources without emitting row data")
    inspect_parser.add_argument("--run-id", required=True)
    inspect_parser.add_argument("--manifest", type=Path, required=True)
    inspect_parser.add_argument("--source", action="append", default=[], metavar="SOURCE_ID=PATH")
    ingest_parser = commands.add_parser("ingest", help="publish an immutable DuckDB and Parquet snapshot")
    ingest_parser.add_argument("--run-id", required=True)
    ingest_parser.add_argument("--snapshot-id", required=True)
    ingest_parser.add_argument("--output-root", type=Path, required=True)
    ingest_parser.add_argument("--manifest", type=Path, required=True)
    ingest_parser.add_argument("--source", action="append", default=[], metavar="SOURCE_ID=PATH")
    for name in ("describe", "quality", "query", "run-saved-query", "promote-query"):
        command = commands.add_parser(name)
        command.add_argument("--warehouse", type=Path, required=True)
        command.add_argument("--snapshot-id", required=True)
        if name in {"quality", "query", "run-saved-query"}:
            command.add_argument("--run-id", required=True)
            command.add_argument("--output-root", type=Path, required=True)
            command.add_argument("--max-rows", type=int, default=1000)
            command.add_argument("--max-result-bytes", type=int, default=1_000_000)
        if name == "query":
            command.add_argument("--sql-file", type=Path, required=True)
            command.add_argument("--params-json", default="null")
        if name in {"run-saved-query", "promote-query"}:
            command.add_argument("--registry-root", type=Path, required=True)
            command.add_argument("--query-id", required=True)
            command.add_argument("--version", required=True)
        if name == "run-saved-query":
            command.add_argument("--params-json", default="null")
        if name == "promote-query":
            command.add_argument("--sql-file", type=Path, required=True)
            command.add_argument("--confirmed-by", required=True)
    return parser


def ingest_sources(*, run_id: str, snapshot_id: str, output_root: Path, manifest_path: Path, source_values: list[str]) -> dict[str, Any]:
    if not RUN_ID.fullmatch(run_id):
        return {"schema_version": "data_foundation_ingest.v2", "status": "failed", "run_id": run_id, "snapshot_id": snapshot_id, "artifacts": [], "warnings": [], "errors": [_error("RUN_ID_INVALID", "run_id must match run_[a-z0-9][a-z0-9_-]{2,67}")]}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bindings = _bindings(source_values)
        expected_sources = manifest["sources"]
        if set(bindings) != set(expected_sources):
            raise SnapshotError("SOURCE_BINDINGS_INVALID", f"required source IDs: {sorted(expected_sources)}; provided: {sorted(bindings)}")
        return publish_snapshot(run_id=run_id, snapshot_id=snapshot_id, output_root=output_root, manifest=manifest, bindings=bindings)
    except SnapshotError as exc:
        code, message = exc.code, str(exc)
    except (OSError, json.JSONDecodeError, KeyError, ValueError, XlsxReadError, ET.ParseError, zipfile.BadZipFile) as exc:
        code, message = "INGEST_FAILED", str(exc)
    return {"schema_version": "data_foundation_ingest.v2", "status": "failed", "run_id": run_id, "snapshot_id": snapshot_id, "artifacts": [], "warnings": [], "errors": [_error(code, message)]}


def _query_failure(command: str, exc: Exception) -> dict[str, Any]:
    code = exc.code if isinstance(exc, QueryError) else "QUERY_FAILED"
    return {"schema_version": f"data_foundation_{command.replace('-', '_')}.v1", "status": "failed", "errors": [_error(code, str(exc))]}


def run_query_command(args: argparse.Namespace) -> dict[str, Any]:
    try:
        if args.command == "describe":
            return describe_warehouse(warehouse=args.warehouse, snapshot_id=args.snapshot_id)
        if args.command == "quality":
            return quality_issues(warehouse=args.warehouse, snapshot_id=args.snapshot_id, run_id=args.run_id, output_root=args.output_root, max_rows=args.max_rows)
        if args.command == "query":
            sql = args.sql_file.read_text(encoding="utf-8")
            parameters = json.loads(args.params_json)
            return execute_query(warehouse=args.warehouse, snapshot_id=args.snapshot_id, sql=sql, parameters=parameters, run_id=args.run_id, output_root=args.output_root, max_rows=args.max_rows, max_result_bytes=args.max_result_bytes)
        if args.command == "promote-query":
            return promote_query(warehouse=args.warehouse, snapshot_id=args.snapshot_id, sql=args.sql_file.read_text(encoding="utf-8"), registry_root=args.registry_root, query_id=args.query_id, version=args.version, confirmed_by=args.confirmed_by)
        parameters = json.loads(args.params_json)
        return run_saved_query(warehouse=args.warehouse, snapshot_id=args.snapshot_id, registry_root=args.registry_root, query_id=args.query_id, version=args.version, parameters=parameters, run_id=args.run_id, output_root=args.output_root, max_rows=args.max_rows, max_result_bytes=args.max_result_bytes)
    except (QueryError, OSError, json.JSONDecodeError, duckdb.Error) as exc:
        return _query_failure(args.command, exc)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inspect":
        result = inspect_sources(run_id=args.run_id, manifest_path=args.manifest, source_values=args.source)
    elif args.command == "ingest":
        result = ingest_sources(run_id=args.run_id, snapshot_id=args.snapshot_id, output_root=args.output_root, manifest_path=args.manifest, source_values=args.source)
    else:
        result = run_query_command(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"passed", "passed_with_warnings"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
