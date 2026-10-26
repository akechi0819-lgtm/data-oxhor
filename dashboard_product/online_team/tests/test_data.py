"""Regression checks for helpers shared by native dashboard calculations."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dashboard_product.online_team import build


class PeriodAndTargetTests(unittest.TestCase):
    def test_study_abroad_target_uses_6715_with_original_month_weights(self):
        config = build.read(build.HERE / 'config/study_abroad_targets.json')
        self.assertEqual(build.study_target(config, {'kind': 'year', 'id': 'FY27'}, 'orders'), 6715)
        self.assertEqual(build.study_target(config, {'kind': 'month', 'id': '2026-09'}, 'orders'), 531)
        self.assertEqual(build.study_target(config, {'kind': 'quarter', 'id': 'Q1'}, 'orders'), 1676)

    def test_fy_q2_and_month_periods_use_real_inclusive_calendar_edges(self):
        periods = {p["id"]: p for p in build.periods(date(2026, 9, 28))}

        self.assertEqual(len(periods), 17)
        self.assertEqual(periods["FY27"]["start_date"], "2026-06-01")
        self.assertEqual(periods["FY27"]["end_date"], "2027-05-31")
        self.assertEqual(periods["FY27"]["prior_start_date"], "2025-06-01")
        self.assertEqual(periods["Q2"]["start_date"], "2026-09-01")
        self.assertEqual(periods["Q2"]["end_date"], "2026-11-30")
        self.assertEqual(periods["Q2"]["through_date"], "2026-09-28")
        self.assertAlmostEqual(periods["Q2"]["time_progress"], 28 / 91)
        self.assertEqual(periods["2026-09"]["end_date"], "2026-09-30")
        self.assertEqual(periods["2026-09"]["prior_through_date"], "2025-09-28")
        self.assertEqual(periods["2026-10"]["status"], "future")
        self.assertIsNone(periods["2026-10"]["through_date"])
        self.assertEqual(periods["2027-05"]["end_date"], "2027-05-31")

    def test_future_window_and_metric_do_not_turn_missing_actual_into_zero(self):
        future = build.window(date(2026, 10, 1), date(2026, 10, 31), date(2026, 9, 28))
        self.assertEqual(future["status"], "future")
        self.assertIsNone(future["through_date"])
        self.assertEqual(future["time_progress"], 0.0)

        result = build.metric(12, 8, 20, 0.25, "条", status="future")
        self.assertIsNone(result["actual"])
        self.assertIsNone(result["prior"])
        self.assertIsNone(result["completion"])
        self.assertIsNone(result["gap"])
        self.assertEqual(result["target"], 20)

    def test_missing_target_stays_null_without_hiding_real_actual(self):
        result = build.metric(7, 5, None, 0.5, "条")
        self.assertEqual(result["actual"], 7)
        self.assertEqual(result["prior"], 5)
        self.assertIsNone(result["target"])
        self.assertIsNone(result["completion"])
        self.assertIsNone(result["gap"])
        self.assertIsNone(result["time_gap"])

    def test_study_target_missing_period_is_not_inferred(self):
        q1 = {"kind": "quarter", "id": "Q1"}
        october = {"kind": "month", "id": "2026-10"}

        study = {
            "study_abroad": {"resource_target": {"annual": 500, "quarters": {"Q1": 120}, "months": {}}},
            "cash": {"total": {"annual": 300, "quarters": {"Q1": 75}}},
        }
        self.assertEqual(build.study_target(study, q1, "orders"), 120)
        self.assertIsNone(build.study_target(study, october, "orders"))
        self.assertIsNone(build.study_target(study, october, "cash"))


class AggregationTests(unittest.TestCase):
    def test_money_and_total_keep_cent_precision(self):
        self.assertEqual(build.money("12.346"), 12.35)
        self.assertEqual(build.money("12.344"), 12.34)
        rows = [
            {"metric": "cash", "value": "0.10"},
            {"metric": "cash", "value": "0.20"},
            {"metric": "orders", "value": 2},
            {"metric": "orders", "value": 3},
        ]
        self.assertEqual(build.total(rows, "cash"), 0.30)
        self.assertEqual(build.total(rows, "orders"), 5)

    def test_channel_rollup_matches_line_totals_and_daily_count(self):
        now = [
            {"metric": "orders", "value": 2, "first_channel": "网络资源", "second_channel": "短视频", "event_date": "2026-09-28"},
            {"metric": "orders", "value": 3, "first_channel": "新媒体", "second_channel": "短视频", "event_date": "2026-09-27"},
            {"metric": "orders", "value": 1, "first_channel": "网络资源", "second_channel": "搜索", "event_date": "2026-09-28"},
            {"metric": "cash", "value": 4.15, "first_channel": "网络资源", "second_channel": "短视频", "event_date": "2026-09-28"},
            {"metric": "cash", "value": 1.20, "first_channel": "新媒体", "second_channel": "搜索", "event_date": "2026-09-27"},
        ]
        prior = [
            {"metric": "orders", "value": 3, "first_channel": "网络资源", "second_channel": "短视频", "event_date": "2025-09-28"},
            {"metric": "orders", "value": 1, "first_channel": "网络资源", "second_channel": "搜索", "event_date": "2025-09-28"},
            {"metric": "cash", "value": 2.40, "first_channel": "网络资源", "second_channel": "短视频", "event_date": "2025-09-28"},
        ]
        period = {"through_date": "2026-09-28"}

        channels = build.channel_rows(now, prior, "training", "2026-09-28", period)
        self.assertEqual(sum(row["orders"] for row in channels), build.total(now, "orders"))
        self.assertEqual(build.money(sum(row["cash"] for row in channels)), build.total(now, "cash"))
        self.assertEqual(sum(row["today_orders"] for row in channels), 3)
        by_name = {row["name"]: row for row in channels}
        self.assertEqual(by_name["短视频"]["orders"], 5)
        self.assertEqual(by_name["短视频"]["first_channels"], ["新媒体", "网络资源"])
        self.assertAlmostEqual(sum(row["share"] for row in channels), 1.0)


class BatchOutputTests(unittest.TestCase):
    def test_output_is_limited_to_workspace_and_cache_identity_is_exact(self):
        with TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            output = workspace / "Output" / "DashboardOnline" / "run_test_001"
            first = build.prepare_output(output, workspace, "run_test_001", "snapshot_a", "2026-09-29")
            self.assertTrue((first / "_build_identity.json").is_file())

            same = build.prepare_output(output, workspace, "run_test_001", "snapshot_a", "2026-09-29")
            self.assertEqual(same, first)
            with self.assertRaisesRegex(ValueError, "another or unknown batch"):
                build.prepare_output(output, workspace, "run_test_002", "snapshot_a", "2026-09-29")
            with self.assertRaisesRegex(ValueError, "another or unknown batch"):
                build.prepare_output(output, workspace, "run_test_001", "snapshot_a", "2026-09-30")
            with self.assertRaisesRegex(ValueError, "under workspace/Output"):
                build.prepare_output(Path(temp) / "outside", workspace, "run_test_001", "snapshot_a", "2026-09-29")

    def test_external_workspace_sources_are_labeled_relative_to_workspace(self):
        with TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            source = workspace / "Input" / "Reference" / "scorecard.json"
            source.parent.mkdir(parents=True)
            source.write_text("{}", encoding="utf-8")
            self.assertEqual(build.source_label(source, workspace), "workspace/Input/Reference/scorecard.json")


if __name__ == "__main__":
    unittest.main()
