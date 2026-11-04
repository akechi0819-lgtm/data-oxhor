from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import openpyxl
import pytest

from dashboard_product.management.study_abroad_facts import load_study_abroad_facts
from dashboard_product.management.study_abroad_query import query_sample
from data_acquisition.jobs import build_study_abroad_warehouse
from data_platform.query.evidence import read_query_result
from tests.data_acquisition import test_study_abroad_facts as facts_fixtures
from tests.data_acquisition import test_study_abroad_warehouse as warehouse_fixtures


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workspace(root: Path) -> tuple[Path, Path, Path]:
    workspace = root / "workspace"
    warehouse_fixtures._write_bi_workspace(workspace)
    people_path, abroad_people_path = warehouse_fixtures._write_rosters(root)
    return workspace, people_path, abroad_people_path


def _month_records(
    month: str,
    *,
    owner: str,
    resource_id: str,
    contract_id: str,
    customer_id: str,
    contract_amount: int,
    language_order_id: str,
    student_id: str,
    language_amount: int,
) -> dict[str, list[dict[str, object]]]:
    records = {
        "资源": [warehouse_fixtures._resource(resource_id, owner)],
        "留学签约": [warehouse_fixtures._contract(contract_id, customer_id, owner, contract_amount)],
        "小语种签约": [warehouse_fixtures._language(language_order_id, student_id, owner, language_amount)],
    }
    records["资源"][0]["分单日期"] = date.fromisoformat(f"{month}-10")
    records["留学签约"][0]["归档月份"] = month
    records["留学签约"][0]["归档日期"] = date.fromisoformat(f"{month}-11")
    records["小语种签约"][0]["业务日期"] = date.fromisoformat(f"{month}-12")
    return records


def _resource_only(resource_id: str, owner: str, assignment_date: date) -> dict[str, list[dict[str, object]]]:
    return {
        "资源": [{
            **warehouse_fixtures._resource(resource_id, owner),
            "分单日期": assignment_date,
        }],
        "留学签约": [],
        "小语种签约": [],
    }


