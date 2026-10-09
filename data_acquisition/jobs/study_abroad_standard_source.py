"""Read a builder-produced study-abroad workbook without reinterpreting its data.

The caller passes the builder's ``SHEET_COLUMNS`` mapping so this reader does
not import the builder at module load time. The workbook is accepted only when
its three normalized sheets and headers match that schema exactly. Rows are
returned as stored; this module does not classify owners, infer identities,
deduplicate records, or write to the source file.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


_KINDS = ("resources", "contracts", "languages")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_market_eligible(row: dict[str, Any]) -> bool:
    return row.get("market_eligible") == "true"


def _validate_provenance(row: dict[str, Any], *, kind: str, physical_row: int) -> None:
    if not isinstance(row.get("origin_sha256"), str) or not _SHA256.fullmatch(row["origin_sha256"]):
        raise ValueError(f"{kind} 第{physical_row}行缺少有效origin_sha256")
    if not _nonempty_text(row.get("origin_filename")):
        raise ValueError(f"{kind} 第{physical_row}行缺少origin_filename")
    if not _nonempty_text(row.get("origin_sheet")):
        raise ValueError(f"{kind} 第{physical_row}行缺少origin_sheet")
    row_number = row.get("origin_row_number")
    if not isinstance(row_number, int) or isinstance(row_number, bool) or row_number < 1:
        raise ValueError(f"{kind} 第{physical_row}行origin_row_number必须为正整数")
    if not _nonempty_text(row.get("record_key")):
        raise ValueError(f"{kind} 第{physical_row}行缺少record_key")


def _validate_flags(row: dict[str, Any], *, kind: str, physical_row: int) -> None:
    for field in ("market_eligible", "team_eligible", "personal_eligible"):
        if not isinstance(row.get(field), str) or row[field] not in {"true", "false"}:
            raise ValueError(f"{kind} 第{physical_row}行{field}必须为true或false")
    if "source_date_conflict" in row and row["source_date_conflict"] is not None:
        if (not isinstance(row["source_date_conflict"], str)
                or row["source_date_conflict"] not in {"true", "false"}):
            raise ValueError(f"{kind} 第{physical_row}行source_date_conflict必须为true或false")


def _validate_event_date(row: dict[str, Any], *, kind: str, physical_row: int) -> None:
    if not _is_market_eligible(row):
        return
    value = row.get("event_date")
    if not isinstance(value, str):
        raise ValueError(f"{kind} 第{physical_row}行市场业务日期必须为ISO日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{kind} 第{physical_row}行市场业务日期必须为ISO日期") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{kind} 第{physical_row}行市场业务日期必须为ISO日期")


def _validate_amount(row: dict[str, Any], *, kind: str, physical_row: int) -> None:
    value = row.get("amount")
    status = row.get("amount_status")
    if not isinstance(status, str) or status not in {"available", "missing"}:
        raise ValueError(f"{kind} 第{physical_row}行amount_status无效")
    customer_key = row.get("customer_key")
    expected_prefix = f"{kind}:"
    if customer_key not in (None, "") and (
        not isinstance(customer_key, str) or not customer_key.startswith(expected_prefix)
    ):
        raise ValueError(f"{kind} 第{physical_row}行customer_key必须使用{expected_prefix}分域")
    if value is None or value == "":
        if status != "missing":
            raise ValueError(f"{kind} 第{physical_row}行金额为空时amount_status必须为missing")
        return
    if isinstance(value, (float, bool)):
        raise ValueError(f"{kind} 第{physical_row}行金额不能使用浮点数或布尔值")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{kind} 第{physical_row}行金额不是有效Decimal") from exc
    if not amount.is_finite():
        raise ValueError(f"{kind} 第{physical_row}行金额必须为有限Decimal")
    if status == "missing":
        raise ValueError(f"{kind} 第{physical_row}行amount_status为missing但金额非空")

    if amount > 0 and _is_market_eligible(row):
        if not _nonempty_text(customer_key) or not customer_key.startswith(expected_prefix):
            raise ValueError(f"{kind} 第{physical_row}行正向市场金额缺少已确认customer_key")


def _validate_row(row: dict[str, Any], *, kind: str, physical_row: int) -> None:
    _validate_provenance(row, kind=kind, physical_row=physical_row)
    _validate_flags(row, kind=kind, physical_row=physical_row)
    _validate_event_date(row, kind=kind, physical_row=physical_row)
    if kind in {"contracts", "languages"}:
        _validate_amount(row, kind=kind, physical_row=physical_row)


def read_standard_source(path: Path, columns: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """Read exact normalized ``resources``, ``contracts`` and ``languages`` sheets.

    ``columns`` must be the builder's ``SHEET_COLUMNS`` mapping. The returned
    ``tables`` preserve all cell values and row multiplicity, including equal
    small-language transactions. Only rows whose cells are all ``None`` are
    treated as empty templates.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if tuple(columns) != _KINDS:
        raise ValueError("标准留学来源schema必须依次包含resources、contracts、languages")

    expected_columns = {kind: list(columns[kind]) for kind in _KINDS}
    for kind in ("contracts", "languages"):
        if "amount_status" not in expected_columns[kind]:
            raise ValueError(f"标准留学来源{kind}schema缺少amount_status")
    before_sha256 = _file_sha256(path)
    try:
        import openpyxl

        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError("标准留学来源不是可读取的XLSX文件") from exc

    tables: dict[str, list[dict[str, Any]]] = {}
    empty_rows_filtered: dict[str, int] = {}
    try:
        if workbook.sheetnames != list(_KINDS):
            raise ValueError("标准留学来源工作表必须依次为resources、contracts、languages")
        for kind in _KINDS:
            sheet = workbook[kind]
            iterator = sheet.iter_rows(values_only=True)
            try:
                header = list(next(iterator))
            except StopIteration:
                raise ValueError(f"标准留学来源{kind}缺少表头") from None
            if header != expected_columns[kind]:
                raise ValueError(f"标准留学来源{kind}表头与SHEET_COLUMNS不完全一致")

            rows: list[dict[str, Any]] = []
            empty_count = 0
            for physical_row, values in enumerate(iterator, start=2):
                cells = list(values)
                if all(value is None for value in cells):
                    empty_count += 1
                    continue
                row = dict(zip(expected_columns[kind], cells))
                _validate_row(row, kind=kind, physical_row=physical_row)
                rows.append(row)
            tables[kind] = rows
            empty_rows_filtered[kind] = empty_count
    finally:
        workbook.close()

    after_sha256 = _file_sha256(path)
    if after_sha256 != before_sha256:
        raise ValueError("标准留学来源在读取期间发生变化")
    return {
        "tables": tables,
        "source_sha256": before_sha256,
        "source_path": str(path),
        "source_sheets": {kind: kind for kind in _KINDS},
        "diagnostics": {
            "row_counts": {kind: len(rows) for kind, rows in tables.items()},
            "empty_rows_filtered": empty_rows_filtered,
        },
    }
