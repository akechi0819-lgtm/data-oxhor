from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_product.fallback_mapping import (
    CHANNEL_NATURAL,
    TMK_PLATFORM_CHANNEL,
    infer_team,
)
from dashboard_product.management.facts import normalize_facts
from dashboard_product.online_team.build import read
from dashboard_product.refresh import project
from workspace_modeling.operations.personnel import PEOPLE_CONFIG_PATH


ROOT = Path(__file__).resolve().parents[1]


class TmkPlatformRoutingTests(unittest.TestCase):
    def test_platform_route_wins_for_cash_and_orders_from_any_original_team(self):
        original_teams = ("offline_market", "online_private", "online_platform", None)
        people = read(PEOPLE_CONFIG_PATH)
        rows = []
        for index, (original_team, cash_amount) in enumerate(
            zip(original_teams, (100, 200, 300, 400)), start=1
        ):
            common = [
                "2026-09-12", original_team, "大学", TMK_PLATFORM_CHANNEL,
                "小表单", "校代系统资源活动", "石仁达", "天津师范大学", "大四",
            ]
            rows.append(common + ["work_orders", 1, None, None, None, None])
            rows.append(common + [
                "passive_reported_cash", cash_amount, None, "普通现金", None,
                "校代系统资源活动",
            ])

        result = project(
            {"result": {"rows": rows}},
            {"result": {"rows": []}},
            read(ROOT / "config/project_targets.json"),
            people,
        )
        teams = {team["team_id"]: team for team in result["teams"]}
        month_index = 3
        for team_id in ("offline_market", "online_private"):
            group = next(group for group in teams[team_id]["groups"] if group["display_name"] == "大学")
            self.assertEqual(group["monthly_actuals"]["orders"][month_index], 0)
            self.assertEqual(group["monthly_actuals"]["cash"][month_index], 0)

        platform_group = next(
            group for group in teams["online_platform"]["groups"]
            if group["display_name"] == "大学"
        )
        self.assertEqual(platform_group["monthly_actuals"]["orders"][month_index], 4)
        self.assertEqual(platform_group["monthly_actuals"]["cash"][month_index], 1000)
        market_total = next(team for team in result["teams"] if team["team_id"] == "market_total")
        total_group = next(group for group in market_total["business_group_groups"] if group["display_name"] == "大学")
        self.assertEqual(total_group["monthly_actuals"]["orders"][month_index], 4)
        self.assertEqual(total_group["monthly_actuals"]["cash"][month_index], 1000)
        for metric in ("orders", "cash"):
            key = f"2026-09|online_platform|大学|{TMK_PLATFORM_CHANNEL}|小表单"
            self.assertEqual(result["drilldowns"]["current"][metric]["channel"][key], 4 if metric == "orders" else 1000)

    def test_normalize_facts_forces_platform_after_cash_resolution_and_keeps_source(self):
        people = {
            "teams": [
                {"team_id": "offline_market", "groups": [{"display_name": "大学组", "members": [
                    {"display_name": "线下校代", "status": "active", "business_group": "大学"},
                ]}]},
                {"team_id": "online_private", "groups": []},
                {"team_id": "online_platform", "groups": []},
            ]
        }
        abroad_people = {"people": []}
        original_teams = ("offline_market", "online_private", "online_platform", None)
        training_rows = []
        order_rows = []
        for index, original_team in enumerate(original_teams, start=1):
            common = {
                "event_date": "2026-09-12", "team_id": original_team,
                "business_group": "大学", "first_channel": TMK_PLATFORM_CHANNEL,
                "second_channel": "小表单", "campaign_name": "校代系统资源活动",
                "entry_person": "线下校代",
            }
            source_row = 100 + index
            training_rows.append({
                **common, "source_row_number": source_row,
                "work_order_id": f"cash-{index}", "metric": "passive_reported_cash",
                "actual_value": str(index * 100), "cash_channel": "普通现金",
                "cash_campaign_name": "普通现金活动",
            })
            work_order_id = f"order-{index}"
            training_rows.append({
                **common, "source_row_number": 200 + index,
                "work_order_id": work_order_id, "metric": "work_orders",
                "actual_value": 1,
            })
            order_rows.append({
                "work_order_id": work_order_id, "source_team": "高中",
                "campaign_name": "校代系统资源活动", "resource_entry_person": "线下校代",
            })

        facts, _ = normalize_facts(training_rows, order_rows, people, abroad_people, {})
        self.assertEqual(len(facts), 8)
        by_id = {fact["fact_id"]: fact for fact in facts}
        for index in range(1, 5):
            cash = by_id[f"training:cash:{100 + index}"]
            order = by_id[f"training:order:order-{index}"]
            self.assertEqual(cash["team_id"], "online_platform")
            self.assertEqual(order["team_id"], "online_platform")
            self.assertEqual(cash["value"], index * 100)
            self.assertEqual(order["value"], 1)
            self.assertEqual(cash["source_row_number"], 100 + index)
            for fact in (cash, order):
                self.assertEqual(fact["first_channel"], TMK_PLATFORM_CHANNEL)
                self.assertEqual(fact["second_channel"], "小表单")
                self.assertEqual(fact["owners"], ["线下校代"])

    def test_other_tmk_market_activity_keeps_existing_offline_rule(self):
        self.assertEqual(
            infer_team(
                "online_private", "TMK", "校园市场活动", "TMK激活-市场活动",
                "校园", "保留现有工单组合",
            )[0],
            "offline_market",
        )
        rows = [[
            "2026-09-12", "online_private", "大学", "TMK激活-市场活动",
            "校园", "校园市场活动", None, "天津大学", "大一",
            "passive_reported_cash", 250, None, "TMK", None, "校园市场活动",
        ]]
        result = project(
            {"result": {"rows": rows}}, {"result": {"rows": []}},
            read(ROOT / "config/project_targets.json"), read(PEOPLE_CONFIG_PATH),
        )
        teams = {team["team_id"]: team for team in result["teams"]}
        offline = next(group for group in teams["offline_market"]["groups"] if group["display_name"] == "大学")
        private = next(group for group in teams["online_private"]["groups"] if group["display_name"] == "大学")
        self.assertEqual(offline["monthly_actuals"]["cash"][3], 250)
        self.assertEqual(private["monthly_actuals"]["cash"][3], 0)
        self.assertIn(
            "2026-09|offline_market|大学|TMK激活-市场活动|校园",
            result["drilldowns"]["current"]["cash"]["channel"],
        )

    def test_original_platform_cash_stays_online_when_cash_channels_conflict(self):
        unresolved = {
            "first_channel": CHANNEL_NATURAL,
            "second_channel": CHANNEL_NATURAL,
            "decision": CHANNEL_NATURAL,
        }
        people = {
            "teams": [{"team_id": "offline_market", "groups": [{"display_name": "大学组", "members": [
                {"display_name": "线下校代", "status": "active", "business_group": "大学"},
            ]}]}]
        }
        cash_row = {
            "source_row_number": 40457, "work_order_id": "platform-conflict",
            "event_date": "2025-05-05", "team_id": "online_private",
            "business_group": "大学", "first_channel": TMK_PLATFORM_CHANNEL,
            "second_channel": "小表单", "campaign_name": "校代系统资源活动",
            "entry_person": "线下校代", "metric": "passive_reported_cash",
            "actual_value": "1250.00", "cash_channel": "TMK",
            "cash_campaign_name": "校代系统资源活动",
        }
        with patch("dashboard_product.management.facts.resolve_cash_channel", return_value=unresolved):
            facts, _ = normalize_facts(
                [cash_row], [], people, {"people": []}, {},
                cash_team_overrides={"overrides": [{
                    "work_order_id": "platform-conflict", "event_date": "2025-05-05",
                    "amount": "1250.00", "team_id": "offline_market", "note": "测试覆盖",
                }]},
            )
        self.assertEqual(len(facts), 1)
        fact = facts[0]
        self.assertEqual(fact["team_id"], "online_platform")
        self.assertEqual(fact["first_channel"], CHANNEL_NATURAL)
        self.assertEqual(fact["second_channel"], CHANNEL_NATURAL)
        self.assertEqual(fact["value"], 1250.0)
        self.assertEqual(fact["source_row_number"], 40457)
        self.assertEqual(fact["owners"], ["线下校代"])
        self.assertNotIn("team_override_reason", fact)

        project_row = [
            "2026-09-05", "online_private", "大学", TMK_PLATFORM_CHANNEL,
            "小表单", "校代系统资源活动", "线下校代", "天津大学", "大一",
            "passive_reported_cash", 1250, None, "TMK", None,
            "校代系统资源活动",
        ]
        with patch("dashboard_product.refresh.resolve_cash_channel", return_value=unresolved):
            result = project(
                {"result": {"rows": [project_row]}},
                {"result": {"rows": []}},
                read(ROOT / "config/project_targets.json"),
                read(PEOPLE_CONFIG_PATH),
            )
        platform = next(team for team in result["teams"] if team["team_id"] == "online_platform")
        university = next(group for group in platform["groups"] if group["display_name"] == "大学")
        month_index = 3
        market = next(team for team in result["teams"] if team["team_id"] == "market_total")
        market_university = next(group for group in market["business_group_groups"] if group["display_name"] == "大学")
        self.assertEqual(university["monthly_actuals"]["cash"][month_index], 1250)
        self.assertEqual(market_university["cash_actual"], 1250)
        self.assertIn(
            f"2026-09|market_total|大学|{CHANNEL_NATURAL}|{CHANNEL_NATURAL}",
            result["drilldowns"]["current"]["cash"]["channel"],
        )


if __name__ == "__main__":
    unittest.main()
