from __future__ import annotations

import hashlib
import json
import os
import re
from types import SimpleNamespace
from contextlib import redirect_stdout
from datetime import date
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from openpyxl import load_workbook

from monitoring_product import delivery_transport as notify
from monitoring_product.shared_preview import _write_xlsx
from monitoring_product.tests.test_shared_preview import notifications_payload


AS_OF_DATE = '2026-10-01'
DATA_THROUGH = '2026-09-30'
SNAPSHOT_ID = 'snapshot_delivery_20261001'

WEBHOOK_CHANNELS = (
    'ONLINE_PRIVATE', 'ONLINE_PLATFORM', 'OFFLINE_YOUTH',
    'OFFLINE_HIGH_SCHOOL', 'OFFLINE_UNIVERSITY',
)


def _credentials_text(*, missing: str | None = None) -> str:
    values = {
        'SERVER_HOST': '192.0.2.10',
        'SERVER_PORT': '22',
        'SERVER_USER': 'notify-test',
        'SERVER_PASSWORD': 'not-a-real-password',
        'NOTIFY_PUBLIC_ORIGIN': 'https://notify.example.test',
    }
    values.update({
        f'DINGTALK_WEBHOOK_{channel}': f'https://example.test/webhook/{channel.lower()}'
        for channel in WEBHOOK_CHANNELS
    })
    if missing:
        values.pop(missing, None)
    return '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n'


def _write_shared_result(root: Path, *, run_id: str = 'run_delivery_a',
                         data_through: str = DATA_THROUGH,
                         snapshot_id: str = SNAPSHOT_ID,
                         bad_hash: bool = False) -> Path:
    payload = notifications_payload()
    virtual = next(message for message in payload['messages'] if message['id'] == 'virtual.training')
    virtual['id'] = 'virtual.mixed'
    virtual['business_line'] = 'mixed'
    payload['data_through'] = data_through
    payload['metadata'].update({
        'run_id': run_id,
        'snapshot_id': snapshot_id,
        'data_through': data_through,
        'as_of_date': AS_OF_DATE,
    })
    notifications_path = root / f'{run_id}_notifications.json'
    encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    notifications_path.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    if bad_hash:
        digest = '0' * 64
    shared_path = root / f'{run_id}_shared_result.json'
    shared_path.write_text(json.dumps({
        'metadata': {
            'run_id': run_id,
            'snapshot_id': snapshot_id,
            'data_through': data_through,
        },
        'notifications_ref': {
            'path': notifications_path.name,
            'sha256': digest,
        },
    }), encoding='utf-8')
    return shared_path