def _contract_only(contract: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    return {"资源": [], "留学签约": [contract], "小语种签约": []}


def _build(
    *,
    workspace: Path,
    people_path: Path,
    abroad_people_path: Path,
    current: Path,
    history: list[Path],
    run_id: str,
    snapshot_id: str,
    through_date: str,
    refresh_months: list[str] | None = None,
) -> dict:
    return build_study_abroad_warehouse.build(
        workspace=workspace,
        source_file=current,
        run_id=run_id,
        snapshot_id=snapshot_id,
        through_date=through_date,
        people_path=people_path,
        abroad_people_path=abroad_people_path,
        history_files=history,
        refresh_months=refresh_months or [],
    )


def _query_rows(
    workspace: Path,
    *,
    snapshot_id: str,
    run_id: str,
    query_name: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    response = query_sample(
        workspace=workspace,
        snapshot_id=snapshot_id,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
        query_name=query_name,
    )
    data = read_query_result(response, output_root=workspace / "Output" / "StudyAbroad")
    return [dict(zip(data["columns"], row)) for row in data["rows"]]


def test_monthly_build_retains_september_adds_october_and_freezes_each_source(tmp_path: Path) -> None:
    workspace, people_path, abroad_people_path = _workspace(tmp_path)
    history = tmp_path / "history-september.xlsx"
    current = tmp_path / "current-october.xlsx"
    warehouse_fixtures._write_workbook(
        history,
        _month_records(
            "2026-09", owner="线下甲", resource_id="R-SEP", contract_id="C-SEP",
            customer_id="U-SEP", contract_amount=1200,
            language_order_id="L-SEP", student_id="S-SEP", language_amount=300,
        ),
    )
    warehouse_fixtures._write_workbook(
        current,
        _month_records(
            "2026-10", owner="线上甲", resource_id="R-OCT", contract_id="C-OCT",
            customer_id="U-OCT", contract_amount=2500,
            language_order_id="L-OCT", student_id="S-OCT", language_amount=600,
        ),
    )
    input_hashes = {path: _sha256(path) for path in (history, current)}
    bi_before = warehouse_fixtures._bi_state(workspace)

    built = _build(
        workspace=workspace,
        people_path=people_path,
        abroad_people_path=abroad_people_path,
        current=current,
        history=[history],
        refresh_months=["2026-10"],
        run_id="run_study_abroad_monthly_history",
        snapshot_id="snapshot_study_abroad_monthly_history",
        through_date="2026-10-31",
    )

    monthly_rows = _query_rows(
        workspace,
        snapshot_id=built["snapshot_id"],
        run_id="run_study_abroad_monthly_query",
        query_name="monthly",
        start_date="2026-09-01",
        end_date="2026-11-01",
    )
    totals = {
        row["month"]: row
        for row in monthly_rows
        if row["scope"] == "total" and row["segment_id"] == "total"
    }
    assert Decimal(str(totals["2026-09"]["gross_signing_amount"])) == Decimal("1500.00")
    assert Decimal(str(totals["2026-10"]["gross_signing_amount"])) == Decimal("3100.00")
    assert totals["2026-09"]["resource_count"] == 1
    assert totals["2026-10"]["resource_count"] == 1

    run_root = workspace / "Work" / "StudyAbroad" / "Runs" / built["run_id"]
    lineage = json.loads((run_root / "source_lineage.json").read_text(encoding="utf-8"))
    frozen_by_name = {item["filename"]: item for item in lineage["origin_files"]}
    assert list(frozen_by_name) == ["history-september.xlsx", "current-october.xlsx"]
    for filename, original in (("history-september.xlsx", history), ("current-october.xlsx", current)):
        frozen = run_root / frozen_by_name[filename]["path"]
        assert frozen.is_file()
        assert frozen_by_name[filename]["sha256"] == input_hashes[original]
        assert _sha256(frozen) == input_hashes[original]
        assert frozen_by_name[filename]["source_sheets"] == {
            "resources": "资源",
            "contracts": "留学签约",
            "languages": "小语种签约",
            "group_mapping": "筛选项",
        }
    assert lineage["update_mode"] == "replace_observed_months_preserve_history"
    assert lineage["retained_months"] == {
        "resources": ["2026-09", "2026-10"],
        "contracts": ["2026-09", "2026-10"],
        "languages": ["2026-09", "2026-10"],
    }
    assert lineage["source_hashes"]["source"] == input_hashes[current]
    history_reader = Path(__file__).resolve().parents[2] / "data_acquisition" / "jobs" / "study_abroad_history.py"
    assert lineage["source_hashes"]["history_reader"] == _sha256(history_reader)

    facts = _query_rows(
        workspace,
        snapshot_id=built["snapshot_id"],
        run_id="run_study_abroad_monthly_facts_query",
        query_name="facts",
        start_date="2026-09-01",
        end_date="2026-11-01",
    )
    september_contract = next(row for row in facts if row["fact_id"] == "contracts:C-SEP")
    october_contract = next(row for row in facts if row["fact_id"] == "contracts:C-OCT")
    assert (
        september_contract["origin_filename"],
        september_contract["origin_sheet"],
        september_contract["origin_sha256"],
        september_contract["origin_row_number"],
    ) == ("history-september.xlsx", "留学签约", input_hashes[history], 2)
    assert (
        october_contract["origin_filename"],
        october_contract["origin_sheet"],
        october_contract["origin_sha256"],
        october_contract["origin_row_number"],
    ) == ("current-october.xlsx", "留学签约", input_hashes[current], 2)
    assert {path: _sha256(path) for path in input_hashes} == input_hashes
    assert warehouse_fixtures._bi_state(workspace) == bi_before


def test_cross_month_resource_id_keeps_latest_assignment_and_same_day_conflict_fails(tmp_path: Path) -> None:
    workspace, people_path, abroad_people_path = _workspace(tmp_path / "latest")
    old = tmp_path / "assignment-august.xlsx"
    current = tmp_path / "assignment-september.xlsx"
    warehouse_fixtures._write_workbook(
        old, _resource_only("SHARED-1", "线下甲", date(2026, 8, 25)),
    )
    warehouse_fixtures._write_workbook(
        current, _resource_only("SHARED-1", "线上甲", date(2026, 9, 11)),
    )

    built = _build(
        workspace=workspace,
        people_path=people_path,
        abroad_people_path=abroad_people_path,
        current=current,
        history=[old],
        run_id="run_study_abroad_latest_assignment",
        snapshot_id="snapshot_study_abroad_latest_assignment",
        through_date="2026-09-30",
    )
    assert built["diagnostics"]["superseded_resource_rows"]["resources"] == 1
    facts = _query_rows(
        workspace,
        snapshot_id=built["snapshot_id"],
        run_id="run_study_abroad_latest_assignment_query",
        query_name="facts",
        start_date="2026-08-01",
        end_date="2026-10-01",
    )
    shared = [row for row in facts if row["fact_type"] == "resource" and row["resource_id"] == "SHARED-1"]
    assert len(shared) == 1
    assert shared[0]["event_date"] == "2026-09-11"
    assert shared[0]["owner"] == "线上甲"

    conflict_root = tmp_path / "same-day"
    conflict_workspace, conflict_people, conflict_abroad_people = _workspace(conflict_root)
    same_day_current = conflict_root / "same-day-current.xlsx"
    same_day = date(2026, 9, 11)
    warehouse_fixtures._write_workbook(
        same_day_current,
        {
            "资源": [
                {**warehouse_fixtures._resource("SHARED-2", "线下甲"), "分单日期": same_day},
                {**warehouse_fixtures._resource("SHARED-2", "线上甲"), "分单日期": same_day},
            ],
            "留学签约": [],
            "小语种签约": [],
        },
    )
    with pytest.raises(ValueError, match="同一资源.*冲突"):
        _build(
            workspace=conflict_workspace,
            people_path=conflict_people,
            abroad_people_path=conflict_abroad_people,
            current=same_day_current,
            history=[],
            run_id="run_study_abroad_same_day_conflict",
            snapshot_id="snapshot_study_abroad_same_day_conflict",
            through_date="2026-09-30",
        )
    assert not (conflict_workspace / "Work" / "StudyAbroad" / "current.json").exists()


@pytest.mark.parametrize(
    "source_month",
    [datetime(2026, 9, 1, 0, 0), None, datetime(2026, 8, 1, 0, 0)],
    ids=["matching-datetime", "missing", "mismatched-datetime"],
)
def test_contract_month_comes_from_archive_date(tmp_path: Path, source_month: object) -> None:
    workspace, people_path, abroad_people_path = _workspace(tmp_path / "workspace")
    source = tmp_path / "contract-source-month.xlsx"
    contract = warehouse_fixtures._contract("C-MONTH", "U-MONTH", "线下甲", 100)
    contract["归档月份"] = source_month
    warehouse_fixtures._write_workbook(source, _contract_only(contract))

    built = _build(
        workspace=workspace,
        people_path=people_path,
        abroad_people_path=abroad_people_path,
        current=source,
        history=[],
        run_id="run_study_abroad_contract_month_canonical",
        snapshot_id="snapshot_study_abroad_contract_month_canonical",
        through_date="2026-09-30",
    )
    lineage_path = workspace / built["source_lineage"]
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    prepared = lineage_path.parent / lineage["prepared_file"]
    book = openpyxl.load_workbook(prepared, read_only=True, data_only=True)
    try:
        sheet = book["contracts"]
        values = iter(sheet.values)
        headers = next(values)
        row = next(values)
        assert row[headers.index("month")] == "2026-09"
        assert row[headers.index("event_date")] == "2026-09-12"
    finally:
        book.close()


def test_changed_frozen_history_source_is_rejected_by_facts_reader(tmp_path: Path) -> None:
    paths = facts_fixtures._make_workspace(tmp_path / "facts-workspace")
    workspace = Path(paths["workspace"])
    lineage_path = Path(paths["lineage"])
    run_root = lineage_path.parent
    frozen_history = run_root / "input" / "history" / "000_history.xlsx"
    frozen_history.parent.mkdir(parents=True)
    frozen_history.write_bytes(b"frozen synthetic history workbook")
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    lineage["origin_files"] = [{
        "path": frozen_history.relative_to(run_root).as_posix(),
        "sha256": _sha256(frozen_history),
        "filename": "history.xlsx",
        "source_sheets": {"resources": "资源", "contracts": "留学签约", "languages": "小语种签约"},
    }]
    history_reader = Path(__file__).resolve().parents[2] / "data_acquisition" / "jobs" / "study_abroad_history.py"
    lineage["source_hashes"]["history_reader"] = _sha256(history_reader)
    lineage_path.write_text(json.dumps(lineage, ensure_ascii=False), encoding="utf-8")
    frozen_history.write_bytes(b"tampered history workbook")

    with pytest.raises(ValueError, match="月份原始来源与source_lineage摘要不一致"):
        load_study_abroad_facts(
            workspace=workspace,
            snapshot_id=facts_fixtures.SNAPSHOT_ID,
            run_id="run_study_abroad_modified_history",
            as_of_date="2026-10-01",
        )
