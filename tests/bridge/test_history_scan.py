from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import openpyxl

from business_pack import load_pack
from company_bridge.history import scan_history
from company_bridge.service import validate_candidate_set


class HistoryScanTests(unittest.TestCase):
    def test_scan_emits_candidates_and_rejections_without_formal_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "super_agent"
            output = Path(directory) / "candidates.json"
            (root / "data_layer/docs").mkdir(parents=True)
            (root / "data_layer/storage/raw/bi_downloads").mkdir(parents=True)
            (root / "data_layer/storage/marts").mkdir(parents=True)
            (root / "workers/docs").mkdir(parents=True)
            (root / "data_layer/docs/业务口径与Taxonomy.md").write_text("# 业务口径\n", encoding="utf-8")
            (root / "data_layer/sql").mkdir(parents=True)
            (root / "data_layer/sql/weekly_analysis.sql").write_text("SELECT * FROM clean.cash_ledger;\n", encoding="utf-8")
            taxonomy = root / "methodology/config/business_taxonomy/business_taxonomy.yaml"
            taxonomy.parent.mkdir(parents=True)
            taxonomy.write_text(
                """cash_headcount_rule:\n  default_student_type: 新生\nproduct_taxonomy:\n  rows:\n    - raw_product: 剑五\n      product: 剑五\n      product_line: 提能线\nconditional_product_rules:\n  - when:\n      raw_product: 剑五\n      class_type_in:\n        - KET\n        - PET\n    set:\n      product_from: class_type\n      product_line: 提能线\n      product_segment: 小高\n      product_group_from: class_type\n""",
                encoding="utf-8",
            )
            (root / "data_layer/storage/raw/bi_downloads/现金表_20260814.csv").write_text(
                "业务日期,校区,报入现金收入,学员编号\n2026-08-14,南开,100,student-1\n",
                encoding="utf-8",
            )
            (root / "data_layer/storage/marts/weekly_inputs.csv").write_text(
                "产品线,净现金差额\n提能线,-100\n",
                encoding="utf-8",
            )
            (root / "workers/docs/周报周会工作流.md").write_text("# workflow\n", encoding="utf-8")
            daily = root / "data_layer/storage/raw/jenny/报名系统操作明细/20260814/报名系统操作明细_20260814.xlsx"
            daily.parent.mkdir(parents=True)
            workbook = openpyxl.Workbook()
            main_sheet = workbook.active
            main_sheet.title = "报名系统操作明细"
            main_sheet.append(["业务形式", "具体原因", "实缴金额", "备注"])
            main_sheet.append(["退班退费", "孩子不上了，退费", -1200, ""])
            main_sheet.append(["转出", "退班重报", -800, ""])
            transfer_sheet = workbook.create_sheet("挂转退")
            transfer_sheet.append(["业务形式", "具体原因", "退班金额", "转班金额"])
            transfer_sheet.append(["转出", "转班", -500, 500])
            refund_sheet = workbook.create_sheet("小语种退费")
            refund_sheet.append(["业务类型", "退费金额", "操作备注"])
            refund_sheet.append(["退费", 300, "退款"])
            workbook.save(daily)
            before = (root / "data_layer/storage/marts/weekly_inputs.csv").read_bytes()

            document = scan_history(
                root=root,
                company_id="company_super_agent",
                candidate_set_id="scan_super_agent_test",
                pack=load_pack(),
                output_path=output,
            )

            validation = validate_candidate_set(document, pack=load_pack(), require_role="historical_scan")
            self.assertEqual("passed", validation["status"])
            self.assertEqual("historical_scan", document["candidate_set_role"])
            self.assertTrue(document["candidates"])
            self.assertTrue(any(item["candidate_type"] == "source_contract" for item in document["candidates"]))
            self.assertTrue(any(item["status"] == "proposed" for item in document["candidates"]))
            rejection_codes = {item["reason_code"] for item in document["rejections"]}
            self.assertIn("SINGLE_ANALYSIS_CONCLUSION", rejection_codes)
            self.assertIn("SKILL_CONTENT", rejection_codes)
            self.assertTrue(any(item["source_locator"] == "data_layer/sql/weekly_analysis.sql" and item["reason_code"] == "ANALYSIS_REPORT" for item in document["rejections"]))
            daily_rules = [
                item
                for item in document["candidates"]
                if item["candidate_type"] == "normalization_rule" and "signup_ops" in str(item["proposed_mapping_or_rule"])
            ]
            self.assertGreaterEqual(len(daily_rules), 4)
            self.assertTrue(any(item["proposed_mapping_or_rule"].get("target_id") == "cash.net_cash" for item in daily_rules))
            self.assertTrue(any(item["proposed_mapping_or_rule"].get("parameters", {}).get("normalized_value") == "refund" for item in daily_rules))
            self.assertTrue(any(item["proposed_mapping_or_rule"].get("parameters", {}).get("normalized_value") == "adjustment" for item in daily_rules))
            self.assertTrue(any("enum.student_type" in item["source_locator"] for item in document["rejections"]))
            self.assertTrue(any("cash_headcount_rule" in item["source_locator"] for item in document["rejections"]))
            self.assertFalse(
                any(
                    item["candidate_type"] == "enum_mapping"
                    and item["proposed_mapping_or_rule"].get("field_name") == "student_type"
                    for item in document["candidates"]
                )
            )
            self.assertFalse(
                any(
                    item["candidate_type"] == "override"
                    and item["proposed_mapping_or_rule"].get("target_id") == "cash.payer_count"
                    for item in document["candidates"]
                )
            )
            self.assertFalse(
                any(
                    item["candidate_type"] == "field_mapping"
                    and item["proposed_mapping_or_rule"].get("source_id") == "br_work_orders"
                    and item["proposed_mapping_or_rule"].get("field_name") == "project_name"
                    for item in document["candidates"]
                )
            )
            conditional = [
                item
                for item in document["candidates"]
                if item["candidate_type"] == "normalization_rule"
                and "conditional_product_rules" in item["source_locator"]
            ]
            self.assertEqual(1, len(conditional))
            self.assertEqual(["KET", "PET"], conditional[0]["proposed_mapping_or_rule"]["parameters"]["condition"]["class_type_in"])
            self.assertFalse(
                any(
                    item["candidate_type"] == "override"
                    and item["proposed_mapping_or_rule"].get("key") == "default_student_type"
                    for item in document["candidates"]
                )
            )
            self.assertTrue(any("default_student_type" in item["source_locator"] for item in document["rejections"]))
            self.assertNotIn("bridge_id", document)
            self.assertEqual(before, (root / "data_layer/storage/marts/weekly_inputs.csv").read_bytes())
            self.assertFalse(output.exists())

    def test_scan_never_accepts_an_output_inside_historical_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "super_agent"
            root.mkdir()
            with self.assertRaises(ValueError):
                scan_history(
                    root=root,
                    company_id="company_super_agent",
                    candidate_set_id="scan_inside_root",
                    pack=load_pack(),
                    output_path=root / "candidates.json",
                )


if __name__ == "__main__":
    unittest.main()
