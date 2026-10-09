from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
from copy import copy
from unittest.mock import patch

import openpyxl
import pytest

from dashboard_product.management.study_abroad_facts import _snapshot_sources
from dashboard_product.management.study_abroad_query import query_sample
from data_acquisition.jobs import build_study_abroad_warehouse
from data_acquisition.jobs import study_abroad_legacy
from data_acquisition.jobs.study_abroad_snapshot_history import load_normalized_history
from data_platform.query.evidence import read_query_result
from tests.data_acquisition import test_study_abroad_facts as facts_fixtures
from tests.data_acquisition import test_study_abroad_legacy as legacy_fixtures
from tests.data_acquisition import test_study_abroad_warehouse as warehouse_fixtures


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workspace(root: Path) -> tuple[Path, Path, Path]:
    workspace = root / "workspace"
    warehouse_fixtures._write_bi_workspace(workspace)
    people_path, abroad_people_path = warehouse_fixtures._write_rosters(root)
    return workspace, people_path, abroad_people_path


def _legacy_workbooks(root: Path) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    june = root / legacy_fixtures.JUNE
    legacy_fixtures._june_book(june)
    book = openpyxl.load_workbook(june)
    crm = book["crm"]
    crm.append(["第二条无CRM编号资源", datetime(2026, 6, 8), "美国", "高中"])
    crm["A4"].fill = copy(crm["A3"].fill)
    book.save(june)
    book.close()

    july = root / legacy_fixtures.JULY
    legacy_fixtures._july_book(july, date_conflict=False)
    book = openpyxl.load_workbook(july)
    book["91 (核算)"]["A2"] = "R-JULY"
    contracts = book["留学签约 (核算)"]
    contracts["B2"] = "C-JULY"
    contracts.append([
        "REC-JULY-2", "C-JULY-2", datetime(2026, 7, 10), 1000,
        "合成甲", "线上组", None, "合成客户",
    ])
    languages = book["语培签约 (核算)"]
    languages["C2"] = "合成客户"
    languages["C3"] = "合成客户"
    book.save(july)
    book.close()

    august = root / legacy_fixtures.AUGUST
    legacy_fixtures._august_book(august)
    book = openpyxl.load_workbook(august)
    resources = book["资源"]
    resources["A3"] = datetime(2026, 8, 6)
    resources["B3"] = "R-AUG"
    resources["D3"] = "U-AUG"
    resources["E3"] = "线上组"
    resources["F3"] = "合成甲"
    resources["G3"] = "留学"
    contracts = book["留学签约"]
    contracts["A3"] = "REC-AUG"
    contracts["B3"] = "C-AUG"
    book.save(august)
    book.close()
    return [june, july, august]


def _standard_month_rows(
    month: str,
    *,
    owner: str,
    resource_id: str,
    contract_id: str,
    customer_id: str,
    contract_amount: int,
    work_order_id: str,
    student_id: str,
    language_amount: int,
) -> dict[str, list[dict[str, object]]]:
    records = {
        "资源": [warehouse_fixtures._resource(resource_id, owner)],
        "留学签约": [warehouse_fixtures._contract(contract_id, customer_id, owner, contract_amount)],
        "小语种签约": [warehouse_fixtures._language(work_order_id, student_id, owner, language_amount)],
    }
    records["资源"][0]["分单日期"] = date.fromisoformat(f"{month}-10")
    records["留学签约"][0]["归档月份"] = month
    records["留学签约"][0]["归档日期"] = date.fromisoformat(f"{month}-11")
    records["小语种签约"][0]["业务日期"] = date.fromisoformat(f"{month}-12")
    return records


def _write_current(path: Path, months: list[dict]) -> None:
    records = {"资源": [], "留学签约": [], "小语种签约": []}
    for item in months:
        month_records = _standard_month_rows(**item)
        for kind in records:
            records[kind].extend(month_records[kind])
    warehouse_fixtures._write_workbook(path, records)
    book = openpyxl.load_workbook(path)
    mapping = book["筛选项"]
    mapping.append(["合成甲", "线上组"])
    book.save(path)
    book.close()


