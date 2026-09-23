"""Approved fallback mapping for passive cash without a usable work-order team."""

import json
from functools import lru_cache
from pathlib import Path


RULES_PATH = Path(__file__).parent / 'config' / 'cash_channel_fallback_rules.json'
CHANNEL_UNASSIGNED = '暂时无法识别渠道'
CHANNEL_NATURAL = '自然无法判定'
CHANNEL_PLACEHOLDERS = {
    '', '暂无归属', '未归类', '未细分', '渠道/顾问暂无法拆分',
    '暂时无法识别渠道', '自然无法判定',
}
TEAM_NAMES = {
    'offline_market': '线下市场',
    'online_platform': '线上市场',
    'online_private': '虚拟人团队',
}


@lru_cache(maxsize=1)
def _rulebook():
    with RULES_PATH.open(encoding='utf-8') as stream:
        return json.load(stream)


def _wildcard(value):
    return value is None or str(value).strip() in _rulebook()['wildcards']


def _contains(source, needle):
    return str(needle).casefold() in str(source or '').casefold()


def _rule_evidence(rule, cash_channel, cash_campaign_name, work_order_second_channel):
    inputs = {
        '资源描述1': [('现金渠道', cash_channel), ('活动名称', cash_campaign_name)],
        '资源描述2': [('活动名称', cash_campaign_name)],
        '资源描述3': [('活动名称', cash_campaign_name)],
        '二级渠道': [('工单二级渠道', work_order_second_channel), ('活动名称', cash_campaign_name)],
        '市场活动1': [('活动名称', cash_campaign_name)],
        '市场活动2': [('活动名称', cash_campaign_name)],
    }
    evidence = []
    for field, candidates in inputs.items():
        value = rule.get(field)
        if _wildcard(value):
            continue
        hit = next(((source_name, source_value) for source_name, source_value in candidates if _contains(source_value, value)), None)
        if hit is None:
            return None
        evidence.append({'field': field, 'value': str(value), 'source': hit[0]})
    return evidence or None


def _has_existing_combo(first_channel, second_channel):
    return all(
        value is not None and str(value).strip() not in CHANNEL_PLACEHOLDERS
        for value in (first_channel, second_channel)
    )


def resolve_cash_channel(cash_channel, cash_campaign_name, work_order_first_channel,
                         work_order_second_channel, work_order_active_type):
    """Keep a linked work-order combo first; otherwise use workbook priority rules."""
    book = _rulebook()
    candidates = []
    for rule in book['rules']:
        evidence = _rule_evidence(rule, cash_channel, cash_campaign_name, work_order_second_channel)
        if evidence is not None:
            candidates.append((int(rule['优先级']), rule, evidence))
    candidates.sort(key=lambda item: item[0])

    winner = candidates[0] if candidates else None
    existing_combo = _has_existing_combo(work_order_first_channel, work_order_second_channel)
    conflict = bool(
        winner
        and str(work_order_active_type or '').strip() == '被动'
        and str(winner[1].get('新_主被动') or '').strip() == '主动'
    )

    mapped_first = str(winner[1]['新_一级渠道']) if winner else None
    mapped_second = str(winner[1]['新_二级渠道']) if winner else None
    original_mapped_second = mapped_second
    mapped_active_type = str(winner[1]['新_主被动']) if winner else None
    override_applied = False
    override_reason = None
    if winner and not existing_combo and not conflict:
        campaign = str(cash_campaign_name or '')
        for override in book.get('campaign_overrides', []):
            if _contains(campaign, override['contains']) and mapped_second == override['when_second_channel']:
                mapped_second = override['replace_second_channel']
                override_applied = True
                override_reason = override['reason']
                break

    if conflict:
        first_channel = CHANNEL_NATURAL
        second_channel = CHANNEL_NATURAL
        active_type = CHANNEL_NATURAL
        decision = CHANNEL_NATURAL
    elif existing_combo:
        first_channel = str(work_order_first_channel).strip()
        second_channel = str(work_order_second_channel).strip()
        active_type = str(work_order_active_type or mapped_active_type or '').strip() or None
        decision = '保留现有工单组合'
    elif winner:
        first_channel = mapped_first
        second_channel = mapped_second
        active_type = mapped_active_type
        decision = '按附件优先级映射'
    else:
        first_channel = CHANNEL_UNASSIGNED
        second_channel = CHANNEL_UNASSIGNED
        active_type = None
        decision = CHANNEL_UNASSIGNED

    return {
        'first_channel': first_channel,
        'second_channel': second_channel,
        'active_type': active_type,
        'decision': decision,
        'existing_combo': existing_combo,
        'conflict': conflict,
        'winner_priority': winner[0] if winner else None,
        'candidate_priorities': [item[0] for item in candidates],
        'candidate_count': len(candidates),
        'matching_evidence': winner[2] if winner else [],
        'mapped_first_channel': mapped_first,
        'mapped_second_channel': mapped_second,
        'original_mapped_second_channel': original_mapped_second,
        'mapped_active_type': mapped_active_type,
        'override_applied': override_applied,
        'override_reason': override_reason,
    }


def infer_team(existing_team_id, cash_channel, campaign_name, first_channel, second_channel, decision):
    """Infer only a missing cash team; return None when the evidence conflicts or is weak."""
    title = str(campaign_name or '')
    raw_channel = str(cash_channel or '')
    first = str(first_channel or '')
    second = str(second_channel or '')

    if 'TMK' in raw_channel.upper() or first.startswith('TMK激活'):
        return 'offline_market', 'TMK 按确认规则归线下市场'
    if decision == CHANNEL_NATURAL:
        return existing_team_id, '工单主被动与附件冲突，团队不据附件重判'
    if second == '虚拟人' or '虚拟人' in title or '私域' in title:
        return 'online_private', '标准二级渠道或活动名含虚拟人/私域'
    if existing_team_id in TEAM_NAMES:
        return existing_team_id, '保留现有工单团队'

    if second == '线上讲座':
        return 'online_platform', '标准二级渠道为线上讲座'
    if second in ('线下讲座', '线下校代'):
        return 'offline_market', '标准二级渠道明确为线下活动'

    online = any(token in title for token in ('线上', '在线', '官网', '小程序'))
    offline = any(token in title for token in ('线下', '校代', '地推', '会销', '展会', '讲座', '路展', '校园', '高招', '中招'))
    if online and offline:
        return None, '活动名同时出现线上和线下信号'
    if online:
        return 'online_platform', '活动名明确线上/官网/小程序'
    if offline:
        return 'offline_market', '活动名明确线下/活动信号'

    if first in ('平台', 'TMK激活-平台'):
        return 'online_platform', '标准一级渠道为平台'
    if first in ('市场活动', 'TMK激活-市场活动', 'TMK激活'):
        return 'offline_market', '标准一级渠道为市场活动/TMK'
    if first == '新东方官网':
        return 'online_platform', '标准一级渠道为新东方官网'
    return None, '活动名和标准渠道都没有唯一团队标记'
