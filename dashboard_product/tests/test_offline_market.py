import hashlib
import json
import unittest
from pathlib import Path

from dashboard_product.offline_market_refresh import _aggregate
from dashboard_product.offline_market_render import render_html
from dashboard_product.render_template import render_html as render_dashboard_html


ROOT = Path(__file__).resolve().parents[1]


def _series(value):
    return {"orders": [value] + [0.0] * 11, "passive_orders": [value] + [0.0] * 11}


class OfflineMarketAggregationTest(unittest.TestCase):
    def test_aggregates_l1_l2_schools_and_line_dimensions(self):
        rows = [
            ["2026-06-03", "市场活动", "市场活动", "高校活动", "英国", "英澳条线", "被动", "大学以上", "南开大学", "邓睿", 1.0, "work_orders"],
            ["2026-06-04", "渠道合作", "渠道合作", "个人渠道", "日本", "欧亚条线", "被动", "大学以下", "南开中学", "杨芸聿", 1.0, "work_orders"],
            ["2026-06-05", "新东方学校推荐", "新东方学校推荐", "高中部", None, None, "主动", "大学以下", "信阳高中", "孙伟", 1.0, "work_orders"],
        ]
        result = _aggregate(rows, ["2026-06"] + ["2026-07"] * 11)
        self.assertEqual(result["total"]["orders"][0], 3)
        self.assertEqual(result["total"]["passive_orders"][0], 2)
        self.assertEqual(result["groups"]["市场活动"]["orders"][0], 1)
        self.assertEqual(result["groups"]["新东方学校推荐"]["orders"][0], 1)
        self.assertEqual(result["platforms"]["高校活动"]["series"]["orders"][0], 1)
        self.assertEqual(result["platforms"]["个人渠道"]["first_channels"], ["渠道合作"])
        self.assertEqual(result["countries"]["国家待确认"]["orders"][0], 1)
        self.assertEqual(result["lines"]["欧亚条线"]["countries"]["日本"]["orders"][0], 1)
        self.assertEqual(result["schools"]["大学以上"]["series"]["orders"][0], 1)
        self.assertEqual(result["schools"]["大学以下"]["schools"]["南开中学"]["orders"][0], 1)
        self.assertEqual(result["schools"]["大学以下"]["schools"]["信阳高中"]["orders"][0], 1)
        self.assertEqual(result["people"]["邓睿"]["orders"][0], 1)
        self.assertEqual(result["people"]["杨芸聿"]["orders"][0], 1)
        self.assertEqual(result["people"]["孙伟"]["orders"][0], 1)
        self.assertEqual(result["people"]["吴子玄"]["orders"][0], 0)


class OfflineMarketRenderTest(unittest.TestCase):
    def _artifact(self):
        period = {
            "total": _series(3),
            "groups": {
                "市场活动": _series(1),
                "官方合作高校": _series(0),
                "渠道合作": _series(1),
                "新东方学校推荐": _series(1),
            },
            "people": {"邓睿": _series(2), "孙伟": _series(0), "吴子玄": _series(1)},
            "platforms": {
                "高校活动": {
                    "first_channels": ["市场活动"],
                    "series": _series(1),
                    "groups": {"市场活动": _series(1)},
                }
            },
            "countries": {"英国": _series(2)},
            "lines": {"英澳条线": {"series": _series(2), "countries": {"英国": _series(2)}}},
            "schools": {
                "大学以上": {"series": _series(2), "schools": {"南开大学": _series(2)}},
                "大学以下": {"series": _series(1), "schools": {"南开中学": _series(1)}},
            },
        }
        return {
            "schema_version": "offline_market_artifact.v1",
            "shadow_snapshot_id": "snapshot_offline_market_shadow_test",
            "as_of_date": "2026-09-21",
            "data_through_date": "2026-09-20",
            "months": ["2026-06"] + ["2026-07"] * 11,
            "prior_months": ["2025-06"] + ["2025-07"] * 11,
            "cash": {"status": "not_connected", "label": "现金数据待接入", "actual": None, "target": None},
            "targets": {
                "groups": {
                    "市场活动": {"work_order_target": None},
                    "官方合作高校": {"work_order_target": None},
                    "渠道合作": {"work_order_target": None},
                    "新东方学校推荐": {"work_order_target": None},
                },
                "total": {"work_order_target": None},
                "cash": {"groups": {}, "total": {"annual": None, "quarters": {}}},
            },
            "study_abroad": {"current": period, "prior": period, "scope": {}},
        }

    def test_page_matches_confirmed_layout(self):
        page = render_html(self._artifact())
        self.assertIn("snapshot_offline_market_shadow_test", page)
        self.assertIn("线下团队特供看板", page)
        self.assertIn("留学线下工单数", page)
        self.assertIn("待接入", page)
        self.assertIn("未配置", page)
        self.assertIn("展开国家", page)
        self.assertIn("展开学校", page)
        self.assertIn("大学以上", page)
        self.assertIn("大学以下", page)
        self.assertIn("人员完成", page)
        self.assertIn("孙伟", page)
        self.assertIn("邓睿", page)
        self.assertIn("部门完成只加留学线下团队映射到的人", page)
        self.assertNotIn('id="group"', page)
        self.assertNotIn("<th>一级渠道</th>", page)
        self.assertNotIn("网络资源", page)
        self.assertNotIn("offline_market.html", page)
        self.assertIn("full.html", page)


