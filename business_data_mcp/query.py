from __future__ import annotations

import json
import fcntl
import multiprocessing
import os
import re
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from data_platform.dashboard_results import TEAM_METRICS_PRIOR, dataset_catalog, result_query
from data_platform.query.service import QueryError, describe_warehouse, execute_query_bundle
from data_platform.sql_release_query import (
    SqlWarehouseRelease,
    describe_sql_release_table,
    execute_query_bundle as execute_sql_release_query_bundle,
    resolve_sql_release,
)


Domain = Literal["training", "study"]

TABLES: dict[str, tuple[dict[str, str], ...]] = {
    "training": (
        {
            "id": "work_orders",
            "name": "语培工单",
            "relation": "landing.br_work_orders__sheet_1f0596db9f25",
            "description": "按工单 ID 取首条物理行的维表；这是明确去重后的结果。",
        },
        {
            "id": "cash_events",
            "name": "语培签约/现金事件",
            "relation": "landing.br_cash__sheet_39b8dee2e4b3",
            "description": "保留每条原始现金来源行；可按工单 ID 左连已按 ID 去重的工单。金额字段以原始列为准。",
        },
    ),
    "study": (
        {
            "id": "resources",
            "name": "留学工单/资源",
            "relation": "landing.study_abroad_market__resources",
            "description": "保留每条留学资源登记来源行、来源标识与资格字段；不预先去重。",
        },
        {
            "id": "contracts",
            "name": "留学签约",
            "relation": "landing.study_abroad_market__contracts",
            "description": "按合同编号取首行；金额为签约金额。资源关联未匹配时保留合同。",
        },
        {
            "id": "language_payments",
            "name": "小语种实缴",
            "relation": "landing.study_abroad_market__languages",
            "description": "来源行实缴记录，金额为实缴金额。",
        },
    ),
}

RESULT_ID = re.compile(r"^result_[0-9a-f]{32}$")
RELEASE_ID = re.compile(r"^[a-z][a-z0-9_-]{2,96}$")
MAX_PAGE_SIZE = 500
MAX_RESULT_BYTES = 128 * 1024 * 1024
MAX_QUERY_TEMP_BYTES = 256 * 1024 * 1024
MAX_RESERVATION_BYTES = MAX_RESULT_BYTES + MAX_QUERY_TEMP_BYTES
MAX_TOTAL_RESULT_BYTES = 1024 * 1024 * 1024
MAX_QUERY_INPUT_BYTES = 256 * 1024
MAX_QUERY_OUTPUT_BYTES = MAX_RESULT_BYTES - (2 * 1024 * 1024)
MAX_PAGE_RESPONSE_BYTES = 256 * 1024
RESERVATION_STALE_SECONDS = 60 * 60


class BusinessDataMCPError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WarehouseRef:
    path: Path
    snapshot_id: str


@dataclass(frozen=True)
class CurrentRelease:
    release: str
    batch_id: str
    data_through: str
    snapshots: dict[str, str]
    warehouses: dict[str, WarehouseRef]


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BusinessDataMCPError(code, "The current data release is unavailable or invalid.") from exc
    if not isinstance(value, dict):
        raise BusinessDataMCPError(code, "The current data release is unavailable or invalid.")
    return value


def _safe_warehouse(foundation: Path, relative: Any, snapshot_id: Any) -> WarehouseRef:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.")
    candidate = foundation / relative
    try:
        if candidate.is_symlink():
            raise ValueError()
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(foundation) or resolved.name != "warehouse.duckdb" or not resolved.is_file():
            raise ValueError()
    except (OSError, RuntimeError, ValueError) as exc:
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.") from exc
    return WarehouseRef(resolved, snapshot_id)


