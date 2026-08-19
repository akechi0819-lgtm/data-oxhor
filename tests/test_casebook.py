from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from casebook.service import (
    CasebookError,
    capture_case,
    confirm_case,
    create_case,
    reject_case,
    search_cases,
    supersede_case,
    verify_case,
)


class CasebookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_root = Path("tests/fixtures/casebook").resolve()

    def _workspace(self, parent: Path, company_id: str = "company_fixture", snapshot_id: str = "snapshot_current") -> Path:
        root = parent / company_id
        (root / "Work" / "Bridge").mkdir(parents=True)
        (root / "Work" / "Pack").mkdir(parents=True)
        (root / "Work" / "Runs" / "evidence").mkdir(parents=True)
        bridge = json.loads(Path("artifacts/company_bridge/bridges/company_bridge.v1_2_0.json").read_text(encoding="utf-8"))
        bridge["company_id"] = company_id
        (root / "Work" / "Bridge" / "reference.json").write_text(json.dumps(bridge), encoding="utf-8")
        shutil.copyfile("business_pack/packs/education_training_operations_cn/pack.json", root / "Work" / "Pack" / "pack.json")
        (root / "Work" / "workspace.json").write_text(json.dumps({
            "schema_version": "bridge_alignment_workspace.v1",
            "company_id": company_id,
            "pack_path": "Work/Pack/pack.json",
            "pack_ref": {"pack_id": "education_training_operations_cn", "pack_version": "1.0.0"},
            "bridge_reference_path": "Work/Bridge/reference.json",
            "current_snapshot_id": snapshot_id,
            "current_warehouse_path": "Work/Runs/run_current/data/snapshots/snapshot_current/warehouse.duckdb",
            "used_snapshot_ids": [snapshot_id],
        }), encoding="utf-8")
        shutil.copyfile(self.fixture_root / "query-result.json", root / "Work" / "Runs" / "evidence" / "query-result.json")
        shutil.copyfile(self.fixture_root / "query.sql", root / "Work" / "Runs" / "evidence" / "query.sql")
        return root

    def _create(self, root: Path, case_id: str, *, role: str = "operator", category: str = "cash_diagnosis", supersedes: str | None = None) -> None:
        with patch("casebook.router.guide", return_value={"next_step": "analyze"}):
            create_case(
                root=root, case_id=case_id, primary_role=role, question_category=category,
                question="Why did net cash decline?", normalized_question="net cash decline diagnosis",
                key_queries=["cash_by_campus"], created_by="reviewer", summary="The decline needs a current Snapshot query.",
                evidence_sources=[
                    {"path": "Work/Runs/evidence/query-result.json", "kind": "query_result", "referenced_source_ids": ["cash"]},
                    {"path": "Work/Runs/evidence/query.sql", "kind": "sql", "referenced_source_ids": ["cash"]},
                ],
                supersedes=supersedes,
            )

    def test_create_copies_evidence_and_verify_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            self._create(root, "case_cash_decline")
            case_path = root / "Work" / "Casebook" / "candidates" / "case_cash_decline"
            self.assertEqual("passed", verify_case(root=root, case_id="case_cash_decline")["status"])
            (case_path / "evidence" / "1-query-result.json").write_text("tampered", encoding="utf-8")
            verification = verify_case(root=root, case_id="case_cash_decline")
            self.assertEqual("failed", verification["status"])
            self.assertEqual("EVIDENCE_HASH_MISMATCH", verification["errors"][0]["code"])

    def test_capture_manifest_creates_candidate_through_existing_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            manifest = root / "Work" / "capture.json"
            manifest.write_text(json.dumps({
                "schema_version": "casebook_capture.v1", "case_id": "case_captured",
                "primary_role": "operator", "question_category": "cash_diagnosis",
                "question": "Why did net cash decline?", "normalized_question": "net cash decline diagnosis",
                "key_queries": ["cash_by_campus"], "evidence_sources": [{
                    "path": "Work/Runs/evidence/query-result.json", "kind": "query_result",
                    "referenced_source_ids": ["cash"],
                }], "summary": "Re-run the current Snapshot query before stating a conclusion.",
                "created_by": "reviewer",
            }), encoding="utf-8")
            with patch("casebook.router.guide", return_value={"next_step": "analyze"}):
                result = capture_case(root=root, manifest_path="Work/capture.json")
            self.assertEqual("candidate_created", result["status"])

    def test_capture_manifest_rejects_missing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            (root / "Work" / "capture.json").write_text(json.dumps({"schema_version": "casebook_capture.v1"}), encoding="utf-8")
            with self.assertRaises(CasebookError) as captured:
                capture_case(root=root, manifest_path="Work/capture.json")
            self.assertEqual("CAPTURE_FIELDS_MISSING", captured.exception.code)

    def test_confirmed_search_is_scoped_and_marks_stale_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory), snapshot_id="snapshot_new")
            self._create(root, "case_current", role="operator")
            confirm_case(root=root, case_id="case_current", decided_by="reviewer", decision_note="confirmed evidence")
            results = search_cases(root=root, company_id="company_fixture", primary_role="operator")
            self.assertEqual(["case_current"], [item["case_id"] for item in results["cases"]])
            self.assertFalse(results["cases"][0]["stale_for_current_snapshot"])
            config = json.loads((root / "Work" / "workspace.json").read_text(encoding="utf-8"))
            config["current_snapshot_id"] = "snapshot_later"
            (root / "Work" / "workspace.json").write_text(json.dumps(config), encoding="utf-8")
            stale = search_cases(root=root, company_id="company_fixture", primary_role="operator")["cases"]
            self.assertTrue(stale[0]["stale_for_current_snapshot"])
            self.assertEqual([], search_cases(root=root, company_id="company_fixture", primary_role="advisor")["cases"])
            with self.assertRaises(CasebookError) as captured:
                search_cases(root=root, company_id="another_company", primary_role="operator")
            self.assertEqual("COMPANY_SCOPE_MISMATCH", captured.exception.code)

    def test_confirmed_search_rejects_case_directory_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = self._workspace(parent)
            self._create(root, "case_external")
            confirm_case(root=root, case_id="case_external", decided_by="reviewer", decision_note="confirmed")
            confirmed_case = root / "Work" / "Casebook" / "confirmed" / "case_external"
            outside_case = parent / "outside-case"
            shutil.move(str(confirmed_case), outside_case)
            confirmed_case.symlink_to(outside_case, target_is_directory=True)
            with self.assertRaises(CasebookError) as captured:
                search_cases(root=root, company_id="company_fixture", primary_role="operator")
            self.assertEqual("PATH_OUTSIDE_WORKSPACE", captured.exception.code)

    def test_reject_and_supersede_require_the_prescribed_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            self._create(root, "case_rejected")
            reject_case(root=root, case_id="case_rejected", decided_by="reviewer", decision_note="insufficient scope")
            self.assertTrue((root / "Work" / "Casebook" / "rejected" / "case_rejected").is_dir())
            with self.assertRaises(CasebookError) as captured:
                confirm_case(root=root, case_id="case_rejected", decided_by="reviewer", decision_note="cannot revise")
            self.assertEqual("CASE_IMMUTABLE", captured.exception.code)
            self._create(root, "case_old")
            confirm_case(root=root, case_id="case_old", decided_by="reviewer", decision_note="confirmed")
            self._create(root, "case_new", supersedes="case_old")
            confirm_case(root=root, case_id="case_new", decided_by="reviewer", decision_note="confirmed")
            supersede_case(root=root, case_id="case_old", superseding_case_id="case_new", decided_by="reviewer", decision_note="revised analysis")
            old = json.loads((root / "Work" / "Casebook" / "superseded" / "case_old" / "case.json").read_text(encoding="utf-8"))
            new = json.loads((root / "Work" / "Casebook" / "confirmed" / "case_new" / "case.json").read_text(encoding="utf-8"))
            self.assertEqual("case_new", old["superseded_by"])
            self.assertEqual("case_old", new["supersedes"])

    def test_create_rejects_unsafe_paths_and_missing_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            with self.assertRaises(CasebookError) as captured:
                with patch("casebook.router.guide", return_value={"next_step": "analyze"}):
                    create_case(
                        root=root, case_id="case_unsafe", primary_role="operator", question_category="cash", question="q",
                        normalized_question="q", key_queries=[], summary="s", created_by="reviewer",
                        evidence_sources=[{"path": "../outside.json", "kind": "query_result", "referenced_source_ids": ["cash"]}],
                    )
            self.assertEqual("PATH_OUTSIDE_WORKSPACE", captured.exception.code)
            self.assertFalse((root / "Work" / "Casebook" / "candidates" / "case_unsafe").exists())

            config_path = root / "Work" / "workspace.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["pack_path"] = "../outside-pack.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(CasebookError) as captured:
                with patch("casebook.router.guide", return_value={"next_step": "analyze"}):
                    create_case(
                        root=root, case_id="case_external_pack", primary_role="operator", question_category="cash", question="q",
                        normalized_question="q", key_queries=[], summary="s", created_by="reviewer",
                        evidence_sources=[{"path": "Work/Runs/evidence/query-result.json", "kind": "query_result", "referenced_source_ids": ["cash"]}],
                    )
            self.assertEqual("PATH_OUTSIDE_WORKSPACE", captured.exception.code)

    def test_create_requires_the_current_snapshot_bridge_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            with patch("casebook.router.guide", return_value={"next_step": "align_bridge"}):
                with self.assertRaises(CasebookError) as captured:
                    create_case(
                        root=root, case_id="case_blocked", primary_role="operator", question_category="cash",
                        question="q", normalized_question="q", key_queries=[], summary="s", created_by="reviewer",
                        evidence_sources=[{"path": "Work/Runs/evidence/query-result.json", "kind": "query_result", "referenced_source_ids": ["cash"]}],
                    )
            self.assertEqual("BRIDGE_NOT_READY", captured.exception.code)
