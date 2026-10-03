from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from dashboard_product.management.publication import PACKAGE_FILES


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / 'dashboard_product/deploy/activate_management_dashboard.sh'
CONFIG = PROJECT_ROOT / 'dashboard_product/deploy/nginx-management-dashboard.conf'
IDENTITY = {
    'run_id': 'run_activation_test_20261002',
    'snapshot_id': 'snapshot_activation_test',
    'data_through': '2026-10-01',
}


class ManagementActivationTests(unittest.TestCase):
    def make_release(self, parent: Path) -> tuple[Path, str]:
        release = parent / IDENTITY['run_id']
        release.mkdir(parents=True)
        entries = []
        for name in sorted(PACKAGE_FILES):
            content = (f'fixture:{name}\n').encode()
            (release / name).write_bytes(content)
            entries.append({'path': name, 'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
        manifest = {
            'schema_version': 'management_dashboard_release.v1',
            **IDENTITY,
            'files': entries,
        }
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()
        (release / 'manifest.json').write_bytes(manifest_bytes)
        return release, hashlib.sha256(manifest_bytes).hexdigest()

    def setUp_remote_mock(self, root: Path, *, fail_first_reload: bool = False,
                          fail_first_test: bool = False) -> dict[str, str]:
        mock_dir = root / 'mock-python'
        mock_dir.mkdir()
        log = root / 'transport-calls.jsonl'
        sitecustomize = r'''import json, os, shutil, subprocess
from pathlib import Path
import monitoring_product.delivery_transport as transport
def mock_run(command, env_file=None, timeout=180):
    with open(os.environ['MOCK_TRANSPORT_CALLS'], 'a', encoding='utf-8') as stream:
        stream.write(json.dumps({'command': command, 'env_file': str(env_file), 'timeout': timeout}) + '\n')
    if command[0] == '/usr/bin/scp':
        source = Path(command[-2])
        target = Path(command[-1].split(':', 1)[1])
        shutil.copy2(source, target)
    return
transport.run_password_command = mock_run
'''
        (mock_dir / 'sitecustomize.py').write_text(sitecustomize, encoding='utf-8')

        bin_dir = root / 'mock-bin'
        bin_dir.mkdir()
        counter = root / 'nginx-reload-count'
        test_counter = root / 'nginx-test-count'
        nginx = bin_dir / 'nginx'
        nginx.write_text(
            '#!/bin/sh\n'
            'if [ "$1" = "-t" ]; then\n'
            '  n=0; test ! -f "$MOCK_NGINX_TEST_COUNT" || n=$(cat "$MOCK_NGINX_TEST_COUNT"); n=$((n+1)); echo "$n" > "$MOCK_NGINX_TEST_COUNT"\n'
            '  if [ "${MOCK_FAIL_FIRST_TEST:-0}" = "1" ] && [ "$n" = "1" ]; then echo "mock config invalid" >&2; exit 1; fi\n'
            'fi\n'
            'if [ "$1" = "-s" ] && [ "${2:-}" = "reload" ]; then\n'
            '  n=0; test ! -f "$MOCK_NGINX_RELOAD_COUNT" || n=$(cat "$MOCK_NGINX_RELOAD_COUNT"); n=$((n+1)); echo "$n" > "$MOCK_NGINX_RELOAD_COUNT"\n'
            '  if [ "${MOCK_FAIL_FIRST_RELOAD:-0}" = "1" ] && [ "$n" = "1" ]; then echo "mock reload rejected" >&2; exit 1; fi\n'
            'fi\nexit 0\n',
            encoding='utf-8',
        )
        nginx.chmod(0o755)
        curl = bin_dir / 'curl'
        curl.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
        curl.chmod(0o755)

        env_file = root / 'server.env'
        env_file.write_text(
            'SERVER_HOST=stage.invalid\nSERVER_PORT=2222\n'
            'SERVER_USER=publisher\nSERVER_PASSWORD=fake-password\n',
            encoding='utf-8',
        )
        env = {
            **os.environ,
            'ENV_FILE': str(env_file),
            'MOCK_TRANSPORT_CALLS': str(log),
            'MOCK_NGINX_RELOAD_COUNT': str(counter),
            'MOCK_NGINX_TEST_COUNT': str(test_counter),
            'MOCK_FAIL_FIRST_RELOAD': '1' if fail_first_reload else '0',
            'MOCK_FAIL_FIRST_TEST': '1' if fail_first_test else '0',
            'PYTHONPATH': str(mock_dir) + os.pathsep + os.environ.get('PYTHONPATH', ''),
            'PATH': str(bin_dir) + os.pathsep + os.environ.get('PATH', ''),
        }
        return env

    def stage_fixture(self, root: Path, local_release: Path) -> dict[str, str]:
        remote_root = root / 'remote'
        remote_root.mkdir()
        remote_release = remote_root / 'releases' / IDENTITY['run_id']
        remote_release.parent.mkdir()
        shutil.copytree(local_release, remote_release)
        staging = remote_root / 'tmp'
        staging.mkdir()
        nginx_dir = remote_root / 'nginx'
        nginx_dir.mkdir()
        nginx_conf = nginx_dir / 'dashboard.conf'
        nginx_conf.write_text('old nginx config\n', encoding='utf-8')
        webroot = remote_root / 'www'
        webroot.mkdir()
        previous_release = remote_root / 'old-release'
        previous_release.mkdir()
        current = webroot / 'current'
        current.symlink_to(previous_release)
        return {
            'REMOTE_RELEASE_DIR': str(remote_release),
            'REMOTE_NGINX_CONF': str(nginx_conf),
            'REMOTE_CURRENT_LINK': str(current),
            'REMOTE_STAGING_DIR': str(staging),
            'REMOTE_PREVIOUS_RELEASE': str(previous_release),
        }

    def run_activation(self, root: Path, release: Path, manifest_sha: str,
                       remote: dict[str, str], *, fail_first_reload: bool = False) -> subprocess.CompletedProcess[str]:
        remote_for_script = {key: value for key, value in remote.items() if key != 'REMOTE_CURRENT_LINK'}
        env = {
            **self.setUp_remote_mock(root, fail_first_reload=fail_first_reload),
            'RELEASE_DIR': str(release),
            'MANIFEST_SHA': manifest_sha,
            **remote_for_script,
        }
        return subprocess.run(['bash', str(SCRIPT)], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)

    def remote_transaction_source(self) -> str:
        script = SCRIPT.read_text(encoding='utf-8')
        start = "read -r -d '' remote_activation_py <<'PY' || true\n"
        end = '\nPY\nremote_tx_b64='
        return script.split(start, 1)[1].split(end, 1)[0]

    def run_remote_transaction(self, release: Path, manifest_sha: str, config_upload: Path,
                               nginx_conf: Path, current: Path, receipt: Path,
                               config_sha: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        args = [str(release), manifest_sha, str(config_upload), str(nginx_conf), str(current),
                str(receipt), IDENTITY['run_id'], IDENTITY['snapshot_id'], IDENTITY['data_through'], config_sha]
        args_b64 = base64.b64encode(json.dumps(args, separators=(',', ':')).encode()).decode()
        source_b64 = base64.b64encode(self.remote_transaction_source().encode()).decode()
        wrapper = 'import base64,sys;exec(base64.b64decode(sys.argv[1]))'
        return subprocess.run([sys.executable, '-c', wrapper, source_b64, args_b64],
                              cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)

    def test_dry_run_validates_local_manifest_and_config_without_credentials_or_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release, manifest_sha = self.make_release(root)
            result = subprocess.run(
                ['bash', str(SCRIPT), '--dry-run'], cwd=PROJECT_ROOT,
                env={**os.environ, 'RELEASE_DIR': str(release), 'MANIFEST_SHA': manifest_sha,
                     'ENV_FILE': str(root / 'missing.env')},
                capture_output=True, text=True, check=True,
            )
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt['status'], 'validated')
            self.assertFalse(receipt['uploaded'])
            self.assertEqual(receipt['manifest_sha256'], manifest_sha)

    def test_activation_command_uses_mocked_password_transport_and_records_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release, manifest_sha = self.make_release(root)
            remote = self.stage_fixture(root, release)
            result = self.run_activation(root, release, manifest_sha, remote)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt['status'], 'activated')
            self.assertEqual(receipt['release_dir'], remote['REMOTE_RELEASE_DIR'])
            self.assertTrue(Path(receipt['receipt_file']).is_file())
            calls = [json.loads(line) for line in (root / 'transport-calls.jsonl').read_text().splitlines()]
            self.assertEqual([Path(call['command'][0]).name for call in calls], ['scp', 'ssh'])
            self.assertTrue(all(call['env_file'] == str(root / 'server.env') for call in calls))
            self.assertTrue(all('StrictHostKeyChecking=yes' in call['command'] for call in calls))
            script = SCRIPT.read_text(encoding='utf-8')
            self.assertIn('REMOTE_CURRENT_LINK="/var/www/dashboard/current"', script)
            self.assertIn("run(['nginx','-t'])", script)
            self.assertNotIn('fake-password', result.stdout + result.stderr)

    def test_nginx_reload_failure_restores_prior_root_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release, manifest_sha = self.make_release(root)
            remote = self.stage_fixture(root, release)
            nginx_conf = Path(remote['REMOTE_NGINX_CONF'])
            old_config = nginx_conf.read_bytes()
            current = Path(remote['REMOTE_CURRENT_LINK'])
            old_target = current.resolve()
            config_upload = Path(remote['REMOTE_STAGING_DIR']) / f'pawsy-management-{IDENTITY["run_id"]}.conf'
            shutil.copy2(CONFIG, config_upload)
            env = self.setUp_remote_mock(root, fail_first_reload=True)
            config_sha = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
            receipt_path = Path(str(nginx_conf) + f'.activation-{IDENTITY["run_id"]}.json')
            result = self.run_remote_transaction(Path(remote['REMOTE_RELEASE_DIR']), manifest_sha,
                                                 config_upload, nginx_conf, current, receipt_path,
                                                 config_sha, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(nginx_conf.read_bytes(), old_config)
            self.assertTrue(current.is_symlink())
            self.assertEqual(current.resolve(), old_target)
            remote_receipt = Path(remote['REMOTE_NGINX_CONF'] + f'.activation-{IDENTITY["run_id"]}.json')
            receipt = json.loads(remote_receipt.read_text())
            self.assertEqual(receipt['status'], 'failed_rolled_back')
            self.assertIn('mock reload rejected', receipt['error'])
            self.assertNotIn('fake-password', result.stdout + result.stderr)

    def test_remote_transaction_activates_by_atomic_current_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            local_release, manifest_sha = self.make_release(root)
            remote = self.stage_fixture(root, local_release)
            remote_release = Path(remote['REMOTE_RELEASE_DIR'])
            config_upload = Path(remote['REMOTE_STAGING_DIR']) / f'pawsy-management-{IDENTITY["run_id"]}.conf'
            shutil.copy2(CONFIG, config_upload)
            nginx_conf = Path(remote['REMOTE_NGINX_CONF'])
            current = Path(remote['REMOTE_CURRENT_LINK'])
            old_target = current.resolve()
            receipt_path = Path(str(nginx_conf) + f'.activation-{IDENTITY["run_id"]}.json')
            config_sha = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
            env = self.setUp_remote_mock(root)
            result = self.run_remote_transaction(remote_release, manifest_sha, config_upload,
                                                 nginx_conf, current, receipt_path, config_sha, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(current.resolve(), remote_release.resolve())
            self.assertNotEqual(old_target, current.resolve())
            self.assertEqual(nginx_conf.read_bytes(), CONFIG.read_bytes())
            self.assertEqual(json.loads(receipt_path.read_text())['status'], 'activated')

    def test_nginx_test_failure_restores_config_without_switching_current(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            local_release, manifest_sha = self.make_release(root)
            remote = self.stage_fixture(root, local_release)
            remote_release = Path(remote['REMOTE_RELEASE_DIR'])
            config_upload = Path(remote['REMOTE_STAGING_DIR']) / f'pawsy-management-{IDENTITY["run_id"]}.conf'
            shutil.copy2(CONFIG, config_upload)
            nginx_conf = Path(remote['REMOTE_NGINX_CONF'])
            old_config = nginx_conf.read_bytes()
            current = Path(remote['REMOTE_CURRENT_LINK'])
            old_target = current.resolve()
            receipt_path = Path(str(nginx_conf) + f'.activation-{IDENTITY["run_id"]}.json')
            config_sha = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
            env = self.setUp_remote_mock(root, fail_first_test=True)
            result = self.run_remote_transaction(remote_release, manifest_sha, config_upload,
                                                 nginx_conf, current, receipt_path, config_sha, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(nginx_conf.read_bytes(), old_config)
            self.assertEqual(current.resolve(), old_target)
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt['status'], 'failed_rolled_back')
            self.assertIn('mock config invalid', receipt['error'])

    def test_manifest_or_nginx_allowlist_tampering_fails_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release, manifest_sha = self.make_release(root)
            (release / 'manifest.json').write_text('{}', encoding='utf-8')
            bad_hash = subprocess.run(
                ['bash', str(SCRIPT), '--dry-run'], cwd=PROJECT_ROOT,
                env={**os.environ, 'RELEASE_DIR': str(release), 'MANIFEST_SHA': manifest_sha,
                     'ENV_FILE': str(root / 'missing.env')}, capture_output=True, text=True,
            )
            self.assertNotEqual(bad_hash.returncode, 0)


if __name__ == '__main__':
    unittest.main()
