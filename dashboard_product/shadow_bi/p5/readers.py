"""映射原账号库全部业务账号为完整只读；不生成另一套密码。"""
import json
from dashboard_product.shadow_bi.p5.legacy_passwords import read_accounts

DISABLED_PASSWORD = '!legacy-htpasswd-only'

def main():
    from superset.app import create_app
    app = create_app()
    with app.app_context():
        from superset import db, security_manager as sm
        accounts = read_accounts(app.config['LEGACY_HTPASSWD_PATH'])
        services = set(app.config['LEGACY_SERVICE_USERS'])
        if not services or accounts.keys() & services:
            raise RuntimeError('服务账号白名单缺失或与原业务账号重名')
        roles = [sm.find_role(n) for n in ('Gamma','ShadowReaderData')]
        if not all(roles):
            raise RuntimeError('完整只读角色未配置')
        report = []
        for name in accounts:
            user = sm.find_user(username=name)
            if user is None:
                user = sm.add_user(username=name, first_name=name, last_name='',
                    email=name+'@localhost', role=roles[0], hashed_password=DISABLED_PASSWORD)
            if not user:
                raise RuntimeError('原账号映射失败')
            user.password = DISABLED_PASSWORD
            user.roles = roles
            user.active = True
            report.append({'username':name,'roles':[r.name for r in roles]})
        disabled = []
        for user in sm.get_all_users():
            if user.username not in accounts and user.username not in services:
                user.active = False
                user.password = DISABLED_PASSWORD
                user.roles = []
                disabled.append(user.username)
        db.session.commit()
        print(json.dumps({'legacy_readers':report,'count':len(report),
                          'disabled_nonlegacy_users':disabled,
                          'password_source':'original htpasswd only'},ensure_ascii=False))

if __name__ == '__main__':
    main()
