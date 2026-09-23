from workspace_modeling.operations.personnel import PEOPLE_CONFIG_PATH, is_displayable_person
import json
import tempfile
import unittest
from pathlib import Path

from dashboard_product.refresh import DASHBOARD_QUERY_COLUMNS, DASHBOARD_SAVED_QUERY, project, render, validate_publish_artifact


def _publish_artifact(directory, version='v14', columns=None):
    root = Path(directory)
    receipt_rel = Path('data/query_results/evidence/receipt.json')
    (root / receipt_rel).parent.mkdir(parents=True)
    (root / receipt_rel).write_text(
        json.dumps({'saved_query_ref': {'query_id': 'dashboard_actuals', 'version': version}}),
        encoding='utf-8',
    )
    query_columns = list(columns or DASHBOARD_QUERY_COLUMNS)
    artifact = {
        'schema_version': 'dashboard_artifact.v1',
        'query_results': [
            {
                'status': 'passed',
                'columns': query_columns,
                'receipt': {'path': str(receipt_rel)},
            },
            {
                'status': 'passed',
                'columns': query_columns,
                'receipt': {'path': str(receipt_rel)},
            },
        ],
    }
    path = root / 'artifact.json'
    path.write_text(json.dumps(artifact), encoding='utf-8')
    return path