def resolve_current(current_path: Path) -> CurrentRelease | SqlWarehouseRelease:
    """Read exactly the active release and both foundation Snapshot pointers."""
    try:
        release_root = current_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BusinessDataMCPError("CURRENT_RELEASE_UNAVAILABLE", "The current data release is unavailable.") from exc
    if not release_root.is_dir() or release_root.parent.name != "releases" or not RELEASE_ID.fullmatch(release_root.name):
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.")

    try:
        sql_release = resolve_sql_release(release_root)
    except QueryError as exc:
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.") from exc
    if sql_release is not None:
        return sql_release

    prepared = _read_json(release_root / "prepared.json", "CURRENT_RELEASE_INVALID")
    library = _read_json(release_root / "library" / "library_manifest.json", "CURRENT_RELEASE_INVALID")
    release = release_root.name
    batch_id = prepared.get("batch_id")
    if (
        prepared.get("status") != "prepared"
        or prepared.get("published") is not False
        or prepared.get("release") != release
        or not isinstance(batch_id, str)
        or not batch_id
        or library.get("schema_version") != "business_query_library.v1"
        or library.get("batch_id") != batch_id
        or prepared.get("library") != str((release_root / "library").resolve())
        or library.get("snapshots") != prepared.get("snapshots")
    ):
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.")

    coverage = library.get("coverage")
    data_through = coverage.get("data_through") if isinstance(coverage, dict) else None
    prepared_coverage = prepared.get("coverage")
    if not isinstance(data_through, str) or not isinstance(prepared_coverage, dict) or prepared_coverage.get("data_through") != data_through:
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.")
    try:
        date.fromisoformat(data_through)
    except ValueError as exc:
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.") from exc

    foundation = release_root / "foundation"
    try:
        resolved_foundation = foundation.resolve(strict=True)
        if not resolved_foundation.is_relative_to(release_root) or not resolved_foundation.is_dir():
            raise ValueError()
    except (OSError, RuntimeError, ValueError) as exc:
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.") from exc
    if prepared.get("foundation") != str(resolved_foundation):
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.")

    workspace = _read_json(resolved_foundation / "Work" / "workspace.json", "CURRENT_RELEASE_INVALID")
    abroad = _read_json(resolved_foundation / "Work" / "StudyAbroad" / "current.json", "CURRENT_RELEASE_INVALID")
    snapshots = library.get("snapshots")
    if not isinstance(snapshots, dict) or set(snapshots) != {"training", "abroad"}:
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.")
    if (
        workspace.get("current_snapshot_id") != snapshots["training"]
        or abroad.get("snapshot_id") != snapshots["abroad"]
    ):
        raise BusinessDataMCPError("CURRENT_RELEASE_INVALID", "The current data release is invalid.")

    warehouses = {
        "training": _safe_warehouse(resolved_foundation, workspace.get("current_warehouse_path"), snapshots["training"]),
        "study": _safe_warehouse(resolved_foundation, abroad.get("warehouse"), snapshots["abroad"]),
    }
    return CurrentRelease(release, batch_id, data_through, dict(snapshots), warehouses)


