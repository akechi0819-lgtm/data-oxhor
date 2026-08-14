from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ALLOWED_SCHEMAS = frozenset({"ingest", "clean", "quality", "semantic", "queries"})
DENIED_FUNCTIONS = re.compile(r"\b(read_csv|read_csv_auto|read_parquet|read_json|read_json_auto|read_xlsx|glob|httpfs_scan)\s*\(", re.IGNORECASE)
DENIED_CATALOG_RELATIONS = re.compile(
    r'(?<![a-z0-9_])(?:"?system"?\s*\.\s*)?"?information_schema"?\s*\.',
    re.IGNORECASE,
)
QUERY_ID = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
VERSION = re.compile(r"^v[0-9]+(?:\.[0-9]+){0,2}$")
RUN_ID = re.compile(r"^run_[a-z0-9][a-z0-9_-]{2,67}$")


class QueryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _json_value(value: Any) -> Any:
    if isinstance(value, (Decimal, date, datetime)):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def _connect(warehouse: Path, *, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    if not warehouse.is_file():
        raise QueryError("WAREHOUSE_NOT_FOUND", "warehouse file does not exist")
    if read_only:
        return duckdb.connect(
            str(warehouse),
            read_only=True,
            config={"enable_external_access": "false", "lock_configuration": "true"},
        )
    return duckdb.connect(str(warehouse))


def _require_snapshot(connection: duckdb.DuckDBPyConnection, snapshot_id: str) -> None:
    try:
        values = {row[0] for row in connection.execute("SELECT DISTINCT snapshot_id FROM ingest.sources").fetchall()}
    except duckdb.Error as exc:
        raise QueryError("WAREHOUSE_INVALID", "warehouse lacks ingest.sources snapshot metadata") from exc
    if values != {snapshot_id}:
        raise QueryError("SNAPSHOT_MISMATCH", "requested snapshot_id does not identify this warehouse")


def validate_query(connection: duckdb.DuckDBPyConnection, sql: str, parameters: Any = None) -> None:
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as exc:
        raise QueryError("QUERY_INVALID", str(exc)) from exc
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise QueryError("QUERY_REJECTED", "exactly one SELECT statement is required")
    if (
        DENIED_FUNCTIONS.search(sql)
        or DENIED_CATALOG_RELATIONS.search(sql)
        or re.search(r"\bduckdb_[a-z0-9_]*\s*\(", sql, re.IGNORECASE)
    ):
        raise QueryError("QUERY_REJECTED", "query contains a denied command or external reader")
    plan_parameters = parameters
    if plan_parameters is None and statements[0].named_parameters:
        names = statements[0].named_parameters
        plan_parameters = [None] * len(names) if all(name.isdigit() for name in names) else {name: None for name in names}
    try:
        plan = connection.execute("EXPLAIN (FORMAT JSON) " + sql, plan_parameters).fetchone()
    except duckdb.Error as exc:
        raise QueryError("QUERY_INVALID", str(exc)) from exc
    plan_text = plan[1] if plan else ""
    for match in re.finditer(r'"Table":\s*"([^"]+)"', plan_text):
        parts = match.group(1).split(".")
        if len(parts) >= 2 and parts[-2] not in ALLOWED_SCHEMAS:
            raise QueryError("QUERY_REJECTED", f"schema is not allowed: {parts[-2]}")


def describe_warehouse(*, warehouse: Path, snapshot_id: str) -> dict[str, Any]:
    with _connect(warehouse) as connection:
        _require_snapshot(connection, snapshot_id)
        rows = connection.execute(
            """
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema IN ('ingest','clean','quality','semantic','queries')
            ORDER BY table_schema, table_name
            """
        ).fetchall()
        columns = connection.execute(
            """
            SELECT table_schema, table_name, column_name, data_type, ordinal_position
            FROM information_schema.columns
            WHERE table_schema IN ('ingest','clean','quality','semantic','queries')
            ORDER BY table_schema, table_name, ordinal_position
            """
        ).fetchall()
    return {
        "schema_version": "warehouse_description.v1",
        "status": "passed",
        "snapshot_id": snapshot_id,
        "relations": [
            {"schema": schema, "name": name, "type": kind, "columns": [
                {"name": column, "type": data_type}
                for column_schema, column_table, column, data_type, _ in columns
                if column_schema == schema and column_table == name
            ]}
            for schema, name, kind in rows
        ],
        "errors": [],
    }


def execute_query(
    *, warehouse: Path, snapshot_id: str, sql: str, run_id: str, output_root: Path,
    parameters: Any = None, max_rows: int = 1000, max_result_bytes: int = 1_000_000,
    inline_bytes: int = 64_000,
) -> dict[str, Any]:
    if max_rows < 1 or max_result_bytes < 1 or inline_bytes < 1:
        raise QueryError("QUERY_LIMIT_INVALID", "query limits must be positive")
    if not RUN_ID.fullmatch(run_id):
        raise QueryError("RUN_ID_INVALID", "run_id is invalid")
    with _connect(warehouse) as connection:
        _require_snapshot(connection, snapshot_id)
        validate_query(connection, sql, parameters)
        cursor = connection.execute(sql, parameters)
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchmany(max_rows + 1)
    if len(rows) > max_rows:
        raise QueryError("QUERY_LIMIT_EXCEEDED", f"query returned more than {max_rows} rows")
    payload_rows = [[_json_value(value) for value in row] for row in rows]
    data = {"columns": columns, "rows": payload_rows}
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > max_result_bytes:
        raise QueryError("QUERY_LIMIT_EXCEEDED", f"query result exceeds {max_result_bytes} bytes")
    result: dict[str, Any] = {
        "schema_version": "controlled_query_result.v1",
        "status": "passed",
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "row_count": len(rows),
        "columns": columns,
        "result": None,
        "artifact": None,
        "errors": [],
    }
    if len(encoded) <= inline_bytes:
        result["result"] = data
        return result
    target = output_root / run_id / "data" / "query_results" / f"query_{uuid.uuid4().hex}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    artifact = {
        "artifact_id": f"artifact_{digest[:24]}",
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "path": target.relative_to(output_root / run_id).as_posix(),
        "sha256": digest,
        "size_bytes": len(encoded),
    }
    try:
        with (output_root / run_id / "artifact_manifest.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(artifact, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    result["artifact"] = {
        **artifact,
    }
    return result


