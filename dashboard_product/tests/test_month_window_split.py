"""Project-baseline month-window checks retained for management reconciliation."""
import unittest
from pathlib import Path

from dashboard_product.online_team.build import read
from dashboard_product.refresh import project
from workspace_modeling.operations.personnel import PEOPLE_CONFIG_PATH

ROOT = Path(__file__).resolve().parents[1]


def _dashboard_row(day, team, group, campaign):
    return [day, team, group, "市场活动", "高校活动", campaign, None, "学校", "年级", "work_orders", 1, None, None, "被动", None]


class MainDashboardMonthSplitTest(unittest.TestCase):
    def _project(self, rows):
        return project({"result": {"rows": rows}}, {"result": {"rows": []}},
                       read(ROOT / "config/project_targets.json"), read(PEOPLE_CONFIG_PATH))

    def test_offline_person_performance_month_team_natural_month(self):
        rows = [_dashboard_row(day, "offline_market", "大学", "师顺盈活动") for day in ("2026-09-25", "2026-09-26")]
        result = self._project(rows)
        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")
        person = next(item for item in team["people"] if item["display_name"] == "师顺盈")
        self.assertEqual(person["monthly_actuals"]["orders"][3:5], [1, 1])
        group = next(item for item in team["groups"] if item["display_name"] == "大学")
        self.assertEqual(group["monthly_actuals"]["orders"][3:5], [2, 0])
        total = next(item for item in result["teams"] if item["team_id"] == "market_total")
        offline_total = next(item for item in total["groups"] if item["team_id"] == "offline_market")
        self.assertEqual(offline_total["monthly_actuals"]["orders"][3:5], [2, 0])

    def test_online_private_person_performance_month_team_natural_month(self):
        rows = [_dashboard_row(day, "online_private", "青少", "潘体学活动")
                for day in ("2026-08-26", "2026-09-25", "2026-09-26")]
        result = self._project(rows)
        team = next(item for item in result["teams"] if item["team_id"] == "online_private")
        person = next(item for item in team["people"] if item["display_name"] == "潘体学")
        self.assertEqual(person["monthly_actuals"]["orders"][2:5], [0, 2, 1])
        drill = person["monthly_drilldowns"]
        self.assertEqual(sum(drill["2026-09"]["orders"].values()), 2)
        self.assertEqual(sum(drill["2026-10"]["orders"].values()), 1)
        group = next(item for item in team["groups"] if item["display_name"] == "留学预备")
        self.assertEqual(group["monthly_actuals"]["orders"][2:5], [1, 2, 0])
        total = next(item for item in result["teams"] if item["team_id"] == "market_total")
        private_total = next(item for item in total["groups"] if item["team_id"] == "online_private")
        self.assertEqual(private_total["monthly_actuals"]["orders"][2:5], [1, 2, 0])

    def test_online_platform_person_stays_natural_month(self):
        people = {"teams": [{"team_id": "online_platform", "groups": [{"display_name": "大学组", "members": [
            {"display_name": "测试平台", "business_group": "大学", "status": "active", "monthly_targets": {}}]}]}]}
        rows = [_dashboard_row(day, "online_platform", "大学", "测试平台活动")
                for day in ("2026-09-25", "2026-09-26")]
        result = project({"result": {"rows": rows}}, {"result": {"rows": []}},
                         read(ROOT / "config/project_targets.json"), people)
        team = next(item for item in result["teams"] if item["team_id"] == "online_platform")
        person = next(item for item in team["people"] if item["display_name"] == "测试平台")
        self.assertEqual(person["monthly_actuals"]["orders"][3:5], [2, 0])


if __name__ == "__main__":
    unittest.main()
