"""Download the complete BI order/cash exports and publish a fresh Snapshot."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from data_acquisition.auth.auth_sessions import AuthSessionPaths
from workspace_modeling.onboarding.service import import_data, init_workspace, sync
from data_acquisition.connectors.bi.bi_downloads import BIExportConfig, run_bi_download


def _valid_xlsx(path: Path) -> None:
    try:
        import openpyxl

        workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
        if not workbook.sheetnames:
            raise ValueError("workbook has no sheets")
        workbook.close()
    except Exception as exc:
        raise RuntimeError(f"invalid BI workbook: {path}: {exc}") from exc


def rebuild(*, workspace: Path, snapshot_id: str, start_date: str, end_date: str) -> dict:
    workspace = workspace.resolve()
    if not (workspace / "Work" / "workspace.json").exists():
        init_workspace(
            root=workspace,
            company_id="workspace_bi_operations",
            business_port="operations",
            pack_path=Path(__file__).parents[2] / "workspace_modeling" / "business_pack" / "packs" / "education_training_operations_cn" / "pack.json",
        )
    raw_dir = workspace / "Work" / "Runs" / "_bi_downloads"
    raw_dir.mkdir(parents=True, exist_ok=True)
    artifacts = run_bi_download(
        config=BIExportConfig(
            browser_profile_dir=AuthSessionPaths(workspace, "bi").browser_profile,
            auth_session_paths=AuthSessionPaths(workspace, "bi"),
            download_dir=raw_dir,
            default_start_date=start_date,
        ),
        targets=("orders", "cash"),
        start_date=start_date,
        end_date=end_date,
    )
    paths = {artifact.target: artifact.path for artifact in artifacts}
    if set(paths) != {"orders", "cash"}:
        raise RuntimeError(f"BI download incomplete: {sorted(paths)}")
    for path in paths.values():
        _valid_xlsx(path)
    input_data = workspace / "Input" / "Data"
    for slot in input_data.iterdir():
        if slot.is_dir():
            shutil.rmtree(slot)
    import_data(root=workspace, source_id="br_work_orders", source_file=paths["orders"], replace=True)
    import_data(root=workspace, source_id="br_cash", source_file=paths["cash"], replace=True)
    result = sync(root=workspace, snapshot_id=snapshot_id)
    if result.get("status") != "snapshot_ready":
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    shutil.rmtree(raw_dir, ignore_errors=True)
    return {"workspace": str(workspace), "snapshot_id": snapshot_id, "orders": str(paths["orders"]), "cash": str(paths["cash"]), "status": result["status"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("customers/bi_operations"))
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--start-date", default="2025-06-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    args = parser.parse_args()
    try:
        print(json.dumps(rebuild(workspace=args.workspace, snapshot_id=args.snapshot_id, start_date=args.start_date, end_date=args.end_date), ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
