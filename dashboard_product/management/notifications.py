"""Build private notification payloads from precomputed management results."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import calendar
import re

from . import aggregate as _aggregate


CHANNELS = (
    ('prep', 'training', 'offline_youth', '线下青少语培'),
    ('high', 'training', 'offline_high_school', '线下高中语培'),
    ('university', 'training', 'offline_university', '线下大学语培'),
    ('university', 'abroad', 'offline_university', '线下大学留学'),
    ('virtual', 'mixed', 'online_private', '线上虚拟人'),
    ('online', 'training', 'online_platform', '线上平台语培'),
    ('online', 'abroad', 'online_platform', '线上平台留学'),
)
MONTH_RE = re.compile(r'^\d{4}-\d{2}$')


def _date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _month_id(value):
    return value.strftime('%Y-%m')


def _performance_month(through):
    """Return the 26th-to-25th performance month containing ``through``."""
    year, month = through.year, through.month
    if through.day >= 26:
        month += 1
        if month == 13:
            year += 1
            month = 1
    return f'{year:04d}-{month:02d}'


def _metric(actual, target):
    return actual / target if actual is not None and target not in (None, 0) else None


def _included(fact):
    # Older fixtures have no explicit flag; current production facts do.
    return fact.get('counts_toward_completion') is not False


def _value(fact):
    return Decimal(str(fact.get('value') or 0))


def _number(value):
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _periods(public):
    by_month = {}
    for period in public.get('periods') or []:
        period_id = str(period.get('id') or '')
        if MONTH_RE.fullmatch(period_id):
            by_month[period_id] = period
    return by_month


def _team(period, team_id):
    return next((row for row in period.get('teams', []) if row.get('id') == team_id), None)


def _personal_period(through, periods, natural_period):
    performance_month = _performance_month(through)
    selected = periods.get(performance_month)
    if selected is None:
        raise ValueError(f'missing fixed performance period: {performance_month}')
    return selected, performance_month


def _team_filter(team_id, line):
    return _aggregate._team_fact_filter(team_id, line)


def _facts_in_window(facts, start, end, team_id, line, kind):
    if not start or not end:
        return []
    start_date, end_date = _date(start), _date(end)
    in_scope = _team_filter(team_id, line)
    rows = [fact for fact in facts
            if fact.get('business_line') == line
            and fact.get('metric') == kind
            and fact.get('event_date')
            and start_date <= _date(fact['event_date']) <= end_date
            and in_scope(fact)]
    return sorted(rows, key=lambda fact: (
        str(fact.get('event_date') or ''), str(fact.get('work_order_id') or ''),
        str(fact.get('fact_id') or ''),
    ))


def _virtual_team_orders(facts, start, end, roster_names):
    if not start or not end:
        return []
    start_date, end_date = _date(start), _date(end)
    training = _facts_in_window(facts, start, end, 'virtual', 'training', 'orders')
    abroad = [fact for fact in facts
              if fact.get('business_line') == 'abroad'
              and fact.get('metric') == 'orders'
              and fact.get('event_date')
              and start_date <= _date(fact['event_date']) <= end_date
              and roster_names.intersection(fact.get('owners') or [])]
    unique = {}
    for fact in [*training, *abroad]:
        unique.setdefault(fact.get('fact_id') or id(fact), fact)
    return sorted(unique.values(), key=lambda fact: (
        str(fact.get('event_date') or ''), str(fact.get('work_order_id') or ''),
        str(fact.get('fact_id') or ''),
    ))


def _roster_index(people_config, abroad_people_config):
    return {person['name']: person
            for person in _aggregate._roster(people_config, abroad_people_config)}


def _heads_targets(people_config, month):
    result = {}
    for team in people_config.get('teams', []):
        for group in team.get('groups', []):
            for person in group.get('members', []):
                name = str(person.get('display_name') or '').strip()
                target = ((person.get('monthly_targets') or {}).get(month) or {}).get('heads')
                if name and target is not None:
                    result[name] = target
    return result


def _owned_person_facts(facts, name, roster_row, line, kind, start, end):
    if not start or not end:
        return []
    start_date, end_date = _date(start), _date(end)
    accepted_lines = ('training', 'abroad') if line == 'mixed' else (line,)
    return [fact for fact in facts
            if fact.get('business_line') in accepted_lines
            and fact.get('metric') == kind
            and fact.get('event_date')
            and start_date <= _date(fact['event_date']) <= end_date
            and name in (fact.get('owners') or [])
            and _aggregate._personal_qualification(roster_row, fact, fact.get('business_line'))]


def _remaining_workdays(after, end):
    if not after or not end:
        return None
    cursor, end_date = _date(after) + timedelta(days=1), _date(end)
    count = 0
    while cursor <= end_date:
        count += cursor.weekday() < 5
        cursor += timedelta(days=1)
    return count


def _number_or_none(value):
    if value is None:
        return None
    value = Decimal(str(value))
    return _number(value)


def _personal_facts(facts, person_rows, roster_index, line, kind, start, end):
    matched = {}
    for person in person_rows:
        name = person['name']
        for fact in _owned_person_facts(facts, name, roster_index[name], line, kind, start, end):
            matched[fact.get('fact_id') or id(fact)] = fact
    return sorted(matched.values(), key=lambda fact: (
        str(fact.get('event_date') or ''), str(fact.get('work_order_id') or ''),
        str(fact.get('fact_id') or ''),
    ))


def _metric_actual(person, line, kind):
    if kind == 'orders':
        return person.get(f'{line}_actual')
    metric = person.get(f'{kind}_actual') or {}
    return metric.get('actual') if isinstance(metric, dict) else None


def _metric_target(person, line, kind):
    if kind == 'orders':
        return person.get(f'{line}_target')
    metric = person.get(f'{kind}_actual') or {}
    return metric.get('target') if isinstance(metric, dict) else None


def _person_rows(person_team, line, message_team_id, people_config,
                 roster_index, month, facts, data_through, person_start, person_through,
                 person_progress):
    rows = []
    source_people = person_team.get('people') or []
    daily_date = data_through.isoformat()
    personal_start = person_start
    personal_end = person_through
    try:
        person_year, person_month_number = map(int, month.split('-'))
        performance_end = date(person_year, person_month_number, 25).isoformat()
    except (TypeError, ValueError):
        performance_end = None
    heads_targets = _heads_targets(people_config, month)
    mixed = message_team_id == 'virtual'
    for source in source_people:
        person = dict(source)
        name = str(person.get('name') or '').strip()
        row = roster_index.get(name)
        if not name or row is None:
            continue
        primary_line = 'training' if row['training_roster'] else 'abroad'
        if not mixed and primary_line != line:
            continue

        current_actual = (person.get('combined_actual') if mixed
                          else _metric_actual(person, line, 'orders'))
        current_target = (person.get('combined_target') if mixed
                          else _metric_target(person, line, 'orders'))
        person.update({
            'orders_target': current_target,
            'orders_actual': current_actual,
            'orders_completion': _metric(current_actual, current_target),
        })

        if not mixed and person.get('home_group') == '大学':
            other_line = 'abroad' if line == 'training' else 'training'
            secondary_actual = _metric_actual(person, other_line, 'orders')
            secondary_target = _metric_target(person, other_line, 'orders')
            person.update({
                'secondary_business_line': other_line,
                'secondary_orders_target': secondary_target,
                'secondary_orders_actual': secondary_actual,
                'secondary_orders_completion': _metric(secondary_actual, secondary_target),
            })

        if line in ('training', 'mixed'):
            heads_actual = _metric_actual(person, 'training' if mixed else line, 'heads')
            heads_target = heads_targets.get(name)
            person['heads_target'] = heads_target
            person['heads_completion'] = _metric(heads_actual, heads_target)
        else:
            person['heads_target'] = None
            person['heads_completion'] = None

        primary_actual = current_actual
        primary_target = current_target
        expected_orders = (
            Decimal(str(primary_target)) * Decimal(str(person_progress))
            if primary_target is not None and person_progress is not None else None
        )
        orders_gap = (
            Decimal(str(primary_actual)) - expected_orders
            if primary_actual is not None and expected_orders is not None else None
        )
        remaining_orders = (
            max(Decimal(0), Decimal(str(primary_target)) - Decimal(str(primary_actual)))
            if primary_target is not None and primary_actual is not None else None
        )
        remaining_workdays = _remaining_workdays(data_through, performance_end)
        required_daily_orders = (
            remaining_orders / remaining_workdays
            if remaining_orders is not None and remaining_workdays else None
        )
        person['behind'] = (
            orders_gap < 0 if orders_gap is not None and primary_target not in (None, 0) else None
        )

        day_rows = [fact for fact in _owned_person_facts(
            facts, name, row, line, 'orders', personal_start, personal_end,
        ) if str(fact.get('event_date') or '')[:10] == daily_date and _included(fact)]
        person.update({
            'expected_orders': _number_or_none(expected_orders),
            'orders_gap': _number_or_none(orders_gap),
            'remaining_orders': _number_or_none(remaining_orders),
            'remaining_workdays': remaining_workdays,
            'today_orders': _number(sum((_value(fact) for fact in day_rows), Decimal(0))),
            'daily_orders': _number_or_none(required_daily_orders),
        })
        rows.append(person)
    return rows


def _channels(order_facts, data_through):
    counts = defaultdict(Decimal)
    today_counts = defaultdict(Decimal)
    for fact in order_facts:
        second = str(fact.get('second_channel') or '').strip() or '二级渠道待确认'
        key = second
        amount = _value(fact)
        counts[key] += amount
        if str(fact.get('event_date') or '')[:10] == data_through.isoformat():
            today_counts[key] += amount
    denominator = sum(counts.values(), Decimal(0))
    result = []
    for second in sorted(counts, key=lambda key: (-counts[key], key)):
        amount = counts[second]
        result.append({
            'name': second,
            'month': _number(amount),
            'today': _number(today_counts[second]),
            'share': float(amount / denominator) if denominator else None,
        })
    return result


def _team_orders_metric(metric, order_facts, data_through, natural_period):
    result = dict(metric or {})
    daily_actual = _number(sum(
        (_value(fact) for fact in order_facts
         if str(fact.get('event_date') or '')[:10] == data_through.isoformat()), Decimal(0)))
    actual, target = result.get('actual'), result.get('target')
    period_start = _date(natural_period['start_date'])
    elapsed = max(1, (data_through - period_start).days + 1)
    month_days = calendar.monthrange(data_through.year, data_through.month)[1]
    remaining = max(0, month_days - data_through.day)
    numeric_actual = Decimal(str(actual)) if actual is not None else None
    numeric_target = Decimal(str(target)) if target is not None else None
    progress = Decimal(str(natural_period.get('time_progress') or 0))
    result.update({
        'daily_actual': daily_actual,
        'daily_average': _number(numeric_actual / elapsed) if numeric_actual is not None else None,
        'daily_required': (
            _number(max(Decimal(0), numeric_target - numeric_actual) / remaining)
            if numeric_target is not None and numeric_actual is not None and remaining else None
        ),
        'behind': (
            numeric_actual < numeric_target * progress
            if numeric_actual is not None and numeric_target not in (None, 0) else None
        ),
    })
    return result


def _team_metrics(natural_team, line, order_facts, data_through, natural_period):
    source = (natural_team.get('lines') or {}).get(line) or {}
    return {
        'orders': _team_orders_metric(source.get('orders'), order_facts, data_through, natural_period),
        'cash': dict(source.get('cash') or {}),
        'heads': dict(source.get('heads') or {}),
    }


def build_notifications(public, facts, people_config, abroad_people_config):
    """Build seven private notification cards from the already-computed public rollups.

    No warehouse access, filesystem writes, or external notifications happen here.
    Team metrics use the natural month. Individual metrics come from the
    precomputed 26th-to-25th window containing ``data_through``.
    """
    metadata = public.get('metadata') or {}
    through_value = metadata.get('data_through')
    if not through_value:
        raise ValueError('public metadata is missing data_through')
    data_through = _date(through_value)
    month = _month_id(data_through)
    periods = _periods(public)
    natural_period = periods.get(month)
    if natural_period is None:
        raise ValueError(f'missing natural-month period: {month}')
    roster_index = _roster_index(people_config, abroad_people_config)
    virtual_roster_names = {
        name for name, row in roster_index.items()
        if 'online_private' in row['team_ids']
    }

    messages = []
    for team_id, line, channel_id, title in CHANNELS:
        natural_team = _team(natural_period, team_id)
        # The online platform has no individual KPI roster or fixed personal
        # performance window. Keep its window natural-month scoped.
        if team_id == 'online':
            person_period, person_month = natural_period, month
        else:
            person_period, person_month = _personal_period(data_through, periods, natural_period)
        person_team = _team(person_period, team_id)
        if natural_team is None or person_team is None:
            raise ValueError(f'missing team rollup for {team_id}')

        natural_through = natural_period.get('through_date')
        natural_start = natural_period.get('start_date')
        team_end = natural_through or natural_start
        if team_id == 'online':
            person_start = person_through = person_progress = None
        else:
            person_start = person_team.get('person_start')
            person_through = person_team.get('person_through')
            person_progress = person_team.get('person_progress')

        team_orders = (_virtual_team_orders(facts, natural_start, team_end, virtual_roster_names)
                       if team_id == 'virtual' else
                       _facts_in_window(facts, natural_start, team_end, team_id, line, 'orders'))
        team_cash = (_facts_in_window(facts, natural_start, team_end, team_id, 'training', 'cash')
                     if line in ('training', 'mixed') else [])
        people = ([] if team_id == 'online' else _person_rows(
            person_team, line, team_id, people_config, roster_index, person_month,
            facts, data_through, person_start, person_through, person_progress,
        ))
        personal_start = person_start
        personal_end = person_through
        personal_orders = _personal_facts(
            facts, people, roster_index, line, 'orders', personal_start, personal_end,
        )
        secondary_orders = (_personal_facts(
            facts, people, roster_index, 'abroad' if line == 'training' else 'training',
            'orders', personal_start, personal_end,
        ) if team_id == 'university' else [])
        personal_cash = (_personal_facts(
            facts, people, roster_index, 'training' if line == 'mixed' else line,
            'cash', personal_start, personal_end,
        ) if line in ('training', 'mixed') else [])

        metric_team, metric_line = natural_team, line
        if line == 'mixed':
            metric_team = dict(natural_team)
            metric_lines = dict(natural_team.get('lines') or {})
            training_metrics = dict(metric_lines.get('training') or {})
            if natural_team.get('combined_orders') is not None:
                training_metrics['orders'] = natural_team['combined_orders']
            metric_lines['training'] = training_metrics
            metric_team['lines'] = metric_lines
            metric_line = 'training'
        team_metrics = _team_metrics(metric_team, metric_line, team_orders, data_through, natural_period)
        messages.append({
            'id': f'{team_id}.{line}',
            'channel_id': channel_id,
            'business_line': line,
            'title': title,
            'month': month,
            'window': {
                'data_through': data_through.isoformat(),
                'team_start': natural_start,
                'team_end': natural_period.get('end_date'),
                'team_through': natural_through,
                'team_progress': natural_period.get('time_progress'),
                'person_month': person_month,
                'person_start': person_start,
                'person_end': person_month + '-25' if person_start else None,
                'person_through': person_through,
                'person_progress': person_progress,
            },
            'team_metrics': team_metrics,
            'people': people,
            'channels': _channels(team_orders, data_through),
            'ledgers': {
                'personal_orders': personal_orders,
                'personal_secondary_orders': secondary_orders,
                'team_orders': team_orders,
                'personal_cash': personal_cash,
                'team_cash': team_cash,
            },
        })
    return {
        'schema_version': 'management_notifications.v1',
        'data_through': data_through.isoformat(),
        'messages': messages,
    }
