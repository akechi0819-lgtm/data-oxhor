from __future__ import annotations
import argparse, json
from pathlib import Path
from data_acquisition.manifests.schema import write_manifest

def main() -> int:
    parser = argparse.ArgumentParser(description="Raw source acquisition utilities")
    cmd = parser.add_subparsers(dest="command", required=True).add_parser("manifest")
    cmd.add_argument("--source-id", required=True); cmd.add_argument("--connector-id", required=True); cmd.add_argument("--source-file", type=Path, required=True); cmd.add_argument("--output", type=Path, required=True); cmd.add_argument("--status", default="retrieved")
    args = parser.parse_args()
    try:
        path = write_manifest(output=args.output, source_id=args.source_id, connector_id=args.connector_id, requested_window=None, source_file=args.source_file, status=args.status)
        print(json.dumps({"status": "manifest_written", "manifest": str(path.resolve())}, ensure_ascii=False)); return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "errors": [str(exc)]}, ensure_ascii=False)); return 1
