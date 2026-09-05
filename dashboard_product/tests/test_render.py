import json
import tempfile
import unittest
from pathlib import Path

from dashboard_product.refresh import render


class RenderTest(unittest.TestCase):
    def test_renders_projection_and_unconfigured_values(self):
        group = {
            "display_name": "留学预备",
            "quarter_targets": {"Q1": {"cash": 100, "orders": None}},
            "annual_targets": {"cash": 100, "orders": None},
            "monthly_actuals": {"cash": [42] + [0] * 11, "orders": [12] + [0] * 11},
            "prior_monthly_actuals": {"cash": [40] + [0] * 11, "orders": [10] + [0] * 11},
            "cash_actual": 42,
            "orders_actual": 12,
        }
        artifact = {"schema_version":"dashboard_artifact.v1","artifact_id":"dashboard_test","run_id":"run_dashboard_test","snapshot_id":"snapshot_bi_full_20260902_r2","as_of_date":"2026-09-05","data_through_date":"2026-09-04","created_at":"2026-09-04T08:00:00+00:00","query_results":[],"errors":[],"dashboard":{"months":["2026-06"] * 12,"prior_months":["2025-06"] * 12,"drilldowns":{"current":{"cash":{"channel":{"2026-06|offline_market|留学预备|转介绍|老客转介绍":3},"school_grade":{}},"orders":{"channel":{},"school_grade":{}}},"prior":{"cash":{"channel":{"2025-06|offline_market|留学预备|转介绍|老客转介绍":4},"school_grade":{}},"orders":{"channel":{},"school_grade":{}}}},"teams":[{"team_id":"offline_market","display_name":"线下市场","cash_target":100,"orders_target":None,"groups":[group],"people":[]}]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
            result = render(path)
            page = Path(result["output"]).read_text(encoding="utf-8")
        self.assertIn("FY27 财年", page)
        self.assertIn("Cyber Shackles", page)
        self.assertIn("数据截至 2026-09-04", page)
        self.assertIn("展开下钻", page)
        self.assertIn("drilldowns", page)
        self.assertIn("二级渠道", page)
        self.assertIn("people-panel", page)
        self.assertIn("metric-details", page)
        self.assertIn("<em>目标</em>", page)
        self.assertIn("<em>完成</em>", page)
        self.assertIn("当期", page)
        self.assertIn("同期", page)
        self.assertNotIn("工单渠道结构", page)
        self.assertIn("未配置", page)
        self.assertIn("snapshot_bi_full_20260902_r2", page)
        self.assertNotIn("duckdb.connect", page)

    def test_rejects_missing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps({"schema_version":"dashboard_artifact.v1"}), encoding="utf-8")
            with self.assertRaisesRegex(KeyError, "dashboard"):
                render(path)