def _write_job_status(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def _execute_in_child(
    *,
    warehouse: str,
    snapshot_id: str,
    sql: str,
    parameters: Any,
    allowed_relations: list[str],
    output_dir: str,
    status_path: str,
    metadata: dict[str, Any],
    sql_release_root: str | None = None,
    expected_release: str | None = None,
    expected_batch_id: str | None = None,
    domain: str | None = None,
    dashboard_dataset: str | None = None,
) -> None:
    status_file = Path(status_path)
    try:
        if sql_release_root is None:
            result = execute_query_bundle(
                warehouse=Path(warehouse),
                snapshot_id=snapshot_id,
                sql=sql,
                parameters=parameters,
                output_dir=Path(output_dir),
                allowed_relations=set(allowed_relations),
                max_result_bytes=MAX_QUERY_OUTPUT_BYTES,
            )
        else:
            result = execute_sql_release_query_bundle(
                release_root=Path(sql_release_root),
                expected_release=expected_release or "",
                expected_batch_id=expected_batch_id or "",
                dashboard_dataset=dashboard_dataset,
                domain=domain or "",
                sql=sql,
                parameters=parameters,
                output_dir=Path(output_dir),
                allowed_relations=set(allowed_relations),
                max_result_bytes=MAX_QUERY_OUTPUT_BYTES,
            )
        saved = {
            "schema_version": "business_data_query_result.v1",
            **metadata,
            "columns": result["columns"],
            "row_count": result["row_count"],
            "referenced_relations": result["referenced_relations"],
            "referenced_source_ids": result["referenced_source_ids"],
            "row_bytes": result["result_bytes"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        Path(output_dir, "metadata.json").write_text(
            json.dumps(saved, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        _write_job_status(status_file, {"status": "passed"})
    except BaseException as exc:
        code = exc.code if isinstance(exc, QueryError) else "QUERY_FAILED"
        if code in {"WAREHOUSE_NOT_FOUND", "WAREHOUSE_INVALID", "SNAPSHOT_MISMATCH", "SNAPSHOT_MANIFEST_INVALID"} or code.startswith("SQL_RELEASE_"):
            code = "RELEASE_UNAVAILABLE"
        shutil.rmtree(output_dir, ignore_errors=True)
        try:
            _write_job_status(status_file, {"status": "failed", "code": code})
        except OSError:
            pass


class BusinessDataQuery:
    """Read the fixed current release and page results from one execution."""

    def __init__(
        self,
        current_path: Path,
        result_root: Path,
        capacity_root: Path | None = None,
        timeout_seconds: float = 60.0,
        result_ttl_seconds: int = 24 * 60 * 60,
    ) -> None:
        if timeout_seconds <= 0 or result_ttl_seconds <= 0:
            raise BusinessDataMCPError("CONFIG_INVALID", "Query timeout and result retention must be positive.")
        self.current_path = Path(current_path)
        self.result_root = Path(result_root)
        self.capacity_root = Path(capacity_root) if capacity_root is not None else self.result_root
        self.timeout_seconds = timeout_seconds
        self.result_ttl_seconds = result_ttl_seconds

    def _results_directory(self) -> Path:
        if self.result_root.is_symlink() or self.capacity_root.is_symlink():
            raise BusinessDataMCPError("RESULT_STORE_INVALID", "The result store is unavailable.")
        try:
            self.capacity_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            capacity = self.capacity_root.resolve(strict=True)
            self.result_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            root = self.result_root.resolve(strict=True)
            if not root.is_dir() or not root.is_relative_to(capacity):
                raise ValueError()
            return root
        except (OSError, RuntimeError, ValueError) as exc:
            raise BusinessDataMCPError("RESULT_STORE_INVALID", "The result store is unavailable.") from exc

    @contextmanager
    def _capacity_lock(self, capacity: Path):
        with (capacity / ".capacity.lock").open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _result_directories(self, capacity: Path):
        for path in capacity.rglob("result_*"):
            if not path.is_symlink() and path.is_dir() and RESULT_ID.fullmatch(path.name):
                yield path

    def _expire_results_locked(self, capacity: Path) -> None:
        cutoff = time.time() - self.result_ttl_seconds
        for path in list(self._result_directories(capacity)):
            try:
                if path.stat().st_mtime < cutoff:
                    shutil.rmtree(path)
            except FileNotFoundError:
                continue

    def _used_result_bytes(self, capacity: Path) -> int:
        total = 0
        for directory in self._result_directories(capacity):
            for path in directory.rglob("*"):
                if path.is_symlink() or not path.is_file():
                    continue
                total += path.stat().st_size
        return total

    def _reservation_dir(self, capacity: Path) -> Path:
        path = capacity / ".reservations"
        path.mkdir(mode=0o700, exist_ok=True)
        return path

    def _reserved_result_bytes_locked(self, capacity: Path) -> int:
        total = 0
        stale_before = time.time() - RESERVATION_STALE_SECONDS
        active_ids: set[str] = set()
        for path in self._reservation_dir(capacity).glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if type(record.get("bytes")) is not int or record["bytes"] < 0:
                    path.unlink(missing_ok=True)
                    continue
                created_at = record.get("created_at")
                result_id = record.get("result_id")
                if type(created_at) is not int or created_at < stale_before or not isinstance(result_id, str) or not RESULT_ID.fullmatch(result_id):
                    path.unlink(missing_ok=True)
                    if isinstance(result_id, str) and RESULT_ID.fullmatch(result_id):
                        self._remove_staging_locked(capacity, result_id)
                    continue
                active_ids.add(result_id)
                total += record["bytes"]
            except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
                path.unlink(missing_ok=True)
        stale_before = time.time() - RESERVATION_STALE_SECONDS
        for path in capacity.rglob(".staging-result_*"):
            if path.is_symlink() or not path.is_dir():
                continue
            result_id = path.name.removeprefix(".staging-")
            if result_id not in active_ids and path.stat().st_mtime < stale_before:
                shutil.rmtree(path)
        return total

    def _remove_staging_locked(self, capacity: Path, result_id: str) -> None:
        for path in capacity.rglob(f".staging-{result_id}"):
            if not path.is_symlink() and path.is_dir():
                shutil.rmtree(path)
        for path in capacity.rglob(f".job-{result_id}.json"):
            if not path.is_symlink() and path.is_file():
                path.unlink(missing_ok=True)

    def _reserve_result(self, capacity: Path, result_id: str) -> Path:
        capacity.mkdir(parents=True, exist_ok=True, mode=0o700)
        capacity = capacity.resolve(strict=True)
        reservation_dir = self._reservation_dir(capacity)
        reservation = reservation_dir / f"{result_id}.json"
        with self._capacity_lock(capacity):
            self._expire_results_locked(capacity)
            used = self._used_result_bytes(capacity)
            reserved = self._reserved_result_bytes_locked(capacity)
            if used + reserved + MAX_RESERVATION_BYTES > MAX_TOTAL_RESULT_BYTES:
                raise BusinessDataMCPError("RESULT_CAPACITY_EXCEEDED", "The result store has no capacity for this query.")
            temporary = reservation.with_name(reservation.name + ".tmp")
            temporary.write_text(json.dumps({
                "bytes": MAX_RESERVATION_BYTES,
                "created_at": int(time.time()),
                "result_id": result_id,
            }), encoding="utf-8")
            os.replace(temporary, reservation)
        return reservation

    def _release_reservation(self, capacity: Path, reservation: Path) -> None:
        try:
            with self._capacity_lock(capacity):
                reservation.unlink(missing_ok=True)
                reservation.with_name(reservation.name + ".tmp").unlink(missing_ok=True)
        except OSError:
            reservation.unlink(missing_ok=True)

    def _commit_result(self, capacity: Path, reservation: Path, staging: Path, final_path: Path) -> None:
        with self._capacity_lock(capacity):
            self._expire_results_locked(capacity)
            if staging.is_symlink() or not staging.is_dir():
                raise BusinessDataMCPError("QUERY_FAILED", "The query result could not be saved.")
            size = sum(path.stat().st_size for path in staging.rglob("*") if path.is_file() and not path.is_symlink())
            if size > MAX_RESULT_BYTES:
                raise BusinessDataMCPError("QUERY_RESULT_TOO_LARGE", "query result exceeds the configured byte limit")
            os.replace(staging, final_path)
            reservation.unlink(missing_ok=True)

    def _check_expected_release(self, expected_release: str | None) -> CurrentRelease | SqlWarehouseRelease:
        current = resolve_current(self.current_path)
        if expected_release is not None and expected_release != current.release:
            raise BusinessDataMCPError(
                "RELEASE_UNAVAILABLE",
                "The requested data version is unavailable. Refresh the available version before querying again.",
            )
        return current

    def describe(
        self,
        domain: Domain | None = None,
        table: str | None = None,
        expected_release: str | None = None,
    ) -> dict[str, Any]:
        current = self._check_expected_release(expected_release)
        common: dict[str, Any] = {
            "schema_version": "business_data_description.v1",
            "status": "passed",
            "release": current.release,
            "data_through": current.data_through,
        }
        if domain is None:
            if table is not None:
                raise BusinessDataMCPError("TABLE_NOT_FOUND", "A domain is required to describe a table.")
            snapshots = (
                {"training": current.snapshots["training"], "study": current.snapshots["abroad"]}
                if isinstance(current, SqlWarehouseRelease)
                else {key: value.snapshot_id for key, value in current.warehouses.items()}
            )
            return {
                **common,
                "snapshots": snapshots,
                "dashboard_datasets": dataset_catalog(current.candidate.get("query_relations", [])) if isinstance(current, SqlWarehouseRelease) else {},
                "domains": {
                    key: [{"id": item["id"], "name": item["name"], "description": item["description"]}
                          for item in items]
                    for key, items in TABLES.items()
                },
            }
        if domain not in TABLES:
            raise BusinessDataMCPError("DOMAIN_NOT_FOUND", "Unknown data domain.")
        snapshot_id = current.snapshot_for(domain) if isinstance(current, SqlWarehouseRelease) else current.warehouses[domain].snapshot_id
        tables = TABLES[domain]
        if table is None:
            return {
                **common,
                "domain": domain,
                "snapshot_id": snapshot_id,
                "tables": [dict(item) for item in tables],
            }
        selected = next((item for item in tables if item["id"] == table), None)
        if selected is None:
            raise BusinessDataMCPError("TABLE_NOT_FOUND", "Unknown table in the selected domain.")
        if isinstance(current, SqlWarehouseRelease):
            relation = describe_sql_release_table(current, domain, selected["relation"])
        else:
            try:
                description = describe_warehouse(warehouse=current.warehouses[domain].path, snapshot_id=snapshot_id)
            except QueryError as exc:
                raise BusinessDataMCPError("RELEASE_UNAVAILABLE", "The requested data version is unavailable.") from exc
            schema, relation_name = selected["relation"].split(".", 1)
            relation = next((item for item in description["relations"]
                             if item["schema"] == schema and item["name"] == relation_name), None)
        if relation is None:
            raise BusinessDataMCPError("SCHEMA_UNAVAILABLE", "The selected table is not present in this data version.")
        return {
            **common,
            "domain": domain,
            "snapshot_id": snapshot_id,
            "table": {**selected, "columns": [
                {"name": column["name"], "type": column["type"],
                 **({"label": column["header_label"]} if column.get("header_label") else {})}
                for column in relation["columns"]
            ]},
        }

    def query(
        self,
        domain: Domain,
        sql: str,
        expected_release: str,
        parameters: Any = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        if domain not in TABLES:
            raise BusinessDataMCPError("DOMAIN_NOT_FOUND", "Unknown data domain.")
        return self._query(domain, sql, expected_release, parameters, page_size)

    def read_dashboard_data(self, dataset, expected_release, filters=None, page_size=100):
        sql, parameters = result_query(dataset, filters or {})
        return self._query("dashboard", sql, expected_release, parameters, page_size, dataset)

    def _query(self, domain, sql, expected_release, parameters, page_size, dashboard_dataset=None):
        if not isinstance(sql, str) or not sql.strip():
            raise BusinessDataMCPError("QUERY_INVALID", "SQL is required.")
        try:
            input_size = len(sql.encode("utf-8")) + len(json.dumps(
                parameters, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8"))
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise BusinessDataMCPError("QUERY_PARAMETERS_INVALID", "Query parameters must be JSON values.") from exc
        if input_size > MAX_QUERY_INPUT_BYTES:
            raise BusinessDataMCPError("QUERY_INPUT_TOO_LARGE", "SQL and parameters exceed the configured input limit.")
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise BusinessDataMCPError("PAGE_SIZE_INVALID", f"page_size must be between 1 and {MAX_PAGE_SIZE}.")
        current = self._check_expected_release(expected_release)
        if dashboard_dataset and not isinstance(current, SqlWarehouseRelease):
            raise BusinessDataMCPError("TABLE_NOT_FOUND", "Dashboard results require a SQL release.")
        if isinstance(current, SqlWarehouseRelease):
            warehouse = current.warehouse
            snapshot_id = None if dashboard_dataset else current.snapshot_for(domain)
            sql_release_root = str(current.root)
            expected_batch_id = current.batch_id
        else:
            reference = current.warehouses[domain]
            warehouse = reference.path
            snapshot_id = reference.snapshot_id
            sql_release_root = None
            expected_batch_id = None
        allowed_relations = ([dashboard_dataset] if dashboard_dataset else
                             [item["relation"].split(".", 1)[1] for item in TABLES[domain]])
        result_id = "result_" + uuid.uuid4().hex
        root = self._results_directory()
        capacity = self.capacity_root.resolve(strict=True)
        reservation = self._reserve_result(capacity, result_id)
        staging = root / f".staging-{result_id}"
        status_path = root / f".job-{result_id}.json"
        metadata = {
            "result_id": result_id,
            "domain": domain,
            "release": current.release,
            "batch_id": current.batch_id,
            "data_through": current.data_through,
            "snapshot_id": snapshot_id,
            "sql": sql,
            "parameters": parameters,
            **({"snapshots": current.snapshots} if dashboard_dataset else {}),
            **({"column_descriptions": {"prior": TEAM_METRICS_PRIOR}} if dashboard_dataset == "team_metrics" else {}),
        }
        context = multiprocessing.get_context("spawn")
        process = context.Process(target=_execute_in_child, kwargs={
            "dashboard_dataset": dashboard_dataset,
            "warehouse": str(warehouse),
            "snapshot_id": snapshot_id,
            "sql": sql,
            "parameters": parameters,
            "allowed_relations": allowed_relations,
            "output_dir": str(staging),
            "status_path": str(status_path),
            "metadata": metadata,
            "sql_release_root": sql_release_root,
            "expected_release": current.release if sql_release_root is not None else None,
            "expected_batch_id": expected_batch_id,
            "domain": domain if sql_release_root is not None else None,
        })
        started = False
        try:
            process.start()
            started = True
            process.join(self.timeout_seconds)
            if process.is_alive():
                process.terminate()
                process.join(1.0)
                if process.is_alive():
                    process.kill()
                    process.join()
                raise BusinessDataMCPError("QUERY_TIMEOUT", "Query exceeded the configured time limit and was terminated.")
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise BusinessDataMCPError("QUERY_FAILED", "The query worker did not return a result.")
            if status.get("status") != "passed":
                raise BusinessDataMCPError(status.get("code", "QUERY_FAILED"), "The query could not be completed.")
            final_path = root / result_id
            self._commit_result(capacity, reservation, staging, final_path)
            reservation = None
        except BusinessDataMCPError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        except (OSError, RuntimeError) as exc:
            if started and process.is_alive():
                process.terminate()
                process.join(1.0)
                if process.is_alive():
                    process.kill()
                    process.join()
            shutil.rmtree(staging, ignore_errors=True)
            raise BusinessDataMCPError("QUERY_FAILED", "The query could not be completed.") from exc
        finally:
            if started and process.exitcode is not None:
                process.close()
            status_path.unlink(missing_ok=True)
            if reservation is not None:
                self._release_reservation(capacity, reservation)
        try:
            return self.read_page(result_id, offset=0, limit=page_size)
        except BusinessDataMCPError as exc:
            if exc.code == "PAGE_ROW_TOO_LARGE":
                with self._capacity_lock(capacity):
                    shutil.rmtree(root / result_id, ignore_errors=True)
            raise

    def _load_result(self, result_id: str) -> tuple[Path, dict[str, Any]]:
        if not isinstance(result_id, str) or not RESULT_ID.fullmatch(result_id):
            raise BusinessDataMCPError("RESULT_NOT_FOUND", "Query result is unavailable.")
        root = self._results_directory()
        path = root / result_id
        try:
            resolved = path.resolve(strict=True)
            if path.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_dir():
                raise ValueError()
            metadata = _read_json(resolved / "metadata.json", "RESULT_NOT_FOUND")
            if metadata.get("schema_version") != "business_data_query_result.v1" or metadata.get("result_id") != result_id:
                raise ValueError()
            if (type(metadata.get("row_count")) is not int or metadata["row_count"] < 0
                    or not isinstance(metadata.get("columns"), list)
                    or not all(isinstance(column, str) for column in metadata["columns"])):
                raise ValueError()
            rows_path = resolved / "rows.jsonl"
            if (rows_path.is_symlink() or not rows_path.is_file()
                    or type(metadata.get("row_bytes")) is not int
                    or rows_path.stat().st_size != metadata["row_bytes"]):
                raise ValueError()
            if resolved.stat().st_mtime < time.time() - self.result_ttl_seconds:
                capacity = self.capacity_root.resolve(strict=True)
                with self._capacity_lock(capacity):
                    if resolved.exists() and resolved.stat().st_mtime < time.time() - self.result_ttl_seconds:
                        shutil.rmtree(resolved)
                raise BusinessDataMCPError("RESULT_NOT_FOUND", "Query result has expired.")
        except BusinessDataMCPError:
            raise
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            raise BusinessDataMCPError("RESULT_NOT_FOUND", "Query result is unavailable.") from exc
        return resolved, metadata

    @staticmethod
    def _page_bounds(offset: int, limit: int, row_count: int) -> None:
        if type(offset) is not int or offset < 0 or offset > row_count:
            raise BusinessDataMCPError("PAGE_OFFSET_INVALID", "offset is outside the saved query result.")
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise BusinessDataMCPError("PAGE_SIZE_INVALID", f"limit must be between 1 and {MAX_PAGE_SIZE}.")

    @staticmethod
    def _mcp_safe_value(value: Any) -> Any:
        if type(value) is int and abs(value) > (2**53 - 1):
            return str(value)
        if isinstance(value, list):
            return [BusinessDataQuery._mcp_safe_value(item) for item in value]
        if isinstance(value, dict):
            return {key: BusinessDataQuery._mcp_safe_value(item) for key, item in value.items()}
        return value

    def _read_rows(
        self,
        rows_path: Path,
        offset: int,
        limit: int,
        row_count: int,
        column_count: int,
        encode_row: Any,
        initial_bytes: int = 0,
    ) -> list[list[Any]]:
        rows = []
        response_bytes = initial_bytes
        byte_limited = False
        try:
            with rows_path.open("r", encoding="utf-8") as stream:
                for index, line in enumerate(stream):
                    if index < offset:
                        continue
                    if len(rows) >= limit:
                        break
                    row = json.loads(line)
                    if not isinstance(row, list) or len(row) != column_count:
                        raise ValueError()
                    row = [self._mcp_safe_value(value) for value in row]
                    row_bytes = len(encode_row(row))
                    if response_bytes + row_bytes > MAX_PAGE_RESPONSE_BYTES:
                        if not rows:
                            raise BusinessDataMCPError("PAGE_ROW_TOO_LARGE", "A result row exceeds the page size limit. Select fewer columns or shorten long text fields.")
                        byte_limited = True
                        break
                    response_bytes += row_bytes
                    rows.append(row)
                expected = min(limit, row_count - offset)
                if len(rows) < expected and not byte_limited:
                    raise BusinessDataMCPError("RESULT_CORRUPT", "Saved query result is incomplete.")
        except BusinessDataMCPError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise BusinessDataMCPError("RESULT_CORRUPT", "Saved query result is unavailable.") from exc
        return rows

    def read_page(self, result_id: str, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        path, metadata = self._load_result(result_id)
        self._page_bounds(offset, limit, metadata["row_count"])
        rows = self._read_rows(
            path / "rows.jsonl", offset, limit, metadata["row_count"], len(metadata["columns"]),
            lambda row: json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        )
        next_offset = offset + len(rows)
        if next_offset >= metadata["row_count"]:
            next_offset = None
        return {
            "schema_version": "business_data_page.v1",
            "status": "passed",
            **{key: metadata[key] for key in ("result_id", "domain", "release", "snapshot_id", "data_through")},
            "columns": metadata["columns"],
            **({"snapshots": metadata["snapshots"]} if "snapshots" in metadata else {}),
            **({"column_descriptions": metadata["column_descriptions"]} if "column_descriptions" in metadata else {}),
            "sql": metadata["sql"],
            "parameters": metadata["parameters"],
            "source_tables": metadata["referenced_relations"],
            "row_count": metadata["row_count"],
            "offset": offset,
            "rows": rows,
            "next_offset": next_offset,
        }

    def export_csv(self, result_id: str, offset: int = 0, limit: int = MAX_PAGE_SIZE) -> dict[str, Any]:
        path, metadata = self._load_result(result_id)
        self._page_bounds(offset, limit, metadata["row_count"])
        from data_platform.query.service import _business_csv_row

        header = _business_csv_row(metadata["columns"]) if offset == 0 else ""
        rows = self._read_rows(
            path / "rows.jsonl", offset, limit, metadata["row_count"], len(metadata["columns"]),
            lambda row: _business_csv_row(row).encode("utf-8"),
            initial_bytes=len(header.encode("utf-8")),
        )
        chunks = []
        if offset == 0:
            chunks.append(header)
        chunks.extend(_business_csv_row(row) for row in rows)
        next_offset = offset + len(rows)
        if next_offset >= metadata["row_count"]:
            next_offset = None
        return {
            "schema_version": "business_data_csv_chunk.v1",
            "status": "passed",
            **{key: metadata[key] for key in ("result_id", "domain", "release", "snapshot_id", "data_through")},
            **({"snapshots": metadata["snapshots"]} if "snapshots" in metadata else {}),
            **({"column_descriptions": metadata["column_descriptions"]} if "column_descriptions" in metadata else {}),
            "sql": metadata["sql"],
            "parameters": metadata["parameters"],
            "source_tables": metadata["referenced_relations"],
            "filename": f"business-data-{result_id}.csv",
            "offset": offset,
            "next_offset": next_offset,
            "complete": next_offset is None,
            "row_count": metadata["row_count"],
            "csv_text": "".join(chunks),
        }
