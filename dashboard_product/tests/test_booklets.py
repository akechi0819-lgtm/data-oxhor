import json
import tempfile
import unittest
from pathlib import Path

from dashboard_product.booklets import (
    BOOKLET_IDS,
    booklet_chrome,
    drill_team_id,
    filter_dashboard_for_booklet,
)
from dashboard_product.refresh import render, render_all_booklets
from dashboard_product.render_template import render_html


def _group(name, cash=100, orders=10, prior_cash=80, prior_orders=8):
    return {
        'display_name': name,
        'quarter_targets': {'Q1': {'cash': cash, 'orders': orders}},
        'annual_targets': {'cash': cash, 'orders': orders},
        'monthly_actuals': {'cash': [cash] + [0] * 11, 'orders': [orders] + [0] * 11},
        'prior_monthly_actuals': {'cash': [prior_cash] + [0] * 11, 'orders': [prior_orders] + [0] * 11},
        'cash_actual': cash,
        'orders_actual': orders,
    }


def _yoy_group(name, cash=100, orders=10, prior_cash=80, prior_orders=8):
    return {
        'display_name': name,
        'monthly_actuals': {'cash': [cash] + [0] * 11, 'orders': [orders] + [0] * 11},
        'prior_monthly_actuals': {'cash': [prior_cash] + [0] * 11, 'orders': [prior_orders] + [0] * 11},
    }


def _yoy_groups():
    return [
        _yoy_group('青少'),
        _yoy_group('初中'),
        _yoy_group('高中'),
        _yoy_group('大学'),
    ]


def _person(name, business_group, roster_group):
    return {
        'display_name': name,
        'group_name': roster_group,
        'business_group': business_group,
        'monthly_targets': {'2026-06': {'orders': 10, 'cash': 1000}},
        'cash_actual': 42,
        'orders_actual': 12,
        'monthly_actuals': {'cash': [42] + [0] * 11, 'orders': [12] + [0] * 11},
        'monthly_drilldowns': {'2026-06': {'cash': {'转介绍||老客转介绍': 42}, 'orders': {'转介绍||老客转介绍': 12}}},
    }


def _four_team_dashboard():
    return {
        'months': ['2026-06'] * 12,
        'prior_months': ['2025-06'] * 12,
        'drilldowns': {
            'current': {
                'cash': {
                    'channel': {
                        '2026-06|offline_market|留学预备|转介绍|老客转介绍': 3,
                        '2026-06|online_private|留学预备|转介绍|老客转介绍': 9,
                        '2026-06|online_platform|大学|TMK|校园': 5,
                        '2026-06|market_total|留学预备|转介绍|老客转介绍': 12,
                    },
                    'school_grade': {
                        '2026-06|offline_market|高中|某高中|高一': 2,
                        '2026-06|online_private|留学预备|某初中|初三': 1,
                        '2026-06|online_platform|大学|某大学|大二': 3,
                        '2026-06|market_total|大学|某大学|大二': 3,
                    },
                },
                'orders': {'channel': {}, 'school_grade': {}},
            },
            'prior': {
                'cash': {
                    'channel': {
                        '2025-06|offline_market|留学预备|转介绍|老客转介绍': 4,
                        '2025-06|online_private|留学预备|转介绍|老客转介绍': 8,
                        '2025-06|online_platform|大学|市场活动|异业渠道': 6,
                        '2025-06|market_total|留学预备|转介绍|老客转介绍': 12,
                    },
                    'school_grade': {},
                },
                'orders': {'channel': {}, 'school_grade': {}},
            },
        },
        'teams': [
            {
                'team_id': 'offline_market',
                'display_name': '线下市场',
                'cash_target': 600,
                'orders_target': 60,
                'groups': [_group('留学预备', 100, 10), _group('高中', 200, 20), _group('大学', 300, 30)],
                'yoy_groups': _yoy_groups(),
                'people': [
                    _person('王昊', '留学预备', '青少组'),
                    _person('杨新宇', '高中', '高中组'),
                    _person('李进', '大学', '大学组'),
                ],
            },
            {
                'team_id': 'online_private',
                'display_name': '线上私域（虚拟人团队）',
                'cash_target': 150,
                'orders_target': 15,
                'groups': [_group('留学预备', 150, 15)],
                'yoy_groups': _yoy_groups(),
                'people': [_person('潘体学', '留学预备', '小初提能组')],
            },
            {
                'team_id': 'online_platform',
                'display_name': '线上平台',
                'cash_target': 80,
                'orders_target': 8,
                'groups': [_group('大学', 80, 8)],
                'yoy_groups': _yoy_groups(),
                'people': [_person('平台同学', '大学', '大学组')],
            },
            {
                'team_id': 'market_total',
                'display_name': '市场总计',
                'cash_target': 830,
                'orders_target': 83,
                'groups': [_group('留学预备', 250, 25), _group('高中', 200, 20), _group('大学', 380, 38)],
                'yoy_groups': _yoy_groups(),
                'people': [],
            },
        ],
    }


