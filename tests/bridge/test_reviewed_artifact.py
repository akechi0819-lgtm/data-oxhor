from __future__ import annotations

import unittest
from pathlib import Path

from business_pack import load_pack
from company_bridge.service import load_bridge, validate_bridge


class ReviewedCompanyBridgeArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[2]

    def test_current_bi_operations_bridge_validates(self) -> None:
        document = load_bridge(self.root / "artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_0_0.json")
        validation = validate_bridge(document, pack=load_pack())
        self.assertEqual("passed", validation["status"])
        self.assertEqual("bridge_bi_operations", validation["bridge_id"])

    def test_current_bridge_is_pack_linked_and_snapshot_independent(self) -> None:
        bridge = load_bridge(
            self.root / "artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_0_0.json"
        )
        validation = validate_bridge(bridge, pack=load_pack())

        self.assertEqual("passed", validation["status"])
        self.assertEqual("1.0.0", bridge["bridge_version"])
        self.assertEqual(2, validation["counts"]["source_contracts"])
        self.assertEqual(19, validation["counts"]["field_mappings"])
        self.assertEqual(2, validation["counts"]["normalization_rules"])
        self.assertEqual(3, validation["counts"]["overrides"])
        self.assertEqual(1, validation["counts"]["unresolved"])
        self.assertNotIn("snapshot_ref", bridge)
        relations = {
            item.get("relation")
            for category in ("source_contracts", "field_mappings", "normalization_rules")
            for item in bridge[category]
            if item.get("relation")
        }
        self.assertTrue(all(relation.startswith("landing.") for relation in relations))


if __name__ == "__main__":
    unittest.main()
