"""The SQL release consumes only the reviewed channel rules."""
import copy
import json

import pytest

from dashboard_product.management.study_abroad_channels import load_decisions


def test_reviewed_exact_channel_rules():
    decision = load_decisions()
    candidates = decision['candidates']
    assert len(candidates) == 11
    assert all(item['status'] == 'confirmed' for item in candidates)
    exact = {tuple(params['match_values']): (params['normalized_l1'], params['normalized_l2'])
             for item in candidates if 'match_values' in (params := item['proposed_mapping_or_rule'].get('parameters', {}))}
    assert len(exact) == 10
    assert exact['网络资源', '搜索推广', '小红书品牌号'] == ('网络资源', '小红书')
    assert exact['新媒体', '欧亚总部在线', '知乎-付费'] == ('新媒体', 'SSC')


def test_rejects_conflicting_reviewed_channel_rules(tmp_path):
    decision = load_decisions()
    duplicate = copy.deepcopy(next(item for item in decision['candidates']
                                  if item['candidate_type'] == 'normalization_rule'))
    duplicate['proposed_mapping_or_rule']['parameters']['normalized_l2'] = '不同口径'
    decision['candidates'].append(duplicate)
    path = tmp_path / 'conflicting.json'
    path.write_text(json.dumps(decision))
    with pytest.raises(ValueError, match='冲突决定'):
        load_decisions(path)
