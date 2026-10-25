from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from dashboard_product.management.publication import PACKAGE_FILES, SEALED_SITE_FILES, package


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ManagementPublicationTests(unittest.TestCase):
    def make_batch(self, parent: Path, *, public_override: dict | None = None) -> Path:
        batch = parent / 'batch'
        site = batch / 'site'
        site.mkdir(parents=True)
        metadata = {
            'run_id': 'run_test_20261001',
            'snapshot_id': 'snapshot_test_20260929',
            'data_through': '2026-09-28',
        }
        public = public_override or {
            'schema_version': 'dashboard_rebuild.v1',
            'metadata': metadata,
            'periods': [{'id': 'M09'}],
        }

        for name in SEALED_SITE_FILES:
            path = site / name
            if name.endswith('.json'):
                data = public
                path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            elif name == 'index.html':
                path.write_text('<!doctype html><link rel="stylesheet" href="./styles.css"><script src="./app.js"></script>', encoding='utf-8')
            elif name in ('prep_high.html', 'university.html'):
                path.write_text('<!doctype html><link rel="stylesheet" href="./boards.css"><script src="./boards.js"></script><a href="./index.html">home</a>', encoding='utf-8')
            elif name == 'online.html':
                embedded = json.dumps(public, ensure_ascii=False, separators=(',', ':'))
                path.write_text('<!doctype html><script id="dashboard-data" type="application/json">' + embedded + '</script>', encoding='utf-8')
            else:
                path.write_text('/* static asset */\n', encoding='utf-8')

        notifications = {'metadata': metadata, 'data_through': metadata['data_through'], 'messages': []}
        online = public
        details = {'metadata': metadata, 'records': []}
        ref_files = {
            'notifications.json': notifications,
            'online_shared_result.json': online,
            'details.json': details,
        }
        refs = {}
        for name, payload in ref_files.items():
            path = batch / name
            content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            path.write_bytes(content)
            refs[name] = {'path': name, 'sha256': hashlib.sha256(content).hexdigest()}
        shared = {
            'metadata': metadata,
            'notifications_ref': refs['notifications.json'],
            'online_ref': refs['online_shared_result.json'],
            'details_ref': {**refs['details.json'], 'record_count': 0},
        }
        (batch / 'shared_result.json').write_text(json.dumps(shared), encoding='utf-8')
        return batch / 'shared_result.json'

    def remote_verifier_source(self) -> str:
        script = (PROJECT_ROOT / 'dashboard_product/deploy/publish_management_dashboard.sh').read_text(encoding='utf-8')
        start_marker = "read -r -d '' remote_verify_py <<'PY' || true\n"
        end_marker = '\nPY\nremote_verify_b64='
        return script.split(start_marker, 1)[1].split(end_marker, 1)[0]

    def test_cli_packages_only_allowlisted_public_files_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared_result = self.make_batch(root)
            output = root / 'release-package'
            completed = subprocess.run(
                [sys.executable, '-m', 'dashboard_product.management.publication',
                 '--shared-result', str(shared_result), '--output-dir', str(output)],
                cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
            )
            result = json.loads(completed.stdout)
            manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(result['status'], 'packaged')
            self.assertEqual({p.name for p in output.iterdir()}, PACKAGE_FILES | {'manifest.json'})
            self.assertEqual({item['path'] for item in manifest['files']}, PACKAGE_FILES)
            for item in manifest['files']:
                path = output / item['path']
                self.assertEqual(path.stat().st_size, item['size_bytes'])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item['sha256'])
            self.assertFalse((output / 'shared_result.json').exists())
            self.assertFalse((output / 'notifications.json').exists())
            self.assertFalse((output / 'details.json').exists())

    def test_package_refuses_a_changed_private_reference_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared_result = self.make_batch(root)
            with (root / 'batch' / 'notifications.json').open('a', encoding='utf-8') as stream:
                stream.write(' ')
            with self.assertRaisesRegex(ValueError, 'sha256'):
                package(shared_result, root / 'package')

    def test_package_refuses_a_matching_hash_with_wrong_reference_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared_result = self.make_batch(root)
            batch = root / 'batch'
            online_path = batch / 'online_shared_result.json'
            online = json.loads(online_path.read_text(encoding='utf-8'))
            online['metadata']['snapshot_id'] = 'snapshot_other'
            content = json.dumps(online, ensure_ascii=False).encode('utf-8')
            online_path.write_bytes(content)
            shared = json.loads(shared_result.read_text(encoding='utf-8'))
            shared['online_ref']['sha256'] = hashlib.sha256(content).hexdigest()
            shared_result.write_text(json.dumps(shared), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'identity'):
                package(shared_result, root / 'package')

    def test_package_refuses_source_record_in_display_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bad = {
                'schema_version': 'dashboard_rebuild.v1',
                'metadata': {'run_id': 'run_test_20261001', 'snapshot_id': 'snapshot_test_20260929', 'data_through': '2026-09-28'},
                'periods': [{'source_record': {'工单ID': 'private'}}],
            }
            shared_result = self.make_batch(root, public_override=bad)
            with self.assertRaisesRegex(ValueError, 'private evidence fields'):
                package(shared_result, root / 'package')

    def test_package_refuses_network_fetches_in_static_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared_result = self.make_batch(root)
            (root / 'batch' / 'site' / 'app.js').write_text('fetch("https://example.invalid/data.json")', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'outside the static dashboard package'):
                package(shared_result, root / 'package')

    def test_package_refuses_missing_resource_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared_result = self.make_batch(root)
            (root / 'batch' / 'site' / 'app.js').unlink()
            with self.assertRaisesRegex(ValueError, 'missing required resources'):
                package(shared_result, root / 'package')

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared_result = self.make_batch(root)
            asset = root / 'batch' / 'site' / 'app.js'
            asset.unlink()
            outside = root / 'app.js'
            outside.write_text('/* outside */', encoding='utf-8')
            asset.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                package(shared_result, root / 'package')

    def test_shell_dry_run_never_reads_credentials_or_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared_result = self.make_batch(root)
            result = subprocess.run(
                ['bash', 'dashboard_product/deploy/publish_management_dashboard.sh', '--dry-run'],
                cwd=PROJECT_ROOT,
                env={**os.environ, 'SHARED_RESULT': str(shared_result), 'ENV_FILE': str(root / 'absent.env')},
                capture_output=True, text=True, check=True,
            )
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt['status'], 'validated')
            self.assertFalse(receipt['uploaded'])
            self.assertIn('manifest_sha256', receipt)

    def test_retired_staging_refuses_before_reading_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared_result = self.make_batch(root)
            result = subprocess.run(
                ['bash', 'dashboard_product/deploy/publish_management_dashboard.sh'],
                cwd=PROJECT_ROOT,
                env={**os.environ, 'SHARED_RESULT': str(shared_result),
                     'ALLOW_LEGACY_STATIC_PUBLISH': '0', 'ENV_FILE': str(root / 'absent.env')},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn('Legacy static publication is retired', result.stderr)
            self.assertNotIn('missing server environment', result.stderr)

    def test_shell_staging_uses_mocked_pexpect_transport_and_returns_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared_result = self.make_batch(root)
            env_file = root / 'server.env'
            env_file.write_text(
                'SERVER_HOST=stage.invalid\nSERVER_PORT=2222\n'
                'SERVER_USER=publisher\nSERVER_PASSWORD=fake-password\n',
                encoding='utf-8',
            )
            mock_dir = root / 'mock'
            mock_dir.mkdir()
            calls_path = root / 'transport-calls.jsonl'
            (mock_dir / 'sitecustomize.py').write_text(
                'import json, os\n'
                'import monitoring_product.delivery_transport as transport\n'
                'def mock_run(command, env_file=None, timeout=180):\n'
                '    with open(os.environ["MOCK_TRANSPORT_CALLS"], "a", encoding="utf-8") as f:\n'
                '        f.write(json.dumps({"command": command, "env_file": str(env_file), "timeout": timeout}) + "\\n")\n'
                'transport.run_password_command = mock_run\n',
                encoding='utf-8',
            )
            env = {
                **os.environ,
                'SHARED_RESULT': str(shared_result),
                'ENV_FILE': str(env_file),
                'MOCK_TRANSPORT_CALLS': str(calls_path),
                'ALLOW_LEGACY_STATIC_PUBLISH': '1',
                'PYTHONPATH': str(mock_dir) + os.pathsep + os.environ.get('PYTHONPATH', ''),
            }
            result = subprocess.run(
                ['bash', 'dashboard_product/deploy/publish_management_dashboard.sh'],
                cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, check=True,
            )
            receipt = json.loads(result.stdout)
            calls = [json.loads(line) for line in calls_path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(receipt['status'], 'staged')
            self.assertEqual(receipt['release_dir'], '/var/www/dashboard/releases/run_test_20261001')
            self.assertFalse(receipt['live_root_changed'])
            self.assertEqual(len(calls), 3)
            self.assertEqual([call['timeout'] for call in calls], [60, 900, 180])
            self.assertEqual([Path(call['command'][0]).name for call in calls], ['ssh', 'scp', 'ssh'])
            self.assertTrue(all(call['env_file'] == str(env_file) for call in calls))
            self.assertTrue(all('StrictHostKeyChecking=yes' in call['command'] for call in calls))
            self.assertIn('/var/www/dashboard/releases/run_test_20261001', calls[0]['command'][-1])
            self.assertIn('python3 -c', calls[2]['command'][-1])
            self.assertIn('mv --', calls[2]['command'][-1])
            script = (PROJECT_ROOT / 'dashboard_product/deploy/publish_management_dashboard.sh').read_text(encoding='utf-8')
            self.assertNotIn('/usr/bin/expect', script)
            self.assertIn('from monitoring_product.delivery_transport import run_password_command', script)
            self.assertNotIn('fake-password', result.stdout + result.stderr)

    def test_remote_manifest_verifier_runs_locally_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared_result = self.make_batch(root)
            output = root / 'release-package'
            package(shared_result, output)
            manifest_path = output / 'manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            identity = [manifest['run_id'], manifest['snapshot_id'], manifest['data_through'], manifest_hash]
            encoded = base64.b64encode(json.dumps(identity, separators=(',', ':')).encode()).decode()
            verifier = self.remote_verifier_source()
            completed = subprocess.run(
                [sys.executable, '-c', verifier, str(output), encoded],
                cwd=PROJECT_ROOT, capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn('manifest hashes verified', completed.stdout)

            identity[2] = '2026-09-27'
            wrong_identity = base64.b64encode(json.dumps(identity, separators=(',', ':')).encode()).decode()
            rejected = subprocess.run(
                [sys.executable, '-c', verifier, str(output), wrong_identity],
                cwd=PROJECT_ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)


if __name__ == '__main__':
    unittest.main()
