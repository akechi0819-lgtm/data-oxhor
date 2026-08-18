from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from pilot_feedback.service import (
    PilotFeedbackError,
    attach_evidence,
    complete_evaluation,
    export_feedback,
    import_test_package,
    load_evaluation,
    record_card,
    start_evaluation,
    validate_test_package,
    verify_feedback,
)


FIXTURE = Path("tests/fixtures/pilot_feedback/synthetic_package.json")


class PilotFeedbackTests(unittest.TestCase):
    def _workspace(self, directory: Path) -> Path:
        workspace = directory / "customer"
        (workspace / "Work").mkdir(parents=True)
        (workspace / "Work" / "workspace.json").write_text(json.dumps({
            "schema_version": "bridge_alignment_workspace.v1",
            "company_id": "company_fixture",
            "pack_ref": {"pack_id": "education_training_operations_cn", "pack_version": "1.0.0"},
            "current_snapshot_id": "snapshot_2026_08",
            "pack_path": "Work/Pack/pack.json",
            "bridge_reference_path": "Work/Bridge/reference.json",
        }), encoding="utf-8")
        return workspace

    def _started(self, workspace: Path) -> None:
        import_test_package(workspace=workspace, package_path=FIXTURE)
        bridge = {"bridge_id": "company_fixture", "bridge_version": "1.0.0", "company_id": "company_fixture"}
        (workspace / "Work" / "Bridge").mkdir(parents=True, exist_ok=True)
        (workspace / "Work" / "Bridge" / "reference.json").write_text(json.dumps(bridge), encoding="utf-8")
        (workspace / "Work" / "Pack").mkdir(parents=True, exist_ok=True)
        (workspace / "Work" / "Pack" / "pack.json").write_text(json.dumps({"pack_id": "education_training_operations_cn", "pack_version": "1.0.0"}), encoding="utf-8")
        start_evaluation(
            workspace=workspace, evaluation_id="evaluation_alpha", product_version="0.1.0",
            pack_ref={"pack_id": "education_training_operations_cn", "pack_version": "1.0.0"},
            bridge_ref={"bridge_id": "company_fixture", "bridge_version": "1.0.0"},
            casebook_version="casebook.v1", test_pack_ref={"pack_id": "pilot_synthetic", "version": "1.0.0"},
        )

    def _record_all(self, workspace: Path) -> None:
        for card_id in ("cash_diagnosis", "source_boundary"):
            record_card(
                workspace=workspace, evaluation_id="evaluation_alpha", card_id=card_id, status="passed",
                duration_seconds=4.5, matched_case_ids=["case_cash_001"], acceptance={"accepted": True},
                score=5, feedback="Synthetic feedback only.", error_codes=[], redacted_log="No sensitive content.", reviewed_by="reviewer",
            )

    def test_import_validates_and_rejects_duplicate_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory))
            result = import_test_package(workspace=workspace, package_path=FIXTURE)
            self.assertEqual("test_package_imported", result["status"])
            with self.assertRaises(PilotFeedbackError) as captured:
                import_test_package(workspace=workspace, package_path=FIXTURE)
            self.assertEqual("OUTPUT_EXISTS", captured.exception.code)

            invalid = json.loads(FIXTURE.read_text(encoding="utf-8"))
            invalid["cards"].append(dict(invalid["cards"][0]))
            with self.assertRaises(PilotFeedbackError) as captured:
                validate_test_package(invalid)
            self.assertEqual("CARD_ID_DUPLICATE", captured.exception.code)

    def test_only_pack_cards_can_be_recorded_and_all_must_finish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory))
            self._started(workspace)
            with self.assertRaises(PilotFeedbackError) as captured:
                record_card(
                    workspace=workspace, evaluation_id="evaluation_alpha", card_id="unlisted_card", status="passed",
                    duration_seconds=1, matched_case_ids=[], acceptance=True, score=1, feedback="redacted", error_codes=[], redacted_log="redacted", reviewed_by="reviewer",
                )
            self.assertEqual("CARD_NOT_IN_TEST_PACKAGE", captured.exception.code)
            with self.assertRaises(PilotFeedbackError) as captured:
                complete_evaluation(workspace=workspace, evaluation_id="evaluation_alpha")
            self.assertEqual("EVALUATION_CARDS_PENDING", captured.exception.code)
            self._record_all(workspace)
            self.assertEqual("evaluation_completed", complete_evaluation(workspace=workspace, evaluation_id="evaluation_alpha")["status"])
            self.assertEqual("completed", load_evaluation(workspace, evaluation_id="evaluation_alpha")["status"])

    def test_export_metrics_only_is_redacted_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory))
            self._started(workspace)
            self._record_all(workspace)
            complete_evaluation(workspace=workspace, evaluation_id="evaluation_alpha")
            result = export_feedback(workspace=workspace, evaluation_id="evaluation_alpha", feedback_id="feedback_metrics", export_type="metrics-only")
            self.assertEqual("feedback_exported", result["status"])
            self.assertEqual("passed", verify_feedback(feedback_path=Path(result["path"]))["status"])
            with zipfile.ZipFile(result["path"]) as archive:
                self.assertEqual({"manifest.json", "feedback.json"}, set(archive.namelist()))
                feedback = json.loads(archive.read("feedback.json"))
                self.assertNotIn("question", json.dumps(feedback))
                self.assertNotIn("company_id", feedback)
                self.assertEqual(64, len(feedback["cards"][0]["matched_case_ids"][0]))

    def test_only_explicit_safe_evidence_can_be_exported_and_tampering_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory))
            self._started(workspace)
            safe = workspace / "Work" / "Reference" / "approval.txt"
            safe.parent.mkdir(parents=True)
            safe.write_text("Synthetic approval", encoding="utf-8")
            attached = attach_evidence(workspace=workspace, evaluation_id="evaluation_alpha", evidence_id="approval_note", source_path=safe)
            self.assertEqual("evidence_attached", attached["status"])
            forbidden = workspace / "Input" / "Data" / "cash.xlsx"
            forbidden.parent.mkdir(parents=True)
            forbidden.write_text("never export", encoding="utf-8")
            with self.assertRaises(PilotFeedbackError) as captured:
                attach_evidence(workspace=workspace, evaluation_id="evaluation_alpha", evidence_id="data_file", source_path=forbidden)
            self.assertEqual("EVIDENCE_SOURCE_FORBIDDEN", captured.exception.code)
            self._record_all(workspace)
            complete_evaluation(workspace=workspace, evaluation_id="evaluation_alpha")
            result = export_feedback(
                workspace=workspace, evaluation_id="evaluation_alpha", feedback_id="feedback_evidence",
                export_type="evidence-approved", evidence_ids=["approval_note"],
            )
            archive_path = Path(result["path"])
            self.assertEqual("passed", verify_feedback(feedback_path=archive_path)["status"])
            with zipfile.ZipFile(archive_path, "a") as archive:
                archive.writestr("evidence/approval_note-approval.txt", "tampered")
            with self.assertRaises(PilotFeedbackError) as captured:
                verify_feedback(feedback_path=archive_path)
            self.assertIn(captured.exception.code, {"FEEDBACK_ZIP_INVALID", "FEEDBACK_HASH_MISMATCH"})

    def test_exports_require_completion_and_metrics_only_rejects_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory))
            self._started(workspace)
            with self.assertRaises(PilotFeedbackError) as captured:
                export_feedback(workspace=workspace, evaluation_id="evaluation_alpha", feedback_id="feedback_pending", export_type="metrics-only")
            self.assertEqual("EVALUATION_NOT_COMPLETED", captured.exception.code)

    def test_verify_rejects_rehashed_sensitive_or_forbidden_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory))
            self._started(workspace)
            self._record_all(workspace)
            complete_evaluation(workspace=workspace, evaluation_id="evaluation_alpha")
            exported = export_feedback(workspace=workspace, evaluation_id="evaluation_alpha", feedback_id="feedback_safe", export_type="metrics-only")
            with zipfile.ZipFile(exported["path"]) as archive:
                feedback = json.loads(archive.read("feedback.json"))
                manifest = json.loads(archive.read("manifest.json"))
            feedback["cards"][0]["question"] = "customer secret"
            feedback_bytes = (json.dumps(feedback, ensure_ascii=False) + "\n").encode("utf-8")
            manifest["entries"][0]["sha256"] = __import__("hashlib").sha256(feedback_bytes).hexdigest()
            forged = workspace / "forged.zip"
            with zipfile.ZipFile(forged, "w") as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("feedback.json", feedback_bytes)
            with self.assertRaises(PilotFeedbackError) as captured:
                verify_feedback(feedback_path=forged)
            self.assertEqual("FEEDBACK_JSON_INVALID", captured.exception.code)

            manifest["export_type"] = "evidence-approved"
            payload = b"not allowed"
            manifest["entries"].append({"path": "evidence/proof-book.xlsx", "sha256": __import__("hashlib").sha256(payload).hexdigest(), "evidence_id": "proof"})
            with zipfile.ZipFile(forged, "w") as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("feedback.json", feedback_bytes)
                archive.writestr("evidence/proof-book.xlsx", payload)
            with self.assertRaises(PilotFeedbackError) as captured:
                verify_feedback(feedback_path=forged)
            self.assertEqual("FEEDBACK_MANIFEST_INVALID", captured.exception.code)


if __name__ == "__main__":
    unittest.main()
