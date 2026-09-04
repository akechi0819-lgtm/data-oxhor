from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from workspace_modeling.business_pack import describe_pack, load_pack, validate_pack
from interfaces.business_pack import main


class EducationBusinessPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = load_pack()

    def test_shipped_pack_is_valid_and_has_expected_scope(self) -> None:
        result = validate_pack(self.pack)

        self.assertEqual("passed", result["status"])
        self.assertEqual("education_training_operations_cn", result["pack_id"])
        self.assertEqual(
            {
                "concepts": 28,
                "dimensions": 26,
                "metrics": 20,
                "taxonomies": 2,
                "journeys": 3,
                "funnels": 3,
                "playbooks": 7,
                "references": 5,
            },
            result["counts"],
        )

    def test_pack_contains_three_distinct_business_journeys(self) -> None:
        journeys = {item["journey_id"]: item for item in self.pack["journeys"]}

        self.assertEqual(
            {"journey.acquisition_conversion", "journey.contract_cash", "journey.service_fulfillment"},
            set(journeys),
        )
        self.assertNotEqual(
            journeys["journey.contract_cash"]["stages"],
            journeys["journey.service_fulfillment"]["stages"],
        )
        fulfillment_concepts = {
            stage["concept_id"]
            for stage in journeys["journey.service_fulfillment"]["stages"]
        }
        self.assertNotIn("revenue.recognition_transfer", fulfillment_concepts)

    def test_net_cash_and_revenue_are_not_treated_as_equivalent(self) -> None:
        concepts = {item["concept_id"]: item for item in self.pack["concepts"]}
        playbooks = {item["playbook_id"]: item for item in self.pack["playbooks"]}
        statements = " ".join(
            hypothesis["statement"]
            for hypothesis in playbooks["diagnose.cash_vs_revenue"]["hypotheses"]
        )

        self.assertIn("采用不同计量基础", concepts["cash.net_cash"]["definition"])
        self.assertIn("不能单独推出已确认收入下降", concepts["cash.net_cash"]["definition"])
        self.assertIn("仍可能", statements)
        self.assertIn("未必同步增长", statements)

    def test_refund_diagnostics_only_use_defined_metrics(self) -> None:
        metrics = {item["metric_id"]: item for item in self.pack["metrics"]}
        playbooks = {item["playbook_id"]: item for item in self.pack["playbooks"]}
        refund_metrics = set(playbooks["diagnose.refund_growth"]["metric_ids"])

        self.assertTrue(refund_metrics <= set(metrics))
        self.assertIn("cash.refund_transaction_count", refund_metrics)
        self.assertIn("cash.average_refund_amount", refund_metrics)
        self.assertIn("cash.cohort_refund_student_rate", refund_metrics)
        cohort_rate = metrics["cash.cohort_refund_student_rate"]
        self.assertIn("不等同于同期退款现金压力比", cohort_rate["definition"])
        self.assertIn("cash.payment", cohort_rate["required_concept_ids"])
        self.assertNotIn("transaction.refund_reason", cohort_rate["compatible_dimension_ids"])

    def test_traffic_diagnostic_does_not_claim_to_explain_recognized_revenue(self) -> None:
        playbooks = {item["playbook_id"]: item for item in self.pack["playbooks"]}
        traffic = playbooks["diagnose.traffic_vs_conversion"]

        self.assertNotIn("已确认收入", traffic["use_when"])
        self.assertNotIn("revenue.recognized_revenue", traffic["metric_ids"])
        self.assertTrue(
            all(
                "报名或付款人数" in hypothesis["statement"]
                for hypothesis in traffic["hypotheses"]
            )
        )

    def test_validator_rejects_duplicate_ids_and_unknown_references(self) -> None:
        invalid = copy.deepcopy(self.pack)
        invalid["metrics"][1]["metric_id"] = invalid["metrics"][0]["metric_id"]
        invalid["playbooks"][0]["metric_ids"].append("cash.missing_metric")

        result = validate_pack(invalid)
        codes = {error["code"] for error in result["errors"]}

        self.assertEqual("failed", result["status"])
        self.assertIn("ID_DUPLICATE", codes)
        self.assertIn("REFERENCE_UNKNOWN", codes)

    def test_validator_rejects_missing_analysis_content_and_time_reference(self) -> None:
        invalid = copy.deepcopy(self.pack)
        invalid["metrics"][0].pop("time_dimension_ids")
        invalid["playbooks"][0]["hypotheses"][0]["statement"] = ""
        invalid["taxonomies"][0]["members"] = []

        result = validate_pack(invalid)
        paths = {error["path"] for error in result["errors"]}

        self.assertEqual("failed", result["status"])
        self.assertIn("metrics.cash.gross_inflow.time_dimension_ids", paths)
        self.assertIn("playbooks.diagnose.net_cash_gap.hypotheses[0].statement", paths)
        self.assertIn("taxonomies.customer.lifecycle_type.members", paths)

    def test_describe_returns_inventory_without_expanding_definitions(self) -> None:
        result = describe_pack()

        self.assertEqual("passed", result["status"])
        self.assertEqual(
            {"metric_id", "name"},
            set(result["inventory"]["metrics"][0]),
        )

    def test_cli_reports_invalid_json_as_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("{", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["validate", "--pack", str(path)])

        result = json.loads(output.getvalue())
        self.assertEqual(1, exit_code)
        self.assertEqual("PACK_JSON_INVALID", result["errors"][0]["code"])


if __name__ == "__main__":
    unittest.main()