def quality_issues(*, warehouse: Path, snapshot_id: str, run_id: str, output_root: Path, max_rows: int = 1000) -> dict[str, Any]:
    return execute_query(
        warehouse=warehouse,
        snapshot_id=snapshot_id,
        sql="SELECT * FROM quality.issues ORDER BY source_id, sheet_name, source_row_number NULLS FIRST, issue_code",
        run_id=run_id,
        output_root=output_root,
        max_rows=max_rows,
    )


def promote_query(
    *, warehouse: Path, snapshot_id: str, sql: str, registry_root: Path,
    query_id: str, version: str, confirmed_by: str,
) -> dict[str, Any]:
    if not QUERY_ID.fullmatch(query_id) or not VERSION.fullmatch(version) or not confirmed_by.strip():
        raise QueryError("PROMOTION_INVALID", "query_id, version, and confirmed_by are required and invalid")
    target = registry_root / query_id / version
    if target.exists():
        raise QueryError("QUERY_VERSION_EXISTS", "saved query version already exists")
    with _connect(warehouse) as read_connection:
        _require_snapshot(read_connection, snapshot_id)
        validate_query(read_connection, sql)
    temporary = target.parent / f".{version}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    sql_path = temporary / "query.sql"
    sql_path.write_text(sql.strip() + "\n", encoding="utf-8")
    digest = hashlib.sha256(sql_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "saved_query.v1",
        "query_id": query_id,
        "version": version,
        "confirmed_by": confirmed_by.strip(),
        "source_snapshot_id": snapshot_id,
        "sql_path": "query.sql",
        "sha256": digest,
    }
    (temporary / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, target)
    except Exception:
        for child in temporary.glob("*"):
            child.unlink()
        if temporary.exists():
            temporary.rmdir()
        raise
    return {"schema_version": "saved_query.v1", "status": "passed", **manifest, "registry_path": f"{query_id}/{version}", "errors": []}


def run_saved_query(
    *, warehouse: Path, snapshot_id: str, registry_root: Path, query_id: str, version: str,
    parameters: Any, run_id: str, output_root: Path, max_rows: int, max_result_bytes: int,
) -> dict[str, Any]:
    target = registry_root / query_id / version
    try:
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        sql_path = target / manifest["sql_path"]
        sql = sql_path.read_text(encoding="utf-8")
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise QueryError("SAVED_QUERY_NOT_FOUND", "saved query cannot be loaded") from exc
    digest = hashlib.sha256(sql_path.read_bytes()).hexdigest()
    if manifest.get("query_id") != query_id or manifest.get("version") != version or manifest.get("sha256") != digest:
        raise QueryError("SAVED_QUERY_INVALID", "saved query manifest or hash is invalid")
    if manifest.get("source_snapshot_id") != snapshot_id:
        raise QueryError("SNAPSHOT_MISMATCH", "saved query was confirmed for a different snapshot")
    return execute_query(
        warehouse=warehouse, snapshot_id=snapshot_id, sql=sql, parameters=parameters,
        run_id=run_id, output_root=output_root, max_rows=max_rows, max_result_bytes=max_result_bytes,
    )
