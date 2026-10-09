from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from data_acquisition.jobs.study_abroad_history import read_retained_sources


SHEETS = {
    "resources": "资源",
    "contracts": "留学签约",
    "languages": "小语种签约",
    "group_mapping": "筛选项",
}


class SourceFiles:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.sources: dict[Path, dict] = {}

    def add(
        self,
        name: str,
        *,
        resources: list[dict] | None = None,
        contracts: list[dict] | None = None,
        languages: list[dict] | None = None,
        group_mapping: list[dict] | None = None,
    ) -> Path:
        path = self.directory / name
        contents = f"synthetic workbook: {name}".encode("utf-8")
        path.write_bytes(contents)
        self.sources[path] = {
            "resources": resources or [],
            "contracts": contracts or [],
            "languages": languages or [],
            "group_mapping": group_mapping or [],
            "source_sheets": dict(SHEETS),
            "source_sha256": hashlib.sha256(contents).hexdigest(),
            "source_path": str(path),
        }
        return path


def _resource(row: int, month_date: object, resource_id: str) -> dict:
    return {"source_row_number": row, "date": month_date, "resource_id": resource_id, "owner": "Owner A"}


def _contract(row: int, month_date: object, contract_id: str) -> dict:
    return {"source_row_number": row, "archive_date": month_date, "contract_id": contract_id, "amount": 1000}


def _language(row: int, month_date: object, work_order_id: str = "WO-1") -> dict:
    return {
        "source_row_number": row,
        "date": month_date,
        "work_order_id": work_order_id,
        "student_id": "S-1",
        "amount": 500,
    }


def _read(files: SourceFiles, current: Path, history: list[Path], refresh: list[str]) -> dict:
    with patch(
        "data_acquisition.jobs.study_abroad_history.read_sources",
        side_effect=lambda path: files.sources[Path(path)],
    ):
        return read_retained_sources(current, history, refresh)


def test_keeps_uncovered_september_and_replaces_observed_october_with_lineage(tmp_path: Path) -> None:
    files = SourceFiles(tmp_path)
    september = files.add(
        "history-september.xlsx",
        resources=[_resource(2, date(2026, 9, 5), "R-SEP")],
        contracts=[_contract(2, "2026-09-20", "C-SEP")],
        languages=[_language(2, "2026-09-25T00:00:00", "WO-SEP")],
        group_mapping=[{"source_row_number": 1, "owner": "Old Owner", "source_group": "线上组"}],
    )
    current = files.add(
        "current-october.xlsx",
        resources=[_resource(2, "2026-10-02T10:00:00", "R-OCT")],
        contracts=[_contract(2, date(2026, 10, 12), "C-OCT")],
        languages=[_language(2, date(2026, 10, 15), "WO-OCT")],
        group_mapping=[{"source_row_number": 1, "owner": "Current Owner", "source_group": "线下组"}],
    )
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (september, current)}

    merged = _read(files, current, [september], ["2026-10"])

    for kind, ids in (
        ("resources", {"R-SEP", "R-OCT"}),
        ("contracts", {"C-SEP", "C-OCT"}),
        ("languages", {"WO-SEP", "WO-OCT"}),
    ):
        key = {"resources": "resource_id", "contracts": "contract_id", "languages": "work_order_id"}[kind]
        assert {row[key] for row in merged[kind]} == ids
        assert merged["retained_months"][kind] == ["2026-09", "2026-10"]

    september_resource = next(row for row in merged["resources"] if row["resource_id"] == "R-SEP")
    assert september_resource["origin_sha256"] == files.sources[september]["source_sha256"]
    assert september_resource["origin_filename"] == "history-september.xlsx"
    assert september_resource["origin_sheet"] == "资源"
    assert september_resource["origin_row_number"] == 2
    assert merged["group_mapping"] == files.sources[current]["group_mapping"]
    assert merged["source_path"] == str(current)
    assert merged["current_source_sha256"] == files.sources[current]["source_sha256"]
    assert [item["filename"] for item in merged["source_files"]] == [
        "history-september.xlsx",
        "current-october.xlsx",
    ]
    assert merged["source_sha256"] != merged["current_source_sha256"]
    assert merged["update_mode"] == "replace_observed_months_preserve_history"
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before} == before


