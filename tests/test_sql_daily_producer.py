"""SQL daily producer contracts; these tests never contact the BI server."""
import hashlib
import json
from pathlib import Path
import tarfile

import pytest

from dashboard_product.shadow_bi.p5 import sql_daily
from dashboard_product.shadow_bi.p5.daily import package_tables
from data_platform.query.evidence import file_ref


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pointer_fixture(tmp_path):
    workspace = tmp_path / "workspace"
    state = workspace / "Output/ShadowDaily"
    state.mkdir(parents=True)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    database = candidate / "warehouse.duckdb"
    database.write_bytes(b"previous sealed SQL warehouse")
    batch_id = "run_sql_daily_previous"
    manifest = {
        "schema_version": "sql_warehouse_candidate.v1",
        "batch_id": batch_id,
        "database": file_ref(database, candidate, "application/vnd.duckdb"),
    }
    (candidate / "candidate.json").write_text(json.dumps(manifest))
    acceptance = tmp_path / "migration-acceptance.json"
    acceptance.write_text(json.dumps({
        "numbers_match": True, "functions_match": True, "interface_match": True,
    }))
    pointer = {
        "schema_version": "sql_daily_current.v1",
        "release": "daily-sql-previous",
        "batch_id": batch_id,
        "candidate": str(candidate.resolve()),
        "coverage": {"notes": ["preserve this note"], "capacity_start": "2026-06-01"},
        "warehouse_sha256": _sha(database),
        "migration_acceptance": str(acceptance.resolve()),
    }
    (state / "sql-current.json").write_text(json.dumps(pointer))
    return workspace, candidate, pointer, acceptance


def test_sql_current_requires_explicit_pointer_and_verifies_baseline_and_acceptance(tmp_path):
    with pytest.raises(ValueError, match="SQL daily pointer is missing"):
        sql_daily.load_sql_current(tmp_path / "workspace")

    workspace, candidate, pointer, acceptance = _pointer_fixture(tmp_path)
    loaded = sql_daily.load_sql_current(workspace)
    assert loaded[0] == pointer
    assert loaded[2] == candidate.resolve()
    assert loaded[4] == _sha(acceptance)

    candidate.joinpath("warehouse.duckdb").write_bytes(b"changed")
    with pytest.raises(ValueError, match="evidence byte identity mismatch"):
        sql_daily.load_sql_current(workspace)


def test_migration_acceptance_must_keep_all_three_checks_true(tmp_path):
    workspace, _, _, acceptance = _pointer_fixture(tmp_path)
    acceptance.write_text(json.dumps({
        "numbers_match": True, "functions_match": False, "interface_match": True,
    }))
    with pytest.raises(ValueError, match="all three passed checks"):
        sql_daily.load_sql_current(workspace)


def test_source_order_receipts_are_fresh_controlled_queries_for_each_year_window(
        tmp_path, monkeypatch):
    import data_platform.query.evidence as evidence
    from dashboard_product.management.calculation import _confirmed_adviser_lists

    workspace = tmp_path / "workspace"
    warehouse = workspace / "warehouse.duckdb"
    warehouse.parent.mkdir(parents=True)
    warehouse.write_bytes(b"snapshot warehouse placeholder")
    (workspace / "Work").mkdir()
    (workspace / "Work/workspace.json").write_text(json.dumps({
        "current_snapshot_id": "snapshot_training_fixture",
        "current_warehouse_path": "warehouse.duckdb",
    }))
    calls = []

    def execute_query(**kwargs):
        calls.append(kwargs)
        return {
            "status": "passed",
            "run_id": kwargs["run_id"],
            "receipt": {"path": "receipt.json"},
        }

    def read_query_result(response, *, output_root):
        assert output_root == tmp_path / "evidence"
        return {
            "columns": ["orders_start", "orders_end", "cash_start", "cash_end"],
            "rows": [["2025-03-01", "2026-11-06", "2024-06-01", "2026-11-06"]],
        }

    monkeypatch.setattr(sql_daily, "read_query_result", read_query_result)
    monkeypatch.setattr(evidence, "resolve_file",
                        lambda base, ref: Path(base) / ref["path"])
    result = sql_daily.source_order_receipts(
        workspace=workspace, training_snapshot="snapshot_training_fixture",
        as_of_date="2026-11-07", batch_id="run_shadow_daily_20261107_093634",
        output_root=tmp_path / "evidence", execute_query=execute_query)

    assert result["through_date"] == "2026-11-06"
    assert len(result["source_order_receipts"]) == 3
    assert [call["parameters"][:2] for call in calls[1:]] == [
        ["2024-06-01", "2025-01-01"],
        ["2025-01-01", "2026-01-01"],
        ["2026-01-01", "2026-11-07"],
    ]
    assert all(call["sql"] == (sql_daily.ROOT / "dashboard_product/management/sql/training_details.sql").read_text()
               for call in calls[1:])
    mapping = json.loads((sql_daily.ROOT / "dashboard_product/online_team/config/confirmed_team_mapping.json").read_text())
    study_advisers, prep_advisers = _confirmed_adviser_lists(mapping)
    assert calls[1]["parameters"][3:5] == [study_advisers, prep_advisers]
    assert calls[1]["parameters"][5] == ["主动", "被动"]
    assert all(call["snapshot_id"] == "snapshot_training_fixture" for call in calls)


