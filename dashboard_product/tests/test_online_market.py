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
            ["2026-06-04", "新媒体", "新媒体", "大众", "中国香港", "欧亚条线", "主动", 1.0, "work_orders"],
            ["2026-06-05", "网络资源", "网络资源", None, None, None, "被动", 1.0, "work_orders"],
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
        self.assertIn("2753.56 万元", page)
        self.assertIn('"annual": 2992.56', page)
        self.assertIn("资源主被动=被动", page)
        self.assertIn("被动线上工单数", page)
        self.assertNotIn("其中被动", page)
        self.assertIn("展开国家", page)


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
        self.assertIn("TRIM(资源主被动), '') = '被动'", sql)
