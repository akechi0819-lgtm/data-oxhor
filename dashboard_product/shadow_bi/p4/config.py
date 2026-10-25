"""服务器专用配置；应用、元数据与业务数据独立。"""
import os
from pathlib import Path
SECRET_KEY=os.environ['SUPERSET_SECRET_KEY']
SQLALCHEMY_DATABASE_URI=os.environ['SUPERSET_METADATA_URI']
SUPERSET_HOME=os.environ['SUPERSET_HOME']
WTF_CSRF_ENABLED=True
TALISMAN_ENABLED=True
# 同域旧HTTP静态入口仍在运行；清除本次默认HSTS副作用，不改变新站TLS与Secure cookie。
TALISMAN_CONFIG={'content_security_policy':None,'force_https':False,'session_cookie_secure':True,'strict_transport_security_max_age':0,'strict_transport_security_include_subdomains':False}
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE='Lax'
ENABLE_PROXY_FIX=True
FEATURE_FLAGS={'DRILL_TO_DETAIL':True,'DRILL_BY':True,'ENABLE_TEMPLATE_PROCESSING':True}
BABEL_DEFAULT_LOCALE='zh'
LANGUAGES={'zh':{'flag':'cn','name':'中文'},'en':{'flag':'us','name':'English'}}
CACHE_CONFIG={'CACHE_TYPE':'SimpleCache','CACHE_DEFAULT_TIMEOUT':60}
DATA_CACHE_CONFIG={'CACHE_TYPE':'SimpleCache','CACHE_DEFAULT_TIMEOUT':60}
FILTER_STATE_CACHE_CONFIG={'CACHE_TYPE':'FileSystemCache','CACHE_DIR':str(Path(SUPERSET_HOME)/'filter-cache'),'CACHE_DEFAULT_TIMEOUT':3600}
EXPLORE_FORM_DATA_CACHE_CONFIG={'CACHE_TYPE':'FileSystemCache','CACHE_DIR':str(Path(SUPERSET_HOME)/'explore-cache'),'CACHE_DEFAULT_TIMEOUT':3600}
SQL_MAX_ROW=1000000
ROW_LIMIT=1000000
DISPLAY_MAX_ROW=1000000
SHADOW_QUERY_AUDIT=False
from dashboard_product.shadow_bi.p5.legacy_security import LegacyHtpasswdSecurityManager
CUSTOM_SECURITY_MANAGER=LegacyHtpasswdSecurityManager
LEGACY_HTPASSWD_PATH=os.environ.get('SHADOW_LEGACY_HTPASSWD','/etc/nginx/dashboard.htpasswd')
LEGACY_SERVICE_USERS=tuple(x for x in os.environ.get('SHADOW_SERVICE_USERS','').split(',') if x)
from dashboard_product.shadow_bi.p4.extension import install
FLASK_APP_MUTATOR=install
