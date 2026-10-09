"""Business rules for the monthly personnel contribution view."""
from __future__ import annotations

import copy
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from dashboard_product.management.personnel_contribution import (
    DEFAULT_ORDER_STATUS_MODE,
    ORDER_STATUS_MODES,
    build_contribution,
    load_sources,
)


def member(name, group='大学', targets=None, status='active'):
    return {
        'display_name': name,
        'status': status,
        'business_group': group,
        'monthly_targets': targets or {},
    }


def rosters(training=(), online=(), abroad=()):
    teams = []
    if training:
        teams.append({
            'team_id': 'offline_market',
            'groups': [{'display_name': '大学组', 'members': list(training)}],
        })
    if online:
        teams.append({
            'team_id': 'online_private',
            'groups': [{'display_name': '大学组', 'members': list(online)}],
        })
    return {'teams': teams}, {'people': list(abroad)}


def sources(*, resources=(), contracts=(), languages=(), transfers=(),
            resources_connected=True, transfers_connected=True):
    return {
        'resources': list(resources),
        'contracts': list(contracts),
        'languages': list(languages),
        'transfers': list(transfers),
        'resources_connected': resources_connected,
        'transfers_connected': transfers_connected,
        'source_hashes': {},
    }


def resource(rid, day, owner, status='正常', campaign='', consultation_type='留学'):
    return {
        'resource_id': rid, 'date': day, 'owner': owner, 'status': status,
        'campaign': campaign, 'consultation_type': consultation_type, 'source_row_number': 2,
    }


def contract(rid, contract_id, month, owner, amount, archive_date, campaign=''):
    return {
        'resource_id': rid, 'contract_id': contract_id, 'month': month,
        'owner': owner, 'amount': amount, 'campaign': campaign,
        'archive_date': archive_date, 'source_row_number': 2,
    }


def language(rid, work_order_id, day, owner, amount):
    return {
        'resource_id': rid, 'work_order_id': work_order_id, 'date': day,
        'owner': owner, 'amount': amount, 'source_row_number': 2,
    }


def transfer(rid, tag, campaign, day='2026-09-10', row=2):
    return {
        'resource_id': rid, 'tag': tag, 'campaign': campaign,
        'date': day, 'source_row_number': row,
    }


def bi_fact(fid, line, metric, day, value, work_order_id, source_row_number=2,
            order_status=None):
    row = {
        'fact_id': fid, 'business_line': line, 'metric': metric,
        'event_date': day, 'value': value, 'work_order_id': work_order_id,
        'source_row_number': source_row_number,
    }
    if order_status is not None:
        row['order_status'] = order_status
    return row


def order_row(work_order_id, rid, campaign, entry_person='', description='', source_row_number=2,
              order_status=None):
    row = {
        'work_order_id': work_order_id, 'resource_id': rid,
        'campaign_name': campaign, 'resource_entry_person': entry_person,
        'resource_description': description, 'source_row_number': source_row_number,
    }
    if order_status is not None:
        row['order_status'] = order_status
    return row


def targets_for(monthly):
    return {'orders_start': '2026-06-01', 'orders_end': '2026-09-30',
            'cash_start': '2026-06-01', 'cash_end': '2026-09-30'}


def rows_for(result, month):
    period = next(row for row in result['periods'] if row['id'] == month)
    return period, {row['name']: row for row in period['people']}


