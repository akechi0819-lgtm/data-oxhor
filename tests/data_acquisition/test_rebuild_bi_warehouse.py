from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openpyxl import Workbook

from data_acquisition.jobs import rebuild_bi_warehouse
from workspace_modeling.bridge_alignment.service import start_session
from workspace_modeling.bridge_alignment.workspace import (
    AlignmentError,
    init_workspace,
    load_workspace,
    sync_data,
)


def _write_workbook(path: Path, sheet_name: str, rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def _mock_download(config, targets, start_date, end_date):
    downloaded = []
    for target in targets:
        if target == "orders":
            filename, sheet, rows = (
                "BI工单.xlsx",
                "工单明细导出用表",
                [["ID", "分配时间", "姓名"], ["NEW", "2026-08-01", "新工单"]],
            )
        else:
            filename, sheet, rows = (
                "BI现金.xlsx",
                "现金明细表",
                [["工单ID", "业务日期", "现金收入"], ["NEW", "2026-08-01", 200]],
            )
        path = config.download_dir / filename
        _write_workbook(path, sheet, rows)
        downloaded.append(SimpleNamespace(target=target, path=path))
    return downloaded


class RebuildBIWarehouseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = Path("workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json").resolve()

    def _workspace(self, root: Path) -> Path:
        init_workspace(
            root=root,
            company_id="company_rebuild_test",
            business_port="operations",
            pack_path=self.pack,
        )
        inputs = root / "Input" / "Data"
        _write_workbook(
            inputs / "br_work_orders" / "old-orders.xlsx",
            "工单明细导出用表",
            [["ID", "分配时间", "姓名"], ["OLD", "2026-01-01", "旧工单"]],
        )
        _write_workbook(
            inputs / "br_cash" / "old-cash.xlsx",
            "现金明细表",
            [["工单ID", "业务日期", "现金收入"], ["OLD", "2026-01-01", 100]],
        )
        _write_workbook(
            inputs / "other_source" / "other.xlsx",
            "其他数据",
            [["编号", "日期"], ["O1", "2026-01-01"]],
        )
        sync_data(root=root, snapshot_id="snapshot_rebuild_initial")
        return root

    def _empty_workspace(self, root: Path) -> Path:
        init_workspace(
            root=root,
            company_id="company_rebuild_test",
            business_port="operations",
            pack_path=self.pack,
        )
        return root

    def _bi_files(self, workspace: Path) -> dict[str, bytes]:
        return {
            source_id: next((workspace / "Input" / "Data" / source_id).glob("*.xlsx")).read_bytes()
            for source_id in ("br_work_orders", "br_cash")
        }

    def test_first_import_without_current_snapshot_succeeds_and_duplicate_stops_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._empty_workspace(Path(directory) / "workspace")
            with patch.object(rebuild_bi_warehouse, "run_bi_download", side_effect=_mock_download) as download:
                result = rebuild_bi_warehouse.rebuild(
                    workspace=workspace,
                    snapshot_id="snapshot_rebuild_first",
                    start_date="2026-03-01",
                    end_date="2026-09-30",
                )
                self.assertEqual(1, download.call_count)
                before = self._bi_files(workspace)

                with self.assertRaises(AlignmentError) as captured:
                    rebuild_bi_warehouse.rebuild(
                        workspace=workspace,
                        snapshot_id="snapshot_rebuild_first",
                        start_date="2026-03-01",
                        end_date="2026-09-30",
                    )

            self.assertEqual("SNAPSHOT_EXISTS", captured.exception.code)
            self.assertEqual(1, download.call_count)
            self.assertEqual(before, self._bi_files(workspace))
            self.assertTrue(Path(result["orders"]).is_file())
            self.assertTrue(Path(result["cash"]).is_file())
            self.assertEqual("snapshot_rebuild_first", load_workspace(workspace)[1]["current_snapshot_id"])

    def test_success_preserves_other_sources_and_returns_existing_input_and_export_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory) / "workspace")
            other_path = workspace / "Input" / "Data" / "other_source" / "other.xlsx"
            other_bytes = other_path.read_bytes()

            with patch.object(rebuild_bi_warehouse, "run_bi_download", side_effect=_mock_download):
                result = rebuild_bi_warehouse.rebuild(
                    workspace=workspace,
                    snapshot_id="snapshot_rebuild_next",
                    start_date="2026-03-01",
                    end_date="2026-09-30",
                )

            self.assertTrue(Path(result["orders"]).is_file())
            self.assertTrue(Path(result["cash"]).is_file())
            self.assertTrue(Path(result["export_orders"]).is_file())
            self.assertTrue(Path(result["export_cash"]).is_file())
            self.assertEqual(other_bytes, other_path.read_bytes())
            self.assertEqual("snapshot_rebuild_next", load_workspace(workspace)[1]["current_snapshot_id"])
            self.assertNotIn("export_keep_orders", result)
            self.assertNotIn("export_keep_cash", result)
            self.assertNotIn("prior_landing", result)
            self.assertEqual([], list((workspace / "Work" / "Runs" / "_bi_rebuild_tmp").glob("*")))

    def test_active_session_blocks_before_download_and_input_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory) / "workspace")
            before = self._bi_files(workspace)
            start_session(root=workspace, session_id="session_rebuild_pending")

            with patch.object(rebuild_bi_warehouse, "run_bi_download", side_effect=_mock_download) as download:
                with self.assertRaises(AlignmentError) as captured:
                    rebuild_bi_warehouse.rebuild(
                        workspace=workspace,
                        snapshot_id="snapshot_rebuild_blocked",
                        start_date="2026-03-01",
                        end_date="2026-09-30",
                    )

            self.assertEqual("ACTIVE_SESSION_EXISTS", captured.exception.code)
            download.assert_not_called()
            self.assertEqual(before, self._bi_files(workspace))

    def test_failed_ingest_restores_only_bi_input_slots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory) / "workspace")
            before = self._bi_files(workspace)
            other_path = workspace / "Input" / "Data" / "other_source" / "other.xlsx"
            other_bytes = other_path.read_bytes()
            failure = {
                "status": "failed",
                "errors": [{"code": "SOURCE_INVALID", "message": "synthetic ingest failure"}],
            }

            with (
                patch.object(rebuild_bi_warehouse, "run_bi_download", side_effect=_mock_download),
                patch("workspace_modeling.bridge_alignment.workspace.ingest_sources", return_value=failure),
            ):
                with self.assertRaises(AlignmentError) as captured:
                    rebuild_bi_warehouse.rebuild(
                        workspace=workspace,
                        snapshot_id="snapshot_rebuild_failed",
                        start_date="2026-03-01",
                        end_date="2026-09-30",
                    )

            self.assertEqual("SOURCE_INVALID", captured.exception.code)
            self.assertEqual(before, self._bi_files(workspace))
            self.assertEqual(other_bytes, other_path.read_bytes())
            self.assertFalse((workspace / "Work" / "Runs" / "_bi_export_keep" / "snapshot_rebuild_failed").exists())
            self.assertEqual("snapshot_rebuild_initial", load_workspace(workspace)[1]["current_snapshot_id"])

    def test_second_bi_slot_copy_failure_restores_both_original_slots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory) / "workspace")
            before = self._bi_files(workspace)
            real_copyfile = __import__("shutil").copyfile

            def fail_cash_import(source, destination, *args, **kwargs):
                if Path(destination).name == "现金表_merged.xlsx":
                    raise OSError("synthetic cash import copy failure")
                return real_copyfile(source, destination, *args, **kwargs)

            with (
                patch.object(rebuild_bi_warehouse, "run_bi_download", side_effect=_mock_download),
                patch("workspace_modeling.onboarding.service.shutil.copyfile", side_effect=fail_cash_import),
            ):
                with self.assertRaisesRegex(OSError, "cash import copy failure"):
                    rebuild_bi_warehouse.rebuild(
                        workspace=workspace,
                        snapshot_id="snapshot_rebuild_copy_failure",
                        start_date="2026-03-01",
                        end_date="2026-09-30",
                    )

            self.assertEqual(before, self._bi_files(workspace))
            self.assertEqual("snapshot_rebuild_initial", load_workspace(workspace)[1]["current_snapshot_id"])

    def test_restore_failure_reports_and_retains_both_original_slot_backups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory) / "workspace")
            before = self._bi_files(workspace)
            real_copyfile = __import__("shutil").copyfile

            def fail_cash_import(source, destination, *args, **kwargs):
                if Path(destination).name == "现金表_merged.xlsx":
                    raise OSError("synthetic cash import copy failure")
                return real_copyfile(source, destination, *args, **kwargs)

            with (
                patch.object(rebuild_bi_warehouse, "run_bi_download", side_effect=_mock_download),
                patch("workspace_modeling.onboarding.service.shutil.copyfile", side_effect=fail_cash_import),
                patch.object(rebuild_bi_warehouse, "_restore_bi_inputs", side_effect=OSError("synthetic restore failure")),
            ):
                with self.assertRaisesRegex(RuntimeError, "backup retained at") as captured:
                    rebuild_bi_warehouse.rebuild(
                        workspace=workspace,
                        snapshot_id="snapshot_rebuild_restore_failure",
                        start_date="2026-03-01",
                        end_date="2026-09-30",
                    )

            error = str(captured.exception)
            self.assertIn("synthetic restore failure", error)
            backup_root = Path(error.split("backup retained at ", 1)[1].split(":", 1)[0])
            self.assertTrue(backup_root.is_dir())
            for source_id, contents in before.items():
                backup = next((backup_root / source_id).glob("*.xlsx"))
                self.assertEqual(contents, backup.read_bytes())

    def test_input_is_not_restored_if_sync_raises_after_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory) / "workspace")
            real_sync = rebuild_bi_warehouse.sync

            def publish_then_raise(*, root: Path, snapshot_id: str):
                real_sync(root=root, snapshot_id=snapshot_id)
                raise RuntimeError("synthetic error after publication")

            with (
                patch.object(rebuild_bi_warehouse, "run_bi_download", side_effect=_mock_download),
                patch.object(rebuild_bi_warehouse, "sync", side_effect=publish_then_raise),
            ):
                with self.assertRaisesRegex(RuntimeError, "after publication"):
                    rebuild_bi_warehouse.rebuild(
                        workspace=workspace,
                        snapshot_id="snapshot_rebuild_published",
                        start_date="2026-03-01",
                        end_date="2026-09-30",
                    )

            self.assertEqual("snapshot_rebuild_published", load_workspace(workspace)[1]["current_snapshot_id"])
            self.assertEqual("工单表_merged.xlsx", next((workspace / "Input" / "Data" / "br_work_orders").glob("*.xlsx")).name)
            self.assertEqual("现金表_merged.xlsx", next((workspace / "Input" / "Data" / "br_cash").glob("*.xlsx")).name)

    def test_unreadable_pointer_preserves_the_local_input_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(Path(directory) / "workspace")
            before = self._bi_files(workspace)

            with (
                patch.object(rebuild_bi_warehouse, "run_bi_download", side_effect=_mock_download),
                patch.object(rebuild_bi_warehouse, "load_workspace", side_effect=RuntimeError("pointer unavailable")),
            ):
                with self.assertRaisesRegex(RuntimeError, "backup retained at") as captured:
                    rebuild_bi_warehouse.rebuild(
                        workspace=workspace,
                        snapshot_id="snapshot_rebuild_pointer_unknown",
                        start_date="2026-03-01",
                        end_date="2026-09-30",
                    )

            self.assertIn("pointer unavailable", str(captured.exception))
            self.assertNotEqual(before, self._bi_files(workspace))
            retained = list((workspace / "Work" / "Runs" / "_bi_rebuild_tmp").glob("*/input_backup"))
            self.assertEqual(1, len(retained))
            for source_id, contents in zip(("br_work_orders", "br_cash"), before.values()):
                backup = next((retained[0] / source_id).glob("*.xlsx"))
                self.assertEqual(contents, backup.read_bytes())


if __name__ == "__main__":
    unittest.main()
