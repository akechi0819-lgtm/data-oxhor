"""Build a non-current shadow Snapshot for the study-abroad offline market board.

The command copies the current BI work-order workbook, fills country/line
fields with the same reference used by the online board, and publishes an
immutable Data Platform Snapshot under the supplied shadow root. It never
edits the customer's Input slots, main-warehouse cleaning, or
Work/workspace.json current pointer. Offline L1/L2 stay in the saved query.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from data_acquisition.jobs.bi_window_merge import _read_xlsx_rows, _write_xlsx
from data_acquisition.jobs.work_order_cleaning import (
    OUTPUT_COLUMNS,
    _extract_country_with_source,
    _is_study_abroad_target,
    _resolve_line,
    load_work_order_reference,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "br_work_orders"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_file(workspace: Path) -> Path:
    candidates = sorted(
        path
        for path in (workspace / "Input" / "Data" / SOURCE_ID).iterdir()
        if path.is_file() and not path.name.startswith("~$") and path.suffix.lower() in {".xlsx", ".xlsm"}
    )
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one work-order workbook, found {len(candidates)}")
    return candidates[0]


def _fill_country_line(rows: list[dict], reference) -> dict[str, int]:
    stats = {
        "target_rows": 0,
        "country_filled": 0,
        "line_filled": 0,
    }
    for row in rows:
        for column in OUTPUT_COLUMNS:
            row.setdefault(column, "")
        if not _is_study_abroad_target(row):
            continue
        stats["target_rows"] += 1
        country, _source = _extract_country_with_source(row)
        row["意向国家"] = country
        if country:
            stats["country_filled"] += 1
        line = _resolve_line(country, str(row.get("咨询方式一级渠道") or ""), reference)
        row["矫正条线"] = line
        if line:
            stats["line_filled"] += 1
    return stats


def build_shadow_snapshot(
    *, workspace: Path, shadow_root: Path, run_id: str, snapshot_id: str
) -> dict:
    workspace = workspace.resolve()
    shadow_root = shadow_root.resolve()
    source = _source_file(workspace)
    reference_path = workspace / "Input" / "Reference" / "留学-FY26-资源表.xlsx"
    if not reference_path.is_file():
        raise RuntimeError(f"missing work-order cleaning reference: {reference_path}")

    sheet_name, columns, rows = _read_xlsx_rows(source)
    fill_stats = _fill_country_line(rows, load_work_order_reference(reference_path))
    for column in OUTPUT_COLUMNS:
        if column not in columns:
            columns.append(column)

    shadow_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{run_id}-", dir=shadow_root) as temp_dir:
        staging = Path(temp_dir)
        filled_path = staging / source.name
        manifest_path = staging / "manifest.json"
        _write_xlsx(filled_path, columns, rows, sheet_name)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "shadow_source_manifest.v1",
                    "sources": {
                        SOURCE_ID: {
                            "filename": filled_path.name,
                            "sha256": _sha256(filled_path),
                        }
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        command = [
            sys.executable,
            "-m",
            "interfaces.data_platform",
            "ingest",
            "--run-id",
            run_id,
            "--snapshot-id",
            snapshot_id,
            "--output-root",
            str(shadow_root),
            "--manifest",
            str(manifest_path),
            "--source",
            f"{SOURCE_ID}={filled_path}",
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            result = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"shadow ingest returned non-JSON output: {completed.stdout or completed.stderr}"
            ) from exc
        if completed.returncode != 0 or result.get("status") != "passed":
            raise RuntimeError(json.dumps(result, ensure_ascii=False))

    return {
        "status": "shadow_snapshot_created",
        "workspace": str(workspace),
        "shadow_root": str(shadow_root),
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "warehouse": str(
            shadow_root / run_id / "data" / "snapshots" / snapshot_id / "warehouse.duckdb"
        ),
        "country_line": fill_stats,
        "source_rows": len(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("customers/bi_operations"))
    parser.add_argument(
        "--shadow-root",
        type=Path,
        default=Path("customers/bi_operations/Work/ShadowOfflineMarket"),
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--snapshot-id", required=True)
    args = parser.parse_args()
    try:
        result = build_shadow_snapshot(
            workspace=args.workspace,
            shadow_root=args.shadow_root,
            run_id=args.run_id,
            snapshot_id=args.snapshot_id,
        )
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
