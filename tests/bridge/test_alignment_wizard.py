from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from openpyxl import Workbook

from bridge_alignment.service import add_evidence, answer_question, finalize_session, propose_candidates, start_session
from bridge_alignment.workspace import AlignmentError, init_workspace, load_workspace, sync_data
from interfaces.bridge_alignment_wizard import main
from tests.fixtures.bridge_alignment.fake_adapter import FakeAdapter


class OptionalFakeAdapter(FakeAdapter):
    def propose(self, model_input):
        document = super().propose(model_input)
        document["candidates"] = [document["candidates"][0]]
        candidate = document["candidates"][0]
        candidate["criticality"] = "optional"
        candidate["must_ask"] = False
        candidate["question"] = None
        candidate["answer_options"] = []
        return document


def _workbook(path: Path, sheet_name: str, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def _source_rows(month: int) -> dict[str, tuple[str, list[list[object]]]]:
    return {
        "cash": ("资金流水", [["流水号", "发生时间", "交易净额", "学员编码", "课程包"], [f"T{month}", f"2026-{month:02d}-01", 1200, "S1", "A班"], [f"R{month}", f"2026-{month:02d}-03", -300, "S1", "A班"]]),
        "leads": ("机会池", [["机会编码", "进入日期", "来源", "负责人"], ["L1", "2026-07-20", "转介绍", "顾问甲"]]),
        "contracts": ("签约记录", [["订单流水", "创建日", "学员编码", "应收"], ["O1", "2026-07-25", "S1", 1200]]),
        "delivery": ("履约日志", [["记录ID", "上课日", "学员编码", "课时数"], ["D1", "2026-08-05", "S1", 2]]),
    }


def _put_current_inputs(workspace: Path, month: int) -> None:
    for source_id, (sheet_name, rows) in _source_rows(month).items():
        slot = workspace / "Input" / "Data" / source_id
        slot.mkdir(parents=True, exist_ok=True)
        for old in slot.glob("*.xlsx"):
            old.unlink()
        _workbook(slot / f"{source_id}_2026_{month:02d}.xlsx", sheet_name, rows)


class BridgeAlignmentWizardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = Path("business_pack/packs/education_training_operations_cn/pack.json").resolve()

    def _workspace(self, parent: Path, *, company_id: str = "company_fixture", existing_bridge: Path | None = None) -> Path:
        root = parent / "customers" / company_id
        init_workspace(root=root, company_id=company_id, pack_path=self.pack, existing_bridge_path=existing_bridge)
        _put_current_inputs(root, 7)
        sync_data(root=root, snapshot_id="snapshot_2026_07")
        return root

    def test_workspace_can_live_inside_product_tree_and_uses_relative_pointers(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = self._workspace(Path(directory))
            _, config = load_workspace(root)

            self.assertFalse(Path(config["pack_path"]).is_absolute())
            self.assertFalse(Path(config["current_warehouse_path"]).is_absolute())
            self.assertTrue((root / config["current_warehouse_path"]).is_file())

    def test_july_input_can_be_replaced_by_august_without_overwriting_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            _, july = load_workspace(root)
            july_warehouse = root / july["current_warehouse_path"]
            _put_current_inputs(root, 8)
            result = sync_data(root=root, snapshot_id="snapshot_2026_08")
            _, august = load_workspace(root)

            self.assertTrue(july_warehouse.is_file())
            self.assertEqual("snapshot_2026_08", august["current_snapshot_id"])
            self.assertEqual(["snapshot_2026_07", "snapshot_2026_08"], august["snapshot_history"])
            self.assertTrue(Path(result["warehouse"]).is_file())
            self.assertEqual(["cash", "contracts", "delivery", "leads"], result["source_ids"])

    def test_new_company_has_no_enterprise_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            result = start_session(root=root, session_id="session_new_company")
            session = json.loads(Path(result["session_path"]).read_text(encoding="utf-8"))
            self.assertEqual([], session["profile"]["enterprise_decisions"])

    def test_same_company_new_snapshot_reuses_decisions_not_old_fields(self) -> None:
        existing = Path("artifacts/company_bridge/bridges/company_bridge.v1_2_0.json").resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory), company_id="company_super_agent", existing_bridge=existing)
            _put_current_inputs(root, 8)
            sync_data(root=root, snapshot_id="snapshot_2026_08")
            result = start_session(root=root, session_id="session_new_port")
            session = json.loads(Path(result["session_path"]).read_text(encoding="utf-8"))
            serialized = json.dumps(session["profile"]["enterprise_decisions"], ensure_ascii=False)

            self.assertTrue(session["profile"]["enterprise_decisions"])
            self.assertNotIn("landing.br_cash__", serialized)
            self.assertEqual("snapshot_2026_08", session["snapshot_id"])

    def test_reference_update_preserves_decision_by_semantic_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            start_session(root=root, session_id="session_reference_update")
            proposed = propose_candidates(root=root, session_id="session_reference_update", adapter=FakeAdapter())
            question = proposed["pending_questions"][0]
            answer_question(
                root=root, session_id="session_reference_update",
                candidate_key=question["candidate_key"], option_id=question["options"][0]["option_id"],
                answer_text="这确实是到账日期", confirmed_by="客户甲",
            )
            evidence = Path(directory) / "usb"
            evidence.mkdir()
            (evidence / "字段说明.md").write_text("交易净额包含退款，退款以负数记录。", encoding="utf-8")
            result = add_evidence(root=root, session_id="session_reference_update", evidence_root=evidence, adapter=FakeAdapter())
            session = json.loads(Path(result["session_path"]).read_text(encoding="utf-8"))

            self.assertEqual(["字段说明.md"], result["updated_reference_files"])
            self.assertEqual(1, len(session["decisions"]))
            self.assertNotIn(question["candidate_key"], {item["candidate_key"] for item in result["pending_questions"]})
            self.assertTrue((root / "Input" / "Reference" / "字段说明.md").is_file())

    def test_end_to_end_blocks_then_builds_into_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            start_session(root=root, session_id="session_end_to_end")
            proposed = propose_candidates(root=root, session_id="session_end_to_end", adapter=FakeAdapter())
            with self.assertRaises(AlignmentError) as captured:
                finalize_session(root=root, session_id="session_end_to_end", bridge_id="bridge_company_fixture", bridge_version="1.0.0")
            self.assertEqual("CRITICAL_QUESTIONS_PENDING", captured.exception.code)
            for question in proposed["pending_questions"]:
                answer_question(
                    root=root, session_id="session_end_to_end", candidate_key=question["candidate_key"],
                    option_id=question["options"][0]["option_id"], answer_text=question["options"][0]["label"], confirmed_by="客户甲",
                )
            result = finalize_session(root=root, session_id="session_end_to_end", bridge_id="bridge_company_fixture", bridge_version="1.0.0")
            self.assertEqual("completed", result["status"])
            self.assertTrue((root / "Output" / "Bridge" / "1.0.0" / "company_bridge.v1.json").is_file())

    def test_unanswered_optional_disables_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            start_session(root=root, session_id="session_optional")
            propose_candidates(root=root, session_id="session_optional", adapter=OptionalFakeAdapter())
            result = finalize_session(root=root, session_id="session_optional", bridge_id="bridge_company_fixture", bridge_version="1.0.0")
            self.assertEqual(["cash.period_analysis"], result["disabled_capabilities"])

    def test_cli_returns_exit_two_and_pending_questions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._workspace(Path(directory))
            start_session(root=root, session_id="session_cli")
            propose_candidates(root=root, session_id="session_cli", adapter=FakeAdapter())
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["finalize", "--workspace", str(root), "--session-id", "session_cli", "--bridge-id", "bridge_company_fixture", "--bridge-version", "1.0.0"])
            result = json.loads(output.getvalue())
            self.assertEqual(2, exit_code)
            self.assertEqual(2, len(result["pending_questions"]))


if __name__ == "__main__":
    unittest.main()