def _artifact(dashboard=None):
    return {
        'schema_version': 'dashboard_artifact.v1',
        'artifact_id': 'dashboard_test',
        'run_id': 'run_dashboard_test',
        'snapshot_id': 'snapshot_bi_full_20260902_r2',
        'as_of_date': '2026-09-05',
        'data_through_date': '2026-09-04',
        'created_at': '2026-09-04T08:00:00+00:00',
        'query_results': [{'rows': [['secret-other-group-row']]}],
        'errors': [],
        'dashboard': dashboard or _four_team_dashboard(),
    }


def _assert_no_foreign_team_payload(blob, booklet_team):
    foreign = {
        'online_private': ('online_platform', 'offline_market', 'market_total'),
        'online_platform': ('online_private', 'offline_market', 'market_total'),
        'offline_market': ('online_private', 'online_platform', 'market_total'),
    }[booklet_team]
    for team_id in foreign:
        assert f'"team_id": "{team_id}"' not in blob, team_id
        assert f'|{team_id}|' not in blob, team_id
    labels = {
        'online_private': '线上私域（虚拟人团队）',
        'online_platform': '线上平台',
        'offline_market': '线下市场',
        'market_total': '市场总计',
    }
    for team_id in foreign:
        assert f'"display_name": "{labels[team_id]}"' not in blob, labels[team_id]


