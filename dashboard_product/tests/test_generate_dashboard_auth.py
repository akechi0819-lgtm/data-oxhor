import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import openpyxl
except ImportError:
    openpyxl = None

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy' / 'generate_dashboard_auth.py'


def _load_module():
    spec = importlib.util.spec_from_file_location('generate_dashboard_auth', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_book(path: Path, rows):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(['用户名', '密码', '权限'])
    for row in rows:
        sheet.append(list(row))
    workbook.save(path)


@unittest.skipUnless(openpyxl is not None, 'openpyxl required to build fixture password books')
class GenerateDashboardAuthTest(unittest.TestCase):
    def test_secrets_directory_defaults_and_override(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            module = _load_module()
            self.assertEqual(module.SECRETS_DIR, Path.home() / '.config/cowh-ops/secrets')
            self.assertEqual(module.DEFAULT_PASSWORD_BOOK.parent, module.SECRETS_DIR)
        with mock.patch.dict(os.environ, {'COWH_SECRETS_DIR': '/tmp/cowh-fixture'}, clear=True):
            module = _load_module()
            self.assertEqual(module.SECRETS_DIR, Path('/tmp/cowh-fixture'))
            self.assertEqual(module.DEFAULT_PASSWORD_BOOK.parent, module.SECRETS_DIR)

    def test_imports_password_book_and_never_prints_passwords(self):
        module = _load_module()
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'secrets'
            book = Path(directory) / 'book.xlsx'
            secret = 'fixture-password-never-print-9Kx'
            _write_book(
                book,
                [
                    ('alice', secret, 'all'),
                    ('bob', 'other-secret-zzz', '虚拟人'),
                    ('cara', 'platform-secret-zzz', '平台'),
                    ('dana', 'offline-secret-zzz', '线下'),
                ],
            )
            result = module.generate(dest, password_book=book)
            self.assertEqual(
                [(row['username'], row['permission']) for row in result['accounts']],
                [('alice', 'all'), ('bob', 'all'), ('cara', 'all'), ('dana', 'all')],
            )
            htpasswd = (dest / 'htpasswd').read_text(encoding='utf-8')
            self.assertIn('alice:$apr1$', htpasswd)
            self.assertNotIn('admin', htpasswd)
            self.assertNotIn('liuxue', htpasswd)
            self.assertNotIn('gaozhong', htpasswd)
            self.assertNotIn('daxue', htpasswd)
            self.assertFalse((dest / 'initial-passwords').exists())
            self.assertEqual(stat.S_IMODE(os.stat(dest / 'htpasswd').st_mode), 0o600)
            dumped = str(result)
            self.assertNotIn(secret, dumped)
            self.assertNotIn('other-secret-zzz', dumped)

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    '--dest',
                    str(dest),
                    '--password-book',
                    str(book),
                    '--force',
                ],
                cwd=str(Path(__file__).resolve().parents[2]),
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn('usernames: alice, bob, cara, dana', proc.stdout)
            self.assertNotIn(secret, proc.stdout)
            self.assertNotIn('other-secret-zzz', proc.stdout)
            self.assertNotIn(secret, proc.stderr)
            self.assertIn('passwords are not printed', proc.stdout)

    def test_any_password_book_permission_maps_to_full(self):
        module = _load_module()
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'secrets'
            book = Path(directory) / 'book.xlsx'
            _write_book(book, [('alice', 'secret-value', 'intern')])
            result = module.generate(dest, password_book=book)
            self.assertEqual(result['accounts'][0]['permission'], 'all')
