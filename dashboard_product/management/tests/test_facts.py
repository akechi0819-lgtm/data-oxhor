from __future__ import annotations

import unittest
from datetime import date

from data_acquisition.jobs.work_order_cleaning import WorkOrderReference
from dashboard_product.management.aggregate import aggregate
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


def abroad_order(work_order_id, *, source_path="渠道合作-大客户渠道", source_channel="分公司对公合作",
                 active="被动", first_channel="", second_channel="", campaign="普通推荐",
                 entry_person="", description="", other_referrer="", online_offline=""):
    return {
        "work_order_id": work_order_id, "source_row_number": 10,
        "source_team": "", "adviser": "确认留学顾问", "event_date": "2026-09-10",
        "source_path": source_path, "resource_active_type": active,
        "main_active_type": active, "source_channel": source_channel,
        "first_channel": first_channel, "second_channel": second_channel,
        "campaign_name": campaign, "resource_entry_person": entry_person,
        "resource_description": description, "other_referrer": other_referrer,
        "intended_country_source": "日本", "online_offline": online_offline,
    }


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
        for work_order_id, status in (("A-deleted", "删除"), ("A-recalled", "回收")):
            row = abroad_order(work_order_id)
            row["order_status"] = status
            orders.append(row)
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
            training, orders, people, abroad_people, {"确认留学顾问": "留学"}, reference(),
        )

        by_id = {fact["fact_id"]: fact for fact in facts}
        self.assertFalse(by_id["training:order:T-deleted"]["counts_toward_completion"])
        self.assertEqual(by_id["training:order:T-deleted"]["exclusion_reason"], "order_status_deleted")
        self.assertEqual(by_id["training:order:T-deleted"]["source_record"]["工单状态"], "删除")
        self.assertFalse(by_id["training:order:T-recalled"]["counts_toward_completion"])
        self.assertEqual(by_id["training:order:T-recalled"]["exclusion_reason"], "order_status_recalled")
        self.assertFalse(by_id["abroad:order:A-deleted"]["counts_toward_completion"])
        self.assertFalse(by_id["abroad:order:A-recalled"]["counts_toward_completion"])
        cash = by_id["training:cash:20"]
        self.assertTrue(cash["counts_toward_completion"])
        self.assertIsNone(cash["exclusion_reason"])
        self.assertEqual(cash["order_status"], "删除")
        self.assertEqual(cash["source_record"], {"工单ID": "T-deleted"})

        result = aggregate(facts, people, abroad_people, {}, {}, {}, date(2026, 9, 28))
        september = next(period for period in result["periods"] if period["id"] == "2026-09")
        total = next(team for team in september["teams"] if team["id"] == "total")
        self.assertEqual(total["lines"]["training"]["orders"]["actual"], 3)
        self.assertEqual(total["lines"]["training"]["cash"]["actual"], 500)
        self.assertEqual(total["lines"]["abroad"]["orders"]["actual"], 2)

    def test_online_eight_person_claim_stays_online_and_keeps_personal_owner(self):
        people, abroad_people = configs()
        orders = [abroad_order(
            "A1", source_path="网络资源-搜索", source_channel="raw",
            entry_person="孙伟", campaign="否", online_offline="线上",
        )]

        facts, _ = normalize_facts(
            [], orders, people, abroad_people,
            {"确认留学顾问": "留学"}, reference(),
        )

        self.assertEqual(len(facts), 1)
        fact = facts[0]
        self.assertEqual(fact["team_id"], "online_platform")
        self.assertIsNone(fact["business_group"])
        self.assertFalse(fact["offline_channel_eligible"])
        self.assertEqual(fact["acquisition_mode"], "online")
        self.assertEqual(fact["country"], "日本")
        self.assertEqual(fact["line"], "亚洲条线")
        self.assertIn("孙伟", fact["owners"])
        self.assertIsNone(fact["campaign_name"])

        result = aggregate(facts, people, abroad_people, {}, {}, {}, date(2026, 9, 28))
        september = next(period for period in result["periods"] if period["id"] == "2026-09")
        team = {row["id"]: row for row in september["teams"]}
        self.assertEqual(team["university"]["lines"]["abroad"]["orders"]["actual"], 0)
        self.assertEqual(team["online"]["lines"]["abroad"]["orders"]["actual"], 1)

    def test_passive_original_offline_channels_count_without_roster_claim(self):
        people, abroad_people = configs()
        orders = [
            abroad_order("partner", source_path="渠道合作-大客户渠道", entry_person=""),
            abroad_order("market", source_path="市场活动-高校", source_channel="高校活动",
                         entry_person="已离职员工"),
            abroad_order("official", source_path="官方合作高校", entry_person="孙伟"),
        ]

        facts, _ = normalize_facts([], orders, people, abroad_people,
                                   {"确认留学顾问": "留学"}, reference())

        self.assertEqual({fact["work_order_id"] for fact in facts if fact["offline_channel_eligible"]},
                         {"partner", "market", "official"})
        self.assertEqual(next(fact for fact in facts if fact["work_order_id"] == "partner")["owners"], [])
        result = aggregate(facts, people, abroad_people, {}, {}, {}, date(2026, 9, 28))
        september = next(period for period in result["periods"] if period["id"] == "2026-09")
        university = next(row for row in september["teams"] if row["id"] == "university")
        self.assertEqual(university["lines"]["abroad"]["orders"]["actual"], 3)

    def test_active_original_offline_channels_do_not_count_from_eight_person_claim(self):
        people, abroad_people = configs()
        orders = [
            abroad_order("partner", source_path="渠道合作-大客户渠道", active="主动", entry_person="孙伟"),
            abroad_order("market", source_path="市场活动-高校", source_channel="高校活动",
                         active="主动", entry_person="孙伟"),
            abroad_order("official", source_path="官方合作高校", active="主动", entry_person="孙伟"),
        ]

        facts, _ = normalize_facts([], orders, people, abroad_people,
                                   {"确认留学顾问": "留学"}, reference())

        self.assertTrue(all("孙伟" in fact["owners"] for fact in facts))
        self.assertTrue(all(not fact["offline_channel_eligible"] for fact in facts))
        result = aggregate(facts, people, abroad_people, {}, {}, {}, date(2026, 9, 28))
        september = next(period for period in result["periods"] if period["id"] == "2026-09")
        university = next(row for row in september["teams"] if row["id"] == "university")
        self.assertEqual(university["lines"]["abroad"]["orders"]["actual"], 0)
        sun_wei = next(person for person in university["people"] if person["name"] == "孙伟")
        self.assertEqual(sun_wei["abroad_actual"], 3)

    def test_newdongfang_only_point_to_point_market_subset_enters_department(self):
        people, abroad_people = configs()
        orders = [
            abroad_order("nd-warehouse", source_path="新东方学校推荐-大学事业部",
                         source_channel="点对点", first_channel="市场活动"),
            abroad_order("nd-strong", source_path="新东方学校推荐-大学事业部",
                         source_channel="点对点", campaign="市场人员精准推荐"),
            abroad_order("nd-event", source_path="新东方学校推荐-大学事业部",
                         source_channel="点对点", description="校园讲座收集"),
            abroad_order("nd-person", source_path="新东方学校推荐-大学事业部",
                         source_channel="点对点", entry_person="吴子玄"),
            abroad_order("nd-default", source_path="新东方学校推荐-大学事业部",
                         source_channel="点对点", campaign="普通推荐"),
            abroad_order("nd-push", source_path="新东方学校推荐-大学事业部",
                         source_channel="批量推送", first_channel="市场活动"),
            abroad_order("nd-import", source_path="新东方学校推荐-大学事业部",
                         source_channel="批量导入", campaign="市场人员推荐"),
            abroad_order("nd-cancel", source_path="新东方学校推荐-大学事业部",
                         source_channel="取消", entry_person="吴子玄"),
        ]

        facts, _ = normalize_facts([], orders, people, abroad_people,
                                   {"确认留学顾问": "留学"}, reference())

        eligible_ids = {fact["work_order_id"] for fact in facts if fact["offline_channel_eligible"]}
        self.assertEqual(eligible_ids, {"nd-warehouse", "nd-strong", "nd-event", "nd-person"})
        result = aggregate(facts, people, abroad_people, {}, {}, {}, date(2026, 9, 28))
        september = next(period for period in result["periods"] if period["id"] == "2026-09")
        university = next(row for row in september["teams"] if row["id"] == "university")
        self.assertEqual(university["lines"]["abroad"]["orders"]["actual"], 4)

    def test_confirmed_offline_id_changes_only_source_mode_and_preserves_university_totals(self):
        people, abroad_people = configs()
        abroad_people['confirmed_offline_work_order_ids'] = ['33436045']

        def order(work_order_id, second_channel=''):
            return {
                'work_order_id': work_order_id, 'source_row_number': 10,
                'source_team': '', 'adviser': '确认留学顾问', 'event_date': '2026-06-28',
                'source_path': '网络资源-搜索', 'resource_active_type': '被动',
                'main_active_type': '被动', 'source_channel': 'raw',
                'first_channel': '', 'second_channel': second_channel, 'campaign_name': '否',
                'resource_entry_person': '邓睿', 'resource_description': '',
                'intended_country_source': '日本', 'online_offline': '线上',
            }

        facts, diagnostics = normalize_facts(
            [], [order('33436045'), order('unknown-id'), order('ssc-id', 'SSC')],
            people, abroad_people, {'确认留学顾问': '留学'}, reference(),
        )

        by_id = {fact['work_order_id']: fact for fact in facts}
        self.assertNotIn('ssc-id', by_id)
        self.assertEqual(diagnostics['ssc_excluded'], 1)
        self.assertEqual(by_id['33436045']['team_id'], 'offline_market')
        self.assertEqual(by_id['33436045']['business_group'], '大学')
        self.assertTrue(by_id['33436045']['offline_channel_eligible'])
        self.assertEqual(by_id['33436045']['acquisition_mode'], 'offline')
        self.assertEqual(by_id['33436045']['first_channel'], '网络资源')
        self.assertEqual(by_id['33436045']['second_channel'], '搜索')
        self.assertEqual(by_id['33436045']['country'], '日本')
        self.assertEqual(by_id['33436045']['line'], '亚洲条线')
        self.assertEqual(by_id['unknown-id']['acquisition_mode'], 'online')

        result = aggregate(facts, people, abroad_people, {}, {}, {}, date(2026, 9, 28))
        june = next(period for period in result['periods'] if period['id'] == '2026-06')
        team = {row['id']: row for row in june['teams']}
        self.assertEqual(team['total']['lines']['abroad']['orders']['actual'], 2)
        self.assertEqual(team['university']['lines']['abroad']['orders']['actual'], 1)
        self.assertEqual(team['online']['lines']['abroad']['orders']['actual'], 1)
        university_country = team['university']['countries'][0]
        self.assertEqual(university_country['country'], '日本')
        self.assertEqual(university_country['online'], 0)
        self.assertEqual(university_country['offline'], 1)

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
            training, orders, people, abroad_people, {}, reference(),
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
