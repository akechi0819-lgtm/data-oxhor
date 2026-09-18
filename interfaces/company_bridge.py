from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from workspace_modeling.business_pack.service import PackError, default_pack_path, load_pack
from workspace_modeling.company_bridge.service import (
    BRIDGE_SCHEMA_VERSION,
    BridgeError,
    build_bridge,
    load_bridge,
    load_candidate_set,
    load_json,
    validate_bridge,
    validate_candidate_set,
)


def _load_quality(path):
    from data_platform.query.evidence import verify_receipt
    document, data = verify_receipt(Path(path))
    return {"schema_version": "snapshot_quality_profile.v1", "status": "passed",
            "snapshot_id": document["snapshot_id"], "row_count": len(data["rows"]), "result": data, "errors": []}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="company-bridge")
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan-history", help="read a historical asset tree and emit candidates only")
    scan.add_argument("--root", type=Path, required=True)
    scan.add_argument("--output", type=Path, required=True)
    scan.add_argument("--company-id", required=True)
    scan.add_argument("--candidate-set-id", required=True)
    scan.add_argument("--pack", type=Path, default=default_pack_path())

    candidates = commands.add_parser("validate-candidates", help="validate a historical or reviewed candidate set")
    candidates.add_argument("--input", type=Path, required=True)
    candidates.add_argument("--pack", type=Path, default=default_pack_path())
    candidates.add_argument("--snapshot-description", type=Path)
    candidates.add_argument("--require-role", choices=("historical_scan", "confirmed_review"))

    validate = commands.add_parser("validate", help="validate a formal company_bridge.v1 manifest")
    validate.add_argument("--bridge", type=Path, required=True)
    validate.add_argument("--pack", type=Path, required=True)
    validate.add_argument("--snapshot-description", type=Path, help="optional Data Platform schema compatibility input")
    validate.add_argument("--snapshot-quality", type=Path, help="verified query_receipt.v1 from quality, paired with the Snapshot description")

    build = commands.add_parser("build", help="build a formal Bridge from a reviewed candidate set")
    build.add_argument("--candidates", type=Path, required=True)
    build.add_argument("--pack", type=Path, required=True)
    build.add_argument("--snapshot-description", type=Path, help="optional Data Platform schema compatibility input")
    build.add_argument("--snapshot-quality", type=Path, help="verified query_receipt.v1 from quality, paired with the Snapshot description")
    build.add_argument("--bridge-id", required=True)
    build.add_argument("--bridge-version", required=True)
    build.add_argument("--company-id", required=True)
    build.add_argument("--output", type=Path, required=True)
    return parser


def _failure(code: str, message: str, errors: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "company_bridge_error.v1",
        "status": "failed",
        "errors": errors or [{"code": code, "path": "$", "message": message}],
    }


def _write_new_json(path: Path, document: dict[str, Any]) -> None:
    if path.exists():
        raise BridgeError("OUTPUT_EXISTS", "output path already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _scan_history(args: argparse.Namespace) -> dict[str, Any]:
    from workspace_modeling.company_bridge.history import scan_history

    pack = load_pack(args.pack)
    candidate_set = scan_history(
        root=args.root,
        company_id=args.company_id,
        candidate_set_id=args.candidate_set_id,
        pack=pack,
        output_path=args.output,
    )
    validation = validate_candidate_set(candidate_set, pack=pack, require_role="historical_scan")
    if validation["status"] != "passed":
        raise BridgeError("SCAN_OUTPUT_INVALID", "historical scanner produced an invalid candidate set", validation["errors"])
    _write_new_json(args.output, candidate_set)
    return {
        "schema_version": "company_bridge_scan.v1",
        "status": "passed",
        "candidate_set_id": args.candidate_set_id,
        "candidate_path": str(args.output),
        "candidate_count": validation["candidate_count"],
        "rejection_count": validation["rejection_count"],
        "errors": [],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "scan-history":
            result = _scan_history(args)
        elif args.command == "validate-candidates":
            pack = load_pack(args.pack)
            description = load_json(args.snapshot_description) if args.snapshot_description else None
            document = load_candidate_set(args.input)
            result = validate_candidate_set(document, pack=pack, description=description, require_role=args.require_role)
        elif args.command == "validate":
            pack = load_pack(args.pack)
            description = load_json(args.snapshot_description) if args.snapshot_description else None
            quality = _load_quality(args.snapshot_quality) if args.snapshot_quality else None
            document = load_bridge(args.bridge)
            result = validate_bridge(document, pack=pack, description=description, quality=quality)
        else:
            pack = load_pack(args.pack)
            description = load_json(args.snapshot_description) if args.snapshot_description else None
            quality = _load_quality(args.snapshot_quality) if args.snapshot_quality else None
            candidates = load_candidate_set(args.candidates)
            document = build_bridge(
                candidates=candidates,
                pack=pack,
                description=description,
                quality=quality,
                bridge_id=args.bridge_id,
                bridge_version=args.bridge_version,
                company_id=args.company_id,
            )
            _write_new_json(args.output, document)
            result = {
                "schema_version": BRIDGE_SCHEMA_VERSION,
                "status": "passed",
                "bridge_id": args.bridge_id,
                "bridge_version": args.bridge_version,
                "bridge_path": str(args.output),
                "errors": [],
            }
    except (BridgeError, PackError, OSError, ValueError) as exc:
        errors = getattr(exc, "errors", None)
        result = _failure(getattr(exc, "code", "COMPANY_BRIDGE_FAILED"), str(exc), errors)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
