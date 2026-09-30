from __future__ import annotations

import unittest

from data_acquisition.jobs.work_order_cleaning import WorkOrderReference
from dashboard_product.management.facts import normalize_facts


def reference():
    return WorkOrderReference(
        path_to_first_channel={"网络资源-搜索": "网络资源"},
        path_channel_to_corrected_channel={("网络资源-搜索", "raw"): "搜索"},
        country_to_line={"日本": "亚洲条线"},
        path_channel_counts={},
        country_line_counts={},
    )


def configs():
    people = {
        "teams": [{"team_id": "offline_market", "groups": [{"display_name": "青少组", "members": [
            {"display_name": "王昊", "status": "active"},
        ]}]}]
    }
    abroad_people = {"people": [{"display_name": name} for name in (
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
            {"确认留学顾问": "留学"}, reference(),
        )

        by_id = {fact["work_order_id"]: fact for fact in facts}
        self.assertEqual(by_id["T1"]["business_group"], "留学预备")
        self.assertIsNone(by_id["T2"]["business_group"])
        self.assertEqual(by_id["A1"]["business_line"], "abroad")
        self.assertNotIn("U1", by_id)
        self.assertEqual(by_id["T1"]["owners"], ["王昊"])
        self.assertEqual(diagnostics["training_study_order_excluded"], 1)
        self.assertEqual(diagnostics["training_unconfirmed_blank_team_excluded"], 1)

    def test_eight_person_claim_sets_department_without_changing_source_mode(self):
        people, abroad_people = configs()
        orders = [{
            "work_order_id": "A1", "source_row_number": 10, "source_team": "",
            "adviser": "确认留学顾问", "event_date": "2026-09-10",
            "source_path": "网络资源-搜索", "resource_active_type": "被动",
            "main_active_type": "被动", "source_channel": "raw",
            "first_channel": "", "second_channel": "", "campaign_name": "否",
            "resource_entry_person": "孙伟", "resource_description": "",
            "intended_country_source": "日本", "online_offline": "线上",
        }]

        facts, _ = normalize_facts(
            [], orders, people, abroad_people,
            {"确认留学顾问": "留学"}, reference(),
        )

        self.assertEqual(len(facts), 1)
        fact = facts[0]
        self.assertEqual(fact["team_id"], "offline_market")
        self.assertEqual(fact["business_group"], "大学")
        self.assertEqual(fact["acquisition_mode"], "online")
        self.assertEqual(fact["country"], "日本")
        self.assertEqual(fact["line"], "亚洲条线")
        self.assertIn("孙伟", fact["owners"])
        self.assertIsNone(fact["campaign_name"])

    def test_cash_facts_use_source_rows_as_unique_ids_and_normalize_placeholder_campaigns(self):
        people, abroad_people = configs()
        training = [{
            "source_row_number": 77, "work_order_id": None, "event_date": "2026-09-11",
            "team_id": None, "business_group": "高中", "metric": "passive_reported_cash",
            "actual_value": "125.50", "first_channel": "暂无归属", "second_channel": "暂无归属",
            "cash_channel": "市场资源", "cash_campaign_name": "None", "campaign_name": "否",
            "work_order_active_type": None,
        }]

        facts, _ = normalize_facts(training, [], people, abroad_people, {}, reference())

        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["fact_id"], "training:cash:77")
        self.assertEqual(facts[0]["value"], 125.5)
        self.assertIsNone(facts[0]["campaign_name"])
        self.assertEqual(facts[0]["owners"], [])
        self.assertIsInstance(facts[0]["team_inferred"], bool)

    def test_country_tail_is_cut_and_leaked_contact_text_is_rejected(self):
        people, abroad_people = configs()
        orders = [
            {
                "work_order_id": "A1", "source_row_number": 10, "source_team": "",
                "adviser": "确认留学顾问", "event_date": "2026-09-10",
                "source_path": "网络资源-搜索", "resource_active_type": "被动",
                "main_active_type": "被动", "source_channel": "raw",
                "first_channel": "", "second_channel": "", "campaign_name": "活动A",
                "intended_country_source": "其他在读年级：未知推送方式：邮件 contact@example.com",
            },
            {
                "work_order_id": "A2", "source_row_number": 11, "source_team": "",
                "adviser": "确认留学顾问", "event_date": "2026-09-11",
                "source_path": "网络资源-搜索", "resource_active_type": "被动",
                "main_active_type": "被动", "source_channel": "raw",
                "first_channel": "", "second_channel": "", "campaign_name": "活动B",
                "intended_country_source": "日本/美国",
            },
        ]

        facts, diagnostics = normalize_facts(
            [], orders, people, abroad_people,
            {"确认留学顾问": "留学"}, reference(),
        )

        by_id = {fact["work_order_id"]: fact for fact in facts}
        self.assertIsNone(by_id["A1"]["country"])
        self.assertEqual(by_id["A2"]["country"], "日本")
        self.assertEqual(diagnostics["abroad_country_untrusted"], 1)


if __name__ == "__main__":
    unittest.main()
