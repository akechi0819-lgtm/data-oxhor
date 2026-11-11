from __future__ import annotations

import unittest

from dashboard_product.fallback_mapping import confirmed_training_platform_team
from dashboard_product.management.facts import normalize_facts


PEOPLE = {"teams": []}
ABROAD_PEOPLE = {"people": []}


def _training_row(work_order_id, source_row_number, *, metric="work_orders",
                  group="高中", team_id="offline_market", first="市场活动",
                  second="大学媒体投放", event_date="2026-09-10",
                  acquisition_mode="被动", **extra):
    row = {
        "work_order_id": work_order_id,
        "source_row_number": source_row_number,
        "event_date": event_date,
        "team_id": team_id,
        "business_group": group,
        "first_channel": first,
        "second_channel": second,
        "campaign_name": "原活动",
        "metric": metric,
        "actual_value": 1 if metric == "work_orders" else "125.50",
        "acquisition_mode": acquisition_mode,
    }
    row.update(extra)
    return row


def _order(work_order_id, *, source_team="高中", first="市场活动",
           second="大学媒体投放", source_channel="腾讯广告",
           campaign="原活动"):
    return {
        "work_order_id": work_order_id,
        "source_team": source_team,
        "first_channel": first,
        "second_channel": second,
        "source_channel": source_channel,
        "campaign_name": campaign,
    }


class ConfirmedTrainingPlatformTests(unittest.TestCase):
    def test_shared_rule_accepts_only_reviewed_direct_patterns(self):
        for source in ("腾讯广告", "微信端投放"):
            with self.subTest(source=source):
                team, reason = confirmed_training_platform_team(
                    "市场活动", "大学媒体投放", source, "无关活动名",
                )
                self.assertEqual(team, "online_platform")
                self.assertIn(source, reason)

        self.assertEqual(
            confirmed_training_platform_team(
                "市场活动", "大学媒体投放", "虚拟人", "原活动",
            )[0],
            "online_private",
        )
        self.assertEqual(
            confirmed_training_platform_team(
                "市场活动", "异业渠道", "全媒体平台（其他）",
                "2026.06.21-XGY-国际-抖音咨询-线上渠道推荐",
            )[0],
            "online_platform",
        )

        for first, second, source, campaign in (
            ("大客服推荐-外呼线索", "大学媒体投放", "腾讯广告", "线上投放"),
            ("市场活动", "讲座", "腾讯广告", "线上投放"),
            ("市场活动", "大学媒体投放", "新东方PC官网", "线上投放"),
            ("市场活动", "大学媒体投放", "未知渠道", "线上投放"),
            ("双分", "其他", "抖音来客", "线上投放"),
            ("市场活动", "异业渠道", "全媒体平台（其他）", "其他抖音活动"),
            ("TMK激活-其他", "大学媒体投放", "腾讯广告", "线上投放"),
        ):
            with self.subTest(first=first, second=second, source=source):
                self.assertIsNone(
                    confirmed_training_platform_team(first, second, source, campaign)
                )

    def test_normalize_uses_linked_resource_for_orders_and_cash_and_keeps_cash_conflict(self):
        training = [
            _training_row("direct-1", 100),
            _training_row(
                "direct-1", 101, metric="passive_reported_cash",
                first="自然无法判定", second="自然无法判定",
                cash_channel="学管续费", cash_campaign_name="12",
                work_order_active_type="被动",
            ),
        ]
        orders = [_order("direct-1")]
        cash_overrides = {"overrides": [{
            "work_order_id": "direct-1", "event_date": "2026-09-10",
            "amount": "125.50", "team_id": "online_private", "note": "既有现金确认",
        }]}

        facts, _ = normalize_facts(
            training, orders, PEOPLE, ABROAD_PEOPLE, {}, cash_team_overrides=cash_overrides,
        )

        by_id = {fact["fact_id"]: fact for fact in facts}
        order = by_id["training:order:direct-1"]
        self.assertEqual(order["team_id"], "online_platform")
        self.assertEqual(order["team_before_override"], "offline_market")
        self.assertIn("大学媒体投放", order["team_override_reason"])
        self.assertEqual(order["value"], 1)
        self.assertEqual(order["business_group"], "高中")

        cash = by_id["training:cash:101"]
        self.assertEqual(cash["team_id"], "online_platform")
        self.assertEqual(cash["team_before_override"], "online_private")
        self.assertIn("大学媒体投放", cash["team_override_reason"])
        self.assertEqual((cash["first_channel"], cash["second_channel"]),
                         ("自然无法判定", "自然无法判定"))
        self.assertEqual(cash["value"], 125.5)
        self.assertFalse(cash["team_inferred"])

    def test_reclassification_has_no_date_group_or_active_mode_gate(self):
        specs = (
            ("prep-young", "青少", "留学预备", "2024-06-10", "主动"),
            ("prep-middle", "初中", "留学预备", "2025-06-10", "被动"),
            ("high-school", "高中", "高中", "2026-06-10", "主动"),
            ("university", "大学", "大学", "2027-01-10", "被动"),
        )
        training = []
        orders = []
        for index, (order_id, group, source_team, day, mode) in enumerate(specs, start=1):
            training.append(_training_row(
                order_id, index, group=group, event_date=day, acquisition_mode=mode,
            ))
            orders.append(_order(order_id, source_team=source_team))

        facts, _ = normalize_facts(training, orders, PEOPLE, ABROAD_PEOPLE, {})

        self.assertEqual(len(facts), len(specs))
        self.assertTrue(all(fact["team_id"] == "online_platform" for fact in facts))
        self.assertEqual(
            [fact["business_group"] for fact in facts],
            ["留学预备", "留学预备", "高中", "大学"],
        )
        self.assertEqual([fact["event_date"] for fact in facts],
                         [spec[3] for spec in specs])

    def test_private_source_special_campaign_and_tmk_priority_are_preserved(self):
        training = [
            _training_row("virtual", 201),
            _training_row("special", 202, second="异业渠道"),
            _training_row("tmk", 203, first="TMK激活-平台", second="平台来源"),
        ]
        orders = [
            _order("virtual", source_channel="虚拟人"),
            _order(
                "special", second="异业渠道", source_channel="全媒体平台（其他）",
                campaign="2026.06.21-XGY-国际-抖音咨询-线上渠道推荐",
            ),
            _order("tmk", first="TMK激活-平台", second="平台来源"),
        ]

        facts, _ = normalize_facts(training, orders, PEOPLE, ABROAD_PEOPLE, {})

        by_id = {fact["work_order_id"]: fact for fact in facts}
        self.assertEqual(by_id["virtual"]["team_id"], "online_private")
        self.assertEqual(by_id["special"]["team_id"], "online_platform")
        self.assertEqual(by_id["tmk"]["team_id"], "online_platform")
        self.assertNotIn("team_override_reason", by_id["tmk"])

    def test_personal_qualification_facts_use_the_same_team_routing(self):
        training = [_training_row("personal", 301)]
        orders = [_order("personal")]

        facts, _ = normalize_facts(
            training, orders, PEOPLE, ABROAD_PEOPLE, {}, personal_qualification=True,
        )

        self.assertEqual(facts[0]["team_id"], "online_platform")
        self.assertEqual(facts[0]["team_before_override"], "offline_market")
        self.assertIn("大学媒体投放", facts[0]["team_override_reason"])


if __name__ == "__main__":
    unittest.main()