class PersonnelContributionTests(unittest.TestCase):
    def test_bidirectional_double_split_and_natural_month_amounts(self):
        training_targets = {
            '2026-08': {'orders': 2, 'cash': 200},
            '2026-09': {'orders': 4, 'cash': 2000},
        }
        abroad_targets = {
            '2026-08': {'orders': 4, 'cash': 4000},
            '2026-09': {'orders': 6, 'cash': 5000},
        }
        people, abroad_people = rosters(
            training=[member('语培甲', targets=training_targets)],
            abroad=[member('留学乙', targets=abroad_targets)],
        )
        facts = [
            bi_fact('training-aug-order', 'training', 'orders', '2026-08-20', 1, 'wo-aug'),
            bi_fact('training-aug-cash', 'training', 'cash', '2026-08-20', 100, 'wo-aug'),
            bi_fact('training-sep-order', 'training', 'orders', '2026-09-12', 1, 'wo-sep'),
            bi_fact('training-sep-cash', 'training', 'cash', '2026-09-12', 200, 'wo-sep'),
        ]
        # BI may contain many study-abroad facts. The new page takes those records
        # from its own workbook and must ignore the BI copies.
        facts.extend(
            bi_fact(f'bi-abroad-{i}', 'abroad', 'orders', '2026-09-15', 1000, f'foreign-{i}')
            for i in range(20)
        )
        original_facts = copy.deepcopy(facts)
        order_rows = [
            order_row('wo-aug', '1001', '语培甲（留学乙）', '语培甲'),
            order_row('wo-sep', '1002', '留学乙（语培甲）', '留学乙'),
        ]
        source_rows = sources(
            resources=[
                # This resource was assigned in August; its September contract
                # still belongs to September by its archive month.
                resource('1001', '2026-08-15', '语培甲'),
                resource('1002', '2026-09-03', '留学乙'),
                resource('1004', '2026-09-10', '语培甲'),
            ],
            contracts=[
                contract('1001', 'C-1001', '2026-09', '语培甲', 300, '2026-09-16'),
                contract('1002', 'C-1002', '2026-09', '留学乙', 500, '2026-09-18'),
            ],
            languages=[language('1003', 'L-1003', '2026-09-20', '留学乙', 700)],
            transfers=[
                transfer('1001', '双分', '语培甲（留学乙）', '2026-08-15', 2),
                transfer('1002', '双分', '留学乙（语培甲）', '2026-09-03', 3),
                transfer('1003', '双分', '留学乙（语培甲）', '2026-09-20', 4),
                transfer('1004', '双分', '语培甲（留学乙）', '2026-09-10', 5),
            ],
        )
        original_sources = copy.deepcopy(source_rows)

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-08', '2026-09'], targets_for(None),
        )

        self.assertEqual(facts, original_facts)
        self.assertEqual(source_rows, original_sources)
        august, august_people = rows_for(result, '2026-08')
        self.assertEqual(august_people['语培甲']['self']['orders'], 1)
        self.assertEqual(august_people['语培甲']['output']['orders'], 0.5)
        self.assertEqual(august_people['留学乙']['received']['orders'], 0.5)
        self.assertEqual(august_people['语培甲']['targets']['orders'], 2)
        self.assertEqual(august_people['语培甲']['completion']['orders'], 0.5)
        self.assertEqual(august_people['语培甲']['self_rate']['orders'], 1)
        self.assertEqual(august['coverage']['abroad']['orders_through'], '2026-08-15')

        september, september_people = rows_for(result, '2026-09')
        training = september_people['语培甲']
        abroad = september_people['留学乙']
        # Reverse split: the abroad owner receives half of the training order;
        # the training owner receives half of the abroad resource.
        self.assertEqual(training['self']['orders'], 0)
        self.assertEqual(training['received']['orders'], 0.5)
        self.assertEqual(training['output']['orders'], 0.5)
        self.assertEqual(training['own_total']['orders'], 0.5)
        self.assertEqual(training['created_total']['orders'], 0.5)
        self.assertEqual(training['targets']['orders'], 4)
        self.assertEqual(training['completion']['orders'], 0.125)
        self.assertEqual(training['self_rate']['orders'], 0)
        self.assertEqual(abroad['self']['orders'], 1)
        self.assertEqual(abroad['received']['orders'], 0.5)
        self.assertEqual(abroad['output']['orders'], 0.5)
        self.assertEqual(abroad['own_total']['orders'], 1.5)
        self.assertEqual(abroad['created_total']['orders'], 1.5)
        self.assertEqual(abroad['targets']['orders'], 6)
        self.assertAlmostEqual(abroad['completion']['orders'], 0.25)
        self.assertAlmostEqual(abroad['self_rate']['orders'], 2 / 3)

        # BI cash follows the same split weights. Contract cash uses its archive
        # month even for an older resource; language cash uses its business date.
        self.assertEqual(training['self']['cash'], 0)
        self.assertEqual(training['received']['cash'], 100)
        self.assertEqual(training['output']['cash'], 150)
        self.assertEqual(training['own_total']['cash'], 100)
        self.assertEqual(training['created_total']['cash'], 150)
        self.assertEqual(training['targets']['cash'], 2000)
        self.assertAlmostEqual(training['completion']['cash'], 0.05)
        self.assertEqual(training['self_rate']['cash'], 0)
        self.assertEqual(abroad['self']['cash'], 1200)
        self.assertEqual(abroad['received']['cash'], 150)
        self.assertEqual(abroad['output']['cash'], 100)
        self.assertEqual(abroad['own_total']['cash'], 1350)
        self.assertEqual(abroad['created_total']['cash'], 1300)
        self.assertEqual(abroad['targets']['cash'], 5000)
        self.assertAlmostEqual(abroad['completion']['cash'], 0.27)
        self.assertAlmostEqual(abroad['self_rate']['cash'], 1200 / 1350)
        self.assertEqual(september['coverage']['abroad']['cash_through'], '2026-09-20')
        old_resource_contract = next(
            row for row in details['records']
            if row['source'] == 'contracts' and row['key'] == 'contracts:C-1001'
            and row['person'] == '语培甲'
        )
        self.assertEqual(old_resource_contract['month'], '2026-09')
        self.assertEqual(old_resource_contract['credited_value'], '150.0')

    def test_abroad_and_small_language_scopes_split_source_events(self):
        training_targets = {'2026-09': {'orders': 4, 'cash': 2000}}
        abroad_targets = {'2026-09': {'orders': 10, 'cash': 1000}}
        people, abroad_people = rosters(
            training=[member('语培甲', targets=training_targets)],
            abroad=[member('留学乙', targets=abroad_targets)],
        )
        facts = [
            bi_fact('scope-bi-order', 'training', 'orders', '2026-09-10', 1, 'wo-bi'),
            bi_fact('scope-bi-cash', 'training', 'cash', '2026-09-10', 100, 'wo-bi'),
        ]
        order_rows = [order_row('wo-bi', '9000', '留学乙（语培甲）')]
        source_rows = sources(
            resources=[
                resource('9001', '2026-09-11', '语培甲',
                         campaign='语培甲（留学乙）', consultation_type='留学'),
                resource('9002', '2026-09-12', '语培甲',
                         campaign='语培甲（留学乙）', consultation_type='小语种'),
                resource('9003', '2026-09-13', '留学乙', consultation_type='留学'),
                resource('9004', '2026-09-14', '留学乙', consultation_type='小语种'),
            ],
            contracts=[contract('cash-study', 'C-study', '2026-09', '留学乙', 100, '2026-09-15')],
            languages=[language('9005', 'L-small', '2026-09-16', '语培甲', 200)],
            transfers=[
                transfer('9000', '双分', '留学乙（语培甲）', row=2),
                transfer('9001', '双分', '语培甲（留学乙）', row=3),
                transfer('9002', '双分', '语培甲（留学乙）', row=4),
                transfer('9005', '双分', '语培甲（留学乙）', row=5),
            ],
        )

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        training = rows['语培甲']
        abroad = rows['留学乙']
        # The aggregate values retain the existing contribution calculation.
        self.assertEqual(training['self'], {'orders': 0, 'cash': 0})
        self.assertEqual(training['received'], {'orders': 0.5, 'cash': 50})
        self.assertEqual(training['output'], {'orders': 1, 'cash': 100})
        self.assertEqual(training['own_total'], {'orders': 0.5, 'cash': 50})
        self.assertEqual(abroad['self'], {'orders': 2, 'cash': 100})
        self.assertEqual(abroad['received'], {'orders': 1, 'cash': 100})
        self.assertEqual(abroad['own_total'], {'orders': 3, 'cash': 200})
        self.assertEqual(abroad['output'], {'orders': 0.5, 'cash': 50})

        training_study = training['breakdowns']['study_abroad']
        training_small = training['breakdowns']['small_language']
        self.assertEqual(training_study['received'], training_small['received'])
        self.assertEqual(training_study['self'], training_small['self'])
        self.assertEqual(training_study['own_total'], training_small['own_total'])
        self.assertEqual(training_study['output'], {'orders': 0.5, 'cash': 0})
        self.assertEqual(training_small['output'], {'orders': 0.5, 'cash': 100})
        self.assertEqual(
            {metric: training_study['output'][metric] + training_small['output'][metric]
             for metric in ('orders', 'cash')},
            training['output'],
        )

        abroad_study = abroad['breakdowns']['study_abroad']
        abroad_small = abroad['breakdowns']['small_language']
        for bucket in ('self', 'received', 'own_total'):
            self.assertEqual(
                {metric: abroad_study[bucket][metric] + abroad_small[bucket][metric]
                 for metric in ('orders', 'cash')},
                abroad[bucket],
            )
        self.assertEqual(abroad_study['self'], {'orders': 1, 'cash': 100})
        self.assertEqual(abroad_small['self'], {'orders': 1, 'cash': 0})
        self.assertEqual(abroad_study['received'], {'orders': 0.5, 'cash': 0})
        self.assertEqual(abroad_small['received'], {'orders': 0.5, 'cash': 100})
        # BI training output is still present in both abroad-filtered views.
        self.assertEqual(abroad_study['output'], abroad['output'])
        self.assertEqual(abroad_small['output'], abroad['output'])

        ledger = details['records']
        self.assertEqual(
            {row['key']: row['product_scope'] for row in ledger
             if row['source'] in ('resources', 'contracts', 'languages')},
            {'resources:9001': 'study_abroad',
             'resources:9002': 'small_language',
             'resources:9003': 'study_abroad',
             'resources:9004': 'small_language',
             'contracts:C-study': 'study_abroad',
             'languages:2': 'small_language'},
        )
        self.assertTrue(all(row['product_scope'] == 'training'
                            for row in ledger if row['source'] == 'bi'))
        split = {row['key']: row for row in ledger
                 if row['person'] in ('语培甲', '留学乙') and row['bucket'] in ('output', 'received')}
        self.assertEqual(split['resources:9001']['weight'], '0.5')
        self.assertEqual(split['resources:9001']['product_scope'], 'study_abroad')
        self.assertEqual(split['resources:9002']['weight'], '0.5')
        self.assertEqual(split['resources:9002']['product_scope'], 'small_language')

    def test_qualified_abroad_resource_requires_exact_product_scope(self):
        people, abroad_people = rosters(abroad=[member('留学乙')])
        source_rows = sources(resources=[resource(
            '9999', '2026-09-10', '留学乙', consultation_type='其他',
        )], transfers_connected=False)

        with self.assertRaisesRegex(ValueError, '咨询类型必须为留学或小语种'):
            build_contribution(
                [], [], people, abroad_people, source_rows,
                ['2026-09'], targets_for(None),
            )

    def test_duplicate_resource_scope_mismatch_is_a_conflict(self):
        people, abroad_people = rosters(abroad=[member('留学乙')])
        source_rows = sources(resources=[
            resource('9998', '2026-09-10', '留学乙', consultation_type='留学'),
            resource('9998', '2026-09-10', '留学乙', consultation_type='小语种'),
        ])

        with self.assertRaisesRegex(ValueError, '同一留学记录存在冲突'):
            build_contribution(
                [], [], people, abroad_people, source_rows,
                ['2026-09'], targets_for(None),
            )

    def test_order_status_views_filter_orders_and_preserve_all_cash(self):
        statuses = ('正常', '删除', '死单', '回收')
        targets = {'2026-09': {'orders': 100, 'cash': 10000}}
        people, abroad_people = rosters(
            training=[member('语培甲', targets=targets)],
            abroad=[member('留学乙', targets=targets)],
        )
        facts = []
        order_rows = []
        for index, status in enumerate(statuses):
            work_order_id = f'wo-status-{index}'
            order_status = None if status == '回收' else status
            facts.extend([
                bi_fact(f'bi-status-order-{index}', 'training', 'orders', '2026-09-10',
                        1, work_order_id, order_status=order_status),
                bi_fact(f'bi-status-cash-{index}', 'training', 'cash', '2026-09-10',
                        100, work_order_id, order_status=status),
            ])
            order_rows.append(order_row(
                work_order_id, str(1200 + index), '语培甲', order_status=status,
            ))

        source_rows = sources(
            resources=[
                resource('1301', '2026-09-11', '留学乙', consultation_type='留学'),
                resource('1302', '2026-09-12', '留学乙', status='删除', consultation_type='留学'),
                resource('1303', '2026-09-13', '语培甲', status='死单',
                         campaign='语培甲（留学乙）', consultation_type='小语种'),
                resource('1304', '2026-09-14', '留学乙', status='回收', consultation_type='小语种'),
                resource('1305', '2026-09-15', '留学乙', status='删除',
                         campaign='语培甲/留学乙（留学乙）', consultation_type='留学'),
            ],
            contracts=[contract('cash-study', 'C-status-study', '2026-09', '留学乙', 500, '2026-09-16')],
            languages=[language('cash-small', 'L-status-small', '2026-09-17', '留学乙', 300)],
            transfers=[
                transfer('1303', '双分', '语培甲（留学乙）', row=3),
                transfer('1305', '双分', '语培甲/留学乙（留学乙）', row=5),
            ],
        )

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        period, rows = rows_for(result, '2026-09')
        training = rows['语培甲']
        abroad = rows['留学乙']
        expected_training_self = {'00': 1, '01': 2, '10': 3, '11': 4}
        expected_training_output = {'00': 0, '01': 0.5, '10': 0, '11': 0.5}
        expected_abroad_self = {'00': 1, '01': 1, '10': 3, '11': 3}
        expected_abroad_received = {'00': 0, '01': 0.5, '10': 0, '11': 0.5}
        for person_row in (training, abroad):
            self.assertEqual(set(person_row['order_status_views']), set(ORDER_STATUS_MODES))
            default_view = person_row['order_status_views'][DEFAULT_ORDER_STATUS_MODE]
            for bucket in ('self', 'received', 'own_total', 'targets', 'completion',
                           'self_rate', 'output', 'created_total'):
                self.assertEqual(person_row[bucket], default_view[bucket])
            self.assertEqual(person_row['breakdowns'], default_view['breakdowns'])
        # The outer row matches mode 01: only the dead-state bit is enabled.
        self.assertEqual(training['self']['orders'], 2)
        self.assertEqual(training['output']['orders'], 0.5)
        self.assertEqual(training['own_total']['orders'], 2)
        self.assertEqual(abroad['self']['orders'], 1)
        self.assertEqual(abroad['received']['orders'], 0.5)
        self.assertEqual(abroad['own_total']['orders'], 1.5)
        for mode in ORDER_STATUS_MODES:
            training_view = training['order_status_views'][mode]
            abroad_view = abroad['order_status_views'][mode]
            self.assertEqual(training_view['self']['orders'], expected_training_self[mode])
            self.assertEqual(training_view['output']['orders'], expected_training_output[mode])
            self.assertEqual(abroad_view['self']['orders'], expected_abroad_self[mode])
            self.assertEqual(abroad_view['received']['orders'], expected_abroad_received[mode])
            self.assertEqual(abroad_view['breakdowns']['small_language']['received']['orders'],
                             expected_abroad_received[mode])
            self.assertEqual(training_view['breakdowns']['small_language']['output']['orders'],
                             expected_training_output[mode])
        self.assertEqual(abroad['breakdowns']['small_language']['received']['orders'], 0.5)
        self.assertEqual(training['breakdowns']['small_language']['output']['orders'], 0.5)

        # Cash stays fixed in every state view and product scope.
        for person_row in (training, abroad):
            for mode in ORDER_STATUS_MODES:
                view = person_row['order_status_views'][mode]
                for bucket in ('self', 'received', 'own_total', 'completion', 'self_rate', 'output', 'created_total'):
                    self.assertEqual(view[bucket]['cash'], person_row[bucket]['cash'])
                for scope in ('study_abroad', 'small_language'):
                    for bucket in ('self', 'received', 'own_total', 'completion', 'self_rate', 'output', 'created_total'):
                        self.assertEqual(view['breakdowns'][scope][bucket]['cash'],
                                         person_row['breakdowns'][scope][bucket]['cash'])
        self.assertEqual(training['self']['cash'], 400)
        self.assertEqual(abroad['own_total']['cash'], 800)

        by_source_status = {
            (row['source'], row['key'], row['person'], row['metric']): row
            for row in details['records'] if row['metric'] == 'orders'
        }
        deleted = by_source_status[('bi', 'bi-status-order-1', '语培甲', 'orders')]
        dead_split = by_source_status[('resources', 'resources:1303', '留学乙', 'orders')]
        recalled = by_source_status[('resources', 'resources:1304', '留学乙', 'orders')]
        self.assertEqual(deleted['order_status'], '删除')
        self.assertEqual(deleted['inclusion'], {'00': False, '01': False, '10': True, '11': True})
        self.assertEqual(dead_split['order_status'], '死单')
        self.assertEqual(dead_split['bucket'], 'received')
        self.assertEqual(dead_split['weight'], '0.5')
        self.assertEqual(dead_split['inclusion'], {'00': False, '01': True, '10': False, '11': True})
        self.assertEqual(recalled['order_status'], '回收')
        self.assertEqual(recalled['inclusion'], {'00': False, '01': False, '10': True, '11': True})
        bi_recalled = by_source_status[('bi', 'bi-status-order-3', '语培甲', 'orders')]
        self.assertEqual(bi_recalled['order_status'], '回收')
        self.assertEqual(details['pending'], [])
        self.assertEqual(period['pending_count'], 0)

    def test_special_training_pair_splits_abroad_to_offline_creator_and_abroad_receiver(self):
        people, abroad_people = rosters(
            training=[member('师顺盈')],
            online=[member('高勃然')],
            abroad=[member('邓睿')],
        )
        source_rows = sources(
            resources=[resource('2101', '2026-09-18', '师顺盈')],
            contracts=[contract('2101', 'C-2101', '2026-09', '师顺盈', 200, '2026-09-19')],
            transfers=[transfer('2101', '双分', '师顺盈/高勃然（邓睿）')],
        )

        result, _ = build_contribution(
            [], [], people, abroad_people, source_rows, ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        self.assertEqual(set(rows), {'师顺盈', '邓睿'})
        self.assertEqual(rows['师顺盈']['output']['orders'], 0.5)
        self.assertEqual(rows['邓睿']['received']['orders'], 0.5)
        self.assertEqual(rows['师顺盈']['output']['cash'], 100)
        self.assertEqual(rows['邓睿']['received']['cash'], 100)

    def test_real_abroad_sources_handoff_without_flow_and_independent_sources_stay_full(self):
        people, abroad_people = rosters(
            training=[member('师顺盈')],
            online=[member('高勃然')],
            abroad=[member('邓睿')],
        )
        campaign = '师顺盈/高勃然（邓睿）'
        source_rows = sources(
            resources=[
                resource('468', '2026-09-10', '师顺盈', campaign=campaign),
                resource('469', '2026-09-11', '邓睿', campaign=campaign),
                resource('599', '2026-09-12', '师顺盈', campaign='校代小语种'),
                resource('836', '2026-09-13', '师顺盈', campaign=''),
                resource('837', '2026-09-14', '师顺盈', campaign=''),
            ],
            contracts=[
                contract('468', 'C-468', '2026-09', '师顺盈', 100, '2026-09-10', campaign),
                contract('469', 'C-469', '2026-09', '邓睿', 200, '2026-09-11', campaign),
            ],
            languages=[language('599', 'L-599', '2026-09-15', '师顺盈', 300)],
            # The flow workbook is connected, but these resources have no ID-matched flow rows.
            transfers=[],
        )

        result, details = build_contribution(
            [], [], people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        creator = rows['师顺盈']
        receiver = rows['邓睿']
        self.assertEqual(creator['output']['orders'], 4)
        self.assertEqual(receiver['received']['orders'], 1)
        self.assertEqual(creator['self']['orders'], 0)
        self.assertEqual(creator['output']['cash'], 450)
        self.assertEqual(receiver['received']['cash'], 150)

        output_orders = {row['key']: row for row in details['records']
                         if row['metric'] == 'orders' and row['bucket'] == 'output'}
        received_orders = {row['key']: row for row in details['records']
                           if row['metric'] == 'orders' and row['bucket'] == 'received'}
        self.assertEqual(set(output_orders), {'resources:468', 'resources:469',
                                               'resources:599', 'resources:836', 'resources:837'})
        self.assertEqual(set(received_orders), {'resources:468', 'resources:469'})
        for rid in ('468', '469'):
            self.assertEqual(output_orders[f'resources:{rid}']['weight'], '0.5')
            self.assertEqual(received_orders[f'resources:{rid}']['weight'], '0.5')
            self.assertEqual(output_orders[f'resources:{rid}']['rule'], 'activity_market_handoff')
        for rid in ('599', '836', '837'):
            self.assertEqual(output_orders[f'resources:{rid}']['weight'], '1')
            self.assertEqual(output_orders[f'resources:{rid}']['rule'], 'independent_cross_output')
        self.assertEqual(details['pending'], [])

    def test_reverse_training_source_handoff_splits_only_the_real_bi_source(self):
        people, abroad_people = rosters(
            training=[member('语培甲')], abroad=[member('留学乙')],
        )
        facts = [
            bi_fact('reverse-order', 'training', 'orders', '2026-09-10', 1, 'wo-reverse'),
            bi_fact('reverse-cash', 'training', 'cash', '2026-09-10', 200, 'wo-reverse'),
        ]
        order_rows = [order_row(
            'wo-reverse', '9701', '留学乙（语培甲）', '留学乙',
        )]

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, sources(transfers=[]),
            ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        self.assertEqual(rows['留学乙']['output']['orders'], 0.5)
        self.assertEqual(rows['语培甲']['received']['orders'], 0.5)
        self.assertEqual(rows['留学乙']['output']['cash'], 100)
        self.assertEqual(rows['语培甲']['received']['cash'], 100)
        self.assertEqual({row['key'] for row in details['records']},
                         {'reverse-order', 'reverse-cash'})
        self.assertTrue(all(row['rule'] == 'activity_market_handoff'
                            for row in details['records']))

    def test_training_activity_names_do_not_create_missing_abroad_sources(self):
        people, abroad_people = rosters(
            training=[member('语培甲')], abroad=[member('留学乙')],
        )
        facts = [
            bi_fact(f'work-{i}', 'training', 'orders', '2026-09-10', 1, f'wo-{i}')
            for i in range(10)
        ]
        order_rows = [
            order_row(f'wo-{i}', str(8400 + i), '语培甲（留学乙）', '语培甲')
            for i in range(10)
        ]
        source_rows = sources(resources=[
            resource('8400', '2026-09-10', '语培甲', campaign='语培甲（留学乙）'),
            resource('8401', '2026-09-11', '语培甲', campaign='语培甲（留学乙）'),
        ], transfers=[])

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        self.assertEqual(rows['语培甲']['self']['orders'], 10)
        self.assertEqual(rows['语培甲']['output']['orders'], 1)
        self.assertEqual(rows['留学乙']['received']['orders'], 1)
        training_records = [row for row in details['records'] if row['source'] == 'bi']
        abroad_records = [row for row in details['records'] if row['source'] == 'resources']
        self.assertEqual(len(training_records), 10)
        self.assertEqual({row['key'] for row in abroad_records}, {'resources:8400', 'resources:8401'})

    def test_non_double_flow_does_not_block_real_handoff_or_split_own_side_training(self):
        people, abroad_people = rosters(
            training=[member('语培甲')], abroad=[member('留学乙')],
        )
        facts = [bi_fact('non-double-training', 'training', 'orders',
                         '2026-09-10', 1, 'wo-non-double')]
        order_rows = [order_row(
            'wo-non-double', '8601', '语培甲（留学乙）', '语培甲',
        )]
        source_rows = sources(
            resources=[resource('8601', '2026-09-10', '语培甲', campaign='语培甲（留学乙）')],
            transfers=[transfer('8601', '非双分', '不用于覆盖来源活动')],
        )

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        self.assertEqual(rows['语培甲']['self']['orders'], 1)
        self.assertEqual(rows['语培甲']['output']['orders'], 0.5)
        self.assertEqual(rows['留学乙']['received']['orders'], 0.5)
        training_row = next(row for row in details['records'] if row['key'] == 'non-double-training')
        self.assertEqual((training_row['person'], training_row['bucket'], training_row['credited_value']),
                         ('语培甲', 'self', '1'))
        abroad_outputs = [row for row in details['records'] if row['key'] == 'resources:8601']
        self.assertEqual({row['bucket']: row['credited_value'] for row in abroad_outputs},
                         {'output': '0.5', 'received': '0.5'})

    def test_blank_owner_is_not_filled_and_unrelated_activity_cannot_replace_source_owner(self):
        people, abroad_people = rosters(
            training=[member('语培甲'), member('语培乙')],
            abroad=[member('留学丙')],
        )
        blank_owner = resource(
            '8801', '2026-09-10', '', campaign='语培甲（留学丙）',
        )
        blank_owner['data_provider'] = '留学丙'
        blank_owner['assigned_adviser'] = '留学丙'
        unrelated_activity = resource(
            '8802', '2026-09-11', '留学丙', campaign='语培甲（语培乙）',
        )
        unrelated_activity['data_provider'] = '语培甲'
        source_rows = sources(resources=[blank_owner, unrelated_activity], transfers=[])

        result, details = build_contribution(
            [], [], people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        period, rows = rows_for(result, '2026-09')
        self.assertEqual(rows['留学丙']['self']['orders'], 1)
        self.assertEqual(rows['留学丙']['received']['orders'], 0)
        self.assertEqual(rows['语培甲']['output']['orders'], 0)
        self.assertEqual(rows['语培乙']['output']['orders'], 0)
        self.assertEqual([row['key'] for row in details['records']], ['resources:8802'])
        self.assertEqual(details['records'][0]['person'], '留学丙')
        self.assertEqual(details['records'][0]['bucket'], 'self')
        self.assertEqual(details['diagnostics']['blank_abroad_owner'], 1)
        self.assertEqual(period['pending_count'], 0)
        self.assertEqual(details['pending'], [])

    def test_departed_activity_receiver_does_not_take_credit_or_reduce_independent_output(self):
        people, abroad_people = rosters(
            training=[member('师顺盈')],
            abroad=[member('邓睿', status='departed')],
        )
        row = resource('8803', '2026-09-12', '师顺盈', campaign='师顺盈（邓睿）')
        row['data_provider'] = '邓睿'
        row['consultant'] = '邓睿'

        result, details = build_contribution(
            [], [], people, abroad_people, sources(resources=[row], transfers=[]),
            ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        self.assertEqual(set(rows), {'师顺盈'})
        self.assertEqual(rows['师顺盈']['output']['orders'], 1)
        self.assertEqual(rows['师顺盈']['received']['orders'], 0)
        self.assertEqual(len(details['records']), 1)
        self.assertEqual(details['records'][0]['person'], '师顺盈')
        self.assertEqual(details['records'][0]['bucket'], 'output')
        self.assertEqual(details['records'][0]['weight'], '1')

    def test_channel_and_same_person_bracket_do_not_create_a_receiver(self):
        people, abroad_people = rosters(training=[member('王洪霞')])
        facts = [
            bi_fact('channel-order', 'training', 'orders', '2026-09-10', 1, 'wo-channel'),
            bi_fact('bracket-order', 'training', 'orders', '2026-09-11', 1, 'wo-bracket'),
        ]
        order_rows = [
            order_row('wo-channel', '3001', '校代渠道活动', '王洪霞'),
            order_row('wo-bracket', '3002', '（双分）王洪霞', '王洪霞'),
        ]
        source_rows = sources(
            resources=[resource('3002', '2026-09-12', '王洪霞')],
            transfers=[
                transfer('3001', '双分', '校代渠道活动'),
                transfer('3002', '双分', '（双分）王洪霞'),
            ],
        )

        result, _ = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        person = rows['王洪霞']
        self.assertEqual(person['self']['orders'], 2)
        self.assertEqual(person['output']['orders'], 1)
        self.assertEqual(person['received']['orders'], 0)

    def test_explicit_non_double_transfer_tag_overrides_double_campaign_text(self):
        people, abroad_people = rosters(
            training=[member('语培甲')], abroad=[member('留学乙')],
        )
        facts = [bi_fact('single-order', 'training', 'orders', '2026-09-10', 1, 'wo-single')]
        order_rows = [order_row('wo-single', '4001', '语培甲（留学乙）双分', '语培甲')]
        source_rows = sources(transfers=[
            transfer('4001', '非双分', '留学乙（语培甲）双分'),
        ])

        result, _ = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        period, rows = rows_for(result, '2026-09')
        self.assertEqual(rows['语培甲']['self']['orders'], 1)
        self.assertEqual(rows['语培甲']['received']['orders'], 0)
        self.assertEqual(rows['留学乙']['output']['orders'], 0)
        self.assertEqual(period['pending_count'], 0)
        self.assertEqual(period['pending'], [])

    def test_same_activity_name_without_matching_resource_transfer_stays_self_owned(self):
        people, abroad_people = rosters(
            training=[member('语培甲')], abroad=[member('留学乙')],
        )
        facts = [bi_fact(
            'pending-order', 'training', 'orders', '2026-09-10', 1, 'wo-pending',
            source_row_number=31,
        )]
        order_rows = [order_row(
            'wo-pending', '8101', '语培甲（留学乙）', '语培甲', source_row_number=41,
        )]
        source_rows = sources(transfers=[
            # Matching activity text cannot substitute for a matching resource ID.
            transfer('8102', '双分', '语培甲（留学乙）', row=9),
        ])
        original_facts = copy.deepcopy(facts)
        original_sources = copy.deepcopy(source_rows)

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        self.assertEqual(facts, original_facts)
        self.assertEqual(source_rows, original_sources)
        period, rows = rows_for(result, '2026-09')
        self.assertEqual(period['pending_count'], 0)
        self.assertEqual(period['pending'], [])
        self.assertEqual(rows['语培甲']['pending_count'], 0)
        self.assertEqual(rows['留学乙']['pending_count'], 0)
        self.assertEqual(rows['语培甲']['self']['orders'], 1)
        self.assertEqual(rows['语培甲']['received']['orders'], 0)
        self.assertEqual(rows['留学乙']['output']['orders'], 0)
        self.assertEqual(details['pending'], [])
        self.assertTrue(any(
            row['key'] == 'pending-order' and row['person'] == '语培甲'
            and row['bucket'] == 'self' and row['credited_value'] == '1'
            for row in details['records']
        ))

    def test_connected_empty_abroad_source_reports_zero_without_inventing_credit(self):
        people, abroad_people = rosters(
            training=[member('语培甲')], abroad=[member('留学乙')],
        )
        facts = [
            bi_fact('training-only-order', 'training', 'orders', '2026-09-10', 1, 'wo-training-only'),
            bi_fact('training-only-cash', 'training', 'cash', '2026-09-10', 100, 'wo-training-only'),
        ]
        order_rows = [order_row(
            'wo-training-only', '8701', '语培甲（留学乙）', '语培甲',
        )]
        source_rows = sources(transfers=[
            transfer('8701', '双分', '语培甲（留学乙）'),
        ])

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        period, rows = rows_for(result, '2026-09')
        training = rows['语培甲']
        abroad = rows['留学乙']
        self.assertFalse(period['coverage']['abroad']['connected'])
        self.assertEqual(training['self']['orders'], 1)
        self.assertEqual(training['self']['cash'], 100)
        self.assertEqual(training['output']['orders'], 0)
        self.assertEqual(training['output']['cash'], 0)
        self.assertEqual(training['created_total']['orders'], 1)
        self.assertEqual(training['created_total']['cash'], 100)
        self.assertEqual(abroad['self']['orders'], 0)
        self.assertEqual(abroad['received']['orders'], 0)
        self.assertEqual(abroad['self']['cash'], 0)
        self.assertEqual(abroad['received']['cash'], 0)
        self.assertTrue(all(row['person'] == '语培甲' and row['bucket'] == 'self'
                            for row in details['records']))
        self.assertEqual(details['pending'], [])

    def test_same_business_bracket_collaboration_is_not_cross_business_pending(self):
        people, abroad_people = rosters(
            training=[member('语培甲'), member('语培乙')],
            abroad=[member('留学丙')],
        )
        facts = [bi_fact('same-line-order', 'training', 'orders', '2026-09-10', 1, 'wo-same-line')]
        order_rows = [order_row(
            'wo-same-line', '8201', '语培甲（语培乙）', '语培甲',
        )]

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, sources(),
            ['2026-09'], targets_for(None),
        )

        period, rows = rows_for(result, '2026-09')
        self.assertEqual(period['pending_count'], 0)
        self.assertEqual(period['pending'], [])
        self.assertEqual(rows['语培甲']['pending_count'], 0)
        self.assertEqual(rows['语培甲']['self']['orders'], 0.5)
        self.assertEqual(rows['语培乙']['self']['orders'], 0.5)
        self.assertEqual(rows['语培甲']['own_total']['orders'], 0.5)
        self.assertEqual(rows['语培乙']['own_total']['orders'], 0.5)
        self.assertEqual(details['pending'], [])

    def test_ordinary_order_and_cash_share_between_offline_people_and_keep_virtual_full(self):
        people, abroad_people = rosters(
            training=[member('语培甲'), member('语培乙')],
            online=[member('虚拟丙')],
        )
        facts = [
            bi_fact('virtual-mix-order', 'training', 'orders', '2026-09-10', 1, 'wo-virtual-mix'),
            bi_fact('virtual-mix-cash', 'training', 'cash', '2026-09-10', 100, 'wo-virtual-mix'),
        ]
        order_rows = [order_row(
            'wo-virtual-mix', '8301', '语培甲/语培乙/虚拟丙', '语培甲',
        )]

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, sources(),
            ['2026-09'], targets_for(None),
        )

        period, rows = rows_for(result, '2026-09')
        self.assertEqual(set(rows), {'语培甲', '语培乙'})
        self.assertEqual(rows['语培甲']['self']['orders'], 0.5)
        self.assertEqual(rows['语培乙']['self']['orders'], 0.5)
        self.assertEqual(rows['语培甲']['self']['cash'], 50)
        self.assertEqual(rows['语培乙']['self']['cash'], 50)
        self.assertFalse(any(row['person'] == '虚拟丙' for row in details['records']))
        offline_ledger = {
            (row['person'], row['metric']): (row['weight'], row['credited_value'])
            for row in details['records']
        }
        self.assertEqual(offline_ledger[('语培甲', 'orders')], ('0.5', '0.5'))
        self.assertEqual(offline_ledger[('语培乙', 'orders')], ('0.5', '0.5'))
        self.assertEqual(offline_ledger[('语培甲', 'cash')], ('0.5', '50.0'))
        self.assertEqual(offline_ledger[('语培乙', 'cash')], ('0.5', '50.0'))
        self.assertEqual(period['pending_count'], 0)

    def test_one_offline_person_is_not_diluted_by_one_virtual_person(self):
        people, abroad_people = rosters(
            training=[member('语培甲')], online=[member('虚拟丙')],
        )
        facts = [bi_fact(
            'one-offline-one-virtual', 'training', 'orders', '2026-09-10', 1, 'wo-one-virtual',
        )]
        order_rows = [order_row(
            'wo-one-virtual', '8302', '语培甲/虚拟丙', '语培甲',
        )]

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, sources(),
            ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        self.assertEqual(set(rows), {'语培甲'})
        self.assertEqual(rows['语培甲']['self']['orders'], 1)
        self.assertEqual(len(details['records']), 1)
        self.assertEqual(details['records'][0]['weight'], '1')

    def test_departed_and_unknown_names_do_not_enter_the_offline_weight_denominator(self):
        people, abroad_people = rosters(training=[
            member('语培甲'),
            member('语培乙'),
            member('离职丙', status='departed'),
        ])
        facts = [bi_fact(
            'active-only-cocreators', 'training', 'orders', '2026-09-10', 1, 'wo-active-only',
        )]
        order_rows = [order_row(
            'wo-active-only', '8303', '语培甲/语培乙/离职丙/未知丁', '语培甲',
        )]

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, sources(),
            ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        self.assertEqual(rows['语培甲']['self']['orders'], 0.5)
        self.assertEqual(rows['语培乙']['self']['orders'], 0.5)
        self.assertNotIn('离职丙', rows)
        self.assertNotIn('未知丁', rows)
        self.assertEqual({row['person'] for row in details['records']}, {'语培甲', '语培乙'})

    def test_only_three_of_ten_training_orders_receive_cross_business_credit(self):
        people, abroad_people = rosters(
            training=[member('语培甲')], abroad=[member('留学乙')],
        )
        facts = [bi_fact(
            f'ten-order-{index}', 'training', 'orders', '2026-09-10', 1, f'wo-{index}',
        ) for index in range(10)]
        order_rows = [order_row(
            f'wo-{index}', f'840{index}', '语培甲（留学乙）', '语培甲',
        ) for index in range(10)]
        source_rows = sources(
            resources=[resource(f'840{index}', '2026-09-10', '留学乙') for index in range(3)],
            transfers=[
                transfer(f'840{index}', '双分', '语培甲（留学乙）', row=index + 2)
                for index in range(3)
            ],
        )

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        period, rows = rows_for(result, '2026-09')
        self.assertEqual(rows['语培甲']['self']['orders'], 10)
        self.assertEqual(rows['语培甲']['output']['orders'], 1.5)
        self.assertEqual(rows['留学乙']['received']['orders'], 1.5)
        self.assertEqual(rows['留学乙']['self']['orders'], 0)
        self.assertEqual(period['pending_count'], 0)
        self.assertEqual(period['pending'], [])
        cross_keys = {f'resources:840{index}' for index in range(3)}
        output_records = [row for row in details['records'] if row['bucket'] == 'output']
        received_records = [row for row in details['records'] if row['bucket'] == 'received']
        self.assertEqual({row['key'] for row in output_records}, cross_keys)
        self.assertEqual({row['key'] for row in received_records}, cross_keys)
        self.assertEqual({row['weight'] for row in output_records}, {'0.5'})
        self.assertEqual({row['weight'] for row in received_records}, {'0.5'})
        self.assertEqual(details['pending'], [])

    def test_two_offline_double_split_primaries_share_cross_business_output(self):
        people, abroad_people = rosters(
            training=[member('语培甲'), member('语培乙')],
            abroad=[member('留学丙')],
        )
        facts = [
            bi_fact('two-primary-order', 'training', 'orders', '2026-09-10', 1, 'wo-two-primary'),
            bi_fact('two-primary-cash', 'training', 'cash', '2026-09-10', 100, 'wo-two-primary'),
        ]
        order_rows = [order_row(
            'wo-two-primary', '8601', '语培甲/语培乙（留学丙）', '语培甲',
        )]
        source_rows = sources(
            resources=[resource('8601', '2026-09-10', '留学丙')],
            transfers=[transfer('8601', '双分', '语培甲/语培乙（留学丙）')],
        )

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        # The matching abroad source is an order resource only; it cannot create
        # an abroad-side cash amount from the training BI cash fact.
        for name in ('语培甲', '语培乙'):
            self.assertEqual(rows[name]['self']['orders'], 0.5)
            self.assertEqual(rows[name]['output']['orders'], 0.25)
            self.assertEqual(rows[name]['self']['cash'], 50)
            self.assertEqual(rows[name]['output']['cash'], 0)
        self.assertEqual(rows['留学丙']['received']['orders'], 0.5)
        self.assertEqual(rows['留学丙']['received']['cash'], 0)
        self.assertEqual(sum(rows[name]['self']['orders'] for name in ('语培甲', '语培乙')), 1)
        self.assertEqual(sum(rows[name]['output']['orders'] for name in ('语培甲', '语培乙')), 0.5)
        self.assertEqual({row['weight'] for row in details['records']
                          if row['bucket'] == 'output' and row['metric'] == 'orders'}, {'0.25'})
        self.assertEqual({row['key'] for row in details['records']
                          if row['bucket'] == 'output' and row['metric'] == 'orders'}, {'resources:8601'})

    def test_departed_double_split_primary_only_gives_secondary_half_received(self):
        people, abroad_people = rosters(training=[member('语培甲')])
        facts = [bi_fact(
            'departed-primary-order', 'training', 'orders', '2026-09-10', 1, 'wo-departed-primary',
        )]
        order_rows = [order_row(
            'wo-departed-primary', '8601', '离职主办（语培甲）', '离职主办',
        )]
        source_rows = sources(
            resources=[resource('8699', '2026-09-01', '语培甲', '删除')],
            transfers=[transfer('8601', '双分', '离职主办（语培甲）')],
        )

        result, details = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        period, rows = rows_for(result, '2026-09')
        self.assertEqual(rows['语培甲']['self']['orders'], 0)
        self.assertEqual(rows['语培甲']['received']['orders'], 0.5)
        self.assertEqual(rows['语培甲']['output']['orders'], 0)
        self.assertEqual(rows['语培甲']['order_status_views']['11']['output']['orders'], 1)
        self.assertEqual(period['pending_count'], 0)
        self.assertEqual(period['pending'], [])
        self.assertEqual(len(details['records']), 2)
        received = next(row for row in details['records'] if row['bucket'] == 'received')
        deleted_output = next(row for row in details['records'] if row['bucket'] == 'output')
        self.assertEqual(received['weight'], '0.5')
        self.assertEqual(deleted_output['order_status'], '删除')
        self.assertEqual(deleted_output['inclusion'], {
            '00': False, '01': False, '10': True, '11': True,
        })

    def test_customer_id_prefix_cannot_match_a_resource_transfer(self):
        people, abroad_people = rosters(
            training=[member('语培甲')], abroad=[member('留学乙')],
        )
        facts = [bi_fact('customer-order', 'training', 'orders', '2026-09-10', 1, 'wo-customer')]
        order_rows = [order_row('wo-customer', '客户ID:5002', '语培甲', '语培甲')]
        source_rows = sources(transfers=[
            transfer('5002', '双分', '留学乙（语培甲）'),
        ])

        result, _ = build_contribution(
            facts, order_rows, people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        _, rows = rows_for(result, '2026-09')
        self.assertEqual(rows['语培甲']['self']['orders'], 1)
        self.assertEqual(rows['语培甲']['received']['orders'], 0)
        self.assertEqual(rows['留学乙']['output']['orders'], 0)

    def test_default_mode_includes_dead_but_excludes_deleted_and_recalled_resources(self):
        people, abroad_people = rosters(abroad=[member('留学乙')])
        source_rows = sources(resources=[
            resource('6001', '2026-09-10', '留学乙', '删除'),
            resource('6002', '2026-09-11', '留学乙', '回收'),
            resource('6003', '2026-09-12', '留学乙', '死单'),
        ])

        result, details = build_contribution(
            [], [], people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        period, rows = rows_for(result, '2026-09')
        self.assertEqual(rows['留学乙']['self']['orders'], 1)
        self.assertEqual(rows['留学乙']['order_status_views']['00']['self']['orders'], 0)
        self.assertEqual(rows['留学乙']['order_status_views']['01']['self']['orders'], 1)
        self.assertEqual(rows['留学乙']['order_status_views']['10']['self']['orders'], 2)
        self.assertEqual(rows['留学乙']['order_status_views']['11']['self']['orders'], 3)
        self.assertEqual(rows['留学乙']['received']['orders'], 0)
        self.assertEqual(period['coverage']['abroad']['orders_through'], '2026-09-12')
        self.assertEqual(details['diagnostics']['deleted_abroad_orders'], 1)
        self.assertEqual(len(details['records']), 3)
        self.assertEqual({row['order_status'] for row in details['records']}, {'删除', '回收', '死单'})

    def test_connected_empty_abroad_month_is_zero_but_disconnected_source_is_unknown(self):
        people, abroad_people = rosters(
            training=[member('语培甲')], abroad=[member('留学乙')],
        )
        facts = [bi_fact('training-order', 'training', 'orders', '2026-09-10', 1, 'wo-1')]
        order_rows = [order_row('wo-1', '7001', '语培甲', '语培甲')]

        result, _ = build_contribution(
            facts, order_rows, people, abroad_people,
            sources(transfers_connected=True), ['2026-09'], targets_for(None),
        )
        period, rows = rows_for(result, '2026-09')
        self.assertFalse(period['coverage']['abroad']['connected'])
        self.assertEqual(rows['留学乙']['self']['orders'], 0)
        self.assertEqual(rows['留学乙']['own_total']['orders'], 0)
        self.assertEqual(rows['留学乙']['self']['cash'], 0)
        self.assertEqual(rows['语培甲']['output']['orders'], 0)
        self.assertEqual(rows['语培甲']['output']['cash'], 0)

        disconnected = sources(
            resources=[resource('7002', '2026-09-12', '留学乙')],
            transfers_connected=False,
        )
        result, details = build_contribution(
            facts, order_rows, people, abroad_people, disconnected,
            ['2026-09'], targets_for(None),
        )
        _, rows = rows_for(result, '2026-09')
        for person in rows.values():
            for bucket in ('self', 'received', 'own_total', 'output', 'created_total'):
                self.assertIsNone(person[bucket]['orders'])
                self.assertIsNone(person[bucket]['cash'])
        self.assertEqual(details['records'], [])

    def test_abroad_month_with_target_and_no_events_is_zero_then_updates_without_changing_prior_month(self):
        people, abroad_people = rosters(abroad=[member('留学乙', targets={
            '2026-09': {'orders': 90, 'cash': 90000},
            '2026-10': {'orders': 70, 'cash': 80000},
        })])
        source_rows = sources(
            resources=[resource('9101', '2026-09-10', '留学乙')],
            contracts=[contract('9101', 'C-9101', '2026-09', '留学乙', 10000, '2026-09-12')],
            transfers=[],
        )

        initial, _ = build_contribution(
            [], [], people, abroad_people, source_rows,
            ['2026-09', '2026-10'], targets_for(None),
        )
        september_before, before_rows = rows_for(initial, '2026-09')
        october_before, before_october_rows = rows_for(initial, '2026-10')
        self.assertEqual(before_october_rows['留学乙']['self']['orders'], 0)
        self.assertEqual(before_october_rows['留学乙']['self']['cash'], 0)
        self.assertEqual(before_october_rows['留学乙']['targets']['orders'], 70)
        self.assertEqual(before_october_rows['留学乙']['targets']['cash'], 80000)
        self.assertEqual(before_october_rows['留学乙']['completion']['orders'], 0)
        self.assertEqual(before_october_rows['留学乙']['completion']['cash'], 0)
        self.assertEqual(before_rows['留学乙']['self']['orders'], 1)
        self.assertEqual(before_rows['留学乙']['self']['cash'], 10000)

        source_rows['resources'].append(resource('9102', '2026-10-07', '留学乙'))
        source_rows['contracts'].append(
            contract('9102', 'C-9102', '2026-10', '留学乙', 12000, '2026-10-10')
        )
        updated, _ = build_contribution(
            [], [], people, abroad_people, source_rows,
            ['2026-09', '2026-10'], targets_for(None),
        )
        september_after, after_rows = rows_for(updated, '2026-09')
        october_after, after_october_rows = rows_for(updated, '2026-10')
        self.assertEqual(after_october_rows['留学乙']['self']['orders'], 1)
        self.assertEqual(after_october_rows['留学乙']['self']['cash'], 12000)
        self.assertAlmostEqual(after_october_rows['留学乙']['completion']['orders'], 1 / 70)
        self.assertEqual(after_october_rows['留学乙']['completion']['cash'], 0.15)
        self.assertEqual(after_rows['留学乙']['self']['orders'], 1)
        self.assertEqual(after_rows['留学乙']['self']['cash'], 10000)
        self.assertEqual(september_after['id'], september_before['id'])
        self.assertEqual(october_after['id'], october_before['id'])

    def test_blank_contract_owner_is_not_inferred_from_other_sources(self):
        people, abroad_people = rosters(
            training=[member('语培甲')], abroad=[member('留学乙')],
        )
        source_rows = sources(
            resources=[resource('7101', '2026-09-10', '语培甲', campaign='语培甲（留学乙）')],
            contracts=[contract('7101', 'C-7101', '2026-09', '', 900, '2026-09-20', '语培甲（留学乙）')],
            transfers=[transfer('7101', '双分', '语培甲（留学乙）')],
        )

        result, details = build_contribution(
            [], [], people, abroad_people, source_rows,
            ['2026-09'], targets_for(None),
        )

        period, rows = rows_for(result, '2026-09')
        self.assertEqual(rows['语培甲']['output']['cash'], 0)
        self.assertEqual(rows['留学乙']['received']['cash'], 0)
        self.assertFalse(any(row['source'] == 'contracts' for row in details['records']))
        self.assertEqual(details['diagnostics']['blank_abroad_owner'], 1)
        self.assertEqual(period['pending_count'], 0)
        self.assertEqual(period['pending'], [])
        self.assertEqual(details['pending'], [])

    def test_loader_reads_rows_beyond_a_stale_a1_dimension(self):
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource_path = root / 'resources.xlsx'
            transfer_path = root / 'missing-transfers.xlsx'
            workbook = Workbook()
            resource_sheet = workbook.active
            resource_sheet.title = '资源'
            resource_sheet.append(['资源ID', '分单日期', '市场资源归属人', '线下组资源', '市场活动'])
            resource_sheet.append(['8001', '2026-09-09', '留学乙', '正常', '测试活动'])
            contracts = workbook.create_sheet('留学签约')
            contracts.append(['记录id', '合同编号', '归档月份', '市场资源归属人', '签约金额', '91资源市场活动', '归档日期'])
            languages = workbook.create_sheet('小语种签约')
            languages.append(['资源ID', '工单ID', '业务日期', '市场资源归属人', '实缴金额'])
            workbook.save(resource_path)

            with zipfile.ZipFile(resource_path) as archive:
                files = {item.filename: archive.read(item.filename) for item in archive.infolist()}
            xml = files['xl/worksheets/sheet1.xml']
            xml, replacements = re.subn(
                rb'<dimension ref="[^"]+"\s*/>',
                b'<dimension ref="A1:A1"/>', xml, count=1,
            )
            self.assertEqual(replacements, 1)
            files['xl/worksheets/sheet1.xml'] = xml
            rewritten = root / 'rewritten.xlsx'
            with zipfile.ZipFile(rewritten, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, content in files.items():
                    archive.writestr(name, content)
            rewritten.replace(resource_path)

            loaded = load_sources(resource_path, transfer_path)

        self.assertTrue(loaded['resources_connected'])
        self.assertFalse(loaded['transfers_connected'])
        self.assertEqual(len(loaded['resources']), 1)
        self.assertEqual(loaded['resources'][0]['resource_id'], '8001')
        self.assertEqual(loaded['resources'][0]['source_row_number'], 2)

    def test_conflicting_contract_unique_key_raises(self):
        people, abroad_people = rosters(abroad=[member('留学乙')])
        source_rows = sources(contracts=[
            contract('9001', 'SAME-CONTRACT', '2026-09', '留学乙', 100, '2026-09-10'),
            contract('9001', 'SAME-CONTRACT', '2026-09', '留学乙', 200, '2026-09-11'),
        ])

        with self.assertRaisesRegex(ValueError, '同一留学记录存在冲突'):
            build_contribution(
                [], [], people, abroad_people, source_rows,
                ['2026-09'], targets_for(None),
            )


if __name__ == '__main__':
    unittest.main()
