"""Review new-source channel bindings using the customer's existing vocabulary."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

from data_acquisition.jobs.work_order_cleaning import load_work_order_reference
from data_platform.query.evidence import read_query_result
from data_platform.query.service import describe_warehouse
from workspace_modeling.business_pack.service import load_pack
from workspace_modeling.company_bridge.service import validate_candidate_set, build_bridge
from dashboard_product.management.study_abroad_query import (
    SQL_ROOT, query_sample, execute_sample_query, query_sql,
)
from dashboard_product.management.study_abroad_grade import load_grade_evidence

DECISIONS_PATH = Path(__file__).resolve().parents[1] / 'config/study_abroad_channel_decisions.json'


def _text(value):
    return '' if value is None else str(value).strip()


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_decisions(path=DECISIONS_PATH):
    """Read the user-reviewed source rules in the existing Bridge contract."""
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    validation = validate_candidate_set(document, require_role='confirmed_review')
    if validation['status'] != 'passed':
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


def _legacy_channel_labels(first, second, third, bridge, reference, decisions):
    """Resolve exact legacy rules; a missing/new combination stays unresolved."""
    first, second, third = map(_text, (first, second, third))
    confirmed = [item['proposed_mapping_or_rule'] | {'candidate_id': item['candidate_id']}
                 for item in decisions['candidates']
                 if item['candidate_type'] == 'normalization_rule' and item['status'] == 'confirmed']
    confirmed.extend(item for item in bridge.get('normalization_rules', [])
                     if item.get('status') == 'confirmed' and 'match_values' in item.get('parameters', {}))
    for item in confirmed:
        params = item['parameters']
        if tuple(params['match_values']) == (first, second, third):
            return params['normalized_l1'], params['normalized_l2'], 'confirmed_new_source', item['candidate_id']
    rules = {row['parameters']['rule']: row['parameters'] for row in bridge['normalization_rules']
             if row.get('target_id') == 'acquisition.channel' and 'rule' in row.get('parameters', {})}
    if not rules:
        # A standalone source Bridge only authorizes its explicit decisions.
        return None, None, 'unresolved', 'source_bridge_unmatched'
    alias = rules['online_root_alias']
    root = alias['normalized_l1'] if first in alias['source_values'] else first
    if root in {'网络资源', '新媒体'}:
        path = root + '-' + second
        if path == rules['newmedia_other_ssc']['source_value']:
            return '新媒体', 'SSC', 'matched_existing', 'newmedia_other_ssc'
        channel = reference.path_channel_to_corrected_channel.get((path, third))
        if channel:
            return root, 'SSC' if channel == '其他' else channel, 'matched_existing', 'online_reference_exact'
        return root, None, 'unresolved', 'online_reference_unmatched'
    if root == '官方合作高校':
        return root, root, 'matched_existing', 'official_university_same_name'
    if root == '新东方学校推荐':
        known = rules['newdongfang_l2_department']['known_departments']
        return root, second if second in known else '其他推荐', 'matched_existing', 'newdongfang_l2_department'
    if root == '渠道合作':
        params = rules['channel_partnership_l2']
        if third in params['maps']:
            return root, params['maps'][third], 'matched_existing', 'channel_partnership_l2'
        return root, None, 'unresolved', 'channel_partnership_unmatched'
    if root == '市场活动':
        cross = rules['campaign_personal_agent_cross']
        if root + '-' + second == cross['source_path'] and third == cross['source_value']:
            return cross['l1'], cross['l2'], 'matched_existing', 'campaign_personal_agent_cross'
        params = rules['campaign_l2_overlay']
        if third in params['direct']:
            return root, params['direct'][third], 'matched_existing', 'campaign_l2_overlay'
        if third in params['collapse_to_综合展'] or second in {'综合展', '现场注册', '部门展'}:
            return root, '综合展', 'matched_existing', 'campaign_l2_overlay'
        return root, None, 'unresolved', 'campaign_l2_unmatched'
    if root in rules['offline_other_roots_not_in_dashboard']['maps']:
        match = rules['offline_other_roots_not_in_dashboard']['maps'][root]
        return match['l1'], match['l2'], 'outside_legacy_scope', 'offline_other_roots_not_in_dashboard'
    return None, None, 'outside_legacy_scope', 'legacy_root_not_covered'


def legacy_channel(first, second, third, bridge, reference, decisions=None, grade_resolution=None):
    decisions = load_decisions() if decisions is None else decisions
    result = _legacy_channel_labels(first, second, third, bridge, reference, decisions)
    policies = [item['proposed_mapping_or_rule'] for item in decisions['candidates']
                if item['candidate_type'] == 'override' and item['status'] == 'confirmed']
    policies.extend(item for item in bridge.get('overrides', []) if item.get('status') == 'confirmed')
    policy = next((item['value'] for item in policies
                   if item['key'] == 'unresolved_market_activity_by_work_order_grade'), None)
    located = policy and (result[0] == policy['normalized_l1']
                         or (result[0] is None and _text(first) == policy['normalized_l1']))
    if not located or result[1] is not None:
        return result
    grade_resolution = grade_resolution or {'status': 'grade_missing', 'second_channel': None}
    if (grade_resolution['status'] == 'resolved'
            and grade_resolution['second_channel'] in policy['maps'].values()):
        return policy['normalized_l1'], grade_resolution['second_channel'], 'confirmed_new_source', 'work_order_grade_school_activity'
    return policy['normalized_l1'], None, 'unresolved', 'market_activity_' + grade_resolution['status']


def _literal(value):
    return 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"


def review(*, workspace: Path, snapshot_id: str, run_id: str, start_date: str, end_date: str,
           decision_path: Path = DECISIONS_PATH) -> dict:
    ws = Path(workspace).resolve()
    out = ws / 'Output/StudyAbroad' / run_id / 'channel_review'
    if out.exists():
        raise ValueError('渠道核对目录已存在，请使用新的显式run_id')
    bridge_path = ws / 'Work/Bridge/reference.json'
    reference_path = ws / 'Input/Reference/留学-FY26-资源表.xlsx'
    bridge = json.loads(bridge_path.read_text(encoding='utf-8'))
    identity = json.loads((ws / 'Work/workspace.json').read_text(encoding='utf-8'))
    if bridge['company_id'] != identity['company_id']:
        raise ValueError('旧Bridge不属于当前客户')
    decisions = load_decisions(decision_path)
    if decisions['company_id'] != identity['company_id']:
        raise ValueError('留学渠道确认决定不属于当前客户')
    decision_hash = _sha(Path(decision_path))
    bridge_hash, reference_hash = _sha(bridge_path), _sha(reference_path)
    reference = load_work_order_reference(reference_path)
    response = query_sample(workspace=ws, snapshot_id=snapshot_id, run_id=run_id,
                            start_date=start_date, end_date=end_date, query_name='facts')
    data = read_query_result(response, output_root=ws / 'Output/StudyAbroad')
    facts = [dict(zip(data['columns'], row)) for row in data['rows']]
    combinations = sorted({tuple(_text(row[key]) for key in ('first_channel', 'second_channel', 'third_channel'))
                           for row in facts})
    mappings = [{
        'raw': list(combo), 'first_channel': result[0], 'second_channel': result[1],
        'status': result[2], 'rule': result[3],
    } for combo in combinations for result in [legacy_channel(*combo, bridge, reference, decisions=decisions)]]
    lookup = {tuple(row['raw']): row for row in mappings}
    grade_ids = sorted({_text(fact['resource_id']) for fact in facts
                        if lookup[tuple(_text(fact[key]) for key in ('first_channel', 'second_channel', 'third_channel'))]['first_channel'] == '市场活动'
                        and lookup[tuple(_text(fact[key]) for key in ('first_channel', 'second_channel', 'third_channel'))]['second_channel'] is None
                        and _text(fact['resource_id'])})
    grade_evidence = load_grade_evidence(workspace=ws, resource_ids=grade_ids, run_id=run_id,
                                        expected_company_id=identity['company_id']) if grade_ids else {
        'resolution': {}, 'rows': [], 'query_response': None, 'bi_snapshot_id': None,
    }
    dictionary = ',\n'.join('(' + ', '.join(_literal(v) for v in (
        *row['raw'], row['first_channel'], row['second_channel'], row['status'], row['rule'],
    )) + ')' for row in mappings)
    if not dictionary:
        raise ValueError('查询范围没有市场明细，不能生成渠道映射候选')
    sql = (SQL_ROOT / 'channel_preview.sql').read_text(encoding='utf-8')
    sql = sql.replace('__STUDY_ABROAD_FACTS__', query_sql('facts').strip().rstrip(';'))
    sql = sql.replace('__CHANNEL_DICTIONARY__', dictionary)
    grade_values = ',\n'.join('(' + ', '.join(_literal(value) for value in (
        resource_id, value['second_channel'], 'work_order_grade_school_activity',
    )) + ')' for resource_id, value in grade_evidence['resolution'].items() if value['status'] == 'resolved')
    sql = sql.replace('__WORK_ORDER_GRADE_CHANNELS__', grade_values or "('',NULL::VARCHAR,NULL::VARCHAR)")
    preview = execute_sample_query(workspace=ws, snapshot_id=snapshot_id, run_id=run_id,
                                   start_date=start_date, end_date=end_date, sql=sql)
    preview_data = read_query_result(preview, output_root=ws / 'Output/StudyAbroad')
    pointer = json.loads((ws / 'Work/StudyAbroad/current.json').read_text(encoding='utf-8'))
    description = describe_warehouse(warehouse=ws / pointer['warehouse'], snapshot_id=snapshot_id)
    pack = load_pack(ws / 'Work/Pack/pack.json')
    candidates = []
    evidence = ['Work/Bridge/reference.json', 'Input/Reference/留学-FY26-资源表.xlsx']
    for sheet in ('resources', 'contracts', 'languages'):
        candidates.append({
            'candidate_id': f'cand_study_abroad_{sheet}_channel_binding',
            'candidate_type': 'normalization_rule',
            'source_locator': f'Work/StudyAbroad/current.json#{sheet}',
            'evidence_summary': '新来源三级字段按旧渠道定义重组路径；已有规则复用，新增来源绑定待业务确认。',
            'evidence_refs': evidence, 'status': 'proposed',
            'proposed_mapping_or_rule': {
                'source_id': 'study_abroad_market',
                'relation': f'landing.study_abroad_market__{sheet}', 'field_name': 'first_channel',
                'operation': 'map_enum', 'target_type': 'dimension', 'target_id': 'acquisition.channel',
                'parameters': {
                    'source_fields': ['first_channel', 'second_channel', 'third_channel'],
                    'legacy_path': 'first_channel + separator + second_channel',
                    'legacy_lower_signal': 'third_channel',
                    'existing_rule_reference': {'bridge_id': bridge['bridge_id'], 'bridge_version': bridge['bridge_version']},
                    'existing_mappings': [row for row in mappings if row['status'] == 'matched_existing'],
                    'unmatched': '保留原始渠道和未命中状态，不兜底改成其他',
                    'market_scope': '人工市场归属决定市场资格，旧渠道准入不再删除本次市场明细',
                    'team_scope': '渠道不覆盖已确认的人员团队归属，国际市场只在总盘单列',
                },
            },
        })
    proposed = {
        'schema_version': 'company_bridge_candidates.v1', 'candidate_set_role': 'historical_scan',
        'candidate_set_id': 'study_abroad_channel_binding_review', 'company_id': identity['company_id'],
        'pack_ref': bridge['pack_ref'], 'candidates': candidates, 'rejections': [],
        'summary': {'candidate_count': len(candidates), 'rejection_count': 0},
    }
    validation = validate_candidate_set(proposed, pack=pack, description=description, require_role='historical_scan')
    if validation['status'] != 'passed':
        raise ValueError('留学渠道Bridge候选校验失败：' + json.dumps(validation['errors'], ensure_ascii=False))
    confirmed = decisions
    confirmed_validation = validate_candidate_set(confirmed, pack=pack, description=description,
                                                  require_role='confirmed_review')
    if confirmed_validation['status'] != 'passed':
        raise ValueError('已确认留学渠道规则与Snapshot不兼容')
    confirmed_bridge = build_bridge(candidates=confirmed, pack=pack,
                                    bridge_id='bridge_study_abroad_channels', bridge_version='1.2.0',
                                    company_id=identity['company_id'])
    if (_sha(bridge_path) != bridge_hash or _sha(reference_path) != reference_hash
            or _sha(Path(decision_path)) != decision_hash):
        raise ValueError('Bridge、渠道参考或确认决定在核对期间变化')
    out.mkdir(parents=True)
    shutil.copyfile(bridge_path, out / 'legacy_bridge.json')
    shutil.copyfile(reference_path, out / 'legacy_channel_reference.xlsx')
    shutil.copyfile(decision_path, out / 'channel_decisions.json')
    coverage = Counter()
    unmatched = Counter()
    for fact in facts:
        key = tuple(_text(fact[field]) for field in ('first_channel', 'second_channel', 'third_channel'))
        resolved = legacy_channel(*key, bridge, reference, decisions=decisions,
                                  grade_resolution=grade_evidence['resolution'].get(_text(fact['resource_id'])))
        coverage[(fact['fact_type'], resolved[2])] += 1
        if resolved[2] not in {'matched_existing', 'confirmed_new_source'}:
            unmatched[(fact['fact_type'], fact['segment_id'], *key, _text(fact.get('channel_source')), resolved[2])] += 1
    result = {
        'schema_version': 'study_abroad_channel_review.v1', 'status': 'passed',
        'binding_status': 'partially_confirmed', 'run_id': run_id, 'snapshot_id': snapshot_id,
        'legacy_bridge_version': bridge['bridge_version'],
        'legacy_bridge_sha256': bridge_hash, 'legacy_reference_sha256': reference_hash,
        'confirmed_decisions_sha256': decision_hash,
        'grade_evidence': grade_evidence,
        'mappings': mappings,
        'coverage': [{'fact_type': kind, 'status': status, 'rows': count} for (kind, status), count in sorted(coverage.items())],
        'unmatched': [{'fact_type': kind, 'segment_id': segment, 'raw': [first, second, third],
                       'manual_channel': manual, 'status': status, 'rows': count}
                      for (kind, segment, first, second, third, manual, status), count in sorted(unmatched.items())],
        'source_receipt': response, 'channel_receipt': preview,
        'candidate_validation': validation, 'confirmed_candidate_validation': confirmed_validation,
    }
    for filename, value in (('review.json', result), ('bridge_candidates.json', proposed),
                            ('preview_result.json', preview_data), ('snapshot_description.json', description),
                            ('confirmed_bridge_candidates.json', confirmed), ('confirmed_channel_bridge.json', confirmed_bridge)):
        (out / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'status': 'passed', 'snapshot_id': snapshot_id, 'review_directory': str(out),
            'binding_status': 'partially_confirmed', 'legacy_bridge_version': bridge['bridge_version'],
            'coverage': result['coverage'], 'unmatched_combinations': len(result['unmatched']),
            'bridge_candidates': str(out / 'bridge_candidates.json')}


def main():
    parser = argparse.ArgumentParser(description='核对独立留学样本与旧渠道定义，输出Bridge候选，不发布正式映射')
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--snapshot-id', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--start-date', required=True)
    parser.add_argument('--end-date', required=True)
    parser.add_argument('--decision-path', type=Path, default=DECISIONS_PATH)
    try:
        print(json.dumps(review(**vars(parser.parse_args())), ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
