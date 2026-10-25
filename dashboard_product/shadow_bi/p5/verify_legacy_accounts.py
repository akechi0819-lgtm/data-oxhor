"""无需原密码明文，核对原库全部账号映射、唯一认证路径和只读角色。"""
import argparse
import json
import os
from pathlib import Path
from dashboard_product.shadow_bi.p5.legacy_passwords import read_accounts
from dashboard_product.shadow_bi.p5.readers import DISABLED_PASSWORD

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    from superset.app import create_app
    from dashboard_product.shadow_bi.p5.legacy_security import LegacyHtpasswdSecurityManager
    app=create_app()
    with app.app_context():
        from superset import security_manager as sm
        assert isinstance(sm,LegacyHtpasswdSecurityManager)
        path=app.config['LEGACY_HTPASSWD_PATH']
        accounts=read_accounts(path)
        services=set(app.config['LEGACY_SERVICE_USERS'])
        assert not accounts.keys() & services
        rows=[]
        for name in accounts:
            user=sm.find_user(username=name)
            assert user is not None and user.is_active,name
            roles=sorted(r.name for r in user.roles)
            assert roles==['Gamma','ShadowReaderData'],name
            assert user.password==DISABLED_PASSWORD,name
            rows.append({'username':name,'source_format':'apr1','mapped':True,
                         'roles':roles,'database_password_disabled':True})
        active_business={u.username for u in sm.get_all_users() if u.is_active and u.username not in services}
        assert active_business==set(accounts)
        assert os.access(path,os.R_OK) and not os.access(path,os.W_OK)
        result={'status':'passed','original_account_count':len(rows),'accounts':rows,
                'service_users':sorted(services),'business_admin_count':0,
                'nonlegacy_business_active_count':0,'service_source_readable':True,
                'service_source_writable':False,'plaintext_passwords_used':False,
                'coverage_note':'全部原条目及映射；未知原密码未猜测或重置，不宣称逐人实际登录。'}
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='accounts'},ensure_ascii=False))

if __name__=='__main__':main()
