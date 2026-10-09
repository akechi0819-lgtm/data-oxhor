"""Existing-vocabulary channel review must not change ownership or totals."""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

from dashboard_product.management.study_abroad_channels import (
    legacy_channel, load_decisions, review,
)
from data_acquisition.jobs.build_study_abroad_warehouse import build
from data_acquisition.jobs.work_order_cleaning import WorkOrderReference
from tests.data_acquisition.test_study_abroad_warehouse import (
    _base_records, _write_workbook, _write_bi_workspace, _write_rosters,
)


def channel_bridge():
    params = [
        {'rule': 'online_root_alias', 'source_values': ['线上运营', '网络'], 'normalized_l1': '网络资源'},
        {'rule': 'newmedia_other_ssc', 'source_value': '新媒体-其他', 'l1': '新媒体', 'l2': 'SSC'},
        {'rule': 'newdongfang_l2_department', 'known_departments': ['大客服', '大学事业部', '国外考试部']},
        {'rule': 'channel_partnership_l2', 'maps': {'分公司个人代理': '个人渠道', '分公司对公合作': '对公渠道（三方）', '留学监理网': '对公渠道（三方）', '异业合作': '其他'}},
        {'rule': 'campaign_personal_agent_cross', 'source_path': '市场活动-高校', 'source_value': '个人代理', 'l1': '渠道合作', 'l2': '个人渠道'},
        {'rule': 'campaign_l2_overlay', 'direct': {'高校活动': '高校活动', '中学活动': '中学活动', '地推': '地推', '市场活动': '高校活动'}, 'collapse_to_综合展': ['信息收集', '条线专展', '部门展', 'F活动邀约']},
        {'rule': 'offline_other_roots_not_in_dashboard', 'maps': {'校代': {'l1': '其他', 'l2': '线下校代'}, '合作': {'l1': '其他', 'l2': '大学事业部合作'}}},
    ]
    return {
        'schema_version': 'company_bridge.v1', 'bridge_id': 'bridge_channel_fixture',
        'bridge_version': '1.7.0', 'company_id': 'company_study_abroad_test',
        'pack_ref': {'pack_id': 'education_training_operations_cn', 'pack_version': '1.0.0'},
        'normalization_rules': [{'target_id': 'acquisition.channel', 'parameters': p} for p in params],
    }


