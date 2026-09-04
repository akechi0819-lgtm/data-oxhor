from __future__ import annotations

import argparse
import json
from pathlib import Path

from workspace_modeling.business_pack.service import PackError, default_pack_path, describe_pack, validate_pack


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="business-pack")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "describe"):
        command = commands.add_parser(name)
        command.add_argument("--pack", type=Path, default=default_pack_path())
    return parser


def _failure(exc: PackError) -> dict[str, object]:
    return {
        "schema_version": "business_pack_error.v1",
        "status": "failed",
        "errors": [{"code": exc.code, "message": str(exc)}],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            document = json.loads(args.pack.read_text(encoding="utf-8"))
            result = validate_pack(document)
        else:
            result = describe_pack(args.pack)
    except OSError as exc:
        result = _failure(PackError("PACK_NOT_FOUND", str(exc)))
    except json.JSONDecodeError as exc:
        result = _failure(PackError("PACK_JSON_INVALID", str(exc)))
    except PackError as exc:
        result = _failure(exc)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
