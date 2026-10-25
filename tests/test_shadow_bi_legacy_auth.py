import hashlib
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from flask import Flask
from superset.security import SupersetSecurityManager
from dashboard_product.shadow_bi.p5.legacy_passwords import read_accounts, verify_password
from dashboard_product.shadow_bi.p5.legacy_security import LegacyHtpasswdSecurityManager


class LegacyAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'original.htpasswd'
        self.encoded=subprocess.run(['/usr/bin/openssl','passwd','-apr1','-salt','fixture','-stdin'],
            input=b'fixture-only-password\n',stdout=subprocess.PIPE,check=True).stdout.decode().strip()
        self.path.write_text('LegacyName:'+self.encoded+'\n')
        self.app=Flask(__name__)
        self.app.config.update(LEGACY_HTPASSWD_PATH=str(self.path),LEGACY_SERVICE_USERS=('service_account',))
        self.user=SimpleNamespace(is_active=True)
        self.manager=object.__new__(LegacyHtpasswdSecurityManager)
        self.manager.find_user=Mock(return_value=self.user)
        self.manager.update_user_auth_stat=Mock()

    def test_original_apr1_verified_without_file_change(self):
        before=hashlib.sha256(self.path.read_bytes()).digest()
        self.assertEqual(list(read_accounts(self.path)),['LegacyName'])
        self.assertTrue(verify_password(self.encoded,'fixture-only-password'))
        self.assertFalse(verify_password(self.encoded,'incorrect'))
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(),before)

    def test_business_login_never_uses_stored_fab_password(self):
        with self.app.app_context(),patch.object(SupersetSecurityManager,'auth_user_db',return_value=self.user) as fallback:
            self.assertIsNone(self.manager.auth_user_db('LegacyName','incorrect'))
            fallback.assert_not_called()

    def test_original_username_preserved_and_email_alias_rejected(self):
        with self.app.app_context(),patch.object(SupersetSecurityManager,'auth_user_db') as fallback:
            self.assertIs(self.manager.auth_user_db('LegacyName','fixture-only-password'),self.user)
            self.manager.find_user.assert_called_with(username='LegacyName')
            self.assertIsNone(self.manager.auth_user_db('legacyname','fixture-only-password'))
            self.assertIsNone(self.manager.auth_user_db('LegacyName@localhost','fixture-only-password'))
            fallback.assert_not_called()

    def test_only_named_service_can_use_fab(self):
        with self.app.app_context(),patch.object(SupersetSecurityManager,'auth_user_db',return_value=self.user) as fallback:
            self.assertIs(self.manager.auth_user_db('service_account','service-fixture'),self.user)
            self.assertIsNone(self.manager.auth_user_db('some_existing_fab_user','service-fixture'))
            fallback.assert_called_once_with('service_account','service-fixture')

    def test_missing_library_rejects_business_but_keeps_maintenance_service(self):
        self.path.unlink()
        with self.app.app_context(),patch.object(SupersetSecurityManager,'auth_user_db',return_value=self.user) as fallback:
            self.assertIsNone(self.manager.auth_user_db('LegacyName','fixture-only-password'))
            self.assertIs(self.manager.auth_user_db('service_account','service-fixture'),self.user)
            fallback.assert_called_once()

    def test_invalid_library_and_verifier_failure_do_not_authenticate(self):
        self.path.write_text('LegacyName:unsupported\n')
        with self.assertRaises(ValueError):read_accounts(self.path)
        self.assertFalse(verify_password(self.encoded,'fixture-only-password',executable='/nonexistent/openssl'))
        for password in ('','\x00','one\ntwo'):
            self.assertFalse(verify_password(self.encoded,password))


if __name__=='__main__':unittest.main()
