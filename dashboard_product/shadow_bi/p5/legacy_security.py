"""原看板账号密码为业务登录唯一权威；服务账号使用明确白名单。"""
from flask import current_app
from superset.security import SupersetSecurityManager
from dashboard_product.shadow_bi.p5.legacy_passwords import read_accounts, verify_password

class LegacyHtpasswdSecurityManager(SupersetSecurityManager):
    def auth_user_db(self, username, password):
        services = set(current_app.config.get('LEGACY_SERVICE_USERS', ()))
        try:
            accounts = read_accounts(current_app.config['LEGACY_HTPASSWD_PATH'])
        except (OSError, ValueError):
            return super().auth_user_db(username, password) if username in services else None
        if username in accounts:
            user = self.find_user(username=username)
            if user is None or not user.is_active:
                return None
            valid = verify_password(accounts[username], password)
            self.update_user_auth_stat(user, valid)
            return user if valid else None
        if username in services:
            return super().auth_user_db(username, password)
        return None