class StudyAbroadChannelTests(unittest.TestCase):
    def setUp(self):
        self.bridge = channel_bridge()
        self.reference = WorkOrderReference({}, {
            ('网络资源-搜索推广乐语', '百度搜索乐语-PC'): '百度',
            ('网络资源-店铺类', '美团点评'): '大众',
        }, {}, {}, {})

    def test_exact_online_vocabulary_and_confirmed_root_alias(self):
        for first in ('网络资源', '网络', '线上运营'):
            with self.subTest(first=first):
                self.assertEqual(('网络资源', '百度', 'matched_existing'),
                                 legacy_channel(first, '搜索推广乐语', '百度搜索乐语-PC', self.bridge, self.reference)[:3])
        self.assertEqual(('网络资源', '大众', 'matched_existing'),
                         legacy_channel('网络资源', '店铺类', '美团点评', self.bridge, self.reference)[:3])
        unknown = legacy_channel('网络资源', '店铺类', '未知平台', self.bridge, self.reference)
        self.assertEqual(('网络资源', None, 'unresolved'), unknown[:3])

    def test_offline_existing_categories_stay_separate(self):
        cases = [
            (('官方合作高校', '', ''), ('官方合作高校', '官方合作高校', 'matched_existing')),
            (('渠道合作', '大客户渠道', '分公司个人代理'), ('渠道合作', '个人渠道', 'matched_existing')),
            (('渠道合作', '大客户渠道', '分公司对公合作'), ('渠道合作', '对公渠道（三方）', 'matched_existing')),
            (('市场活动', '高校', '个人代理'), ('渠道合作', '个人渠道', 'matched_existing')),
            (('市场活动', '高校', '高校活动'), ('市场活动', '高校活动', 'matched_existing')),
            (('市场活动', '综合展', '信息收集'), ('市场活动', '综合展', 'matched_existing')),
            (('新东方学校推荐', '大客服', '点对点'), ('新东方学校推荐', '大客服', 'matched_existing')),
            (('校代', '线下校代', ''), ('其他', '线下校代', 'outside_legacy_scope')),
            (('校代', '线下校代', '线下校代'), ('其他', '线下校代', 'confirmed_new_source')),
            (('合作', '公司合作', ''), ('其他', '大学事业部合作', 'outside_legacy_scope')),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(expected, legacy_channel(*raw, self.bridge, self.reference)[:3])

    def test_explicit_user_decision_resolves_old_implementation_difference(self):
        self.assertEqual(('市场活动', '高校活动', 'confirmed_new_source'),
                         legacy_channel('市场活动', '市场活动', '市场活动', self.bridge, self.reference)[:3])
        self.assertEqual((None, None, 'outside_legacy_scope'),
                         legacy_channel('搜索推广', '百度搜索', '百度搜索-PC', self.bridge, self.reference)[:3])

    def test_standalone_confirmed_bridge_leaves_unknown_combinations_unresolved(self):
        decisions = load_decisions()
        standalone = {'normalization_rules': [
            {**item['proposed_mapping_or_rule'], 'candidate_id': item['candidate_id'], 'status': 'confirmed'}
            for item in decisions['candidates']
            if item['candidate_type'] == 'normalization_rule'
            and 'match_values' in item['proposed_mapping_or_rule'].get('parameters', {})
        ]}
        self.assertEqual((None, None, 'unresolved'), legacy_channel(
            '网络资源', '店铺类', '未确认平台', standalone, self.reference,
            decisions={**decisions, 'candidates': []},
        )[:3])

    def test_meeting_channel_uses_grade_only_when_legacy_l2_is_unresolved(self):
        raw = ('市场活动', '会销/讲座', '会销/讲座')
        college = {
            'second_channel': '高校活动', 'status': 'resolved',
            'work_order_ids': ['WO-COLLEGE'],
        }
        middle = {
            'second_channel': '中学活动', 'status': 'resolved',
            'work_order_ids': ['WO-MIDDLE'],
        }
        self.assertEqual(('市场活动', '高校活动', 'confirmed_new_source'), legacy_channel(
            *raw, self.bridge, self.reference, grade_resolution=college,
        )[:3])
        self.assertEqual(('市场活动', '中学活动', 'confirmed_new_source'), legacy_channel(
            *raw, self.bridge, self.reference, grade_resolution=middle,
        )[:3])

        for status in ('grade_missing', 'grade_conflict'):
            with self.subTest(status=status):
                unresolved = {
                    'second_channel': None, 'status': status,
                    'work_order_ids': ['WO-AMBIGUOUS'],
                }
                self.assertEqual(('市场活动', None, 'unresolved'), legacy_channel(
                    *raw, self.bridge, self.reference, grade_resolution=unresolved,
                )[:3])

        # An already-defined L2 or an exact user rule takes precedence over
        # contextual grade evidence; grade must not alter other channel roots.
        self.assertEqual(('市场活动', '高校活动', 'matched_existing'), legacy_channel(
            '市场活动', '校内活动', '高校活动', self.bridge, self.reference,
            grade_resolution=middle,
        )[:3])
        self.assertEqual(('市场活动', '高校活动', 'confirmed_new_source'), legacy_channel(
            '市场活动', '市场活动', '市场活动', self.bridge, self.reference,
            grade_resolution=middle,
        )[:3])
        self.assertEqual(('网络资源', None, 'unresolved'), legacy_channel(
            '网络资源', '店铺类', '未知平台', self.bridge, self.reference,
            grade_resolution=middle,
        )[:3])

    def test_confirmed_source_decisions_match_exactly_without_brand_wildcards(self):
        cases = [
            (('网络资源', '搜索推广', '小红书品牌号'), ('网络资源', '小红书')),
            (('线上运营', '本地生活平台', '高德地图门店'), ('网络资源', '高德')),
            (('线上运营', '本地生活平台', '大众点评'), ('网络资源', '大众')),
            (('新媒体', '欧亚总部在线', '知乎-付费'), ('新媒体', 'SSC')),
            (('新媒体', '欧亚总部在线', 'B站-免费'), ('新媒体', 'SSC')),
            (('渠道合作', '异业合作', '其他'), ('渠道合作', '个人渠道')),
            (('校代', '线下校代', '线下校代'), ('其他', '线下校代')),
            (('网络资源', '搜索推广乐语', '百度搜索乐语'), ('网络资源', '百度')),
            (('网络资源', '店铺类', '高德地图 田曼萍推荐'), ('网络资源', '高德')),
        ]
        decisions = load_decisions()
        self.assertEqual('company_bridge_candidates.v1', decisions['schema_version'])
        self.assertEqual('confirmed_review', decisions['candidate_set_role'])
        self.assertEqual(11, len(decisions['candidates']))
        self.assertTrue(all(candidate['status'] == 'confirmed'
                            for candidate in decisions['candidates']))
        exact_candidates = [candidate for candidate in decisions['candidates']
                            if 'match_values' in candidate['proposed_mapping_or_rule'].get('parameters', {})]
        self.assertEqual(10, len(exact_candidates))
        self.assertEqual(1, len(decisions['candidates']) - len(exact_candidates))
        for candidate in exact_candidates:
            parameters = candidate['proposed_mapping_or_rule']['parameters']
            self.assertEqual(['first_channel', 'second_channel', 'third_channel'],
                             parameters['source_fields'])
            self.assertEqual(3, len(parameters['match_values']))
        for raw, expected in cases:
            with self.subTest(raw=raw):
                result = legacy_channel(*raw, self.bridge, self.reference, decisions=decisions)
                self.assertEqual((*expected, 'confirmed_new_source'), result[:3])
        self.assertEqual(
            ('网络资源', '小红书', 'confirmed_new_source'),
            legacy_channel('网络资源', '搜索推广', '小红书品牌号', self.bridge, self.reference)[:3],
        )

        for raw in (
            ('网络资源', '搜索推广', '小红书品牌号-未知后缀'),
            ('新媒体', '欧亚总部在线', '知乎-付费-未知后缀'),
            ('网络资源', '店铺类', '高德地图 田曼萍推荐-未知后缀'),
        ):
            with self.subTest(unknown_raw=raw):
                self.assertEqual('unresolved', legacy_channel(
                    *raw, self.bridge, self.reference, decisions=decisions,
                )[2])

    def test_controlled_review_preserves_totals_and_does_not_publish_a_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ws = root / 'workspace'
            _write_bi_workspace(ws)
            # Use the fixture company's actual identity; the old Bridge must match.
            identity_path = ws / 'Work/workspace.json'
            identity = json.loads(identity_path.read_text())
            bridge = {**self.bridge, 'company_id': identity['company_id']}
            people, abroad = _write_rosters(root)
            source = root / 'sample.xlsx'
            _write_workbook(source, _base_records())
            book = load_workbook(source)
            for name, labels in [
                ('资源', ['一级渠道', '二级渠道', '三级渠道']),
                ('留学签约', ['来访类型', '来源渠道', '渠道明细']),
                ('小语种签约', ['来访类型', '渠道来源', '渠道明细']),
            ]:
                sheet = book[name]
                start = sheet.max_column + 1
                for offset, label in enumerate(labels):
                    sheet.cell(1, start + offset, label)
                for row in range(2, sheet.max_row + 1):
                    for offset, value in enumerate(['网络资源', '搜索推广乐语', '百度搜索乐语-PC']):
                        sheet.cell(row, start + offset, value)
            book.save(source)
            book.close()
            (ws / 'Work/Bridge').mkdir()
            bridge_path = ws / 'Work/Bridge/reference.json'
            bridge_path.write_text(json.dumps(bridge, ensure_ascii=False))
            (ws / 'Work/Pack').mkdir()
            shutil.copyfile(Path(__file__).resolve().parents[2] / 'workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json', ws / 'Work/Pack/pack.json')
            reference_path = ws / 'Input/Reference/留学-FY26-资源表.xlsx'
            reference_path.parent.mkdir(parents=True, exist_ok=True)
            ref = Workbook()
            ref.active.append(['一级获取渠道', '二级获取渠道', '三级获取渠道', '矫正-渠道', '矫正-条线', '矫正-意向国家'])
            ref.active.append(['网络资源', '搜索推广乐语', '百度搜索乐语-PC', '百度', '美本', '美国'])
            ref.save(reference_path)
            ref.close()
            config_before, bridge_before = identity_path.read_bytes(), bridge_path.read_bytes()
            decisions = load_decisions()
            decisions['company_id'] = identity['company_id']
            decision_path = root / 'study_abroad_channel_decisions.json'
            decision_path.write_text(json.dumps(decisions, ensure_ascii=False), encoding='utf-8')
            built = build(workspace=ws, source_file=source, run_id='run_channel_source',
                          snapshot_id='snapshot_channel_source', through_date='2026-09-30',
                          people_path=people, abroad_people_path=abroad)
            with patch('dashboard_product.management.study_abroad_channels.load_grade_evidence') as grade_lookup:
                result = review(workspace=ws, snapshot_id=built['snapshot_id'], run_id='run_channel_review',
                                start_date='2026-09-01', end_date='2026-10-01',
                                decision_path=decision_path)
            grade_lookup.assert_not_called()
            review_root = Path(result['review_directory'])
            preview = json.loads((review_root / 'preview_result.json').read_text())
            rows = [dict(zip(preview['columns'], row)) for row in preview['rows']]
            total_rows = [row for row in rows if row['scope'] == 'total']
            self.assertEqual(7, sum(row['resource_count'] for row in total_rows))
            self.assertEqual(Decimal('1145.00'), sum(Decimal(row['gross_signing_amount']) for row in total_rows))
            self.assertEqual({'study_abroad_online', 'study_abroad_offline'},
                             {row['segment_id'] for row in rows if row['scope'] == 'team'})
            self.assertTrue(any(row['mapping_status'] == 'matched_existing'
                                and row['second_channel'] == '百度' for row in rows))
            candidates = json.loads((review_root / 'bridge_candidates.json').read_text())
            self.assertTrue(all(row['status'] == 'proposed' for row in candidates['candidates']))
            confirmed_candidates = json.loads(
                (review_root / 'confirmed_bridge_candidates.json').read_text()
            )
            self.assertEqual('confirmed_review', confirmed_candidates['candidate_set_role'])
            self.assertTrue(confirmed_candidates['candidates'])
            self.assertTrue(all(row['status'] == 'confirmed'
                                for row in confirmed_candidates['candidates']))
            new_bridge = json.loads((review_root / 'confirmed_channel_bridge.json').read_text())
            self.assertEqual('1.2.0', new_bridge['bridge_version'])
            no_decisions = {**decisions, 'candidates': []}
            self.assertEqual(('网络资源', '小红书'), legacy_channel(
                '网络资源', '搜索推广', '小红书品牌号', new_bridge, self.reference,
                decisions=no_decisions,
            )[:2])
            self.assertEqual(('市场活动', '中学活动'), legacy_channel(
                '市场活动', '会销/讲座', '会销/讲座', new_bridge, self.reference,
                decisions=no_decisions,
                grade_resolution={
                    'second_channel': '中学活动', 'status': 'resolved',
                    'work_order_ids': ['WO-MIDDLE'],
                },
            )[:2])

            # A second synthetic Snapshot makes just one resource's market-
            # activity L2 unresolved. The BI grade lookup is mocked so the
            # review proves it requests only that resource and leaves totals intact.
            grade_source = root / 'sample-grade.xlsx'
            shutil.copyfile(source, grade_source)
            grade_book = load_workbook(grade_source)
            grade_resource = grade_book['资源']
            channel_columns = {grade_resource.cell(1, column).value: column
                               for column in range(1, grade_resource.max_column + 1)}
            for label, value in (
                ('一级渠道', '市场活动'),
                ('二级渠道', '会销/讲座'),
                ('三级渠道', '会销/讲座'),
            ):
                grade_resource.cell(2, channel_columns[label], value)
            grade_book.save(grade_source)
            grade_book.close()
            grade_built = build(
                workspace=ws, source_file=grade_source,
                run_id='run_channel_source_grade',
                snapshot_id='snapshot_channel_source_grade',
                through_date='2026-09-30', people_path=people, abroad_people_path=abroad,
            )
            grade_result = {
                'resolution': {
                    '1001': {
                        'second_channel': '中学活动', 'status': 'resolved',
                        'work_order_ids': ['WO-MIDDLE'],
                    },
                },
                'rows': [], 'query_response': None, 'bi_snapshot_id': 'snapshot_bi_grade_fixture',
            }
            with patch(
                'dashboard_product.management.study_abroad_channels.load_grade_evidence',
                return_value=grade_result,
            ) as grade_lookup:
                graded = review(
                    workspace=ws, snapshot_id=grade_built['snapshot_id'],
                    run_id='run_channel_review_grade', start_date='2026-09-01',
                    end_date='2026-10-01', decision_path=decision_path,
                )
            self.assertEqual(['1001'], grade_lookup.call_args.kwargs['resource_ids'])
            grade_preview = json.loads(
                (Path(graded['review_directory']) / 'preview_result.json').read_text()
            )
            grade_rows = [dict(zip(grade_preview['columns'], row)) for row in grade_preview['rows']]
            graded_totals = [row for row in grade_rows if row['scope'] == 'total']
            self.assertEqual(7, sum(row['resource_count'] for row in graded_totals))
            self.assertEqual(Decimal('1145.00'), sum(
                Decimal(row['gross_signing_amount']) for row in graded_totals
            ))
            self.assertTrue(any(
                row['first_channel'] == '市场活动'
                and row['second_channel'] == '中学活动'
                and row['mapping_status'] == 'confirmed_new_source'
                for row in graded_totals
            ))
            self.assertTrue(any(
                row['first_channel'] == '网络资源'
                and row['second_channel'] == '百度'
                and row['mapping_status'] == 'matched_existing'
                for row in graded_totals
            ))
            base_team_segments = {row['segment_id'] for row in rows if row['scope'] == 'team'}
            graded_team_segments = {row['segment_id'] for row in grade_rows if row['scope'] == 'team'}
            self.assertEqual(base_team_segments, graded_team_segments)
            self.assertEqual(
                {segment: sum(row['resource_count'] for row in rows
                              if row['scope'] == 'team' and row['segment_id'] == segment)
                 for segment in base_team_segments},
                {segment: sum(row['resource_count'] for row in grade_rows
                              if row['scope'] == 'team' and row['segment_id'] == segment)
                 for segment in graded_team_segments},
            )
            self.assertEqual(
                {segment: sum(Decimal(row['gross_signing_amount']) for row in rows
                              if row['scope'] == 'team' and row['segment_id'] == segment)
                 for segment in base_team_segments},
                {segment: sum(Decimal(row['gross_signing_amount']) for row in grade_rows
                              if row['scope'] == 'team' and row['segment_id'] == segment)
                 for segment in graded_team_segments},
            )
            self.assertEqual(config_before, identity_path.read_bytes())
            self.assertEqual(bridge_before, bridge_path.read_bytes())
            with self.assertRaisesRegex(ValueError, '已存在'):
                review(workspace=ws, snapshot_id=built['snapshot_id'], run_id='run_channel_review',
                       start_date='2026-09-01', end_date='2026-10-01')


if __name__ == '__main__':
    unittest.main()
