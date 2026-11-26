from pathlib import Path

import pytest

from ops.render_rules import documents, render


def test_published_metric_documents_match_the_registry():
    root = Path(__file__).resolve().parents[1]
    render(root, check=True)
    for value in documents(root).values():
        assert 'core.training_heads_attributed' in value
        assert 'mart.study_abroad_summary' in value


def test_render_rules_check_rejects_local_drift(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for directory in ('config', 'business_data_mcp', 'docs'):
        (tmp_path / directory).mkdir()
    (tmp_path / 'config/metrics.yaml').write_bytes((root / 'config/metrics.yaml').read_bytes())
    render(tmp_path)
    (tmp_path / 'docs/metrics-reference.md').write_text('旧版')
    with pytest.raises(ValueError, match='偏离指标注册表'):
        render(tmp_path, check=True)
