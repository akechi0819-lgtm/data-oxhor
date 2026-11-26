from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import shutil
from datetime import UTC
from data_platform.query.evidence import encode, file_ref, producer, snapshot_ref, verify_receipt, EvidenceError
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ALLOWED_SCHEMAS = frozenset({"ingest", "landing", "quality", "queries"})
DENIED_FUNCTIONS = re.compile(r"\b(read_csv|read_csv_auto|read_parquet|read_json|read_json_auto|read_xlsx|glob|httpfs_scan)\s*\(", re.IGNORECASE)
DENIED_CATALOG_RELATIONS = re.compile(
    r'(?<![a-z0-9_])(?:"?system"?\s*\.\s*)?"?information_schema"?\s*\.',
    re.IGNORECASE,
)
QUERY_ID = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
VERSION = re.compile(r"^v[0-9]+(?:\.[0-9]+){0,2}$")
RETIRED_SAVED_QUERIES = frozenset(
    {("dashboard_actuals", f"v{version}") for version in range(9, 15)}
    | {("attributed_passive_reported_cash", "v1")}
)
RUN_ID = re.compile(r"^run_[a-z0-9][a-z0-9_-]{2,67}$")



class QueryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject_retired_saved_query(query_id: str, version: str) -> None:
    if (query_id, version) in RETIRED_SAVED_QUERIES:
        raise QueryError("SAVED_QUERY_RETIRED", "saved query version has been retired")


def _json_value(value: Any) -> Any:
    if isinstance(value, (Decimal, date, datetime)):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _connect(
    warehouse: Path,
    *,
    read_only: bool = True,
    config: dict[str, str] | None = None,
) -> duckdb.DuckDBPyConnection:
    if not warehouse.is_file():
        raise QueryError("WAREHOUSE_NOT_FOUND", "warehouse file does not exist")
    if read_only:
        connection_config = {
            "enable_external_access": "false",
            **(config or {}),
            "lock_configuration": "true",
        }
        return duckdb.connect(
            str(warehouse),
            read_only=True,
            config=connection_config,
        )
    return duckdb.connect(str(warehouse))


def _require_snapshot(connection: duckdb.DuckDBPyConnection, snapshot_id: str) -> None:
    try:
        values = {row[0] for row in connection.execute("SELECT DISTINCT snapshot_id FROM ingest.sources").fetchall()}
    except duckdb.Error as exc:
        raise QueryError("WAREHOUSE_INVALID", "warehouse lacks ingest.sources snapshot metadata") from exc
    if values != {snapshot_id}:
        raise QueryError("SNAPSHOT_MISMATCH", "requested snapshot_id does not identify this warehouse")


def _provenance_sql(connection: duckdb.DuckDBPyConnection, sql: str) -> str:
    # get_table_names cannot bind parameters or resolve JOIN USING/NATURAL
    # columns. Normalize these native AST nodes only for dependency discovery;
    # execution and evidence keep the original SQL and parameters unchanged.
    statement = json.loads(connection.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0])
    if statement.get("error"):
        raise QueryError("QUERY_PROVENANCE_INVALID", "cannot serialize SQL for source provenance")
    null_statement = json.loads(connection.execute("SELECT json_serialize_sql('SELECT NULL')").fetchone()[0])
    null_node = null_statement["statements"][0]["node"]["select_list"][0]

    def normalize_for_provenance(value: Any, in_table_function: bool = False) -> Any:
        if isinstance(value, dict):
            in_table_function = in_table_function or value.get("type") == "TABLE_FUNCTION"
            if value.get("class") == "PARAMETER":
                if in_table_function:
                    raise QueryError("QUERY_PROVENANCE_INVALID", "parameters in table functions cannot establish stable source provenance")
                return null_node
            normalized = {key: normalize_for_provenance(item, in_table_function) for key, item in value.items()}
            if value.get("type") == "JOIN" and (value.get("using_columns") or value.get("ref_type") == "NATURAL"):
                normalized.update(using_columns=[], ref_type="CROSS", join_type="INNER")
            return normalized
        if isinstance(value, list):
            return [normalize_for_provenance(item, in_table_function) for item in value]
        return value

    return connection.execute(
        "SELECT json_deserialize_sql(?)", [json.dumps(normalize_for_provenance(statement))]
    ).fetchone()[0]


