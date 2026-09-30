"""Deterministic rollups for the isolated management dashboard."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from dashboard_product.online_team.build import metric, periods as online_periods
from workspace_modeling.operations.personnel import (
    BUSINESS_GROUP_BY_ROSTER_GROUP,
    is_displayable_person,
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
ABROAD_NOT_CONFIGURED_TEAMS = frozenset({'prep', 'high', 'virtual'})
ABROAD_OFFLINE_TEAM = 'offline_market'
ABROAD_ONLINE_TEAM = 'online_platform'
ABROAD_METRICS_NOTE = '留学现金及人头数据尚未接入。'
CASH_CAPACITY = 800000
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
        name = _text(person.get('display_name'))
        if not name:
            continue
        row = entry(name)
        row['home_group'] = row['home_group'] or '大学'
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


def _valid_facts(facts, through):
    end = _date(through)
    cleaned = []
    for fact in facts:
        event_date = _date(fact['event_date'])
        if event_date > end:
            continue
        if fact.get('metric') not in ('orders', 'cash'):
            continue
        if fact.get('business_line') not in ('training', 'abroad'):
            continue
        row = dict(fact)
        row['event_date'] = event_date
        row['value'] = _decimal(fact.get('value'))
        row['owners'] = _owners(fact)
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
    students = set()
    for fact in facts:
        if (fact['business_line'] != business_line or fact['metric'] != 'cash'
                or fact['value'] <= 0 or not _in_window(fact, start, end)
                or (predicate is not None and not predicate(fact))):
            continue
        student_id = _text(fact.get('student_id'))
        if student_id:
            students.add(student_id)
    return len(students)


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


def _abroad_filter(team_id=None, owner_names=None):
    owner_names = set(owner_names or ())

    def matches(fact):
        if team_id is not None and fact.get('team_id') != team_id:
            return False
        if owner_names and not (owner_names.intersection(fact['owners'])):
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

    if kind != 'orders':
        return None
    if team_id == 'university':
        return _offline_abroad_target(offline_abroad_targets, period)
    if team_id == 'online':
        return _online_abroad_target(online_abroad_targets, period)
    # Total includes unassigned contributions without a confirmed aggregate target.
    return None


def _team_fact_filter(team_id, line, abroad_people_names):
    if team_id == 'total':
        return lambda fact: True
    if line == 'training':
        if team_id in GROUP_BY_TEAM:
            return _training_filter(TRAINING_TEAM_ID[team_id], GROUP_BY_TEAM[team_id])
        if team_id in ('virtual', 'online'):
            return _training_filter(TRAINING_TEAM_ID[team_id])
        return lambda fact: False
    if team_id == 'university':
        # The eight-person list is the only confirmed offline abroad assignment.
        owner_filter = _abroad_filter(ABROAD_OFFLINE_TEAM, abroad_people_names)
        return lambda fact: fact.get('business_group') == '大学' and owner_filter(fact)
    if team_id == 'online':
        return lambda fact: fact.get('team_id') == ABROAD_ONLINE_TEAM and fact.get('acquisition_mode') == 'online'
    # Prep/high/virtual abroad ownership has not been confirmed.
    return lambda fact: False


def _metric_for_period(facts, line, kind, predicate, period, target, *, note=''):
    status = period['status']
    if line == 'abroad' and kind in ('cash', 'heads'):
        if status == 'future':
            return metric(None, None, None, period.get('time_progress', 0), kind,
                          status='future', note=ABROAD_METRICS_NOTE)
        return metric(None, None, None, period.get('time_progress', 0), kind,
                      status='not_connected', note=ABROAD_METRICS_NOTE)
    if line == 'abroad' and kind == 'orders' and note == 'not_configured':
        if status == 'future':
            return metric(None, None, target, period.get('time_progress', 0), 'orders',
                          status='future', note='本部门暂不统计留学完成；贡献见人员产能。')
        return metric(None, None, None, period.get('time_progress', 0), 'orders',
                      status='not_configured', note='本部门暂不统计留学完成；贡献见人员产能。')
    if status == 'future' or not period.get('through_date'):
        return metric(None, None, target, period.get('time_progress', 0), kind,
                      status='future', note=note)
    start, through = _date(period['start_date']), _date(period['through_date'])
    actual = (_unique_heads(facts, line, start, through, predicate) if kind == 'heads'
              else _sum_fact_values(facts, line, kind, start, through, predicate))
    prior_start, prior_through = _shift_year(start), _shift_year(through)
    prior = (_unique_heads(facts, line, prior_start, prior_through, predicate) if kind == 'heads'
             else _sum_fact_values(facts, line, kind, prior_start, prior_through, predicate))
    return metric(actual, prior, target, period.get('time_progress', 0), kind, note=note)


def _personal_qualification(person, fact, line):
    if fact.get('team_inferred') and fact.get('metric') == 'cash':
        return False
    if line == 'training':
        if not person['training_roster'] and not person['abroad_roster']:
            return False
        if fact.get('team_id') not in person['team_ids']:
            return False
        return bool(person['home_group']) and fact.get('business_group') == person['home_group']
    if line == 'abroad':
        # Actual study-abroad contributions remain visible even without a target.
        return bool(person['training_roster'] or person['abroad_roster'])
    return False


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
    if base is None:
        return None
    # The reciprocal line is 10% of the roster's primary monthly order target.
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


def _personal_actual(facts, person, line, kind, start, end, roster_by_name=None):
    matching = [fact for fact in facts if fact['business_line'] == line
                and fact['metric'] == ('cash' if kind == 'heads' else kind) and _in_window(fact, start, end)
                and person['name'] in fact['owners']
                and _personal_qualification(person, fact, line)]
    if kind == 'heads':
        credit = {}
        for fact in matching:
            if fact['metric'] != 'cash' or fact['value'] <= 0:
                continue
            student_id = _text(fact.get('student_id'))
            if not student_id:
                continue
            eligible = [name for name in fact['owners'] if name in (roster_by_name or {})
                        and roster_by_name[name]['training_roster']
                        and _personal_qualification(roster_by_name[name], fact, line)]
            weight = Decimal(1) / Decimal(max(1, len(eligible)))
            credit[student_id] = max(credit.get(student_id, Decimal(0)), weight)
        return _number(sum(credit.values(), Decimal(0)))
    return _sum_numbers((fact['value'] for fact in matching), money=kind == 'cash')


def _personal_metric(value, prior, target, status, unit, note='', progress=0):
    if status == 'future':
        value = prior = None
    if status == 'not_connected':
        value = prior = None
    return metric(value, prior, target, progress, unit, status=status, note=note)


def _people_for_period(facts, roster, period, through, mode='performance'):
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
    owner_facts = defaultdict(list)
    for fact in facts:
        for owner in fact['owners']:
            owner_facts[owner].append(fact)
    for person in roster:
        personal_facts = owner_facts[person['name']]
        train_target = _personal_target(person, period, 'training')
        abroad_target = _personal_target(person, period, 'abroad')
        if status == 'future':
            train_actual = abroad_actual = train_prior = abroad_prior = None
            cash_actual = heads_actual = cash_prior = heads_prior = None
            cash_status = heads_status = 'future'
        else:
            train_actual = _personal_actual(personal_facts, person, 'training', 'orders', start, effective_end)
            abroad_actual = _personal_actual(personal_facts, person, 'abroad', 'orders', start, effective_end)
            train_prior = _personal_actual(personal_facts, person, 'training', 'orders', prior_start, prior_end)
            abroad_prior = _personal_actual(personal_facts, person, 'abroad', 'orders', prior_start, prior_end)
            if person['training_roster']:
                cash_actual = _personal_actual(personal_facts, person, 'training', 'cash', start, effective_end)
                heads_actual = _personal_actual(personal_facts, person, 'training', 'heads', start, effective_end, roster_by_name)
                cash_prior = _personal_actual(personal_facts, person, 'training', 'cash', prior_start, prior_end)
                heads_prior = _personal_actual(personal_facts, person, 'training', 'heads', prior_start, prior_end, roster_by_name)
                cash_status = heads_status = 'available'
            else:
                cash_actual = heads_actual = cash_prior = heads_prior = None
                cash_status = heads_status = 'not_connected'
        rows.append({
            'name': person['name'],
            'home_group': person['home_group'],
            'business_line': person['business_line'],
            'training_target': train_target,
            'training_actual': train_actual,
            'training_prior': train_prior,
            'training_completion': train_actual / train_target if train_actual is not None and train_target else None,
            'abroad_target': abroad_target,
            'abroad_actual': abroad_actual,
            'abroad_prior': abroad_prior,
            'abroad_completion': abroad_actual / abroad_target if abroad_actual is not None and abroad_target else None,
            'cash_actual': _personal_metric(cash_actual, cash_prior, _personal_cash_target(person, period), cash_status, 'cash',
                                           ABROAD_METRICS_NOTE if cash_status == 'not_connected' else '', progress=progress),
            'heads_actual': _personal_metric(heads_actual, heads_prior, None, heads_status, 'heads',
                                            ABROAD_METRICS_NOTE if heads_status == 'not_connected' else ''),
        })
    return start.isoformat(), through_value, rows, progress


def _capacity(facts, roster, through, cash_capacity=CASH_CAPACITY, start=None):
    start = start or date(2026, 6, 1)
    year_end = date(start.year + 1, 5, 31)
    end = min(year_end, through)
    fy_days = (year_end - start).days + 1
    progress = max(0, min(1, ((end - start).days + 1) / fy_days))
    target_to_date = cash_capacity * progress
    capacity = []
    for person in roster:
        owned = [fact for fact in facts if person['name'] in fact['owners']
                 and _in_window(fact, start, end)]
        order_facts = [fact for fact in owned if fact['metric'] == 'orders']
        training_orders = [fact for fact in order_facts if fact['business_line'] == 'training']
        abroad_orders = [fact for fact in order_facts if fact['business_line'] == 'abroad']
        cash_facts = [fact for fact in owned if fact['business_line'] == 'training' and fact['metric'] == 'cash']
        cash_value = _sum_numbers((fact['value'] for fact in cash_facts), money=True)
        cash_status = 'available' if person['training_roster'] else 'partial'
        if not person['training_roster'] and not cash_facts:
            cash_value = None
            cash_status = 'not_connected'
        destinations = defaultdict(Decimal)
        own_training = Decimal(0)
        cross_training = Decimal(0)
        for fact in training_orders:
            group = _text(fact.get('business_group')) or '未归类'
            destinations[group] += fact['value']
            if group == person['home_group']:
                own_training += fact['value']
            else:
                cross_training += fact['value']
        heads_by_student = {}
        for fact in cash_facts:
            if fact['value'] <= 0:
                continue
            student_id = _text(fact.get('student_id'))
            if not student_id:
                continue
            weight = Decimal(1) / Decimal(max(1, len(fact['owners'])))
            heads_by_student[student_id] = max(heads_by_student.get(student_id, Decimal(0)), weight)
        heads = _number(sum(heads_by_student.values(), Decimal(0))) if cash_value is not None else None
        capacity.append({
            'name': person['name'],
            'home_group': person['home_group'],
            'home_team': sorted(person['team_ids'])[0],
            'business_line': person['business_line'],
            'orders': _sum_numbers(fact['value'] for fact in order_facts),
            'cash': cash_value,
            'heads': heads,
            'own_training_orders': _number(own_training),
            'cross_training_orders': _number(cross_training),
            'abroad_orders': _sum_numbers(fact['value'] for fact in abroad_orders),
            'training_destinations': [
                {'name': name, 'orders': _number(value)}
                for name, value in sorted(destinations.items())
            ],
            'cash_status': cash_status,
            'cash_capacity': cash_capacity if person['training_roster'] else None,
            'cash_progress_completion': (
                float(_decimal(cash_value) / _decimal(target_to_date))
                if person['training_roster'] and cash_value is not None and target_to_date else None
            ),
        })
    return capacity


def _activities(facts):
    grouped = defaultdict(lambda: {
        'training_orders': Decimal(0), 'abroad_orders': Decimal(0),
        'cash': Decimal(0), 'training_students': set(), 'has_abroad': False, 'has_training': False,
    })
    for fact in facts:
        name = _text(fact.get('campaign_name')) or '未填写活动'
        row = grouped[name]
        row['has_training'] |= fact['business_line'] == 'training'
        if fact['metric'] == 'orders':
            row['training_orders' if fact['business_line'] == 'training' else 'abroad_orders'] += fact['value']
            if fact['business_line'] == 'abroad':
                row['has_abroad'] = True
        elif fact['metric'] == 'cash' and fact['business_line'] == 'training':
            row['cash'] += fact['value']
            if fact['value'] > 0 and _text(fact.get('student_id')):
                row['training_students'].add(_text(fact.get('student_id')))
        elif fact['metric'] == 'cash' and fact['business_line'] == 'abroad':
            # Abroad cash is intentionally not connected to this product.
            row['has_abroad'] = True
    rows = []
    for name, row in sorted(grouped.items()):
        training_orders = _number(row['training_orders'])
        abroad_orders = _number(row['abroad_orders'])
        rows.append({
            'name': name,
            'training_orders': training_orders,
            'abroad_orders': abroad_orders,
            'orders': _number(row['training_orders'] + row['abroad_orders']),
            'cash': _number(row['cash'], money=True) if row['has_training'] else None,
            'heads': len(row['training_students']) if row['has_training'] else None,
            'cash_status': ('partial' if row['has_training'] else 'not_connected') if row['has_abroad'] else 'available',
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
        mode = fact.get('acquisition_mode')
        if mode == 'offline':
            row['offline'] += fact['value']
        elif mode == 'online':
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
              abroad_targets, online_abroad_targets, through, capacity_config=None):
    """Aggregate normalized facts without reading source data or changing ownership.

    Team actuals use calendar periods. Person actuals keep the selected period's
    26th-to-25th performance window, with a parallel natural-calendar view.
    """
    through = _date(through)
    facts = _valid_facts(facts, through)
    roster = _roster(people_config, abroad_people_config)
    abroad_people_names = {person['name'] for person in roster if person['abroad_roster']}
    configs = (training_targets, abroad_targets, online_abroad_targets)
    period_rows = []
    for source_period in online_periods(through):
        period = dict(source_period)
        team_rows = []
        person_start, person_through, people_rows, person_progress = _people_for_period(facts, roster, period, through)
        calendar_start, calendar_through, calendar_people_rows, calendar_progress = _people_for_period(
            facts, roster, period, through, mode='calendar',
        )
        people_map = {person['name']: person for person in roster}
        for team_id, name in TEAM_DEFS:
            lines = {}
            for line in ('training', 'abroad'):
                metrics = {}
                for kind in ('orders', 'cash', 'heads'):
                    note = ''
                    if line == 'abroad' and kind == 'orders' and team_id in ABROAD_NOT_CONFIGURED_TEAMS:
                        note = 'not_configured'
                    predicate = _team_fact_filter(team_id, line, abroad_people_names)
                    target = _team_target(configs, period, team_id, line, kind, facts)
                    metrics[kind] = _metric_for_period(
                        facts, line, kind, predicate, period, target, note=note,
                    )
                lines[line] = metrics
            selected_people = [row for row in people_rows if team_id == 'total' or
                (team_id in GROUP_BY_TEAM and 'offline_market' in people_map[row['name']]['team_ids']
                 and row['home_group'] == GROUP_BY_TEAM[team_id]) or
                (team_id == 'virtual' and 'online_private' in people_map[row['name']]['team_ids'])]
            selected_calendar_people = [row for row in calendar_people_rows if team_id == 'total' or
                (team_id in GROUP_BY_TEAM and 'offline_market' in people_map[row['name']]['team_ids']
                 and row['home_group'] == GROUP_BY_TEAM[team_id]) or
                (team_id == 'virtual' and 'online_private' in people_map[row['name']]['team_ids'])]
            country_scope = _team_fact_filter(team_id, 'abroad', abroad_people_names)
            countries = [] if not period.get('through_date') else _countries(
                [fact for fact in facts if country_scope(fact)],
                _date(period['start_date']), _date(period['through_date']))
            team_rows.append({'id': team_id, 'name': name, 'lines': lines,
                              'people': selected_people,
                              'person_start': person_start, 'person_through': person_through, 'person_progress': person_progress,
                              'person_calendar': {
                                  'person_start': calendar_start,
                                  'person_through': calendar_through,
                                  'person_progress': calendar_progress,
                                  'people': selected_calendar_people,
                              },
                              'countries': countries})
        if period['status'] == 'future' or not period.get('through_date'):
            country_rows = []
        else:
            country_rows = _countries(facts, _date(period['start_date']), _date(period['through_date']))
        # Person detail is a period-level table and appears once per period.
        period_rows.append({
            'id': period['id'], 'label': period['label'],
            'start_date': period['start_date'], 'through_date': period['through_date'],
            'status': period['status'], 'teams': team_rows,
            'person_start': team_rows[0]['person_start'],
            'person_through': team_rows[0]['person_through'],
            'countries': country_rows,
        })
    return {
        'periods': period_rows,
        'capacity': _capacity(facts, roster, through, (capacity_config or {}).get('annual_cash_by_person', CASH_CAPACITY)),
        'activities': _activities(facts),
    }
