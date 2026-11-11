from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from data_acquisition.transfer.foundation import prepare_bundle


AS_OF = "2026-11-04"
BI_ID = "snapshot_bi_operations_20261104_fixture"
ABROAD_ID = "snapshot_study_abroad_20261104_fixture"
HISTORY_ID = "snapshot_study_abroad_history_fixture"
COMPANY = "workspace_bi_operations"


def _raw(value: bytes) -> tuple[str, int]:
    return hashlib.sha256(value).hexdigest(), len(value)


def _write(path: Path, value: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _snapshot(root: Path, *, snapshot_id: str, run_id: str, source_id: str | None = None,
              source_sha256: str | None = None) -> dict:
    warehouse = _write(root / "warehouse.duckdb", f"warehouse:{snapshot_id}".encode())
    digest, size = _raw(warehouse.read_bytes())
    manifest = {
        "schema_version": "warehouse_snapshot.v2",
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "sources": ([{"source_id": source_id, "sha256": source_sha256}] if source_id else []),
        "artifacts": [{"path": "warehouse.duckdb", "sha256": digest, "size_bytes": size}],
    }
    _write(root / "snapshot_manifest.json", _json_bytes(manifest))
    return manifest


def _query_evidence(workspace: Path, *, run_id: str, snapshot_id: str,
                    manifest_bytes: bytes, warehouse_sha: str, kind: str) -> dict:
    evidence_id = f"evidence_{kind}"
    output_root = workspace / "Output/StudyAbroad/历史查询回执"
    base = output_root / run_id / "data/query_results" / evidence_id
    result = _json_bytes({"columns": ["value"], "rows": []})
    files = {
        "query.sql": b"SELECT 1\n",
        "parameters.json": b"[]",
        "result.json": result,
    }
    refs = {}
    for name, payload in files.items():
        _write(base / name, payload)
        sha, size = _raw(payload)
        key = {"query.sql": "sql", "parameters.json": "parameters", "result.json": "result"}[name]
        refs[key] = {"path": name, "sha256": sha, "size_bytes": size,
                     "media_type": "text/plain" if key == "sql" else "application/json"}
    receipt = {
        "schema_version": "query_receipt.v1",
        "kind": "query",
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "created_at": "2026-11-04T00:00:00+00:00",
        "producer": {"name": "foundation-transfer-test", "version": "1"},
        "evidence_id": evidence_id,
        "snapshot_ref": {
            "snapshot_id": snapshot_id,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "warehouse_sha256": warehouse_sha,
        },
        **refs,
        "referenced_relations": ["landing.study_abroad_market__" + kind],
        "referenced_source_ids": ["study_abroad_market"],
        "columns": ["value"],
        "row_count": 0,
        "limits": {"max_rows": 10, "max_result_bytes": 1000},
    }
    receipt_bytes = _json_bytes(receipt)
    _write(base / "receipt.json", receipt_bytes)
    receipt_sha, receipt_size = _raw(receipt_bytes)
    return {"path": f"data/query_results/{evidence_id}/receipt.json",
            "sha256": receipt_sha, "size_bytes": receipt_size,
            "media_type": "application/json", "evidence_id": evidence_id}


@pytest.fixture
def paired_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    bi_run = "run_bi_operations_20261104_fixture"
    abroad_run = "run_shadow_daily_20261104_fixture"
    history_run = "run_study_abroad_history_fixture"
    bi_root = workspace / "Work/Runs" / bi_run / "data/snapshots" / BI_ID
    bi_manifest = _snapshot(bi_root, snapshot_id=BI_ID, run_id=bi_run)
    bi_warehouse = (bi_root / "warehouse.duckdb").relative_to(workspace).as_posix()

    history_root = workspace / "Work/StudyAbroad/Runs" / history_run / "data/snapshots" / HISTORY_ID
    history_manifest = _snapshot(history_root, snapshot_id=HISTORY_ID, run_id=history_run)
    history_manifest_bytes = (history_root / "snapshot_manifest.json").read_bytes()
    history_lineage = {
        "schema_version": "study_abroad_warehouse.v1",
        "company_id": COMPANY,
        "run_id": history_run,
        "snapshot_id": HISTORY_ID,
    }
    history_lineage_bytes = _json_bytes(history_lineage)
    history_lineage_path = workspace / "Work/StudyAbroad/Runs" / history_run / "source_lineage.json"
    _write(history_lineage_path, history_lineage_bytes)
    history_warehouse_sha, _ = _raw((history_root / "warehouse.duckdb").read_bytes())

    abroad_root = workspace / "Work/StudyAbroad/Runs" / abroad_run / "data/snapshots" / ABROAD_ID
    origin = _write(workspace / "Work/StudyAbroad/Runs" / abroad_run / "input/source.xlsx", b"origin")
    prepared = _write(workspace / "Work/StudyAbroad/Runs" / abroad_run / "input/prepared.xlsx", b"prepared")
    people = _write(workspace / "Work/StudyAbroad/Runs" / abroad_run / "input/people.json", b"{}")
    abroad_people = _write(workspace / "Work/StudyAbroad/Runs" / abroad_run / "input/abroad_people.json", b"{}")
    origin_sha, _ = _raw(origin.read_bytes())
    prepared_sha, _ = _raw(prepared.read_bytes())
    abroad_manifest = _snapshot(abroad_root, snapshot_id=ABROAD_ID, run_id=abroad_run,
                                source_id="study_abroad_market", source_sha256=prepared_sha)
    abroad_warehouse = (abroad_root / "warehouse.duckdb").relative_to(workspace).as_posix()

    query_receipts = {}
    query_run_ids = {}
    for kind in ("resources", "contracts", "languages"):
        query_run_id = f"run_shadow_daily_20261104_fixture_history_{kind}"
        query_run_ids[kind] = query_run_id
        query_receipts[kind] = _query_evidence(
            workspace, run_id=query_run_id, snapshot_id=HISTORY_ID,
            manifest_bytes=history_manifest_bytes, warehouse_sha=history_warehouse_sha,
            kind=kind,
        )

    study_lineage = {
        "schema_version": "study_abroad_warehouse.v1",
        "company_id": COMPANY,
        "run_id": abroad_run,
        "snapshot_id": ABROAD_ID,
        "origin_file": "input/source.xlsx",
        "prepared_file": "input/prepared.xlsx",
        "roster_files": {"people": "input/people.json", "abroad_people": "input/abroad_people.json"},
        "source_hashes": {
            "source": origin_sha,
            "people": _raw(people.read_bytes())[0],
            "abroad_people": _raw(abroad_people.read_bytes())[0],
        },
        "normalized_history": {
            "source_run_id": history_run,
            "source_snapshot_id": HISTORY_ID,
            "company_id": COMPANY,
            "warehouse": "/local/producer/path/warehouse.duckdb",
            "snapshot_manifest_sha256": hashlib.sha256(history_manifest_bytes).hexdigest(),
            "source_lineage_sha256": hashlib.sha256(history_lineage_bytes).hexdigest(),
            "query_receipts": query_receipts,
            "query_run_ids": query_run_ids,
        },
    }
    lineage_path = workspace / "Work/StudyAbroad/Runs" / abroad_run / "source_lineage.json"
    _write(lineage_path, _json_bytes(study_lineage))
    study_pointer = {
        "schema_version": "study_abroad_warehouse.v1",
        "company_id": COMPANY,
        "run_id": abroad_run,
        "snapshot_id": ABROAD_ID,
        "through_date": AS_OF,
        "source_sha256": origin_sha,
        "warehouse": abroad_warehouse,
        "source_lineage": lineage_path.relative_to(workspace).as_posix(),
    }
    _write(workspace / "Work/StudyAbroad/current.json", _json_bytes(study_pointer))

    workspace_config = {
        "schema_version": "bridge_alignment_workspace.v1",
        "company_id": COMPANY,
        "business_port": "operations",
        "pack_path": "Work/Pack/pack.json",
        "pack_ref": {"pack_id": "education_training_operations_cn", "pack_version": "1.0.0"},
        "bridge_reference_path": "Work/Bridge/reference.json",
        "current_snapshot_id": BI_ID,
        "current_warehouse_path": bi_warehouse,
        "used_snapshot_ids": [BI_ID],
    }
    _write(workspace / "Work/workspace.json", _json_bytes(workspace_config))
    _write(workspace / "Work/Pack/pack.json", b"{}\n")
    _write(workspace / "Work/Bridge/reference.json", b"{}\n")
    _write(workspace / "Input/Reference/留学-FY26-资源表.xlsx", b"reference")
    _write(workspace / "Input/AdvertisingCosts/sources.json", b'{"sources":[]}\n')

    daily_run = "run_shadow_daily_20261104_fixture"
    daily_receipt = {
        "schema_version": "daily_warehouse_refresh.v1",
        "run_id": daily_run,
        "company_id": COMPANY,
        "as_of_date": AS_OF,
        "status": "passed",
        "sources": {
            "bi": {"status": "success", "company_id": COMPANY, "snapshot_id": BI_ID,
                   "run_id": daily_run, "cutoff_date": AS_OF, "captured_at": AS_OF,
                   "value_sha256": "a" * 64},
            "study_abroad": {"status": "success", "company_id": COMPANY, "snapshot_id": ABROAD_ID,
                             "run_id": daily_run, "cutoff_date": AS_OF, "through_date": AS_OF,
                             "captured_at": AS_OF, "value_sha256": "b" * 64},
        },
    }
    receipt_bytes = _json_bytes(daily_receipt)
    _write(workspace / "Work/DailyWarehouseRefresh/Runs" / daily_run / "receipt.json", receipt_bytes)
    pointer = {
        "schema_version": "daily_warehouse_refresh.v1",
        "status": "passed",
        "run_id": daily_run,
        "company_id": COMPANY,
        "as_of_date": AS_OF,
        "receipt_path": f"Runs/{daily_run}/receipt.json",
        "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "bi_snapshot_id": BI_ID,
        "study_snapshot_id": ABROAD_ID,
    }
    _write(workspace / "Work/DailyWarehouseRefresh/current.json", _json_bytes(pointer))
    _write(workspace / ".private/token", b"must-not-be-packed")
    return workspace


def _prepare(workspace: Path, output: Path, *, advertising_manifest: Path | None = None) -> dict:
    return prepare_bundle(
        workspace,
        {"bi": BI_ID, "study_abroad": ABROAD_ID},
        "run_shadow_daily_20261104_fixture_transfer",
        AS_OF,
        output,
        release_id="daily-20261104_fixture_transfer",
        advertising_manifest=advertising_manifest,
    )


def test_bundle_contains_explicit_pair_and_only_declared_payload(paired_workspace: Path, tmp_path: Path) -> None:
    result = _prepare(paired_workspace, tmp_path / "bundle")
    with tarfile.open(result["bundle_path"], "r:") as archive:
        names = archive.getnames()
        manifest = json.load(archive.extractfile("manifest.json"))
        assert names[0] == "manifest.json"
        assert manifest["schema_version"] == "shadow_foundation_bundle.v1"
        assert manifest["snapshots"] == {"bi": BI_ID, "study_abroad": ABROAD_ID}
        assert set(manifest["files"]) == set(names[1:])
        assert "workspace/Work/Runs/run_bi_operations_20261104_fixture/data/snapshots/" + BI_ID + "/warehouse.duckdb" in names
        assert "workspace/Work/StudyAbroad/Runs/run_shadow_daily_20261104_fixture/data/snapshots/" + ABROAD_ID + "/warehouse.duckdb" in names
        assert "workspace/Work/StudyAbroad/Runs/run_study_abroad_history_fixture/data/snapshots/" + HISTORY_ID + "/warehouse.duckdb" in names
        assert "workspace/Work/DailyWarehouseRefresh/Runs/run_shadow_daily_20261104_fixture/receipt.json" in names
        assert not any("/.private/" in name for name in names)
        assert not any("/Output/ShadowBI/" in name for name in names)


def test_explicit_empty_fee_manifest_is_bound_and_resume_is_idempotent(
    paired_workspace: Path, tmp_path: Path,
) -> None:
    candidate = tmp_path / "empty-candidate.json"
    candidate.write_text('{"sources":[]}\n', encoding="utf-8")
    output = tmp_path / "bundle"
    first = _prepare(paired_workspace, output, advertising_manifest=candidate)
    second = _prepare(paired_workspace, output, advertising_manifest=candidate)
    assert first["manifest"]["advertising_manifest"] == "Input/AdvertisingCosts/candidate-sources.json"
    assert first["sha256"] == second["sha256"]
    with tarfile.open(first["bundle_path"], "r:") as archive:
        candidate_bytes = archive.extractfile("workspace/Input/AdvertisingCosts/candidate-sources.json").read()
        expected = first["manifest"]["files"]["workspace/Input/AdvertisingCosts/candidate-sources.json"]
    assert hashlib.sha256(candidate_bytes).hexdigest() == expected["sha256"]


def test_candidate_fee_assets_and_absolute_scope_evidence_are_rebased(
    paired_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from data_acquisition.transfer import foundation as transfer
    from openpyxl import Workbook

    source = tmp_path / "native-ocean.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["项目ID", "日期", "投放类型", "营销场景", "消耗(元)"])
    sheet.append(["project-1", "2026-11-03", "信息流", "招生", 12.34])
    workbook.save(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    evidence = tmp_path / "scope-evidence.json"
    evidence_doc = {
        "evidence_type": "user_confirmed_business_scope",
        "account_id": "74749810",
        "combine_rule": "sum",
        "confirmed_entrances": ["竞价－搜索投放", "竞价－展示投放"],
        "exclude_costs_by_product": False,
        "technical_disjointness_proven": False,
    }
    evidence.write_text(json.dumps(evidence_doc, ensure_ascii=False), encoding="utf-8")
    evidence_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "sources": [{
            "source_id": "training_ocean_fixture",
            "path": str(source),
            "kind": "ocean_daily",
            "business_line": "training",
            "business_group": "大学",
            "platform": "抖音",
            "sha256": source_sha,
        }],
        "business_scope_confirmation": {
            "account_id": "74749810",
            "product_scopes": ["display_plus", "legacy_search"],
            "combine_rule": "sum",
            "evidence": {"path": str(evidence), "sha256": evidence_sha},
        },
    }, ensure_ascii=False), encoding="utf-8")

    remote_root = tmp_path / "remote/releases"
    monkeypatch.setattr(transfer, "REMOTE_RELEASE_ROOT", str(remote_root))
    result = _prepare(paired_workspace, tmp_path / "bundle", advertising_manifest=candidate)
    release_root = remote_root / "daily-20261104_fixture_transfer/foundation"
    with tarfile.open(result["bundle_path"], "r:") as archive:
        candidate_manifest = json.load(archive.extractfile("workspace/Input/AdvertisingCosts/candidate-sources.json"))
        source_path = candidate_manifest["sources"][0]["path"]
        evidence_path = candidate_manifest["business_scope_confirmation"]["evidence"]["path"]
        assert source_path.startswith("candidate-assets/")
        assert Path(evidence_path).is_absolute()
        assert Path(evidence_path).parent == release_root / "Input/AdvertisingCosts/candidate-assets"
        assert archive.extractfile("workspace/Input/AdvertisingCosts/" + source_path) is not None
        evidence_member = "workspace/" + str(Path(evidence_path).relative_to(release_root))
        evidence_bytes = archive.extractfile(evidence_member).read()
        assert hashlib.sha256(evidence_bytes).hexdigest() == evidence_sha
        for member in archive.getmembers()[1:]:
            relative = Path(member.name).relative_to("workspace")
            destination = release_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.extractfile(member).read())
    from dashboard_product.management.candidate_sources import load_candidate_sources
    parsed = load_candidate_sources(release_root / "Input/AdvertisingCosts/candidate-sources.json")
    assert parsed["rows"][0]["amount"] == 12.34


