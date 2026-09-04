import json
import tempfile
import unittest
from pathlib import Path

from dashboard_product.refresh import render


class RenderTest(unittest.TestCase):
    def test_renders_projection_and_unconfigured_values(self):
        artifact = {"schema_version":"dashboard_artifact.v1","artifact_id":"dashboard_test","run_id":"run_dashboard_test","snapshot_id":"snapshot_bi_full_20260902_r2","created_at":"2026-09-04T08:00:00+00:00","query_results":[{"query_id":"dashboard_metrics","run_id":"run_dashboard_test","snapshot_id":"snapshot_bi_full_20260902_r2"}],"errors":[],"period_label":"FY27 Q1","dashboard":{"period":{"project_label":"FY27 Q1（自然月项目目标）","performance_label":"2026-09-26 至 2026-10-25"},"teams":[{"team_id":"offline_market","display_name":"线下市场","metrics":{"passive_cash":1200000,"work_orders":230,"completion_rate":.48,"gap":-1300000},"groups":[{"display_name":"留学预备","target":100,"actual":42,"completion_rate":.42}],"people":[{"display_name":"杨玉林","group_name":"小初提能组","employment_status":"在职","target":None,"actual":12,"completion_rate":None}]}]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
            result = render(path)
            page = Path(result["output"]).read_text(encoding="utf-8")
        self.assertIn("FY27 Q1（自然月项目目标）", page)
        self.assertIn("未配置", page)
        self.assertIn("snapshot_bi_full_20260902_r2", page)
        self.assertNotIn("duckdb.connect", page)

    def test_rejects_missing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps({"schema_version":"dashboard_artifact.v1"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact_id"):
                render(path)
