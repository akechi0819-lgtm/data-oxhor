"""Team-level historical and drill-down views derived from normalized facts."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from dashboard_product.management import aggregate as _aggregate
from dashboard_product.online_team.build import metric as _metric
from dashboard_product.online_team.build import periods as _source_periods


BUSINESS_GROUPS = ('留学预备', '高中', '大学')
COMPARISON_GROUPS = ('青少', '初中', '高中', '大学')
UNASSIGNED_GROUP = '业务组暂无法拆分'
UNKNOWN_CHANNEL = '二级渠道待确认'
UNKNOWN_FIRST_CHANNEL = '一级渠道待确认'
UNKNOWN_SCHOOL = '暂无归属'


# Display-only aliases explicitly confirmed by the user on 2026-09-30.
GRADE_ALIASES = {'七年级':'初一','八年级':'初二','九年级':'初三',
                 '小班':'幼儿园小班','中班':'幼儿园中班','大班':'幼儿园大班'}

def grade_label(value):
    name = str(value or '').strip()
    if name in ('', '未知', '暂无归属'): return '年级待确认'
    return GRADE_ALIASES.get(name, name)


def _date(value):
    return _aggregate._date(value)


def _shift_year(value):
    return _aggregate._shift_year(value)


def _period_bounds(period):
    if period.get('status') == 'future' or not period.get('through_date'):
        return None
    start = _date(period['start_date'])
    through = _date(period['through_date'])
    return start, through, _shift_year(start), _shift_year(through)


def _period_progress(period):
    return float(period.get('time_progress') or 0)


def _metric_with_status(actual, prior, target, period, unit, *, status=None, note=''):
    status = status or period.get('status', 'available')
    return _metric(
        actual, prior, target, _period_progress(period), _aggregate.METRIC_UNITS[unit],
        status=status, note=note,
    )


def _measure(facts, line, kind, predicate, period, team_id, target=None):
    """Use the established period, target, and status rules for one metric."""
    if period.get('status') == 'future' or not period.get('through_date'):
        return _metric_with_status(None, None, target, period, kind, status='future')

    if line == 'abroad' and kind in ('cash', 'heads'):
        return _metric_with_status(
            None, None, None, period, kind, status='not_connected',
            note=_aggregate.ABROAD_METRICS_NOTE,
        )
    if line == 'abroad' and kind == 'orders' and team_id in _aggregate.ABROAD_NOT_CONFIGURED_TEAMS:
        return _metric_with_status(
            None, None, None, period, kind, status='not_configured',
            note='本部门暂不统计留学完成；贡献见人员产能。',
        )

    bounds = _period_bounds(period)
    start, through, prior_start, prior_through = bounds
    if kind == 'heads':
        actual = _aggregate._unique_heads(facts, line, start, through, predicate)
        prior = _aggregate._unique_heads(facts, line, prior_start, prior_through, predicate)
    else:
        actual = _aggregate._sum_fact_values(facts, line, kind, start, through, predicate)
        prior = _aggregate._sum_fact_values(facts, line, kind, prior_start, prior_through, predicate)
    return _metric_with_status(actual, prior, target, period, kind)


def _source_group(fact):
    source = str(fact.get('comparison_group') or '').strip()
    if source in COMPARISON_GROUPS:
        return source
    return None


def _business_group(fact):
    group = str(fact.get('business_group') or '').strip()
    if group in BUSINESS_GROUPS:
        return group
    return UNASSIGNED_GROUP


def _channel_group(fact, line):
    if line == 'training':
        return _source_group(fact) or UNASSIGNED_GROUP
    group = str(fact.get('business_group') or '').strip()
    return group if group in BUSINESS_GROUPS else UNASSIGNED_GROUP


def _fact_matches(fact, predicate, *, field=None, value=None):
    if predicate is not None and not predicate(fact):
        return False
    return field is None or value is None or fact.get(field) == value


def _training_targets(training_targets, period, team_id, group, kind):
    if group not in BUSINESS_GROUPS:
        return None
    helper = (_aggregate._department_training_cash_target if kind == 'cash'
              else _aggregate._department_training_target)
    configs = {
        'total': ('offline_market', 'online_private', 'online_platform'),
        'prep': ('offline_market',) if group == '留学预备' else (),
        'high': ('offline_market',) if group == '高中' else (),
        'university': ('offline_market',) if group == '大学' else (),
        'virtual': ('online_private',),
        'online': ('online_platform',),
    }.get(team_id, ())
    values = [helper(training_targets or {}, period, config_team, group)
              for config_team in configs]
    if not values or any(value is None for value in values):
        return None
    return _aggregate._sum_numbers(values, money=kind == 'cash')


def _has_facts(facts, line, start, through, predicate):
    return any(fact['business_line'] == line and start <= fact['event_date'] <= through
               and predicate(fact) for fact in facts)


def _business_groups(facts, team_id, period, training_targets):
    scope = _aggregate._team_fact_filter(team_id, 'training')
    bounds = _period_bounds(period)
    names = [_aggregate.GROUP_BY_TEAM[team_id]] if team_id in _aggregate.GROUP_BY_TEAM else list(BUSINESS_GROUPS)
    if bounds:
        start, through, prior_start, prior_through = bounds
        unresolved = lambda fact: _business_group(fact) == UNASSIGNED_GROUP
        if (_has_facts(facts, 'training', start, through,
                       lambda fact: scope(fact) and unresolved(fact))
                or _has_facts(facts, 'training', prior_start, prior_through,
                              lambda fact: scope(fact) and unresolved(fact))):
            names.append(UNASSIGNED_GROUP)

    rows = []
    for name in names:
        group_filter = lambda fact, name=name: scope(fact) and _business_group(fact) == name
        metrics = {}
        for kind in ('orders', 'cash', 'heads'):
            target = (_training_targets(training_targets, period, team_id, name, kind)
                      if kind in ('orders', 'cash') else None)
            metrics[kind] = _measure(
                facts, 'training', kind, group_filter, period, team_id, target,
            )
        rows.append({'name': name, **metrics})
    return rows


def _yoy_groups(facts, team_id, period):
    scope = _aggregate._team_fact_filter(team_id, 'training')
    rows = []
    names = {'prep': ('青少','初中'), 'high': ('高中',), 'university': ('大学',)}.get(team_id, COMPARISON_GROUPS)
    for name in names:
        group_filter = lambda fact, name=name: scope(fact) and _source_group(fact) == name
        rows.append({
            'name': name,
            'orders': _measure(facts, 'training', 'orders', group_filter, period, team_id),
            'cash': _measure(facts, 'training', 'cash', group_filter, period, team_id),
            'heads': _measure(facts, 'training', 'heads', group_filter, period, team_id),
        })
    return rows


def _in_range(fact, bounds, which):
    if bounds is None:
        return False
    start, through = (bounds[0], bounds[1]) if which == 'current' else (bounds[2], bounds[3])
    return start <= fact['event_date'] <= through


def _channel_identity(fact):
    return (
        str(fact.get('first_channel') or UNKNOWN_FIRST_CHANNEL).strip() or UNKNOWN_FIRST_CHANNEL,
        str(fact.get('second_channel') or UNKNOWN_CHANNEL).strip() or UNKNOWN_CHANNEL,
    )


def _channels(facts, team, period):
    team_id = team['id']
    bounds = _period_bounds(period)
    output = []
    if bounds is None:
        return output
    for line in ('training', 'abroad'):
        scope = _aggregate._team_fact_filter(team_id, line)
        in_scope = lambda fact: scope(fact) and fact.get('business_line') == line
        current = [fact for fact in facts if _in_range(fact, bounds, 'current') and in_scope(fact)]
        prior = [fact for fact in facts if _in_range(fact, bounds, 'prior') and in_scope(fact)]
        identities = sorted({_channel_identity(fact) for fact in current + prior})
        all_orders = _measure(current + prior, line, 'orders', in_scope, period, team_id)
        all_cash = _measure(current + prior, line, 'cash', in_scope, period, team_id)
        buckets = defaultdict(list)
        for item in current + prior:
            buckets[_channel_identity(item)].append(item)
        for first_channel, second_channel in identities:
            channel_facts = buckets[(first_channel, second_channel)]
            channel_filter = lambda fact, first=first_channel, second=second_channel: (
                in_scope(fact) and _channel_identity(fact) == (first, second)
            )
            orders = _measure(channel_facts, line, 'orders', channel_filter, period, team_id)
            cash = _measure(channel_facts, line, 'cash', channel_filter, period, team_id)
            heads = _measure(channel_facts, line, 'heads', channel_filter, period, team_id)
            group_names = sorted({
                _channel_group(fact, line)
                for fact in channel_facts
                if _channel_identity(fact) == (first_channel, second_channel)
            })
            groups = []
            for group_name in group_names:
                group_filter = lambda fact, group=group_name: (
                    channel_filter(fact) and _channel_group(fact, line) == group
                )
                groups.append({
                    'name': group_name,
                    'orders': _measure(channel_facts, line, 'orders', group_filter, period, team_id),
                    'cash': _measure(channel_facts, line, 'cash', group_filter, period, team_id),
                })
            for group in groups:
                group['share'] = group['orders']['actual'] / all_orders['actual'] if all_orders.get('actual') and group['orders']['actual'] is not None else None
                group['cash_share'] = group['cash']['actual'] / all_cash['actual'] if all_cash.get('actual') and group['cash']['actual'] is not None else None
                group['channel_cash_share'] = group['cash']['actual'] / cash['actual'] if cash.get('actual') and group['cash']['actual'] is not None else None
            share = None
            cash_share = None
            if orders.get('actual') is not None and all_orders.get('actual'):
                share = orders['actual'] / all_orders['actual']
            if (line == 'training' and cash.get('actual') is not None
                    and all_cash.get('actual')):
                cash_share = cash['actual'] / all_cash['actual']
            output.append({
                'business_line': line,
                'name': second_channel,
                'first_channel': first_channel,
                'orders': orders,
                'cash': cash,
                'heads': heads,
                'share': share,
                'cash_share': cash_share,
                'groups': groups,
            })
    output.sort(key=lambda row: (
        row['business_line'],
        -(row['cash'].get('actual') or 0),
        -(row['orders'].get('actual') or 0),
        row['name'], row['first_channel'],
    ))
    return output


def _school_grade_rows(facts, team, period, line="training"):
    if period.get('status') == 'future' or not period.get('through_date'):
        return []
    bounds = _period_bounds(period)
    scope = _aggregate._team_fact_filter(team['id'], line)
    grouped = defaultdict(lambda: {'orders': {'current': [], 'prior': []},
                                  'cash': {'current': [], 'prior': []}})
    for fact in facts:
        if fact.get('business_line') != line or not scope(fact):
            continue
        which = next((label for label in ('current', 'prior')
                      if _in_range(fact, bounds, label)), None)
        if which is None:
            continue
        school = str(fact.get('school_name') or '').strip() or UNKNOWN_SCHOOL
        grade = grade_label(fact.get('grade_name'))
        key = (school, grade)
        if fact['metric'] in ('orders', 'cash'):
            grouped[key][fact['metric']][which].append(fact['value'])

    by_school = defaultdict(lambda: {'grades': []})
    for (school, grade), values in sorted(grouped.items()):
        grade_row = {'name': grade}
        for kind in ('orders', 'cash'):
            current = _aggregate._sum_numbers(values[kind]['current'], money=kind == 'cash')
            prior = _aggregate._sum_numbers(values[kind]['prior'], money=kind == 'cash')
            grade_row[kind] = (_metric_with_status(None, None, None, period, kind, status='not_connected')
                               if line == 'abroad' and kind == 'cash' else
                               _metric_with_status(current, prior, None, period, kind))
        by_school[school]['grades'].append(grade_row)

    result = []
    for school, row in sorted(by_school.items()):
        school_row = {'name': school, 'grades': row['grades']}
        for kind in ('orders', 'cash'):
            current_values = [grade[kind]['actual'] or 0 for grade in row['grades']]
            prior_values = [grade[kind]['prior'] or 0 for grade in row['grades']]
            current = _aggregate._sum_numbers(current_values, money=kind == 'cash')
            prior = _aggregate._sum_numbers(prior_values, money=kind == 'cash')
            school_row[kind] = (_metric_with_status(None, None, None, period, kind, status='not_connected')
                                if line == 'abroad' and kind == 'cash' else
                                _metric_with_status(current, prior, None, period, kind))
        school_row["business_line"] = line
        result.append(school_row)
    totals={kind:sum(r[kind]['actual'] or 0 for r in result) for kind in ('orders','cash')}
    for r in result:
        for item in [r,*r['grades']]:
            item['share']=item['orders']['actual']/totals['orders'] if totals['orders'] else None
            item['cash_share']=item['cash']['actual']/totals['cash'] if totals['cash'] and item['cash']['actual'] is not None else None
    return sorted(result,key=lambda r: (-(r['orders']['actual'] or 0), r['name']))


def _grade_rows(facts, team, period, line):
    bounds = _period_bounds(period)
    if not bounds: return []
    scope = _aggregate._team_fact_filter(team['id'], line)
    buckets = defaultdict(list)
    for fact in facts:
        if fact['business_line']==line and scope(fact) and (_in_range(fact,bounds,'current') or _in_range(fact,bounds,'prior')):
            buckets[grade_label(fact.get('grade_name'))].append(fact)
    result=[]
    for name, rows in buckets.items():
        result.append({'name':name, **{kind:_measure(rows,line,kind,lambda f:True,period,team['id']) for kind in ('orders','cash')}})
    for kind, key in [('orders','share'),('cash','cash_share')]:
        denominator=sum(r[kind]['actual'] or 0 for r in result)
        for row in result: row[key]=row[kind]['actual']/denominator if denominator and row[kind]['actual'] is not None else None
    return sorted(result,key=lambda row:row['name'])


def _country_groups(team):
    grouped = defaultdict(list)
    for country in team.get('countries', []):
        grouped[str(country.get('line') or '条线待确认')].append(country)
    result = []
    for line, countries in sorted(grouped.items()):
        countries = sorted(countries, key=lambda row: str(row.get('country') or ''))
        result.append({
            'line': line,
            'online': _aggregate._sum_numbers(row.get('online', 0) for row in countries),
            'offline': _aggregate._sum_numbers(row.get('offline', 0) for row in countries),
            'unassigned': _aggregate._sum_numbers(row.get('unassigned', 0) for row in countries),
            'total': _aggregate._sum_numbers(row.get('total', 0) for row in countries),
            'countries': countries,
        })
    return result


def _add_period_windows(periods):
    through_dates = [period.get('through_date') for period in periods if period.get('through_date')]
    if not through_dates:
        for period in periods:
            period.setdefault('end_date', None)
            period.setdefault('time_progress', 0.0)
        return
    data_through = max((_date(value) for value in through_dates))
    source = {period['id']: period for period in _source_periods(data_through)}
    for period in periods:
        window = source.get(period.get('id'))
        if window is None:
            continue
        period['kind'] = window['kind']
        period['end_date'] = window['end_date']
        period['time_progress'] = window['time_progress']
        period['prior_start_date'] = window['prior_start_date']
        period['prior_through_date'] = window['prior_through_date']


def enrich_periods(periods, facts, training_targets, abroad_targets, online_targets) -> None:
    """Attach old dashboard comparisons and details to each aggregate team.

    Only normalized facts and the already-loaded target configurations are
    used; this function performs no query and does not alter attribution.
    """
    _add_period_windows(periods)
    through_dates = [period.get('through_date') for period in periods if period.get('through_date')]
    valid_facts = (_aggregate._valid_facts(
        facts, max(_date(value) for value in through_dates), include_non_completion=True,
    )
                   if through_dates else [])
    # The first argument to these helpers has a fixed contract today. Keep the
    # loaded configurations in this signature so callers can enrich the full
    # set of detail rows without loading any config from disk here.
    _ = (abroad_targets, online_targets)

    for period in periods:
        for team in period.get('teams', []):
            team_id = team.get('id')
            team['business_groups'] = _business_groups(
                valid_facts, team_id, period, training_targets,
            )
            team['yoy_groups'] = _yoy_groups(valid_facts, team_id, period)
            team['channels'] = _channels(valid_facts, team, period)
            team['schools_by_line'] = {line:_school_grade_rows(valid_facts, team, period, line) for line in ('training','abroad')}
            team['grades_by_line'] = {line:_grade_rows(valid_facts,team,period,line) for line in ('training','abroad')}
            team['country_groups'] = _country_groups(team)
