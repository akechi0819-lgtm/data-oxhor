from pathlib import Path

from dashboard_product.shadow_bi.sql_warehouse.build import _rule_binding


def test_active_advertising_and_source_rules_are_sealed():
    root = Path(__file__).resolve().parents[1]
    rules = _rule_binding(root)
    assert {
        'dashboard_product/management/tencent_sources.py',
        'dashboard_product/management/candidate_sources.py',
        'dashboard_product/management/tencent_native.py',
        'data_acquisition/connectors/study_abroad_source.py',
        'data_acquisition/workspace_snapshot.py',
    } <= rules.keys()
    assert not any('/tests/' in name for name in rules)
