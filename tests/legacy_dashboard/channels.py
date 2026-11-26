def _text(value):
    return '' if value is None else str(value).strip()

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
    assert decisions is not None
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
