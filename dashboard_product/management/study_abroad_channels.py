"""Read the reviewed exact-match channel rules used by the SQL build."""
import json
from pathlib import Path

DECISIONS_PATH = Path(__file__).resolve().parents[1] / 'config/study_abroad_channel_decisions.json'


def load_decisions(path=DECISIONS_PATH):
    """Read the user-reviewed source rules in the existing Bridge contract."""
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    if (document.get('schema_version') != 'company_bridge_candidates.v1'
            or document.get('candidate_set_role') != 'confirmed_review'
            or not isinstance(document.get('candidates'), list)):
        raise ValueError('留学已确认渠道规则合同无效')
    seen = {}
    for item in document['candidates']:
        if item['candidate_type'] != 'normalization_rule' or item['status'] != 'confirmed':
            continue
        params = item['proposed_mapping_or_rule']['parameters']
        if (params.get('source_fields') != ['first_channel', 'second_channel', 'third_channel']
                or len(params.get('match_values', [])) != 3
                or not params.get('normalized_l1') or not params.get('normalized_l2')):
            raise ValueError('留学渠道规则必须明确三层精确匹配及标准一级、二级')
        key = tuple(params['match_values'])
        target = (params['normalized_l1'], params['normalized_l2'])
        if key in seen and seen[key] != target:
            raise ValueError('同一渠道三层组合存在冲突决定')
        seen[key] = target
    return document
