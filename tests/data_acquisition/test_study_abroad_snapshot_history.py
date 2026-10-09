from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from data_acquisition.jobs import build_study_abroad_warehouse
from data_acquisition.jobs.study_abroad_snapshot_history import (
    load_normalized_history,
    replace_normalized_months,
)
from data_platform.query.evidence import resolve_file, verify_receipt
from tests.data_acquisition import test_study_abroad_warehouse as warehouse_fixtures


KINDS = ("resources", "contracts", "languages")


def _row(kind: str, event_date: str, *, label: str, **values) -> dict:
    return {
        "event_date": event_date,
        "fact_id": f"{kind}:{label}",
        "origin_sha256": f"{label:0<64}"[:64],
        "origin_filename": f"{label}.xlsx",
        "origin_sheet": {"resources": "资源", "contracts": "留学签约", "languages": "小语种签约"}[kind],
        "origin_row_number": 2,
        "owner": f"Owner {label}",
        "market_group": "线上组",
        "team_eligible": "true",
        "market_eligible": "true",
        "personal_eligible": "false",
        **values,
    }


def test_replaces_only_explicit_months_and_preserves_row_metadata() -> None:
    history = {
        kind: [
            _row(kind, "2026-09-15", label=f"{kind}-sep"),
            _row(kind, "2026-10-05", label=f"{kind}-old-oct", owner="Historical Owner"),
        ]
        for kind in KINDS
    }
    new = {
        kind: [
            _row(kind, "2026-10-20", label=f"{kind}-new-oct", owner="Current Owner"),
            _row(kind, "2026-11-01", label=f"{kind}-unrequested"),
        ]
        for kind in KINDS
    }
    history_before = {kind: [dict(row) for row in rows] for kind, rows in history.items()}

    merged = replace_normalized_months(history, new, ["2026-10"])

    for kind in KINDS:
        assert [row["fact_id"] for row in merged[kind]] == [f"{kind}:{kind}-sep", f"{kind}:{kind}-new-oct"]
        current_october = merged[kind][1]
        assert current_october["owner"] == "Current Owner"
        assert current_october["origin_sha256"] == new[kind][0]["origin_sha256"]
        assert current_october["origin_filename"] == new[kind][0]["origin_filename"]
        assert current_october["origin_sheet"] == new[kind][0]["origin_sheet"]
        assert current_october["origin_row_number"] == new[kind][0]["origin_row_number"]
        assert current_october["team_eligible"] == new[kind][0]["team_eligible"]
        assert current_october["market_eligible"] == new[kind][0]["market_eligible"]
        assert current_october["personal_eligible"] == new[kind][0]["personal_eligible"]
    assert history == history_before


def test_empty_refresh_month_clears_old_rows_and_does_not_deduplicate_equal_language_rows() -> None:
    history = {
        "resources": [_row("resources", "2026-10-10", label="old-resource")],
        "contracts": [_row("contracts", "2026-10-11", label="old-contract")],
        "languages": [
            _row("languages", "2026-10-12", label="old-language-1", amount="500.00", student_id="S-1"),
            _row("languages", "2026-10-12", label="old-language-2", amount="500.00", student_id="S-1"),
        ],
    }

    cleared = replace_normalized_months(history, {kind: [] for kind in KINDS}, ["2026-10"])
    assert cleared == {kind: [] for kind in KINDS}

    current = {
        kind: [] for kind in KINDS
    }
    current["languages"] = [
        _row("languages", "2026-10-12", label="same-value-1", amount="500.00", student_id="S-1"),
        _row("languages", "2026-10-12", label="same-value-2", amount="500.00", student_id="S-1"),
    ]
    current["languages"][1]["origin_row_number"] = 3
    merged = replace_normalized_months(history, current, ["2026-10"])
    assert len(merged["languages"]) == 2
    assert [row["amount"] for row in merged["languages"]] == ["500.00", "500.00"]
    assert [row["origin_row_number"] for row in merged["languages"]] == [2, 3]