def test_sql_release_archive_accepts_only_the_seven_runtime_files(tmp_path):
    release = "daily-sql-fixture"
    files = sorted(sql_daily._ARCHIVE_FILES)
    archive_path = tmp_path / "release.tar"
    with tarfile.open(archive_path, "w") as archive:
        for name in files:
            file_path = tmp_path / name
            file_path.write_text(name)
            archive.add(file_path, arcname=f"{release}/library/{name}")
    sql_daily._validate_archive(archive_path, release)

    unsafe_path = tmp_path / "unsafe.tar"
    with tarfile.open(unsafe_path, "w") as archive:
        payload = tmp_path / "payload"
        payload.write_text("not allowed")
        archive.add(payload, arcname=f"{release}/library/../../outside")
    with pytest.raises(ValueError, match="unsafe path"):
        sql_daily._validate_archive(unsafe_path, release)


def test_install_script_uses_fixed_release_root_and_sql_release_activation():
    script = sql_daily._install_script(
        "daily-sql-next", "run_shadow_daily_20261107_093634",
        "daily-sql-previous", "a" * 64, "b" * 64)
    assert "tar --no-same-owner --no-same-permissions" in script
    assert "/var/lib/shadow-bi/releases/daily-sql-next" in script
    assert "/srv/shadow-bi/venv/bin/python -m dashboard_product.shadow_bi.p4.sql_release" not in script

    with pytest.raises(ValueError, match="release identity"):
        sql_daily._install_script("../../candidate", "run_shadow_daily_20261107_093634",
                                  "daily-sql-previous", "a" * 64, "b" * 64)


def test_runtime_acceptance_carries_migration_sha_and_catalogue_contract():
    acceptance = {
        "mode": "runtime_contract",
        "migration_acceptance": {"path": "/local/certificate.json", "sha256": "a" * 64},
        "runtime_contract": {
            "status": "passed", "catalogue_sha256": "b" * 64,
            "candidate_identity_passed": True, "source_gates_passed": True,
        },
    }
    assert acceptance["mode"] == "runtime_contract"
    assert acceptance["migration_acceptance"]["sha256"] == "a" * 64
    assert acceptance["runtime_contract"]["catalogue_sha256"] == "b" * 64
    assert acceptance["runtime_contract"]["candidate_identity_passed"] is True
    assert acceptance["runtime_contract"]["source_gates_passed"] is True


def test_full_daily_preview_package_still_transfers_only_sealed_table_files(tmp_path):
    source = tmp_path / "source"
    presentation = tmp_path / "presentation"
    source.mkdir()
    presentation.mkdir()
    table = source / "tables/known.jsonl"
    table.parent.mkdir()
    table.write_text('{"orders":7}\n')
    (presentation / "library_manifest.json").write_text(json.dumps({
        "tables": {"known": {"data": {"path": "tables/known.jsonl", "sha256": _sha(table)}}},
    }))

    package_tables(source, presentation, tmp_path / "transfer")

    files = {path.relative_to(tmp_path / "transfer").as_posix()
             for path in (tmp_path / "transfer").rglob("*") if path.is_file()}
    assert files == {"tables/known.jsonl", "library_manifest.json"}


