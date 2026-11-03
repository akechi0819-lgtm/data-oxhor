import json
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile
from pathlib import Path
from xml.etree import ElementTree

from openpyxl import Workbook

from dashboard_product.management.advertising_sources import load_sources


class SemSourcesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        book = Workbook()
        sheet = book.active
        sheet.title = "代投-欧亚"
        for row in [("时间", "消费", "现金消费"), ("2026-10-12", 200, 123.456),
                    ("2026-10-13", None, 0), ("2026-10-14", 0, 0),
                    ("2026-10-26", 999, 888)]:
            sheet.append(row)
        total = book.create_sheet("SEM总计")
        total.append(["时间", "消费", "现金消费"])
        total.append(["2026-10-12", 9999, 9999])
        book.save(self.root / "sem.xlsx")
        book.close()
        self.entry = {"source_id": "sem", "path": "sem.xlsx", "kind": "sem_daily",
                      "start_date": "2026-10-12", "end_date": "2026-10-25",
                      "sheets": {"代投-欧亚": {"business_line": "abroad", "business_group": "留学整体", "platform": "百度"}}}

    def load(self):
        path = self.root / "sources.json"
        path.write_text(json.dumps({"sources": [self.entry]}, ensure_ascii=False))
        return load_sources(path)

    def test_reported_cash_zero_is_distinct_from_missing_and_future_excluded(self):
        costs = self.load()
        self.assertEqual([r["amount"] for r in costs["rows"]], [123.46, 0, 0])
        self.assertEqual(costs["rows"][0]["raw_cash_consume"], "123.456")
        self.assertEqual(costs["rows"][1]["amount_status"], "reported_zero")
        self.assertEqual(len(costs["sources"]), 1)
        self.assertEqual(costs["sources"][0]["source_id"], "sem:代投-欧亚")

    def test_parent_total_cannot_be_mapped_as_leaf(self):
        self.entry["sheets"]["SEM总计"] = self.entry["sheets"]["代投-欧亚"]
        with self.assertRaisesRegex(ValueError, "总表"):
            self.load()

    def test_missing_sheet_stops_instead_of_silent_omission(self):
        self.entry["sheets"]["missing"] = self.entry["sheets"]["代投-欧亚"]
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.load()

    def test_unallocated_training_cost_stays_whole(self):
        self.entry["sheets"]["代投-欧亚"] = {"business_line": "training", "business_group": "语培整体", "platform": "百度"}
        self.assertTrue(all(r["business_group"] == "语培整体" for r in self.load()["rows"]))

    def test_blank_cash_is_missing_when_no_native_value_is_reported(self):
        book = Workbook()
        sheet = book.active
        sheet.title = "代投-欧亚"
        sheet.append(["时间", "消费", "现金消费"])
        sheet.append(["2026-10-12", None, None])
        book.save(self.root / "sem.xlsx")
        book.close()
        costs = self.load()
        self.assertEqual(len(costs["rows"]), 1)
        self.assertIsNone(costs["rows"][0]["amount"])
        self.assertIsNone(costs["rows"][0]["raw_consume"])
        self.assertEqual(costs["rows"][0]["amount_status"], "missing_cash_consumption")
        self.assertEqual(costs["sources"][0]["missing_amount_dates"], ["2026-10-12"])
        self.assertEqual(costs["sources"][0]["start_date"], "2026-10-12")

    def test_cash_value_is_used_even_if_consumption_column_is_blank(self):
        book = Workbook()
        sheet = book.active
        sheet.title = "代投-欧亚"
        sheet.append(["时间", "消费", "现金消费"])
        sheet.append(["2026-10-12", None, 42])
        book.save(self.root / "sem.xlsx")
        book.close()
        row = self.load()["rows"][0]
        self.assertEqual(row["amount"], 42)
        self.assertIsNone(row["raw_consume"])

    def test_formula_cached_zero_from_blank_consumption_is_not_a_reported_zero(self):
        book = Workbook()
        sheet = book.active
        sheet.title = "代投-欧亚"
        sheet.append(["时间", "消费", "现金消费"])
        sheet.append(["2026-10-12", None, "=B2/2"])
        book.save(self.root / "sem.xlsx")
        book.close()
        native = self.root / "sem.xlsx"
        with ZipFile(native) as source:
            members = {name: source.read(name) for name in source.namelist()}
        worksheet = ElementTree.fromstring(members["xl/worksheets/sheet1.xml"])
        namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        cached_cash = worksheet.find(f".//{namespace}c[@r='C2']/{namespace}v")
        self.assertIsNotNone(cached_cash)
        cached_cash.text = "0"
        members["xl/worksheets/sheet1.xml"] = ElementTree.tostring(worksheet)
        rewritten = self.root / "sem-rewritten.xlsx"
        with ZipFile(rewritten, "w", ZIP_DEFLATED) as target:
            for name, content in members.items():
                target.writestr(name, content)
        rewritten.replace(native)

        row = self.load()["rows"][0]
        self.assertIsNone(row["amount"])
        self.assertEqual(row["raw_cash_consume"], "0")
        self.assertEqual(row["raw_cash_formula"], "=B2/2")
        self.assertEqual(row["amount_status"], "formula_derived_from_blank_consumption")

    def test_missing_date_rows_are_reported_without_becoming_zero_rows(self):
        book = Workbook()
        sheet = book.active
        sheet.title = "代投-欧亚"
        sheet.append(["时间", "消费", "现金消费"])
        sheet.append(["2026-10-12", 10, 8])
        sheet.append(["2026-10-14", 20, 16])
        book.save(self.root / "sem.xlsx")
        book.close()
        self.entry["end_date"] = "2026-10-14"
        source = self.load()["sources"][0]
        self.assertEqual(source["missing_date_rows"], ["2026-10-13"])
        self.assertEqual(source["coverage_state"], "partial")


if __name__ == "__main__":
    unittest.main()