def _query_source_provenance(connection: duckdb.DuckDBPyConnection, sql: str) -> tuple[list[str], list[str]]:
    try:
        names = connection.get_table_names(_provenance_sql(connection, sql), qualified=True)
        relations = set()
        for name in names:
            # Let DuckDB decode quoted identifiers, including embedded dots and
            # escaped quotes, instead of splitting SQL names ourselves.
            parsed = json.loads(connection.execute(
                "SELECT json_serialize_sql(?)", ["SELECT * FROM " + name]
            ).fetchone()[0])
            if parsed.get("error"):
                raise QueryError("QUERY_PROVENANCE_INVALID", "cannot parse source relation: " + name)
            relation = parsed["statements"][0]["node"]["from_table"]
            schema = relation["schema_name"]
            if not schema:
                raise QueryError("QUERY_PROVENANCE_INVALID", "source relation must be schema-qualified: " + name)
            if schema.lower() == "landing":
                relations.add(relation["table_name"])
    except duckdb.Error as exc:
        raise QueryError("QUERY_PROVENANCE_INVALID", "cannot resolve query source provenance: " + str(exc)) from exc
    if not relations:
        return [], []
    # DuckDB identifiers are ASCII case-insensitive, even when quoted. Preserve
    # the registered spelling in evidence instead of the query's spelling.
    fold = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
    rows = connection.execute("SELECT target_table, source_id FROM ingest.sheets").fetchall()
    mapped = {table.translate(fold): (table, source_id) for table, source_id in rows}
    missing = sorted(name for name in relations if name.translate(fold) not in mapped)
    if missing:
        raise QueryError("QUERY_PROVENANCE_INVALID", "landing relation has no source provenance: " + ", ".join(missing))
    referenced = [mapped[name.translate(fold)] for name in relations]
    return sorted({f"landing.{table}" for table, _ in referenced}), sorted({source for _, source in referenced})


def validate_query(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    parameters: Any = None,
    *,
    allowed_schemas: frozenset[str] | set[str] = ALLOWED_SCHEMAS,
) -> None:
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
    nodes = [json.loads(plan[1])] if plan else []
    while nodes:
        node = nodes.pop()
        if isinstance(node, list):
            nodes.extend(node)
        elif isinstance(node, dict):
            table = node.get("Table")
            if isinstance(table, str):
                parts = re.findall(r'"(?:[^"]|"")*"|[^.]+', table)
                schema = parts[-2].strip('"').replace('""', '"') if len(parts) >= 2 else None
                if schema is not None and schema not in allowed_schemas:
                    raise QueryError("QUERY_REJECTED", f"schema is not allowed: {schema}")
            nodes.extend(node.values())


_BUSINESS_DENIED_FUNCTIONS = frozenset({
    "current_catalog", "current_database", "current_query", "current_schema",
    "current_setting", "current_user", "getenv", "glob", "session_user",
    "user", "version",
})


def _validate_business_query_ast(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    *,
    allowed_relations: set[str] | frozenset[str],
    allowed_schema: str = "landing",
    allowed_table_macros: set[str] | frozenset[str] = frozenset(),
    allowed_qualified: frozenset[str] | None = None,
) -> set[str]:
    """Validate registered relations and identify the explicitly referenced tables."""
    try:
        statement = json.loads(connection.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0])
    except (duckdb.Error, TypeError, ValueError) as exc:
        raise QueryError("QUERY_INVALID", "cannot parse query") from exc
    if statement.get("error") or len(statement.get("statements", [])) != 1:
        raise QueryError("QUERY_REJECTED", "exactly one SELECT statement is required")

    cte_names: set[str] = set()

    def collect_ctes(value: Any) -> None:
        if isinstance(value, dict):
            cte_map = value.get("cte_map")
            if isinstance(cte_map, dict):
                for item in cte_map.get("map", []):
                    if isinstance(item, dict) and isinstance(item.get("key"), str):
                        cte_names.add(item["key"].casefold())
            for child in value.values():
                collect_ctes(child)
        elif isinstance(value, list):
            for child in value:
                collect_ctes(child)

    collect_ctes(statement)
    allowed = (allowed_qualified if allowed_qualified is not None
               else {f'{allowed_schema.casefold()}.{name.casefold()}' for name in allowed_relations})
    referenced = set()

    def inspect(value: Any) -> None:
        if isinstance(value, dict):
            node_type = value.get("type")
            node_class = value.get("class")
            if node_type == "TABLE_FUNCTION":
                function = value.get("function", {})
                if (function.get("catalog") or
                    str(function.get("schema", "")).casefold() != allowed_schema.casefold() or
                    str(function.get("function_name", "")).casefold() not in allowed_table_macros):
                    raise QueryError("QUERY_REJECTED", "table functions are not available")
            if node_type == "BASE_TABLE":
                schema = value.get("schema_name", "")
                table = value.get("table_name", "")
                catalog = value.get("catalog_name", "")
                if catalog:
                    raise QueryError("QUERY_REJECTED", "catalog-qualified tables are not available")
                if not schema and str(table).casefold() in cte_names:
                    pass
                elif (qualified := f'{schema.casefold()}.{table.casefold()}') in allowed:
                    referenced.add(qualified)
                else:
                    label = 'semantic' if allowed_qualified is not None else allowed_schema
                    raise QueryError("QUERY_REJECTED", "query may read only registered " + label + " tables")
            if node_class == "FUNCTION":
                name = str(value.get("function_name", "")).casefold()
                if (name in _BUSINESS_DENIED_FUNCTIONS or name.startswith(("duckdb_", "pg_", "pragma_", "read_"))):
                    raise QueryError("QUERY_REJECTED", "system and external-reader functions are not available")
            if node_class == "COLUMN_REF":
                names = value.get("column_names", [])
                if any(str(name).casefold() in _BUSINESS_DENIED_FUNCTIONS for name in names):
                    raise QueryError("QUERY_REJECTED", "system metadata is not available")
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    inspect(statement)
    return referenced


