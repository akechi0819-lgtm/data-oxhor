from __future__ import annotations

import hashlib
from pathlib import Path

import openpyxl
import pytest

from data_acquisition.jobs.build_study_abroad_warehouse import SHEET_COLUMNS
from data_acquisition.jobs.study_abroad_standard_source import read_standard_source


def _row(kind: str, row_number: int, **overrides) -> dict:
    values = {column: None for column in SHEET_COLUMNS[kind]}
    values.update({
        "origin_sha256": "a" * 64,
        "origin_filename": "synthetic-source.xlsx",
        "origin_sheet": {"resources": "资源", "contracts": "留学签约", "languages": "小语种签约"}[kind],
        "origin_row_number": row_number,
        "owner": "合成甲",
        "source_owner": "合成甲",
        "source_group": "线上组",
        "market_group": "线上组",
        "segment_id": "study_abroad_online",
        "team_eligible": "true",
        "market_eligible": "true",
        "roster_group": "大学",
        "roster_status": "active",
        "personal_eligible": "false",
        "event_date": "2026-10-12",
        "record_key": f"source:{kind}:{row_number}",
        "source_date_conflict": "false",
        "source_date_resolution": None,
    })
    if kind == "resources":
        values.update({"resource_id": None, "consultation_type": "留学", "status": "正常"})
    elif kind == "contracts":
        values.update({
            "resource_id": "R-1", "contract_id": f"C-{row_number}",
            "customer_id": None, "customer_name": "同名客户",
            "customer_key": "contracts:name:customer-hash", "customer_key_basis": "name",
            "amount": "100.00", "amount_status": "available", "month": "2026-10",
        })
    else:
        values.update({
            "resource_id": "R-1", "work_order_id": f"W-{row_number}", "student_id": None,
            "customer_name": "同名客户", "customer_key": "languages:name:student-hash",
            "customer_key_basis": "name", "amount": "100.00", "amount_status": "available",
            "language": "日语",
        })
    values.update(overrides)
    return values


def _write_standard_source(
    path: Path,
    *,
    columns: dict[str, tuple[str, ...]] = SHEET_COLUMNS,
    rows: dict[str, list[dict]] | None = None,
    header_overrides: dict[str, list[str]] | None = None,
) -> None:
    rows = rows or {
        "resources": [_row("resources", 2)],
        "contracts": [_row("contracts", 2)],
        "languages": [_row("languages", 2), _row("languages", 3)],
    }
    header_overrides = header_overrides or {}
    book = openpyxl.Workbook()
    book.remove(book.active)
    for kind in columns:
        sheet = book.create_sheet(kind)
        headers = header_overrides.get(kind, list(columns[kind]))
        sheet.append(headers)
        for item in rows.get(kind, []):
            sheet.append([item.get(header) for header in columns[kind]])
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    book.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reads_exact_normalized_tables_preserves_rows_and_leaves_source_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "standard-source.xlsx"
    rows = {
        "resources": [_row("resources", 2)],
        "contracts": [_row("contracts", 2)],
        "languages": [
            _row("languages", 2, amount="500.00", work_order_id="W-2"),
            _row("languages", 3, amount="500.00", work_order_id="W-3"),
        ],
    }
    _write_standard_source(path, rows=rows)
    before = _sha256(path)

    result = read_standard_source(path, SHEET_COLUMNS)

    assert result["source_sha256"] == before
    assert _sha256(path) == before
    assert result["source_path"] == str(path)
    assert result["source_sheets"] == {kind: kind for kind in SHEET_COLUMNS}
    assert result["diagnostics"]["row_counts"] == {"resources": 1, "contracts": 1, "languages": 2}
    assert len(result["tables"]["languages"]) == 2
    assert [row["record_key"] for row in result["tables"]["languages"]] == [
        "source:languages:2", "source:languages:3",
    ]
    assert result["tables"]["contracts"][0]["customer_key"] == "contracts:name:customer-hash"
    assert result["tables"]["languages"][0]["customer_key"] == "languages:name:student-hash"
    assert result["tables"]["contracts"][0]["customer_key"] != result["tables"]["languages"][0]["customer_key"]
    assert result["tables"]["resources"][0]["resource_id"] is None
    assert result["tables"]["resources"][0]["record_key"] == "source:resources:2"


def test_filters_only_all_none_template_rows(tmp_path: Path) -> None:
    path = tmp_path / "with-template.xlsx"
    rows = {
        "resources": [_row("resources", 2)],
        "contracts": [_row("contracts", 2)],
        "languages": [_row("languages", 2), _row("languages", 3)],
    }
    _write_standard_source(path, rows=rows)
    book = openpyxl.load_workbook(path)
    book["languages"].insert_rows(3)
    book["languages"].append([None] * len(SHEET_COLUMNS["languages"]))
    book.save(path)
    book.close()

    result = read_standard_source(path, SHEET_COLUMNS)

    assert result["diagnostics"]["empty_rows_filtered"]["languages"] == 2
    assert len(result["tables"]["languages"]) == 2


