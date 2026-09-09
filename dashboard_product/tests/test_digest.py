import json
import unittest
from datetime import date
from pathlib import Path

from dashboard_product.digest import (
    NOTIFY_CHANNEL_IDS,
    build_all_digests,
    build_digest,
    remaining_workdays,
)
from dashboard_product.notify_render import render_markdown, render_people_html, write_details_xlsx


def _months():
    return [f'2026-{month:02d}' for month in range(6, 13)] + [f'2027-{month:02d}' for month in range(1, 6)]


def _person(name, business_group, group_name, orders=0, cash=0, orders_target=None, cash_target=None):
    targets = {}
    if orders_target is not None or cash_target is not None:
        month = {'orders': orders_target, 'cash': cash_target}
        targets = {'2026-09': {key: value for key, value in month.items() if value is not None}}
    actuals = {'orders': [0, 0, 0, orders] + [0] * 8, 'cash': [0, 0, 0, cash] + [0] * 8}
    return {
        'display_name': name,
        'group_name': group_name,
        'business_group': business_group,
        'monthly_targets': targets,
        'monthly_actuals': actuals,
    }


def _artifact():
    return {
        'schema_version': 'dashboard_artifact.v1',
        'artifact_id': 'dashboard_test',
        'run_id': 'run_notify_test',
        'snapshot_id': 'snap_notify_test',
        'as_of_date': '2026-09-07',
        'data_through_date': '2026-09-06',
        'query_results': [{
            'result': {
                'rows': [
                    ['2026-09-03', 'online_private', '留学预备', '转介绍', '老客', '杨玉林活动', None, '某初中', '初三', 'work_orders', 10],
                    ['2026-09-03', 'online_private', '留学预备', '转介绍', '老客', '杨玉林活动', None, '某初中', '初三', 'passive_reported_cash', 18900],
                    ['2026-09-03', 'online_private', '留学预备', 'TMK', '校园', '校代系统资源活动', '杨玉林', '某初中', '初三', 'work_orders', 1],
                    ['2026-09-03', 'online_private', '留学预备', 'TMK', '校园', None, '杨玉林', '某初中', '初三', 'work_orders', 2],
                    ['2026-09-03', 'online_private', '高中', '直播', '视频号', '勾天瑀直播', '勾天瑀', '某高中', '高一', 'work_orders', 18],
                    ['2026-08-01', 'online_private', '留学预备', '转介绍', '老客', '杨玉林活动', None, '某初中', '初三', 'work_orders', 99],
                    ['2026-09-03', 'offline_market', '留学预备', 'TMK', '校园', '王昊活动', None, '某初中', '初三', 'work_orders', 5],
                    ['2026-09-03', 'offline_market', '高中', 'TMK', '校园', '杨新宇活动', None, '某高中', '高一', 'work_orders', 4],
                    ['2026-09-03', 'offline_market', '大学', 'TMK', '校园', '李进活动', None, '某大学', '大一', 'work_orders', 6],
                ]
            }
        }],
        'dashboard': {
            'months': _months(),
            'teams': [
                {
                    'team_id': 'online_private',
                    'display_name': '线上私域（虚拟人团队）',
                    'people': [
                        _person('杨玉林', '留学预备', '小初提能组', orders=11, cash=18900, orders_target=90, cash_target=150000),
                        _person('王玥', '高中', '高中多途径组'),
                    ],
                },
                {
                    'team_id': 'offline_market',
                    'display_name': '线下市场',
                    'people': [
                        _person('王昊', '留学预备', '青少组', orders=5, cash=0, orders_target=105, cash_target=120000),
                        _person('杨新宇', '高中', '高中组', orders=4, cash=0, orders_target=60),
                        _person('李进', '大学', '大学组', orders=6, cash=0, orders_target=135, cash_target=390000),
                    ],
                },
                {'team_id': 'online_platform', 'display_name': '线上平台', 'people': []},
            ],
        },
    }


