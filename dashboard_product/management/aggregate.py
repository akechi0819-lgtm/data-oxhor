"""Deterministic rollups for the isolated management dashboard."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from dashboard_product.management.windowing import metric, periods as online_periods
from workspace_modeling.operations.personnel import (
    BUSINESS_GROUP_BY_ROSTER_GROUP,
    ORDER_STATUS_MODES,
    ORDER_STATUS_VALUES,
    activity_co_creation_weights,
    is_displayable_person,
    order_status_allowed,
)


TEAM_DEFS = (
    ('total', '市场总计'),
    ('prep', '留学预备'),
    ('high', '高中'),
    ('university', '大学'),
    ('virtual', '虚拟人'),
    ('online', '线上平台'),
)
GROUP_BY_TEAM = {'prep': '留学预备', 'high': '高中', 'university': '大学'}
TRAINING_TEAM_ID = {
    'prep': 'offline_market', 'high': 'offline_market', 'university': 'offline_market',
    'virtual': 'online_private', 'online': 'online_platform',
}
ABROAD_NOT_CONFIGURED_TEAMS = frozenset({'prep', 'high'})
ABROAD_OFFLINE_TEAM = 'offline_market'
ABROAD_ONLINE_TEAM = 'online_platform'
ABROAD_METRICS_NOTE = '留学毛签使用签约金额，小语种使用实缴金额；两类客户分别去重。'
METRIC_UNITS = {'orders': '单', 'cash': '元', 'heads': '人'}
CENT = Decimal('0.01')
ONE = Decimal('1')


def _date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _text(value):
    return str(value or '').strip()


def _decimal(value):
    if value in (None, ''):
        return Decimal(0)
    return Decimal(str(value))


def _number(value, *, money=False):
    amount = _decimal(value)
    if money:
        amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    if amount == amount.to_integral_value():
        return int(amount)
    return float(amount)


def _round_target(value):
    if value is None:
        return None
    return int(_decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def _sum_numbers(values, *, money=False):
    values = list(values)
    if not values:
        return 0
    total = sum((_decimal(value) for value in values), Decimal(0))
    return _number(total, money=money)


def _month_ids(period):
    kind = period['kind']
    if kind == 'month':
        return [period['id']]
    if kind == 'quarter':
        quarter_months = {
            'Q1': [(2026, 6), (2026, 7), (2026, 8)],
            'Q2': [(2026, 9), (2026, 10), (2026, 11)],
            'Q3': [(2026, 12), (2027, 1), (2027, 2)],
            'Q4': [(2027, 3), (2027, 4), (2027, 5)],
        }
        return [f'{year:04d}-{month:02d}' for year, month in quarter_months[period['id']]]
    return [f'{year:04d}-{month:02d}' for year, month in
            ([(2026, month) for month in range(6, 13)] + [(2027, month) for month in range(1, 6)])]


def _calendar_month_window(period):
    """Return the personal performance window matching a dashboard period."""
    months = _month_ids(period)
    first_year, first_month = map(int, months[0].split('-'))
    last_year, last_month = map(int, months[-1].split('-'))
    prior_month = first_month - 1
    prior_year = first_year
    if prior_month == 0:
        prior_year -= 1
        prior_month = 12
    start = date(prior_year, prior_month, 26)
    end = date(last_year, last_month, 25)
    return start, end


def _shift_year(value):
    try:
        return value.replace(year=value.year - 1)
    except ValueError:  # Feb 29
        return value.replace(year=value.year - 1, day=28)


def _business_group(group, person):
    return person.get('business_group') or BUSINESS_GROUP_BY_ROSTER_GROUP.get(group)


def _roster(people_config, abroad_people_config):
    people = {}

    def entry(name):
        if name not in people:
            people[name] = {
                'name': name,
                'home_group': None,
                'team_ids': set(),
                'lines': set(),
                'targets': {'training': {}, 'abroad': {}},
                'training_roster': False,
                'abroad_roster': False,
            }
        return people[name]

    for team in people_config.get('teams', []):
        team_id = team.get('team_id')
        # Platform has no confirmed individual KPI roster.
        if team_id not in ('offline_market', 'online_private'):
            continue
        for group in team.get('groups', []):
            group_name = group.get('display_name')
            for person in group.get('members', []):
                if not is_displayable_person(person):
                    continue
                name = _text(person.get('display_name'))
                if not name:
                    continue
                row = entry(name)
                row['home_group'] = _business_group(group_name, person) or row['home_group']
                row['team_ids'].add(team_id)
                row['lines'].add('training')
                row['training_roster'] = True
                row['targets']['training'].update(person.get('monthly_targets') or {})

    for person in abroad_people_config.get('people', []):
        if not is_displayable_person(person):
            continue
        name = _text(person.get('display_name'))
        if not name:
            continue
        row = entry(name)
        business_group = _text(person['business_group'])
        if not row['training_roster']:
            row['home_group'] = business_group
        row['team_ids'].add(ABROAD_OFFLINE_TEAM)
        row['lines'].add('abroad')
        row['abroad_roster'] = True
        row['targets']['abroad'].update(person.get('monthly_targets') or {})

    result = []
    for row in people.values():
        row['team_ids'] = frozenset(row['team_ids'])
        row['lines'] = frozenset(row['lines'])
        if row['training_roster'] and row['abroad_roster']:
            row['business_line'] = 'training+abroad'
        elif row['training_roster']:
            row['business_line'] = 'training'
        else:
            row['business_line'] = 'abroad'
        result.append(row)
    return sorted(result, key=lambda row: row['name'])


def _owners(fact):
    seen = set()
    for name in fact.get('owners') or []:
        cleaned = _text(name)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
    return sorted(seen)


def _valid_facts(facts, through, *, include_non_completion=False):
    end = _date(through)
    cleaned = []
    for fact in facts:
        event_date = _date(fact['event_date'])
        if event_date > end:
            continue
        if fact.get('metric') not in ('orders', 'cash'):
            continue
        if not include_non_completion and fact.get('metric') == 'orders' and (
                fact.get('counts_toward_completion') is False
                or _text(fact.get('order_status')) in ('删除', '回收')):
            continue
        if fact.get('business_line') not in ('training', 'abroad'):
            continue
        row = dict(fact)
        row['event_date'] = event_date
        row['value'] = _decimal(fact.get('value'))
        row['owners'] = _owners(fact)
        row['virtual_owners'] = _owners({'owners': fact.get('virtual_owners')})
        cleaned.append(row)
    return cleaned


def _in_window(fact, start, end):
    return start <= fact['event_date'] <= end


def _sum_fact_values(facts, business_line, metric_name, start, end, predicate=None):
    return _sum_numbers(
        (fact['value'] for fact in facts
         if fact['business_line'] == business_line and fact['metric'] == metric_name
         and _in_window(fact, start, end) and (predicate is None or predicate(fact))),
        money=metric_name == 'cash',
    )


def _unique_heads(facts, business_line, start, end, predicate=None):
    if business_line == 'training':
        from .windowing import qualified_students
        return len(qualified_students(f for f in facts if f['business_line']=='training'
            and f['metric']=='cash' and _in_window(f,start,end)
            and (predicate is None or predicate(f))))
    students = set()
    for fact in facts:
        if (fact['business_line'] != business_line or fact['metric'] != 'cash'
                or fact['value'] <= 0 or not _in_window(fact, start, end)
                or (predicate is not None and not predicate(fact))):
            continue
        student_id = _text(fact.get('student_id'))
        if student_id:
            students.add(student_id)
    if business_line == 'abroad':
        parts = _abroad_head_parts(facts, start, end, predicate)
        if all(part['actual'] for part in parts):
            return None
    return len(students)


def _abroad_head_parts(facts, start, end, predicate=None):
    customers = {'study_abroad': set(), 'small_language': set()}
    for fact in facts:
        if (fact['business_line'] == 'abroad' and fact['metric'] == 'cash'
                and fact['value'] > 0 and _in_window(fact, start, end)
                and (predicate is None or predicate(fact))):
            key = _text(fact.get('student_id'))
            domain = fact.get('customer_domain') or fact.get('source_product')
            if key and domain in customers:
                customers[domain].add(key)
    return [{'label': label, 'actual': len(customers[key])}
            for key, label in (('study_abroad', '留学'), ('small_language', '小语种'))]


def _abroad_window(period, start=None, through=None):
    """Clip a requested period to the explicitly declared isolated source."""
    source = period['abroad_source']
    explicit_personal_window = start is not None and through is not None
    if not explicit_personal_window and (period.get('status') == 'future' or not period.get('through_date')):
        return None
    start = _date(start or period['start_date'])
    through = _date(through or period['through_date'])
    left = max(start, _date(source['start_date']))
    right = min(through, _date(source['through_date']))
    if left > right:
        return None
    return left, right, ('partial' if left != start or right != through else 'available')


def _abroad_metric(facts, kind, predicate, period, target=None, *, start=None, through=None, progress=None):
    source = period['abroad_source']
    progress = period.get('time_progress', 0) if progress is None else progress
    window = _abroad_window(period, start, through)
    if window is None:
        future = ((start is None and period.get('status') == 'future')
                  or (start is not None and through is not None and _date(through) < _date(start)))
        status = 'future' if future else 'not_covered'
        return {**metric(None, None, target, progress, METRIC_UNITS[kind], status=status),
                'source_coverage': dict(source)}
    left, right, status = window
    actual = (_unique_heads(facts, 'abroad', left, right, predicate) if kind == 'heads'
              else _sum_fact_values(facts, 'abroad', kind, left, right, predicate))
    result = metric(actual, None, target, progress, METRIC_UNITS[kind])
    result.update(status=status, source_coverage={**source, 'start_date': left.isoformat(), 'through_date': right.isoformat()})
    if status == 'partial':
        result.update(gap=None, time_gap=None)
    if kind == 'heads':
        result['parts'] = _abroad_head_parts(facts, left, right, predicate)
        if actual is None:
            result.update(status='separate_counts', display='／'.join(
                f"{part['label']}{part['actual']}人" for part in result['parts']))
    return result


def _training_filter(team_id=None, group=None):
    def matches(fact):
        if team_id is not None and fact.get('team_id') != team_id:
            return False
        if team_id is not None and fact.get('business_group') not in GROUP_BY_TEAM.values():
            return False
        if group is not None and fact.get('business_group') != group:
            return False
        return True
    return matches


def _training_target(config, period, team_id, group=None):
    field = 'work_order_target' if 'orders' in period.get('_metric_kind', 'orders') else 'passive_cash_target'
    # The helper is called with an explicit order/cash kind through a short-lived
    # copy key, keeping the external aggregate interface small.
    rows = [row for row in config.get('business_groups', {}).values()
            if group is None or row.get('display_name') == group]
    if not rows:
        return None
    values = []
    for row in rows:
        if period['kind'] == 'month':
            value = ((row.get('months') or {}).get(period['id']) or {}).get(team_id, {}).get(field)
            values.append(value)
        else:
            quarters = [period['id']] if period['kind'] == 'quarter' else ['Q1', 'Q2', 'Q3', 'Q4']
            for quarter in quarters:
                value = ((((row.get('quarters') or {}).get(quarter) or {}).get(team_id)) or {}).get(field)
                values.append(value)
    if not values or any(value is None for value in values):
        return None
    return _number(sum((_decimal(value) for value in values), Decimal(0)), money=field == 'passive_cash_target')


def _offline_abroad_target(config, period):
    target = config.get('total', {})
    if period['kind'] == 'year':
        value = target.get('work_order_target')
    elif period['kind'] == 'month':
        value = (target.get('months') or {}).get(period['id'])
    else:
        value = (target.get('quarters') or {}).get(period['id'])
    return None if value is None else _number(value)


def _online_abroad_target(config, period):
    resource = ((config.get('study_abroad') or {}).get('resource_target')
                or config.get('resource_target') or {})
    key = 'annual' if period['kind'] == 'year' else ('months' if period['kind'] == 'month' else 'quarters')
    value = resource.get(key) if key == 'annual' else (resource.get(key) or {}).get(period['id'])
    return None if value is None else _number(value)


def _department_training_target(config, period, team_id, group=None):
    order_period = dict(period, _metric_kind='orders')
    return _training_target(config, order_period, team_id, group)


def _department_training_cash_target(config, period, team_id, group=None):
    cash_period = dict(period, _metric_kind='cash')
    return _training_target(config, cash_period, team_id, group)


def _team_target(configs, period, team_id, line, kind, facts):
    training_targets, offline_abroad_targets, online_abroad_targets = configs
    if kind == 'heads':
        return None
    if line == 'training':
        if team_id == 'total':
            values = []
            for team_key in ('prep', 'high', 'university', 'virtual', 'online'):
                value = _team_target(configs, period, team_key, line, kind, facts)
                if value is None:
                    return None
                values.append(value)
            # Preserve the original market board: sum the configured team targets.
            return _number(sum((_decimal(v) for v in values), Decimal(0)), money=kind == 'cash')
        team_config_id = TRAINING_TEAM_ID.get(team_id)
        if team_id in GROUP_BY_TEAM:
            group = GROUP_BY_TEAM[team_id]
        else:
            group = None
        if team_config_id is None:
            return None
        return (_department_training_target(training_targets, period, team_config_id, group)
                if kind == 'orders' else
                _department_training_cash_target(training_targets, period, team_config_id, group))

    if kind == 'cash' and team_id in ('online', 'university'):
        from dashboard_product.management.windowing import study_target
        cash_config = online_abroad_targets if team_id == 'online' else offline_abroad_targets
        return study_target(cash_config, period, 'cash') if 'cash' in cash_config else None
    if kind != 'orders':
        return None
    if team_id == 'university':
        return _offline_abroad_target(offline_abroad_targets, period)
    if team_id == 'online':
        return _online_abroad_target(online_abroad_targets, period)
    # Total includes unassigned contributions without a confirmed aggregate target.
    return None


def _team_fact_filter(team_id, line):
    if team_id == 'total':
        return lambda fact: True
    if line == 'training':
        if team_id in GROUP_BY_TEAM:
            return _training_filter(TRAINING_TEAM_ID[team_id], GROUP_BY_TEAM[team_id])
        if team_id in ('virtual', 'online'):
            return _training_filter(TRAINING_TEAM_ID[team_id])
        return lambda fact: False
    if team_id == 'university':
        return lambda fact: fact.get('segment_id') == 'study_abroad_offline'
    if team_id == 'online':
        return lambda fact: fact.get('segment_id') == 'study_abroad_online'
    if team_id == 'virtual':
        return lambda fact: fact.get('segment_id') == 'study_abroad_virtual'
    # Prep/high abroad ownership has not been confirmed.
    return lambda fact: False


def _metric_for_period(facts, line, kind, predicate, period, target, *, note=''):
    status = period['status']
    if line == 'abroad' and note == 'not_configured':
        if status == 'future':
            return metric(None, None, target, period.get('time_progress', 0), METRIC_UNITS[kind],
                          status='future', note='本部门暂不统计留学完成；贡献见人员产能。')
        return metric(None, None, None, period.get('time_progress', 0), METRIC_UNITS[kind],
                      status='not_configured', note='本部门暂不统计留学完成；贡献见人员产能。')
    if line == 'abroad':
        return _abroad_metric(facts, kind, predicate, period, target)
    if status == 'future' or not period.get('through_date'):
        return metric(None, None, target, period.get('time_progress', 0), METRIC_UNITS[kind],
                      status='future', note=note)
    start, through = _date(period['start_date']), _date(period['through_date'])
    actual = (_unique_heads(facts, line, start, through, predicate) if kind == 'heads'
              else _sum_fact_values(facts, line, kind, start, through, predicate))
    prior_start, prior_through = _shift_year(start), _shift_year(through)
    prior = (_unique_heads(facts, line, prior_start, prior_through, predicate) if kind == 'heads'
             else _sum_fact_values(facts, line, kind, prior_start, prior_through, predicate))
    return metric(actual, prior, target, period.get('time_progress', 0), METRIC_UNITS[kind], note=note)


def _personal_owners(person, fact, kind):
    if kind in ('orders', 'cash') and 'online_private' in person['team_ids']:
        return fact.get('virtual_owners') or []
    return fact.get('owners') or []


def _personal_qualification(person, fact, line, kind):
    if fact.get('segment_id') == 'international_market':
        return False
    virtual_personal = (kind in ('orders', 'cash')
                        and 'online_private' in person['team_ids'])
    if (fact.get('team_inferred') and fact.get('metric') == 'cash'
            and not virtual_personal):
        return False
    if virtual_personal and kind == 'orders' and _text(fact.get('order_status')) == '无效':
        return False
    if line == 'training':
        if not person['training_roster'] and not person['abroad_roster']:
            return False
        if virtual_personal:
            return True
        if fact.get('team_id') not in person['team_ids']:
            return False
        return bool(person['home_group']) and fact.get('business_group') == person['home_group']
    if line == 'abroad':
        # Actual study-abroad contributions remain visible even without a target.
        return bool(person['training_roster'] or person['abroad_roster'])
    return False


def _personal_order_status_allowed(fact, mode):
    """Apply the completion-page selector without changing legacy callers."""
    if mode is None:
        return True
    order_status = _text(fact.get('order_status'))
    if not order_status_allowed(order_status, mode):
        return False
    if order_status in ORDER_STATUS_VALUES:
        return True
    # Preserve any existing non-status eligibility flag outside the three
    # statuses explicitly opened by this selector.
    return fact.get('counts_toward_completion') is not False


def _personal_weights(fact, kind, roster_by_name):
    names = list(fact.get('owners') or [])
    if kind in ('orders', 'cash'):
        names.extend(fact.get('virtual_owners') or [])
    return activity_co_creation_weights(
        names, roster_by_name, fact.get('business_line'), fact.get('campaign_name'),
    )


def _personal_weighted_facts(facts, person, line, kind, start, end, roster_by_name,
                             *, order_status_mode=None):
    source_kind = 'cash' if kind == 'heads' else kind
    for fact in facts:
        if (fact['business_line'] != line
                or fact['metric'] != source_kind
                or not _in_window(fact, start, end)
                or (kind == 'orders'
                    and not _personal_order_status_allowed(fact, order_status_mode))
                or person['name'] not in _personal_owners(person, fact, kind)
                or not _personal_qualification(person, fact, line, kind)):
            continue
        weights = _personal_weights(fact, source_kind, roster_by_name)
        if person['name'] in weights:
            yield fact, weights


def _person_month_target(person, month_id, target_line):
    targets = person['targets']
    own = 'training' if person['training_roster'] else 'abroad'
    primary = (targets.get(own) or {}).get(month_id) or {}
    base = primary.get('orders')
    if target_line == own:
        return None if base is None else _round_target(base)
    if person['home_group'] != '大学' or not (person['training_roster'] or person['abroad_roster']):
        return None
    if own == 'training' and not any(team_id == 'offline_market' for team_id in person['team_ids']):
        return None
    # 2026-11大学语培线下人员的留学目标按用户确认值优先，不套用10%规则。
    if (target_line == 'abroad' and own == 'training' and month_id == '2026-11'
            and 'study_abroad_orders' in primary):
        return _round_target(primary['study_abroad_orders'])
    if base is None:
        return None
    # Other reciprocal targets use 10%; the 2026-11 explicit abroad target returns above.
    return _round_target(_decimal(base) * Decimal('0.1'))


def _personal_target(person, period, target_line):
    values = [_person_month_target(person, month_id, target_line) for month_id in _month_ids(period)]
    configured = [value for value in values if value is not None]
    if len(configured) != len(values):
        return None
    return sum(configured)


def _personal_cash_target(person, period):
    primary = 'training' if person['training_roster'] else 'abroad'
    values = [(person['targets'][primary].get(m) or {}).get('cash') for m in _month_ids(period)]
    return None if any(v is None for v in values) else _sum_numbers(values, money=True)


def _personal_actual(facts, person, line, kind, start, end, roster_by_name,
                     *, order_status_mode=None):
    matching = list(_personal_weighted_facts(
        facts, person, line, kind, start, end, roster_by_name,
        order_status_mode=order_status_mode,
    ))
    if kind == 'heads':
        credit = {}
        for fact, weights in matching:
            if fact['metric'] != 'cash' or fact['value'] <= 0:
                continue
            student_id = _text(fact.get('student_id'))
            if not student_id:
                continue
            weight = weights.get(person['name'], Decimal(0))
            if weight:
                credit[student_id] = max(credit.get(student_id, Decimal(0)), weight)
        return _number(sum(credit.values(), Decimal(0)))
    return _sum_numbers(
        (fact['value'] * weights[person['name']] for fact, weights in matching),
        money=kind == 'cash',
    )


def _personal_abroad_channels(facts, person, start, end, prior_start, prior_end,
                              roster_by_name, actual, status, progress,
                              *, order_status_mode=None):
    if status == 'future':
        return []
    grouped = defaultdict(lambda: {'actual': Decimal(0), 'prior': Decimal(0)})
    for fact, weights in _personal_weighted_facts(
            facts, person, 'abroad', 'orders', start, end, roster_by_name,
            order_status_mode=order_status_mode):
        first = _text(fact.get('first_channel')) or '一级渠道待确认'
        second = _text(fact.get('second_channel')) or '二级渠道待确认'
        grouped[(first, second)]['actual'] += fact['value'] * weights[person['name']]
    for fact, weights in _personal_weighted_facts(
            facts, person, 'abroad', 'orders', prior_start, prior_end, roster_by_name,
            order_status_mode=order_status_mode):
        first = _text(fact.get('first_channel')) or '一级渠道待确认'
        second = _text(fact.get('second_channel')) or '二级渠道待确认'
        grouped[(first, second)]['prior'] += fact['value'] * weights[person['name']]

    identities = sorted(grouped)
    rows = []
    for first, second in identities:
        values = grouped[(first, second)]
        orders = metric(_number(values['actual']), None, None,
                        progress, '单', status=status)
        share = (float(_decimal(orders['actual']) / _decimal(actual))
                 if orders['actual'] is not None and actual not in (None, 0) else None)
        rows.append({
            'name': second,
            'first_channel': first,
            'orders': orders,
            'share': share,
        })
    return rows


def _personal_metric(value, prior, target, status, unit, note='', progress=0):
    if status == 'future':
        value = prior = None
    if status == 'not_connected':
        value = prior = None
    return metric(value, prior, target, progress, unit, status=status, note=note)


def _personal_order_values(facts, person, start, effective_end, prior_start, prior_end,
                           roster_by_name, training_target, abroad_target, status, progress,
                           *, period, order_status_mode=None):
    if order_status_mode is not None:
        order_status_allowed(None, order_status_mode)
    abroad_window = None
    if status == 'future':
        train_actual = abroad_actual = train_prior = abroad_prior = None
        combined_actual = combined_prior = None
    else:
        train_actual = _personal_actual(
            facts, person, 'training', 'orders', start, effective_end, roster_by_name,
            order_status_mode=order_status_mode,
        )
        abroad_window = _abroad_window(period, start, effective_end)
        abroad_actual = (_personal_actual(
            facts, person, 'abroad', 'orders', abroad_window[0], abroad_window[1], roster_by_name,
            order_status_mode=order_status_mode,
        ) if abroad_window else None)
        train_prior = _personal_actual(
            facts, person, 'training', 'orders', prior_start, prior_end, roster_by_name,
            order_status_mode=order_status_mode,
        )
        abroad_prior = None
        combined_actual = (_number(_decimal(train_actual) + _decimal(abroad_actual))
                           if abroad_actual is not None else None)
        combined_prior = None
        if 'online_private' in person['team_ids']:
            # The new source excludes 国际市场 from all training/virtual views.
            combined_actual, combined_prior = train_actual, train_prior

    values = {
        'training_target': training_target,
        'training_actual': train_actual,
        'training_prior': train_prior,
        'training_completion': (train_actual / training_target
                                if train_actual is not None and training_target else None),
        'combined_target': training_target,
        'combined_actual': combined_actual,
        'combined_prior': combined_prior,
        'combined_completion': (combined_actual / training_target
                                if combined_actual is not None and training_target
                                and ('online_private' in person['team_ids']
                                     or (abroad_window and abroad_window[2] == 'available')) else None),
        'abroad_target': abroad_target,
        'abroad_actual': abroad_actual,
        'abroad_prior': abroad_prior,
        'abroad_completion': (abroad_actual / abroad_target
                              if abroad_actual is not None and abroad_target
                              and abroad_window and abroad_window[2] == 'available' else None),
    }
    if person['home_group'] == '高中' and person['abroad_roster']:
        values['abroad_channels'] = _personal_abroad_channels(
            facts, person, start, effective_end, prior_start, prior_end,
            roster_by_name, abroad_actual, status, progress,
            order_status_mode=order_status_mode,
        )
    return values


def _owner_fact_index(facts):
    result = defaultdict(list)
    for fact in facts:
        for owner in dict.fromkeys([*(fact.get('owners') or []),
                                    *(fact.get('virtual_owners') or [])]):
            result[owner].append(fact)
    return result


def _people_for_period(facts, roster, period, through, mode='performance', *,
                       order_status_facts=None):
    if mode == 'performance':
        start, end = _calendar_month_window(period)
    elif mode == 'calendar':
        start, end = _date(period['start_date']), _date(period['end_date'])
    else:
        raise ValueError(f'unsupported personal period mode: {mode}')
    effective_end = min(end, through)
    status = 'future' if through < start else 'available'
    through_value = None if status == 'future' else effective_end.isoformat()
    progress = 0 if status == 'future' else ((effective_end-start).days+1)/((end-start).days+1)
    prior_start = _shift_year(start)
    prior_end = _shift_year(effective_end) if status == 'available' else _shift_year(end)
    rows = []
    roster_by_name = {person['name']: person for person in roster}
    owner_facts = _owner_fact_index(facts)
    status_owner_facts = (_owner_fact_index(order_status_facts)
                          if order_status_facts is not None else None)
    for person in roster:
        personal_facts = owner_facts[person['name']]
        train_target = _personal_target(person, period, 'training')
        abroad_target = _personal_target(person, period, 'abroad')
        order_values = _personal_order_values(
            personal_facts, person, start, effective_end, prior_start, prior_end,
            roster_by_name, train_target, abroad_target, status, progress, period=period,
        )
        if status == 'future':
            cash_actual = heads_actual = cash_prior = heads_prior = None
            cash_status = heads_status = 'future'
        else:
            if person['training_roster']:
                cash_actual = _personal_actual(personal_facts, person, 'training', 'cash', start, effective_end, roster_by_name)
                heads_actual = _personal_actual(personal_facts, person, 'training', 'heads', start, effective_end, roster_by_name)
                cash_prior = _personal_actual(personal_facts, person, 'training', 'cash', prior_start, prior_end, roster_by_name)
                heads_prior = _personal_actual(personal_facts, person, 'training', 'heads', prior_start, prior_end, roster_by_name)
                cash_status = heads_status = 'available'
            else:
                cash_actual = heads_actual = cash_prior = heads_prior = None
                cash_status = heads_status = 'not_covered'
        personal_scope = lambda fact: (person['name'] in (fact.get('owners') or [])
                                      and _personal_qualification(person, fact, 'abroad', fact['metric']))
        abroad_cash = _abroad_metric(personal_facts, 'cash', personal_scope, period,
                                     _personal_cash_target(person, period),
                                     start=start, through=effective_end, progress=progress)
        abroad_heads = _abroad_metric(personal_facts, 'heads', personal_scope, period,
                                      start=start, through=effective_end, progress=progress)
        person_row = {
            'name': person['name'],
            'home_group': person['home_group'],
            'business_line': person['business_line'],
            **order_values,
            'cash_actual': (_personal_metric(cash_actual, cash_prior, _personal_cash_target(person, period), cash_status, '元', progress=progress)
                            if person['training_roster'] else abroad_cash),
            'heads_actual': (_personal_metric(heads_actual, heads_prior, None, heads_status, '人')
                             if person['training_roster'] else abroad_heads),
            'abroad_source_coverage': dict(period['abroad_source']),
        }
        if status_owner_facts is not None:
            eligible_status_facts = status_owner_facts[person['name']]
            person_row['order_status_views'] = {
                status_mode: _personal_order_values(
                    eligible_status_facts, person, start, effective_end, prior_start, prior_end,
                    roster_by_name, train_target, abroad_target, status, progress,
                    period=period, order_status_mode=status_mode,
                )
                for status_mode in ORDER_STATUS_MODES
            }
        rows.append(person_row)
    return start.isoformat(), through_value, rows, progress


def _activities(facts):
    grouped = defaultdict(lambda: {
        'training_orders': Decimal(0), 'abroad_orders': Decimal(0),
        'cash': Decimal(0), 'customers': defaultdict(set), 'has_abroad': False, 'has_training': False,
    })
    for fact in facts:
        name = _text(fact.get('campaign_name')) or '未填写活动'
        row = grouped[name]
        row['has_training'] |= fact['business_line'] == 'training'
        if fact['metric'] == 'orders':
            row['training_orders' if fact['business_line'] == 'training' else 'abroad_orders'] += fact['value']
            if fact['business_line'] == 'abroad':
                row['has_abroad'] = True
        elif fact['metric'] == 'cash':
            row['cash'] += fact['value']
            if fact['value'] > 0 and _text(fact.get('student_id')):
                domain = ('training' if fact['business_line'] == 'training'
                          else fact['customer_domain'])
                row['customers'][domain].add(_text(fact.get('student_id')))
            row['has_abroad'] |= fact['business_line'] == 'abroad'
    rows = []
    for name, row in sorted(grouped.items()):
        training_orders = _number(row['training_orders'])
        abroad_orders = _number(row['abroad_orders'])
        parts = [{'label': label, 'actual': len(row['customers'][domain])}
                 for domain, label in (('training', '语培'), ('study_abroad', '留学'), ('small_language', '小语种'))
                 if row['customers'][domain]]
        rows.append({
            'name': name,
            'training_orders': training_orders,
            'abroad_orders': abroad_orders,
            'orders': _number(row['training_orders'] + row['abroad_orders']),
            'cash': _number(row['cash'], money=True),
            'heads': sum(part['actual'] for part in parts) if len(parts) <= 1 else None,
            'heads_parts': parts,
            'heads_display': '／'.join(f"{part['label']}{part['actual']}人" for part in parts) if len(parts) > 1 else None,
            'cash_status': 'partial' if row['has_training'] and row['has_abroad'] else 'available',
        })
    return rows


def _countries(facts, start, through):
    grouped = defaultdict(lambda: {'online': Decimal(0), 'offline': Decimal(0), 'unassigned': Decimal(0)})
    for fact in facts:
        if fact['business_line'] != 'abroad' or fact['metric'] != 'orders' or not _in_window(fact, start, through):
            continue
        line = _text(fact.get('line')) or '条线待确认'
        country = _text(fact.get('country')) or '国家待确认'
        row = grouped[(line, country)]
        segment = fact.get('segment_id')
        if segment == 'study_abroad_offline':
            row['offline'] += fact['value']
        elif segment == 'study_abroad_online':
            row['online'] += fact['value']
        else:
            row['unassigned'] += fact['value']
    result = []
    for (line, country), values in sorted(grouped.items()):
        online = _number(values['online'])
        offline = _number(values['offline'])
        unassigned = _number(values['unassigned'])
        result.append({'line': line, 'country': country, 'online': online, 'offline': offline,
                       'unassigned': unassigned,
                       'total': _number(values['online'] + values['offline'] + values['unassigned'])})
    return result


def aggregate(facts, people_config, abroad_people_config, training_targets,
              abroad_targets, online_abroad_targets, through, *, abroad_source, person_facts=None):
    """Aggregate normalized facts without reading source data or changing ownership.

    Team actuals use calendar periods. Person actuals keep the selected period's
    26th-to-25th performance window, with a parallel natural-calendar view.
    """
    through = _date(through)
    team_facts = _valid_facts(facts, through, include_non_completion=True)
    personal_source = facts if person_facts is None else person_facts
    personal_facts = _valid_facts(personal_source, through)
    personal_status_facts = _valid_facts(personal_source, through, include_non_completion=True)
    roster = _roster(people_config, abroad_people_config)
    configs = (training_targets, abroad_targets, online_abroad_targets)
    period_rows = []
    for source_period in online_periods(through):
        period = {**source_period, 'abroad_source': dict(abroad_source)}
        team_rows = []
        person_start, person_through, people_rows, person_progress = _people_for_period(
            personal_facts, roster, period, through, order_status_facts=personal_status_facts,
        )
        calendar_start, calendar_through, calendar_people_rows, calendar_progress = _people_for_period(
            personal_facts, roster, period, through, mode='calendar',
            order_status_facts=personal_status_facts,
        )
        people_map = {person['name']: person for person in roster}
        for team_id, name in TEAM_DEFS:
            lines = {}
            for line in ('training', 'abroad'):
                metrics = {}
                for kind in ('orders', 'cash', 'heads'):
                    note = ''
                    if line == 'abroad' and team_id in ABROAD_NOT_CONFIGURED_TEAMS:
                        note = 'not_configured'
                    predicate = _team_fact_filter(team_id, line)
                    target = _team_target(configs, period, team_id, line, kind, team_facts)
                    metrics[kind] = _metric_for_period(
                        team_facts, line, kind, predicate, period, target, note=note,
                    )
                lines[line] = metrics
                if line == 'abroad':
                    lines[line]['source_coverage'] = dict(abroad_source)
                    if team_id == 'total':
                        lines[line]['supplemental'] = [
                            {'id': segment, 'name': label,
                             **{kind: _abroad_metric(team_facts, kind,
                                 lambda fact, segment=segment: fact.get('segment_id') == segment, period)
                                for kind in ('orders', 'cash', 'heads')}}
                            for segment, label in (('international_market', '国际市场'), ('ssc', 'SSC'), ('unassigned', '归属待确认'))]
            selected_people = [row for row in people_rows if team_id == 'total' or
                (team_id in GROUP_BY_TEAM and 'offline_market' in people_map[row['name']]['team_ids']
                 and row['home_group'] == GROUP_BY_TEAM[team_id]) or
                (team_id == 'virtual' and 'online_private' in people_map[row['name']]['team_ids'])]
            selected_calendar_people = [row for row in calendar_people_rows if team_id == 'total' or
                (team_id in GROUP_BY_TEAM and 'offline_market' in people_map[row['name']]['team_ids']
                 and row['home_group'] == GROUP_BY_TEAM[team_id]) or
                 (team_id == 'virtual' and 'online_private' in people_map[row['name']]['team_ids'])]
            combined_orders = None
            if team_id == 'virtual':
                combined_orders = dict(lines['training']['orders'])
            country_scope = _team_fact_filter(team_id, 'abroad')
            countries = [] if not period.get('through_date') else _countries(
                [fact for fact in team_facts if country_scope(fact)],
                _date(period['start_date']), _date(period['through_date']))
            team_row = {'id': team_id, 'name': name, 'lines': lines,
                        'people': selected_people,
                        'person_start': person_start, 'person_through': person_through, 'person_progress': person_progress,
                        'person_calendar': {
                            'person_start': calendar_start,
                            'person_through': calendar_through,
                            'person_progress': calendar_progress,
                            'people': selected_calendar_people,
                        },
                        'countries': countries}
            if combined_orders is not None:
                team_row['combined_orders'] = combined_orders
            team_rows.append(team_row)
        if period['status'] == 'future' or not period.get('through_date'):
            country_rows = []
        else:
            country_rows = _countries(team_facts, _date(period['start_date']), _date(period['through_date']))
        # Person detail is a period-level table and appears once per period.
        period_rows.append({
            **period,
            'id': period['id'], 'label': period['label'],
            'start_date': period['start_date'], 'through_date': period['through_date'],
            'status': period['status'], 'teams': team_rows,
            'person_start': team_rows[0]['person_start'],
            'person_through': team_rows[0]['person_through'],
            'countries': country_rows,
        })
    return {
        'periods': period_rows,
        'activities': _activities(team_facts),
    }
