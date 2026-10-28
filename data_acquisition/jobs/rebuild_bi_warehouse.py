"""Download the rolling BI order/cash exports, merge prior outside-window history, publish Snapshot."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).parents[1]))
from data_acquisition.auth.auth_sessions import AuthSessionPaths
from workspace_modeling.onboarding.service import import_data, init_workspace, sync
from data_acquisition.connectors.bi.bi_downloads import BIExportConfig, run_bi_download
from data_acquisition.jobs.bi_window_merge import merge_exports_with_prior, rolling_start_date
from workspace_modeling.bridge_alignment.workspace import load_workspace, validate_sync_preconditions


def _valid_xlsx(path: Path) -> None:
    try:
        import openpyxl

        workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
        if not workbook.sheetnames:
            raise ValueError("workbook has no sheets")
        workbook.close()
    except Exception as exc:
        raise RuntimeError(f"invalid BI workbook: {path}: {exc}") from exc


def _snapshot_is_current(workspace: Path, snapshot_id: str) -> bool:
    _, config = load_workspace(workspace)
    return config.get("current_snapshot_id") == snapshot_id


def _backup_bi_inputs(input_data: Path, backup_root: Path) -> dict[str, bool]:
    existed: dict[str, bool] = {}
    for source_id in ("br_work_orders", "br_cash"):
        slot = input_data / source_id
        if slot.is_symlink() or (slot.exists() and not slot.is_dir()):
            raise RuntimeError(f"BI Input source slot must be a directory: {slot}")
        existed[source_id] = slot.is_dir()
        if slot.is_dir():
            shutil.copytree(slot, backup_root / source_id)
    return existed


def _restore_bi_inputs(input_data: Path, backup_root: Path, existed: dict[str, bool]) -> None:
    for source_id in ("br_work_orders", "br_cash"):
        slot = input_data / source_id
        if slot.is_symlink() or slot.is_file():
            slot.unlink()
        elif slot.is_dir():
            shutil.rmtree(slot)
        if existed[source_id]:
            shutil.copytree(backup_root / source_id, slot)


def rebuild(*, workspace: Path, snapshot_id: str, start_date: str, end_date: str,
            export_paths: dict[str, Path] | None = None) -> dict:
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
    validate_sync_preconditions(root=workspace, snapshot_id=snapshot_id)

    temporary_parent = workspace / "Work" / "Runs" / "_bi_rebuild_tmp"
    temporary_parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=f"{snapshot_id}-", dir=temporary_parent))
    keep_dir = workspace / "Work" / "Runs" / "_bi_export_keep" / snapshot_id
    backup_state = "not-created"
    try:
        download_dir = temporary_root / "downloads"
        download_dir.mkdir()
        if export_paths is None:
            artifacts = run_bi_download(
                config=BIExportConfig(
                    browser_profile_dir=AuthSessionPaths(workspace, "bi").browser_profile,
                    auth_session_paths=AuthSessionPaths(workspace, "bi"),
                    download_dir=download_dir,
                    default_start_date=start_date,
                ),
                targets=("orders", "cash"),
                start_date=start_date,
                end_date=end_date,
            )
            paths = {artifact.target: artifact.path for artifact in artifacts}
        else:
            # Explicit validated receiver files; history merge and Snapshot logic stay shared.
            paths = {key: Path(value) for key, value in export_paths.items()}
        if set(paths) != {"orders", "cash"}:
            raise RuntimeError(f"BI download incomplete: {sorted(paths)}")
        for path in paths.values():
            _valid_xlsx(path)

        merge_stats = merge_exports_with_prior(
            workspace=workspace,
            orders_xlsx=paths["orders"],
            cash_xlsx=paths["cash"],
            start_date=start_date,
            output_dir=temporary_root / "merged",
        )
        merged_orders = Path(merge_stats["orders_path"])
        merged_cash = Path(merge_stats["cash_path"])
        _valid_xlsx(merged_orders)
        _valid_xlsx(merged_cash)

        # Retain only these two raw exports; their returned paths outlive this temp directory.
        if keep_dir.exists():
            shutil.rmtree(keep_dir)
        keep_dir.mkdir(parents=True)
        kept = {}
        for label, source in (("orders", paths["orders"]), ("cash", paths["cash"])):
            destination = keep_dir / Path(source).name
            shutil.copy2(source, destination)
            kept[label] = destination

        input_data = workspace / "Input" / "Data"
        backup_root = temporary_root / "input_backup"
        backup_root.mkdir()
        existed = _backup_bi_inputs(input_data, backup_root)
        backup_state = "available"
        try:
            imported_orders = import_data(
                root=workspace, source_id="br_work_orders", source_file=merged_orders, replace=True,
            )
            imported_cash = import_data(
                root=workspace, source_id="br_cash", source_file=merged_cash, replace=True,
            )
            result = sync(root=workspace, snapshot_id=snapshot_id)
            published = _snapshot_is_current(workspace, snapshot_id)
            if result.get("status") != "snapshot_ready":
                raise RuntimeError(json.dumps(result, ensure_ascii=False))
            if not published:
                raise RuntimeError("Snapshot sync returned success without publishing the requested Snapshot")
            backup_state = "published"
        except Exception as operation_error:
            try:
                published = _snapshot_is_current(workspace, snapshot_id)
            except Exception as pointer_error:
                backup_state = "preserve"
                raise RuntimeError(
                    f"cannot confirm current Snapshot after BI Input update; backup retained at {backup_root}; "
                    f"pointer read failed: {pointer_error}; operation error: {operation_error}"
                ) from operation_error
            if published:
                backup_state = "published"
            else:
                try:
                    _restore_bi_inputs(input_data, backup_root, existed)
                except Exception as restore_error:
                    backup_state = "preserve"
                    raise RuntimeError(
                        f"BI Input restoration failed; backup retained at {backup_root}: {restore_error}"
                    ) from restore_error
                backup_state = "restored"
                shutil.rmtree(keep_dir, ignore_errors=True)
            raise

        return {
            "workspace": str(workspace),
            "snapshot_id": snapshot_id,
            "orders": imported_orders["source_file"],
            "cash": imported_cash["source_file"],
            "export_orders": str(kept["orders"]),
            "export_cash": str(kept["cash"]),
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
        }
    except Exception:
        if backup_state in {"not-created", "restored"}:
            shutil.rmtree(keep_dir, ignore_errors=True)
        raise
    finally:
        if backup_state != "preserve":
            shutil.rmtree(temporary_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("customers/shadow_bi_daily"))
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
