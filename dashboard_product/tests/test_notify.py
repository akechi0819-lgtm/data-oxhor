import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dashboard_product.digest import NOTIFY_CHANNEL_IDS
from dashboard_product.notify import send
from test_digest import _artifact


class NotifyCliTest(unittest.TestCase):
    def setUp(self):
        os.environ['NOTIFY_FORCE_PIL'] = '1'

    def tearDown(self):
        os.environ.pop('NOTIFY_FORCE_PIL', None)

    def test_dry_run_writes_all_team_files_and_does_not_post(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / 'artifact.json'
            artifact.write_text(json.dumps(_artifact(), ensure_ascii=False), encoding='utf-8')
            output = Path(directory) / 'notify'
            with mock.patch('dashboard_product.notify.post_dingtalk') as posted:
                with mock.patch('dashboard_product.notify.upload_notify_assets') as uploaded:
                    result = send(artifact, dry_run=True, output_dir=output)
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
            self.assertIn('杨玉林', private_html)
            self.assertNotIn('王昊', private_html)
            offline_html = (output / 'offline_youth' / 'people.html').read_text(encoding='utf-8')
            self.assertIn('王昊', offline_html)
            self.assertNotIn('杨玉林', offline_html)

    def test_single_team_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / 'artifact.json'
            artifact.write_text(json.dumps(_artifact(), ensure_ascii=False), encoding='utf-8')
            result = send(artifact, team_ids=('online_private',), dry_run=True, output_dir=Path(directory) / 'notify')
            self.assertEqual([item['team_id'] for item in result['teams']], ['online_private'])
            self.assertTrue((Path(directory) / 'notify' / 'online_private' / 'people.png').exists())
            self.assertFalse((Path(directory) / 'notify' / 'offline_youth').exists())

    def test_offline_market_alias_builds_three_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / 'artifact.json'
            artifact.write_text(json.dumps(_artifact(), ensure_ascii=False), encoding='utf-8')
            result = send(artifact, team_ids=('offline_market',), dry_run=True, output_dir=Path(directory) / 'notify')
            self.assertEqual(
                [item['team_id'] for item in result['teams']],
                ['offline_youth', 'offline_high_school', 'offline_university'],
            )
            youth = (Path(directory) / 'notify' / 'offline_youth' / 'people.html').read_text(encoding='utf-8')
            self.assertIn('王昊', youth)
            self.assertNotIn('李进', youth)
            self.assertNotIn('杨新宇', youth)