def _build(
    *,
    workspace: Path,
    people_path: Path,
    abroad_people_path: Path,
    source_file: Path,
    run_id: str,
    snapshot_id: str,
    through_date: str,
    legacy_files: list[Path] | None = None,
    history_snapshot_id: str | None = None,
    refresh_months: list[str] | None = None,
) -> dict:
    return build_study_abroad_warehouse.build(
        workspace=workspace,
        source_file=source_file,
        run_id=run_id,
        snapshot_id=snapshot_id,
        through_date=through_date,
        people_path=people_path,
        abroad_people_path=abroad_people_path,
        legacy_files=legacy_files or [],
        history_snapshot_id=history_snapshot_id,
        refresh_months=refresh_months or [],
    )


def _query_rows(
    workspace: Path,
    *,
    snapshot_id: str,
    run_id: str,
    query_name: str,
    start_date: str = "2026-06-01",
    end_date: str = "2026-11-01",
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


def _month(row: dict) -> str | None:
    value = row.get("event_date")
    return value[:7] if isinstance(value, str) and len(value) >= 7 else None


def _assert_origin(row: dict, source_file: Path, sheet: str, row_number: int) -> None:
    assert row["origin_sha256"] == _sha256(source_file)
    assert row["origin_filename"] == source_file.name
    assert row["origin_sheet"] == sheet
    assert str(row["origin_row_number"]) == str(row_number)


def _install_product_context(root: Path, workspace: Path) -> None:
    fixtures = facts_fixtures._make_workspace(root)
    bridge = json.loads(Path(fixtures["bridge"]).read_text(encoding="utf-8"))
    workspace_config = json.loads((workspace / "Work" / "workspace.json").read_text(encoding="utf-8"))
    bridge["company_id"] = workspace_config["company_id"]
    bridge_path = workspace / "Work" / "Bridge" / "reference.json"
    bridge_path.parent.mkdir(parents=True, exist_ok=True)
    bridge_path.write_text(json.dumps(bridge, ensure_ascii=False), encoding="utf-8")

    for key, destination in (
        ("reference", workspace / "Input" / "Reference" / "留学-FY26-资源表.xlsx"),
        ("decisions", workspace / "config" / "study_abroad_channel_decisions.json"),
    ):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(fixtures[key]), destination)


def _seed_first_import(root: Path) -> tuple[Path, dict, list[Path], Path]:
    workspace, people_path, abroad_people_path = _workspace(root)
    legacy_files = _legacy_workbooks(root / "legacy")
    current = root / "current-sep-oct.xlsx"
    _write_current(current, [
        {
            "month": "2026-09", "owner": "合成甲", "resource_id": "R-SEP",
            "contract_id": "C-SEP", "customer_id": "U-SEP", "contract_amount": 150,
            "work_order_id": "L-SEP", "student_id": "S-SEP", "language_amount": 50,
        },
        {
            "month": "2026-10", "owner": "线上甲", "resource_id": "R-OCT",
            "contract_id": "C-OCT", "customer_id": "U-OCT", "contract_amount": 200,
            "work_order_id": "L-OCT", "student_id": "S-OCT", "language_amount": 20,
        },
    ])
    built = _build(
        workspace=workspace,
        people_path=people_path,
        abroad_people_path=abroad_people_path,
        source_file=current,
        legacy_files=legacy_files,
        refresh_months=["2026-09", "2026-10"],
        run_id="run_study_abroad_legacy_seed",
        snapshot_id="snapshot_study_abroad_legacy_seed",
        through_date="2026-10-31",
    )
    return workspace, built, legacy_files, current


