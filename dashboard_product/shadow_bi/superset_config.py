"""P1 loopback experiment only; metadata is disposable, never production."""
import json
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / ".local/audits/shadow-bi-p1-20261022"
RUNTIME = AUDIT / "runtime"
SECRET_KEY = json.loads((RUNTIME / "credentials.json").read_text())["secret_key"]
SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(RUNTIME / "superset.db")
SUPERSET_HOME = str(RUNTIME / "home")
WTF_CSRF_ENABLED = True
TALISMAN_ENABLED = False  # loopback HTTP experiment; no public listener
FEATURE_FLAGS = {"DRILL_TO_DETAIL": True, "DRILL_BY": True, "ENABLE_TEMPLATE_PROCESSING": True}
ENABLE_PROXY_FIX = False
CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 60}
DATA_CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 60}
FILTER_STATE_CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 3600}
EXPLORE_FORM_DATA_CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 3600}
SQL_MAX_ROW = 10000
ROW_LIMIT = 10000
import sys
sys.path.insert(0,str(ROOT))
from dashboard_product.shadow_bi.extension import install
FLASK_APP_MUTATOR = install