class BookletFilterTest(unittest.TestCase):
    def test_online_private_drops_other_teams_people_drills_and_market_total(self):
        original = _four_team_dashboard()
        original_dump = json.dumps(original, ensure_ascii=False)
        filtered = filter_dashboard_for_booklet(original, 'online_private')
        self.assertEqual(original_dump, json.dumps(original, ensure_ascii=False))
        self.assertEqual([team['team_id'] for team in filtered['teams']], ['online_private'])
        self.assertEqual(filtered['booklet_team'], 'online_private')
        team = filtered['teams'][0]
        self.assertEqual(team['cash_target'], 150)
        self.assertEqual(team['orders_target'], 15)
        people_names = [person['display_name'] for person in team['people']]
        self.assertEqual(people_names, ['潘体学'])
        channel_keys = list(filtered['drilldowns']['current']['cash']['channel'])
        self.assertEqual(channel_keys, ['2026-06|online_private|留学预备|转介绍|老客转介绍'])
        self.assertTrue(all(drill_team_id(key) == 'online_private' for key in channel_keys))
        blob = json.dumps(filtered, ensure_ascii=False)
        _assert_no_foreign_team_payload(blob, 'online_private')
        self.assertNotIn('王昊', blob)
        self.assertNotIn('平台同学', blob)
        self.assertNotIn('杨新宇', blob)
        self.assertIn('潘体学', blob)

    def test_full_keeps_all_teams_including_market_total(self):
        original = _four_team_dashboard()
        filtered = filter_dashboard_for_booklet(original, 'full')
        ids = [team['team_id'] for team in filtered['teams']]
        self.assertEqual(ids, ['offline_market', 'online_private', 'online_platform', 'market_total'])
        self.assertEqual(filtered['teams'][0]['cash_target'], 600)
        self.assertIsNone(filtered.get('booklet_team'))
        blob = json.dumps(filtered, ensure_ascii=False)
        self.assertIn('"team_id": "market_total"', blob)
        self.assertIn('王昊', blob)
        self.assertIn('潘体学', blob)
        self.assertIn('平台同学', blob)

    def test_offline_market_reserved_booklet_renders_when_team_missing(self):
        original = _four_team_dashboard()
        original['teams'] = [team for team in original['teams'] if team['team_id'] != 'offline_market']
        filtered = filter_dashboard_for_booklet(original, 'offline_market')
        self.assertEqual([team['team_id'] for team in filtered['teams']], ['offline_market'])
        self.assertEqual(filtered['teams'][0]['groups'], [])
        self.assertEqual(filtered['teams'][0]['people'], [])
        blob = json.dumps(filtered, ensure_ascii=False)
        _assert_no_foreign_team_payload(blob, 'offline_market')

    def test_unknown_and_legacy_group_booklets_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown booklet'):
            filter_dashboard_for_booklet(_four_team_dashboard(), 'intern')
        for legacy in ('liuxue', 'gaozhong', 'daxue'):
            self.assertNotIn(legacy, BOOKLET_IDS)
            with self.assertRaisesRegex(ValueError, 'unknown booklet'):
                filter_dashboard_for_booklet(_four_team_dashboard(), legacy)

    def test_team_chrome_keeps_business_groups_and_names_the_board(self):
        chrome = booklet_chrome('online_private')
        self.assertEqual(chrome['special_board_link'], '')
        self.assertIn('线上私域（虚拟人团队）', chrome['page_title'])
        self.assertIn('线上私域（虚拟人团队）分册', chrome['period_line'])
        self.assertIn('value="留学预备"', chrome['people_group_options'])
        self.assertIn('value="高中"', chrome['people_group_options'])
        self.assertIn('value="大学"', chrome['people_group_options'])
        self.assertEqual(json.loads(chrome['school_grade_groups_json']), ['高中', '大学'])
        full = booklet_chrome('full')
        self.assertEqual(full['page_title'], 'Cyber Shackles - 语培完成进度看板')
        self.assertIn('online_market_special.html', full['special_board_link'])
        self.assertIn('渠道同比和年级同比按青少、初中、高中、大学', full['grade_kicker'])


