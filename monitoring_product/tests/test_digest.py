import json
import unittest
from datetime import date
from pathlib import Path

from monitoring_product.digest import (
    NOTIFY_CHANNEL_IDS,
    build_all_digests,
    build_digest,
    ensure_roster,
    remaining_workdays,
)
from monitoring_product.notify_render import render_markdown, render_people_html, write_details_xlsx


class DigestTest(unittest.TestCase):
    def test_remaining_workdays_mid_september(self):
        self.assertEqual(remaining_workdays(date(2026, 9, 7), date(2026, 9, 25)), 15)






    def test_warehouse_owner_column_comes_first(self):
        from monitoring_product.digest import ledger_attributions
        from monitoring_product.notify import _pack_warehouse_table
        people = [{'display_name': '潘体学', 'business_group': '留学预备'}]
        order_columns = ['团队', '年级属性', '年级名称', '活动名称', '资源描述', '资源录入人', 'ID', '姓名']
        order_rows = [
            ['留学预备', None, None, '潘体学活动', None, None, '1', '学生甲'],
            ['留学预备', None, None, '校代系统资源活动', '市场人员：潘体学', '别人', '2', '学生乙'],
            ['留学预备', None, None, '无关活动', None, None, '3', '学生丙'],
        ]
        cash_columns = ['团队', '市场活动名称', '工单ID', '学员姓名']
        cash_rows = [
            ['青少', '别的活动', '1', '学生甲'],
            ['青少', '无关现金', '99', '学生丁'],
        ]
        order_owners, cash_owners = ledger_attributions(order_columns, order_rows, cash_columns, cash_rows, people)
        self.assertEqual(order_owners, ['潘体学', '潘体学', '未归属'])
        self.assertEqual(cash_owners, ['潘体学', '未归属'])
        packed = _pack_warehouse_table(order_columns, order_rows, owners=order_owners)
        self.assertEqual(packed['columns'][0], '归属人')
        self.assertEqual(packed['rows'][0][0], '潘体学')
        self.assertEqual(packed['rows'][2][0], '未归属')


    def test_resource_desc_fallback_covers_typo_campaign_and_embedded_name(self):
        from workspace_modeling.operations.personnel import match_person_names
        from monitoring_product.digest import ledger_attributions
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

    def test_cash_inherits_from_full_warehouse_orders_not_just_this_month(self):
        from monitoring_product.digest import ledger_attributions, missing_cash_order_ids
        people = [
            {'display_name': '师顺盈', 'business_group': '大学'},
            {'display_name': '翟昕羽', 'business_group': '大学'},
            {'display_name': '刘彬', 'business_group': '高中'},
        ]
        order_columns = ['团队', '年级属性', '年级名称', '活动名称', '资源描述', '资源录入人', 'ID', '姓名']
        order_rows = [
            ['大学', None, None, '本月师顺盈活动', None, None, '1', '本月生'],
        ]
        extra_columns = order_columns
        extra_rows = [
            ['大学', None, None, '2026.08.17-师顺盈-线上雅思行讲座', None, '杜晓蕾', '34587495', '王家昱'],
            ['大学', None, None, '2027财年第3财月91校代系统资源活动', '市场人员：翟昕羽 备注：渠道推荐', '刘炫麟', '34570085', '李晨曦'],
            ['高中', None, None, '2027财年第2财月91校代系统资源活动', '市场人员：刘彬 备注：咨询sat', '李鑫', '33619709', '胡维杨'],
            ['大学', None, None, '无关历史活动', None, None, '34500000', '未匹配生'],
        ]
        cash_columns = ['团队', '市场活动名称', '工单ID', '学员姓名']
        cash_rows = [
            ['大学', '别的活动', '1', '本月生'],
            ['大学', '现金活动名里没有人', '34587495', '王家昱'],
            ['大学', '2027财年第3财月91校代系统资源活动', '34570085', '李晨曦'],
            ['高中', '校代活动', '33619709', '胡维杨'],
            ['大学', '师顺盈讲座', '34500000', '未匹配生'],
            ['大学', '师顺盈讲座', '999', '仓里没有'],
            ['大学', '无关现金', None, '无工单'],
        ]
        self.assertEqual(
            missing_cash_order_ids(order_columns, order_rows, cash_columns, cash_rows),
            ['34587495', '34570085', '33619709', '34500000', '999'],
        )
        _, cash_owners = ledger_attributions(
            order_columns, order_rows, cash_columns, cash_rows, people,
            extra_order_columns=extra_columns, extra_order_rows=extra_rows,
        )
        self.assertEqual(cash_owners, [
            '师顺盈',
            '师顺盈',
            '翟昕羽',
            '刘彬',
            '未归属',
            '师顺盈',
            '未归属',
        ])

    def test_historical_order_is_judged_again_for_cash(self):
        from monitoring_product.digest import ensure_roster, ledger_attributions
        digest = {
            'team_id': 'offline_high_school',
            'perf_month': '2026-09',
            'time_progress': 0.4,
            'remaining_workdays': 15,
            'people': [{
                'display_name': '杨新宇', 'business_group': '高中', 'group_name': '高中组',
                'orders_target': 60, 'orders_actual': 0, 'behind': True,
            }],
            'behind': [],
        }
        people_config = {
            'teams': [{
                'team_id': 'offline_market',
                'groups': [{
                    'display_name': '高中组',
                    'members': [
                        {'display_name': '杨新宇', 'status': 'active', 'business_group': '高中'},
                        {'display_name': '刘彬', 'status': 'active', 'business_group': '高中'},
                    ],
                }],
            }]
        }
        digest = ensure_roster(digest, people_config, months=['2026-09'])
        names = [person['display_name'] for person in digest['people']]
        self.assertEqual(names, ['杨新宇', '刘彬'])
        from monitoring_product.digest import ledger_attributions
        order_columns = ['团队', '年级属性', '年级名称', '活动名称', '资源描述', '资源录入人', 'ID']
        cash_columns = ['团队', '市场活动名称', '工单ID']
        _, cash_owners = ledger_attributions(
            order_columns, [], cash_columns,
            [['高中', '校代活动没有人名', '33619709']],
            digest['people'],
            extra_order_columns=order_columns,
            extra_order_rows=[[
                '高中', None, None, '2027财年第2财月91校代系统资源活动',
                '市场人员：刘彬 备注：咨询sat', '李鑫', '33619709',
            ]],
        )
        self.assertEqual(cash_owners, ['刘彬'])

    def test_ensure_roster_replaces_departed_names_from_people_config(self):
        digest = {
            'team_id': 'online_private',
            'perf_month': '2026-09',
            'time_progress': 0.4,
            'remaining_workdays': 15,
            'people': [{
                'display_name': '杨玉林', 'business_group': '留学预备', 'group_name': '小初提能组',
                'orders_target': 90, 'orders_actual': 10, 'behind': True,
            }],
            'behind': [],
        }
        people_config = {
            'teams': [{
                'team_id': 'online_private',
                'groups': [{
                    'display_name': '小初提能组',
                    'members': [{
                        'display_name': '潘体学',
                        'status': 'active',
                        'business_group': '留学预备',
                        'monthly_targets': {'2026-09': {'orders': 25, 'cash': 50000}},
                    }],
                }],
            }]
        }
        digest = ensure_roster(digest, people_config, months=['2026-09'])
        names = [person['display_name'] for person in digest['people']]
        self.assertEqual(names, ['潘体学'])
        self.assertEqual(digest['people'][0]['orders_target'], 25)
        self.assertEqual(digest['people'][0]['cash_target'], 50000)
        self.assertNotIn('杨玉林', names)

    def test_apply_warehouse_actuals_uses_owner_counts(self):

        from monitoring_product.digest import apply_warehouse_actuals
        digest = {
            'time_progress': 0.5,
            'remaining_workdays': 10,
            'people': [{
                'display_name': '潘体学', 'business_group': '留学预备',
                'orders_target': 90, 'orders_actual': 10, 'orders_completion': 10/90,
                'cash_target': 150000, 'cash_actual': 0, 'cash_completion': None,
                'expected_orders': 45, 'orders_gap': 35, 'remaining_orders': 80,
                'daily_orders': 8, 'behind': True,
            }],
            'behind': [],
            'warehouse': {
                'orders': {'columns': ['归属人', 'ID'], 'rows': [['潘体学', '1'], ['潘体学', '2'], ['未归属', '3']]},
                'cash': {'columns': ['归属人', '报入现金收入'], 'rows': [['潘体学', '1000'], ['未归属', '9']]},
            },
        }
        apply_warehouse_actuals(digest)
        person = digest['people'][0]
        self.assertEqual(person['orders_actual'], 2)
        self.assertEqual(person['cash_actual'], 1000)
        self.assertEqual(person['heads_actual'], 0)
        self.assertTrue(person['behind'])


    def test_count_heads_distinct_student_and_split_shared_row(self):
        from monitoring_product.digest import apply_warehouse_actuals, count_heads_by_owner
        cash = {
            'columns': ['归属人', '学员编号', '报入现金收入'],
            'rows': [
                ['李进', 'S1', '13000'],
                ['李进', 'S1', '8000'],
                ['李进、师顺盈', 'S2', '15000'],
                ['师顺盈', '', '9000'],
                ['未归属', 'S3', '12000'],
                ['石仁达、翟昕羽、曹恒玮', 'S4', '11000'],
            ],
        }
        counts = count_heads_by_owner(cash)
        self.assertEqual(counts['李进'], 1.5)
        self.assertEqual(counts['师顺盈'], 0.5)
        self.assertNotIn('未归属', counts)
        self.assertAlmostEqual(counts['石仁达'], 1 / 3)
        self.assertAlmostEqual(counts['翟昕羽'], 1 / 3)
        self.assertAlmostEqual(counts['曹恒玮'], 1 / 3)
        digest = {
            'time_progress': 0.5,
            'remaining_workdays': 10,
            'secondary_metric': 'heads',
            'people': [{
                'display_name': '李进', 'business_group': '大学',
                'orders_target': 135, 'orders_actual': 30, 'orders_completion': 30 / 135,
                'heads_target': 30, 'heads_actual': 0, 'heads_completion': None,
                'cash_target': 390000, 'cash_actual': 0, 'cash_completion': None,
                'expected_orders': 67.5, 'orders_gap': 37.5, 'remaining_orders': 105,
                'daily_orders': 10.5, 'behind': True,
            }],
            'behind': [],
            'warehouse': {
                'orders': {'columns': ['归属人', 'ID'], 'rows': [['李进', '1']] * 80},
                'cash': cash,
            },
        }
        apply_warehouse_actuals(digest)
        person = digest['people'][0]
        self.assertEqual(person['heads_actual'], 1.5)
        self.assertEqual(person['heads_completion'], 1.5 / 30)
        self.assertEqual(person['orders_actual'], 80)
        self.assertFalse(person['behind'])