def _fake_render_notifications(payload: dict, output_dir: str | Path,
                               dashboard_base_url: str | None = None) -> dict:
    """Make deterministic local artifacts while leaving delivery behavior real."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    messages = []
    for message in payload['messages']:
        slug = re.sub(r'[^A-Za-z0-9_-]+', '-', message['id']).strip('-_').lower()
        folder = output_dir / slug
        folder.mkdir(parents=True, exist_ok=True)
        png = folder / 'message.png'
        xlsx = folder / 'details.xlsx'
        markdown = folder / 'message.md'
        png.write_bytes(f"png:{message['id']}".encode())
        xlsx.write_bytes(f"xlsx:{message['id']}".encode())
        markdown.write_text(
            f"{message['id']}\n![本地消息图片](message.png)\n"
            '[查看HTML预览](message.html)\n'
            '[下载相关工单与现金流水](details.xlsx)\n',
            encoding='utf-8',
        )
        messages.append({
            'id': message['id'],
            'channel_id': message['channel_id'],
            'title': message['title'],
            'png': str(png),
            'xlsx': str(xlsx),
            'markdown': str(markdown),
            'dashboard_url': dashboard_base_url or '',
        })
    return {
        'status': 'preview_ready',
        'data_through': payload['data_through'],
        'output_dir': str(output_dir.resolve()),
        'messages': messages,
    }


class SharedDeliveryTests(unittest.TestCase):
    def setUp(self):
        from monitoring_product import shared_delivery
        self.delivery = shared_delivery

    def test_fresh_bi_cannot_send_stale_study_abroad_source(self):
        with TemporaryDirectory() as folder:
            shared_path = _write_shared_result(Path(folder))
            shared = json.loads(shared_path.read_text())
            payload = json.loads((Path(folder) / shared['notifications_ref']['path']).read_text())
            source = {'snapshot_id': 'snapshot_study_fixture', 'start_date': '2026-09-01',
                      'through_date': '2026-09-29', 'source_sha256': 'a' * 64}
            shared['metadata']['study_abroad_source'] = source
            payload['metadata']['study_abroad_source'] = dict(source)
            self.assertEqual(len(self.delivery._validate_contract(shared, payload, AS_OF_DATE, sending=False)), 8)
            with patch.object(self.delivery, '_today_shanghai', return_value=date(2026, 10, 1)):
                with self.assertRaisesRegex(ValueError, '留学来源须覆盖至昨日'):
                    self.delivery._validate_contract(shared, payload, AS_OF_DATE, sending=True)
                payload['metadata']['study_abroad_source']['through_date'] = DATA_THROUGH
                with self.assertRaisesRegex(ValueError, 'study-abroad source does not match'):
                    self.delivery._validate_contract(shared, payload, AS_OF_DATE, sending=False)
                source['through_date'] = DATA_THROUGH
                self.assertEqual(len(self.delivery._validate_contract(shared, payload, AS_OF_DATE, sending=True)), 8)

    def test_fixed_contract_requires_high_abroad_unique_id_and_correct_channel(self):
        shared = {
            'metadata': {
                'run_id': 'run_contract', 'snapshot_id': SNAPSHOT_ID,
                'data_through': DATA_THROUGH,
            },
        }

        def fresh_payload():
            payload = notifications_payload()
            payload['data_through'] = DATA_THROUGH
            payload['metadata'].update({
                'run_id': 'run_contract',
                'snapshot_id': SNAPSHOT_ID,
                'data_through': DATA_THROUGH,
                'as_of_date': AS_OF_DATE,
            })
            virtual = next(message for message in payload['messages']
                           if message['id'] == 'virtual.training')
            virtual['id'] = 'virtual.mixed'
            virtual['business_line'] = 'mixed'
            return payload

        payload = fresh_payload()
        self.assertEqual(len(payload['messages']), 8)
        self.assertEqual(
            {message['channel_id'] for message in payload['messages']},
            {'offline_youth', 'offline_high_school', 'offline_university',
             'online_private', 'online_platform'},
        )
        self.delivery._validate_contract(shared, payload, AS_OF_DATE, sending=False)

        missing = fresh_payload()
        missing['messages'] = [message for message in missing['messages']
                               if message['id'] != 'high.abroad']
        with self.assertRaisesRegex(ValueError, 'fixed eight-message, five-channel'):
            self.delivery._validate_contract(shared, missing, AS_OF_DATE, sending=False)

        duplicate = fresh_payload()
        next(message for message in duplicate['messages']
             if message['id'] == 'high.abroad')['id'] = 'high.training'
        with self.assertRaisesRegex(ValueError, 'duplicate message id'):
            self.delivery._validate_contract(shared, duplicate, AS_OF_DATE, sending=False)

        wrong_channel = fresh_payload()
        next(message for message in wrong_channel['messages']
             if message['id'] == 'high.abroad')['channel_id'] = 'online_platform'
        with self.assertRaisesRegex(ValueError, 'offline_high_school'):
            self.delivery._validate_contract(shared, wrong_channel, AS_OF_DATE, sending=False)

    def _invoke(self, root: Path, shared_path: Path, *, state_dir: Path,
                env_file: Path | None, as_of_date: str = AS_OF_DATE,
                output_name: str = 'delivery', dry_run: bool = False) -> tuple[int, dict]:
        argv = [
            '--shared-result', str(shared_path),
            '--output-dir', str(root / output_name),
            '--as-of-date', as_of_date,
            '--state-dir', str(state_dir),
            '--dashboard-base-url', 'https://dashboard.example.test',
        ]
        if env_file is not None:
            argv.extend(['--env-file', str(env_file)])
        if dry_run:
            argv.append('--dry-run')
        captured = StringIO()
        with patch.object(self.delivery, '_today_shanghai', return_value=date.fromisoformat(as_of_date)), \
             redirect_stdout(captured):
            code = self.delivery.main(argv)
        return code, json.loads(captured.getvalue())

    def test_dry_run_does_not_read_credentials_upload_or_send(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shared_path = _write_shared_result(root)
            missing_env_file = root / 'must-not-be-read.env'
            with patch.dict(os.environ, {}, clear=True), \
                 patch('monitoring_product.shared_preview.render_notifications',
                       side_effect=_fake_render_notifications) as rendered, \
                 patch.object(notify, 'load_env_file', side_effect=AssertionError('dry-run read credentials')) as read_env, \
                 patch.object(notify, 'upload_notify_assets') as uploaded, \
                 patch.object(notify, 'post_dingtalk') as posted:
                code, result = self._invoke(
                    root, shared_path, state_dir=root / 'state', env_file=missing_env_file,
                    dry_run=True,
                )

            self.assertEqual(code, 0, result)
            self.assertEqual(result['status'], 'dry_run')
            self.assertEqual(len(result['messages']), 8)
            rendered.assert_called_once()
            read_env.assert_not_called()
            uploaded.assert_not_called()
            posted.assert_not_called()

    def test_xlsx_completion_flag_uses_team_or_person_scope(self):
        payload = notifications_payload()
        cases = (
            ('online.training', '是', None, '团队核算范围'),
            ('university.training', '否', '工单状态为回收，不计个人业绩', '个人流水'),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for message_id, expected_flag, expected_reason, scope_text in cases:
                with self.subTest(message_id=message_id):
                    message = next(row for row in payload['messages'] if row['id'] == message_id)
                    path = _write_xlsx(message, payload['data_through'], root / f'{message_id}.xlsx')
                    workbook = load_workbook(path, data_only=True)
                    sheet = workbook['工单明细']
                    headers = {cell.value: cell.column for cell in sheet[4]}
                    recalled = next(
                        row for row in range(5, sheet.max_row + 1)
                        if sheet.cell(row, headers['工单ID']).value == 'recalled-order'
                    )
                    self.assertEqual(sheet.cell(recalled, headers['是否计入工单完成']).value,
                                     expected_flag)
                    self.assertEqual(sheet.cell(recalled, headers['不计入原因']).value,
                                     expected_reason)
                    self.assertIn(scope_text, sheet.cell(2, 1).value)
                    workbook.close()

    def test_missing_one_required_credential_blocks_the_batch_before_effects(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shared_path = _write_shared_result(root)
            env_file = root / 'credentials.env'
            env_file.write_text(
                _credentials_text(missing='DINGTALK_WEBHOOK_ONLINE_PLATFORM'),
                encoding='utf-8',
            )
            with patch.dict(os.environ, {}, clear=True), \
                 patch('monitoring_product.shared_preview.render_notifications',
                       side_effect=_fake_render_notifications) as rendered, \
                 patch.object(notify, 'upload_notify_assets') as uploaded, \
                 patch.object(notify, 'post_dingtalk') as posted:
                code, result = self._invoke(
                    root, shared_path, state_dir=root / 'state', env_file=env_file,
                )

            self.assertNotEqual(code, 0)
            self.assertIn(result['status'], {'blocked', 'failed'})
            self.assertIn('DINGTALK_WEBHOOK_ONLINE_PLATFORM', json.dumps(result))
            rendered.assert_not_called()
            uploaded.assert_not_called()
            posted.assert_not_called()

    def test_missing_env_file_blocks_even_when_process_environment_has_credentials(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shared_path = _write_shared_result(root)
            missing_env_file = root / 'credentials.env'
            process_values = dict(line.split('=', 1) for line in _credentials_text().splitlines())
            with patch.dict(os.environ, process_values, clear=True), \
                 patch('monitoring_product.shared_preview.render_notifications',
                       side_effect=_fake_render_notifications) as rendered, \
                 patch.object(notify, 'load_env_file') as loaded, \
                 patch.object(notify, 'upload_notify_assets') as uploaded, \
                 patch.object(notify, 'post_dingtalk') as posted:
                code, result = self._invoke(
                    root, shared_path, state_dir=root / 'state', env_file=missing_env_file,
                )

            self.assertNotEqual(code, 0)
            self.assertEqual(result['status'], 'blocked')
            self.assertIn('existing readable regular file', result['error'])
            loaded.assert_not_called()
            rendered.assert_not_called()
            uploaded.assert_not_called()
            posted.assert_not_called()

    def test_stale_cutoff_and_notifications_hash_block_before_delivery(self):
        cases = (
            ('stale', {'data_through': '2026-09-29', 'bad_hash': False}, '2026-10-01'),
            ('hash', {'data_through': DATA_THROUGH, 'bad_hash': True}, AS_OF_DATE),
        )
        for label, options, as_of_date in cases:
            with self.subTest(case=label), TemporaryDirectory() as directory:
                root = Path(directory)
                shared_path = _write_shared_result(root, **options)
                env_file = root / 'credentials.env'
                env_file.write_text(_credentials_text(), encoding='utf-8')
                with patch.dict(os.environ, {}, clear=True), \
                     patch('monitoring_product.shared_preview.render_notifications',
                           side_effect=_fake_render_notifications) as rendered, \
                     patch.object(notify, 'upload_notify_assets') as uploaded, \
                     patch.object(notify, 'post_dingtalk') as posted:
                    code, result = self._invoke(
                        root, shared_path, state_dir=root / 'state', env_file=env_file,
                        as_of_date=as_of_date,
                    )

                self.assertNotEqual(code, 0)
                self.assertIn(result['status'], {'blocked', 'failed'})
                rendered.assert_not_called()
                uploaded.assert_not_called()
                posted.assert_not_called()

    def test_old_snapshot_with_yesterday_data_through_is_blocked(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shared_path = _write_shared_result(
                root, snapshot_id='snapshot_delivery_20260930', data_through=DATA_THROUGH,
            )
            env_file = root / 'credentials.env'
            env_file.write_text(_credentials_text(), encoding='utf-8')
            with patch.dict(os.environ, {}, clear=True), \
                 patch('monitoring_product.shared_preview.render_notifications',
                       side_effect=_fake_render_notifications) as rendered, \
                 patch.object(notify, 'upload_notify_assets') as uploaded, \
                 patch.object(notify, 'post_dingtalk') as posted:
                code, result = self._invoke(
                    root, shared_path, state_dir=root / 'state', env_file=env_file,
                )

            self.assertNotEqual(code, 0)
            self.assertEqual(result['status'], 'blocked')
            self.assertIn('不是当天新切', result['error'])
            rendered.assert_not_called()
            uploaded.assert_not_called()
            posted.assert_not_called()

    def test_same_channel_messages_get_independent_public_assets_and_rewritten_links(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shared_path = _write_shared_result(root)
            env_file = root / 'credentials.env'
            env_file.write_text(_credentials_text(), encoding='utf-8')
            uploaded_tokens = []
            staged_files = []

            def fake_upload(stage_dir, token, env_file=None, **kwargs):
                uploaded_tokens.append(token)
                staged_files.append(sorted(
                    path.relative_to(stage_dir).as_posix()
                    for path in Path(stage_dir).rglob('*') if path.is_file()
                ))
                return f'published token={token}'

            with patch.dict(os.environ, {}, clear=True), \
                 patch('monitoring_product.shared_preview.render_notifications',
                       side_effect=_fake_render_notifications), \
                 patch.object(notify, 'upload_notify_assets', side_effect=fake_upload) as uploaded, \
                 patch.object(notify, 'post_dingtalk', return_value={'status': 'sent'}) as posted:
                code, result = self._invoke(
                    root, shared_path, state_dir=root / 'state', env_file=env_file,
                )

            self.assertEqual(code, 0, result)
            self.assertEqual(result['status'], 'sent')
            self.assertEqual(len(result['messages']), 8)
            self.assertEqual(uploaded.call_count, 8)
            self.assertEqual(posted.call_count, 8)
            self.assertEqual(len(set(uploaded_tokens)), 8)
            self.assertTrue(all(any(name.endswith('/people.png') for name in files)
                                and any(name.endswith('/details.xlsx') for name in files)
                                for files in staged_files))

            message_ids = [message['id'] for message in notifications_payload()['messages']]
            message_ids[5] = 'virtual.mixed'
            texts = [call.args[3] for call in posted.call_args_list]
            self.assertEqual(len(texts), len(message_ids))
            for index in (3, 4, 6, 7):
                with self.subTest(message=message_ids[index]):
                    self.assertIn(message_ids[index], texts[index])
                    self.assertNotIn('](message.png)', texts[index])
                    self.assertNotIn('](details.xlsx)', texts[index])
                    self.assertRegex(texts[index], r'https://notify\.example\.test/notify/[^\s)]+\.png')
                    self.assertRegex(texts[index], r'https://notify\.example\.test/notify/[^\s)]+\.xlsx')

            def asset_urls(text: str) -> tuple[str, str]:
                png = re.search(r'(https://notify\.example\.test/notify/[^\s)]+\.png)', text)
                xlsx = re.search(r'(https://notify\.example\.test/notify/[^\s)]+\.xlsx)', text)
                self.assertIsNotNone(png)
                self.assertIsNotNone(xlsx)
                return png.group(1), xlsx.group(1)

            for pair in ((3, 4), (6, 7)):
                first_assets = asset_urls(texts[pair[0]])
                second_assets = asset_urls(texts[pair[1]])
                self.assertNotEqual(first_assets[0], second_assets[0])
                self.assertNotEqual(first_assets[1], second_assets[1])

    def test_successful_deliveries_are_deduped_across_a_new_run_on_the_same_date(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = _write_shared_result(root, run_id='run_delivery_first')
            env_file = root / 'credentials.env'
            env_file.write_text(_credentials_text(), encoding='utf-8')
            uploaded = []
            posted = []

            def fake_upload(stage_dir, token, env_file=None, **kwargs):
                uploaded.append(token)
                return 'published'

            def fake_post(webhook, secret, title, text):
                posted.append(title)
                return {'status': 'sent'}

            with patch.dict(os.environ, {}, clear=True), \
                 patch('monitoring_product.shared_preview.render_notifications',
                       side_effect=_fake_render_notifications), \
                 patch.object(notify, 'upload_notify_assets', side_effect=fake_upload), \
                 patch.object(notify, 'post_dingtalk', side_effect=fake_post):
                first_code, first_result = self._invoke(
                    root, first, state_dir=root / 'state', env_file=env_file,
                    output_name='first-delivery',
                )
                second = _write_shared_result(root, run_id='run_delivery_second')
                second_code, second_result = self._invoke(
                    root, second, state_dir=root / 'state', env_file=env_file,
                    output_name='second-delivery',
                )

            self.assertEqual(first_code, 0, first_result)
            self.assertEqual(first_result['status'], 'sent')
            self.assertIn(second_result['status'], {'sent', 'partial', 'blocked'})
            self.assertIn(second_code, {0, 1})
            self.assertEqual(len(posted), 8)
            self.assertEqual(len(uploaded), 8)

    def test_unknown_message_is_not_retried_and_other_pending_messages_continue(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = _write_shared_result(root, run_id='run_delivery_uncertain')
            env_file = root / 'credentials.env'
            env_file.write_text(_credentials_text(), encoding='utf-8')
            attempted_titles = []
            uploaded_tokens = []

            def fake_upload(stage_dir, token, env_file=None, **kwargs):
                uploaded_tokens.append(token)
                return 'published'

            def fake_post(webhook, secret, title, text):
                attempted_titles.append(title)
                if len(attempted_titles) == 1:
                    raise TimeoutError('connection ended after request was written')
                return {'status': 'sent'}

            with patch.dict(os.environ, {}, clear=True), \
                 patch('monitoring_product.shared_preview.render_notifications',
                       side_effect=_fake_render_notifications), \
                 patch.object(notify, 'upload_notify_assets', side_effect=fake_upload), \
                 patch.object(notify, 'post_dingtalk', side_effect=fake_post):
                first_code, first_result = self._invoke(
                    root, first, state_dir=root / 'state', env_file=env_file,
                    output_name='uncertain-first',
                )
                second = _write_shared_result(root, run_id='run_delivery_uncertain_retry')
                retry_code, retry_result = self._invoke(
                    root, second, state_dir=root / 'state', env_file=env_file,
                    output_name='uncertain-retry',
                )

            self.assertIn(first_code, {0, 1})
            self.assertIn(first_result['status'], {'partial', 'blocked', 'failed'})
            self.assertIn(retry_code, {0, 1})
            self.assertIn(retry_result['status'], {'partial', 'blocked', 'failed'})
            self.assertEqual(len(attempted_titles), 8, first_result)
            self.assertEqual(len(uploaded_tokens), 8)


class DeliveryTransportTests(unittest.TestCase):
    def _response(self, payload: dict) -> BytesIO:
        return BytesIO(json.dumps(payload).encode('utf-8'))

    def test_dingtalk_only_confirms_explicit_zero_errcode(self):
        with patch('monitoring_product.delivery_transport.urllib.request.urlopen',
                   return_value=self._response({'errcode': 0})) as urlopen:
            self.assertEqual(
                notify.post_dingtalk('https://example.test/hook', '', '标题', '正文'),
                {'status': 'sent'},
            )
            self.assertEqual(urlopen.call_args.kwargs['timeout'], 20)

    def test_dingtalk_nonzero_errcode_is_rejected(self):
        with patch('monitoring_product.delivery_transport.urllib.request.urlopen',
                   return_value=self._response({'errcode': 310000, 'errmsg': 'bad signature'})):
            with self.assertRaisesRegex(ValueError, 'bad signature'):
                notify.post_dingtalk('https://example.test/hook', '', '标题', '正文')

    def test_dingtalk_missing_errcode_is_not_treated_as_success(self):
        with patch('monitoring_product.delivery_transport.urllib.request.urlopen',
                   return_value=self._response({'errmsg': 'incomplete response'})):
            with self.assertRaisesRegex(ValueError, 'did not confirm success'):
                notify.post_dingtalk('https://example.test/hook', '', '标题', '正文')

    def test_env_file_loading_and_secret_redaction(self):
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / 'delivery.env'
            env_file.write_text(
                'DINGTALK_SECRET_OFFLINE_YOUTH=file-secret-value\n'
                'SERVER_PASSWORD=file-password-value\n',
                encoding='utf-8',
            )
            with patch.dict(os.environ, {'API_KEY_FOR_TEST': 'process-key-value'}, clear=True):
                notify.load_env_file(env_file)
                self.assertEqual(os.environ['DINGTALK_SECRET_OFFLINE_YOUTH'], 'file-secret-value')
                self.assertEqual(os.environ['SERVER_PASSWORD'], 'file-password-value')
                diagnostic = notify.redact_secrets(
                    'file-secret-value file-password-value process-key-value', env_file,
                )
            self.assertNotIn('file-secret-value', diagnostic)
            self.assertNotIn('file-password-value', diagnostic)
            self.assertNotIn('process-key-value', diagnostic)
            self.assertEqual(diagnostic.count('<redacted>'), 3)

    def test_password_command_uses_typed_argv_and_accepts_eof_exit_zero(self):
        child = Mock()
        child.before = 'completed'
        child.exitstatus = 0
        child.expect.side_effect = [0, 1]
        fake_pexpect = SimpleNamespace(EOF=object(), TIMEOUT=object(), spawn=Mock(return_value=child))
        with patch.dict('sys.modules', {'pexpect': fake_pexpect}), \
             patch.dict(os.environ, {'SERVER_PASSWORD': 'only-in-env'}, clear=True):
            result = notify.run_password_command(
                ['/usr/bin/ssh', 'example.test', 'true'], timeout=17,
            )

        self.assertIsNone(result)
        fake_pexpect.spawn.assert_called_once()
        argv = fake_pexpect.spawn.call_args.args
        self.assertEqual(argv[:2], ('/usr/bin/ssh', ['example.test', 'true']))
        self.assertEqual(fake_pexpect.spawn.call_args.kwargs['timeout'], 17)
        child.close.assert_called_once_with()
        child.sendline.assert_called_once_with('only-in-env')

    def test_password_command_failure_redacts_env_file_password(self):
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / 'delivery.env'
            env_file.write_text('SERVER_PASSWORD=private-server-password\n', encoding='utf-8')
            child = Mock()
            child.before = 'authentication failed with private-server-password'
            child.exitstatus = 255
            child.expect.return_value = 1
            fake_pexpect = SimpleNamespace(EOF=object(), TIMEOUT=object(), spawn=Mock(return_value=child))
            with patch.dict('sys.modules', {'pexpect': fake_pexpect}), \
                 patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(notify.UploadStepError) as caught:
                    notify.run_password_command(
                        ['/usr/bin/scp', 'local', 'remote'], env_file=env_file,
                    )

            message = str(caught.exception)
            self.assertIn('<redacted>', message)
            self.assertNotIn('private-server-password', message)
            self.assertEqual(caught.exception.returncode, 255)
            child.close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
