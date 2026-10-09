from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest

from dashboard_product.management import study_abroad_facts
from dashboard_product.management.study_abroad_facts import load_study_abroad_facts
from tests.data_acquisition import test_study_abroad_facts as facts_fixtures


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_prepared_hashes(path: Path, hashes: list[str]) -> None:
    book = openpyxl.Workbook()
    book.remove(book.active)
    for kind in ("resources", "contracts", "languages"):
        sheet = book.create_sheet(kind)
        sheet.append(["origin_sha256"])
        for value in hashes:
            sheet.append([value])
    book.save(path)
    book.close()


def _set_manifest_prepared_sha(paths: dict) -> None:
    manifest_path = Path(paths["snapshot_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"][0]["sha256"] = _sha256(Path(paths["prepared_source"]))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _workspace_with_origins(root: Path, origin_hashes: list[str]) -> dict:
    paths = facts_fixtures._make_workspace(root)
    _write_prepared_hashes(Path(paths["prepared_source"]), origin_hashes)
    _set_manifest_prepared_sha(paths)
    return paths


def _query_rows(origin_hashes: list[str]) -> list[dict]:
    rows = []
    for index, source_hash in enumerate(origin_hashes, start=1):
        rows.append(facts_fixtures._fact_row(
            fact_type="resource",
            fact_id=f"resources:raw-{index}",
            business_line="study_abroad",
            event_date="2026-09-15",
            segment_id="study_abroad_online",
            resource_id=f"R-{index}",
            owner="线上甲",
            source_sha256=source_hash,
            origin_filename=f"raw-{index}.xlsx",
            origin_sheet="资源",
            origin_row_number=index + 1,
        ))
    return rows


def _load_facts_with_rows(paths: dict, rows: list[dict]) -> dict:
    columns = list(rows[0])
    query_data = {"columns": columns, "rows": [[row.get(key) for key in columns] for row in rows]}
    response = {
        "schema_version": "controlled_query_result.v2",
        "status": "passed",
        "run_id": facts_fixtures.RUN_ID,
        "snapshot_id": facts_fixtures.SNAPSHOT_ID,
    }
    decisions = {"company_id": facts_fixtures.COMPANY_ID, "candidates": []}
    with (
        patch.object(study_abroad_facts, "DECISIONS_PATH", Path(paths["decisions"])),
        patch.object(study_abroad_facts, "load_decisions", return_value=decisions),
        patch.object(study_abroad_facts, "load_work_order_reference", return_value=None),
        patch.object(study_abroad_facts, "query_sample", return_value=response),
        patch.object(study_abroad_facts, "_validate_query_response", return_value=query_data),
        patch.object(
            study_abroad_facts, "_channel_result",
            return_value=("网络资源", "店铺类", "matched_existing", "synthetic"),
        ),
        patch.object(study_abroad_facts, "_resolve_line", return_value=None),
    ):
        return load_study_abroad_facts(
            workspace=Path(paths["workspace"]),
            snapshot_id=facts_fixtures.SNAPSHOT_ID,
            run_id=facts_fixtures.RUN_ID,
            as_of_date="2026-10-01",
        )


def test_facts_accept_multiple_prepared_origin_hashes_distinct_from_pointer_hash(tmp_path: Path) -> None:
    first_origin = "a" * 64
    second_origin = "b" * 64
    paths = _workspace_with_origins(tmp_path / "valid", [first_origin, second_origin])
    pointer = json.loads(Path(paths["pointer"]).read_text(encoding="utf-8"))
    assert pointer["source_sha256"] != first_origin
    assert pointer["source_sha256"] != second_origin

    result = _load_facts_with_rows(paths, _query_rows([first_origin, second_origin]))

    assert {fact["source_sha256"] for fact in result["facts"]} == {first_origin, second_origin}
    assert result["coverage"]["source_sha256"] == pointer["source_sha256"]


def test_facts_reject_query_row_with_origin_hash_outside_prepared_source_whitelist(tmp_path: Path) -> None:
    first_origin = "a" * 64
    second_origin = "b" * 64
    paths = _workspace_with_origins(tmp_path / "forged-row", [first_origin, second_origin])

    with pytest.raises(ValueError, match="不属于当前Snapshot冻结规范表"):
        _load_facts_with_rows(paths, _query_rows([first_origin, "c" * 64]))


def test_malformed_prepared_origin_hash_is_rejected(tmp_path: Path) -> None:
    paths = _workspace_with_origins(tmp_path / "malformed", ["not-a-sha256"])

    with pytest.raises(ValueError, match="规范表逐行来源SHA无效"):
        study_abroad_facts._snapshot_sources(
            Path(paths["workspace"]),
            facts_fixtures.SNAPSHOT_ID,
            facts_fixtures.COMPANY_ID,
        )


def test_prepared_source_mutation_fails_snapshot_manifest_sha_check(tmp_path: Path) -> None:
    paths = _workspace_with_origins(tmp_path / "mutated-source", ["a" * 64, "b" * 64])
    prepared = Path(paths["prepared_source"])
    prepared.write_bytes(prepared.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="Snapshot规范化来源SHA与source_lineage不一致"):
        study_abroad_facts._snapshot_sources(
            Path(paths["workspace"]),
            facts_fixtures.SNAPSHOT_ID,
            facts_fixtures.COMPANY_ID,
        )
