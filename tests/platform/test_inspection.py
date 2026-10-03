from __future__ import annotations

import hashlib
import json
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

from data_platform.connectors.xlsx import iter_sheet_rows, inspect_workbook, sheet_targets
from interfaces.data_platform import inspect_sources


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
ROOT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
WORKBOOK = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="FY25-汇总" sheetId="1" r:id="rId1"/><sheet name="看板" sheetId="2" state="hidden" r:id="rId2"/></sheets>
</workbook>"""
WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>"""
SHEET_ONE = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1"/>
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>名称</t></is></c><c r="B1" t="inlineStr"><is><t>名称</t></is></c><c r="C1" t="inlineStr"><is><t>金额</t></is></c></row>
    <row r="7"><c r="A7" t="inlineStr"><is><t>示例</t></is></c><c r="C7"><f>1+1</f><v>2</v></c><c r="D7"><v>2.8086303E7</v></c></row>
    <row r="8"><c r="C8"><f>2+2</f></c></row>
  </sheetData>
</worksheet>"""
SHEET_TWO = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:B2"/><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>项目</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>汇总</t></is></c></row></sheetData>
</worksheet>"""


def write_workbook(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("xl/workbook.xml", WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        archive.writestr("xl/worksheets/sheet1.xml", SHEET_ONE)
        archive.writestr("xl/worksheets/sheet2.xml", SHEET_TWO)


class WorkbookInspectionTests(unittest.TestCase):
    def test_streaming_row_interface_preserves_raw_cell_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.xlsx"
            write_workbook(path)
            with zipfile.ZipFile(path) as archive:
                target = sheet_targets(archive)[0]
                rows = list(iter_sheet_rows(archive, target.target))

        self.assertEqual([row_number for row_number, _ in rows], [1, 7, 8])
        cached = rows[1][1][3]
        missing = rows[2][1][3]
        self.assertEqual((cached.reference, cached.storage_type, cached.formula, cached.value, cached.formula_cache), ("C7", "n", "1+1", "2", "present"))
        self.assertEqual((missing.reference, missing.formula, missing.value, missing.formula_cache), ("C8", "2+2", None, "missing"))
        self.assertEqual(rows[1][1][4].value, "28086303")

    def test_inspection_ignores_declared_dimension_and_reports_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.xlsx"
            write_workbook(path)
            result = inspect_workbook(path)

        first, second = result["sheets"]
        self.assertEqual(first["declared_dimension"], "A1")
        self.assertEqual(first["actual_max_row"], 8)
        self.assertEqual(first["populated_rows"], 3)
        self.assertEqual(first["first_row_duplicate_header_names"], ["名称"])
        self.assertEqual([item["technical_name"] for item in first["first_row_headers"]], ["名称", "名称__2", "金额"])
        self.assertEqual(first["header_candidates"][0]["row_number"], 1)
        self.assertEqual(first["formula_cache"], {"present": 1, "missing": 1})
        self.assertEqual(second["state"], "hidden")
        self.assertEqual(
            result["quality"],
            [
                {"issue_code": "DECLARED_DIMENSION_MISMATCH", "sheet_name": "FY25-汇总", "status": "pending"},
                {"issue_code": "FORMULA_CACHE_MISSING", "sheet_name": "FY25-汇总", "count": 1, "status": "pending"},
                {"issue_code": "SHEET_HIDDEN", "sheet_name": "看板", "status": "pending"},
                {"issue_code": "HEADER_CANDIDATE_NOT_FOUND", "sheet_name": "看板", "status": "pending"},
            ],
        )

    def test_cli_contract_does_not_emit_absolute_source_path_or_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xlsx"
            write_workbook(source)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"sources": {"fy25_frontdesk_daily": {"filename": source.name, "sha256": digest}}}), encoding="utf-8")
            result = inspect_sources(
                run_id="run_inspection_001",
                manifest_path=manifest,
                source_values=[f"fy25_frontdesk_daily={source}"],
            )

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["schema_version"], "data_foundation_inspection.v2")
        self.assertEqual(result["status"], "passed_with_warnings")
        self.assertNotIn(str(source.parent), serialized)
        self.assertNotIn("示例", serialized)

    def test_cli_rejects_invalid_identity_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xlsx"
            source.write_bytes(b"not xlsx")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"sources": {"fy25_frontdesk_daily": {"filename": source.name, "sha256": "0" * 64}}}), encoding="utf-8")
            result = inspect_sources(
                run_id="run_inspection_002",
                manifest_path=manifest,
                source_values=[f"fy25_frontdesk_daily={source}"],
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"][0]["code"], "HASH_MISMATCH")
        self.assertNotIn(str(source), json.dumps(result))

    def test_cli_reports_matching_non_xlsx_as_invalid_xlsx(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xlsx"
            source.write_bytes(b"not xlsx")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"sources": {"fy25_frontdesk_daily": {"filename": source.name, "sha256": digest}}}), encoding="utf-8")
            result = inspect_sources(
                run_id="run_inspection_003",
                manifest_path=manifest,
                source_values=[f"fy25_frontdesk_daily={source}"],
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"][0]["code"], "INVALID_XLSX")
        self.assertNotIn(str(source), json.dumps(result))

    def test_cli_requires_run_id_and_exact_source_set(self):
        bad_run = inspect_sources(run_id="manual", manifest_path=Path("missing"), source_values=[])
        self.assertEqual(bad_run["errors"][0]["code"], "RUN_ID_INVALID")

        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"sources": {"one": {"filename": "one.xlsx", "sha256": "0" * 64}}}), encoding="utf-8")
            result = inspect_sources(run_id="run_exact_sources", manifest_path=manifest, source_values=[])
        self.assertEqual(result["errors"][0]["code"], "SOURCE_BINDINGS_INVALID")

    def test_runtime_dependency_contract_stays_minimal_and_exact(self):
        project = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["requires-python"], ">=3.12")
        self.assertEqual(project["dependencies"], ["duckdb==1.5.5"])
        extras = project["optional-dependencies"]
        self.assertEqual(
            extras["test"],
            ["openpyxl==3.1.5", "Pillow==12.3.0", "python-dateutil==2.9.0.post0"],
        )
        self.assertEqual(
            extras["full"],
            [
                "openpyxl==3.1.5", "Pillow==12.3.0", "python-dateutil==2.9.0.post0",
                "playwright==1.62.0", "pexpect==4.9.0", "certifi==2026.7.22",
            ],
        )
        self.assertNotIn("ppt", extras)


if __name__ == "__main__":
    unittest.main()
