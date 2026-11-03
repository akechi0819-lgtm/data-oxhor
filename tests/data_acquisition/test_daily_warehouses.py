from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_acquisition.jobs import daily_warehouses


AS_OF = "2026-10-09"
BI_SNAPSHOT = "snapshot_bi_operations_20261009_daily"
STUDY_SNAPSHOT = "snapshot_study_abroad_20261009_daily"
COMPANY_ID = "company_daily_fixture"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class DailyWarehousesTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self._write_workspace()

    def _write_workspace(self, *, current_bi: str = "snapshot_bi_operations_20261008_old") -> None:
        _write_json(self.workspace / "Work/workspace.json", {
            "schema_version": "workspace.v1",
            "company_id": COMPANY_ID,
            "business_port": "operations",
            "current_snapshot_id": current_bi,
        })
        _write_json(self.workspace / "Work/StudyAbroad/current.json", {
            "schema_version": "study_abroad_warehouse.v1",
            "company_id": COMPANY_ID,
            "run_id": "run_study_previous",
            "snapshot_id": "snapshot_study_abroad_20261008_previous",
            "through_date": "2026-10-08",
            "used_snapshot_ids": [],
        })

    def _success_mocks(self, *, update_bi_pointer: bool = True):
        exports = self.base / "exports"
        exports.mkdir(exist_ok=True)
        orders = exports / "orders.xlsx"
        cash = exports / "cash.xlsx"
        orders.write_bytes(b"orders export")
        cash.write_bytes(b"cash export")
        capture = exports / "tencent.xlsx"
        capture.write_bytes(b"tencent export")
        study_hash = hashlib.sha256(capture.read_bytes()).hexdigest()

        def rebuild(**kwargs):
            if update_bi_pointer:
                workspace_json = self.workspace / "Work/workspace.json"
                config = json.loads(workspace_json.read_text(encoding="utf-8"))
                config["current_snapshot_id"] = kwargs["snapshot_id"]
                _write_json(workspace_json, config)
            return {
                "status": "snapshot_ready",
                "snapshot_id": kwargs["snapshot_id"],
                "start_date": kwargs["start_date"],
                "end_date": kwargs["end_date"],
                "export_orders": str(orders),
                "export_cash": str(cash),
            }

        def update(**kwargs):
            _write_json(self.workspace / "Work/StudyAbroad/current.json", {
                "schema_version": "study_abroad_warehouse.v1",
                "company_id": COMPANY_ID,
                "run_id": kwargs["run_id"],
                "snapshot_id": kwargs["snapshot_id"],
                "through_date": kwargs["through_date"],
                "used_snapshot_ids": [kwargs["snapshot_id"]],
            })
            return {
                "company_id": COMPANY_ID,
                "run_id": kwargs["run_id"],
                "snapshot_id": kwargs["snapshot_id"],
                "through_date": kwargs["through_date"],
                "capture": {"path": str(capture), "sha256": study_hash},
            }

        return rebuild, update

    def _refresh(self, *, run_id: str = "run_daily_fixture",
                 bi_snapshot_id: str = BI_SNAPSHOT,
                 study_snapshot_id: str = STUDY_SNAPSHOT) -> dict:
        return daily_warehouses.refresh_daily(
            workspace=self.workspace,
            as_of_date=AS_OF,
            run_id=run_id,
            bi_snapshot_id=bi_snapshot_id,
            study_snapshot_id=study_snapshot_id,
        )

    def test_success_records_pair_and_passes_ready_guard(self) -> None:
        rebuild, update = self._success_mocks()
        with (
            patch.object(daily_warehouses.rebuild_bi_warehouse, "rebuild", side_effect=rebuild) as bi_call,
            patch.object(daily_warehouses.update_tencent_study_abroad, "update", side_effect=update) as study_call,
        ):
            result = self._refresh()

        self.assertEqual("passed", result["status"])
        bi_call.assert_called_once()
        self.assertEqual("2026-04-09", bi_call.call_args.kwargs["start_date"])
        self.assertEqual(AS_OF, bi_call.call_args.kwargs["end_date"])
        study_call.assert_called_once()
        self.assertEqual(["2026-10"], study_call.call_args.kwargs["refresh_months"])
        self.assertEqual(AS_OF, study_call.call_args.kwargs["through_date"])
        self.assertEqual(result["receipt_sha256"], json.loads(
            (self.workspace / "Work/DailyWarehouseRefresh/current.json").read_text(encoding="utf-8")
        )["receipt_sha256"])

        receipt = daily_warehouses.assert_daily_ready(
            self.workspace, AS_OF,
            bi_snapshot_id=BI_SNAPSHOT,
            study_snapshot_id=STUDY_SNAPSHOT,
        )
        self.assertEqual("passed", receipt["status"])
        self.assertTrue((self.workspace / "Work/DailyWarehouseRefresh/last_good.json").is_file())

    def test_content_delivery_uses_the_successful_bi_export(self) -> None:
        _write_json(self.workspace / ".private/content-work-orders.json", {})
        rebuild, update = self._success_mocks()
        with (
            patch.object(daily_warehouses.rebuild_bi_warehouse, "rebuild", side_effect=rebuild),
            patch.object(daily_warehouses.update_tencent_study_abroad, "update", side_effect=update),
            patch.object(daily_warehouses.sync_content_work_orders, "sync",
                         return_value={"status": "passed", "added": 2}) as delivery,
        ):
            result = self._refresh()
        self.assertEqual("passed", result["status"])
        self.assertEqual(2, result["content_work_orders"]["added"])
        self.assertEqual(self.base / "exports/orders.xlsx", delivery.call_args.kwargs["source_file"])
        self.assertEqual(AS_OF, delivery.call_args.kwargs["as_of_date"])
        self.assertEqual("run_daily_fixture", delivery.call_args.kwargs["run_id"])

    def test_content_delivery_failure_does_not_invalidate_the_warehouses(self) -> None:
        _write_json(self.workspace / ".private/content-work-orders.json", {})
        rebuild, update = self._success_mocks()
        with (
            patch.object(daily_warehouses.rebuild_bi_warehouse, "rebuild", side_effect=rebuild),
            patch.object(daily_warehouses.update_tencent_study_abroad, "update", side_effect=update),
            patch.object(daily_warehouses.sync_content_work_orders, "sync",
                         side_effect=RuntimeError("private token must not appear")),
        ):
            result = self._refresh()
        self.assertEqual("passed", result["status"])
        self.assertEqual("success", result["sources"]["bi"]["status"])
        self.assertEqual("success", result["sources"]["study_abroad"]["status"])
        self.assertEqual("failed", result["content_work_orders"]["status"])
        self.assertNotIn("private token", json.dumps(result))
        daily_warehouses.assert_daily_ready(self.workspace, AS_OF)

    def test_running_attempt_blocks_old_ready_state_before_either_source_moves(self) -> None:
        state_root = self.workspace / "Work/DailyWarehouseRefresh"
        old_last_good = {"status": "passed", "run_id": "run_daily_previous"}
        _write_json(state_root / "last_good.json", old_last_good)
        rebuild, update = self._success_mocks()

        def inspect_running_then_rebuild(**kwargs):
            current = json.loads((state_root / "current.json").read_text(encoding="utf-8"))
            self.assertEqual("running", current["status"])
            self.assertEqual(old_last_good, json.loads((state_root / "last_good.json").read_text(encoding="utf-8")))
            with self.assertRaisesRegex(ValueError, "did not pass"):
                daily_warehouses.assert_daily_ready(self.workspace, AS_OF)
            return rebuild(**kwargs)

        with (
            patch.object(
                daily_warehouses.rebuild_bi_warehouse,
                "rebuild",
                side_effect=inspect_running_then_rebuild,
            ),
            patch.object(daily_warehouses.update_tencent_study_abroad, "update", side_effect=update),
        ):
            result = self._refresh()
        self.assertEqual("passed", result["status"])

    def test_success_return_without_matching_bi_pointer_fails_joint_attempt(self) -> None:
        rebuild, update = self._success_mocks(update_bi_pointer=False)
        with (
            patch.object(daily_warehouses.rebuild_bi_warehouse, "rebuild", side_effect=rebuild),
            patch.object(daily_warehouses.update_tencent_study_abroad, "update", side_effect=update),
        ):
            result = self._refresh()

        self.assertEqual("failed", result["status"])
        self.assertIn("BI current Snapshot", result["joint_error"])
        current = json.loads((self.workspace / "Work/DailyWarehouseRefresh/current.json").read_text(encoding="utf-8"))
        self.assertEqual("failed", current["status"])
        self.assertFalse((self.workspace / "Work/DailyWarehouseRefresh/last_good.json").exists())

    def test_check_cli_is_read_only_and_returns_ready_identity(self) -> None:
        receipt = {
            "run_id": "run_daily_cli",
            "as_of_date": AS_OF,
            "sources": {
                "bi": {"snapshot_id": BI_SNAPSHOT},
                "study_abroad": {"snapshot_id": STUDY_SNAPSHOT},
            },
        }
        output = io.StringIO()
        with (
            patch.object(daily_warehouses, "assert_daily_ready", return_value=receipt) as ready,
            patch.object(daily_warehouses, "refresh_daily") as refresh,
            redirect_stdout(output),
        ):
            code = daily_warehouses.main([
                "check", "--workspace", str(self.workspace), "--as-of-date", AS_OF,
                "--bi-snapshot-id", BI_SNAPSHOT,
            ])

        self.assertEqual(0, code)
        self.assertEqual({
            "status": "passed",
            "run_id": "run_daily_cli",
            "as_of_date": AS_OF,
            "bi_snapshot_id": BI_SNAPSHOT,
            "study_snapshot_id": STUDY_SNAPSHOT,
        }, json.loads(output.getvalue()))
        ready.assert_called_once_with(
            Path(self.workspace), AS_OF,
            bi_snapshot_id=BI_SNAPSHOT,
            study_snapshot_id=None,
        )
        refresh.assert_not_called()

    def test_check_cli_reports_failure_without_refresh_arguments(self) -> None:
        output = io.StringIO()
        with (
            patch.object(daily_warehouses, "assert_daily_ready", side_effect=ValueError("not ready")) as ready,
            patch.object(daily_warehouses, "refresh_daily") as refresh,
            redirect_stdout(output),
        ):
            code = daily_warehouses.main([
                "check", "--workspace", str(self.workspace), "--as-of-date", AS_OF,
            ])

        self.assertEqual(1, code)
        self.assertEqual({"status": "failed", "error": "not ready"}, json.loads(output.getvalue()))
        ready.assert_called_once_with(
            Path(self.workspace), AS_OF,
            bi_snapshot_id=None,
            study_snapshot_id=None,
        )
        refresh.assert_not_called()

    def test_both_sources_are_attempted_and_failed_current_blocks_retained_last_good(self) -> None:
        state_root = self.workspace / "Work/DailyWarehouseRefresh"
        old_last_good = {"status": "passed", "run_id": "run_daily_previous"}
        _write_json(state_root / "last_good.json", old_last_good)
        with (
            patch.object(
                daily_warehouses.rebuild_bi_warehouse,
                "rebuild",
                side_effect=RuntimeError("token=do-not-store-this"),
            ) as bi_call,
            patch.object(
                daily_warehouses.update_tencent_study_abroad,
                "update",
                side_effect=RuntimeError("signed_url=do-not-store-this-either"),
            ) as study_call,
        ):
            result = self._refresh()

        self.assertEqual("failed", result["status"])
        self.assertEqual("failed", result["sources"]["bi"]["status"])
        self.assertEqual("failed", result["sources"]["study_abroad"]["status"])
        bi_call.assert_called_once()
        study_call.assert_called_once()
        receipt_text = Path(result["receipt_path"]).read_text(encoding="utf-8")
        self.assertNotIn("do-not-store-this", receipt_text)
        self.assertEqual(old_last_good, json.loads((state_root / "last_good.json").read_text(encoding="utf-8")))
        current = json.loads((state_root / "current.json").read_text(encoding="utf-8"))
        self.assertEqual("failed", current["status"])
        self.assertEqual(AS_OF, current["as_of_date"])
        with self.assertRaisesRegex(ValueError, "did not pass"):
            daily_warehouses.assert_daily_ready(self.workspace, AS_OF)

    def test_uninitialized_bi_is_not_created_and_tencent_is_still_attempted(self) -> None:
        (self.workspace / "Work/workspace.json").unlink()
        with (
            patch.object(daily_warehouses.rebuild_bi_warehouse, "rebuild") as bi_call,
            patch.object(
                daily_warehouses.update_tencent_study_abroad,
                "update",
                side_effect=ValueError("missing BI workspace"),
            ) as study_call,
        ):
            result = self._refresh()

        bi_call.assert_not_called()
        study_call.assert_called_once()
        self.assertFalse((self.workspace / "Work/workspace.json").exists())
        self.assertEqual("failed", result["status"])
        receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual("failed", receipt["sources"]["bi"]["status"])
        self.assertEqual("failed", receipt["sources"]["study_abroad"]["status"])
        self.assertIn("not initialized", receipt["sources"]["bi"]["error"])

    def test_bi_failure_still_publishes_successful_tencent_source(self) -> None:
        _write_json(self.workspace / ".private/content-work-orders.json", {})
        _, update = self._success_mocks()
        with (
            patch.object(daily_warehouses.rebuild_bi_warehouse, "rebuild", side_effect=TimeoutError("login")),
            patch.object(daily_warehouses.update_tencent_study_abroad, "update", side_effect=update) as study_call,
            patch.object(daily_warehouses.sync_content_work_orders, "sync") as delivery,
        ):
            result = self._refresh()

        self.assertEqual("failed", result["status"])
        self.assertEqual("failed", result["sources"]["bi"]["status"])
        self.assertEqual("success", result["sources"]["study_abroad"]["status"])
        study_call.assert_called_once()
        delivery.assert_not_called()
        with self.assertRaisesRegex(ValueError, "did not pass"):
            daily_warehouses.assert_daily_ready(self.workspace, AS_OF)

    def test_tencent_failure_keeps_successful_bi_terminal_status(self) -> None:
        rebuild, _ = self._success_mocks()
        with (
            patch.object(daily_warehouses.rebuild_bi_warehouse, "rebuild", side_effect=rebuild),
            patch.object(
                daily_warehouses.update_tencent_study_abroad,
                "update",
                side_effect=RuntimeError("signed_url=must-not-be-stored"),
            ) as study_call,
        ):
            result = self._refresh()

        self.assertEqual("failed", result["status"])
        self.assertEqual("success", result["sources"]["bi"]["status"])
        self.assertEqual("failed", result["sources"]["study_abroad"]["status"])
        self.assertNotIn("must-not-be-stored", Path(result["receipt_path"]).read_text(encoding="utf-8"))
        study_call.assert_called_once()

    def test_receipt_hash_and_snapshot_pointers_are_checked(self) -> None:
        rebuild, update = self._success_mocks()
        with (
            patch.object(daily_warehouses.rebuild_bi_warehouse, "rebuild", side_effect=rebuild),
            patch.object(daily_warehouses.update_tencent_study_abroad, "update", side_effect=update),
        ):
            result = self._refresh()

        with self.assertRaisesRegex(ValueError, "another date"):
            daily_warehouses.assert_daily_ready(self.workspace, "2026-10-08")
        with self.assertRaisesRegex(ValueError, "requested id"):
            daily_warehouses.assert_daily_ready(self.workspace, AS_OF, bi_snapshot_id="snapshot_bi_other_20261009")

        self._write_workspace(current_bi="snapshot_bi_other_20261009")
        with self.assertRaisesRegex(ValueError, "does not match the successful receipt"):
            daily_warehouses.assert_daily_ready(self.workspace, AS_OF)

        receipt_path = Path(result["receipt_path"])
        receipt_path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "has changed"):
            daily_warehouses.assert_daily_ready(self.workspace, AS_OF)

    def test_run_id_collision_is_rejected_before_a_second_source_call(self) -> None:
        rebuild, update = self._success_mocks()
        with (
            patch.object(daily_warehouses.rebuild_bi_warehouse, "rebuild", side_effect=rebuild) as bi_call,
            patch.object(daily_warehouses.update_tencent_study_abroad, "update", side_effect=update) as study_call,
        ):
            self._refresh()
            with self.assertRaisesRegex(ValueError, "already been used"):
                self._refresh()

        bi_call.assert_called_once()
        study_call.assert_called_once()

    def test_bi_snapshot_id_must_encode_the_explicit_as_of_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "must contain the as_of_date"):
            self._refresh(bi_snapshot_id="snapshot_bi_operations_20261008_wrong")


if __name__ == "__main__":
    unittest.main()
