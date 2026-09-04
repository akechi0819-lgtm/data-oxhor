from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from interfaces.casebook import main


class CasebookPilotCliTests(unittest.TestCase):
    def _workspace(self, parent: Path) -> Path:
        root = parent / "customer"
        (root / "Work").mkdir(parents=True)
        (root / "Work" / "workspace.json").write_text(json.dumps({
            "schema_version": "bridge_alignment_workspace.v1",
            "company_id": "company_fixture",
            "pack_path": "Work/Pack/pack.json",
            "pack_ref": {"pack_id": "education_training_operations_cn", "pack_version": "1.0.0"},
            "current_snapshot_id": None,
        }), encoding="utf-8")
        return root

    def _run(self, argv: list[str]) -> tuple[int, dict]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_guide_routes_uninitialized_and_unsynced_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "missing"
            code, result = self._run(["guide", "--workspace", str(root)])
            self.assertEqual(2, code)
            self.assertEqual("casebook_pilot_result.v1", result["schema_version"])
            self.assertEqual("initialize_workspace", result["next_step"])
            root = self._workspace(Path(directory))
            code, result = self._run(["guide", "--workspace", str(root)])
            self.assertEqual(2, code)
            self.assertEqual("sync_data", result["next_step"])

    def test_case_verify_cli_returns_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            config = json.loads((root / "Work" / "workspace.json").read_text(encoding="utf-8"))
            config["current_snapshot_id"] = "snapshot_current"
            config["bridge_reference_path"] = "Work/Bridge/reference.json"
            (root / "Work" / "Bridge").mkdir()
            (root / "Work" / "Pack").mkdir()
            (root / "Work" / "Pack" / "pack.json").write_bytes(Path("workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json").read_bytes())
            bridge = json.loads(Path("artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_1_0.json").read_text(encoding="utf-8"))
            bridge["company_id"] = "company_fixture"
            (root / "Work" / "Bridge" / "reference.json").write_text(json.dumps(bridge), encoding="utf-8")
            (root / "Work" / "workspace.json").write_text(json.dumps(config), encoding="utf-8")
            source = root / "Work" / "evidence.txt"
            source.write_text("synthetic", encoding="utf-8")
            with patch("workspace_modeling.casebook.router.guide", return_value={"next_step": "analyze"}):
                code, result = self._run([
                    "case-create", "--workspace", str(root), "--case-id", "case_cli", "--primary-role", "operator",
                    "--question-category", "cash", "--question", "q", "--normalized-question", "q",
                    "--key-queries-json", "[]", "--evidence-json",
                    json.dumps([{"path": "Work/evidence.txt", "kind": "log", "referenced_source_ids": ["cash"]}]),
                    "--summary", "synthetic", "--created-by", "tester",
                ])
            self.assertEqual(0, code)
            self.assertEqual("casebook_pilot_result.v1", result["schema_version"])
            self.assertEqual("candidate_created", result["status"])
            code, result = self._run(["case-verify", "--workspace", str(root), "--case-id", "case_cli"])
            self.assertEqual(0, code)
            self.assertEqual("passed", result["status"])

    def test_case_capture_cli_accepts_workspace_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            config = json.loads((root / "Work" / "workspace.json").read_text(encoding="utf-8"))
            config["current_snapshot_id"] = "snapshot_current"
            config["bridge_reference_path"] = "Work/Bridge/reference.json"
            (root / "Work" / "Bridge").mkdir()
            (root / "Work" / "Pack").mkdir()
            (root / "Work" / "Pack" / "pack.json").write_bytes(Path("workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json").read_bytes())
            bridge = json.loads(Path("artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_1_0.json").read_text(encoding="utf-8"))
            bridge["company_id"] = "company_fixture"
            (root / "Work" / "Bridge" / "reference.json").write_text(json.dumps(bridge), encoding="utf-8")
            (root / "Work" / "workspace.json").write_text(json.dumps(config), encoding="utf-8")
            (root / "Work" / "evidence.txt").write_text("synthetic", encoding="utf-8")
            (root / "Work" / "capture.json").write_text(json.dumps({
                "schema_version": "casebook_capture.v1", "case_id": "case_capture_cli", "primary_role": "operator",
                "question_category": "cash", "question": "q", "normalized_question": "q", "key_queries": [],
                "evidence_sources": [{"path": "Work/evidence.txt", "kind": "log", "referenced_source_ids": ["cash"]}],
                "summary": "synthetic", "created_by": "tester",
            }), encoding="utf-8")
            with patch("workspace_modeling.casebook.router.guide", return_value={"next_step": "analyze"}):
                code, result = self._run(["case-capture", "--workspace", str(root), "--manifest", "Work/capture.json"])
            self.assertEqual(0, code)
            self.assertEqual("candidate_created", result["status"])


if __name__ == "__main__":
    unittest.main()