class DigestTest(unittest.TestCase):
    def test_remaining_workdays_mid_september(self):
        self.assertEqual(remaining_workdays(date(2026, 9, 7), date(2026, 9, 25)), 15)

    def test_online_private_attribution_and_behind(self):
        digest = build_digest(_artifact(), 'online_private')
        self.assertEqual(digest['perf_month'], '2026-09')
        self.assertEqual(digest['remaining_workdays'], 15)
        self.assertTrue(0.3 < digest['time_progress'] < 0.5)
        self.assertEqual(digest['orders']['attributed'], 13)
        self.assertEqual(digest['orders']['unattributed'], 18)
        self.assertEqual(digest['orders']['total'], 31)
        yang = next(person for person in digest['people'] if person['display_name'] == '杨玉林')
        self.assertEqual(yang['orders_actual'], 11)
        self.assertEqual(yang['orders_target'], 90)
        self.assertTrue(yang['behind'])
        self.assertGreater(yang['daily_orders'], 0)
        wang = next(person for person in digest['people'] if person['display_name'] == '王玥')
        self.assertFalse(wang['behind'])
        self.assertIsNone(wang['daily_orders'])
        self.assertEqual([item['display_name'] for item in digest['behind']], ['杨玉林'])
        attributions = {item['attribution'] for item in digest['order_details']}
        self.assertIn('杨玉林', attributions)
        self.assertIn('未归属', attributions)
        none_campaign = next(item for item in digest['order_details'] if item['campaign_name'] is None)
        self.assertEqual(none_campaign['attribution'], '杨玉林')
        school_agent = next(item for item in digest['order_details'] if item['campaign_name'] == '校代系统资源活动')
        self.assertEqual(school_agent['attribution'], '杨玉林')

    def test_team_isolation(self):
        digest = build_digest(_artifact(), 'online_private')
        blob = json.dumps(digest, ensure_ascii=False)
        self.assertNotIn('王昊', blob)
        self.assertNotIn('offline_market', blob)
        html = render_people_html(digest)
        markdown = render_markdown(digest, '/tmp/people.png', '/tmp/details.xlsx')
        self.assertIn('杨玉林', html)
        self.assertNotIn('王昊', html)
        self.assertNotIn('online_private.html', markdown)
        self.assertNotIn('full.html', markdown)
        self.assertNotIn('未归属', markdown)
        self.assertNotIn('已归属', markdown)
        self.assertNotIn('未归属', html)
        self.assertNotIn('已归属', html)

    def test_all_teams_are_built_from_one_artifact(self):
        digests = build_all_digests(_artifact())
        self.assertEqual([item['team_id'] for item in digests], list(NOTIFY_CHANNEL_IDS))
        platform = next(item for item in digests if item['team_id'] == 'online_platform')
        self.assertEqual(platform['people'], [])
        self.assertEqual(platform['orders']['total'], 0)

    def test_offline_market_splits_into_youth_high_school_university(self):
        youth = build_digest(_artifact(), 'offline_youth')
        high_school = build_digest(_artifact(), 'offline_high_school')
        university = build_digest(_artifact(), 'offline_university')
        self.assertEqual(youth['display_name'], '线下市场·青少')
        self.assertEqual([person['display_name'] for person in youth['people']], ['王昊'])
        self.assertEqual([person['display_name'] for person in high_school['people']], ['杨新宇'])
        self.assertEqual([person['display_name'] for person in university['people']], ['李进'])
        self.assertEqual(youth['orders']['total'], 5)
        self.assertEqual(high_school['orders']['total'], 4)
        self.assertEqual(university['orders']['total'], 6)
        self.assertNotIn('李进', json.dumps(youth, ensure_ascii=False))
        self.assertNotIn('王昊', json.dumps(high_school, ensure_ascii=False))

    def test_xlsx_has_attributed_and_unattributed_sheets(self):
        import tempfile
        digest = build_digest(_artifact(), 'online_private')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'details.xlsx'
            write_details_xlsx(digest, path)
            from openpyxl import load_workbook
            workbook = load_workbook(path)
            self.assertEqual(workbook.sheetnames, ['人员进度', '工单明细', '现金明细'])
            headers = next(workbook['工单明细'].iter_rows(min_row=1, max_row=1, values_only=True))
            self.assertEqual(headers[0], '归属人')
            orders = [row[0] for row in workbook['工单明细'].iter_rows(min_row=2, values_only=True)]
            self.assertIn('杨玉林', orders)
            self.assertIn('未归属', orders)
            people_names = [row[0] for row in workbook['人员进度'].iter_rows(min_row=2, values_only=True)]
            self.assertEqual(people_names, ['杨玉林', '王玥'])
            self.assertNotIn('王昊', people_names)

    def test_warehouse_owner_column_comes_first(self):
        from dashboard_product.digest import ledger_attributions
        from dashboard_product.notify import _pack_warehouse_table
        people = [{'display_name': '杨玉林', 'business_group': '留学预备'}]
        order_columns = ['团队', '年级属性', '年级名称', '活动名称', '资源描述', '资源录入人', 'ID', '姓名']
        order_rows = [
            ['留学预备', None, None, '杨玉林活动', None, None, '1', '学生甲'],
            ['留学预备', None, None, '校代系统资源活动', '市场人员：杨玉林', '别人', '2', '学生乙'],
            ['留学预备', None, None, '无关活动', None, None, '3', '学生丙'],
        ]
        cash_columns = ['团队', '市场活动名称', '工单ID', '学员姓名']
        cash_rows = [
            ['青少', '别的活动', '1', '学生甲'],
            ['青少', '无关现金', '99', '学生丁'],
        ]
        order_owners, cash_owners = ledger_attributions(order_columns, order_rows, cash_columns, cash_rows, people)
        self.assertEqual(order_owners, ['杨玉林', '杨玉林', '未归属'])
        self.assertEqual(cash_owners, ['杨玉林', '未归属'])
        packed = _pack_warehouse_table(order_columns, order_rows, owners=order_owners)
        self.assertEqual(packed['columns'][0], '归属人')
        self.assertEqual(packed['rows'][0][0], '杨玉林')
        self.assertEqual(packed['rows'][2][0], '未归属')


    def test_resource_desc_fallback_covers_typo_campaign_and_embedded_name(self):
        from dashboard_product.refresh import match_person_names
        from dashboard_product.digest import ledger_attributions
        university = ['李进', '师顺盈', '石仁达', '翟昕羽', '曹恒玮']
        high_school = ['谷志文', '于洋', '杨新宇']
        youth = ['王昊', '马澳', '张钦莉']
        ding = match_person_names(
            university,
            '2026.09.02-DX-刚需纳新-【本地】双非活动资源-天财豆蔻学姐号微信推广-曹恒为玮-线上雅思行地推',
            '曹恒玮',
            '此客户在2026.09.02-DX-刚需纳新-【本地】双非活动资源-天财豆蔻学姐号微信推广-曹恒为玮-线上雅思行地推活动中已签到,客户类型为新客户 曹恒玮市场资源-B类，按市场顺序分李艳婵，备注：丁槟槟',
        )
        yao = match_person_names(
            university,
            None,
            '杜晓蕾',
            'TMK激活分配产生的资源；tmk微信咨询-天财广告牌进资-杜晓蕾/曹恒玮-线下雅思行',
        )
        liu = match_person_names(
            university,
            None,
            '刘炫麟',
            'TMK激活分配产生的资源；杜晓蕾暂时不需要，发学习资料2026.06.16-HGK-其他-【本地】毛坯-异业渠道L推荐后高考资源-师顺盈-线下渠道推荐 外呼主题：批量导入-TMK汪洋录入20260617加微返打',
        )
        school_agent = match_person_names(university, '2027财年第4财月91校代系统资源活动', '彭仪静', '市场人员：李进 备注：校代推荐')
        self.assertEqual(ding, ['曹恒玮'])
        self.assertEqual(yao, ['曹恒玮'])
        self.assertEqual(liu, [])
        self.assertEqual(school_agent, ['李进'])
        self.assertEqual(match_person_names(high_school, None, '别人', '市场人员：杨新宇 备注：高中外展'), ['杨新宇'])
        self.assertEqual(match_person_names(youth, '无关活动', '王昊', None), ['王昊'])
        people = [
            {'display_name': '曹恒玮', 'business_group': '大学'},
            {'display_name': '师顺盈', 'business_group': '大学'},
            {'display_name': '杨新宇', 'business_group': '高中'},
        ]
        order_columns = ['团队', '年级属性', '年级名称', '活动名称', '资源描述', '资源录入人', 'ID', '姓名']
        order_rows = [
            ['大学', None, None, '2026.09.02-DX-曹恒为玮-线上雅思行地推', '曹恒玮市场资源-B类', '曹恒玮', '34722714', '丁槟槟'],
            ['大学', None, None, None, 'tmk微信咨询-天财广告牌进资-杜晓蕾/曹恒玮-线下雅思行', '杜晓蕾', '34858734', '姚志诚'],
            ['大学', None, None, None, '发学习资料2026.06.16-HGK-其他-【本地】毛坯-异业渠道L推荐后高考资源-师顺盈-线下渠道推荐 外呼主题：批量导入', '刘炫麟', '34811640', '刘家长'],
            ['高中', None, None, None, '市场人员：杨新宇 备注：外展', '别人', 'hs1', '高中生'],
            ['高中', None, None, '2026.08.29-DX-仁爱新生外展-翟昕羽-线下雅思行地推', '此客户在活动中已签到', '翟昕羽', '34602589', '李耀华1'],
        ]
        cash_columns = ['团队', '市场活动名称', '工单ID', '学员姓名']
        cash_rows = [
            ['大学', '别的活动', '34722714', '丁槟槟'],
            ['大学', '无关现金', '34811640', '刘家长'],
        ]
        order_owners, cash_owners = ledger_attributions(order_columns, order_rows, cash_columns, cash_rows, people)
        self.assertEqual(order_owners, ['曹恒玮', '曹恒玮', '未归属', '杨新宇', '未归属'])
        self.assertEqual(cash_owners, ['曹恒玮', '未归属'])

    def test_apply_warehouse_actuals_uses_owner_counts(self):
        from dashboard_product.digest import apply_warehouse_actuals
        digest = {
            'time_progress': 0.5,
            'remaining_workdays': 10,
            'people': [{
                'display_name': '杨玉林', 'business_group': '留学预备',
                'orders_target': 90, 'orders_actual': 10, 'orders_completion': 10/90,
                'cash_target': 150000, 'cash_actual': 0, 'cash_completion': None,
                'expected_orders': 45, 'orders_gap': 35, 'remaining_orders': 80,
                'daily_orders': 8, 'behind': True,
            }],
            'behind': [],
            'warehouse': {
                'orders': {'columns': ['归属人', 'ID'], 'rows': [['杨玉林', '1'], ['杨玉林', '2'], ['未归属', '3']]},
                'cash': {'columns': ['归属人', '报入现金收入'], 'rows': [['杨玉林', '1000'], ['未归属', '9']]},
            },
        }
        apply_warehouse_actuals(digest)
        person = digest['people'][0]
        self.assertEqual(person['orders_actual'], 2)
        self.assertEqual(person['cash_actual'], 1000)


