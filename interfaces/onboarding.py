from __future__ import annotations

import argparse
import json
from pathlib import Path

from business_pack.service import default_pack_path
from onboarding.service import OnboardingError, derive_company_id, doctor, handoff, import_data, status, sync
from bridge_alignment.workspace import AlignmentError, init_workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onboarding")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor_command = commands.add_parser("doctor")
    doctor_command.add_argument("--profile", choices=("core", "full"), default="core")
    doctor_command.add_argument("--pack", type=Path, default=default_pack_path())
    init = commands.add_parser("init")
    init.add_argument("--workspace", type=Path, required=True)
    init.add_argument("--business-port", required=True, help="业务端口，例如 high_school、middle_school、marketing、operations、teaching")
    init.add_argument("--pack", type=Path, default=default_pack_path())
    init.add_argument("--existing-bridge", type=Path)
    data = commands.add_parser("import-data")
    data.add_argument("--workspace", type=Path, required=True)
    data.add_argument("--source-id", required=True)
    data.add_argument("--file", type=Path, required=True)
    data.add_argument("--replace", action="store_true")
    for name in ("status", "handoff"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", type=Path, required=True)
        if name == "handoff":
            command.add_argument("--session-id")
    sync_command = commands.add_parser("sync")
    sync_command.add_argument("--workspace", type=Path, required=True)
    sync_command.add_argument("--snapshot-id", required=True)
    return parser


def _failure(exc: Exception) -> dict[str, object]:
    code = getattr(exc, "code", "ONBOARDING_FAILED")
    return {"schema_version": "onboarding_result.v1", "status": "failed", "next_step": None, "pending_actions": [], "errors": getattr(exc, "errors", [{"code": code, "path": "$", "message": str(exc)}])}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor(profile=args.profile, pack_path=args.pack)
        elif args.command == "init":
            result = init_workspace(
                root=args.workspace,
                company_id=derive_company_id(args.workspace),
                business_port=args.business_port,
                pack_path=args.pack,
                existing_bridge_path=args.existing_bridge,
            )
            result = {**result, "schema_version": "onboarding_result.v1", "next_step": "import_data", "pending_actions": ["把每个基础工作簿放入 Input/Data/<source_id>/ 或使用 import-data"]}
        elif args.command == "import-data":
            result = import_data(root=args.workspace, source_id=args.source_id, source_file=args.file, replace=args.replace)
        elif args.command == "sync":
            result = sync(root=args.workspace, snapshot_id=args.snapshot_id)
        elif args.command == "status":
            result = status(root=args.workspace)
        else:
            result = handoff(root=args.workspace, session_id=args.session_id)
    except (OnboardingError, AlignmentError, OSError, ValueError, KeyError) as exc:
        result = _failure(exc)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") in {"doctor_passed", "workspace_ready", "data_imported", "snapshot_ready", "handoff_ready", "ready"}:
        return 0
    if result.get("status") in {"in_progress", "not_initialized", "doctor_failed"}:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