def test_rejects_any_header_order_or_unknown_column_change(tmp_path: Path) -> None:
    path = tmp_path / "unknown-column.xlsx"
    _write_standard_source(
        path,
        header_overrides={"contracts": [*SHEET_COLUMNS["contracts"], "unexpected"]},
    )

    with pytest.raises(ValueError, match="表头与SHEET_COLUMNS不完全一致"):
        read_standard_source(path, SHEET_COLUMNS)


@pytest.mark.parametrize(
    ("kind", "overrides", "message"),
    [
        ("resources", {"origin_sha256": "invalid"}, "origin_sha256"),
        ("contracts", {"origin_filename": "  "}, "origin_filename"),
        ("languages", {"origin_sheet": None}, "origin_sheet"),
        ("resources", {"origin_row_number": 0}, "origin_row_number"),
        ("resources", {"record_key": ""}, "record_key"),
        ("resources", {"market_eligible": "yes"}, "market_eligible"),
        ("resources", {"team_eligible": True}, "team_eligible"),
        ("resources", {"personal_eligible": "False"}, "personal_eligible"),
        ("resources", {"source_date_conflict": "yes"}, "source_date_conflict"),
        ("resources", {"event_date": "2026-10-40"}, "ISO日期"),
    ],
)
def test_rejects_invalid_provenance_flags_and_market_date(
    tmp_path: Path,
    kind: str,
    overrides: dict,
    message: str,
) -> None:
    path = tmp_path / f"bad-{kind}-{message}.xlsx"
    rows = {name: [] for name in SHEET_COLUMNS}
    rows[kind] = [_row(kind, 2, **overrides)]
    _write_standard_source(path, rows=rows)

    with pytest.raises(ValueError, match=message):
        read_standard_source(path, SHEET_COLUMNS)


def test_nonmarket_rows_may_have_no_event_date(tmp_path: Path) -> None:
    path = tmp_path / "nonmarket-no-date.xlsx"
    rows = {kind: [] for kind in SHEET_COLUMNS}
    rows["resources"] = [
        _row("resources", 2, market_eligible="false", team_eligible="false", event_date=None),
    ]
    _write_standard_source(path, rows=rows)

    result = read_standard_source(path, SHEET_COLUMNS)

    assert result["tables"]["resources"][0]["event_date"] is None


def test_amount_status_decimal_and_customer_domain_are_enforced(tmp_path: Path) -> None:
    bad_amount = tmp_path / "float-amount.xlsx"
    rows = {kind: [] for kind in SHEET_COLUMNS}
    rows["contracts"] = [_row("contracts", 2, amount=0.1)]
    _write_standard_source(bad_amount, rows=rows)
    with pytest.raises(ValueError, match="不能使用浮点数"):
        read_standard_source(bad_amount, SHEET_COLUMNS)

    bad_key = tmp_path / "cross-domain-key.xlsx"
    rows["contracts"] = []
    rows["languages"] = [_row("languages", 2, customer_key="contracts:name:wrong-domain")]
    _write_standard_source(bad_key, rows=rows)
    with pytest.raises(ValueError, match="customer_key必须使用languages:"):
        read_standard_source(bad_key, SHEET_COLUMNS)

    missing_key = tmp_path / "positive-without-key.xlsx"
    rows["languages"] = [_row("languages", 2, customer_key=None)]
    _write_standard_source(missing_key, rows=rows)
    with pytest.raises(ValueError, match="正向市场金额缺少已确认customer_key"):
        read_standard_source(missing_key, SHEET_COLUMNS)


def test_amount_can_be_empty_only_with_explicit_missing_status(tmp_path: Path) -> None:
    path = tmp_path / "missing-amount.xlsx"
    rows = {kind: [] for kind in SHEET_COLUMNS}
    rows["contracts"] = [_row("contracts", 2, amount=None, amount_status="missing")]
    _write_standard_source(path, rows=rows)

    result = read_standard_source(path, SHEET_COLUMNS)
    assert result["tables"]["contracts"][0]["amount"] is None
    assert result["tables"]["contracts"][0]["amount_status"] == "missing"

    rows["contracts"] = [_row("contracts", 2, amount=None, amount_status="available")]
    _write_standard_source(path, rows=rows)
    with pytest.raises(ValueError, match="金额为空时amount_status必须为missing"):
        read_standard_source(path, SHEET_COLUMNS)


def test_schema_mapping_requires_builder_sheet_order(tmp_path: Path) -> None:
    path = tmp_path / "schema-order.xlsx"
    _write_standard_source(path)
    reversed_columns = {
        "contracts": SHEET_COLUMNS["contracts"],
        "resources": SHEET_COLUMNS["resources"],
        "languages": SHEET_COLUMNS["languages"],
    }

    with pytest.raises(ValueError, match="必须依次包含resources"):
        read_standard_source(path, reversed_columns)
