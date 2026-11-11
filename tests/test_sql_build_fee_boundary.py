"""Opt-in real-workspace regression for the SQL builder's independent fee boundary."""
import json
import os
from pathlib import Path

import duckdb
import pytest

from data_platform.query.evidence import resolve_file
from dashboard_product.shadow_bi.sql_warehouse import build, expenses


def test_fee_manifest_change_does_not_block_business_build(tmp_path, monkeypatch):
    workspace_value = os.environ.get("SHADOW_BI_SQL_TEST_WORKSPACE")
    baseline_value = os.environ.get("SHADOW_BI_SQL_TEST_BASELINE")
    if workspace_value is None and baseline_value is None:
        pytest.skip("requires explicit SHADOW_BI_SQL_TEST_WORKSPACE and SHADOW_BI_SQL_TEST_BASELINE")
    if workspace_value is None or baseline_value is None:
        pytest.fail("workspace and baseline must both be explicitly configured")
    if not workspace_value.strip() or not baseline_value.strip():
        pytest.fail("workspace and baseline paths must be non-empty")

    workspace = Path(workspace_value).expanduser().resolve()
    baseline_dir = Path(baseline_value).expanduser().resolve()
    if not workspace.is_dir():
        pytest.fail("SHADOW_BI_SQL_TEST_WORKSPACE must name an existing directory")
    if not baseline_dir.is_dir():
        pytest.fail("SHADOW_BI_SQL_TEST_BASELINE must name an existing candidate directory")
    temp_root = tmp_path.resolve()
    if temp_root.is_relative_to(workspace) or temp_root.is_relative_to(baseline_dir):
        pytest.fail("pytest temporary directory must be outside the workspace and baseline")

    baseline_path = baseline_dir / "candidate.json"
    if not baseline_path.is_file():
        pytest.fail("baseline directory must contain candidate.json")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert baseline["schema_version"] == "sql_warehouse_candidate.v1"
    training_snapshot = baseline["snapshots"]["training"]
    abroad_snapshot = baseline["snapshots"]["abroad"]
    as_of_date = baseline["as_of_date"]
    company_id = baseline["company_id"]

    workspace_identity = json.loads((workspace / "Work/workspace.json").read_text(encoding="utf-8"))
    abroad_pointer = json.loads((workspace / "Work/StudyAbroad/current.json").read_text(encoding="utf-8"))
    assert workspace_identity["company_id"] == company_id
    assert workspace_identity["current_snapshot_id"] == training_snapshot
    assert abroad_pointer["snapshot_id"] == abroad_snapshot

    source_manifest = workspace / "Input/AdvertisingCosts/sources.json"
    if not source_manifest.is_file():
        pytest.fail("workspace must contain a valid registered fee manifest")
    manifest_copy = json.loads(source_manifest.read_text(encoding="utf-8-sig"))
    assert isinstance(manifest_copy.get("sources"), list)
    for entry in manifest_copy["sources"]:
        source_path = Path(entry["path"])
        if not source_path.is_absolute():
            entry["path"] = str((source_manifest.parent / source_path).resolve())
    confirmation = manifest_copy.get("business_scope_confirmation")
    if isinstance(confirmation, dict) and isinstance(confirmation.get("evidence"), dict):
        evidence_path = Path(confirmation["evidence"]["path"])
        if not evidence_path.is_absolute():
            confirmation["evidence"]["path"] = str((source_manifest.parent / evidence_path).resolve())
    fee_manifest = tmp_path / "sources.json"
    fee_manifest.write_text(json.dumps(manifest_copy, ensure_ascii=False), encoding="utf-8")
    assert expenses.parse_manifest(fee_manifest, candidate=False)["configured"] is True

    original_refresh = expenses.refresh_from_manifest

    def invalidate_manifest_then_refresh(connection, path, import_id):
        assert Path(path).resolve() == fee_manifest.resolve()
        Path(path).write_text("{", encoding="utf-8")
        return original_refresh(connection, path, import_id)

    monkeypatch.setattr(expenses, "refresh_from_manifest", invalidate_manifest_then_refresh)

    output_dir = tmp_path / "candidate"
    candidate = build.build_local(
        workspace=workspace,
        output_dir=output_dir,
        batch_id=f"run_sql_fee_boundary_{as_of_date.replace('-', '')}",
        training_snapshot=training_snapshot,
        abroad_snapshot=abroad_snapshot,
        as_of_date=as_of_date,
        config_root=Path(__file__).resolve().parents[1],
        expense_baseline=baseline_dir,
        advertising_manifest=fee_manifest,
        source_order_receipts=baseline["source_order_receipts"],
    )

    assert json.loads((output_dir / "candidate.json").read_text(encoding="utf-8")) == json.loads(
        json.dumps(candidate, ensure_ascii=False, default=str)
    )
    assert candidate["status"] == "built_unreconciled"
    assert candidate["expenses"]["status"] == "failed"
    assert candidate["expenses"]["retained_rows"] > 0
    assert fee_manifest.read_text(encoding="utf-8") == "{"

    baseline_database = resolve_file(baseline_dir, baseline["database"])
    candidate_database = resolve_file(output_dir, candidate["database"])
    expense_tables = {"expense_rows": "row_key", "expense_sources": "summary_key"}
    with duckdb.connect(str(baseline_database), read_only=True) as con:
        baseline_fees = {
            table: con.execute(f"SELECT * FROM expenses.{table} ORDER BY {key}").fetchall()
            for table, key in expense_tables.items()
        }
    with duckdb.connect(str(candidate_database), read_only=True) as con:
        candidate_fees = {
            table: con.execute(f"SELECT * FROM expenses.{table} ORDER BY {key}").fetchall()
            for table, key in expense_tables.items()
        }
    assert baseline_fees["expense_rows"]
    assert baseline_fees["expense_sources"]
    assert candidate_fees == baseline_fees

    baseline_preview_path = resolve_file(baseline_dir, baseline["notification_preview"])
    candidate_preview_path = resolve_file(output_dir, candidate["notification_preview"])
    baseline_preview = json.loads(baseline_preview_path.read_text(encoding="utf-8"))
    candidate_preview = json.loads(candidate_preview_path.read_text(encoding="utf-8"))
    assert len(baseline_preview["messages"]) == 8
    assert candidate_preview == baseline_preview
