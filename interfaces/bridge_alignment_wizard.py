from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bridge_alignment.service import add_evidence, answer_question, finalize_session, load_adapter, propose_candidates, start_session
from bridge_alignment.workspace import AlignmentError, init_workspace, sync_data
from business_pack.service import PackError, default_pack_path
from company_bridge.service import BridgeError
from data_foundation.query.service import QueryError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bridge-alignment-wizard")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--workspace", type=Path, required=True)
    init.add_argument("--company-id", required=True)
    init.add_argument("--pack", type=Path, default=default_pack_path())
    init.add_argument("--existing-bridge", type=Path)
    sync = commands.add_parser("sync-data")
    sync.add_argument("--workspace", type=Path, required=True)
    sync.add_argument("--snapshot-id", required=True)
    start = commands.add_parser("start")
    start.add_argument("--workspace", type=Path, required=True)
    start.add_argument("--session-id", required=True)
    propose = commands.add_parser("propose")
    propose.add_argument("--workspace", type=Path, required=True)
    propose.add_argument("--session-id", required=True)
    propose.add_argument("--adapter", required=True)
    answer = commands.add_parser("answer")
    answer.add_argument("--workspace", type=Path, required=True)
    answer.add_argument("--session-id", required=True)
    answer.add_argument("--candidate-key", required=True)
    answer.add_argument("--option-id", required=True)
    answer.add_argument("--answer-text", required=True)
    answer.add_argument("--confirmed-by", required=True)
    evidence = commands.add_parser("add-evidence")
    evidence.add_argument("--workspace", type=Path, required=True)
    evidence.add_argument("--session-id", required=True)
    evidence.add_argument("--directory", type=Path, required=True)
    evidence.add_argument("--adapter", required=True)
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--workspace", type=Path, required=True)
    finalize.add_argument("--session-id", required=True)
    finalize.add_argument("--bridge-id", required=True)
    finalize.add_argument("--bridge-version", required=True)
    return parser


def _failure(exc: Exception) -> dict[str, Any]:
    code = getattr(exc, "code", "BRIDGE_ALIGNMENT_FAILED")
    return {
        "schema_version": "bridge_alignment_result.v1",
        "status": "blocked" if code in {"CRITICAL_QUESTIONS_PENDING", "CRITICAL_AMBIGUITY_UNRESOLVED"} else "failed",
        "session_id": getattr(exc, "session_id", None),
        "pending_questions": getattr(exc, "pending_questions", []),
        "disabled_capabilities": getattr(exc, "disabled_capabilities", []),
        "errors": getattr(exc, "errors", [{"code": code, "path": "$", "message": str(exc)}]),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            result = init_workspace(root=args.workspace, company_id=args.company_id, pack_path=args.pack, existing_bridge_path=args.existing_bridge)
        elif args.command == "sync-data":
            result = sync_data(root=args.workspace, snapshot_id=args.snapshot_id)
        elif args.command == "start":
            result = start_session(root=args.workspace, session_id=args.session_id)
        elif args.command == "propose":
            result = propose_candidates(root=args.workspace, session_id=args.session_id, adapter=load_adapter(args.adapter))
        elif args.command == "answer":
            result = answer_question(root=args.workspace, session_id=args.session_id, candidate_key=args.candidate_key, option_id=args.option_id, answer_text=args.answer_text, confirmed_by=args.confirmed_by)
        elif args.command == "add-evidence":
            result = add_evidence(root=args.workspace, session_id=args.session_id, evidence_root=args.directory, adapter=load_adapter(args.adapter))
        else:
            result = finalize_session(root=args.workspace, session_id=args.session_id, bridge_id=args.bridge_id, bridge_version=args.bridge_version)
    except (AlignmentError, BridgeError, PackError, QueryError, OSError, json.JSONDecodeError) as exc:
        result = _failure(exc)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] in {"workspace_ready", "data_ready", "ready_for_model", "ready_to_finalize", "completed"}:
        return 0
    if result["status"] in {"awaiting_confirmation", "blocked"}:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