def test_registered_fee_manifest_keeps_default_mode_and_assets_are_reopenable(
    paired_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openpyxl import Workbook
    from data_acquisition.transfer import foundation as transfer

    source = paired_workspace / "Input/AdvertisingCosts/native-ocean.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["项目ID", "日期", "投放类型", "营销场景", "消耗(元)"])
    sheet.append(["project-1", "2026-11-03", "信息流", "招生", 12.34])
    workbook.save(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    (paired_workspace / "Input/AdvertisingCosts/sources.json").write_text(json.dumps({
        "sources": [{
            "source_id": "training_ocean_fixture",
            "path": str(source),
            "kind": "ocean_daily",
            "business_line": "training",
            "business_group": "大学",
            "platform": "抖音",
            "sha256": source_sha,
        }],
    }, ensure_ascii=False), encoding="utf-8")
    remote_root = tmp_path / "remote/releases"
    monkeypatch.setattr(transfer, "REMOTE_RELEASE_ROOT", str(remote_root))
    result = _prepare(paired_workspace, tmp_path / "bundle")
    assert "advertising_manifest" not in result["manifest"]
    release_root = remote_root / "daily-20261104_fixture_transfer/foundation"
    with tarfile.open(result["bundle_path"], "r:") as archive:
        fee_manifest = json.load(archive.extractfile("workspace/Input/AdvertisingCosts/sources.json"))
        source_path = fee_manifest["sources"][0]["path"]
        assert source_path.startswith("assets/")
        for member in archive.getmembers()[1:]:
            relative = Path(member.name).relative_to("workspace")
            destination = release_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.extractfile(member).read())
    from dashboard_product.management.advertising_sources import load_sources
    parsed = load_sources(release_root / "Input/AdvertisingCosts/sources.json")
    assert parsed["rows"][0]["amount"] == 12.34


def test_bundle_rejects_unpaired_snapshot_ids(paired_workspace: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit training Snapshot"):
        prepare_bundle(
            paired_workspace,
            {"bi": "snapshot_bi_operations_20261103_old", "study_abroad": ABROAD_ID},
            "run_shadow_daily_20261104_fixture_transfer",
            AS_OF,
            tmp_path / "bundle",
            release_id="daily-20261104_fixture_transfer",
        )


def test_bundle_rejects_changed_snapshot_artifact(paired_workspace: Path, tmp_path: Path) -> None:
    warehouse = paired_workspace / "Work/Runs/run_bi_operations_20261104_fixture/data/snapshots" / BI_ID / "warehouse.duckdb"
    warehouse.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Snapshot artifact hash or size does not match"):
        _prepare(paired_workspace, tmp_path / "bundle")