class OfflineMarketQueryContractTest(unittest.TestCase):
    def test_saved_query_manifest_matches_sql(self):
        query = ROOT / "config" / "offline_market_queries" / "offline_market_orders" / "v1"
        digest = hashlib.sha256((query / "query.sql").read_bytes()).hexdigest()
        manifest = json.loads((query / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["sha256"], digest)
        sql = (query / "query.sql").read_text(encoding="utf-8")
        self.assertIn("source_team IS NULL", sql)
        self.assertIn("mapped_person", sql)
        self.assertIn("WHERE mapped_person IS NOT NULL", sql)
        self.assertIn("孙伟", sql)
        self.assertIn("吴子玄", sql)
        self.assertIn("邓睿", sql)
        self.assertIn("王洪霞", sql)
        self.assertIn("王衡利", sql)
        self.assertIn("杨芸聿", sql)
        self.assertIn("马玥", sql)
        self.assertIn("高书航", sql)
        self.assertIn("资源录入人", sql)
        self.assertIn("数据提供方", sql)
        self.assertIn("不算新", sql)
        self.assertIn("学生学校名称", sql)
        self.assertIn("所在学校", sql)
        self.assertIn("大学以上", sql)
        self.assertIn("大学以下", sql)
        self.assertNotIn("矫正-渠道", sql)
        self.assertNotIn("1449", sql)
        self.assertNotIn("AND resource_active_type = '被动'", sql)


class OfflineMarketMainBoardLinkTest(unittest.TestCase):
    def test_v12_offline_tab_links_to_special_board_without_rewriting_team_id(self):
        src = (ROOT / "render_template.py").read_text(encoding="utf-8")
        self.assertIn('href="offline_market_special.html"', src)
        self.assertIn("team.team_id === 'offline_market'", src)
        self.assertIn("进入留学线下市场特供看板", Path(__file__).resolve().parents[1].joinpath("dashboard_chrome.py").read_text(encoding="utf-8"))
        artifact = {
            "snapshot_id": "snap_test",
            "run_id": "run_test",
            "artifact_id": "art_test",
            "created_at": "2026-09-21T00:00:00+08:00",
            "as_of_date": "2026-09-21",
            "data_through_date": "2026-09-20",
            "dashboard": {
                "months": ["2026-06"] + ["2026-07"] * 11,
                "teams": [
                    {
                        "team_id": "offline_market",
                        "display_name": "线下市场",
                        "groups": [],
                        "people": [],
                        "channels": [],
                        "grades": [],
                    }
                ],
            },
        }
        page = render_dashboard_html(artifact)
        self.assertIn("offline_market_special.html", page)
        self.assertIn('"team_id": "offline_market"', page)


class OfflineMarketTargetConfigTest(unittest.TestCase):
    def test_official_scorecard_annual_targets_are_configured(self):
        cfg = json.loads((ROOT / "config" / "offline_market_targets.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["total"]["work_order_target"], 2620)
        self.assertEqual(cfg["cash"]["total"]["annual"], 660)
        self.assertEqual(cfg["groups"]["市场活动"]["work_order_target"], 1800)
        self.assertEqual(cfg["groups"]["官方合作高校"]["work_order_target"], 470)
        self.assertEqual(cfg["groups"]["渠道合作"]["work_order_target"], 350)
        self.assertIsNone(cfg["groups"]["新东方学校推荐"]["work_order_target"])
