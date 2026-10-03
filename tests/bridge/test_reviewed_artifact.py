from __future__ import annotations

import unittest
from pathlib import Path

from workspace_modeling.business_pack import load_pack
from workspace_modeling.company_bridge.service import load_bridge, validate_bridge


class ReviewedCompanyBridgeArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[2]

    def test_current_bi_operations_bridge_validates(self) -> None:
        document = load_bridge(self.root / "tests/fixtures/company_bridge/company_bridge.bi_operations.v1_2_0.json")
        validation = validate_bridge(document, pack=load_pack())
        self.assertEqual("passed", validation["status"])
        self.assertEqual("bridge_bi_operations", validation["bridge_id"])

    def test_current_bridge_is_pack_linked_and_snapshot_independent(self) -> None:
        bridge = load_bridge(
            self.root / "tests/fixtures/company_bridge/company_bridge.bi_operations.v1_2_0.json"
        )
        validation = validate_bridge(bridge, pack=load_pack())

        self.assertEqual("passed", validation["status"])
        self.assertEqual("1.2.0", bridge["bridge_version"])
        self.assertEqual(2, validation["counts"]["source_contracts"])
        self.assertEqual(20, validation["counts"]["field_mappings"])
        self.assertEqual(0, validation["counts"]["normalization_rules"])
        self.assertEqual(6, validation["counts"]["overrides"])
        self.assertEqual(1, validation["counts"]["unresolved"])
        self.assertNotIn("snapshot_ref", bridge)
        relations = {
            item.get("relation")
            for category in ("source_contracts", "field_mappings", "normalization_rules")
            for item in bridge[category]
            if item.get("relation")
        }
        self.assertTrue(all(relation.startswith("landing.") for relation in relations))

    def test_dashboard_work_order_ids_stay_text(self) -> None:
        # Unit tests run from a source checkout without a private customer registry.
        query_path = self.root / "dashboard_product/sql/dashboard_actuals.sql"
        query = query_path.read_text(encoding="utf-8")

        self.assertIn("NULLIF(TRIM(ID),'') AS work_order_id", query)
        self.assertIn("NULLIF(TRIM(工单ID),'') AS work_order_id", query)
        self.assertNotIn("column_", query)
        self.assertNotIn("TRY_CAST(TRIM(ID)", query)
        self.assertNotIn("TRY_CAST(TRIM(工单ID)", query)
        self.assertIn("AS DECIMAL(38,2)", query)


if __name__ == "__main__":
    unittest.main()
