import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/dirty_data"


class DirtyDataCorpusTests(unittest.TestCase):
    def setUp(self):
        self.corpus = json.loads((FIXTURES / "corpus.json").read_text(encoding="utf-8"))
        self.golden = json.loads((FIXTURES / "golden_cases.json").read_text(encoding="utf-8"))

    def test_corpus_has_two_confirmed_groups(self):
        self.assertEqual([group["case_id"] for group in self.corpus["groups"]], ["golden_registration_cash", "golden_work_orders"])
        self.assertEqual({source for group in self.corpus["groups"] for source in group["source_ids"]}, set(self.golden["sources"]))

    def test_external_sources_use_filename_and_hash_without_absolute_paths(self):
        for source in self.golden["sources"].values():
            self.assertEqual(set(source), {"filename", "sha256"})
            self.assertEqual(len(source["sha256"]), 64)
            self.assertNotIn("/", source["filename"])

    def test_registration_cash_contract_is_frozen(self):
        case = next(case for case in self.golden["cases"] if case["case_id"] == "golden_registration_cash")
        self.assertEqual(case["metric"]["included_business_forms"], ["报班", "报班-预收"])
        self.assertIsInstance(case["minimum_acceptance"]["fy25_frontdesk_daily"]["data_rows"], int)
        self.assertIsInstance(case["minimum_acceptance"]["fy27_frontdesk_daily"]["data_rows"], int)
        self.assertEqual(case["minimum_acceptance"]["fy25_frontdesk_daily"]["registration_cash"], "146126124.8")
        self.assertEqual(case["minimum_acceptance"]["fy27_frontdesk_daily"]["registration_cash"], "41200607.1")

    def test_work_order_contract_records_range_and_field_drift(self):
        case = next(case for case in self.golden["cases"] if case["case_id"] == "golden_work_orders")
        archived = case["minimum_acceptance"]["archived_work_orders"]
        self.assertIsInstance(archived["data_rows"], dict)
        self.assertEqual(set(archived["declared_dimensions"].values()), {"A1"})
        self.assertEqual(archived["date_fields"], {"FY24": "分配时间", "FY25": "分配日期", "FY26": "分配时间"})


if __name__ == "__main__":
    unittest.main()
