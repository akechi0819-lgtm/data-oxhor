import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from dashboard_product.shadow_bi.p5.full_daily import DailyBlocked
from data_acquisition.jobs.prepare_full_daily import (
    resolve_sem_receipt, sem_auth_workspace, sem_capture_status, tencent_window_status,
)


class SEMTotalEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.receipt = self.root / "capture.json"
        self.receipt.write_text("{}")

    def test_auto_mode_calls_saved_session_host_for_same_batch_output(self):
        runner = Mock(return_value={
            "status": "success",
            "capture_receipt": str(self.receipt),
            "reused_existing": True,
            "exported": False,
            "published": False,
        })
        result = resolve_sem_receipt(
            workspace=self.root,
            mapping_manifest=self.root / "sources.json",
            output=self.root / "sem",
            start="2026-10-01",
            through="2026-10-28",
            use_saved_session=True,
            executable_path="/installed/chrome-for-testing",
            sem_runner=runner,
        )
        self.assertEqual(result, self.receipt.resolve())
        runner.assert_called_once_with(
            workspace=self.root,
            mapping_manifest=self.root / "sources.json",
            output=self.root / "sem",
            start_date="2026-10-01",
            through_date="2026-10-28",
            executable_path="/installed/chrome-for-testing",
        )

    def test_sem_host_auth_uses_repository_root_not_customer_workspace(self):
        repo_root = Path(__file__).resolve().parents[1]
        self.assertEqual(sem_auth_workspace(), repo_root)

    def test_download_only_sem_capture_is_accepted_and_reported_as_partial(self):
        status = sem_capture_status({
            'status': 'success', 'start_date': '2026-10-01', 'through_date': '2026-10-28',
            'account_ids': ['2665', 'bing'], 'files': [{'path': 'native.xlsx'}],
            'completion': {'complete': False, 'through_date': None, 'basis': 'download_only'},
        })
        self.assertTrue(status['accepted'])
        self.assertEqual(status['status'], 'partial_marker_unavailable')
        self.assertFalse(status['completion_marked'])
        self.assertEqual(status['available_through_date'], '2026-10-28')
        self.assertEqual(status['available_account_count'], 2)

    def test_failed_sem_capture_is_not_accepted(self):
        self.assertFalse(sem_capture_status({'status': 'blocked'})['accepted'])

    def test_tencent_display_native_sparse_rows_remain_sparse_under_user_confirmed_scope(self):
        window = ["2026-09-01", "2026-10-28"]
        result = {"phase": "verified", "product_scope": "display_plus", "window": window,
                  "task_id": 123, "file_sha256": "a" * 64,
                  "native": {"product_scope": "display_plus", "selected_window": window,
                             "scope_dates_complete": False,
                             "missing_selected_dates": ["2026-09-17", "2026-10-28"]}}
        inventory = {"sha256": "a" * 64, "export_task_id": "123",
                     "completion": {"verified": True, "through_date": window[1],
                                    "basis": "native_export_window"}}
        status = tencent_window_status(
            result, inventory, scope="display_plus", selected_window=window,
            sparse_display_allowed=True,
        )
        self.assertTrue(status["export_window_verified"])
        self.assertFalse(status["native_dates_complete"])
        self.assertTrue(status["sparse_display_accepted"])
        self.assertEqual(status["unreported_dates"], ["2026-09-17", "2026-10-28"])

    def test_tencent_search_sparse_rows_still_block_without_scope_approval(self):
        window = ["2026-09-01", "2026-10-28"]
        result = {"phase": "verified", "product_scope": "legacy_search", "window": window,
                  "task_id": 123, "file_sha256": "a" * 64,
                  "native": {"product_scope": "legacy_search", "selected_window": window,
                             "scope_dates_complete": False,
                             "missing_selected_dates": ["2026-10-28"]}}
        inventory = {"sha256": "a" * 64, "export_task_id": "123",
                     "completion": {"verified": True, "through_date": window[1],
                                    "basis": "native_export_window"}}
        with self.assertRaisesRegex(DailyBlocked, "tencent_sparse_window_not_confirmed"):
            tencent_window_status(result, inventory, scope="legacy_search",
                                  selected_window=window, sparse_display_allowed=True)

    def test_explicit_receipt_does_not_call_saved_session_host(self):
        runner = Mock()
        result = resolve_sem_receipt(
            workspace=self.root, mapping_manifest=self.root / "sources.json",
            output=self.root / "sem", start="2026-10-01", through="2026-10-28",
            receipt=self.receipt, sem_runner=runner,
        )
        self.assertEqual(result, self.receipt.resolve())
        runner.assert_not_called()

    def test_default_without_receipt_or_auto_mode_stays_blocked(self):
        with self.assertRaisesRegex(DailyBlocked, "sem_capture_receipt_required"):
            resolve_sem_receipt(
                workspace=self.root, mapping_manifest=self.root / "sources.json",
                output=self.root / "sem", start="2026-10-01", through="2026-10-28",
            )

    def test_failed_or_published_host_result_is_not_accepted(self):
        for result in (
            {"status": "failed", "capture_receipt": str(self.receipt)},
            {"status": "success", "capture_receipt": str(self.receipt), "published": True},
            {"status": "success", "published": False},
        ):
            with self.subTest(result=result), self.assertRaisesRegex(DailyBlocked, "sem_export_not_verified"):
                resolve_sem_receipt(
                    workspace=self.root, mapping_manifest=self.root / "sources.json",
                    output=self.root / "sem", start="2026-10-01", through="2026-10-28",
                    use_saved_session=True, sem_runner=Mock(return_value=result),
                )

    def test_auto_mode_rejects_manual_receipt_ambiguity(self):
        with self.assertRaisesRegex(DailyBlocked, "sem_input_mode_ambiguous"):
            resolve_sem_receipt(
                workspace=self.root, mapping_manifest=self.root / "sources.json",
                output=self.root / "sem", start="2026-10-01", through="2026-10-28",
                receipt=self.receipt, use_saved_session=True,
            )


if __name__ == "__main__":
    unittest.main()