def test_one_time_legacy_import_keeps_june_lineage_and_distinct_missing_id_resources(tmp_path: Path) -> None:
    workspace, built, legacy_files, current = _seed_first_import(tmp_path)
    history = load_normalized_history(
        workspace, built["snapshot_id"], "run_study_abroad_legacy_table_read",
    )
    tables = history["tables"]
    june = legacy_files[0]

    june_crm_rows = [
        row for row in tables["resources"]
        if row["origin_filename"] == june.name and row["origin_sheet"] == "crm"
        and row.get("resource_id") is None
    ]
    assert len(june_crm_rows) == 2
    assert {row["origin_row_number"] for row in june_crm_rows} == {"3", "4"}
    assert len({row["record_key"] for row in june_crm_rows}) == 2
    assert all(row["record_key"].endswith((":crm:3", ":crm:4")) for row in june_crm_rows)

    lineage_path = workspace / built["source_lineage"]
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    frozen_by_name = {item["filename"]: item for item in lineage["origin_files"]}
    assert set(frozen_by_name) == {path.name for path in [*legacy_files, current]}
    run_root = lineage_path.parent
    for original in [*legacy_files, current]:
        item = frozen_by_name[original.name]
        frozen = run_root / item["path"]
        assert item["sha256"] == _sha256(original)
        assert _sha256(frozen) == _sha256(original)
        assert item["source_sheets"]
    june_contract = next(row for row in tables["contracts"] if row["contract_id"] == "C-1")
    _assert_origin(june_contract, june, "留学签约", 3)
    june_language = next(row for row in tables["languages"] if row["origin_filename"] == june.name)
    _assert_origin(june_language, june, "语培签约", 3)
    july = legacy_files[1]
    july_contract = next(row for row in tables["contracts"] if row["contract_id"] == "C-JULY")
    _assert_origin(july_contract, july, "留学签约 (核算)", 2)
    july_language = next(row for row in tables["languages"] if row["origin_filename"] == july.name)
    _assert_origin(july_language, july, "语培签约 (核算)", 2)
    august = legacy_files[2]
    august_resource = next(row for row in tables["resources"] if row.get("resource_id") == "R-AUG")
    _assert_origin(august_resource, august, "资源", 3)
    august_contract = next(row for row in tables["contracts"] if row["contract_id"] == "C-AUG")
    _assert_origin(august_contract, august, "留学签约", 3)
    september_contract = next(row for row in tables["contracts"] if row["contract_id"] == "C-SEP")
    _assert_origin(september_contract, current, "留学签约", 2)
    october_contract = next(row for row in tables["contracts"] if row["contract_id"] == "C-OCT")
    _assert_origin(october_contract, current, "留学签约", 3)

    monthly = _query_rows(
        workspace,
        snapshot_id=built["snapshot_id"],
        run_id="run_study_abroad_legacy_monthly",
        query_name="monthly",
    )
    totals = {
        row["month"]: row for row in monthly
        if row["scope"] == "total" and row["segment_id"] == "total"
    }
    assert Decimal(str(totals["2026-06"]["gross_signing_amount"])) == Decimal("1500.00")
    assert totals["2026-06"]["study_abroad_signed_customers"] == 1
    assert totals["2026-06"]["small_language_signed_customers"] == 1
    assert Decimal(str(totals["2026-07"]["gross_signing_amount"])) == Decimal("3700.00")
    assert totals["2026-07"]["study_abroad_signed_customers"] == 1
    assert totals["2026-07"]["small_language_signed_customers"] == 1
    assert totals["2026-07"]["signed_customer_count"] is None
    assert totals["2026-07"]["signed_customer_count_status"] == "cross_system_unaligned"

    july_contracts = [row for row in tables["contracts"] if row["contract_id"] in {"C-JULY", "C-JULY-2"}]
    july_languages = [row for row in tables["languages"] if row["event_date"].startswith("2026-07")]
    assert len(july_contracts) == 2
    assert len({row["customer_key"] for row in july_contracts}) == 1
    assert {row["customer_key_basis"] for row in july_contracts} == {"name"}
    assert len(july_languages) == 2
    assert len({row["customer_key"] for row in july_languages}) == 1
    assert {row["customer_key_basis"] for row in july_languages} == {"name"}
    assert july_contracts[0]["customer_key"].startswith("contracts:name:")
    assert july_languages[0]["customer_key"].startswith("languages:name:")
    assert july_contracts[0]["customer_key"] != july_languages[0]["customer_key"]