def test_second_october_export_replaces_the_first_october_partition(tmp_path: Path) -> None:
    files = SourceFiles(tmp_path)
    september = files.add(
        "september.xlsx",
        resources=[_resource(2, date(2026, 9, 2), "R-SEP")],
        contracts=[_contract(2, date(2026, 9, 3), "C-SEP")],
        languages=[_language(2, date(2026, 9, 4), "WO-SEP")],
    )
    october_first = files.add(
        "october-first.xlsx",
        resources=[_resource(2, date(2026, 10, 1), "R-OLD"), _resource(3, date(2026, 10, 2), "R-OLD-2")],
        contracts=[_contract(2, date(2026, 10, 1), "C-OLD"), _contract(3, date(2026, 10, 2), "C-OLD-2")],
        languages=[_language(2, date(2026, 10, 1), "WO-OLD"), _language(3, date(2026, 10, 2), "WO-OLD-2")],
    )
    october_second = files.add(
        "october-second.xlsx",
        resources=[_resource(2, date(2026, 10, 20), "R-NEW")],
        contracts=[_contract(2, date(2026, 10, 20), "C-NEW")],
        languages=[_language(2, date(2026, 10, 20), "WO-NEW")],
    )

    merged = _read(files, october_second, [september, october_first], ["2026-10"])

    assert {row["resource_id"] for row in merged["resources"]} == {"R-SEP", "R-NEW"}
    assert {row["contract_id"] for row in merged["contracts"]} == {"C-SEP", "C-NEW"}
    assert {row["work_order_id"] for row in merged["languages"]} == {"WO-SEP", "WO-NEW"}
    assert all(row["origin_filename"] != "october-first.xlsx" for kind in ("resources", "contracts", "languages") for row in merged[kind])


def test_refresh_month_with_no_current_rows_clears_its_old_partition(tmp_path: Path) -> None:
    files = SourceFiles(tmp_path)
    october = files.add(
        "october-history.xlsx",
        resources=[_resource(2, date(2026, 10, 5), "R-OCT")],
        contracts=[_contract(2, date(2026, 10, 6), "C-OCT")],
        languages=[_language(2, date(2026, 10, 7), "WO-OCT")],
    )
    current = files.add("current-empty-october.xlsx")

    merged = _read(files, current, [october], ["2026-10"])

    assert merged["resources"] == []
    assert merged["contracts"] == []
    assert merged["languages"] == []
    assert merged["retained_months"] == {"resources": [], "contracts": [], "languages": []}


def test_equal_value_language_rows_are_preserved_without_deduplication(tmp_path: Path) -> None:
    files = SourceFiles(tmp_path)
    current = files.add(
        "current.xlsx",
        languages=[_language(2, date(2026, 10, 5)), _language(3, date(2026, 10, 5))],
    )

    merged = _read(files, current, [], [])

    assert len(merged["languages"]) == 2
    assert [row["origin_row_number"] for row in merged["languages"]] == [2, 3]
    assert merged["languages"][0]["amount"] == merged["languages"][1]["amount"] == 500
    assert merged["source_sha256"] == merged["current_source_sha256"]


def test_business_row_without_date_fails_instead_of_being_dropped(tmp_path: Path) -> None:
    files = SourceFiles(tmp_path)
    current = files.add("current.xlsx", resources=[_resource(7, None, "R-NO-DATE")])

    with pytest.raises(ValueError, match="resources 第 7 行缺少业务日期"):
        _read(files, current, [], [])


def test_composite_source_hash_is_deterministic_for_ordered_inputs(tmp_path: Path) -> None:
    files = SourceFiles(tmp_path)
    old = files.add("old.xlsx", resources=[_resource(2, "2026-09", "R-SEP")])
    current = files.add("current.xlsx", resources=[_resource(2, "2026-10", "R-OCT")])

    first = _read(files, current, [old], ["2026-10"])
    second = _read(files, current, [old], ["2026-10"])

    assert first["source_sha256"] == second["source_sha256"]
    assert first["source_sha256"] != files.sources[current]["source_sha256"]
