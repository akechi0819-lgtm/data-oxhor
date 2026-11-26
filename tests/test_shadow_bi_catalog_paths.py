"""SQL catalogue metadata must not depend on the retired presentation warehouse."""
import os
from pathlib import Path
import subprocess
import sys


def test_catalogue_import_and_build_without_legacy_paths(tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith('SHADOW_BI_')}
    script = (
        "from dashboard_product.shadow_bi.p3.catalog import VIEWS, PAGES; "
        "from dashboard_product.shadow_bi.sql_warehouse.catalog import build_catalogue; "
        "assert VIEWS and PAGES and build_catalogue()"
    )
    subprocess.run([sys.executable, '-c', script], cwd=root, env=environment,
                   check=True, capture_output=True, text=True)


def test_server_paths_use_explicit_environment(tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith('SHADOW_BI_')}
    environment.update({
        'SHADOW_BI_AUDIT': str(tmp_path / 'audit'),
        'SHADOW_BI_LIBRARY': str(tmp_path / 'current/library'),
        'SHADOW_BI_BATCH': 'run_server_current',
    })
    script = (
        "from dashboard_product.shadow_bi.p3.catalog import AUDIT, LIBRARY, BATCH; "
        "import os; "
        "assert str(AUDIT) == os.environ['SHADOW_BI_AUDIT']; "
        "assert str(LIBRARY) == os.environ['SHADOW_BI_LIBRARY']; "
        "assert BATCH == os.environ['SHADOW_BI_BATCH']"
    )
    subprocess.run([sys.executable, '-c', script], cwd=root, env=environment,
                   check=True, capture_output=True, text=True)