def _business_csv_cell(value: Any) -> str:
    if value is None:
        return ""
    value = _json_value(value)
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
    raw = str(value)
    return '"' + raw.replace('"', '""') + '"'


def _business_csv_row(values: list[Any]) -> str:
    return ",".join(_business_csv_cell(value) for value in values) + "\r\n"


def _minimum_json_size(value: Any) -> int:
    if value is None:
        return 4
    if isinstance(value, str):
        return len(value)
    if isinstance(value, bytes):
        return len(value) * 2
    if isinstance(value, dict):
        return sum(_minimum_json_size(key) + _minimum_json_size(item) + 2 for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return sum(_minimum_json_size(item) + 1 for item in value)
    return len(str(value))


def execute_query_bundle(
    *,
    warehouse: Path,
    snapshot_id: str,
    sql: str,
    parameters: Any = None,
    output_dir: Path,
    allowed_relations: set[str] | frozenset[str],
    max_result_bytes: int = 128 * 1024 * 1024,
) -> dict[str, Any]:
    """Execute once, saving the full typed result as JSONL.

    This is a service-facing extension for paged delivery. It intentionally has
    no row preview limit: callers receive a full row count and may page over the
    artifacts created by this execution.
    """
    if max_result_bytes < 1:
        raise QueryError("QUERY_LIMIT_INVALID", "max_result_bytes must be positive")
    try:
        identity = snapshot_ref(warehouse, snapshot_id)
    except EvidenceError as exc:
        raise QueryError("SNAPSHOT_MANIFEST_INVALID", str(exc)) from exc
    output_dir.mkdir(parents=True, exist_ok=False)
    temporary = output_dir / ".duckdb-tmp"
    try:
        temporary.mkdir(mode=0o700)
        with _connect(warehouse, config={
            "memory_limit": "1GB",
            "threads": "2",
            "temp_directory": str(temporary),
            "max_temp_directory_size": "256MB",
        }) as connection:
            _require_snapshot(connection, snapshot_id)
            _validate_business_query_ast(connection, sql, allowed_relations=allowed_relations)
            validate_query(connection, sql, parameters, allowed_schemas={"landing"})
            referenced_relations, referenced_source_ids = _query_source_provenance(connection, sql)
            if not set(referenced_relations).issubset({f"landing.{name}" for name in allowed_relations}):
                raise QueryError("QUERY_REJECTED", "query references an unavailable landing table")
            cursor = connection.execute(sql, parameters)
            columns = [item[0] for item in cursor.description]
            count = 0
            result_bytes = 0
            with (output_dir / "rows.jsonl").open("w", encoding="utf-8", newline="\n") as rows_file:
                while True:
                    chunk = cursor.fetchmany(100)
                    if not chunk:
                        break
                    for row in chunk:
                        if sum(_minimum_json_size(value) for value in row) > max_result_bytes:
                            raise QueryError("QUERY_RESULT_TOO_LARGE", "query result exceeds the configured byte limit")
                        values = [_json_value(value) for value in row]
                        line = json.dumps(values, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
                        result_bytes += len(line.encode("utf-8"))
                        if result_bytes > max_result_bytes:
                            raise QueryError("QUERY_RESULT_TOO_LARGE", "query result exceeds the configured byte limit")
                        rows_file.write(line)
                        count += 1
        shutil.rmtree(temporary, ignore_errors=True)
        return {
            "columns": columns,
            "row_count": count,
            "referenced_relations": referenced_relations,
            "referenced_source_ids": referenced_source_ids,
            "snapshot_ref": identity,
            "rows_path": str(output_dir / "rows.jsonl"),
            "result_bytes": result_bytes,
        }
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def describe_warehouse(*, warehouse: Path, snapshot_id: str) -> dict[str, Any]:
    with _connect(warehouse) as connection:
        _require_snapshot(connection, snapshot_id)
        header_metadata = {
            table: json.loads(headers) if headers else []
            for table, headers in connection.execute(
                "SELECT target_table, header_columns FROM ingest.sheets"
            ).fetchall()
        }
        rows = connection.execute(
            """
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema IN ('ingest','landing','quality','queries')
            ORDER BY table_schema, table_name
            """
        ).fetchall()
        columns = connection.execute(
            """
            SELECT table_schema, table_name, column_name, data_type, ordinal_position
            FROM information_schema.columns
            WHERE table_schema IN ('ingest','landing','quality','queries')
            ORDER BY table_schema, table_name, ordinal_position
            """
        ).fetchall()
    return {
        "schema_version": "warehouse_description.v1",
        "status": "passed",
        "snapshot_id": snapshot_id,
        "relations": [
            {"schema": schema, "name": name, "type": kind, "columns": [
                {
                    "name": column,
                    "type": data_type,
                    **({"header_label": next((
                        item.get("original_name")
                        for item in header_metadata.get(column_table, [])
                        if item.get("technical_name") == column
                    ), None)} if column_table in header_metadata else {}),
                }
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
    inline_bytes: int = 64_000, saved_query_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    if max_rows < 1 or max_result_bytes < 1 or inline_bytes < 1:
        raise QueryError("QUERY_LIMIT_INVALID", "query limits must be positive")
    if not RUN_ID.fullmatch(run_id):
        raise QueryError("RUN_ID_INVALID", "run_id is invalid")
    try:
        identity = snapshot_ref(warehouse, snapshot_id)
    except EvidenceError as exc:
        raise QueryError("SNAPSHOT_MANIFEST_INVALID", str(exc)) from exc
    with _connect(warehouse) as connection:
        _require_snapshot(connection, snapshot_id)
        validate_query(connection, sql, parameters)
        referenced_relations, referenced_source_ids = _query_source_provenance(connection, sql)
        cursor = connection.execute(sql, parameters)
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchmany(max_rows + 1)
    if len(rows) > max_rows:
        raise QueryError("QUERY_LIMIT_EXCEEDED", f"query returned more than {max_rows} rows")
    payload_rows = [[_json_value(value) for value in row] for row in rows]
    data = {"columns": columns, "rows": payload_rows}
    encoded = encode(data)
    if len(encoded) > max_result_bytes:
        raise QueryError("QUERY_LIMIT_EXCEEDED", f"query result exceeds {max_result_bytes} bytes")
    evidence_id = "evidence_" + uuid.uuid4().hex
    target = output_root / run_id / "data" / "query_results" / evidence_id
    if not target.resolve().is_relative_to(output_root.resolve()):
        raise QueryError("EVIDENCE_PATH_INVALID", "query output escapes output root")
    target.mkdir(parents=True, exist_ok=False)
    try:
        (target / "query.sql").write_bytes(sql.encode("utf-8"))
        (target / "parameters.json").write_bytes(encode(parameters))
        (target / "result.json").write_bytes(encoded)
        receipt = {
            "schema_version": "query_receipt.v1", "kind": "query", "evidence_id": evidence_id,
            "run_id": run_id, "snapshot_id": snapshot_id, "snapshot_ref": identity,
            "created_at": datetime.now(UTC).isoformat(), "producer": producer("data_platform.query"),
            "sql": file_ref(target / "query.sql", target, "text/plain"),
            "parameters": file_ref(target / "parameters.json", target, "application/json"),
            "result": file_ref(target / "result.json", target, "application/json"),
            "row_count": len(rows), "columns": columns,
            "limits": {"max_rows": max_rows, "max_result_bytes": max_result_bytes},
            "referenced_relations": referenced_relations, "referenced_source_ids": referenced_source_ids,
        }
        if saved_query_ref is not None:
            receipt["saved_query_ref"] = saved_query_ref
        receipt_path = target / "receipt.json"
        receipt_path.write_bytes(encode(receipt))
        verify_receipt(receipt_path)
        return {"schema_version": "controlled_query_result.v2", "status": "passed",
                "run_id": run_id, "snapshot_id": snapshot_id,
                "receipt": file_ref(receipt_path, output_root / run_id, "application/json", evidence_id=evidence_id),
                "result": data if len(encoded) <= inline_bytes else None, "errors": []}
    except Exception:
        shutil.rmtree(target)
        raise


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
    _reject_retired_saved_query(query_id, version)
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
    _reject_retired_saved_query(query_id, version)
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
    return execute_query(
        warehouse=warehouse, snapshot_id=snapshot_id, sql=sql, parameters=parameters,
        run_id=run_id, output_root=output_root, max_rows=max_rows, max_result_bytes=max_result_bytes,
        saved_query_ref={"query_id": query_id, "version": version},
    )
