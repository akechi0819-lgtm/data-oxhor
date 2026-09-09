import json
import tempfile
import unittest
from pathlib import Path

from dashboard_product.refresh import project, render


class RenderTest(unittest.TestCase):
    def test_projects_people_targets_and_channel_drills(self):
        from dashboard_product.refresh import read
        root = Path(__file__).resolve().parents[1]
        rows = [
            ["2026-09-03", "offline_market", "高中", "TMK", "校园", "杨新宇活动", None, "学校", "高一", "work_orders", 2],
            ["2026-09-03", "offline_market", "高中", "TMK", "校园", "杨新宇活动", None, "学校", "高一", "passive_reported_cash", 26000],
        ]
        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(root / "config/people.json"))
        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")
        person = next(item for item in team["people"] if item["display_name"] == "杨新宇")
        self.assertEqual(person["business_group"], "高中")
        self.assertEqual(person["monthly_targets"]["2026-09"]["orders"], 60)
        self.assertEqual(person["monthly_drilldowns"]["2026-09"]["orders"]["TMK||校园"], 2)
        self.assertEqual(person["monthly_drilldowns"]["2026-09"]["cash"]["TMK||校园"], 26000)
        self.assertFalse(any(item["display_name"] == "空白占位 1" for item in team["people"]))

    def test_person_attribution_uses_entry_person_when_campaign_name_misses_roster(self):
        from dashboard_product.refresh import read
        root = Path(__file__).resolve().parents[1]
        rows = [
            ["2026-09-03", "offline_market", "大学", "TMK", "校园", "天财豆蔻学姐号微信推广-曹恒为玮-线上雅思行地推", "曹恒玮", "某大学", "大一", "work_orders", 1],
        ]
        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(root / "config/people.json"))
        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")
        cao = next(item for item in team["people"] if item["display_name"] == "曹恒玮")
        self.assertEqual(cao["orders_actual"], 1)

    def test_person_attribution_uses_entry_person_when_campaign_is_empty(self):
        from dashboard_product.refresh import read
        root = Path(__file__).resolve().parents[1]
        rows = [
            ["2026-09-03", "offline_market", "大学", "TMK", "校园", None, "曹恒玮", "某大学", "大一", "work_orders", 1],
        ]
        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(root / "config/people.json"))
        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")
        cao = next(item for item in team["people"] if item["display_name"] == "曹恒玮")
        self.assertEqual(cao["orders_actual"], 1)

    def test_person_attribution_filters_business_group_then_uses_entry_person_for_school_agent(self):
        from dashboard_product.refresh import read
        root = Path(__file__).resolve().parents[1]
        rows = [
            ["2026-09-03", "offline_market", "高中", "TMK", "校园", "马澳高中活动", None, "学校", "高一", "work_orders", 5],
            ["2026-09-03", "offline_market", "青少", "TMK", "校园", "校代系统资源活动", "马澳", "学校", "初三", "work_orders", 3],
            ["2026-09-03", "offline_market", "青少", "TMK", "校园", "校代系统资源活动", "马澳", "学校", "初三", "passive_reported_cash", 39000],
        ]
        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(root / "config/people.json"))
        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")
        ma_ao = next(item for item in team["people"] if item["display_name"] == "马澳")
        self.assertEqual(ma_ao["orders_actual"], 3)
        self.assertEqual(ma_ao["cash_actual"], 39000)
        self.assertEqual(ma_ao["monthly_drilldowns"]["2026-09"]["orders"]["TMK||校园"], 3)

    def test_cash_channel_contract_uses_work_order_left_join(self):
        query = (Path(__file__).resolve().parents[1] / "sql/dashboard_actuals.sql").read_text(encoding="utf-8")
        self.assertIn("LEFT JOIN orders_dim o", query)
        self.assertIn("资源描述", query)
        self.assertIn("市场人员", query)
        self.assertIn("COALESCE(o.first_channel, '暂无归属') AS first_channel", query)
        self.assertIn("COALESCE(o.second_channel, '暂无归属') AS second_channel", query)
        self.assertIn("顾问归属", query)
        self.assertIn("年级校正", query)
        self.assertIn("c.cash_business_group AS business_group", query)
        self.assertIn("WHEN TRIM(团队) IN ('初中','初中国际学科') THEN '初中'", query)
        self.assertNotIn("COALESCE(o.business_group, c.cash_business_group)", query)

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
        yoy = {
            "display_name": "青少",
            "monthly_actuals": {"cash": [42] + [0] * 11, "orders": [12] + [0] * 11},
            "prior_monthly_actuals": {"cash": [40] + [0] * 11, "orders": [10] + [0] * 11},
        }
        artifact = {"schema_version":"dashboard_artifact.v1","artifact_id":"dashboard_test","run_id":"run_dashboard_test","snapshot_id":"snapshot_bi_full_20260902_r2","as_of_date":"2026-09-05","data_through_date":"2026-09-04","created_at":"2026-09-04T08:00:00+00:00","query_results":[],"errors":[],"dashboard":{"months":["2026-06"] * 12,"prior_months":["2025-06"] * 12,"drilldowns":{"current":{"cash":{"channel":{"2026-06|offline_market|留学预备|转介绍|老客转介绍":3},"school_grade":{}},"orders":{"channel":{},"school_grade":{}}},"prior":{"cash":{"channel":{"2025-06|offline_market|留学预备|转介绍|老客转介绍":4},"school_grade":{}},"orders":{"channel":{},"school_grade":{}}}},"teams":[{"team_id":"offline_market","display_name":"线下市场","cash_target":100,"orders_target":None,"groups":[group],"yoy_groups":[yoy],"people":[{"display_name":"王昊","group_name":"青少组","business_group":"留学预备","monthly_targets":{"2026-06":{"orders":10,"cash":1000}},"monthly_actuals":{"cash":[42] + [0] * 11,"orders":[12] + [0] * 11},"monthly_drilldowns":{"2026-06":{"cash":{"转介绍||老客转介绍":42},"orders":{"转介绍||老客转介绍":12}}}}]}]}}
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
        self.assertIn("业务团队", page)
        self.assertIn("工单渠道", page)
        self.assertIn("现金渠道", page)
        self.assertIn("渠道同比和年级同比按青少、初中、高中、大学", page)
        self.assertNotIn("<th>状态</th>", page)
        self.assertIn("<em>目标</em>", page)
        self.assertIn("<em>完成</em>", page)
        self.assertIn("当期", page)
        self.assertIn("同期", page)
        self.assertNotIn("工单渠道结构", page)
        self.assertIn("未配置", page)
        self.assertIn("snapshot_bi_full_20260902_r2", page)
        self.assertNotIn("duckdb.connect", page)


    def test_youth_and_middle_school_roll_up_to_liuxue_and_keep_four_yoy_groups(self):
        from dashboard_product.refresh import read
        root = Path(__file__).resolve().parents[1]
        rows = [
            ["2026-09-03", "offline_market", "青少", "TMK", "校园", "王昊活动", None, "学校", "一年级", "passive_reported_cash", 100],
            ["2026-09-03", "offline_market", "初中", "TMK", "校园", "初中活动", None, "学校", "七年级", "passive_reported_cash", 40],
            ["2026-09-03", "offline_market", "高中", "TMK", "校园", "杨新宇活动", None, "学校", "高一", "passive_reported_cash", 20],
        ]
        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(root / "config/people.json"))
        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")
        groups = {group["display_name"]: group for group in team["groups"]}
        self.assertEqual(groups["留学预备"]["monthly_actuals"]["cash"][3], 140)
        self.assertEqual(groups["高中"]["monthly_actuals"]["cash"][3], 20)
        yoy = {group["display_name"]: group for group in team["yoy_groups"]}
        self.assertEqual(list(yoy), ["青少", "初中", "高中", "大学"])
        self.assertEqual(yoy["青少"]["monthly_actuals"]["cash"][3], 100)
        self.assertEqual(yoy["初中"]["monthly_actuals"]["cash"][3], 40)
        self.assertIn("2026-09|offline_market|青少|TMK|校园", result["drilldowns"]["current"]["cash"]["channel"])
        self.assertNotIn("2026-09|offline_market|留学预备|TMK|校园", result["drilldowns"]["current"]["cash"]["channel"])

    def test_render_template_does_not_fill_empty_yoy_groups(self):
        src = (Path(__file__).resolve().parents[1] / "render_template.py").read_text(encoding="utf-8")
        self.assertIn("function yoyGroups(team) {", src)
        self.assertIn("return team.yoy_groups || [];", src)
        self.assertNotIn("Array(12).fill(0)", src)
        self.assertNotIn("if (team.yoy_groups && team.yoy_groups.length)", src)

    def test_rejects_missing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps({"schema_version":"dashboard_artifact.v1"}), encoding="utf-8")
            with self.assertRaisesRegex(KeyError, "dashboard"):
                render(path)
