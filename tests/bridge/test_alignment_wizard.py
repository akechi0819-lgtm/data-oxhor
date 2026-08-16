from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from openpyxl import Workbook

from bridge_alignment.service import AlignmentError, add_evidence, answer_question, finalize_session, propose_candidates, start_session
from interfaces.bridge_alignment_wizard import main
from interfaces.data_foundation import ingest_sources
from tests.fixtures.bridge_alignment.fake_adapter import FakeAdapter


class OptionalFakeAdapter(FakeAdapter):
    def propose(self, model_input):
        document = super().propose(model_input)
        document["candidates"] = [document["candidates"][0]]
        document["candidates"][0]["criticality"] = "optional"
        document["candidates"][0]["must_ask"] = False
        document["candidates"][0]["question"] = None
        document["candidates"][0]["answer_options"] = []
        return document


def _workbook(path: Path, sheet_name: str, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def _snapshot(root: Path) -> tuple[Path, str]:
    sources = {
        "port_cash": ("陌生资金端口.xlsx", "资金流水", [["流水号", "发生时间", "交易净额", "学员编码", "课程包"], ["T1", "2026-08-01", 1200, "S1", "A班"], ["T2", "2026-08-03", -300, "S1", "A班"]]),
        "port_leads": ("线索导出.xlsx", "机会池", [["机会编码", "进入日期", "来源", "负责人"], ["L1", "2026-07-20", "转介绍", "顾问甲"]]),
        "port_contracts": ("订单接口.xlsx", "签约记录", [["订单流水", "创建日", "学员编码", "应收"], ["O1", "2026-07-25", "S1", 1200]]),
        "port_delivery": ("消课明细.xlsx", "履约日志", [["记录ID", "上课日", "学员编码", "课时数"], ["D1", "2026-08-05", "S1", 2]]),
    }
    manifest_sources = {}
    bindings = []
    for source_id, (filename, sheet_name, rows) in sources.items():
        path = root / filename
        _workbook(path, sheet_name, rows)
        manifest_sources[source_id] = {"filename": filename, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        bindings.append(f"{source_id}={path}")
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"sources": manifest_sources}, ensure_ascii=False), encoding="utf-8")
    output = root / "data_runs"
    result = ingest_sources(
        run_id="run_alignment_fixture",
        snapshot_id="snapshot_alignment_fixture",
        output_root=output,
        manifest_path=manifest,
        source_values=bindings,
    )
    if result["status"] != "passed":
        raise AssertionError(result)
    warehouse = output / "run_alignment_fixture/data/snapshots/snapshot_alignment_fixture/warehouse.duckdb"
    return warehouse, "snapshot_alignment_fixture"


class BridgeAlignmentWizardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = Path("business_pack/packs/education_training_operations_cn/pack.json").resolve()

    def _start(self, root: Path, *, company_id: str = "company_fixture", existing_bridge: Path | None = None) -> Path:
        warehouse, snapshot_id = _snapshot(root)
        workspace = root / "external_workspace"
        start_session(
            workspace=workspace,
            session_id="session_alignment_fixture",
            company_id=company_id,
            warehouse=warehouse,
            snapshot_id=snapshot_id,
            pack_path=self.pack,
            existing_bridge_path=existing_bridge,
        )
        return workspace / "session_alignment_fixture"

    def test_new_company_uses_pack_without_another_company_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = self._start(Path(directory))
            profile = json.loads((session / "profile.json").read_text(encoding="utf-8"))

            self.assertEqual("company_fixture", profile["company_id"])
            self.assertEqual([], profile["enterprise_decisions"])
            self.assertEqual(4, len(profile["relations"]))

    def test_existing_bridge_must_belong_to_same_company(self) -> None:
        existing = Path("artifacts/company_bridge/bridges/company_bridge.v1_2_0.json").resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            warehouse, snapshot_id = _snapshot(root)
            with self.assertRaises(AlignmentError) as captured:
                start_session(
                    workspace=root / "workspace",
                    session_id="session_company_mismatch",
                    company_id="company_other",
                    warehouse=warehouse,
                    snapshot_id=snapshot_id,
                    pack_path=self.pack,
                    existing_bridge_path=existing,
                )
        self.assertEqual("EXISTING_BRIDGE_COMPANY_MISMATCH", captured.exception.code)

    def test_same_company_reuses_enterprise_decisions_not_field_bindings(self) -> None:
        existing = Path("artifacts/company_bridge/bridges/company_bridge.v1_2_0.json").resolve()
        with tempfile.TemporaryDirectory() as directory:
            session = self._start(Path(directory), company_id="company_super_agent", existing_bridge=existing)
            profile = json.loads((session / "profile.json").read_text(encoding="utf-8"))
            serialized = json.dumps(profile["enterprise_decisions"], ensure_ascii=False)

            self.assertTrue(profile["enterprise_decisions"])
            self.assertNotIn("landing.br_cash__", serialized)

    def test_append_evidence_preserves_decision_and_deduplicates_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self._start(root)
            proposed = propose_candidates(session_dir=session, adapter=FakeAdapter())
            first_question = proposed["pending_questions"][0]
            answer_question(
                session_dir=session,
                question_id=first_question["question_id"],
                answer="是，作为实际收款日期",
                confirmed_by="客户甲",
            )
            decisions_before = (session / "decisions.jsonl").read_text(encoding="utf-8")
            evidence = root / "usb_readonly"
            evidence.mkdir()
            (evidence / "字段说明.md").write_text("交易净额包含退款，退款以负数记录。", encoding="utf-8")

            first = add_evidence(session_dir=session, evidence_root=evidence, adapter=FakeAdapter())
            second = add_evidence(session_dir=session, evidence_root=evidence, adapter=FakeAdapter())

            self.assertEqual(1, first["evidence"]["added_count"])
            self.assertEqual(0, second["evidence"]["added_count"])
            self.assertEqual(decisions_before, (session / "decisions.jsonl").read_text(encoding="utf-8"))
            self.assertNotIn(first_question["question_id"], {item["question_id"] for item in first["pending_questions"]})

    def test_end_to_end_blocks_then_builds_review_and_snapshot_valid_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = self._start(root)
            proposed = propose_candidates(session_dir=session, adapter=FakeAdapter())

            with self.assertRaises(AlignmentError) as captured:
                finalize_session(session_dir=session, bridge_id="bridge_company_fixture", bridge_version="1.0.0")
            self.assertEqual("CRITICAL_QUESTIONS_PENDING", captured.exception.code)

            for question in proposed["pending_questions"]:
                label = question["options"][0]["label"]
                answer_question(session_dir=session, question_id=question["question_id"], answer=label, confirmed_by="客户甲")
            result = finalize_session(session_dir=session, bridge_id="bridge_company_fixture", bridge_version="1.0.0")
            review = json.loads(Path(result["artifacts"]["confirmed_review"]).read_text(encoding="utf-8"))
            bridge = json.loads(Path(result["artifacts"]["bridge"]).read_text(encoding="utf-8"))
            validation = json.loads(Path(result["artifacts"]["validation"]).read_text(encoding="utf-8"))

            self.assertEqual("completed", result["status"])
            self.assertEqual("confirmed_review", review["candidate_set_role"])
            self.assertEqual({"confirmed"}, {item["status"] for item in review["candidates"]})
            self.assertEqual("company_fixture", bridge["company_id"])
            self.assertEqual("snapshot_alignment_fixture", validation["snapshot_id"])
            self.assertEqual("passed", validation["status"])

    def test_cli_returns_exit_two_for_pending_critical_questions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = self._start(Path(directory))
            propose_candidates(session_dir=session, adapter=FakeAdapter())
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["finalize", "--session", str(session), "--bridge-id", "bridge_company_fixture", "--bridge-version", "1.0.0"])
            result = json.loads(output.getvalue())

        self.assertEqual(2, exit_code)
        self.assertEqual("blocked", result["status"])
        self.assertEqual("CRITICAL_QUESTIONS_PENDING", result["errors"][0]["code"])
        self.assertEqual(2, len(result["pending_questions"]))

    def test_unanswered_optional_question_becomes_unresolved_and_disables_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = self._start(Path(directory))
            propose_candidates(session_dir=session, adapter=OptionalFakeAdapter())
            result = finalize_session(session_dir=session, bridge_id="bridge_company_fixture", bridge_version="1.0.0")
            review = json.loads(Path(result["artifacts"]["confirmed_review"]).read_text(encoding="utf-8"))

        self.assertEqual("completed", result["status"])
        self.assertEqual(["cash.period_analysis"], result["disabled_capabilities"])
        self.assertEqual("unresolved", review["candidates"][0]["status"])
        self.assertEqual("unresolved", review["candidates"][0]["candidate_type"])


if __name__ == "__main__":
    unittest.main()
