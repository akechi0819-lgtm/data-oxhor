from __future__ import annotations

import hashlib
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": MAIN_NS, "r": REL_NS, "p": PACKAGE_REL_NS}

CLEAN_CANDIDATE_SHEETS = {
    "fy25_frontdesk_daily": frozenset({"FY25-汇总"}),
    "fy27_frontdesk_daily": frozenset({"FY27-汇总"}),
    "br_cash": frozenset({"现金明细表"}),
    "current_work_orders": frozenset({"工单分析", "新表区域"}),
    "archived_work_orders": frozenset({"FY24", "FY25", "FY26"}),
}


class XlsxReadError(ValueError):
    """Raised when an XLSX package cannot be inspected reliably."""


@dataclass(frozen=True)
class Cell:
    column: int
    reference: str
    value: str | None
    storage_type: str
    formula: str | None
    formula_cache: str


@dataclass(frozen=True)
class SheetTarget:
    name: str
    target: str
    state: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def column_number(reference: str) -> int:
    match = re.match(r"[A-Z]+", reference.upper())
    if not match:
        raise XlsxReadError(f"invalid cell reference: {reference}")
    value = 0
    for letter in match.group(0):
        value = value * 26 + ord(letter) - 64
    return value


def shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(".//m:t", NS)) for item in root.findall("m:si", NS)]


def _resolve_target(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return f"xl/{target}"


def sheet_targets(archive: zipfile.ZipFile) -> list[SheetTarget]:
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError as exc:
        raise XlsxReadError(f"missing required XLSX member: {exc.args[0]}") from exc
    targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships.findall("p:Relationship", NS)}
    result = []
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        relationship_id = sheet.attrib.get(f"{{{REL_NS}}}id")
        if not relationship_id or relationship_id not in targets:
            raise XlsxReadError(f"worksheet relationship missing for {sheet.attrib.get('name', '<unnamed>')}")
        result.append(
            SheetTarget(
                name=sheet.attrib["name"],
                target=_resolve_target(targets[relationship_id]),
                state=sheet.attrib.get("state", "visible"),
            )
        )
    return result


def _cell_value(cell: ET.Element, shared: list[str]) -> str | None:
    if cell.attrib.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", NS))
    value = cell.find("m:v", NS)
    if value is None:
        return None
    raw = value.text or ""
    if cell.attrib.get("t") != "s":
        return raw
    try:
        return shared[int(raw)]
    except (ValueError, IndexError) as exc:
        raise XlsxReadError(f"invalid shared string index: {raw}") from exc


def iter_sheet_rows(archive: zipfile.ZipFile, target: str, shared: list[str] | None = None) -> Iterator[tuple[int, dict[int, Cell]]]:
    strings = shared_strings(archive) if shared is None else shared
    try:
        source = archive.open(target)
    except KeyError as exc:
        raise XlsxReadError(f"worksheet member missing: {target}") from exc
    with source:
        for _, element in ET.iterparse(source, events=("end",)):
            if not element.tag.endswith("}row"):
                continue
            row_number = int(element.attrib.get("r", "0"))
            cells: dict[int, Cell] = {}
            for node in element.findall("m:c", NS):
                reference = node.attrib.get("r", "")
                column = column_number(reference)
                formula_node = node.find("m:f", NS)
                formula = formula_node.text if formula_node is not None else None
                value = _cell_value(node, strings)
                cells[column] = Cell(
                    column=column,
                    reference=reference,
                    value=value,
                    storage_type=node.attrib.get("t", "n"),
                    formula=formula,
                    formula_cache="missing" if formula is not None and value in (None, "") else "present" if formula is not None else "not_formula",
                )
            yield row_number, cells
            element.clear()


def declared_dimension(archive: zipfile.ZipFile, target: str) -> str | None:
    with archive.open(target) as source:
        for event, element in ET.iterparse(source, events=("start",)):
            if element.tag.endswith("}dimension"):
                return element.attrib.get("ref")
            if element.tag.endswith("}sheetData"):
                break
    return None


def _technical_headers(cells: dict[int, Cell]) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    headers = []
    for position, cell in sorted(cells.items()):
        original = str(cell.value).strip() if cell.value not in (None, "") else ""
        base = original or f"column_{position}"
        counts[base] += 1
        technical = base if counts[base] == 1 else f"{base}__{counts[base]}"
        headers.append({"position": position, "original_name": original or None, "technical_name": technical})
    return headers


def inspect_sheet(archive: zipfile.ZipFile, sheet: SheetTarget, shared: list[str]) -> dict[str, object]:
    row_count = 0
    populated_rows = 0
    max_row = 0
    max_column = 0
    header_cells: dict[int, Cell] = {}
    storage_types: Counter[str] = Counter()
    formula_cells = 0
    formula_cache_missing = 0
    for row_number, cells in iter_sheet_rows(archive, sheet.target, shared):
        meaningful = {column: cell for column, cell in cells.items() if cell.value not in (None, "") or cell.formula is not None}
        if meaningful:
            row_count += 1
            max_row = max(max_row, row_number)
            populated_rows += 1
            max_column = max(max_column, max(meaningful))
        if row_number == 1:
            header_cells = meaningful
        for cell in meaningful.values():
            storage_types[cell.storage_type] += 1
            if cell.formula is not None:
                formula_cells += 1
                formula_cache_missing += cell.formula_cache == "missing"
    headers = _technical_headers(header_cells)
    duplicate_names = sorted(
        name for name, count in Counter(item["original_name"] for item in headers if item["original_name"]).items() if count > 1
    )
    return {
        "name": sheet.name,
        "state": sheet.state,
        "declared_dimension": declared_dimension(archive, sheet.target),
        "physical_rows": row_count,
        "populated_rows": populated_rows,
        "data_rows": max(row_count - (1 if header_cells else 0), 0),
        "actual_max_row": max_row,
        "actual_max_column": max_column,
        "headers": headers,
        "duplicate_header_names": duplicate_names,
        "storage_type_counts": dict(sorted(storage_types.items())),
        "formula_cells": formula_cells,
        "formula_cache": {"present": formula_cells - formula_cache_missing, "missing": formula_cache_missing},
    }


def inspect_workbook(path: Path, source_id: str) -> dict[str, object]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise XlsxReadError("file is not a readable XLSX package") from exc
    with archive:
        required_members = {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
        missing = sorted(required_members - set(archive.namelist()))
        if missing:
            raise XlsxReadError(f"missing required XLSX members: {', '.join(missing)}")
        shared = shared_strings(archive)
        sheets = []
        quality = []
        candidates = CLEAN_CANDIDATE_SHEETS.get(source_id, frozenset())
        for target in sheet_targets(archive):
            summary = inspect_sheet(archive, target, shared)
            is_candidate = target.name in candidates
            summary["clean_candidate"] = is_candidate
            sheets.append(summary)
            if not is_candidate:
                quality.append({"issue_code": "SHEET_NOT_CLEAN_CANDIDATE", "sheet_name": target.name, "status": "pending"})
        return {"sheets": sheets, "quality": quality}
