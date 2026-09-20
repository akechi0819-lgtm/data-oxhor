"""Download the rolling BI order/cash exports, merge prior outside-window history, publish Snapshot."""

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
from data_acquisition.jobs.bi_window_merge import merge_exports_with_prior, rolling_start_date


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
            pack_path=Path(__file__).parents[2]
            / "workspace_modeling"
            / "business_pack"
            / "packs"
            / "education_training_operations_cn"
            / "pack.json",
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

    merge_dir = raw_dir / "_merged"
    work_order_reference = workspace / "Input" / "Reference" / "留学-FY26-资源表.xlsx"
    if not work_order_reference.is_file():
        raise RuntimeError(f"missing work-order cleaning reference: {work_order_reference}")
    merge_stats = merge_exports_with_prior(
        workspace=workspace,
        orders_xlsx=paths["orders"],
        cash_xlsx=paths["cash"],
        start_date=start_date,
        end_date=end_date,
        output_dir=merge_dir,
        work_order_reference=work_order_reference,
    )
    merged_orders = Path(merge_stats["orders_path"])
    merged_cash = Path(merge_stats["cash_path"])
    _valid_xlsx(merged_orders)
    _valid_xlsx(merged_cash)

    input_data = workspace / "Input" / "Data"
    if input_data.exists():
        for slot in input_data.iterdir():
            if slot.is_dir():
                shutil.rmtree(slot)
    import_data(root=workspace, source_id="br_work_orders", source_file=merged_orders, replace=True)
    import_data(root=workspace, source_id="br_cash", source_file=merged_cash, replace=True)
    result = sync(root=workspace, snapshot_id=snapshot_id)
    if result.get("status") != "snapshot_ready":
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    # Keep raw export copies for near-window field audit (孙悟空建议)；再删临时 _bi_downloads
    keep_dir = workspace / "Work" / "Runs" / "_bi_export_keep" / snapshot_id
    keep_dir.mkdir(parents=True, exist_ok=True)
    kept = {}
    for label, src in (("orders", paths["orders"]), ("cash", paths["cash"])):
        dest = keep_dir / Path(src).name
        shutil.copy2(src, dest)
        kept[label] = str(dest)
    shutil.rmtree(raw_dir, ignore_errors=True)
    return {
        "workspace": str(workspace),
        "snapshot_id": snapshot_id,
        "orders": str(merged_orders),
        "cash": str(merged_cash),
        "export_orders": str(paths["orders"]),
        "export_cash": str(paths["cash"]),
        "status": result["status"],
        "start_date": start_date,
        "end_date": end_date,
        "export_orders_rows": merge_stats["export_orders_rows"],
        "export_cash_rows": merge_stats["export_cash_rows"],
        "merged_orders_rows": merge_stats["merged_orders_rows"],
        "merged_cash_rows": merge_stats["merged_cash_rows"],
        "prior_orders_rows": merge_stats["prior_orders_rows"],
        "prior_cash_rows": merge_stats["prior_cash_rows"],
        "outside_orders_rows": merge_stats["outside_orders_rows"],
        "outside_cash_rows": merge_stats["outside_cash_rows"],
        "work_order_cleaning": merge_stats.get("work_order_cleaning", {}),
        "prior_landing": merge_stats.get("prior_landing"),
        "export_keep_dir": str(keep_dir),
        "export_keep_orders": kept["orders"],
        "export_keep_cash": kept["cash"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("customers/bi_operations"))
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument(
        "--start-date",
        default=None,
        help="Export window start (ISO). Default: today minus 6 calendar months.",
    )
    parser.add_argument("--end-date", default=date.today().isoformat())
    args = parser.parse_args()
    start_date = args.start_date or rolling_start_date()
    try:
        print(
            json.dumps(
                rebuild(
                    workspace=args.workspace,
                    snapshot_id=args.snapshot_id,
                    start_date=start_date,
                    end_date=args.end_date,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
