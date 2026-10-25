"""首次配置独立P4主机；已有角色时拒绝重复初始化，凭据仅服务器生成。"""
from pathlib import Path
import json,secrets,os,subprocess
base=Path('/var/lib/shadow-bi')
for name in ['app/audit/p3/runtime','app/audit/p3/evidence','app/home','releases','backups']:(base/name).mkdir(parents=True,exist_ok=True)
cred={'username':'shadow_admin','password':secrets.token_urlsafe(24),'secret_key':secrets.token_urlsafe(48)}
f=base/'app/audit/p3/runtime/credentials.json'
if not f.exists():f.write_text(json.dumps(cred));f.chmod(0o600)
else:cred=json.loads(f.read_text())
subprocess.run(['runuser','-u','postgres','--','psql','-v','ON_ERROR_STOP=1','-c',"CREATE ROLE shadowbi LOGIN"],check=True)
subprocess.run(['runuser','-u','postgres','--','createdb','-O','shadowbi','shadowbi'],check=True)
env={'SUPERSET_SECRET_KEY':cred['secret_key'],'SUPERSET_METADATA_URI':'postgresql+psycopg2://shadowbi@/shadowbi?host=/var/run/postgresql','SUPERSET_HOME':str(base/'app/home'),'SUPERSET_CONFIG_PATH':'/srv/shadow-bi/code/dashboard_product/shadow_bi/p4/config.py','PYTHONPATH':'/srv/shadow-bi/code','FLASK_APP':'superset','SHADOW_BI_AUDIT':str(base/'app/audit/p3'),'SHADOW_BI_LIBRARY':str(base/'current/library'),'SHADOW_BI_BATCH':'run_p35_personal_ui_20261023','SHADOW_BI_PUBLIC_URL':'https://dashboard.apinova.cn','SHADOW_BI_DUCKDB_MEMORY':'1100MB','SHADOW_BI_DUCKDB_TEMP':str(base/'app/home/duckdb-tmp')}
Path('/etc/shadow-bi.env').write_text('\n'.join(k+'='+v for k,v in env.items())+'\n');Path('/etc/shadow-bi.env').chmod(0o600)
subprocess.run(['chown','-R','shadowbi:shadowbi',str(base)],check=True)
print('独立元数据库、应用目录和密钥配置已创建；未输出凭据')
