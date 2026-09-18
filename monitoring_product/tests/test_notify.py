import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from monitoring_product.digest import NOTIFY_CHANNEL_IDS
from monitoring_product.notify import send, run_detail_query



class NotifyCliTest(unittest.TestCase):
    def setUp(self):
        os.environ['NOTIFY_FORCE_PIL'] = '1'
        self.ledger = mock.patch('monitoring_product.notify.fetch_channel_ledger', return_value={
            'orders': {'columns': ['归属人', 'ID'], 'rows': [['潘体学', 'test-order']]},
            'cash': {'columns': ['归属人', '报入现金收入', '学员编号'], 'rows': []},
        }).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch('monitoring_product.notify.load_env_file').start()
        mock.patch('monitoring_product.notify.find_warehouse', return_value=Path('/test/warehouse.duckdb')).start()

    def test_query_failure_blocks_whole_batch_before_render_upload_or_send(self):
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run), tempfile.TemporaryDirectory() as directory:

                self.ledger.side_effect = [self.ledger.return_value, ValueError('detail query failed')]
                with mock.patch('monitoring_product.notify.write_people_image') as rendered, \
                     mock.patch('monitoring_product.notify.upload_notify_assets') as uploaded, \
                     mock.patch('monitoring_product.notify.post_dingtalk') as posted:
                    with self.assertRaisesRegex(ValueError, 'detail query failed'):
                        send(directory, snapshot_id='snapshot_test', run_id='run_test', as_of_date='2026-09-07', data_through_date='2026-09-06', env_file='/test/credentials', dry_run=dry_run, output_dir=Path(directory) / 'notify')
                rendered.assert_not_called()
                uploaded.assert_not_called()
                posted.assert_not_called()

    def test_sent_text_and_files_use_same_refreshed_actuals(self):
        from openpyxl import load_workbook
        from monitoring_product.notify_render import write_people_image
        with tempfile.TemporaryDirectory() as directory:

            output = Path(directory) / 'notify'
            with mock.patch.dict(os.environ, {'DINGTALK_WEBHOOK_ONLINE_PRIVATE': 'https://example.invalid'}), \
                 mock.patch('monitoring_product.notify.upload_notify_assets'), \
                 mock.patch('monitoring_product.notify.post_dingtalk') as posted, \
                 mock.patch('monitoring_product.notify.write_people_image', wraps=write_people_image) as rendered:
                send(directory, snapshot_id='snapshot_test', run_id='run_test', as_of_date='2026-09-07', data_through_date='2026-09-06', env_file='/test/credentials', team_ids=('online_private',), output_dir=output)
            text = posted.call_args.args[3]
            self.assertIn('潘体学 1/25', text)
            digest = rendered.call_args.args[0]
            person = next(p for p in digest['people'] if p['display_name'] == '潘体学')
            self.assertEqual(person['orders_actual'], 1)
            preview = (output / 'online_private' / 'message.md').read_text(encoding='utf-8')
            self.assertIn('潘体学 1/25', preview)
            workbook = load_workbook(output / 'online_private' / 'details.xlsx')
            try:
                row = next(r for r in workbook['人员进度'].iter_rows(values_only=True) if r[0] == '潘体学')
                self.assertEqual(row[3], 1)
            finally:
                workbook.close()

    def test_missing_query_result_is_error_not_empty_success(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch('monitoring_product.notify.find_warehouse', return_value=Path(directory) / 'warehouse.duckdb'), \
             mock.patch('subprocess.run', return_value=mock.Mock(returncode=0, stdout='{"status":"passed"}', stderr='')):
            sql = Path(directory) / 'test.sql'
            sql.write_text('SELECT 1')
            with self.assertRaisesRegex(ValueError, 'unsupported or failed controlled query response'):
                run_detail_query(directory, 'snapshot_test', 'run_test', sql, [], directory)

    def tearDown(self):
        os.environ.pop('NOTIFY_FORCE_PIL', None)

    def test_dry_run_writes_all_team_files_and_does_not_post(self):
        with tempfile.TemporaryDirectory() as directory:

            output = Path(directory) / 'notify'
            with mock.patch('monitoring_product.notify.post_dingtalk') as posted:
                with mock.patch('monitoring_product.notify.upload_notify_assets') as uploaded:
                    result = send(directory, snapshot_id='snapshot_test', run_id='run_test', as_of_date='2026-09-07', data_through_date='2026-09-06', env_file='/test/credentials', dry_run=True, output_dir=output)
            posted.assert_not_called()
            uploaded.assert_not_called()
            self.assertEqual(result['status'], 'dry_run')
            self.assertEqual([item['team_id'] for item in result['teams']], list(NOTIFY_CHANNEL_IDS))
            for team_id in NOTIFY_CHANNEL_IDS:
                team_dir = output / team_id
                self.assertTrue((team_dir / 'people.png').stat().st_size > 0)
                self.assertTrue((team_dir / 'details.xlsx').stat().st_size > 0)
                html = (team_dir / 'people.html').read_text(encoding='utf-8')
                markdown = (team_dir / 'message.md').read_text(encoding='utf-8')
                self.assertIn('people-panel', html)
                self.assertNotIn(f'{team_id}.html', markdown)
                self.assertNotIn('full.html', markdown)
                self.assertNotIn('oapi.dingtalk.com', markdown)
            private_html = (output / 'online_private' / 'people.html').read_text(encoding='utf-8')
            self.assertIn('潘体学', private_html)
            self.assertNotIn('杨玉林', private_html)
            self.assertNotIn('王昊', private_html)
            offline_html = (output / 'offline_youth' / 'people.html').read_text(encoding='utf-8')
            self.assertIn('王昊', offline_html)
            self.assertNotIn('潘体学', offline_html)
            self.assertNotIn('杨玉林', offline_html)

    def test_single_team_filter(self):
        with tempfile.TemporaryDirectory() as directory:

            result = send(directory, snapshot_id='snapshot_test', run_id='run_test', as_of_date='2026-09-07', data_through_date='2026-09-06', env_file='/test/credentials', team_ids=('online_private',), dry_run=True, output_dir=Path(directory) / 'notify')
            self.assertEqual([item['team_id'] for item in result['teams']], ['online_private'])
            self.assertTrue((Path(directory) / 'notify' / 'online_private' / 'people.png').exists())
            self.assertFalse((Path(directory) / 'notify' / 'offline_youth').exists())

    def test_offline_market_alias_builds_three_groups(self):
        with tempfile.TemporaryDirectory() as directory:

            result = send(directory, snapshot_id='snapshot_test', run_id='run_test', as_of_date='2026-09-07', data_through_date='2026-09-06', env_file='/test/credentials', team_ids=('offline_market',), dry_run=True, output_dir=Path(directory) / 'notify')
            self.assertEqual(
                [item['team_id'] for item in result['teams']],
                ['offline_youth', 'offline_high_school', 'offline_university'],
            )
            youth = (Path(directory) / 'notify' / 'offline_youth' / 'people.html').read_text(encoding='utf-8')
            university = (Path(directory) / 'notify' / 'offline_university' / 'people.html').read_text(encoding='utf-8')
            self.assertIn('王昊', youth)
            self.assertNotIn('李进', youth)
            self.assertNotIn('杨新宇', youth)
            self.assertIn('现金目标', youth)
            self.assertNotIn('人头目标', youth)
            self.assertIn('李进', university)
            self.assertIn('人头目标', university)
            self.assertNotIn('现金目标', university)
