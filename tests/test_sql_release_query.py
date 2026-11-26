from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import duckdb
import pytest

from business_data_mcp.deploy import acl_sync
from business_data_mcp.query import BusinessDataQuery, TABLES
from data_platform.query.evidence import file_ref
from data_platform.query.service import QueryError
from data_platform.sql_release_query import (
    PUBLIC_RELATIONS,
    execute_query_bundle,
    resolve_sql_release,
)


BATCH = "run_sql_release_test"
RELEASE = "daily-sql-release-test"
SNAPSHOTS = {
    "training": "snapshot_training_sql_release_test",
    "abroad": "snapshot_abroad_sql_release_test",
}
TRAINING_WORK_ORDERS = "br_work_orders__sheet_1f0596db9f25"
TRAINING_CASH = "br_cash__sheet_39b8dee2e4b3"
STUDY_RESOURCES = "study_abroad_market__resources"
STUDY_CONTRACTS = "study_abroad_market__contracts"
STUDY_LANGUAGES = "study_abroad_market__languages"


def _build_release(
    root: Path,
    *,
    identity_batch: str = BATCH,
    bad_import_snapshot: bool = False,
    bad_provenance_domain: bool = False,
) -> tuple[Path, Path]:
    releases = root / "releases"
    release_root = releases / RELEASE
    library = release_root / "library"
    library.mkdir(parents=True)
    warehouse = library / "warehouse.duckdb"
    imports = [
        ("training", SNAPSHOTS["training"], TRAINING_WORK_ORDERS),
        ("training", SNAPSHOTS["training"], TRAINING_CASH),
        ("abroad", SNAPSHOTS["abroad"], STUDY_RESOURCES),
        ("abroad", SNAPSHOTS["abroad"], STUDY_CONTRACTS),
        ("abroad", SNAPSHOTS["abroad"], STUDY_LANGUAGES),
    ]
    if bad_import_snapshot:
        imports[0] = ("training", "snapshot_wrong", TRAINING_WORK_ORDERS)
    definitions = {
        TRAINING_WORK_ORDERS: ('"ID" VARCHAR, "source_row_number" BIGINT', [("001", 1), ("002", 2)]),
        TRAINING_CASH: ('"工单ID" VARCHAR, "现金收入" DECIMAL(18,2)', [("001", "10.50")]),
        STUDY_RESOURCES: ("resource_id VARCHAR, record_key VARCHAR", [("r1", "001")]),
        STUDY_CONTRACTS: ("contract_id VARCHAR, amount DECIMAL(18,2)", [("c1", "20.00")]),
        STUDY_LANGUAGES: ("record_key VARCHAR, amount DECIMAL(18,2)", [("l1", "5.00")]),
    }
    with duckdb.connect(str(warehouse)) as connection:
        connection.execute("CREATE SCHEMA landing; CREATE SCHEMA meta")
        connection.execute("CREATE SCHEMA business")
        connection.execute("CREATE TABLE business.team_metrics AS SELECT 'FY27' AS period_id, 'heads' AS metric, 2 AS actual, 'training' AS business_line, 'total' AS unit_id, '被动' AS acquisition_scope")
        connection.execute("INSERT INTO business.team_metrics VALUES ('FY27', 'heads', 3, 'training', 'total', '全部'), ('FY27', 'heads', 4, 'abroad', 'online', '被动')")
        connection.execute("CREATE TABLE meta.identity(batch_id VARCHAR)")
        connection.execute("INSERT INTO meta.identity VALUES (?)", [identity_batch])
        connection.execute("CREATE TABLE meta.imports(source VARCHAR, snapshot_id VARCHAR, relation VARCHAR, row_count BIGINT, seconds DOUBLE)")
        connection.execute("CREATE SCHEMA core; CREATE SCHEMA mart")
        connection.execute("CREATE VIEW core.training_orders_attributed AS SELECT 1 AS fixture_id")
        connection.execute("CREATE VIEW mart.team_metrics AS SELECT 1 AS fixture_id")
        for source, snapshot_id, relation in imports:
            definition, rows = definitions[relation]
            connection.execute(f'CREATE TABLE landing."{relation}" ({definition})')
            if rows:
                placeholders = ",".join("?" for _ in rows[0])
                connection.executemany(f'INSERT INTO landing."{relation}" VALUES ({placeholders})', rows)
            connection.execute("INSERT INTO meta.imports VALUES (?, ?, ?, ?, 0.01)", [source, snapshot_id, relation, len(rows)])

    database_ref = file_ref(warehouse, library, "application/vnd.duckdb")
    candidate = {
        "schema_version": "sql_warehouse_candidate.v1",
        "status": "built_unreconciled",
        "published": False,
        "company_id": "fixture-company",
        "batch_id": BATCH,
        "as_of_date": "2026-11-06",
        "through_date": "2026-11-05",
        "snapshots": SNAPSHOTS,
        "database": database_ref,
        "schemas": ["landing", "meta", "business", "core", "mart"],
        "semantic_relations": ["core.training_orders_attributed", "mart.team_metrics"],
        "query_relations": ["team_metrics"],
        "source_queries": [
            {
                "schema_version": "controlled_query_result.v2",
                "status": "passed",
                "snapshot_id": SNAPSHOTS["training"],
                "receipt": {
                    "path": "data/query_results/evidence_training/receipt.json",
                    "sha256": "a" * 64,
                    "size_bytes": 100,
                    "media_type": "application/json",
                },
                "errors": [],
            },
            {
                "schema_version": "controlled_query_result.v2",
                "status": "passed",
                "snapshot_id": SNAPSHOTS["abroad"],
                "receipt": {
                    "path": "data/query_results/evidence_abroad/receipt.json",
                    "sha256": "b" * 64,
                    "size_bytes": 100,
                    "media_type": "application/json",
                },
                "errors": [],
            },
        ],
    }
    candidate_path = library / "candidate.json"
    candidate_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
    candidate_sha = hashlib.sha256(candidate_path.read_bytes()).hexdigest()

    description = {"training": None, "study": None}
    relation_columns = {
        TRAINING_WORK_ORDERS: [("ID", "VARCHAR", "ID"), ("source_row_number", "BIGINT", None)],
        TRAINING_CASH: [("工单ID", "VARCHAR", "工单ID"), ("现金收入", "DECIMAL(18,2)", "现金收入")],
        STUDY_RESOURCES: [("resource_id", "VARCHAR", "资源ID"), ("record_key", "VARCHAR", "登记ID")],
        STUDY_CONTRACTS: [("contract_id", "VARCHAR", "合同编号"), ("amount", "DECIMAL(18,2)", "签约金额")],
        STUDY_LANGUAGES: [("record_key", "VARCHAR", "实缴记录ID"), ("amount", "DECIMAL(18,2)", "实缴金额")],
    }
    for domain, snapshot_key, names in (
        ("training", "training", (TRAINING_WORK_ORDERS, TRAINING_CASH)),
        ("study", "abroad", (STUDY_RESOURCES, STUDY_CONTRACTS, STUDY_LANGUAGES)),
    ):
        description[domain] = {
            "schema_version": "warehouse_description.v1",
            "status": "passed",
            "snapshot_id": SNAPSHOTS[snapshot_key],
            "relations": [
                {
                    "schema": "landing",
                    "name": name,
                    "type": "BASE TABLE",
                    "columns": [
                        {"name": column, "type": kind, **({"header_label": label} if label else {})}
                        for column, kind, label in relation_columns[name]
                    ],
                }
                for name in names
            ],
            "errors": [],
        }
    description_path = library / "landing-description.json"
    description_path.write_text(json.dumps(description, ensure_ascii=False), encoding="utf-8")

    provenance = {}
    for relation, domain in PUBLIC_RELATIONS.items():
        snapshot_key = "training" if domain == "training" else "abroad"
        item_domain = "wrong" if bad_provenance_domain and relation == f"landing.{TRAINING_WORK_ORDERS}" else domain
        provenance[relation] = {
            "source_id": f"source_{relation.split('.')[-1]}",
            "snapshot_id": SNAPSHOTS[snapshot_key],
            "domain": item_domain,
        }
    manifest = {
        "schema_version": "sql_warehouse_release.v1",
        "release_id": RELEASE,
        "candidate": file_ref(candidate_path, library, "application/json"),
        "candidate_sha256": candidate_sha,
        "database_sha256": database_ref["sha256"],
        "batch_id": BATCH,
        "snapshots": SNAPSHOTS,
        "as_of_date": "2026-11-06",
        "coverage": {"data_through": "2026-11-05"},
        "landing_description": file_ref(description_path, library, "application/json"),
        "landing_provenance": provenance,
    }
    (library / "release.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (library / "notification-preview.json").write_text("{}", encoding="utf-8")
    (library / "superset-catalogue.json").write_text("{}", encoding="utf-8")
    (library / "acceptance.json").write_text("{}", encoding="utf-8")
    for directory in (root, releases, release_root, library):
        directory.chmod(0o700)
    return release_root, warehouse


def test_candidate_release_query_returns_streamed_result_and_source_provenance(tmp_path: Path) -> None:
    release_root, _ = _build_release(tmp_path)
    release = resolve_sql_release(release_root)
    assert release is not None
    assert release.batch_id == BATCH
    assert release.snapshots == SNAPSHOTS

    result = execute_query_bundle(
        release_root=release_root,
        expected_release=RELEASE,
        expected_batch_id=BATCH,
        domain="training",
        sql='SELECT "ID" FROM landing."br_work_orders__sheet_1f0596db9f25" WHERE "ID" = $id',
        parameters={"id": "001"},
        output_dir=tmp_path / "query-output",
        allowed_relations={TRAINING_WORK_ORDERS, TRAINING_CASH},
    )
    assert result["columns"] == ["ID"]
    assert result["row_count"] == 1
    assert result["referenced_relations"] == [f"landing.{TRAINING_WORK_ORDERS}"]
    assert result["referenced_source_ids"] == [f"source_{TRAINING_WORK_ORDERS}"]
    assert Path(result["rows_path"]).read_text(encoding="utf-8") == '["001"]\n'
    assert result["snapshot_ref"]["kind"] == "sql_warehouse_release_ref.v1"
    assert result["snapshot_ref"]["warehouse_sha256"] == release.database_sha256


def test_sql_release_adapter_keeps_the_existing_public_landing_tables() -> None:
    public = {
        "landing." + table["relation"].split(".", 1)[1]: domain
        for domain, tables in TABLES.items()
        for table in tables
    }
    assert public == PUBLIC_RELATIONS


def test_business_data_query_describes_candidate_labels_and_csv(tmp_path: Path) -> None:
    release_root, _ = _build_release(tmp_path)
    current = tmp_path / "current"
    current.symlink_to(release_root, target_is_directory=True)
    query = BusinessDataQuery(current, tmp_path / "results")

    overview = query.describe()
    assert overview["release"] == RELEASE
    assert overview["snapshots"] == {"training": SNAPSHOTS["training"], "study": SNAPSHOTS["abroad"]}
    table = query.describe(domain="training", table="work_orders")
    assert table["table"]["columns"][0] == {"name": "ID", "type": "VARCHAR", "label": "ID"}
    assert table["table"]["columns"][1] == {"name": "source_row_number", "type": "BIGINT"}

    result = query.query(
        domain="training",
        sql='SELECT "ID" FROM landing."br_work_orders__sheet_1f0596db9f25" WHERE "ID" = $id',
        parameters={"id": "001"},
        expected_release=RELEASE,
        page_size=1,
    )
    assert result["snapshot_id"] == SNAPSHOTS["training"]
    assert result["rows"] == [["001"]]
    assert result["source_tables"] == [f"landing.{TRAINING_WORK_ORDERS}"]
    csv = query.export_csv(result["result_id"], offset=0, limit=10)
    assert csv["complete"] is True
    assert csv["csv_text"] == '"ID"\r\n"001"\r\n'


def test_sql_release_acl_allows_only_candidate_query_inputs(tmp_path: Path) -> None:
    release_root, warehouse = _build_release(tmp_path)
    current = tmp_path / "current"
    releases = tmp_path / "releases"
    current.symlink_to(release_root, target_is_directory=True)

    _, directories, files = acl_sync._release_allowlist(current, releases)
    library = release_root / "library"
    assert files == {
        library / "candidate.json",
        library / "release.json",
        library / "warehouse.duckdb",
        library / "landing-description.json",
    }
    assert warehouse in files
    assert directories == {tmp_path, releases, release_root, library}
    assert not files & {
        library / "notification-preview.json",
        library / "superset-catalogue.json",
        library / "acceptance.json",
    }


def test_sql_release_acl_revokes_previous_release_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release_root, _ = _build_release(tmp_path)
    current = tmp_path / "current"
    releases = tmp_path / "releases"
    current.symlink_to(release_root, target_is_directory=True)
    old_directory = release_root / "foundation"
    old_directory.mkdir()
    old_file = old_directory / "old-warehouse.duckdb"
    old_file.write_bytes(b"legacy")
    old_files = {old_file}
    old_directories = {tmp_path, releases, release_root, old_directory}
    removed: list[tuple[str, str]] = []
    monkeypatch.setattr(acl_sync.os, "geteuid", lambda: 0)
    monkeypatch.setattr(acl_sync.pwd, "getpwnam", lambda _: object())
    monkeypatch.setattr(acl_sync, "_state_read", lambda *_: (old_directories, old_files))
    monkeypatch.setattr(acl_sync, "_has_acl", lambda *_: True)
    monkeypatch.setattr(acl_sync, "_write_state", lambda *args: None)

    def record_acl(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        if command[1] == "-x":
            removed.append((command[2], command[-1]))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(acl_sync.subprocess, "run", record_acl)
    acl_sync.sync_for(current, releases, tmp_path / "state.json", "nobody")
    assert set(removed) == {
        ("u:nobody", str(old_file)),
        ("u:nobody", str(old_directory)),
    }


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    [
        ({"identity_batch": "run_wrong_batch"}, "SQL_RELEASE_IDENTITY_INVALID"),
        ({"bad_import_snapshot": True}, "SQL_RELEASE_SOURCE_INVALID"),
        ({"bad_provenance_domain": True}, "SQL_RELEASE_SOURCE_INVALID"),
    ],
)
def test_sql_release_rejects_unmatched_batch_or_source_identity(
    tmp_path: Path,
    kwargs: dict[str, object],
    error_code: str,
) -> None:
    release_root, _ = _build_release(tmp_path, **kwargs)
    with pytest.raises(QueryError) as error:
        resolve_sql_release(release_root)
    assert error.value.code == error_code


def test_sql_release_rejects_database_mutation_after_seal(tmp_path: Path) -> None:
    release_root, warehouse = _build_release(tmp_path)
    with duckdb.connect(str(warehouse)) as connection:
        connection.execute("INSERT INTO landing.br_work_orders__sheet_1f0596db9f25 VALUES ('003', 3)")
    with pytest.raises(QueryError) as error:
        resolve_sql_release(release_root)
    assert error.value.code == "SQL_RELEASE_INVALID"


def test_candidate_sql_does_not_expand_registered_raw_landing_scope(tmp_path: Path) -> None:
    release_root, _ = _build_release(tmp_path)
    with pytest.raises(QueryError) as error:
        execute_query_bundle(
            release_root=release_root,
            expected_release=RELEASE,
            expected_batch_id=BATCH,
            domain="training",
            sql="SELECT * FROM landing.study_abroad_market__resources",
            output_dir=tmp_path / "query-output",
            allowed_relations={TRAINING_WORK_ORDERS, TRAINING_CASH},
        )
    assert error.value.code == "QUERY_REJECTED"
    assert not (tmp_path / "query-output").exists()

def test_dashboard_query_and_csv_use_the_same_published_rows(tmp_path: Path) -> None:
    release_root, _ = _build_release(tmp_path)
    current = tmp_path / "current"
    current.symlink_to(release_root, target_is_directory=True)
    worker = BusinessDataQuery(current, tmp_path / "results")
    catalog = worker.describe()["dashboard_datasets"]
    assert list(catalog) == ["team_metrics"]
    assert "prior 上年同期" in catalog["team_metrics"]["description"]
    page = worker.read_dashboard_data("team_metrics", RELEASE, {"metric": ["heads", "cash"]})
    assert page["rows"] == [["FY27", "heads", 2, "training", "total", "被动"]]
    assert page["source_tables"] == ["business.team_metrics"]
    assert "上年同期" in page["column_descriptions"]["prior"]
    assert worker.read_page(page["result_id"])["column_descriptions"] == page["column_descriptions"]
    assert worker.read_dashboard_data("team_metrics", RELEASE, {"acquisition_scope": "全部"})["rows"][0][2] == 3
    assert worker.read_dashboard_data("team_metrics", RELEASE, {"business_line": "abroad", "unit_id": "online"})["rows"][0][2] == 4
    all_rows = worker.read_dashboard_data("team_metrics", RELEASE, {"business_line": "*", "unit_id": "*", "acquisition_scope": "*"})["rows"]
    assert sorted(row[2] for row in all_rows) == [2, 3, 4]
    csv = worker.export_csv(page["result_id"])
    assert csv["snapshots"] == SNAPSHOTS
    assert csv["column_descriptions"] == page["column_descriptions"]
    assert csv["csv_text"].splitlines()[-1] == '"FY27","heads","2","training","total","被动"'
    with pytest.raises(QueryError, match="Unsupported dashboard filter"):
        worker.read_dashboard_data("team_metrics", RELEASE, {"unknown": "FY27"})


def test_semantic_release_reads_only_registered_qualified_relations(tmp_path):
    release_root, _ = _build_release(tmp_path)
    allowed = {"core.training_orders_attributed", "mart.team_metrics"}
    def query(sql, output):
        return execute_query_bundle(
            release_root=release_root, expected_release=RELEASE, expected_batch_id=BATCH,
            domain="semantic", sql=sql, output_dir=tmp_path / output,
            allowed_relations=allowed, max_rows=3,
        )
    result = query("SELECT a.fixture_id FROM core.training_orders_attributed a "
                   "JOIN mart.team_metrics m USING(fixture_id)", "semantic")
    assert result["referenced_relations"] == sorted(allowed)
    assert result["snapshot_ref"]["release"] == RELEASE
    assert Path(result["rows_path"]).read_text() == "[1]\n"
    with pytest.raises(QueryError, match="registered semantic"):
        query(f"SELECT * FROM landing.{TRAINING_WORK_ORDERS}", "raw_not_allowed")
    with pytest.raises(QueryError, match="catalog-qualified"):
        query("SELECT * FROM warehouse.mart.team_metrics", "catalog_not_allowed")


def test_oxhor_semantic_binds_current_sealed_release_and_writes_evidence(tmp_path, monkeypatch):
    from market_workspace.tools import data

    source, market = tmp_path / 'source', tmp_path / 'market'
    state = source / 'Output/ShadowDaily'
    release_root, _ = _build_release(state)
    release = resolve_sql_release(release_root)
    (state / 'sql-current.json').write_text(json.dumps({
        'schema_version': 'sql_daily_current.v1', 'release': RELEASE, 'batch_id': BATCH,
        'local_release_root': str(release_root), 'release_manifest_sha256': release.release_manifest_sha256,
        'warehouse_sha256': release.database_sha256,
    }))
    market.mkdir()
    sql = market / 'query.sql'
    sql.write_text('SELECT fixture_id FROM core.training_orders_attributed')
    monkeypatch.setattr(data, 'SOURCE', source)
    monkeypatch.setattr(data, 'MARKET', market)
    args = data.parser().parse_args(['query', '--release-id', RELEASE, '--run-id', 'run_semantic_test',
                                    '--sql-file', str(sql)])
    code, receipt = data.execute(args)
    assert code == 0 and receipt['release_id'] == RELEASE
    assert receipt['result']['referenced_relations'] == ['core.training_orders_attributed']
    run = market / 'Evidence/run_semantic_test'
    assert json.loads((run / 'receipt.json').read_text()) == receipt
    assert (run / receipt['files']['rows']['path']).read_text() == '[1]\n'
    args.release_id = 'not-current'
    with pytest.raises(ValueError, match='版本已变化'):
        data.execute(args)
