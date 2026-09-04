#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_platform.connectors.xlsx import (  # noqa: E402
    XlsxReadError,
    declared_dimension,
    iter_sheet_rows,
    sha256_file,
    shared_strings,
    sheet_targets,
)


class ValidationError(ValueError):
    pass


def decimal(raw: str | None) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", "").strip())
    except InvalidOperation:
        return None


def inspect_sheet(archive: zipfile.ZipFile, target: str, shared: list[str]) -> dict:
    dimension = declared_dimension(archive, target)
    headers: dict[int, str] = {}
    rows = 0
    business_forms = Counter()
    registration_cash = Decimal(0)
    registration_cash_rows = 0
    negative_amount_rows = 0
    date_values: dict[str, Counter] = {}
    for row_number, row_cells in iter_sheet_rows(archive, target, shared):
        cells = {column: (cell.value, cell.storage_type) for column, cell in row_cells.items()}
        if row_number == 1:
            headers = {column: str(value).strip() for column, (value, _) in cells.items() if value not in (None, "")}
            date_values = {name: Counter() for name in headers.values() if name in {"最新回访时间", "分配时间", "分配日期"}}
            continue
        if not cells:
            continue
        rows += 1
        values = {name: cells.get(column, (None, "n")) for column, name in headers.items()}
        form = values.get("业务形式", (None, "n"))[0]
        amount = decimal(values.get("实缴金额", (None, "n"))[0])
        if form not in (None, ""):
            business_forms[str(form).strip()] += 1
        if amount is not None and amount < 0:
            negative_amount_rows += 1
        if form in {"报班", "报班-预收"} and amount is not None:
            registration_cash += amount
            registration_cash_rows += 1
        for field in date_values:
            raw, kind = values.get(field, (None, "n"))
            if raw in (None, ""):
                date_values[field]["blank"] += 1
            elif kind in {"s", "inlineStr", "str"}:
                date_values[field]["text"] += 1
            else:
                date_values[field]["numeric"] += 1
    return {
        "declared_dimension": dimension,
        "headers": headers,
        "data_rows": rows,
        "business_forms": business_forms,
        "registration_cash": registration_cash,
        "registration_cash_rows": registration_cash_rows,
        "negative_amount_rows": negative_amount_rows,
        "date_values": date_values,
    }


def require(condition: bool, check_id: str, actual, expected, checks: list[dict]) -> None:
    passed = bool(condition)
    checks.append({"check_id": check_id, "status": "passed" if passed else "failed", "actual": actual, "expected": expected})
    if not passed:
        raise ValidationError(f"{check_id}: actual={actual!r}, expected={expected!r}")


def validate_source(source_id: str, path: Path, source_contract: dict, acceptance: dict) -> list[dict]:
    checks: list[dict] = []
    require(path.is_file(), f"{source_id}.file_exists", path.name, source_contract["filename"], checks)
    require(path.name == source_contract["filename"], f"{source_id}.filename", path.name, source_contract["filename"], checks)
    digest = sha256_file(path)
    require(digest == source_contract["sha256"], f"{source_id}.sha256", digest, source_contract["sha256"], checks)
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"{source_id}.invalid_xlsx: {exc}") from exc
    with archive:
        shared = shared_strings(archive)
        targets = {sheet.name: sheet.target for sheet in sheet_targets(archive)}
        required_sheets = acceptance["required_sheets"]
        require(all(name in targets for name in required_sheets), f"{source_id}.required_sheets", sorted(targets), sorted(required_sheets), checks)
        inspected = {name: inspect_sheet(archive, targets[name], shared) for name in required_sheets}
        if "sheet" in acceptance:
            sheet = inspected[acceptance["sheet"]]
            for field in ("data_rows", "negative_amount_rows", "registration_cash_rows"):
                require(sheet[field] == acceptance[field], f"{source_id}.{field}", sheet[field], acceptance[field], checks)
            require(sheet["registration_cash"] == Decimal(acceptance["registration_cash"]), f"{source_id}.registration_cash", str(sheet["registration_cash"]), acceptance["registration_cash"], checks)
            for form in acceptance.get("required_business_forms", []):
                require(form in sheet["business_forms"], f"{source_id}.business_form.{form}", form in sheet["business_forms"], True, checks)
        data_rows_by_sheet = acceptance.get("data_rows", {})
        if not isinstance(data_rows_by_sheet, dict):
            data_rows_by_sheet = {}
        for sheet_name, expected_rows in data_rows_by_sheet.items():
            require(inspected[sheet_name]["data_rows"] == expected_rows, f"{source_id}.{sheet_name}.data_rows", inspected[sheet_name]["data_rows"], expected_rows, checks)
        for sheet_name, expected_dimension in acceptance.get("declared_dimensions", {}).items():
            require(inspected[sheet_name]["declared_dimension"] == expected_dimension, f"{source_id}.{sheet_name}.declared_dimension", inspected[sheet_name]["declared_dimension"], expected_dimension, checks)
        for sheet_name, field in acceptance.get("date_fields", {}).items():
            require(field in inspected[sheet_name]["date_values"], f"{source_id}.{sheet_name}.date_field", sorted(inspected[sheet_name]["date_values"]), field, checks)
        for sheet_name, expected_blanks in acceptance.get("blank_date_rows", {}).items():
            field = acceptance["date_fields"][sheet_name]
            actual = inspected[sheet_name]["date_values"][field]["blank"]
            require(actual == expected_blanks, f"{source_id}.{sheet_name}.blank_date_rows", actual, expected_blanks, checks)
        for locator, expected_type in acceptance.get("date_storage", {}).items():
            sheet_name, field = locator.split(".", 1)
            counts = inspected[sheet_name]["date_values"][field]
            actual_type = "text" if counts["text"] and not counts["numeric"] else "numeric" if counts["numeric"] and not counts["text"] else "mixed"
            require(actual_type == expected_type, f"{source_id}.{locator}.storage", actual_type, expected_type, checks)
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate external Stage 0 Golden Case workbooks without emitting row data.")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("golden_cases.json"))
    parser.add_argument("--source", action="append", default=[], metavar="SOURCE_ID=PATH")
    args = parser.parse_args()
    bindings = {}
    for binding in args.source:
        source_id, separator, raw_path = binding.partition("=")
        if not separator or not source_id or not raw_path:
            parser.error(f"invalid --source binding: {binding}")
        bindings[source_id] = Path(raw_path)
    contract = json.loads(args.manifest.read_text(encoding="utf-8"))
    required_ids = set(contract["sources"])
    if set(bindings) != required_ids:
        print(json.dumps({"status": "failed", "error": "SOURCE_BINDINGS_INVALID", "required": sorted(required_ids), "provided": sorted(bindings)}, ensure_ascii=False))
        return 2
    result = {"schema_version": "golden_case_validation.v1", "status": "passed", "checks": [], "errors": []}
    acceptance_by_source = {}
    for case in contract["cases"]:
        for source_id, acceptance in case["minimum_acceptance"].items():
            acceptance_by_source[source_id] = acceptance
    for source_id in sorted(required_ids):
        try:
            result["checks"].extend(validate_source(source_id, bindings[source_id], contract["sources"][source_id], acceptance_by_source[source_id]))
        except (OSError, KeyError, ValidationError, XlsxReadError, ET.ParseError) as exc:
            result["status"] = "failed"
            result["errors"].append({"source_id": source_id, "message": str(exc)})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
