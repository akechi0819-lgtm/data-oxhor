from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bridge_alignment.service import (
    AlignmentError,
    add_evidence,
    answer_question,
    finalize_session,
    load_adapter,
    propose_candidates,
    start_session,
)
from business_pack.service import PackError, default_pack_path
from company_bridge.service import BridgeError
from data_foundation.query.service import QueryError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bridge-alignment-wizard")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start")
    start.add_argument("--workspace", type=Path, required=True)
    start.add_argument("--session-id", required=True)
    start.add_argument("--company-id", required=True)
    start.add_argument("--warehouse", type=Path, required=True)
    start.add_argument("--snapshot-id", required=True)
    start.add_argument("--pack", type=Path, default=default_pack_path())
    start.add_argument("--existing-bridge", type=Path)
    propose = commands.add_parser("propose")
    propose.add_argument("--session", type=Path, required=True)
    propose.add_argument("--adapter", required=True)
    answer = commands.add_parser("answer")
    answer.add_argument("--session", type=Path, required=True)
    answer.add_argument("--question-id", required=True)
    answer.add_argument("--answer", required=True)
    answer.add_argument("--confirmed-by", required=True)
    evidence = commands.add_parser("add-evidence")
    evidence.add_argument("--session", type=Path, required=True)
    evidence.add_argument("--directory", type=Path, required=True)
    evidence.add_argument("--adapter", required=True)
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--session", type=Path, required=True)
    finalize.add_argument("--bridge-id", required=True)
    finalize.add_argument("--bridge-version", required=True)
    return parser


def _failure(exc: Exception) -> dict[str, Any]:
    code = getattr(exc, "code", "BRIDGE_ALIGNMENT_FAILED")
    return {
        "schema_version": "bridge_alignment_result.v1",
        "status": "blocked" if code in {"CRITICAL_QUESTIONS_PENDING", "CRITICAL_AMBIGUITY_UNRESOLVED"} else "failed",
        "session_id": getattr(exc, "session_id", None),
        "artifacts": {},
        "pending_questions": getattr(exc, "pending_questions", []),
        "disabled_capabilities": getattr(exc, "disabled_capabilities", []),
        "errors": getattr(exc, "errors", [{"code": code, "path": "$", "message": str(exc)}]),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            result = start_session(
                workspace=args.workspace,
                session_id=args.session_id,
                company_id=args.company_id,
                warehouse=args.warehouse,
                snapshot_id=args.snapshot_id,
                pack_path=args.pack,
                existing_bridge_path=args.existing_bridge,
            )
        elif args.command == "propose":
            result = propose_candidates(session_dir=args.session, adapter=load_adapter(args.adapter))
        elif args.command == "answer":
            result = answer_question(
                session_dir=args.session,
                question_id=args.question_id,
                answer=args.answer,
                confirmed_by=args.confirmed_by,
            )
        elif args.command == "add-evidence":
            result = add_evidence(session_dir=args.session, evidence_root=args.directory, adapter=load_adapter(args.adapter))
        else:
            result = finalize_session(session_dir=args.session, bridge_id=args.bridge_id, bridge_version=args.bridge_version)
    except (AlignmentError, BridgeError, PackError, QueryError, OSError, json.JSONDecodeError) as exc:
        result = _failure(exc)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] in {"ready_for_model", "ready_to_finalize", "completed"}:
        return 0
    if result["status"] in {"awaiting_confirmation", "blocked"}:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