def _seed_normalized_snapshot(root: Path) -> tuple[Path, dict]:
    workspace = root / "workspace"
    warehouse_fixtures._write_bi_workspace(workspace)
    people_path, abroad_people_path = warehouse_fixtures._write_rosters(root)
    source_file = root / "normalized-source.xlsx"
    warehouse_fixtures._write_workbook(source_file, warehouse_fixtures._base_records())
    built = build_study_abroad_warehouse.build(
        workspace=workspace,
        source_file=source_file,
        run_id="run_study_abroad_snapshot_history_seed",
        snapshot_id="snapshot_study_abroad_snapshot_history_seed",
        through_date="2026-09-30",
        people_path=people_path,
        abroad_people_path=abroad_people_path,
    )
    return workspace, built


def test_reads_explicit_snapshot_through_controlled_queries_without_changing_bi_state(tmp_path: Path) -> None:
    workspace, built = _seed_normalized_snapshot(tmp_path)
    bi_before = warehouse_fixtures._bi_state(workspace)
    run_id = "run_study_abroad_normalized_history_read"

    result = load_normalized_history(workspace, built["snapshot_id"], run_id)

    assert warehouse_fixtures._bi_state(workspace) == bi_before
    assert {kind: len(rows) for kind, rows in result["tables"].items()} == {
        "resources": 9,
        "contracts": 16,
        "languages": 5,
    }
    resource = next(row for row in result["tables"]["resources"] if row["resource_id"] == "1001")
    assert resource["owner"] == "线下甲"
    assert resource["segment_id"] == "study_abroad_offline"
    assert resource["team_eligible"] == "true"
    assert resource["personal_eligible"] == "true"
    assert resource["origin_sheet"] == "资源"
    assert resource["origin_filename"] == "normalized-source.xlsx"

    pointer_path = workspace / "Work" / "StudyAbroad" / "current.json"
    pointer_bytes = pointer_path.read_bytes()
    pointer = json.loads(pointer_bytes)
    manifest_path = Path(built["warehouse"]).parent / "snapshot_manifest.json"
    lineage_path = workspace / pointer["source_lineage"]
    metadata = result["source_metadata"]
    assert metadata["source_snapshot_id"] == built["snapshot_id"]
    assert metadata["source_run_id"] == built["run_id"]
    assert metadata["company_id"] == "company_bi_keep_fixture"
    assert metadata["pointer_sha256"] == hashlib.sha256(pointer_bytes).hexdigest()
    assert metadata["warehouse"] == str(Path(built["warehouse"]).resolve())
    assert metadata["snapshot_manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert metadata["source_lineage_sha256"] == hashlib.sha256(lineage_path.read_bytes()).hexdigest()
    assert set(metadata["query_receipts"]) == set(KINDS)

    output_root = workspace / "Output" / "StudyAbroad" / "历史查询回执"
    for kind in KINDS:
        query_run_id = f"{run_id}_history_{kind}"
        assert metadata["query_run_ids"][kind] == query_run_id
        receipt_path = resolve_file(output_root / query_run_id, metadata["query_receipts"][kind])
        receipt, _ = verify_receipt(receipt_path)
        assert receipt["snapshot_id"] == built["snapshot_id"]
        assert receipt["referenced_source_ids"] == ["study_abroad_market"]
        assert receipt["referenced_relations"] == [f"landing.study_abroad_market__{kind}"]

    with pytest.raises(ValueError, match="显式snapshot_id必须匹配当前留学Snapshot指针"):
        load_normalized_history(workspace, "snapshot_not_current", run_id)


def test_snapshot_company_must_match_workspace_company(tmp_path: Path) -> None:
    workspace, built = _seed_normalized_snapshot(tmp_path)
    config_path = workspace / "Work" / "workspace.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["company_id"] = "another_company"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="客户身份不匹配"):
        load_normalized_history(
            workspace,
            built["snapshot_id"],
            "run_study_abroad_company_mismatch",
        )