REAL_ARTIFACT = (
    Path(__file__).resolve().parents[2]
    / 'customers/bi_operations/Output/Dashboard/run_dashboard_20260907_101900/artifact.json'
)


@unittest.skipUnless(REAL_ARTIFACT.exists(), 'no local September 7 artifact')
class RealArtifactDigestTest(unittest.TestCase):
    def test_online_private_september_counts(self):
        artifact = json.loads(REAL_ARTIFACT.read_text(encoding='utf-8'))
        digest = build_digest(artifact, 'online_private')
        self.assertEqual(digest['perf_month'], '2026-09')
        self.assertEqual(digest['remaining_workdays'], 15)
        self.assertEqual(digest['orders']['total'], 29)
        self.assertEqual(digest['orders']['attributed'], 11)
        self.assertEqual(digest['orders']['unattributed'], 18)
        yang = next(person for person in digest['people'] if person['display_name'] == '杨玉林')
        self.assertEqual(yang['orders_actual'], 10)
        self.assertEqual(yang['orders_target'], 90)
        self.assertTrue(yang['behind'])
        names = {person['display_name'] for person in digest['people']}
        self.assertTrue({'杨玉林', '王玥', '许萌', '高勃然'} <= names)
        self.assertNotIn('王昊', json.dumps(digest, ensure_ascii=False))
