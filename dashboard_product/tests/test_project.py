from workspace_modeling.operations.personnel import PEOPLE_CONFIG_PATH, is_displayable_person
import json
import unittest
from pathlib import Path

from dashboard_product.refresh import project
from dashboard_product.online_team.build import read

ROOT = Path(__file__).resolve().parents[1]


class ProjectTest(unittest.TestCase):
    def test_online_person_actuals_follow_natural_month(self):

        root = Path(__file__).resolve().parents[1]

        rows = [

            [day, "online_private", "青少", "市场活动", "虚拟人", "潘体学活动", None, "学校", "年级", "work_orders", 1, None, None, "被动", None]

            for day in ("2026-09-26", "2026-10-01")

        ]

        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(PEOPLE_CONFIG_PATH))

        team = next(team for team in result["teams"] if team["team_id"] == "online_private")

        person = next(person for person in team["people"] if person["display_name"] == "潘体学")

        # 20260929 v3 用户口径：虚拟人团队个人改按绩效月，9/26 与 10/01 都落在 2026-10 绩效月（9/26—10/25）。

        # 原断言 [1, 1] 把虚拟人个人锁成自然月，与新口径冲突；线上平台个人自然月另由 test_month_window_split 锁定。

        self.assertEqual(person["monthly_actuals"]["orders"][3:5], [0, 2])

    def test_departed_and_transferred_people_are_hidden_from_project(self):



        root = Path(__file__).resolve().parents[1]

        people = read(PEOPLE_CONFIG_PATH)

        statuses = {

            person['display_name']: person['status']

            for team in people['teams']

            for group in team.get('groups', [])

            for person in group.get('members', [])

            if person.get('display_name') in {'于洋', '王欣庆', '李进'}

        }

        self.assertEqual(statuses, {'于洋': 'departed', '王欣庆': 'departed', '李进': 'transferred'})



        result = project(

            {'result': {'rows': []}},

            {'result': {'rows': []}},

            read(root / 'config/project_targets.json'),

            people,

        )

        dashboard_names = {

            person['display_name']

            for team in result['teams']

            for person in team.get('people', [])

        }

        self.assertNotIn('于洋', dashboard_names)

        self.assertNotIn('王欣庆', dashboard_names)

        self.assertNotIn('李进', dashboard_names)

    def test_projects_people_targets_and_channel_drills(self):

        root = Path(__file__).resolve().parents[1]

        rows = [

            ["2026-09-03", "offline_market", "高中", "TMK", "校园", "杨新宇活动", None, "学校", "高一", "work_orders", 2, None, None, '被动', None],

            ["2026-09-03", "offline_market", "高中", "TMK", "校园", "杨新宇活动", None, "学校", "高一", "passive_reported_cash", 26000, None, '市场资源', '被动', '杨新宇活动'],

        ]

        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(PEOPLE_CONFIG_PATH))

        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")

        person = next(item for item in team["people"] if item["display_name"] == "杨新宇")

        self.assertEqual(person["business_group"], "高中")

        self.assertEqual(person["monthly_targets"]["2026-09"]["orders"], 60)

        self.assertEqual(person["monthly_drilldowns"]["2026-09"]["orders"]["TMK||校园"], 2)

        self.assertEqual(person["monthly_drilldowns"]["2026-09"]["cash"]["TMK||校园"], 26000)

        self.assertFalse(any(item["display_name"] == "空白占位 1" for item in team["people"]))

    def test_person_attribution_uses_entry_person_when_campaign_name_misses_roster(self):

        root = Path(__file__).resolve().parents[1]

        rows = [

            ["2026-09-03", "offline_market", "大学", "TMK", "校园", "天财豆蔻学姐号微信推广-曹恒为玮-线上雅思行地推", "曹恒玮", "某大学", "大一", "work_orders", 1, None, None, '被动', None],

        ]

        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(PEOPLE_CONFIG_PATH))

        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")

        cao = next(item for item in team["people"] if item["display_name"] == "曹恒玮")

        self.assertEqual(cao["orders_actual"], 1)

    def test_person_attribution_uses_entry_person_when_campaign_is_empty(self):

        root = Path(__file__).resolve().parents[1]

        rows = [

            ["2026-09-03", "offline_market", "大学", "TMK", "校园", None, "曹恒玮", "某大学", "大一", "work_orders", 1, None, None, '被动', None],

        ]

        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(PEOPLE_CONFIG_PATH))

        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")

        cao = next(item for item in team["people"] if item["display_name"] == "曹恒玮")

        self.assertEqual(cao["orders_actual"], 1)

    def test_person_attribution_filters_business_group_then_uses_entry_person_for_school_agent(self):

        root = Path(__file__).resolve().parents[1]

        rows = [

            ["2026-09-03", "offline_market", "高中", "TMK", "校园", "马澳高中活动", None, "学校", "高一", "work_orders", 5, None, None, '被动', None],

            ["2026-09-03", "offline_market", "青少", "TMK", "校园", "校代系统资源活动", "马澳", "学校", "初三", "work_orders", 3, None, None, '被动', None],

            ["2026-09-03", "offline_market", "青少", "TMK", "校园", "校代系统资源活动", "马澳", "学校", "初三", "passive_reported_cash", 39000, None, '市场资源', '被动', '校代系统资源活动'],

        ]

        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(PEOPLE_CONFIG_PATH))

        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")

        ma_ao = next(item for item in team["people"] if item["display_name"] == "马澳")

        self.assertEqual(ma_ao["orders_actual"], 3)

        self.assertEqual(ma_ao["cash_actual"], 39000)

        self.assertEqual(ma_ao["monthly_drilldowns"]["2026-09"]["orders"]["TMK||校园"], 3)

    def test_tmk_school_agent_owned_by_offline_roster_counts_offline(self):

        from dashboard_product.refresh import remap_tmk_school_agent_team

        root = Path(__file__).resolve().parents[1]

        people = read(PEOPLE_CONFIG_PATH)

        offline_names = {

            person.get("display_name")

            for team in people["teams"] if team["team_id"] == "offline_market"

            for group in team.get("groups", [])

            for person in group.get("members", [])

            if is_displayable_person(person)

        }

        self.assertEqual(

            remap_tmk_school_agent_team(

                "online_platform",

                "TMK激活-平台",

                "2027财年第4财月91校代系统资源活动",

                "石仁达",

                offline_names,

            ),

            "offline_market",

        )

        for person_name in ("刘彬", "马澳", "石仁达"):

            for note_label in ("备注:", "备注："):

                self.assertEqual(

                    remap_tmk_school_agent_team(

                        "online_platform",

                        "TMK激活-平台",

                        "2027财年第4财月91校代系统资源活动",

                        f"{person_name}{note_label}联系人刘彬",

                        offline_names,

                    ),

                    "offline_market",

                )

        self.assertEqual(

            remap_tmk_school_agent_team(

                "online_platform",

                "TMK激活-平台",

                "2027财年第4财月91校代系统资源活动",

                "无名人员备注：石仁达",

                offline_names,

            ),

            "online_platform",

        )

        self.assertEqual(

            remap_tmk_school_agent_team(

                "online_platform",

                "平台",

                "2027财年第4财月91校代系统资源活动",

                "石仁达",

                offline_names,

            ),

            "online_platform",

        )

        self.assertEqual(

            remap_tmk_school_agent_team(

                "online_platform",

                "TMK激活-平台",

                "2027财年第4财月抖音来客-新媒体管家",

                "石仁达",

                offline_names,

            ),

            "online_platform",

        )

        rows = [

            ["2026-09-12", "online_platform", "大学", "TMK激活-平台", "小表单", "2027财年第4财月91校代系统资源活动", "石仁达", "天津师范大学", "大四", "work_orders", 3, None, None, '被动', None],

            ["2026-09-12", "online_platform", "大学", "平台", "抖音来客", "2027财年第4财月抖音来客-新媒体管家", "苗莎莎", "天津大学", "大一", "work_orders", 4, None, None, '被动', None],

        ]

        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), people)

        offline = next(item for item in result["teams"] if item["team_id"] == "offline_market")

        platform = next(item for item in result["teams"] if item["team_id"] == "online_platform")

        shi = next(item for item in offline["people"] if item["display_name"] == "石仁达")

        uni_offline = next(item for item in offline["groups"] if item["display_name"] == "大学")

        uni_platform = next(item for item in platform["groups"] if item["display_name"] == "大学")

        self.assertEqual(shi["orders_actual"], 3)

        self.assertEqual(shi["monthly_actuals"]["orders"][3], 3)

        self.assertEqual(shi["monthly_drilldowns"]["2026-09"]["orders"]["TMK激活-平台||小表单"], 3)

        self.assertEqual(uni_offline["monthly_actuals"]["orders"][3], 3)

        self.assertEqual(uni_platform["monthly_actuals"]["orders"][3], 4)

    def test_cash_channel_contract_uses_work_order_left_join(self):

        query = (Path(__file__).resolve().parents[1] / "sql/dashboard_actuals.sql").read_text(encoding="utf-8")

        self.assertIn("LEFT JOIN orders_dim o", query)

        self.assertIn("资源描述", query)

        self.assertIn("市场人员", query)

        self.assertIn("渠道/顾问暂无法拆分", query)

        self.assertIn("COALESCE(c.cash_business_group, '业务组暂无法拆分')", query)

        self.assertIn("顾问归属", query)

        self.assertIn("跟进顾问", query)

        self.assertIn("张艺彤", query)

        self.assertIn("年级校正", query)

        self.assertIn("COALESCE(c.cash_business_group, '业务组暂无法拆分') AS business_group", query)

        self.assertIn("WHEN TRIM(团队) IN ('初中','初中国际学科') THEN '初中'", query)

        self.assertNotIn("COALESCE(o.business_group, c.cash_business_group)", query)

        self.assertIn("NULLIF(TRIM(学员编号),'') AS student_id", query)

        self.assertIn("NULL AS student_id", query)

        self.assertIn("metric, actual_value, student_id, cash_channel, work_order_active_type, cash_campaign_name FROM orders", query)

    def test_market_total_keeps_unassigned_facts_without_putting_them_in_teams_or_people(self):

        root = Path(__file__).resolve().parents[1]

        rows = [

            ["2026-08-12", None, "业务组暂无法拆分", "平台", "小红书", "活动", None, None, None, "work_orders", 3, None, None, '被动', None],

            ["2026-08-12", None, "高中", "渠道/顾问暂无法拆分", "渠道/顾问暂无法拆分", "现金活动", None, None, None, "passive_reported_cash", 181200, "S1", '市场资源', None, '现金活动'],

            ["2026-08-12", "offline_market", "高中", "TMK", "讲座", "杨新宇活动", None, None, None, "work_orders", 2, None, None, '被动', None],

        ]

        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(PEOPLE_CONFIG_PATH))

        market = next(item for item in result["teams"] if item["team_id"] == "market_total")

        offline = next(item for item in result["teams"] if item["team_id"] == "offline_market")

        market_groups = {item["display_name"]: item for item in market["business_group_groups"]}

        market_teams = {item["display_name"]: item for item in market["groups"]}

        offline_groups = {item["display_name"]: item for item in offline["groups"]}

        self.assertEqual(market_groups["业务组暂无法拆分"]["monthly_actuals"]["orders"][2], 3)

        self.assertEqual(market_groups["高中"]["monthly_actuals"]["cash"][2], 181200)

        self.assertEqual(market_teams["暂时无法识别团队"]["monthly_actuals"]["cash"][2], 181200)

        self.assertEqual(offline_groups["高中"]["monthly_actuals"]["cash"][2], 0)

        self.assertEqual(offline_groups["高中"]["monthly_actuals"]["orders"][2], 2)

        self.assertIn("2026-08|market_total|高中|暂时无法识别渠道|暂时无法识别渠道", result["drilldowns"]["current"]["cash"]["channel"])

    def test_youth_and_middle_school_roll_up_to_liuxue_and_keep_four_yoy_groups(self):

        root = Path(__file__).resolve().parents[1]

        rows = [

            ["2026-09-03", "offline_market", "青少", "TMK", "校园", "王昊活动", None, "学校", "一年级", "passive_reported_cash", 100, None, '市场资源', '被动', '王昊活动'],

            ["2026-09-03", "offline_market", "初中", "TMK", "校园", "初中活动", None, "学校", "七年级", "passive_reported_cash", 40, None, '市场资源', '被动', '初中活动'],

            ["2026-09-03", "offline_market", "高中", "TMK", "校园", "杨新宇活动", None, "学校", "高一", "passive_reported_cash", 20, None, '市场资源', '被动', '杨新宇活动'],

        ]

        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(PEOPLE_CONFIG_PATH))

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

    def test_online_platform_monthly_targets_from_training_workbook(self):

        from dashboard_product.refresh import project

        result = project(

            {'result': {'rows': []}},

            {'result': {'rows': []}},

            read(Path(__file__).resolve().parents[1] / 'config/project_targets.json'),

            read(PEOPLE_CONFIG_PATH),

        )

        platform = next(team for team in result['teams'] if team['team_id'] == 'online_platform')

        prep = next(group for group in platform['groups'] if group['display_name'] == '留学预备')

        self.assertEqual(prep['monthly_targets']['2026-06']['orders'], 336)

        self.assertEqual(prep['monthly_targets']['2026-06']['cash'], 351034)

        self.assertEqual(prep['annual_targets']['orders'], 3985)

    def test_offline_cocreation_splits_person_actuals_and_heads_not_team_totals(self):
        people = {'teams': [{
            'team_id': 'offline_market',
            'groups': [{'display_name': '大学组', 'members': [
                {'display_name': '共创甲', 'status': 'active', 'business_group': '大学'},
                {'display_name': '共创乙', 'status': 'active', 'business_group': '大学'},
            ]}],
        }]}
        rows = [
            ['2026-09-10', 'offline_market', '大学', '市场活动', '异业渠道', '共创甲共创乙活动',
             None, '某大学', '大一', 'work_orders', 100, None, None, '被动', None],
            ['2026-09-10', 'offline_market', '大学', '市场活动', '异业渠道', '共创甲共创乙活动',
             None, '某大学', '大一', 'passive_reported_cash', 100, 'S-1', '市场资源', '被动', '共创甲共创乙活动'],
        ]

        result = project(
            {'result': {'rows': rows}}, {'result': {'rows': []}},
            read(ROOT / 'config/project_targets.json'), people,
        )

        team = next(row for row in result['teams'] if row['team_id'] == 'offline_market')
        group = next(row for row in team['groups'] if row['display_name'] == '大学')
        members = {row['display_name']: row for row in team['people']}
        self.assertEqual(group['monthly_actuals']['orders'][3], 100)
        self.assertEqual(group['monthly_actuals']['cash'][3], 100)
        for name in ('共创甲', '共创乙'):
            self.assertEqual(members[name]['orders_actual'], 50)
            self.assertEqual(members[name]['cash_actual'], 50)
            self.assertEqual(members[name]['heads_actual'], 0.5)
            self.assertEqual(members[name]['monthly_drilldowns']['2026-09']['orders']['市场活动||异业渠道'], 50)
            self.assertEqual(members[name]['monthly_drilldowns']['2026-09']['cash']['市场活动||异业渠道'], 50)

    def test_other_home_group_participant_stays_in_denominator_but_not_person_kpi(self):
        people = {'teams': [{
            'team_id': 'offline_market',
            'groups': [
                {'display_name': '大学组', 'members': [
                    {'display_name': '大学甲', 'status': 'active', 'business_group': '大学'},
                ]},
                {'display_name': '高中组', 'members': [
                    {'display_name': '高中乙', 'status': 'active', 'business_group': '高中'},
                ]},
            ],
        }]}
        rows = [
            ['2026-09-10', 'offline_market', '大学', '市场活动', '异业渠道', '大学甲高中乙共创',
             None, '某大学', '大一', 'work_orders', 100, None, None, '被动', None],
            ['2026-09-10', 'offline_market', '大学', '市场活动', '异业渠道', '大学甲高中乙共创',
             None, '某大学', '大一', 'passive_reported_cash', 100, 'S-3', '市场资源', '被动', '大学甲高中乙共创'],
        ]

        result = project(
            {'result': {'rows': rows}}, {'result': {'rows': []}},
            read(ROOT / 'config/project_targets.json'), people,
        )

        team = next(row for row in result['teams'] if row['team_id'] == 'offline_market')
        university = next(row for row in team['groups'] if row['display_name'] == '大学')
        members = {row['display_name']: row for row in team['people']}
        self.assertEqual(university['monthly_actuals']['orders'][3], 100)
        self.assertEqual(university['monthly_actuals']['cash'][3], 100)
        self.assertEqual(members['大学甲']['orders_actual'], 50)
        self.assertEqual(members['大学甲']['cash_actual'], 50)
        self.assertEqual(members['大学甲']['heads_actual'], 0.5)
        self.assertEqual(members['高中乙']['orders_actual'], 0)
        self.assertEqual(members['高中乙']['cash_actual'], 0)
        self.assertEqual(members['高中乙']['heads_actual'], 0)

    def test_online_private_cocreators_each_keep_full_personal_weight(self):
        people = {'teams': [{
            'team_id': 'online_private',
            'groups': [{'display_name': '大学组', 'members': [
                {'display_name': '虚拟甲', 'status': 'active', 'business_group': '大学'},
                {'display_name': '虚拟乙', 'status': 'active', 'business_group': '大学'},
            ]}],
        }]}
        rows = [
            ['2026-09-10', 'online_private', '大学', '市场活动', '虚拟人', '虚拟甲虚拟乙活动',
             None, '某大学', '大一', 'work_orders', 100, None, None, '被动', None],
            ['2026-09-10', 'online_private', '大学', '市场活动', '虚拟人', '虚拟甲虚拟乙活动',
             None, '某大学', '大一', 'passive_reported_cash', 100, 'S-2', '市场资源', '被动', '虚拟甲虚拟乙活动'],
        ]

        result = project(
            {'result': {'rows': rows}}, {'result': {'rows': []}},
            read(ROOT / 'config/project_targets.json'), people,
        )

        team = next(row for row in result['teams'] if row['team_id'] == 'online_private')
        group = next(row for row in team['groups'] if row['display_name'] == '大学')
        members = {row['display_name']: row for row in team['people']}
        self.assertEqual(group['monthly_actuals']['orders'][3], 100)
        self.assertEqual(group['monthly_actuals']['cash'][3], 100)
        for name in ('虚拟甲', '虚拟乙'):
            self.assertEqual(members[name]['orders_actual'], 100)
            self.assertEqual(members[name]['cash_actual'], 100)
            self.assertEqual(members[name]['heads_actual'], 1)
