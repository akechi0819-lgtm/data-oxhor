import hashlib
import json
import unittest
from pathlib import Path

from dashboard_product.online_market_refresh import _aggregate
from dashboard_product.online_market_render import render_html


ROOT = Path(__file__).resolve().parents[1]


def _series(value):
    return {"orders": [value] + [0.0] * 11, "passive_orders": [value] + [0.0] * 11}


class OnlineMarketAggregationTest(unittest.TestCase):
    def test_aggregates_root_groups_platforms_and_cleaned_dimensions(self):
        rows = [
            ["2026-06-03", "网络资源", "网络资源", "小红书", "英国", "英澳条线", "被动", 1.0, "work_orders"],
            ["2026-06-04", "新媒体", "新媒体", "大众", "中国香港", "欧亚条线", "被动", 1.0, "work_orders"],
            ["2026-06-05", "网络资源", "网络资源", None, None, None, "主动", 1.0, "work_orders"],
        ]
        result = _aggregate(rows, ["2026-06"] + ["2026-07"] * 11)
        self.assertEqual(result["total"]["orders"][0], 3)
        self.assertEqual(result["total"]["passive_orders"][0], 2)
        self.assertEqual(result["groups"]["网络资源"]["orders"][0], 2)
        self.assertEqual(result["groups"]["新媒体"]["orders"][0], 1)
        self.assertEqual(result["platforms"]["小红书"]["series"]["orders"][0], 1)
        self.assertEqual(result["platforms"]["二级渠道待确认"]["series"]["orders"][0], 1)
        self.assertEqual(result["countries"]["国家待确认"]["orders"][0], 1)
        self.assertEqual(result["lines"]["欧亚条线"]["series"]["orders"][0], 1)
        self.assertEqual(result["lines"]["欧亚条线"]["countries"]["中国香港"]["orders"][0], 1)



    def test_maps_other_platform_to_ssc(self):
        rows = [
            ["2026-06-03", "网络资源", "网络资源", "其他", "英国", "英澳条线", "被动", 1.0, "work_orders"],
        ]
        result = _aggregate(rows, ["2026-06"] + ["2026-07"] * 11)
        self.assertIn("ssc", result["platforms"])
        self.assertNotIn("其他", result["platforms"])
        self.assertEqual(result["platforms"]["ssc"]["series"]["orders"][0], 1)


class OnlineMarketRenderTest(unittest.TestCase):
    def _artifact(self):
        period = {
            "total": _series(3),
            "groups": {"网络资源": _series(2), "新媒体": _series(1)},
            "platforms": {
                "小红书": {
                    "first_channels": ["新媒体"],
                    "series": _series(1),
                    "groups": {"网络资源": _series(0), "新媒体": _series(1)},
                }
            },
            "countries": {"英国": _series(2)},
            "lines": {"英澳条线": {"series": _series(2), "countries": {"英国": _series(2)}}},
        }
        return {
            "schema_version": "online_market_artifact.v1",
            "shadow_snapshot_id": "snapshot_online_market_shadow_test",
            "as_of_date": "2026-09-20",
            "data_through_date": "2026-09-19",
            "months": ["2026-06"] + ["2026-07"] * 11,
            "prior_months": ["2025-06"] + ["2025-07"] * 11,
            "cash": {"status": "not_connected", "label": "现金数据待接入", "actual": None, "target": None},
            "targets": {
                "groups": {"网络资源": {"work_order_target": 5708}, "新媒体": {"work_order_target": 1007}},
                "total": {"work_order_target": 6715},
                "cash": {
                    "groups": {"网络资源": {"annual": 2753.56, "quarters": {"Q1": 688.39}}, "新媒体": {"annual": 239.0, "quarters": {"Q1": 59.75}}},
                    "total": {"annual": 2992.56, "quarters": {"Q1": 748.14}}
                },
            },
            "study_abroad": {"current": period, "prior": period, "scope": {}},
        }

    def test_page_has_shadow_identity_targets_cash_empty_and_no_legacy_training_board(self):
        page = render_html(self._artifact())
        self.assertIn("snapshot_online_market_shadow_test", page)
        self.assertIn("线上团队特供看板", page)
        self.assertNotIn("online_platform.html", page)
        self.assertIn("现金实际", page)
        self.assertIn("5708", page)
        self.assertIn("6715", page)
        self.assertIn("2992.56 万元", page)
        self.assertIn('"annual": 2753.56', page)
        self.assertIn('"annual": 2992.56', page)
        self.assertIn("网络资源计入被动+主动", page)
        self.assertIn("线上工单数", page)
        self.assertNotIn("其中被动", page)
        self.assertIn("展开国家", page)
        self.assertNotIn('id="group"', page)
        self.assertNotIn("<th>一级渠道</th>", page)

    def test_render_aliases_other_platform_label_to_ssc(self):
        artifact = self._artifact()
        artifact["study_abroad"]["current"]["platforms"]["其他"] = {
            "first_channels": ["网络资源"],
            "series": _series(2),
            "groups": {"网络资源": _series(2), "新媒体": _series(0)},
        }
        page = render_html(artifact)
        self.assertIn("aliases = {'其他':'ssc'}", page)
        self.assertIn('"其他"', page)  # legacy artifact key still present



    def test_training_src_adds_tabs_and_iframe_without_legacy_booklet(self):
        page = render_html(self._artifact(), training_src="online_market_training.html")
        self.assertIn("online_market_training.html", page)
        self.assertIn("语培进度", page)
        self.assertIn("留学线上", page)
        self.assertIn('id="training-view"', page)
        self.assertIn('src="online_market_training.html"', page)
        self.assertNotIn("online_platform.html", page)

    def test_without_training_src_omits_training_tab(self):
        page = render_html(self._artifact())
        self.assertNotIn("语培进度", page)
        self.assertNotIn("online_market_training.html", page)
        self.assertNotIn("online_platform.html", page)