class RenderTest(unittest.TestCase):
    def test_publish_validation_accepts_current_query_and_rejects_legacy_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            current = _publish_artifact(Path(directory) / 'current')
            self.assertEqual(validate_publish_artifact(current)['saved_query'], DASHBOARD_SAVED_QUERY)

            legacy = _publish_artifact(
                Path(directory) / 'legacy',
                version='v10',
                columns=DASHBOARD_QUERY_COLUMNS[:-1],
            )
            with self.assertRaisesRegex(ValueError, 'dashboard_actuals/v14'):
                validate_publish_artifact(legacy)

    def test_departed_and_transferred_people_are_hidden_from_dashboard_and_notify(self):
        from dashboard_product.refresh import read

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

        from monitoring_product.digest import configured_people_for_channel
        notify_names = {
            person['display_name']
            for channel_id in ('offline_high_school', 'offline_youth', 'offline_university')
            for person in configured_people_for_channel(channel_id, people)
        }
        self.assertNotIn('于洋', notify_names)
        self.assertNotIn('王欣庆', notify_names)
        self.assertNotIn('李进', notify_names)

    def test_projects_people_targets_and_channel_drills(self):
        from dashboard_product.refresh import read
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
        from dashboard_product.refresh import read
        root = Path(__file__).resolve().parents[1]
        rows = [
            ["2026-09-03", "offline_market", "大学", "TMK", "校园", "天财豆蔻学姐号微信推广-曹恒为玮-线上雅思行地推", "曹恒玮", "某大学", "大一", "work_orders", 1, None, None, '被动', None],
        ]
        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(PEOPLE_CONFIG_PATH))
        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")
        cao = next(item for item in team["people"] if item["display_name"] == "曹恒玮")
        self.assertEqual(cao["orders_actual"], 1)

    def test_person_attribution_uses_entry_person_when_campaign_is_empty(self):
        from dashboard_product.refresh import read
        root = Path(__file__).resolve().parents[1]
        rows = [
            ["2026-09-03", "offline_market", "大学", "TMK", "校园", None, "曹恒玮", "某大学", "大一", "work_orders", 1, None, None, '被动', None],
        ]
        result = project({"result": {"rows": rows}}, {"result": {"rows": []}}, read(root / "config/project_targets.json"), read(PEOPLE_CONFIG_PATH))
        team = next(item for item in result["teams"] if item["team_id"] == "offline_market")
        cao = next(item for item in team["people"] if item["display_name"] == "曹恒玮")
        self.assertEqual(cao["orders_actual"], 1)

    def test_person_attribution_filters_business_group_then_uses_entry_person_for_school_agent(self):
        from dashboard_product.refresh import read
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
        from dashboard_product.refresh import read, remap_tmk_school_agent_team
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
        from dashboard_product.refresh import read
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
        self.assertIn("2026-08|market_total|高中|渠道/顾问暂无法拆分|渠道/顾问暂无法拆分", result["drilldowns"]["current"]["cash"]["channel"])

    def test_notify_sql_remaps_tmk_school_agent_owned_by_offline_roster(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('notify_work_orders.sql', 'notify_cash.sql'):
            query = (root.parent / 'monitoring_product' / 'sql' / name).read_text(encoding='utf-8')
            self.assertIn("TMK激活-平台", query)
            self.assertIn("校代系统资源", query)
            self.assertIn("石仁达", query)
            self.assertIn("THEN 'offline_market'", query)
            for hidden_name in ('王欣庆', '于洋', '李进'):
                self.assertNotIn(hidden_name, query)

    def test_renders_projection_and_unconfigured_values(self):
        group = {
            "display_name": "留学预备",
            "quarter_targets": {"Q1": {"cash": 100, "orders": None}},
            "annual_targets": {"cash": 100, "orders": None},
            "monthly_actuals": {"cash": [42] + [0] * 11, "orders": [12] + [0] * 11},
            "prior_monthly_actuals": {"cash": [40] + [0] * 11, "orders": [10] + [0] * 11},
            "cash_actual": 42,
            "orders_actual": 12,
        }
        yoy = {
            "display_name": "青少",
            "monthly_actuals": {"cash": [42] + [0] * 11, "orders": [12] + [0] * 11},
            "prior_monthly_actuals": {"cash": [40] + [0] * 11, "orders": [10] + [0] * 11},
        }
        artifact = {"schema_version":"dashboard_artifact.v1","artifact_id":"dashboard_test","run_id":"run_dashboard_test","snapshot_id":"snapshot_bi_full_20260902_r2","as_of_date":"2026-09-05","data_through_date":"2026-09-04","created_at":"2026-09-04T08:00:00+00:00","query_results":[],"errors":[],"dashboard":{"months":["2026-06"] * 12,"prior_months":["2025-06"] * 12,"drilldowns":{"current":{"cash":{"channel":{"2026-06|offline_market|留学预备|转介绍|老客转介绍":3},"school_grade":{}},"orders":{"channel":{},"school_grade":{}}},"prior":{"cash":{"channel":{"2025-06|offline_market|留学预备|转介绍|老客转介绍":4},"school_grade":{}},"orders":{"channel":{},"school_grade":{}}}},"teams":[{"team_id":"offline_market","display_name":"线下市场","cash_target":100,"orders_target":None,"groups":[group],"yoy_groups":[yoy],"people":[{"display_name":"王昊","group_name":"青少组","business_group":"留学预备","monthly_targets":{"2026-06":{"orders":10,"cash":1000}},"monthly_actuals":{"cash":[42] + [0] * 11,"orders":[12] + [0] * 11},"monthly_drilldowns":{"2026-06":{"cash":{"转介绍||老客转介绍":42},"orders":{"转介绍||老客转介绍":12}}}}]}]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
            result = render(path)
            page = Path(result["output"]).read_text(encoding="utf-8")
        self.assertIn("FY27 财年", page)
        self.assertIn("Cyber Shackles", page)
        self.assertIn("数据截至 2026-09-04", page)
        self.assertIn("展开下钻", page)
        self.assertIn("drilldowns", page)
        self.assertIn("二级渠道", page)
        self.assertIn("people-panel", page)
        self.assertIn("metric-details", page)
        self.assertIn("业务团队", page)
        self.assertIn("工单渠道", page)
        self.assertIn("现金渠道", page)
        self.assertIn("渠道同比和年级同比按青少、初中、高中、大学", page)
        self.assertIn("渠道同期对比", page)
        self.assertIn('id="channel-matrix"', page)
        self.assertIn("现金占比", page)
        self.assertIn("renderChannelMatrix", page)
        self.assertIn("展开团队", page)
        self.assertNotIn("<th>状态</th>", page)
        self.assertIn("<em>目标</em>", page)
        self.assertIn("<em>完成</em>", page)
        self.assertIn("当期", page)
        self.assertIn("同期", page)
        self.assertNotIn("工单渠道结构", page)
        self.assertIn("未配置", page)
        self.assertIn("snapshot_bi_full_20260902_r2", page)
        self.assertNotIn("duckdb.connect", page)


    def test_youth_and_middle_school_roll_up_to_liuxue_and_keep_four_yoy_groups(self):
        from dashboard_product.refresh import read
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

    def test_render_template_does_not_fill_empty_yoy_groups(self):
        src = (Path(__file__).resolve().parents[1] / "render_template.py").read_text(encoding="utf-8")
        self.assertIn('id="month"', src)
        self.assertIn("const QUARTER_MONTHS", src)
        self.assertIn("function updateMonthOptions(", src)
        self.assertIn("function yoyGroups(team) {", src)
        self.assertIn("return team.yoy_groups || [];", src)
        self.assertNotIn("Array(12).fill(0)", src)
        self.assertNotIn("if (team.yoy_groups && team.yoy_groups.length)", src)

    def test_channel_matrix_and_market_total_team_share_are_client_side(self):
        src = (Path(__file__).resolve().parents[1] / "render_template.py").read_text(encoding="utf-8")
        self.assertIn("function renderChannelMatrix()", src)
        self.assertIn("YOY_GROUP_NAMES = ['青少', '初中', '高中', '大学']", src)
        self.assertIn("rowspan=\"2\">二级渠道", src)
        self.assertIn("右侧合计该渠道全部现金、工单及占总现金占比，按合计现金降序", src)
        self.assertIn("colspan=\"5\">合计", src)
        self.assertIn("class=\"total-row\"><th>总计</th>", src)
        self.assertIn("channelTotal(currentCash, b, matrixGroupNames) - channelTotal(currentCash, a, matrixGroupNames)", src)
        self.assertIn("function capacityPeerKey(row)", src)
        self.assertIn("return 'offline|' + (row.businessGroup || '未分组')", src)
        self.assertIn("item.team_id !== 'market_total'", src)
        self.assertIn("function matrixGroups(team)", src)
        self.assertIn("业务组暂无法拆分", src)
        self.assertIn("展开团队", src)
        self.assertIn("staff_capacity", src)
        self.assertIn("市场人员产能", src)
        self.assertIn("工单数", src)
        self.assertIn("签约量", src)
        self.assertIn("转化率", src)
        self.assertIn("渠道&校代贡献", src)
        self.assertIn("TMK贡献", src)
        self.assertIn("活动贡献", src)
        self.assertIn("CAPACITY_DIMS = [", src)
        self.assertEqual(src.count("{ key:"), 6)
        self.assertIn("renderChannelMatrix(); renderComparison(GRADE, 'grade')", src)
        self.assertIn('href="offline_market_special.html"', src)
        self.assertIn('group.monthly_targets', src)


    def test_online_platform_monthly_targets_from_training_workbook(self):
        from dashboard_product.refresh import project, read
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

    def test_rejects_missing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text(json.dumps({"schema_version":"dashboard_artifact.v1"}), encoding="utf-8")
            with self.assertRaisesRegex(KeyError, "dashboard"):
                render(path)
