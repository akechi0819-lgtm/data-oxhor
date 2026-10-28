import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TEST_ENV = {
    'SHADOW_BI_AUDIT': str(_ROOT / 'tests/fixtures/shadow-bi/audit'),
    'SHADOW_BI_SOURCE_LIBRARY': str(_ROOT / 'tests/fixtures/shadow-bi/source-library'),
    'SHADOW_BI_SOURCE_BATCH': 'run_shadow_daily_synthetic_business',
    'SHADOW_BI_LIBRARY': str(_ROOT / 'tests/fixtures/shadow-bi/presentation'),
    'SHADOW_BI_BATCH': 'run_shadow_daily_synthetic',
}
with patch.dict(os.environ, _TEST_ENV):
    from dashboard_product.shadow_bi.p3 import catalog


def _write_current_release(root, run_id='run_shadow_daily_test_001'):
    workspace = root / 'customers/shadow_bi_daily'
    run_root = workspace / 'Output/ShadowDaily' / run_id
    source = workspace / 'Output/ShadowBI' / f'{run_id}_business/library'
    source.mkdir(parents=True)
    (run_root / 'presentation').mkdir(parents=True)
    pointer = workspace / 'Output/ShadowDaily/current.json'
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({'run_id': run_id, 'status': 'published'}), encoding='utf-8')
    return workspace, run_root, source


def test_default_paths_follow_canonical_current_pointer(tmp_path):
    workspace, run_root, source = _write_current_release(tmp_path)

    paths = catalog._paths_for_environment(tmp_path, {})

    assert paths['AUDIT'] == tmp_path / '.local/audits/shadow-bi-p3-run_shadow_daily_test_001'
    assert paths['SOURCE_LIBRARY'] == source
    assert paths['SOURCE_BATCH'] == 'run_shadow_daily_test_001_business'
    assert paths['LIBRARY'] == run_root / 'presentation'
    assert paths['BATCH'] == 'run_shadow_daily_test_001'
    assert workspace in paths['SOURCE_LIBRARY'].parents


def test_explicit_daily_paths_do_not_read_current_pointer(tmp_path):
    env = {
        'SHADOW_BI_AUDIT': '/srv/shadow-bi/audit',
        'SHADOW_BI_LIBRARY': '/srv/shadow-bi/current/library',
        'SHADOW_BI_BATCH': 'run_server_current',
    }

    paths = catalog._paths_for_environment(tmp_path, env)

    assert paths['AUDIT'] == Path('/srv/shadow-bi/audit')
    assert paths['LIBRARY'] == Path('/srv/shadow-bi/current/library')
    assert paths['BATCH'] == 'run_server_current'
    assert paths['SOURCE_LIBRARY'] is None
    assert paths['SOURCE_BATCH'] is None


def test_missing_current_pointer_fails_without_old_stage_fallback(tmp_path):
    with pytest.raises(FileNotFoundError, match='current发布指针缺失'):
        catalog._paths_for_environment(tmp_path, {})


def test_malformed_current_pointer_fails_clearly(tmp_path):
    pointer = tmp_path / 'customers/shadow_bi_daily/Output/ShadowDaily/current.json'
    pointer.parent.mkdir(parents=True)
    pointer.write_text('{', encoding='utf-8')

    with pytest.raises(ValueError, match='current发布指针不是有效JSON'):
        catalog._paths_for_environment(tmp_path, {})