class LockOnlinePlatformRenderTest(unittest.TestCase):
    def test_lock_team_id_keeps_only_online_platform(self):
        from dashboard_product.render_template import render_html as render_dashboard_html

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
                    },
                    {
                        "team_id": "online_platform",
                        "display_name": "线上平台",
                        "groups": [
                            {
                                "group_id": "g1",
                                "display_name": "留学预备",
                                "monthly_actuals": {"cash": [0] * 12, "orders": [0] * 12},
                                "prior_monthly_actuals": {"cash": [0] * 12, "orders": [0] * 12},
                                "targets": {"cash": 0, "orders": 0},
                                "channels": [],
                                "grades": [],
                            }
                        ],
                        "people": [],
                        "channels": [],
                        "grades": [],
                    },
                    {
                        "team_id": "market_total",
                        "display_name": "市场总计",
                        "groups": [],
                        "people": [],
                        "channels": [],
                        "grades": [],
                    },
                ],
            },
        }
        page = render_dashboard_html(artifact, lock_team_id="online_platform")
        self.assertIn("语培完成进度（线上平台 · V12同源）", page)
        self.assertIn("同源主看板 artifact，非分册", page)
        self.assertIn("online_market_special.html", page)
        self.assertIn('"team_id": "online_platform"', page)
        self.assertNotIn('"team_id": "offline_market"', page)
        self.assertNotIn('"team_id": "market_total"', page)

    def test_lock_team_id_missing_raises(self):
        from dashboard_product.render_template import render_html as render_dashboard_html

        artifact = {
            "snapshot_id": "snap_test",
            "run_id": "run_test",
            "artifact_id": "art_test",
            "created_at": "2026-09-21T00:00:00+08:00",
            "as_of_date": "2026-09-21",
            "data_through_date": "2026-09-20",
            "dashboard": {"months": ["2026-06"] * 12, "teams": []},
        }
        with self.assertRaises(ValueError):
            render_dashboard_html(artifact, lock_team_id="online_platform")


class OnlineMarketQueryContractTest(unittest.TestCase):
    def test_saved_query_manifest_matches_sql(self):
        query = ROOT / "config" / "online_market_queries" / "online_market_orders" / "v1"
        digest = hashlib.sha256((query / "query.sql").read_bytes()).hexdigest()
        manifest = json.loads((query / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["sha256"], digest)
        sql = (query / "query.sql").read_text(encoding="utf-8")
        self.assertIn("source_team IS NULL", sql)
        self.assertIn("source_root IN ('网络资源', '新媒体')", sql)
        self.assertIn("意向国家", sql)
        self.assertIn("矫正条线", sql)
        self.assertIn("留学渠道清洗状态", sql)
        self.assertIn("(source_root = '网络资源' AND resource_active_type IN ('被动', '主动'))", sql)
        self.assertIn("(source_root = '新媒体' AND resource_active_type = '被动')", sql)
        self.assertNotIn("WHERE NULLIF(TRIM(资源主被动), '') = '被动'", sql)