def test_publish_builds_runtime_contract_and_updates_pointer_only_after_activation(
        tmp_path, monkeypatch):
    import duckdb
    from dashboard_product.shadow_bi.p5 import sql_bundle
    from dashboard_product.shadow_bi.sql_warehouse import build as sql_build
    from dashboard_product.shadow_bi.sql_warehouse.foundation import TABLES

    workspace, baseline, pointer, acceptance_file = _pointer_fixture(tmp_path)
    folder = tmp_path / "daily-run"
    folder.mkdir()
    current_catalogue = b"static SQL catalogue"
    current_catalogue_sha = hashlib.sha256(current_catalogue).hexdigest()
    remote_before = {"catalogue_sha256": current_catalogue_sha}
    migration = json.loads(acceptance_file.read_text())
    migration_sha = _sha(acceptance_file)
    current_state = (pointer, remote_before, {}, baseline, migration, migration_sha)
    pair = {"sources": {
        "bi": {"snapshot_id": "snapshot_training_new"},
        "study_abroad": {"snapshot_id": "snapshot_abroad_new"},
    }}
    batch_id = "run_shadow_daily_20261107_093634"
    release_id = "daily-sql-next"
    candidate_builds = []
    prepared_acceptance = {}
    archives = []

    def source_receipts(**kwargs):
        return {"source_order_receipts": [str(tmp_path / "receipt.json")],
                "coverage": {"orders_start": "2025-03-01", "cash_start": "2024-06-01"},
                "through_date": "2026-11-06"}

    def build_local(**kwargs):
        candidate_builds.append(kwargs)
        candidate_dir = Path(kwargs["output_dir"])
        candidate_dir.mkdir(parents=True)
        database = candidate_dir / "warehouse.duckdb"
        with duckdb.connect(str(database)) as con:
            con.execute("CREATE SCHEMA landing; CREATE SCHEMA meta")
            con.execute("CREATE TABLE meta.identity(batch_id VARCHAR)")
            con.execute("INSERT INTO meta.identity VALUES (?)", [batch_id])
            for name in (*TABLES["training"], *TABLES["abroad"]):
                con.execute(f'CREATE TABLE landing."{name}" (source_row_number BIGINT)')
        preview = candidate_dir / "notification-preview.json"
        preview.write_text(json.dumps({
            "schema_version": "management_notifications.v1",
            "data_through": "2026-11-06", "messages": [{} for _ in range(8)],
        }))
        manifest = {
            "schema_version": "sql_warehouse_candidate.v1", "status": "built_unreconciled",
            "published": False, "batch_id": batch_id,
            "snapshots": {"training": "snapshot_training_new", "abroad": "snapshot_abroad_new"},
            "as_of_date": "2026-11-07", "through_date": "2026-11-06",
            "database": file_ref(database, candidate_dir, "application/vnd.duckdb"),
            "notification_preview": file_ref(preview, candidate_dir, "application/json"),
            "relations": [{"table_schema": "landing", "table_name": name}
                          for name in (*TABLES["training"], *TABLES["abroad"])],
            "expenses": {"status": "updated", "rows": 0},
        }
        (candidate_dir / "candidate.json").write_text(json.dumps(manifest))
        return manifest

    def prepare_release(*, candidate, workspace, release_id, output_dir,
                        coverage_template, acceptance):
        prepared_acceptance.update(acceptance)
        candidate_dir = Path(candidate)
        release_dir = Path(output_dir) / release_id / "library"
        release_dir.mkdir(parents=True)
        for name in ("candidate.json", "warehouse.duckdb", "notification-preview.json"):
            (release_dir / name).write_bytes((candidate_dir / name).read_bytes())
        catalogue = release_dir / "superset-catalogue.json"
        catalogue.write_bytes(current_catalogue)
        description = release_dir / "landing-description.json"
        description.write_text("{}")
        (release_dir / "acceptance.json").write_text(json.dumps(acceptance))
        candidate_doc = json.loads((release_dir / "candidate.json").read_text())
        candidate_ref = file_ref(release_dir / "candidate.json", release_dir, "application/json")
        manifest = {
            "schema_version": "sql_warehouse_release.v1", "release_id": release_id,
            "candidate": candidate_ref, "candidate_sha256": candidate_ref["sha256"],
            "database_sha256": candidate_doc["database"]["sha256"],
            "batch_id": batch_id, "snapshots": candidate_doc["snapshots"],
            "as_of_date": candidate_doc["as_of_date"],
            "coverage": {"data_through": candidate_doc["through_date"],
                         "snapshot_id": candidate_doc["snapshots"]["training"]},
            "superset_catalogue": file_ref(catalogue, release_dir, "application/json"),
        }
        (release_dir / "release.json").write_text(json.dumps(manifest))
        archive_path = Path(output_dir) / "sql-release.tar"
        with tarfile.open(archive_path, "w") as archive:
            archive.add(release_dir, arcname=f"{release_id}/library")
        archives.append(archive_path)
        return {"release": release_id, "library": str(release_dir),
                "archive": str(archive_path), "archive_sha256": _sha(archive_path)}

    def candidate_doc():
        return json.loads((Path(candidate_builds[0]["output_dir"]) / "candidate.json").read_text())

    def remote_after_activation(**kwargs):
        candidate = candidate_doc()
        return {
            "release": release_id, "batch_id": batch_id,
            "warehouse_sha256": candidate["database"]["sha256"],
            "catalogue_sha256": current_catalogue_sha,
            "coverage": {"data_through": candidate["through_date"],
                         "snapshot_id": candidate["snapshots"]["training"]},
            "verification": {"status": "passed", "metrics_compared": 18},
        }

    monkeypatch.setattr(sql_daily, "source_order_receipts", source_receipts)
    monkeypatch.setattr(sql_daily, "remote_current", remote_after_activation)
    monkeypatch.setattr(sql_bundle, "prepare_release", prepare_release)
    monkeypatch.setattr(sql_build, "build_local", build_local)

    commands = []
    result_commands = []

    def command(args, log, **kwargs):
        if "stdin" in kwargs:
            commands.append((args, kwargs["stdin"].read()))

    def command_result(args, log, **kwargs):
        result_commands.append(args)
        script = kwargs["input"]
        if '--retire-previous' in script:
            return {'status': 'retired', 'current': release_id, 'removed': pointer['release']}
        if "--expected-current" in script:
            return {"status": "activated", "current": release_id, "batch_id": batch_id,
                    "verification": {"status": "passed", "metrics_compared": 18}}
        return {"status": "prepared", "release": release_id, "batch_id": batch_id,
                "warehouse_sha256": candidate_doc()["database"]["sha256"]}

    ssh = ["ssh", "-o", "BatchMode=yes", "example"]
    result = sql_daily.publish(
        workspace=workspace, day="2026-11-07", pair=pair, run_id=batch_id,
        release_id=release_id, folder=folder, advertising_manifest=None,
        ssh=ssh, ssh_env={}, command=command, command_result=command_result,
        config_root=tmp_path, current_state=current_state)

    assert result["status"] == "published"
    assert result['server_retention']['status'] == 'retired'
    assert candidate_builds[0]["expense_baseline"] == baseline
    assert prepared_acceptance["mode"] == "runtime_contract"
    assert prepared_acceptance["migration_acceptance"] == {
        "path": pointer["migration_acceptance"], "sha256": migration_sha,
    }
    assert prepared_acceptance["runtime_contract"]["catalogue_sha256"] == current_catalogue_sha
    assert len(commands) == 1
    assert commands[0][0][:-1] == ["ssh", "-C", "-o", "BatchMode=yes", "example"]
    assert commands[0][1] == archives[0].read_bytes()
    assert result_commands and all(args == ssh + ["bash -s"] for args in result_commands)
    assert ssh == ["ssh", "-o", "BatchMode=yes", "example"]
    updated = json.loads((workspace / "Output/ShadowDaily/sql-current.json").read_text())
    assert updated["release"] == release_id
    assert updated["batch_id"] == batch_id
    assert updated["candidate"] == str(candidate_builds[0]["output_dir"])