def test_normalized_history_reuse_replaces_october_without_reparsing_legacy_and_product_reads_its_receipts(
    tmp_path: Path,
) -> None:
    workspace, first, legacy_files, _current = _seed_first_import(tmp_path)
    _install_product_context(tmp_path / "facts-product-fixtures", workspace)
    old = load_normalized_history(
        workspace, first["snapshot_id"], "run_study_abroad_old_snapshot_tables",
    )["tables"]
    bi_before = warehouse_fixtures._bi_state(workspace)
    revised_current = tmp_path / "current-october-revised.xlsx"
    _write_current(revised_current, [{
        "month": "2026-10", "owner": "线上甲", "resource_id": "R-OCT",
        "contract_id": "C-OCT", "customer_id": "U-OCT", "contract_amount": 450,
        "work_order_id": "L-OCT", "student_id": "S-OCT", "language_amount": 80,
    }])
    with patch.object(
        study_abroad_legacy, "read_legacy_sources",
        side_effect=AssertionError("normalized Snapshot reuse must not reopen legacy workbooks"),
    ) as legacy_reader:
        second = _build(
            workspace=workspace,
            people_path=tmp_path / "fixtures" / "people.json",
            abroad_people_path=tmp_path / "fixtures" / "abroad_people.json",
            source_file=revised_current,
            history_snapshot_id=first["snapshot_id"],
            refresh_months=["2026-10"],
            run_id="run_study_abroad_reuse_october",
            snapshot_id="snapshot_study_abroad_reuse_october",
            through_date="2026-10-31",
        )
        legacy_reader.assert_not_called()

    assert warehouse_fixtures._bi_state(workspace) == bi_before
    current = load_normalized_history(
        workspace, second["snapshot_id"], "run_study_abroad_reused_snapshot_tables",
    )["tables"]
    stable_columns = {
        "record_key", "resource_id", "contract_id", "work_order_id",
        "customer_name", "customer_key", "customer_key_basis", "amount",
        "event_date", "origin_sha256", "origin_filename", "origin_sheet",
        "origin_row_number", "owner", "source_owner", "source_group",
        "market_group", "segment_id", "team_eligible", "market_eligible",
        "personal_eligible", "roster_group", "roster_status",
    }
    for kind in ("resources", "contracts", "languages"):
        old_rows = {
            row["record_key"]: {key: row.get(key) for key in stable_columns}
            for row in old[kind] if _month(row) != "2026-10"
        }
        kept_rows = {
            row["record_key"]: {key: row.get(key) for key in stable_columns}
            for row in current[kind] if _month(row) != "2026-10"
        }
        assert kept_rows == old_rows

    october_contracts = [row for row in current["contracts"] if row["contract_id"] == "C-OCT"]
    october_languages = [row for row in current["languages"] if row["work_order_id"] == "L-OCT"]
    assert len(october_contracts) == 1
    assert october_contracts[0]["amount"] == "450.00"
    assert len(october_languages) == 1
    assert october_languages[0]["amount"] == "80.00"
    monthly = _query_rows(
        workspace,
        snapshot_id=second["snapshot_id"],
        run_id="run_study_abroad_reused_october_monthly",
        query_name="monthly",
        start_date="2026-10-01",
        end_date="2026-11-01",
    )
    october_total = next(row for row in monthly if row["scope"] == "total" and row["segment_id"] == "total")
    assert Decimal(str(october_total["gross_signing_amount"])) == Decimal("530.00")

    lineage_path = workspace / second["source_lineage"]
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    parent_metadata = lineage["normalized_history"]
    assert parent_metadata["source_snapshot_id"] == first["snapshot_id"]
    assert parent_metadata["source_run_id"] == first["run_id"]
    assert set(parent_metadata["query_receipts"]) == {"resources", "contracts", "languages"}
    assert parent_metadata["pointer_sha256"]
    assert parent_metadata["snapshot_manifest_sha256"]
    assert parent_metadata["source_lineage_sha256"]

    context = _snapshot_sources(workspace, second["snapshot_id"], "company_bi_keep_fixture")
    assert context["lineage"]["normalized_history"]["source_snapshot_id"] == first["snapshot_id"]
    assert any("历史查询回执" in str(path) for path in context["source_paths"])
    assert legacy_files
