from __future__ import annotations

import unittest
from datetime import date

from dashboard_product.management.aggregate import aggregate
from tests.legacy_dashboard.training_facts import _safe_country, normalize_facts


def configs():
    people = {
        "teams": [{"team_id": "offline_market", "groups": [{"display_name": "青少组", "members": [
            {"display_name": "王昊", "status": "active"},
        ]}]}]
    }
    abroad_people = {"people": [{"display_name": name, "business_group": "大学"} for name in (
        "孙伟", "吴子玄", "邓睿", "王洪霞", "王衡利", "杨芸聿", "马玥", "高书航",
    )]}
    return people, abroad_people


class NormalizeFactsTests(unittest.TestCase):
    def test_keeps_confirmed_training_and_unknown_group_without_counting_study_as_training(self):
        people, abroad_people = configs()
        training = [
            {"source_row_number": 2, "work_order_id": "T1", "event_date": "2026-09-01",
             "team_id": "offline_market", "business_group": "青少", "first_channel": "市场活动",
             "second_channel": "讲座", "campaign_name": "王昊活动", "metric": "work_orders", "actual_value": 1},
            {"source_row_number": 3, "work_order_id": "T2", "event_date": "2026-09-02",
             "team_id": None, "business_group": "业务组暂无法拆分", "first_channel": None,
             "second_channel": None, "campaign_name": None, "metric": "work_orders", "actual_value": 1},
            {"source_row_number": 4, "work_order_id": "A1", "event_date": "2026-09-03",
             "team_id": "online_platform", "business_group": "业务组暂无法拆分", "metric": "work_orders", "actual_value": 1},
            {"source_row_number": 5, "work_order_id": "U1", "event_date": "2026-09-04",
             "team_id": "online_platform", "business_group": "大学", "metric": "work_orders", "actual_value": 1},
        ]
        orders = [
            {"work_order_id": "T1", "source_team": "高中", "source_row_number": 2,
             "campaign_name": "王昊活动", "resource_entry_person": "王昊"},
            {"work_order_id": "T2", "source_team": "高中", "source_row_number": 3},
            {"work_order_id": "A1", "source_team": "", "adviser": "确认留学顾问",
             "source_path": "网络资源-搜索", "resource_active_type": "被动", "source_row_number": 4},
            {"work_order_id": "U1", "source_team": "", "adviser": "名单外顾问", "source_row_number": 5},
        ]
        facts, diagnostics = normalize_facts(
            training, orders, people, abroad_people,
            {"确认留学顾问": "留学"},
        )

        by_id = {fact["work_order_id"]: fact for fact in facts}
        self.assertEqual(by_id["T1"]["business_group"], "留学预备")
        self.assertIsNone(by_id["T2"]["business_group"])
        self.assertNotIn("A1", by_id)
        self.assertNotIn("U1", by_id)
        self.assertTrue(all(fact["business_line"] == "training" for fact in facts))
        self.assertEqual(by_id["T1"]["owners"], ["王昊"])
        self.assertEqual(diagnostics["training_study_order_excluded"], 1)
        self.assertEqual(diagnostics["training_unconfirmed_blank_team_excluded"], 1)

    def test_personal_history_keeps_confirmed_prep_blank_team_independently(self):
        people, abroad_people = configs()
        training = [{"source_row_number": 1, "work_order_id": "blank-prep",
            "event_date": "2025-07-01", "business_group": "初中",
            "metric": "work_orders", "actual_value": 1}]
        orders = [{"work_order_id": "blank-prep", "source_team": "",
                   "adviser": "预备顾问", "source_row_number": 1}]
        market, _ = normalize_facts(training, orders, people, abroad_people,
                                    {"预备顾问": "留学预备"})
        personal, _ = normalize_facts(training, orders, people, abroad_people,
                                    {"预备顾问": "留学预备"}, personal_qualification=True)
        self.assertEqual(market, [])
        self.assertEqual([f['work_order_id'] for f in personal], ['blank-prep'])
        unknown, _ = normalize_facts(training, orders, people, abroad_people,
                                    {}, personal_qualification=True)
        self.assertEqual(unknown, [])

    def test_guanyuan_scope_excludes_blank_team_even_with_confirmed_prep_adviser(self):
        people, abroad_people = configs()
        training = [{"source_row_number": 1, "work_order_id": "blank-prep",
            "event_date": "2026-09-01", "business_group": "初中",
            "metric": "work_orders", "actual_value": 1}]
        orders = [{"work_order_id": "blank-prep", "source_team": "",
            "adviser": "预备顾问"}]
        facts, _ = normalize_facts(training, orders, people, abroad_people,
                                   {"预备顾问": "留学预备"})
        self.assertEqual(facts, [])

    def test_bi_study_abroad_order_rows_never_create_management_abroad_facts(self):
        people, abroad_people = configs()
        orders = [{
            "work_order_id": "BI-study-1", "source_team": "留学", "adviser": "确认留学顾问",
            "source_row_number": 101, "event_date": "2026-09-10",
        }]

        facts, diagnostics = normalize_facts(
            [], orders, people, abroad_people, {"确认留学顾问": "留学"},
        )

        self.assertEqual([], facts)
        self.assertEqual(0, diagnostics["training_facts"])
        self.assertTrue(all(fact["business_line"] != "abroad" for fact in facts))

    def test_deleted_and_recalled_orders_count_for_teams_but_not_personal_eligibility(self):
        people, abroad_people = configs()
        order_statuses = {"T-deleted": "删除", "T-recalled": "回收", "T-live": "死单"}
        training = []
        orders = []
        for index, (work_order_id, status) in enumerate(order_statuses.items(), start=1):
            training.append({
                "source_row_number": index, "work_order_id": work_order_id,
                "event_date": "2026-09-10", "team_id": "offline_market",
                "business_group": "高中", "first_channel": "市场活动",
                "second_channel": "校区市场活动", "campaign_name": "活动A",
                "metric": "work_orders", "actual_value": 1,
                "order_status": status,
                "source_record": f'{{"ID":"{work_order_id}","工单状态":"{status}"}}',
            })
            orders.append({
                "work_order_id": work_order_id, "source_team": "高中",
                "source_row_number": index, "order_status": status,
                "campaign_name": "活动A",
            })
        training.append({
            "source_row_number": 20, "work_order_id": "T-deleted",
            "event_date": "2026-09-11", "team_id": "offline_market",
            "business_group": "高中", "first_channel": "市场活动",
            "second_channel": "校区市场活动", "campaign_name": "活动A",
            "metric": "passive_reported_cash", "actual_value": "500.00",
            "cash_channel": "市场资源", "cash_campaign_name": "活动A",
            "order_status": "删除", "cash_source_record": '{"工单ID":"T-deleted"}',
        })

        facts, _ = normalize_facts(
            training, orders, people, abroad_people, {"确认留学顾问": "留学"},
        )

        by_id = {fact["fact_id"]: fact for fact in facts}
        self.assertFalse(by_id["training:order:T-deleted"]["counts_toward_completion"])
        self.assertEqual(by_id["training:order:T-deleted"]["exclusion_reason"], "order_status_deleted")
        self.assertEqual(by_id["training:order:T-deleted"]["source_record"]["工单状态"], "删除")
        self.assertFalse(by_id["training:order:T-recalled"]["counts_toward_completion"])
        self.assertEqual(by_id["training:order:T-recalled"]["exclusion_reason"], "order_status_recalled")
        cash = by_id["training:cash:20"]
        self.assertTrue(cash["counts_toward_completion"])
        self.assertIsNone(cash["exclusion_reason"])
        self.assertEqual(cash["order_status"], "删除")
        self.assertEqual(cash["source_record"], {"工单ID": "T-deleted"})

        result = aggregate(
            facts, people, abroad_people, {}, {}, {}, date(2026, 9, 28),
            abroad_source={"start_date": "2026-06-01", "through_date": "2026-09-27"},
        )
        september = next(period for period in result["periods"] if period["id"] == "2026-09")
        total = next(team for team in september["teams"] if team["id"] == "total")
        self.assertEqual(total["lines"]["training"]["orders"]["actual"], 3)
        self.assertEqual(total["lines"]["training"]["cash"]["actual"], 500)

    def test_cash_facts_use_source_rows_as_unique_ids_and_normalize_placeholder_campaigns(self):
        people, abroad_people = configs()
        training = [{
            "source_row_number": 77, "work_order_id": None, "event_date": "2026-09-11",
            "team_id": None, "business_group": "高中", "metric": "passive_reported_cash",
            "actual_value": "125.50", "first_channel": "暂无归属", "second_channel": "暂无归属",
            "cash_channel": "市场资源", "cash_campaign_name": "None", "campaign_name": "否",
            "work_order_active_type": None,
        }]

        facts, _ = normalize_facts(training, [], people, abroad_people, {})

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["fact_id"], "training:cash:77")
        self.assertEqual(facts[0]["value"], 125.5)
        self.assertIsNone(facts[0]["campaign_name"])
        self.assertEqual(facts[0]["owners"], [])
        self.assertIsInstance(facts[0]["team_inferred"], bool)

    def test_virtual_owners_union_activity_entry_and_resource_text_without_changing_owners(self):
        people, abroad_people = configs()
        people["teams"].append({
            "team_id": "online_private",
            "groups": [{"display_name": "虚拟组", "members": [
                {"display_name": name, "status": status}
                for name, status in (("虚拟甲", "active"), ("虚拟乙", "active"),
                                     ("虚拟丙", "active"), ("离职虚拟", "departed"))
            ]}],
        })
        training = [
            {
                "source_row_number": 41, "work_order_id": "T-virtual",
                "event_date": "2026-09-10", "team_id": "offline_market",
                "business_group": "高中", "first_channel": "市场活动",
                "second_channel": "线下校代", "campaign_name": "培训市场活动（虚拟甲）和虚拟乙",
                "metric": "work_orders", "actual_value": 1,
                "entry_person": "普通录入人",
            },
            {
                "source_row_number": 42, "work_order_id": "C-virtual",
                "event_date": "2026-09-11", "team_id": "online_platform",
                "business_group": "高中", "first_channel": "网络资源",
                "second_channel": "搜索", "metric": "passive_reported_cash",
                "actual_value": "800.00", "cash_channel": "市场资源",
                "cash_campaign_name": "现金市场活动（虚拟乙）",
                "work_order_campaign_name": "关联工单活动-虚拟甲",
                "campaign_name": "关联工单活动-虚拟甲",
                "entry_person": "普通录入人",
                "resource_entry_person": "原资源录入人：虚拟丙",
                "resource_description": "旧现金活动说明（虚拟乙），离职虚拟",
            },
        ]
        orders = [
            {
                "work_order_id": "T-virtual", "source_team": "高中",
                "campaign_name": "原工单活动-虚拟丙",
                "resource_entry_person": "虚拟甲",
                "resource_description": "旧活动说明：虚拟乙",
            },
            {
                "work_order_id": "C-virtual", "source_team": "高中",
                "campaign_name": "关联工单活动-虚拟甲",
                "resource_entry_person": "原工单录入人-虚拟丙",
                "resource_description": "旧工单描述（虚拟乙）",
            },
        ]

        facts, _ = normalize_facts(
            training, orders, people, abroad_people,
            {"确认留学顾问": "留学"},
        )
        by_id = {fact["fact_id"]: fact for fact in facts}

        work_order = by_id["training:order:T-virtual"]
        self.assertEqual(work_order["virtual_owners"], ["虚拟甲", "虚拟乙", "虚拟丙"])
        self.assertEqual(work_order["owners"], ["虚拟丙"])
        self.assertEqual(work_order["team_id"], "offline_market")
        self.assertEqual(work_order["business_group"], "高中")

        cash = by_id["training:cash:42"]
        self.assertEqual(cash["virtual_owners"], ["虚拟甲", "虚拟乙", "虚拟丙"])
        self.assertEqual(cash["owners"], ["虚拟甲"])
        self.assertEqual(cash["team_id"], "online_platform")
        self.assertEqual(cash["business_group"], "高中")

        self.assertTrue(all(fact["business_line"] == "training" for fact in facts))

    def test_confirmed_cash_team_overrides_match_work_order_date_and_amount_only(self):
        people, abroad_people = configs()
        training = []
        cash_specs = [
            (701, "35385878", "2026-09-28", "21200.00"),
            (702, "34886362", "2026-09-26", "53600.00"),
            (703, "34886362", "2026-09-26", "40800.00"),
            (704, "35385878", "2026-09-27", "21200.00"),
            (705, "34886362", "2026-09-26", "50000.00"),
        ]
        for source_row, work_order_id, event_date, amount in cash_specs:
            training.append({
                "source_row_number": source_row, "work_order_id": work_order_id,
                "event_date": event_date, "team_id": None, "business_group": "高中",
                "metric": "passive_reported_cash", "actual_value": amount,
                "cash_channel": "其他", "cash_campaign_name": "否",
                "campaign_name": "否", "first_channel": None, "second_channel": None,
            })
        for source_row, work_order_id in ((706, "35385878"), (707, "34886362")):
            training.append({
                "source_row_number": source_row, "work_order_id": work_order_id,
                "event_date": "2026-09-28", "team_id": "offline_market",
                "business_group": "高中", "metric": "work_orders", "actual_value": 1,
            })
        orders = [
            {"work_order_id": work_order_id, "source_team": "高中"}
            for work_order_id in ("35385878", "34886362")
        ]
        overrides = {
            "overrides": [
                {"work_order_id": "35385878", "event_date": "2026-09-28",
                 "amount": "21200.00", "team_id": "online_platform", "note": "用户确认"},
                {"work_order_id": "34886362", "event_date": "2026-09-26",
                 "amount": "53600.00", "team_id": "online_platform", "note": "用户确认"},
                {"work_order_id": "34886362", "event_date": "2026-09-26",
                 "amount": "40800.00", "team_id": "online_platform", "note": "用户确认"},
            ]
        }

        facts, _ = normalize_facts(
            training, orders, people, abroad_people, {},
            cash_team_overrides=overrides,
        )

        by_id = {fact["fact_id"]: fact for fact in facts}
        for source_row, expected_amount in ((701, 21200.0), (702, 53600.0), (703, 40800.0)):
            fact = by_id[f"training:cash:{source_row}"]
            self.assertEqual(fact["team_id"], "online_platform")
            self.assertEqual(fact["value"], expected_amount)
            self.assertEqual(fact["team_override_reason"], "用户确认")
            self.assertFalse(fact["team_inferred"])
            self.assertEqual(fact["owners"], [])
        for source_row in (704, 705):
            fact = by_id[f"training:cash:{source_row}"]
            self.assertNotIn("team_override_reason", fact)
        for source_row in (706, 707):
            fact = by_id[f"training:order:{'35385878' if source_row == 706 else '34886362'}"]
            self.assertEqual(fact["team_id"], "offline_market")
            self.assertNotIn("team_override_reason", fact)

    def test_safe_country_rejects_description_tail_and_contact_text(self):
        self.assertEqual((None, True), _safe_country("其他在读年级：未知推送方式：邮件 contact@example.com"))
        self.assertEqual(("日本", False), _safe_country("日本/美国"))


if __name__ == "__main__":
    unittest.main()
