from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from workspace_modeling.business_pack import load_pack
from workspace_modeling.company_bridge.service import load_bridge, validate_bridge


class ReviewedCompanyBridgeArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[2]

    def test_current_bi_operations_bridge_validates(self) -> None:
        document = load_bridge(self.root / "artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json")
        validation = validate_bridge(document, pack=load_pack())
        self.assertEqual("passed", validation["status"])
        self.assertEqual("bridge_bi_operations", validation["bridge_id"])

    def test_current_bridge_is_pack_linked_and_snapshot_independent(self) -> None:
        bridge = load_bridge(
            self.root / "artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json"
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

    def test_dashboard_work_order_ids_stay_text_and_manifest_matches(self) -> None:
        config = json.loads(
            (self.root / "dashboard_product/config/saved_queries.json").read_text(encoding="utf-8")
        )
        declared_query = next(item for item in config["queries"] if item["query_id"] == "dashboard_actuals")
        query_path = (
            self.root / config["workspace"] / "Work/SavedQueries"
            / declared_query["query_id"] / declared_query["version"] / "query.sql"
        )
        query = query_path.read_text(encoding="utf-8")
        manifest = json.loads(query_path.with_name("manifest.json").read_text(encoding="utf-8"))
        tracked = (self.root / "dashboard_product/sql/dashboard_actuals.sql").read_text(encoding="utf-8")
        self.assertEqual(query, tracked)

        self.assertIn("NULLIF(TRIM(ID),'') AS work_order_id", query)
        self.assertIn("NULLIF(TRIM(工单ID),'') AS work_order_id", query)
        self.assertNotIn("column_", query)
        self.assertNotIn("TRY_CAST(TRIM(ID)", query)
        self.assertNotIn("TRY_CAST(TRIM(工单ID)", query)
        self.assertIn("AS DECIMAL(38,2)", query)
        self.assertEqual(hashlib.sha256(query_path.read_bytes()).hexdigest(), manifest["sha256"])


if __name__ == "__main__":
    unittest.main()
