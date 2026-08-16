from __future__ import annotations

import json
import unittest
from pathlib import Path

from business_pack import load_pack
from company_bridge.service import load_bridge, validate_bridge, validate_candidate_set


class ReviewedCompanyBridgeArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[2]

    def test_current_reviewed_input_uses_landing_contracts(self) -> None:
        document = json.loads(
            (
                self.root
                / "artifacts/company_bridge/reviewed/super_agent_confirmed_review_20260816_v3.json"
            ).read_text(encoding="utf-8")
        )
        validation = validate_candidate_set(
            document,
            pack=load_pack(),
            require_role="confirmed_review",
        )

        self.assertEqual("passed", validation["status"])
        self.assertEqual(119, validation["candidate_count"])
        relations = {
            item["proposed_mapping_or_rule"].get("relation")
            for item in document["candidates"]
            if item["proposed_mapping_or_rule"].get("relation")
        }
        self.assertTrue(all(relation.startswith("landing.") for relation in relations))
        payer_override = next(
            item
            for item in document["candidates"]
            if item["candidate_id"] == "cand_review_payer_identity_basis"
        )
        self.assertEqual("customer.student", payer_override["proposed_mapping_or_rule"]["value"])

    def test_current_bridge_is_pack_linked_and_snapshot_independent(self) -> None:
        bridge = load_bridge(
            self.root / "artifacts/company_bridge/bridges/company_bridge.v1_2_0.json"
        )
        validation = validate_bridge(bridge, pack=load_pack())

        self.assertEqual("passed", validation["status"])
        self.assertEqual("1.2.0", bridge["bridge_version"])
        self.assertEqual(3, validation["counts"]["source_contracts"])
        self.assertEqual(10, validation["counts"]["field_mappings"])
        self.assertEqual(105, validation["counts"]["normalization_rules"])
        self.assertEqual(1, validation["counts"]["overrides"])
        self.assertEqual(0, validation["counts"]["unresolved"])
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
