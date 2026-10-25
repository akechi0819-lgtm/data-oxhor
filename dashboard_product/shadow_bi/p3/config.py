"""P3 loopback only. P1/P2 sealed artifacts remain read-only."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
AUDIT=ROOT/'.local/audits/shadow-bi-p3-20261022'
RUNTIME=AUDIT/'runtime'
SECRET_KEY=json.loads((RUNTIME/'credentials.json').read_text())['secret_key']
SQLALCHEMY_DATABASE_URI='sqlite:///'+str(RUNTIME/'superset.db')
SUPERSET_HOME=str(RUNTIME/'home')
WTF_CSRF_ENABLED=True
TALISMAN_ENABLED=False
FEATURE_FLAGS={'DRILL_TO_DETAIL':True,'DRILL_BY':True,'ENABLE_TEMPLATE_PROCESSING':True}
BABEL_DEFAULT_LOCALE='zh'
LANGUAGES={'zh':{'flag':'cn','name':'中文'},'en':{'flag':'us','name':'English'}}
ENABLE_PROXY_FIX=False
CACHE_CONFIG={'CACHE_TYPE':'SimpleCache','CACHE_DEFAULT_TIMEOUT':60}
DATA_CACHE_CONFIG={'CACHE_TYPE':'SimpleCache','CACHE_DEFAULT_TIMEOUT':60}
FILTER_STATE_CACHE_CONFIG={'CACHE_TYPE':'SimpleCache','CACHE_DEFAULT_TIMEOUT':3600}
EXPLORE_FORM_DATA_CACHE_CONFIG={'CACHE_TYPE':'SimpleCache','CACHE_DEFAULT_TIMEOUT':3600}
# Overall safety ceiling exceeds the complete fixed batch. UI uses server paging.
SQL_MAX_ROW=1000000
ROW_LIMIT=1000000
DISPLAY_MAX_ROW=1000000
import sys
sys.path.insert(0,str(ROOT))
from dashboard_product.shadow_bi.p3.extension import install
FLASK_APP_MUTATOR=install
