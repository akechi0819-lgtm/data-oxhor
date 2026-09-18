from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from tests.evidence_helpers import delivery
from workspace_modeling.casebook.router import guide, repeat_candidates
from workspace_modeling.casebook.service import confirm_case, create_case


class RouterTests(unittest.TestCase):
    def _config(self, root: Path, **updates: object) -> None:
        config = {
            "schema_version": "bridge_alignment_workspace.v1",
            "company_id": "company_fixture",
            "pack_path": "Work/Pack/pack.json",
            "pack_ref": {"pack_id": "education_training_operations_cn", "pack_version": "1.0.0"},
            "current_snapshot_id": None,
            "current_warehouse_path": None,
            "bridge_reference_path": None,
        }
        config.update(updates)
        path = root / "Work" / "workspace.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config), encoding="utf-8")

    def test_guide_priority_and_bridge_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "customer"
            self.assertEqual("initialize_workspace", guide(root=root)["next_step"])
            self._config(root)
            self.assertEqual("sync_data", guide(root=root)["next_step"])
            warehouse = root / "Work" / "Runs" / "warehouse.duckdb"
            pack = root / "Work" / "Pack" / "pack.json"
            pack.parent.mkdir(parents=True, exist_ok=True)
            pack.write_text("{}", encoding="utf-8")
            warehouse.parent.mkdir(parents=True, exist_ok=True)
            warehouse.write_bytes(b"placeholder")
            self._config(root, current_snapshot_id="snapshot_current", current_warehouse_path="Work/Runs/warehouse.duckdb")
            with patch("workspace_modeling.casebook.router.load_pack", return_value={"pack_id": "pack", "pack_version": "1.0.0"}):
                self.assertEqual("align_bridge", guide(root=root)["next_step"])

    def test_guide_analyze_requires_validated_explicit_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "customer"
            pack = root / "Work" / "Pack" / "pack.json"
            bridge = root / "Work" / "Bridge" / "reference.json"
            warehouse = root / "Work" / "Runs" / "warehouse.duckdb"
            for path in (pack, bridge, warehouse):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")
            self._config(
                root,
                pack_path="Work/Pack/pack.json",
                current_snapshot_id="snapshot_current",
                current_warehouse_path="Work/Runs/warehouse.duckdb",
                bridge_reference_path="Work/Bridge/reference.json",
            )
            valid_pack = {"pack_id": "pack", "pack_version": "1.0.0"}
            valid_bridge = {"bridge_id": "bridge", "bridge_version": "1.0.0", "company_id": "company_fixture"}
            with patch("workspace_modeling.casebook.router.load_pack", return_value=valid_pack), patch("workspace_modeling.casebook.router.load_bridge", return_value=valid_bridge), patch(
                "workspace_modeling.casebook.router.profile_snapshot", return_value=({}, {"snapshot_id": "snapshot_current"}, {})
            ), patch("workspace_modeling.casebook.router.validate_bridge", return_value={"status": "passed", "errors": []}):
                self.assertEqual("analyze", guide(root=root)["next_step"])

    def test_repeat_candidates_need_three_recent_confirmed_cases_and_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "customer"
            (root / "Work" / "Bridge").mkdir(parents=True)
            (root / "Work" / "Pack").mkdir(parents=True)
            bridge = json.loads(Path("artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_1_0.json").read_text(encoding="utf-8"))
            bridge["company_id"] = "company_fixture"
            (root / "Work" / "Bridge" / "reference.json").write_text(json.dumps(bridge), encoding="utf-8")
            (root / "Work" / "Pack" / "pack.json").write_bytes(Path("workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json").read_bytes())
            self._config(root, current_snapshot_id="snapshot_current", bridge_reference_path="Work/Bridge/reference.json")
            case_ids = []
            with patch("workspace_modeling.casebook.router.guide", return_value={"next_step": "analyze"}):
                for index in range(3):
                    case_id = f"case_repeat_{index}"
                    case_ids.append(case_id)
                    create_case(
                        root=root, case_id=case_id, primary_role="operator", question_category="cash",
                        question="Why did net cash decline?", normalized_question="net cash decline",
                        key_queries=["cash"], created_by="reviewer", summary="reviewed",
                        evidence_sources=[{"path": str(delivery(root).relative_to(root))}],
                    )
                    confirm_case(root=root, case_id=case_id, decided_by="reviewer", decision_note="confirmed")
                    path = root / "Work" / "Casebook" / "confirmed" / case_id / "case.json"
                    document = json.loads(path.read_text(encoding="utf-8"))
                    document["decided_at"] = (datetime.now(UTC) - timedelta(days=index)).isoformat().replace("+00:00", "Z")
                    path.write_text(json.dumps(document), encoding="utf-8")
            evaluation_path = root / "Work" / "Evaluation" / "sessions" / "evaluation_1" / "evaluation.json"
            evaluation_path.parent.mkdir(parents=True)
            evaluation_path.write_text(json.dumps({
                "schema_version": "pilot_evaluation.v1", "evaluation_id": "evaluation_1", "company_id": "company_fixture",
                "status": "completed", "cards": [{"card_id": "card_1", "matched_case_ids": [*case_ids], "feedback": "useful", "acceptance": {"passed": True}, "score": None, "reviewed_by": "reviewer", "reviewed_at": "2026-08-18T00:00:00Z"}],
            }), encoding="utf-8")
            result = repeat_candidates(root=root)
            self.assertEqual("skill_or_template_candidate", result["candidates"][0]["suggestion"])
            self.assertEqual(3, result["candidates"][0]["case_count"])
            evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
            evaluation["cards"][0].pop("reviewed_by")
            evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
            self.assertEqual([], repeat_candidates(root=root)["candidates"])


if __name__ == "__main__":
    unittest.main()