class MappingTest(unittest.TestCase):
    def test_cash_middle_school_rolls_to_liuxue(self):
        from monitoring_product.digest import mapped_cash_business_group, mapped_order_business_group, mapped_order_yoy_group
        self.assertEqual(mapped_cash_business_group('初中'), '留学预备')
        self.assertEqual(mapped_cash_business_group('初中国际学科'), '留学预备')
        self.assertEqual(mapped_cash_business_group('ICC'), '高中')
        self.assertEqual(mapped_cash_business_group('高中'), '高中')
        self.assertEqual(mapped_order_yoy_group('留学预备', '青少顾问', '六年级'), '青少')
        self.assertEqual(mapped_order_yoy_group('留学预备', '初中顾问', '一年级'), '初中')
        self.assertEqual(mapped_order_yoy_group('留学预备', None, '五年级'), '青少')
        self.assertEqual(mapped_order_yoy_group('留学预备', None, '六年级'), '初中')
        self.assertEqual(mapped_order_yoy_group('留学预备', '武清顾问', '未知'), '大学')
        self.assertEqual(mapped_order_yoy_group('留学预备', '塘沽顾问', '7年级（初一）'), '初中')
        self.assertEqual(mapped_order_business_group('留学预备', None, None, '初中顾问', '一年级'), '留学预备')
        self.assertEqual(mapped_order_yoy_group(None, None, '四年级', '张艺彤'), '青少')
        self.assertEqual(mapped_order_yoy_group('', None, '六年级', '张艺彤'), '初中')
        self.assertEqual(mapped_order_yoy_group('无法判断', None, '五年级', '张艺彤'), '青少')
        self.assertIsNone(mapped_order_yoy_group(None, None, '四年级', '王新源'))
        self.assertIsNone(mapped_order_yoy_group(None, None, '四年级'))
        self.assertEqual(mapped_order_business_group(None, None, None, None, '四年级', '张艺彤'), '留学预备')
