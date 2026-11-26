"""Read-only SQL query support for sealed single-warehouse releases."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import duckdb

from data_platform.query.evidence import EvidenceError, load_json_bytes, resolve_file
from data_platform.query.service import (
    QueryError,
    _connect,
    _json_value,
    _minimum_json_size,
    _provenance_sql,
    _validate_business_query_ast,
    validate_query,
)


CANDIDATE_SCHEMA = "sql_warehouse_candidate.v1"
RELEASE_SCHEMA = "sql_warehouse_release.v1"
CONTROLLED_QUERY_SCHEMA = "controlled_query_result.v2"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RELEASE_ID = re.compile(r"^[a-z][a-z0-9_-]{2,96}$")

PUBLIC_RELATIONS: dict[str, str] = {
    "landing.br_work_orders__sheet_1f0596db9f25": "training",
    "landing.br_cash__sheet_39b8dee2e4b3": "training",
    "landing.study_abroad_market__resources": "study",
    "landing.study_abroad_market__contracts": "study",
    "landing.study_abroad_market__languages": "study",
}
SEMANTIC_RELATIONS = frozenset({
    "core.training_orders_attributed", "core.training_cash_attributed",
    "core.training_heads_attributed", "core.abroad_facts_attributed",
    "core.abroad_heads_attributed", "core.abroad_excluded_source",
    "core.training_channel_orders_attributed", "core.dimension_heads_attributed",
    "core.training_channel_source_exclusions",
    "mart.team_metrics", "mart.dimension_metrics", "mart.study_abroad_summary",
    "ref.official_scorecard",
})
DOMAIN_IMPORT_SOURCE = {"training": "training", "study": "abroad"}
DOMAIN_SNAPSHOT_KEY = {"training": "training", "study": "abroad"}


@dataclass(frozen=True)
class SqlWarehouseRelease:
    root: Path
    library: Path
    release: str
    batch_id: str
    as_of_date: str
    data_through: str
    snapshots: dict[str, str]
    warehouse: Path
    candidate_path: Path
    release_manifest_path: Path
    landing_description_path: Path
    candidate: dict[str, Any]
    manifest: dict[str, Any]
    landing_description: dict[str, Any]
    landing_provenance: dict[str, dict[str, str]]
    candidate_sha256: str
    database_sha256: str
    release_manifest_sha256: str

    def snapshot_for(self, domain: str) -> str:
        key = DOMAIN_SNAPSHOT_KEY.get(domain)
        snapshot = self.snapshots.get(key) if key else None
        if not isinstance(snapshot, str):
            raise QueryError("SQL_RELEASE_INVALID", "The requested data version is unavailable.")
        return snapshot


def _invalid(code: str = "SQL_RELEASE_INVALID") -> QueryError:
    return QueryError(code, "The current SQL data release is unavailable or invalid.")


def _direct_file(root: Path, name: str) -> Path:
    path = root / name
    if path.is_symlink():
        raise _invalid()
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _invalid() from exc
    if resolved.parent != root or not resolved.is_file():
        raise _invalid()
    return resolved


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = load_json_bytes(raw)
    except (OSError, UnicodeError, ValueError, EvidenceError) as exc:
        raise _invalid() from exc
    if not isinstance(value, dict):
        raise _invalid()
    return value, raw


def _verify_ref(library: Path, reference: Any, expected_name: str) -> Path:
    if not isinstance(reference, dict) or reference.get("path") != expected_name:
        raise _invalid()
    path = _direct_file(library, expected_name)
    try:
        verified = resolve_file(library, reference)
    except EvidenceError as exc:
        raise _invalid() from exc
    if verified != path:
        raise _invalid()
    return path


def _valid_relative_receipt_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def _validate_candidate_source_queries(candidate: dict[str, Any], snapshots: dict[str, str]) -> None:
    queries = candidate.get("source_queries")
    if not isinstance(queries, list) or not queries:
        raise _invalid("SQL_RELEASE_SOURCE_INVALID")
    seen_snapshots: set[str] = set()
    for query in queries:
        if (
            not isinstance(query, dict)
            or query.get("schema_version") != CONTROLLED_QUERY_SCHEMA
            or query.get("status") != "passed"
            or query.get("snapshot_id") not in set(snapshots.values())
            or query.get("errors") != []
        ):
            raise _invalid("SQL_RELEASE_SOURCE_INVALID")
        receipt = query.get("receipt")
        if (
            not isinstance(receipt, dict)
            or not _valid_relative_receipt_path(receipt.get("path"))
            or not isinstance(receipt.get("sha256"), str)
            or not SHA256.fullmatch(receipt["sha256"])
            or type(receipt.get("size_bytes")) is not int
            or receipt["size_bytes"] < 1
            or receipt.get("media_type") != "application/json"
        ):
            raise _invalid("SQL_RELEASE_SOURCE_INVALID")
        seen_snapshots.add(query["snapshot_id"])
    if seen_snapshots != set(snapshots.values()):
        raise _invalid("SQL_RELEASE_SOURCE_INVALID")


def _validate_landing_description(
    description: Any,
    snapshots: dict[str, str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(description, dict) or set(description) != {"training", "study"}:
        raise _invalid("SQL_RELEASE_SCHEMA_INVALID")
    output: dict[str, dict[str, Any]] = {}
    for domain, snapshot_key in DOMAIN_SNAPSHOT_KEY.items():
        item = description.get(domain)
        if (
            not isinstance(item, dict)
            or item.get("schema_version") != "warehouse_description.v1"
            or item.get("status") != "passed"
            or item.get("snapshot_id") != snapshots[snapshot_key]
            or not isinstance(item.get("relations"), list)
        ):
            raise _invalid("SQL_RELEASE_SCHEMA_INVALID")
        required = {name.split(".", 1)[1] for name, source_domain in PUBLIC_RELATIONS.items() if source_domain == domain}
        relations: dict[str, dict[str, Any]] = {}
        for relation in item["relations"]:
            if not isinstance(relation, dict) or relation.get("schema") != "landing":
                continue
            name = relation.get("name")
            if isinstance(name, str) and name in required:
                if name in relations or not isinstance(relation.get("columns"), list):
                    raise _invalid("SQL_RELEASE_SCHEMA_INVALID")
                columns: set[str] = set()
                for column in relation["columns"]:
                    if (
                        not isinstance(column, dict)
                        or not isinstance(column.get("name"), str)
                        or not column["name"]
                        or not isinstance(column.get("type"), str)
                        or not column["type"]
                        or column["name"] in columns
                    ):
                        raise _invalid("SQL_RELEASE_SCHEMA_INVALID")
                    label = column.get("header_label")
                    if label is not None and (not isinstance(label, str) or not label):
                        raise _invalid("SQL_RELEASE_SCHEMA_INVALID")
                    columns.add(column["name"])
                relations[name] = relation
        if set(relations) != required:
            raise _invalid("SQL_RELEASE_SCHEMA_INVALID")
        output[domain] = item
    return output


def _validate_landing_provenance(value: Any, snapshots: dict[str, str]) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or set(value) != set(PUBLIC_RELATIONS):
        raise _invalid("SQL_RELEASE_SOURCE_INVALID")
    output: dict[str, dict[str, str]] = {}
    for relation, domain in PUBLIC_RELATIONS.items():
        item = value.get(relation)
        expected_snapshot = snapshots[DOMAIN_SNAPSHOT_KEY[domain]]
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("source_id"), str)
            or not item["source_id"].strip()
            or item.get("snapshot_id") != expected_snapshot
            or item.get("domain") != domain
        ):
            raise _invalid("SQL_RELEASE_SOURCE_INVALID")
        output[relation] = {
            "source_id": item["source_id"],
            "snapshot_id": expected_snapshot,
            "domain": domain,
        }
    return output


def _validate_database_metadata(
    database: Path,
    batch_id: str,
    snapshots: dict[str, str],
    provenance: dict[str, dict[str, str]],
) -> None:
    try:
        with _connect(database) as connection:
            identity = connection.execute("SELECT batch_id FROM meta.identity").fetchall()
            imports = connection.execute("SELECT source, snapshot_id, relation FROM meta.imports").fetchall()
    except (duckdb.Error, QueryError) as exc:
        raise _invalid("SQL_RELEASE_WAREHOUSE_INVALID") from exc
    if identity != [(batch_id,)]:
        raise _invalid("SQL_RELEASE_IDENTITY_INVALID")
    if len(imports) != len(PUBLIC_RELATIONS):
        raise _invalid("SQL_RELEASE_SOURCE_INVALID")
    seen: set[str] = set()
    for source, snapshot_id, relation in imports:
        if not all(isinstance(value, str) and value for value in (source, snapshot_id, relation)):
            raise _invalid("SQL_RELEASE_SOURCE_INVALID")
        relation = relation.removeprefix("landing.")
        qualified = "landing." + relation
        domain = PUBLIC_RELATIONS.get(qualified)
        if domain is None or relation in seen:
            raise _invalid("SQL_RELEASE_SOURCE_INVALID")
        source_key = DOMAIN_IMPORT_SOURCE[domain]
        expected_snapshot = snapshots[DOMAIN_SNAPSHOT_KEY[domain]]
        mapped = provenance[qualified]
        if source != source_key or snapshot_id != expected_snapshot or mapped["snapshot_id"] != snapshot_id:
            raise _invalid("SQL_RELEASE_SOURCE_INVALID")
        seen.add(relation)
    expected_names = {name.split(".", 1)[1] for name in PUBLIC_RELATIONS}
    if seen != expected_names:
        raise _invalid("SQL_RELEASE_SOURCE_INVALID")


def resolve_sql_release(release_root: Path) -> SqlWarehouseRelease | None:
    """Resolve and verify a candidate release; return None for the legacy release shape."""
    try:
        root = Path(release_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _invalid() from exc
    if not root.is_dir() or root.parent.name != "releases" or not RELEASE_ID.fullmatch(root.name):
        raise _invalid()
    library = root / "library"
    if library.is_symlink():
        raise _invalid()
    try:
        library = library.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _invalid() from exc
    if not library.is_dir() or library.parent != root:
        raise _invalid()
    candidate_path = library / "candidate.json"
    if candidate_path.is_symlink():
        raise _invalid()
    if not candidate_path.exists():
        return None
    candidate, candidate_bytes = _read_json(candidate_path)
    if candidate.get("schema_version") != CANDIDATE_SCHEMA:
        return None

    release_manifest_path = _direct_file(library, "release.json")
    manifest, release_bytes = _read_json(release_manifest_path)
    if manifest.get("schema_version") != RELEASE_SCHEMA or manifest.get("release_id") != root.name:
        raise _invalid()

    candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
    candidate_reference = _verify_ref(library, manifest.get("candidate"), "candidate.json")
    if (
        manifest.get("candidate_sha256") != candidate_sha256
        or manifest["candidate"].get("sha256") != candidate_sha256
        or candidate_reference != candidate_path.resolve(strict=True)
    ):
        raise _invalid("SQL_RELEASE_IDENTITY_INVALID")

    database_reference = candidate.get("database")
    if not isinstance(database_reference, dict) or database_reference.get("path") != "warehouse.duckdb":
        raise _invalid("SQL_RELEASE_IDENTITY_INVALID")
    warehouse = _verify_ref(library, database_reference, "warehouse.duckdb")
    database_sha256 = database_reference.get("sha256")
    if manifest.get("database_sha256") != database_sha256 or not isinstance(database_sha256, str):
        raise _invalid("SQL_RELEASE_IDENTITY_INVALID")

    batch_id = candidate.get("batch_id")
    snapshots = candidate.get("snapshots")
    if (
        not isinstance(batch_id, str)
        or not re.fullmatch(r"run_[a-z0-9][a-z0-9_-]{2,67}", batch_id)
        or manifest.get("batch_id") != batch_id
        or not isinstance(snapshots, dict)
        or set(snapshots) != {"training", "abroad"}
        or not all(isinstance(value, str) and value for value in snapshots.values())
        or manifest.get("snapshots") != snapshots
    ):
        raise _invalid("SQL_RELEASE_IDENTITY_INVALID")

    as_of_date = candidate.get("as_of_date")
    coverage = manifest.get("coverage")
    data_through = coverage.get("data_through") if isinstance(coverage, dict) else None
    if (
        not isinstance(as_of_date, str)
        or manifest.get("as_of_date") != as_of_date
        or not isinstance(data_through, str)
        or candidate.get("through_date") != data_through
    ):
        raise _invalid("SQL_RELEASE_IDENTITY_INVALID")
    try:
        date.fromisoformat(as_of_date)
        date.fromisoformat(data_through)
    except ValueError as exc:
        raise _invalid("SQL_RELEASE_IDENTITY_INVALID") from exc

    _validate_candidate_source_queries(candidate, snapshots)
    provenance = _validate_landing_provenance(manifest.get("landing_provenance"), snapshots)

    description_reference = manifest.get("landing_description")
    description_path = _verify_ref(library, description_reference, "landing-description.json")
    description_doc, _ = _read_json(description_path)
    landing_description = _validate_landing_description(description_doc, snapshots)
    _validate_database_metadata(warehouse, batch_id, snapshots, provenance)

    return SqlWarehouseRelease(
        root=root,
        library=library,
        release=root.name,
        batch_id=batch_id,
        as_of_date=as_of_date,
        data_through=data_through,
        snapshots=dict(snapshots),
        warehouse=warehouse,
        candidate_path=candidate_path.resolve(strict=True),
        release_manifest_path=release_manifest_path,
        landing_description_path=description_path,
        candidate=candidate,
        manifest=manifest,
        landing_description=landing_description,
        landing_provenance=provenance,
        candidate_sha256=candidate_sha256,
        database_sha256=database_sha256,
        release_manifest_sha256=hashlib.sha256(release_bytes).hexdigest(),
    )


def describe_sql_release_table(
    release: SqlWarehouseRelease,
    domain: str,
    relation: str,
) -> dict[str, Any] | None:
    if domain not in DOMAIN_SNAPSHOT_KEY or relation not in PUBLIC_RELATIONS:
        return None
    if PUBLIC_RELATIONS[relation] != domain:
        return None
    name = relation.split(".", 1)[1]
    descriptor = release.landing_description[domain]
    return next((item for item in descriptor["relations"]
                 if item.get("schema") == "landing" and item.get("name") == name), None)


def _query_source_provenance(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    release: SqlWarehouseRelease,
    allowed_relations: set[str] | frozenset[str],
) -> tuple[list[str], list[str]]:
    try:
        names = connection.get_table_names(_provenance_sql(connection, sql), qualified=True)
        relations: set[str] = set()
        for name in names:
            parsed = json.loads(connection.execute(
                "SELECT json_serialize_sql(?)", ["SELECT * FROM " + name]
            ).fetchone()[0])
            if parsed.get("error"):
                raise QueryError("QUERY_PROVENANCE_INVALID", "cannot parse source relation")
            relation = parsed["statements"][0]["node"]["from_table"]
            schema = relation.get("schema_name")
            table = relation.get("table_name")
            if not schema:
                raise QueryError("QUERY_PROVENANCE_INVALID", "source relation must be schema-qualified")
            if schema.casefold() != "landing":
                continue
            qualified = f"landing.{table}"
            if table not in allowed_relations or qualified not in release.landing_provenance:
                raise QueryError("QUERY_PROVENANCE_INVALID", "landing relation has no sealed source provenance")
            relations.add(qualified)
    except duckdb.Error as exc:
        raise QueryError("QUERY_PROVENANCE_INVALID", "cannot resolve query source provenance") from exc
    referenced_source_ids = sorted({release.landing_provenance[name]["source_id"] for name in relations})
    return sorted(relations), referenced_source_ids


def execute_query_bundle(
    *,
    release_root: Path,
    expected_release: str,
    expected_batch_id: str,
    domain: str,
    sql: str,
    parameters: Any = None,
    output_dir: Path,
    allowed_relations: set[str] | frozenset[str],
    max_result_bytes: int = 128 * 1024 * 1024,
    dashboard_dataset: str | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Execute one SQL release query and stream the full bounded result to JSONL."""
    if max_rows is not None and (type(max_rows) is not int or max_rows < 1):
        raise QueryError("QUERY_LIMIT_INVALID", "max_rows must be positive")
    if max_result_bytes < 1:
        raise QueryError("QUERY_LIMIT_INVALID", "max_result_bytes must be positive")
    release = resolve_sql_release(release_root)
    if (
        release is None
        or release.release != expected_release
        or release.batch_id != expected_batch_id
    ):
        raise QueryError("SQL_RELEASE_IDENTITY_INVALID", "The requested data version is unavailable.")
    expected_allowed = {
        relation.split(".", 1)[1]
        for relation, source_domain in PUBLIC_RELATIONS.items()
        if source_domain == domain
    }
    schema = "landing"
    semantic = domain == "semantic"
    if semantic:
        advertised = release.candidate.get("semantic_relations")
        if not isinstance(advertised, list) or not advertised or any(
                not isinstance(relation, str) or relation not in SEMANTIC_RELATIONS for relation in advertised):
            raise QueryError("TABLE_NOT_FOUND", "Semantic relations are unavailable in this sealed release")
        expected_allowed = set(advertised)
    if dashboard_dataset is not None:
        from .dashboard_results import DATASETS
        if (domain != "dashboard" or dashboard_dataset not in DATASETS
                or dashboard_dataset not in release.candidate.get("query_relations", [])):
            raise QueryError("TABLE_NOT_FOUND", "Dashboard dataset is unavailable in this release")
        schema = "business"
        expected_allowed = {dashboard_dataset}
    elif not semantic and domain not in DOMAIN_SNAPSHOT_KEY:
        raise QueryError("QUERY_REJECTED", "Unknown query domain")
    if set(allowed_relations) != expected_allowed:
        raise QueryError("QUERY_REJECTED", "Query relation is outside the requested scope")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    temporary = output_dir / ".duckdb-tmp"
    try:
        temporary.mkdir(mode=0o700)
        with _connect(release.warehouse, config={
            "memory_limit": "1GB",
            "threads": "2",
            "temp_directory": str(temporary),
            "max_temp_directory_size": "256MB",
        }) as connection:
            referenced = _validate_business_query_ast(
                connection,
                sql,
                allowed_relations=expected_allowed,
                allowed_schema=schema,
                allowed_qualified=frozenset(expected_allowed) if semantic else None,
            )
            validate_query(connection, sql, parameters, allowed_schemas=(
                set(release.candidate["schemas"]) if semantic or dashboard_dataset is not None else {schema}))
            if semantic:
                if not referenced:
                    raise QueryError("QUERY_REJECTED", "A semantic query must reference a registered relation")
                referenced_relations = sorted(referenced)
                referenced_source_ids = []
            elif dashboard_dataset is None:
                referenced_relations, referenced_source_ids = _query_source_provenance(
                    connection, sql, release, expected_allowed
                )
            else:
                referenced_relations = ["business." + dashboard_dataset]
                referenced_source_ids = []
            cursor = connection.execute(sql, parameters)
            columns = [item[0] for item in cursor.description]
            row_count = 0
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
                        row_count += 1
                        if max_rows is not None and row_count > max_rows:
                            raise QueryError("QUERY_RESULT_TOO_LARGE", "query result exceeds the configured row limit")
        shutil.rmtree(temporary, ignore_errors=True)
        return {
            "columns": columns,
            "row_count": row_count,
            "referenced_relations": referenced_relations,
            "referenced_source_ids": referenced_source_ids,
            "snapshot_ref": {
                "kind": "sql_warehouse_release_ref.v1",
                "release": release.release,
                "batch_id": release.batch_id,
                "release_manifest_sha256": release.release_manifest_sha256,
                "candidate_sha256": release.candidate_sha256,
                "warehouse_sha256": release.database_sha256,
                "snapshots": release.snapshots,
            },
            "rows_path": str(output_dir / "rows.jsonl"),
            "result_bytes": result_bytes,
        }
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise
