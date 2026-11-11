from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
import shutil
import time

import duckdb
import pytest

from business_data_mcp.query import (
    MAX_RESULT_BYTES,
    MAX_RESERVATION_BYTES,
    MAX_TOTAL_RESULT_BYTES,
    BusinessDataMCPError,
    BusinessDataQuery,
    TABLES,
)
from data_platform.query.service import QueryError, execute_query_bundle
from tests.evidence_helpers import manifest


TRAINING_SNAPSHOT = "snapshot_training_test"
STUDY_SNAPSHOT = "snapshot_study_test"
RELEASE = "daily-20261104_foundation2"
NEXT_RELEASE = "daily-20261105_test_next"


def _create_warehouse(path: Path, snapshot_id: str, tables: dict[str, tuple[str, list[tuple]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as connection:
        for schema in ("ingest", "landing", "quality", "queries"):
            connection.execute(f"CREATE SCHEMA {schema}")
        connection.execute("CREATE TABLE ingest.sources(source_id VARCHAR, snapshot_id VARCHAR)")
        connection.execute("CREATE TABLE ingest.sheets(source_id VARCHAR, target_table VARCHAR, header_columns JSON)")
        relation_sources = {name: f"source_{index}" for index, name in enumerate(tables, 1)}
        for name, (definition, rows) in tables.items():
            source_id = relation_sources[name]
            connection.execute("INSERT INTO ingest.sources VALUES (?, ?)", [source_id, snapshot_id])
            connection.execute("INSERT INTO ingest.sheets VALUES (?, ?, '[]')", [source_id, name])
            connection.execute(f'CREATE TABLE landing."{name}" ({definition})')
            if rows:
                placeholders = ",".join(["?"] * len(rows[0]))
                connection.executemany(f'INSERT INTO landing."{name}" VALUES ({placeholders})', rows)
    manifest(path, snapshot_id)


def _release(root: Path, *, row_count: int = 2) -> Path:
    release_root = root / "releases" / RELEASE
    foundation = release_root / "foundation"
    training_path = foundation / "Work/Runs/training/data/snapshots/training/warehouse.duckdb"
    study_path = foundation / "Work/StudyAbroad/Runs/study/data/snapshots/study/warehouse.duckdb"
    order_rows = [("0000000000000000000001", None, 1)]
    order_rows.extend((f"000000000000000000{index:04d}", "", index + 1) for index in range(2, row_count + 1))
    _create_warehouse(training_path, TRAINING_SNAPSHOT, {
        "br_work_orders__sheet_1f0596db9f25": (
            '"ID" VARCHAR, "备注" VARCHAR, source_row_number BIGINT', order_rows,
        ),
        "br_cash__sheet_39b8dee2e4b3": (
            '"工单ID" VARCHAR, "现金收入" DECIMAL(18,2)',
            [("0000000000000000000001", "123.45")],
        ),
    })
    _create_warehouse(study_path, STUDY_SNAPSHOT, {
        "study_abroad_market__resources": (
            "resource_id VARCHAR, record_key VARCHAR", [("001", "r1")],
        ),
        "study_abroad_market__contracts": (
            "contract_id VARCHAR, amount DECIMAL(18,2)", [("0002", "456.78")],
        ),
        "study_abroad_market__languages": (
            "record_key VARCHAR, amount DECIMAL(18,2)", [("r1", "12.34")],
        ),
    })
    (foundation / "Work").mkdir(parents=True, exist_ok=True)
    (foundation / "Work/workspace.json").write_text(json.dumps({
        "current_warehouse_path": training_path.relative_to(foundation).as_posix(),
        "current_snapshot_id": TRAINING_SNAPSHOT,
    }), encoding="utf-8")
    (foundation / "Work/StudyAbroad/current.json").parent.mkdir(parents=True, exist_ok=True)
    (foundation / "Work/StudyAbroad/current.json").write_text(json.dumps({
        "warehouse": study_path.relative_to(foundation).as_posix(),
        "snapshot_id": STUDY_SNAPSHOT,
    }), encoding="utf-8")
    (release_root / "library").mkdir(parents=True, exist_ok=True)
    library_manifest = {
        "schema_version": "business_query_library.v1",
        "batch_id": "run_shadow_daily_20261104_test",
        "snapshots": {"training": TRAINING_SNAPSHOT, "abroad": STUDY_SNAPSHOT},
        "coverage": {"data_through": "2026-11-03"},
    }
    (release_root / "library/library_manifest.json").write_text(json.dumps(library_manifest), encoding="utf-8")
    prepared = {
        "status": "prepared",
        "published": False,
        "release": RELEASE,
        "batch_id": library_manifest["batch_id"],
        "snapshots": library_manifest["snapshots"],
        "coverage": library_manifest["coverage"],
        "foundation": str(foundation),
        "library": str(release_root / "library"),
    }
    (release_root / "prepared.json").write_text(json.dumps(prepared), encoding="utf-8")
    current = root / "current"
    current.symlink_to(release_root, target_is_directory=True)
    return current


def _atomically_switch_current(current: Path, next_release: str) -> Path:
    previous_root = current.resolve(strict=True)
    next_root = previous_root.parent / next_release
    shutil.copytree(previous_root, next_root)

    prepared_path = next_root / "prepared.json"
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    library_path = next_root / "library/library_manifest.json"
    library = json.loads(library_path.read_text(encoding="utf-8"))
    batch_id = f"run_shadow_daily_{next_release}"
    prepared.update({
        "release": next_release,
        "batch_id": batch_id,
        "foundation": str((next_root / "foundation").resolve()),
        "library": str((next_root / "library").resolve()),
    })
    library["batch_id"] = batch_id
    prepared_path.write_text(json.dumps(prepared), encoding="utf-8")
    library_path.write_text(json.dumps(library), encoding="utf-8")

    next_link = current.with_name(current.name + ".next")
    next_link.symlink_to(next_root, target_is_directory=True)
    os.replace(next_link, current)
    return previous_root


@pytest.fixture
def worker(tmp_path: Path) -> tuple[BusinessDataQuery, Path, Path]:
    current = _release(tmp_path)
    results = tmp_path / "results"
    capacity = results
    return BusinessDataQuery(current, results / "key_a", capacity_root=capacity), current, results


def test_describe_selects_one_domain_or_one_table(worker) -> None:
    query, _, _ = worker
    overview = query.describe()
    assert overview["release"] == RELEASE
    assert overview["data_through"] == "2026-11-03"
    assert overview["snapshots"] == {"training": TRAINING_SNAPSHOT, "study": STUDY_SNAPSHOT}
    assert len(overview["domains"]["training"]) == 2

    domain = query.describe(domain="study")
    assert domain["snapshot_id"] == STUDY_SNAPSHOT
    assert [table["id"] for table in domain["tables"]] == ["resources", "contracts", "language_payments"]
    table = query.describe(domain="study", table="contracts")
    assert table["snapshot_id"] == STUDY_SNAPSHOT
    assert {column["name"] for column in table["table"]["columns"]} == {"contract_id", "amount"}


def test_current_pair_and_same_execution_page_csv_preserve_values(worker) -> None:
    query, _, _ = worker
    sql = """
    WITH selected AS (
      SELECT ID, 备注, row_number() OVER (ORDER BY source_row_number) AS rn
      FROM landing.br_work_orders__sheet_1f0596db9f25
    )
    SELECT s.ID, c.现金收入, s.备注
    FROM selected s JOIN landing.br_cash__sheet_39b8dee2e4b3 c ON c.工单ID=s.ID
    WHERE s.rn = 1 AND c.工单ID = $order_id
    """
    result = query.query(
        domain="training", sql=sql, parameters={"order_id": "0000000000000000000001"},
        expected_release=RELEASE, page_size=1,
    )
    assert result["snapshot_id"] == TRAINING_SNAPSHOT
    assert result["data_through"] == "2026-11-03"
    assert result["row_count"] == 1
    assert result["rows"] == [["0000000000000000000001", "123.45", None]]
    assert result["sql"].strip() == sql.strip()
    assert result["parameters"] == {"order_id": "0000000000000000000001"}
    assert set(result["source_tables"]) == {
        "landing.br_work_orders__sheet_1f0596db9f25",
        "landing.br_cash__sheet_39b8dee2e4b3",
    }

    csv_page = query.export_csv(result["result_id"], offset=0, limit=1)
    assert csv_page["complete"] is True
    assert csv_page["csv_text"].splitlines() == [
        '"ID","现金收入","备注"',
        '"0000000000000000000001","123.45",',
    ]


def test_full_result_pages_and_csv_chunks_have_no_preview_truncation(tmp_path: Path) -> None:
    current = _release(tmp_path, row_count=1205)
    results = tmp_path / "results"
    query = BusinessDataQuery(current, results / "key_a", capacity_root=results)
    result = query.query(
        domain="training",
        sql="SELECT ID FROM landing.br_work_orders__sheet_1f0596db9f25 ORDER BY source_row_number",
        expected_release=RELEASE,
        page_size=3,
    )
    assert result["row_count"] == 1205
    assert len(result["rows"]) == 3

    rows = result["rows"]
    offset = result["next_offset"]
    while offset is not None:
        page = query.read_page(result["result_id"], offset=offset, limit=137)
        rows.extend(page["rows"])
        offset = page["next_offset"]
    assert len(rows) == 1205
    assert rows[0] == ["0000000000000000000001"]
    assert rows[-1] == ["0000000000000000001205"]

    csv_chunks = []
    offset = 0
    while True:
        chunk = query.export_csv(result["result_id"], offset=offset, limit=500)
        csv_chunks.append(chunk["csv_text"])
        if chunk["next_offset"] is None:
            assert chunk["complete"] is True
            break
        assert chunk["complete"] is False
        offset = chunk["next_offset"]
    csv_text = "".join(csv_chunks)
    assert csv_text.count("\r\n") == 1206
    assert csv_text.startswith('"ID"\r\n"0000000000000000000001"\r\n')
    assert csv_text.endswith('"0000000000000000001205"\r\n')


@pytest.mark.parametrize("sql", [
    "SELECT * FROM ingest.sources",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM br_work_orders__sheet_1f0596db9f25",
    "SELECT getenv('HOME')",
    "SELECT current_setting('threads')",
    "SELECT * FROM query('SELECT 1')",
    "SELECT * FROM query_table('landing.br_work_orders__sheet_1f0596db9f25')",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM duckdb_settings()",
    "SELECT * FROM landing.not_registered",
])
def test_ast_guard_rejects_metadata_external_and_dynamic_sources(worker, tmp_path: Path, sql: str) -> None:
    query, current, _ = worker
    source = next(item["relation"].split(".", 1)[1] for item in TABLES["training"] if item["id"] == "work_orders")
    warehouse_path = (current.resolve() / "foundation/Work/Runs/training/data/snapshots/training/warehouse.duckdb")
    result_path = tmp_path / f"bundle-{abs(hash(sql))}"
    with pytest.raises(QueryError) as error:
        execute_query_bundle(
            warehouse=warehouse_path,
            snapshot_id=TRAINING_SNAPSHOT,
            sql=sql,
            output_dir=result_path,
            allowed_relations={source, "br_cash__sheet_39b8dee2e4b3"},
        )
    assert error.value.code == "QUERY_REJECTED"
    assert not result_path.exists()


def test_full_result_byte_limit_fails_clearly_without_a_partial_result(worker, tmp_path: Path) -> None:
    _, current, _ = worker
    warehouse_path = (current.resolve() / "foundation/Work/Runs/training/data/snapshots/training/warehouse.duckdb")
    output_dir = tmp_path / "oversize-result"
    with pytest.raises(QueryError) as error:
        execute_query_bundle(
            warehouse=warehouse_path,
            snapshot_id=TRAINING_SNAPSHOT,
            sql="SELECT repeat('x', 50) AS long_value FROM landing.br_work_orders__sheet_1f0596db9f25",
            output_dir=output_dir,
            allowed_relations={"br_work_orders__sheet_1f0596db9f25"},
            max_result_bytes=10,
        )
    assert error.value.code == "QUERY_RESULT_TOO_LARGE"
    assert not output_dir.exists()


def test_plain_cte_join_and_window_are_available(worker) -> None:
    query, _, _ = worker
    result = query.query(
        domain="training",
        expected_release=RELEASE,
        sql="WITH orders AS (SELECT ID, row_number() OVER (ORDER BY ID) AS rn FROM landing.br_work_orders__sheet_1f0596db9f25) SELECT ID FROM orders WHERE rn=1",
    )
    assert result["rows"] == [["0000000000000000000001"]]


def test_expected_release_does_not_silently_switch(worker) -> None:
    query, _, _ = worker
    with pytest.raises(BusinessDataMCPError) as error:
        query.query(domain="training", sql="SELECT 1", expected_release="daily-old")
    assert error.value.code == "RELEASE_UNAVAILABLE"


def test_saved_result_survives_atomic_current_switch_and_old_release_cleanup(worker) -> None:
    query, current, _ = worker
    result = query.query(
        domain="training",
        expected_release=RELEASE,
        page_size=1,
        sql="SELECT ID FROM landing.br_work_orders__sheet_1f0596db9f25 ORDER BY source_row_number",
    )
    page_before = query.read_page(result["result_id"], offset=0, limit=1)
    csv_before = query.export_csv(result["result_id"], offset=0, limit=500)
    assert page_before["release"] == RELEASE
    assert csv_before["complete"] is True

    old_release_root = _atomically_switch_current(current, NEXT_RELEASE)
    assert current.resolve(strict=True).name == NEXT_RELEASE
    shutil.rmtree(old_release_root)
    assert not old_release_root.exists()

    assert query.read_page(result["result_id"], offset=0, limit=1) == page_before
    assert query.export_csv(result["result_id"], offset=0, limit=500) == csv_before

    with pytest.raises(BusinessDataMCPError) as error:
        query.query(
            domain="training",
            sql="SELECT 1 AS value",
            expected_release=RELEASE,
        )
    assert error.value.code == "RELEASE_UNAVAILABLE"


def test_bigint_and_hugeint_are_text_in_mcp_payload_without_precision_loss(worker) -> None:
    query, _, _ = worker
    result = query.query(
        domain="training",
        expected_release=RELEASE,
        sql=("SELECT CAST('9007199254740993' AS BIGINT) AS big, "
             "CAST('170141183460469231731687303715884105727' AS HUGEINT) AS huge"),
    )
    assert result["rows"] == [["9007199254740993", "170141183460469231731687303715884105727"]]
    chunk = query.export_csv(result["result_id"])
    assert '"9007199254740993","170141183460469231731687303715884105727"' in chunk["csv_text"]


def test_page_and_csv_chunks_stop_at_response_budget_and_advance(tmp_path: Path) -> None:
    current = _release(tmp_path, row_count=1205)
    results = tmp_path / "results"
    query = BusinessDataQuery(current, results / "key_a", capacity_root=results)
    result = query.query(
        domain="training",
        expected_release=RELEASE,
        page_size=100,
        sql=("SELECT ID, repeat('x', 5000) AS note "
             "FROM landing.br_work_orders__sheet_1f0596db9f25 ORDER BY source_row_number"),
    )
    assert 0 < len(result["rows"]) < 100
    assert result["next_offset"] == len(result["rows"])
    next_page = query.read_page(result["result_id"], offset=result["next_offset"], limit=500)
    assert 0 < len(next_page["rows"]) < 500
    assert next_page["offset"] == result["next_offset"]

    csv = query.export_csv(result["result_id"], offset=0, limit=500)
    assert csv["next_offset"] is not None
    assert 0 < csv["next_offset"] < 500


def test_single_row_over_page_budget_fails_instead_of_returning_empty_page(worker) -> None:
    query, _, results = worker
    with pytest.raises(BusinessDataMCPError) as error:
        query.query(
            domain="training",
            expected_release=RELEASE,
            sql=("SELECT repeat('x', 300000) AS note "
                 "FROM landing.br_work_orders__sheet_1f0596db9f25 LIMIT 1"),
        )
    assert error.value.code == "PAGE_ROW_TOO_LARGE"
    assert not list((results / "key_a").glob("result_*"))


def test_row_and_total_byte_limits_are_explicit_and_atomic(worker, monkeypatch) -> None:
    query, _, results = worker
    monkeypatch.setattr("business_data_mcp.query.MAX_TOTAL_RESULT_BYTES", MAX_RESERVATION_BYTES)
    capacity = results.resolve()
    first = query._reserve_result(capacity, "result_" + "1" * 32)
    try:
        with pytest.raises(BusinessDataMCPError) as error:
            query._reserve_result(capacity, "result_" + "2" * 32)
        assert error.value.code == "RESULT_CAPACITY_EXCEEDED"
    finally:
        query._release_reservation(capacity, first)

    result = query.query(domain="training", expected_release=RELEASE, sql="SELECT 1 AS value")
    result_dir = results / "key_a" / result["result_id"]
    metadata_path = result_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    rows_path = result_dir / "rows.jsonl"
    rows_path.write_text("", encoding="utf-8")
    metadata["row_bytes"] = 0
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(BusinessDataMCPError) as corrupt:
        query.read_page(result["result_id"], offset=0, limit=10)
    assert corrupt.value.code == "RESULT_CORRUPT"


def test_capacity_reservations_are_atomic_across_concurrent_callers(worker, monkeypatch) -> None:
    query, _, results = worker
    monkeypatch.setattr("business_data_mcp.query.MAX_TOTAL_RESULT_BYTES", MAX_RESERVATION_BYTES)
    barrier = Barrier(2)

    def reserve(result_id: str):
        barrier.wait()
        try:
            return query._reserve_result(results, result_id)
        except BusinessDataMCPError as exc:
            assert exc.code == "RESULT_CAPACITY_EXCEEDED"
            return None

    ids = ["result_" + "3" * 32, "result_" + "4" * 32]
    with ThreadPoolExecutor(max_workers=2) as pool:
        reservations = list(pool.map(reserve, ids))
    assert sum(item is not None for item in reservations) == 1
    for reservation in reservations:
        if reservation is not None:
            query._release_reservation(results.resolve(), reservation)


def test_result_expires_on_read(worker) -> None:
    query, _, results = worker
    result = query.query(domain="training", expected_release=RELEASE, sql="SELECT 1 AS value")
    result_dir = results / "key_a" / result["result_id"]
    old = time.time() - query.result_ttl_seconds - 2
    os.utime(result_dir, (old, old))
    with pytest.raises(BusinessDataMCPError) as error:
        query.export_csv(result["result_id"])
    assert error.value.code == "RESULT_NOT_FOUND"
    assert not result_dir.exists()


def test_timeout_terminates_the_query_worker(worker) -> None:
    _, current, results = worker
    query = BusinessDataQuery(current, results / "key_timeout", capacity_root=results, timeout_seconds=1.5)
    with pytest.raises(BusinessDataMCPError) as error:
        query.query(
            domain="training",
            expected_release=RELEASE,
            sql="WITH RECURSIVE loop(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM loop) SELECT sum(n) FROM loop",
        )
    assert error.value.code == "QUERY_TIMEOUT"
    assert not list((results / "key_timeout").glob(".staging-*"))
    assert not list((results / ".reservations").glob("*.json"))


def test_real_worker_runs_through_http_mcp_tools(tmp_path: Path) -> None:
    from starlette.testclient import TestClient

    from business_data_mcp.keys import issue_key
    from business_data_mcp.server import create_app

    current = _release(tmp_path)
    results_root = tmp_path / "results"
    keys_file = tmp_path / "keys.json"
    key = issue_key(keys_file, "synthetic integration")
    app = create_app(current, results_root, keys_file, allowed_hosts=["testserver"])

    def call(client, request_id: int, name: str, arguments: dict) -> dict:
        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer " + key["token"]},
            json={
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result.get("isError") is not True
        return result

    with TestClient(app) as client:
        described = call(client, 1, "describe_data", {})
        description = described.get("structuredContent") or json.loads(described["content"][0]["text"])
        assert description["release"] == RELEASE
        assert description["snapshots"]["training"] == TRAINING_SNAPSHOT

        queried = call(client, 2, "query_data", {
            "domain": "training",
            "expected_release": RELEASE,
            "sql": "SELECT ID FROM landing.br_work_orders__sheet_1f0596db9f25 WHERE ID = '0000000000000000000001'",
        })
        result = queried.get("structuredContent") or json.loads(queried["content"][0]["text"])
        assert result["rows"] == [["0000000000000000000001"]]
        assert result["source_tables"] == ["landing.br_work_orders__sheet_1f0596db9f25"]

        exported = call(client, 3, "export_query_csv", {"result_id": result["result_id"]})
        metadata = json.loads(exported["content"][0]["text"])
        assert metadata["complete"] is True
        assert exported["content"][1]["text"] == '"ID"\r\n"0000000000000000000001"\r\n'
