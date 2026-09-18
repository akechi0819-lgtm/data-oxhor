from workspace_modeling.operations.personnel import PEOPLE_CONFIG_PATH
import unittest
from pathlib import Path

from dashboard_product.capacity import (
    ANNUAL_CASH_CAPACITY,
    annual_cash_capacity,
    cash_contribution_bucket,
)
from dashboard_product.refresh import project, read, render


ROOT = Path(__file__).resolve().parents[1]


class CapacityBucketTest(unittest.TestCase):
    def test_classifies_partner_tmk_and_campaign(self):
        self.assertEqual(cash_contribution_bucket('市场活动', '异业渠道'), 'partner')
        self.assertEqual(cash_contribution_bucket('市场活动', '线下校代'), 'partner')
        self.assertEqual(cash_contribution_bucket('TMK激活', '入库返打'), 'tmk')
        self.assertEqual(cash_contribution_bucket('TMK激活-市场活动', '异业渠道'), 'tmk')
        self.assertEqual(cash_contribution_bucket('市场活动', '展会'), 'campaign')
        self.assertEqual(cash_contribution_bucket('市场活动', '地推'), 'campaign')
        self.assertEqual(cash_contribution_bucket('平台', '虚拟人'), 'other')
        self.assertEqual(cash_contribution_bucket('暂无归属', '暂无归属'), 'other')

    def test_uniform_annual_capacity_is_800000(self):
        self.assertEqual(ANNUAL_CASH_CAPACITY, 800000)
        self.assertEqual(annual_cash_capacity(read(ROOT / 'config/capacity_targets.json')), 800000)


class CapacityProjectionTest(unittest.TestCase):
    def test_projects_heads_and_six_dim_cash_mix(self):
        rows = [
            ['2026-09-03', 'offline_market', '青少', '市场活动', '异业渠道', '王昊活动', None, '学校', '一年级', 'work_orders', 10, None],
            ['2026-09-03', 'offline_market', '青少', '市场活动', '异业渠道', '王昊活动', None, '学校', '一年级', 'passive_reported_cash', 10000, 'S1'],
            ['2026-09-03', 'offline_market', '青少', 'TMK激活', '入库返打', '王昊活动', None, '学校', '一年级', 'passive_reported_cash', 20000, 'S2'],
            ['2026-09-03', 'offline_market', '青少', '市场活动', '展会', '王昊活动', None, '学校', '一年级', 'passive_reported_cash', 30000, 'S1'],
            ['2026-09-03', 'offline_market', '青少', '平台', '大众点评', '王昊活动', None, '学校', '一年级', 'passive_reported_cash', 40000, 'S3'],
        ]
        result = project(
            {'result': {'rows': rows}},
            {'result': {'rows': []}},
            read(ROOT / 'config/project_targets.json'),
            read(PEOPLE_CONFIG_PATH),
            read(ROOT / 'config/capacity_targets.json'),
        )
        team = next(item for item in result['teams'] if item['team_id'] == 'offline_market')
        person = next(item for item in team['people'] if item['display_name'] == '王昊')
        self.assertEqual(person['orders_actual'], 10)
        self.assertEqual(person['cash_actual'], 100000)
        self.assertEqual(person['heads_actual'], 3)
        self.assertEqual(person['annual_cash_capacity'], 800000)
        self.assertEqual(person['line'], 'offline')
        self.assertEqual(person['cash_contributions']['partner'], 10000)
        self.assertEqual(person['cash_contributions']['tmk'], 20000)
        self.assertEqual(person['cash_contributions']['campaign'], 30000)
        self.assertEqual(person['cash_contributions']['other'], 40000)

    def test_shared_student_splits_headcount(self):
        people = {
            'teams': [{
                'team_id': 'offline_market',
                'groups': [{
                    'display_name': '青少组',
                    'members': [
                        {'display_name': '王昊', 'status': 'active', 'business_group': '留学预备'},
                        {'display_name': '马澳', 'status': 'active', 'business_group': '留学预备'},
                    ],
                }],
            }]
        }
        rows = [
            ['2026-09-03', 'offline_market', '青少', '市场活动', '展会', '王昊马澳活动', None, '学校', '一年级', 'passive_reported_cash', 8000, 'S9'],
        ]
        result = project(
            {'result': {'rows': rows}},
            {'result': {'rows': []}},
            read(ROOT / 'config/project_targets.json'),
            people,
        )
        team = next(item for item in result['teams'] if item['team_id'] == 'offline_market')
        by_name = {item['display_name']: item for item in team['people']}
        self.assertEqual(by_name['王昊']['heads_actual'], 0.5)
        self.assertEqual(by_name['马澳']['heads_actual'], 0.5)

    def test_render_keeps_six_radar_dimensions(self):
        src = (ROOT / 'render_template.py').read_text(encoding='utf-8')
        labels = ['工单数', '签约量', '转化率', '渠道&校代贡献', 'TMK贡献', '活动贡献']
        for label in labels:
            self.assertIn(label, src)
        self.assertIn("key: 'orders'", src)
        self.assertIn("key: 'heads'", src)
        self.assertIn("key: 'conversion'", src)
        self.assertIn("key: 'partner'", src)
        self.assertIn("key: 'tmk'", src)
        self.assertIn("key: 'campaign'", src)
        self.assertEqual(src.count('{ key:'), 6)
        self.assertIn('市场人员产能</button>', src)
        self.assertIn('function capacityPeerKey(row)', src)
        self.assertIn("offline_market') return 'offline|'", src)
        self.assertIn('线上私域整队一个均值', src)


if __name__ == '__main__':
    unittest.main()
