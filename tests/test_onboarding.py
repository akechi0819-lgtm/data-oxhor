from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from openpyxl import Workbook

from workspace_modeling.onboarding.service import OnboardingError, doctor, handoff, import_data, status, sync
from workspace_modeling.bridge_alignment.workspace import init_workspace
from interfaces.workspace_modeling import main


class OnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = Path("workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json").resolve()

    def _workbook(self, path: Path) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "现金流水"
        sheet.append(["流水号", "发生时间", "交易净额"])
        sheet.append(["T1", "2026-08-01", 100])
        workbook.save(path)

    def test_doctor_checks_runtime_and_pack(self) -> None:
        result = doctor(pack_path=self.pack)
        self.assertEqual("doctor_passed", result["status"])

        full = doctor(profile="full", pack_path=self.pack)
        self.assertEqual({"duckdb", "openpyxl", "Pillow", "business_pack"}, {item["name"] for item in full["checks"]})
        self.assertTrue(all(item["status"] == "passed" for item in result["checks"]))

    def test_first_deployment_flow_and_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "customer"
            init_workspace(root=root, company_id="company_demo", business_port="operations", pack_path=self.pack)
            source = parent / "cash.xlsx"
            self._workbook(source)
            imported = import_data(root=root, source_id="cash", source_file=source)
            self.assertEqual("data_imported", imported["status"])
            synced = sync(root=root, snapshot_id="snapshot_demo_2026_08")
            self.assertEqual("snapshot_ready", synced["status"])
            self.assertEqual("align_bridge", synced["next_step"])
            handoff_result = handoff(root=root, session_id="session_onboarding")
            self.assertEqual("handoff_ready", handoff_result["status"])
            self.assertEqual("align_bridge", handoff_result["next_step"])
            self.assertEqual("session_onboarding", handoff_result["session"]["session_id"])
            self.assertEqual("operations", handoff_result["business_port"])
            repeated = handoff(root=root, session_id="session_onboarding")
            self.assertEqual("session_onboarding", repeated["session"]["session_id"])

            current = status(root=root)
            self.assertEqual("in_progress", current["status"])
            self.assertEqual("align_bridge", current["next_step"])

    def test_import_does_not_overwrite_without_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "customer"
            init_workspace(root=root, company_id="company_demo", business_port="operations", pack_path=self.pack)
            first = parent / "first.xlsx"
            second = parent / "second.xlsx"
            self._workbook(first)
            self._workbook(second)
            import_data(root=root, source_id="cash", source_file=first)
            with self.assertRaises(OnboardingError) as captured:
                import_data(root=root, source_id="cash", source_file=second)
            self.assertEqual("SOURCE_EXISTS", captured.exception.code)

    def test_cli_emits_onboarding_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = StringIO()
            with redirect_stdout(output):
                code = main(["init", "--workspace", str(Path(directory) / "customer"), "--business-port", "operations", "--pack", str(self.pack)])
            self.assertEqual(0, code)
            document = json.loads(output.getvalue())
            self.assertEqual("onboarding_result.v1", document["schema_version"])
            self.assertEqual("import_data", document["next_step"])
            self.assertEqual("operations", document["business_port"])
            self.assertEqual("workspace_customer", document["company_id"])


if __name__ == "__main__":
    unittest.main()
