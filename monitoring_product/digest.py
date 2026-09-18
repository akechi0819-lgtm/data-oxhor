"""Personnel progress rules and warehouse attribution."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from workspace_modeling.operations.personnel import (
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


def configured_people_for_channel(channel_id, people_config):
    from workspace_modeling.operations.personnel import BUSINESS_GROUP_BY_ROSTER_GROUP
    if channel_id not in NOTIFY_CHANNELS:
        return []
    channel = NOTIFY_CHANNELS[channel_id]
    team_id = channel['team_id']
    business_group = channel['business_group']
    rows = []
    for team in (people_config or {}).get('teams') or []:
        if team.get('team_id') != team_id:
            continue
        for group in team.get('groups') or []:
            group_business_group = BUSINESS_GROUP_BY_ROSTER_GROUP.get(group.get('display_name'))
            for person in group.get('members') or []:
                if person.get('status') == 'vacant':
                    continue
                name = person.get('display_name')
                person_group = person.get('business_group') or group_business_group
                if not name or not person_group:
                    continue
                if business_group and person_group != business_group:
                    continue
                rows.append({
                    'display_name': name,
                    'business_group': person_group,
                    'group_name': group.get('display_name'),
                    'monthly_targets': person.get('monthly_targets') or {},
                })
    return rows


def ensure_roster(digest, people_config, months=None, time_progress=None, workdays=None):
    configured = configured_people_for_channel(digest['team_id'], people_config)
    if not configured:
        return digest
    months = months or []
    time_progress = digest['time_progress'] if time_progress is None else time_progress
    workdays = digest['remaining_workdays'] if workdays is None else workdays
    people_rows = build_people_rows(configured, months, digest['perf_month'], time_progress, workdays)
    digest = dict(digest)
    digest['people'] = people_rows
    digest['behind'] = [row for row in people_rows if row['behind']]
    return digest


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


def attributed_names(candidates, campaign, entry_person, resource_desc=None):
    return unique_keep_order(match_person_names(candidates, campaign, entry_person, resource_desc))


def rolled_business_group(group):
    if group in {'青少', '初中'}:
        return '留学预备'
    return group


TEMPORARY_STUDY_ABROAD_ADVISERS = {'张艺彤'}


def empty_order_team(team_name):
    return team_name in {'无法判断', '校区资源无法归属', '需要判定'} or not team_name


def study_abroad_grade_split(grade):
    if grade in {'学龄前', '一年级', '二年级', '三年级', '四年级', '五年级'} or any(token in grade for token in ('小班', '中班', '大班')):
        return '青少'
    return '初中'


def mapped_order_yoy_group(team, adviser_belong=None, grade_correction=None, follow_adviser=None):
    team_name = str(team or '').strip()
    belong = str(adviser_belong or '').strip()
    grade = str(grade_correction or '').strip()
    follow = str(follow_adviser or '').strip()
    if empty_order_team(team_name) and follow in TEMPORARY_STUDY_ABROAD_ADVISERS:
        return study_abroad_grade_split(grade)
    if empty_order_team(team_name):
        return None
    if belong in {'武清顾问', '塘沽顾问', '塘沽学管'} or team_name in {'武清', '塘沽'}:
        if grade in {'', '未知'}:
            return '大学'
        if grade in {'学龄前', '一年级', '二年级', '三年级', '四年级', '五年级', '六年级'} or any(token in grade for token in ('小班', '中班', '大班')):
            return '青少'
        if any(token in grade for token in ('初一', '初二', '初三')):
            return '初中'
        if any(token in grade for token in ('高一', '高二', '高三')):
            return '高中'
        return '大学'
    if belong == '青少顾问':
        return '青少'
    if belong == '初中顾问':
        return '初中'
    if belong == '高中顾问':
        return '高中'
    if belong in {'大学顾问', '大学学管'}:
        return '大学'
    if not belong and team_name == '留学预备':
        return study_abroad_grade_split(grade)
    if team_name == '高中':
        return '高中'
    if team_name == '大学':
        return '大学'
    return None


def mapped_order_business_group(team, grade_attr=None, grade_name=None, adviser_belong=None, grade_correction=None, follow_adviser=None):
    return rolled_business_group(mapped_order_yoy_group(team, adviser_belong, grade_correction, follow_adviser))


def mapped_cash_business_group(team):
    team_name = str(team or '').strip()
    if team_name in {'青少', '初中', '初中国际学科'}:
        return '留学预备'
    if team_name in {'高中', 'ICC', '国际学科'}:
        return '高中'
    if team_name == '大学':
        return '大学'
    return None


def column_index(columns):
    return {name: index for index, name in enumerate(columns)}


def cell_value(row, columns, name):
    index = columns.get(name) if isinstance(columns, dict) else None
    if index is None or index >= len(row):
        return None
    return row[index]


def attribution_label(people, business_group, campaign, entry_person, resource_desc=None):
    grouped = candidates_by_business_group(people)
    names = attributed_names(grouped.get(business_group) or [], campaign, entry_person, resource_desc)
    return '、'.join(names) if names else '未归属'


def order_attribution(row, columns, people):
    cols = columns if isinstance(columns, dict) else column_index(columns)
    business_group = mapped_order_business_group(
        cell_value(row, cols, '团队'),
        cell_value(row, cols, '年级属性'),
        cell_value(row, cols, '年级名称'),
        cell_value(row, cols, '顾问归属'),
        cell_value(row, cols, '年级校正'),
        cell_value(row, cols, '跟进顾问'),
    )
    return attribution_label(
        people,
        business_group,
        cell_value(row, cols, '活动名称'),
        cell_value(row, cols, '资源录入人'),
        cell_value(row, cols, '资源描述'),
    )


def cash_work_order_id(row, columns):
    cols = columns if isinstance(columns, dict) else column_index(columns)
    return str(cell_value(row, cols, '工单ID') or cell_value(row, cols, '工单ID__2') or '').strip()


def collect_order_labels(columns, rows, people, inherited):
    cols = columns if isinstance(columns, dict) else column_index(columns)
    labels = [order_attribution(row, cols, people) for row in rows]
    for row, label in zip(rows, labels):
        work_order_id = str(cell_value(row, cols, 'ID') or '').strip()
        if work_order_id and work_order_id not in inherited:
            inherited[work_order_id] = label
    return labels


def missing_cash_order_ids(order_columns, order_rows, cash_columns, cash_rows):
    order_cols = column_index(order_columns)
    month_ids = {
        str(cell_value(row, order_cols, 'ID') or '').strip()
        for row in order_rows
    }
    month_ids.discard('')
    missing = []
    seen = set()
    cash_cols = column_index(cash_columns)
    for row in cash_rows:
        work_order_id = cash_work_order_id(row, cash_cols)
        if work_order_id and work_order_id not in month_ids and work_order_id not in seen:
            seen.add(work_order_id)
            missing.append(work_order_id)
    return missing


def ledger_attributions(order_columns, order_rows, cash_columns, cash_rows, people, extra_order_columns=None, extra_order_rows=None):
    inherited = {}
    order_labels = collect_order_labels(order_columns, order_rows, people, inherited)
    if extra_order_rows:
        collect_order_labels(extra_order_columns or [], extra_order_rows, people, inherited)
    cash_cols = column_index(cash_columns)
    cash_labels = []
    for row in cash_rows:
        work_order_id = cash_work_order_id(row, cash_cols)
        if work_order_id and work_order_id in inherited:
            cash_labels.append(inherited[work_order_id])
            continue
        cash_labels.append(attribution_label(
            people,
            mapped_cash_business_group(cell_value(row, cash_cols, '团队')),
            cell_value(row, cash_cols, '市场活动名称'),
            None,
        ))
    return order_labels, cash_labels


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


def owner_names(owner):
    if not owner or owner == '未归属':
        return []
    return [name for name in str(owner).split('、') if name and name != '未归属']


def student_id_value(row, columns):
    if '学员编号' not in columns:
        return None
    index = columns.index('学员编号')
    if index >= len(row):
        return None
    value = row[index]
    if value in (None, ''):
        return None
    text = str(value).strip()
    return text or None


def count_heads_by_owner(cash):
    columns = cash.get('columns') or []
    rows = cash.get('rows') or []
    credits = defaultdict(dict)
    if '学员编号' not in columns:
        return Counter()
    for row in rows:
        names = owner_names(row[0] if row else None)
        if not names:
            continue
        student = student_id_value(row, columns)
        if not student:
            continue
        weight = 1.0 / len(names)
        for name in names:
            credits[name][student] = max(credits[name].get(student, 0.0), weight)
    return Counter({name: sum(weights.values()) for name, weights in credits.items()})


def channel_secondary_metric(channel_id):
    return 'heads' if channel_id == 'offline_university' else 'cash'


def build_people_rows(people, months, month, time_progress, workdays):
    rows = []
    for person in people:
        business_group = person.get('business_group')
        name = person.get('display_name')
        if not name or not business_group:
            continue
        orders_actual = person_month_value(person, months, month, 'orders')
        cash_actual = person_month_value(person, months, month, 'cash')
        heads_actual = person_month_value(person, months, month, 'heads')
        orders_target = person_month_target(person, month, 'orders')
        cash_target = person_month_target(person, month, 'cash')
        heads_target = person_month_target(person, month, 'heads')
        orders_completion = completion_rate(orders_actual, orders_target)
        cash_completion = completion_rate(cash_actual, cash_target)
        heads_completion = completion_rate(heads_actual, heads_target)
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
            'heads_target': heads_target,
            'heads_actual': heads_actual,
            'heads_completion': heads_completion,
        })
    return rows


def build_digest(context, channel_id):
    channel = NOTIFY_CHANNELS[channel_id]
    as_of = parse_iso_date(context['as_of_date'])
    perf_month = date_to_perf_month(as_of.isoformat())
    start, end = performance_month_window(perf_month)
    return {
        **context,
        'team_id': channel_id,
        'source_team_id': channel['team_id'],
        'business_group': channel['business_group'],
        'display_name': channel['display_name'],
        'perf_month': perf_month,
        'window_start': start.isoformat(), 'window_end': end.isoformat(),
        'time_progress': performance_month_progress(perf_month, as_of),
        'remaining_workdays': remaining_workdays(as_of, end),
        'secondary_metric': channel_secondary_metric(channel_id),
        'people': [], 'behind': [],
    }


def build_all_digests(context, team_ids=None):
    return [build_digest(context, channel_id) for channel_id in resolve_channels(team_ids)]


def apply_warehouse_actuals(digest):
    from collections import Counter
    warehouse = digest.get('warehouse') or {}
    order_counts = Counter()
    for row in (warehouse.get('orders') or {}).get('rows') or []:
        owner = row[0] if row else None
        if not owner or owner == '未归属':
            continue
        for name in str(owner).split('、'):
            if name and name != '未归属':
                order_counts[name] += 1
    cash = warehouse.get('cash') or {}
    cash_cols = cash.get('columns') or []
    amount_index = cash_cols.index('报入现金收入') if '报入现金收入' in cash_cols else None
    cash_sum = Counter()
    if amount_index is not None:
        for row in cash.get('rows') or []:
            owner = row[0] if row else None
            if not owner or owner == '未归属':
                continue
            try:
                amount = float(row[amount_index] or 0)
            except (TypeError, ValueError):
                amount = 0.0
            for name in str(owner).split('、'):
                if name and name != '未归属':
                    cash_sum[name] += amount
    heads_counts = count_heads_by_owner(cash)
    time_progress = digest['time_progress']
    workdays = digest['remaining_workdays']
    people = []
    for person in digest.get('people') or []:
        item = dict(person)
        item['orders_actual'] = float(order_counts.get(item['display_name'], 0))
        item['cash_actual'] = float(cash_sum.get(item['display_name'], 0))
        item['heads_actual'] = float(heads_counts.get(item['display_name'], 0))
        item['orders_completion'] = completion_rate(item['orders_actual'], item['orders_target'])
        item['cash_completion'] = completion_rate(item['cash_actual'], item['cash_target'])
        item['heads_completion'] = completion_rate(item['heads_actual'], item.get('heads_target'))
        target = item['orders_target']
        item['expected_orders'] = target * time_progress if target and target > 0 else None
        item['orders_gap'] = None if item['expected_orders'] is None else item['expected_orders'] - item['orders_actual']
        item['remaining_orders'] = max(0.0, (target or 0) - item['orders_actual']) if target and target > 0 else None
        item['behind'] = item['orders_completion'] is not None and item['orders_completion'] < time_progress
        if item['remaining_orders'] is None:
            item['daily_orders'] = None
        elif item['remaining_orders'] <= 0:
            item['daily_orders'] = 0.0
        elif workdays <= 0:
            item['daily_orders'] = None
        else:
            item['daily_orders'] = item['remaining_orders'] / workdays
        people.append(item)
    for kind, amount_column in (('orders', None), ('cash', '报入现金收入')):
        table = warehouse[kind]
        index = table['columns'].index(amount_column) if amount_column else None
        totals = {'total': 0.0, 'attributed': 0.0, 'unattributed': 0.0,
                  'total_rows': 0, 'attributed_rows': 0, 'unattributed_rows': 0}
        for row in table['rows']:
            value = float(row[index] or 0) if index is not None else 1.0
            bucket = 'attributed' if owner_names(row[0]) else 'unattributed'
            totals['total'] += value
            totals[bucket] += value
            totals['total_rows'] += 1
            totals[bucket + '_rows'] += 1
        digest[kind] = totals
    digest['people'] = people
    digest['behind'] = [row for row in people if row['behind']]
    return digest
