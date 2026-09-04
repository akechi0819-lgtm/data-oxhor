from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from workspace_modeling.casebook.router import RouterError, guide, repeat_candidates
from workspace_modeling.casebook.service import CasebookError, capture_case, confirm_case, create_case, reject_case, search_cases, supersede_case, verify_case
from workspace_modeling.pilot_feedback.service import (
    PilotFeedbackError,
    attach_evidence,
    complete_evaluation,
    export_feedback,
    import_test_package,
    record_card,
    start_evaluation,
    verify_feedback,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workspace-modeling casebook")
    commands = parser.add_subparsers(dest="command", required=True)
    workspace = argparse.ArgumentParser(add_help=False)
    workspace.add_argument("--workspace", type=Path, required=True)

    command = commands.add_parser("case-create", parents=[workspace]); command.add_argument("--case-id", required=True); command.add_argument("--primary-role", required=True); command.add_argument("--question-category", required=True); command.add_argument("--question", required=True); command.add_argument("--normalized-question", required=True); command.add_argument("--key-queries-json", required=True); command.add_argument("--evidence-json", required=True); command.add_argument("--summary", required=True); command.add_argument("--created-by", required=True); command.add_argument("--supersedes")
    command = commands.add_parser("case-capture", parents=[workspace]); command.add_argument("--manifest", required=True, help="workspace-relative casebook_capture.v1 JSON manifest")
    for name in ("case-confirm", "case-reject"):
        command = commands.add_parser(name, parents=[workspace]); command.add_argument("--case-id", required=True); command.add_argument("--decided-by", required=True); command.add_argument("--decision-note", required=True)
    command = commands.add_parser("case-supersede", parents=[workspace]); command.add_argument("--case-id", required=True); command.add_argument("--superseding-case-id", required=True); command.add_argument("--decided-by", required=True); command.add_argument("--decision-note", required=True)
    command = commands.add_parser("case-search", parents=[workspace]); command.add_argument("--company-id", required=True); command.add_argument("--primary-role", required=True); command.add_argument("--question-category")
    command = commands.add_parser("case-verify", parents=[workspace]); command.add_argument("--case-id", required=True)
    command = commands.add_parser("test-pack-import", parents=[workspace]); command.add_argument("--package", type=Path, required=True)
    command = commands.add_parser("evaluation-start", parents=[workspace]); command.add_argument("--evaluation-id", required=True); command.add_argument("--product-version", required=True); command.add_argument("--pack-ref-json", required=True); command.add_argument("--bridge-ref-json", required=True); command.add_argument("--casebook-version", required=True); command.add_argument("--test-pack-ref-json", required=True)
    command = commands.add_parser("evaluation-record-card", parents=[workspace]); command.add_argument("--evaluation-id", required=True); command.add_argument("--card-id", required=True); command.add_argument("--status", required=True); command.add_argument("--duration-seconds", type=float, required=True); command.add_argument("--matched-case-ids-json", required=True); command.add_argument("--acceptance-json", required=True); command.add_argument("--score-json", required=True); command.add_argument("--feedback", required=True); command.add_argument("--error-codes-json", required=True); command.add_argument("--redacted-log", required=True); command.add_argument("--reviewed-by", required=True)
    command = commands.add_parser("evaluation-complete", parents=[workspace]); command.add_argument("--evaluation-id", required=True)
    command = commands.add_parser("evaluation-attach-evidence", parents=[workspace]); command.add_argument("--evaluation-id", required=True); command.add_argument("--evidence-id", required=True); command.add_argument("--source", type=Path, required=True)
    command = commands.add_parser("feedback-export", parents=[workspace]); command.add_argument("--evaluation-id", required=True); command.add_argument("--feedback-id", required=True); command.add_argument("--export-type", choices=("metrics-only", "evidence-approved"), required=True); command.add_argument("--evidence-ids-json", default="[]")
    command = commands.add_parser("feedback-verify"); command.add_argument("--feedback", type=Path, required=True)
    commands.add_parser("guide", parents=[workspace]); commands.add_parser("repeat-candidates", parents=[workspace])
    return parser


def _json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON argument: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "case-create":
            result = create_case(root=args.workspace, case_id=args.case_id, primary_role=args.primary_role, question_category=args.question_category, question=args.question, normalized_question=args.normalized_question, key_queries=_json(args.key_queries_json), evidence_sources=_json(args.evidence_json), summary=args.summary, created_by=args.created_by, supersedes=args.supersedes)
        elif args.command == "case-capture": result = capture_case(root=args.workspace, manifest_path=args.manifest)
        elif args.command == "case-confirm": result = confirm_case(root=args.workspace, case_id=args.case_id, decided_by=args.decided_by, decision_note=args.decision_note)
        elif args.command == "case-reject": result = reject_case(root=args.workspace, case_id=args.case_id, decided_by=args.decided_by, decision_note=args.decision_note)
        elif args.command == "case-supersede": result = supersede_case(root=args.workspace, case_id=args.case_id, superseding_case_id=args.superseding_case_id, decided_by=args.decided_by, decision_note=args.decision_note)
        elif args.command == "case-search": result = search_cases(root=args.workspace, company_id=args.company_id, primary_role=args.primary_role, question_category=args.question_category)
        elif args.command == "case-verify": result = verify_case(root=args.workspace, case_id=args.case_id)
        elif args.command == "test-pack-import": result = import_test_package(workspace=args.workspace, package_path=args.package)
        elif args.command == "evaluation-start": result = start_evaluation(workspace=args.workspace, evaluation_id=args.evaluation_id, product_version=args.product_version, pack_ref=_json(args.pack_ref_json), bridge_ref=_json(args.bridge_ref_json), casebook_version=args.casebook_version, test_pack_ref=_json(args.test_pack_ref_json))
        elif args.command == "evaluation-record-card": result = record_card(workspace=args.workspace, evaluation_id=args.evaluation_id, card_id=args.card_id, status=args.status, duration_seconds=args.duration_seconds, matched_case_ids=_json(args.matched_case_ids_json), acceptance=_json(args.acceptance_json), score=_json(args.score_json), feedback=args.feedback, error_codes=_json(args.error_codes_json), redacted_log=args.redacted_log, reviewed_by=args.reviewed_by)
        elif args.command == "evaluation-complete": result = complete_evaluation(workspace=args.workspace, evaluation_id=args.evaluation_id)
        elif args.command == "evaluation-attach-evidence": result = attach_evidence(workspace=args.workspace, evaluation_id=args.evaluation_id, evidence_id=args.evidence_id, source_path=args.source)
        elif args.command == "feedback-export": result = export_feedback(workspace=args.workspace, evaluation_id=args.evaluation_id, feedback_id=args.feedback_id, export_type=args.export_type, evidence_ids=_json(args.evidence_ids_json))
        elif args.command == "feedback-verify": result = verify_feedback(feedback_path=args.feedback)
        elif args.command == "guide": result = guide(root=args.workspace)
        else: result = repeat_candidates(root=args.workspace)
    except (CasebookError, PilotFeedbackError, RouterError, OSError, ValueError, json.JSONDecodeError) as exc:
        code = getattr(exc, "code", "CASEBOOK_PILOT_FAILED")
        result = {"schema_version": "casebook_pilot_result.v1", "status": "failed", "errors": getattr(exc, "errors", [{"code": code, "path": "$", "message": str(exc)}])}
    result = {**result, "schema_version": "casebook_pilot_result.v1"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "guide_completed":
        return 0 if result.get("next_step") == "analyze" else 2
    if result.get("status") == "repeat_candidates_completed":
        return 2 if not result.get("candidates") else 0
    if result.get("status") in {"search_completed", "case-verify"} or str(result.get("status", "")).endswith(("created", "confirmed", "rejected", "superseded", "imported", "started", "recorded", "completed", "attached", "exported", "passed")):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