class BookletRenderTest(unittest.TestCase):
    def test_online_private_html_has_no_other_team_data(self):
        page = render_html(_artifact(), booklet='online_private')
        self.assertIn('线上私域（虚拟人团队）分册', page)
        self.assertIn('潘体学', page)
        self.assertNotIn('王昊', page)
        self.assertNotIn('平台同学', page)
        self.assertNotIn('secret-other-group-row', page)
        self.assertNotIn('query_results', page)
        _assert_no_foreign_team_payload(page, 'online_private')

    def test_online_platform_and_offline_market_are_isolated(self):
        platform = render_html(_artifact(), booklet='online_platform')
        offline = render_html(_artifact(), booklet='offline_market')
        self.assertIn('平台同学', platform)
        self.assertNotIn('潘体学', platform)
        self.assertNotIn('王昊', platform)
        _assert_no_foreign_team_payload(platform, 'online_platform')
        self.assertIn('王昊', offline)
        self.assertIn('杨新宇', offline)
        self.assertIn('李进', offline)
        self.assertNotIn('潘体学', offline)
        self.assertNotIn('平台同学', offline)
        _assert_no_foreign_team_payload(offline, 'offline_market')

    def test_full_html_still_embeds_all_teams(self):
        page = render_html(_artifact(), booklet='full')
        self.assertIn('"team_id": "offline_market"', page)
        self.assertIn('"team_id": "online_private"', page)
        self.assertIn('"team_id": "online_platform"', page)
        self.assertIn('"team_id": "market_total"', page)
        self.assertIn('王昊', page)
        self.assertIn('潘体学', page)
        self.assertIn('平台同学', page)
        self.assertIn('渠道同比和年级同比按青少、初中、高中、大学', page)
        self.assertIn('渠道同期对比', page)
        self.assertIn('id="channel-matrix"', page)
        self.assertIn('展开团队', page)
        self.assertIn('renderTeamShareTable', page)

    def test_render_writes_named_team_booklets_and_default_artifact_html(self):
        artifact = _artifact()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'artifact.json'
            path.write_text(json.dumps(artifact, ensure_ascii=False), encoding='utf-8')
            default = render(path)
            self.assertEqual(Path(default['output']).name, 'artifact.html')
            private = render(path, booklet='online_private')
            self.assertEqual(Path(private['output']).name, 'online_private.html')
            self.assertTrue(Path(private['output']).is_file())
            all_booklets = render_all_booklets(path)
            names = {Path(item).name for item in all_booklets['outputs']}
            self.assertEqual(
                names,
                {'full.html', 'online_private.html', 'online_platform.html', 'offline_market.html'},
            )
            self.assertEqual(tuple(all_booklets['booklets']), BOOKLET_IDS)
            private_page = Path(private['output']).read_text(encoding='utf-8')
            _assert_no_foreign_team_payload(private_page, 'online_private')
            original = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(len(original['dashboard']['teams']), 4)


class BookletDeployConfigTest(unittest.TestCase):
    def test_nginx_and_publish_whitelist_team_booklets_only(self):
        root = Path(__file__).resolve().parents[1]
        nginx = (root / 'deploy' / 'nginx-dashboard-http.conf').read_text(encoding='utf-8')
        publish = (root / 'deploy' / 'publish_static_dashboard.sh').read_text(encoding='utf-8')
        example = (root / 'deploy' / 'user-booklets.map.example').read_text(encoding='utf-8')
        self.assertIn('BOOKLETS=(full online_private online_platform offline_market)', publish)
        self.assertIn('location ~ ^/(full|online_private|online_platform|offline_market)\\.html$', nginx)
        self.assertIn('try_files $dashboard_booklet_file =403;', nginx)
        self.assertNotIn('$dashboard_booklet_ok', nginx)
        self.assertIn('/notify/[0-9a-f]{32}/(offline_youth|offline_high_school|offline_university|online_private|online_platform)/people\\.png$', nginx)
        self.assertIn('/notify/[0-9a-f]{32}/(offline_youth|offline_high_school|offline_university|online_private|online_platform)/details\\.xlsx$', nginx)
        notify_publish = (root.parent / 'monitoring_product' / 'deploy' / 'publish_notify_assets.sh').read_text(encoding='utf-8')
        self.assertIn('NOTIFY_TOKEN', notify_publish)
        self.assertIn('people.png', notify_publish)
        self.assertIn('details.xlsx', notify_publish)
        self.assertNotIn('scp artifact.json', notify_publish)
        self.assertNotIn('monitoring_product.notify', publish)
        for booklet in BOOKLET_IDS:
            self.assertIn(f'"/{booklet}.html/{booklet}" /{booklet}.html;', nginx)
            self.assertIn(f'{booklet}.html', publish)
        for legacy in ('liuxue', 'gaozhong', 'daxue'):
            self.assertNotIn(f'{legacy}.html/{legacy}', nginx)
            self.assertNotIn(f'BOOKLETS=(full liuxue gaozhong daxue)', publish)
            self.assertNotIn(f'{legacy} {legacy};', example)
        self.assertIn('online_private', example)
        self.assertIn('full | online_private | online_platform | offline_market', example)
