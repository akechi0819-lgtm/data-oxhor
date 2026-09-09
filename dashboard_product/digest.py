"""Team personnel progress digest from a dashboard artifact."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from dashboard_product.booklets import TEAM_DISPLAY_NAMES
from dashboard_product.refresh import (
    campaign_allows_person_match,
    date_to_perf_month,
    match_person_names,
)

NOTIFY_CHANNELS = {
    'online_private': {
        'team_id': 'online_private',
        'business_group': None,
        'display_name': '线上私域（虚拟人团队）',
    },
    'online_platform': {
        'team_id': 'online_platform',
        'business_group': None,
        'display_name': '线上平台',
    },
    'offline_youth': {
        'team_id': 'offline_market',
        'business_group': '留学预备',
        'display_name': '线下市场·青少',
    },
    'offline_high_school': {
        'team_id': 'offline_market',
        'business_group': '高中',
        'display_name': '线下市场·高中',
    },
    'offline_university': {
        'team_id': 'offline_market',
        'business_group': '大学',
        'display_name': '线下市场·大学',
    },
}
NOTIFY_CHANNEL_IDS = tuple(NOTIFY_CHANNELS)
NOTIFY_TEAM_IDS = NOTIFY_CHANNEL_IDS
CHANNEL_ALIASES = {
    'offline_market': ('offline_youth', 'offline_high_school', 'offline_university'),
}
BUSINESS_GROUPS = {'留学预备', '高中', '大学'}
ORDER_METRIC = 'work_orders'
CASH_METRIC = 'passive_reported_cash'


def unique_keep_order(items):
    seen = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def parse_iso_date(value):
    if not value:
        raise ValueError('missing date')
    return datetime.fromisoformat(str(value)[:10]).date()


def performance_month_window(month):
    year, month_n = map(int, month.split('-'))
    end = date(year, month_n, 25)
    if month_n == 1:
        start = date(year - 1, 12, 26)
    else:
        start = date(year, month_n - 1, 26)
    return start, end


def performance_month_progress(month, as_of):
    start, end = performance_month_window(month)
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end, time(23, 59, 59))
    as_of_dt = datetime.combine(as_of, time.min)
    span = (end_dt - start_dt).total_seconds()
    if span <= 0:
        return 0.0
    ratio = (as_of_dt - start_dt).total_seconds() / span
    return max(0.0, min(1.0, ratio))


def remaining_workdays(as_of, end):
    count = 0
    cursor = as_of
    while cursor <= end:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def completion_rate(actual, target):
    if target is None or target <= 0:
        return None
    return actual / target


def current_query_rows(artifact):
    results = artifact.get('query_results') or []
    if not results:
        return []
    first = results[0]
    if not isinstance(first, dict):
        return []
    nested = first.get('result')
    if isinstance(nested, dict) and isinstance(nested.get('rows'), list):
        return nested['rows']
    rows = first.get('rows')
    return rows if isinstance(rows, list) else []


def find_team(artifact, team_id):
    for team in (artifact.get('dashboard') or {}).get('teams') or []:
        if team.get('team_id') == team_id:
            return team
    return {
        'team_id': team_id,
        'display_name': TEAM_DISPLAY_NAMES.get(team_id, team_id),
        'groups': [],
        'people': [],
    }


def person_month_value(person, months, month, metric):
    values = (person.get('monthly_actuals') or {}).get(metric) or []
    try:
        index = months.index(month)
    except ValueError:
        return 0.0
    if index >= len(values):
        return 0.0
    return float(values[index] or 0)


def person_month_target(person, month, metric):
    target = ((person.get('monthly_targets') or {}).get(month) or {}).get(metric)
    if target in (None, ''):
        return None
    return float(target)


def candidates_by_business_group(people):
    grouped = {}
    for person in people:
        name = person.get('display_name')
        group = person.get('business_group')
        if not name or not group:
            continue
        grouped.setdefault(group, []).append(name)
    return {group: unique_keep_order(names) for group, names in grouped.items()}


def attributed_names(candidates, campaign, entry_person):
    if not campaign_allows_person_match(campaign):
        return []
    return unique_keep_order(match_person_names(candidates, campaign, entry_person))


def metric_kind(metric):
    if metric == CASH_METRIC:
        return 'cash'
    if metric == ORDER_METRIC:
        return 'orders'
    return None


def resolve_channels(channel_ids=None):
    if not channel_ids:
        return NOTIFY_CHANNEL_IDS
    resolved = []
    for item in channel_ids:
        if item in CHANNEL_ALIASES:
            resolved.extend(CHANNEL_ALIASES[item])
        elif item in NOTIFY_CHANNELS:
            resolved.append(item)
        else:
            raise ValueError(f'unknown notify channel: {item}')
    return tuple(unique_keep_order(resolved))


def build_detail_rows(rows, team_id, perf_month, people, business_group=None):
    grouped = candidates_by_business_group(people)
    details = {'orders': [], 'cash': []}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 11:
            continue
        event_date, row_team, row_group, first_channel, second_channel, campaign, entry_person, school, grade, metric, value = row[:11]
        if row_team != team_id or row_group not in BUSINESS_GROUPS:
            continue
        if business_group and row_group != business_group:
            continue
        business_group_name = row_group
        kind = metric_kind(metric)
        if kind is None or value in (None, ''):
            continue
        if date_to_perf_month(event_date) != perf_month:
            continue
        names = attributed_names(grouped.get(business_group_name) or [], campaign, entry_person)
        details[kind].append({
            'event_date': str(event_date)[:10],
            'business_group': business_group_name,
            'first_channel': first_channel or '未归类',
            'second_channel': second_channel or '未细分',
            'campaign_name': campaign,
            'entry_person': entry_person,
            'school_name': school,
            'grade_name': grade,
            'value': float(value),
            'attributed_people': names,
            'attribution': '、'.join(names) if names else '未归属',
        })
    for kind in details:
        details[kind].sort(key=lambda item: (item['event_date'], item['business_group'], str(item['campaign_name'] or '')))
    return details


def summarize_details(items):
    attributed = [item for item in items if item['attributed_people']]
    unattributed = [item for item in items if not item['attributed_people']]
    return {
        'total': sum(item['value'] for item in items),
        'attributed': sum(item['value'] for item in attributed),
        'unattributed': sum(item['value'] for item in unattributed),
        'total_rows': len(items),
        'attributed_rows': len(attributed),
        'unattributed_rows': len(unattributed),
    }


def build_people_rows(people, months, month, time_progress, workdays):
    rows = []
    for person in people:
        business_group = person.get('business_group')
        name = person.get('display_name')
        if not name or not business_group:
            continue
        orders_actual = person_month_value(person, months, month, 'orders')
        cash_actual = person_month_value(person, months, month, 'cash')
        orders_target = person_month_target(person, month, 'orders')
        cash_target = person_month_target(person, month, 'cash')
        orders_completion = completion_rate(orders_actual, orders_target)
        cash_completion = completion_rate(cash_actual, cash_target)
        expected_orders = orders_target * time_progress if orders_target and orders_target > 0 else None
        remaining_orders = max(0.0, (orders_target or 0) - orders_actual) if orders_target and orders_target > 0 else None
        behind = orders_completion is not None and orders_completion < time_progress
        if remaining_orders is None:
            daily_orders = None
        elif remaining_orders <= 0:
            daily_orders = 0.0
        elif workdays <= 0:
            daily_orders = None
        else:
            daily_orders = remaining_orders / workdays
        rows.append({
            'display_name': name,
            'business_group': business_group,
            'group_name': person.get('group_name'),
            'orders_target': orders_target,
            'orders_actual': orders_actual,
            'orders_completion': orders_completion,
            'expected_orders': expected_orders,
            'orders_gap': None if expected_orders is None else expected_orders - orders_actual,
            'remaining_orders': remaining_orders,
            'daily_orders': daily_orders,
            'behind': behind,
            'cash_target': cash_target,
            'cash_actual': cash_actual,
            'cash_completion': cash_completion,
        })
    return rows


def build_digest(artifact, channel_id, rows=None):
    if channel_id not in NOTIFY_CHANNELS:
        raise ValueError(f'unknown notify channel: {channel_id}')
    channel = NOTIFY_CHANNELS[channel_id]
    team_id = channel['team_id']
    business_group = channel['business_group']
    as_of = parse_iso_date(artifact.get('as_of_date'))
    data_through = parse_iso_date(artifact.get('data_through_date') or artifact.get('as_of_date'))
    perf_month = date_to_perf_month(as_of.isoformat())
    if not perf_month:
        raise ValueError('cannot derive performance month')
    window_start, window_end = performance_month_window(perf_month)
    time_progress = performance_month_progress(perf_month, as_of)
    workdays = remaining_workdays(as_of, window_end)
    dashboard = artifact.get('dashboard') or {}
    months = dashboard.get('months') or []
    team = find_team(artifact, team_id)
    people = [
        person for person in (team.get('people') or [])
        if not business_group or person.get('business_group') == business_group
    ]
    details = build_detail_rows(
        rows if rows is not None else current_query_rows(artifact),
        team_id,
        perf_month,
        people,
        business_group=business_group,
    )
    people_rows = build_people_rows(people, months, perf_month, time_progress, workdays)
    return {
        'team_id': channel_id,
        'source_team_id': team_id,
        'business_group': business_group,
        'display_name': channel['display_name'],
        'as_of_date': as_of.isoformat(),
        'data_through_date': data_through.isoformat(),
        'perf_month': perf_month,
        'window_start': window_start.isoformat(),
        'window_end': window_end.isoformat(),
        'time_progress': time_progress,
        'remaining_workdays': workdays,
        'run_id': artifact.get('run_id'),
        'snapshot_id': artifact.get('snapshot_id'),
        'people': people_rows,
        'behind': [row for row in people_rows if row['behind']],
        'orders': summarize_details(details['orders']),
        'cash': summarize_details(details['cash']),
        'order_details': details['orders'],
        'cash_details': details['cash'],
    }


def build_all_digests(artifact, team_ids=None):
    selected = resolve_channels(team_ids)
    rows = current_query_rows(artifact)
    return [build_digest(artifact, channel_id, rows=rows) for channel_id in selected]
