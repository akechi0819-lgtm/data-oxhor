import json
import tempfile
import unittest
from pathlib import Path

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

    def test_cash_leaf_blank_is_confirmed_zero_and_future_excluded(self):
        costs = self.load()
        self.assertEqual([r["amount"] for r in costs["rows"]], [123.46, 0, 0])
        self.assertEqual(costs["rows"][0]["raw_cash_consume"], "123.456")
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

    def test_confirmed_blank_leaf_is_zero_even_without_cash_formula(self):
        book = Workbook()
        sheet = book.active
        sheet.title = "代投-欧亚"
        sheet.append(["时间", "消费", "现金消费"])
        sheet.append(["2026-10-12", None, None])
        book.save(self.root / "sem.xlsx")
        book.close()
        costs = self.load()
        self.assertEqual(len(costs["rows"]), 1)
        self.assertEqual(costs["rows"][0]["amount"], 0)
        self.assertIsNone(costs["rows"][0]["raw_consume"])
        self.assertEqual(costs["sources"][0]["start_date"], "2026-10-12")

    def test_blank_consumption_cannot_erase_nonzero_cash(self):
        book = Workbook()
        sheet = book.active
        sheet.title = "代投-欧亚"
        sheet.append(["时间", "消费", "现金消费"])
        sheet.append(["2026-10-12", None, 42])
        book.save(self.root / "sem.xlsx")
        book.close()
        with self.assertRaisesRegex(ValueError, "现金费用非0"):
            self.load()


if __name__ == "__main__":
    unittest.main()
