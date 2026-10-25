"""Restore the management total team's passive market work-order baseline."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from dashboard_product.management.aggregate import _date, _shift_year
from dashboard_product.online_team.build import metric


UNKNOWN_GROUP = '业务组暂无法拆分'
SOURCE_GROUPS = ('青少', '初中', '高中', '大学')


def _number(value):
    amount = Decimal(str(value))
    if amount == amount.to_integral_value():
        return int(amount)
    return float(amount)


def _source_group(value):
    name = str(value or '').strip()
    return name if name in SOURCE_GROUPS else UNKNOWN_GROUP


def _business_group(source_group):
    if source_group in ('青少', '初中'):
        return '留学预备'
    if source_group in ('高中', '大学'):
        return source_group
    return UNKNOWN_GROUP


def _baseline_sums(rows, start, through):
    totals = defaultdict(Decimal)
    if start is None or through is None:
        return totals
    for row in rows:
        if not row.get('event_date'):
            continue
        event_date = _date(row['event_date'])
        if not start <= event_date <= through:
            continue
        totals[_source_group(row.get('business_group'))] += Decimal(1)
    return totals


def _unique_market_orders(rows):
    unique = {}
    for row in rows:
        order_id = str(row['work_order_id']).strip()
        if order_id:
            unique.setdefault(order_id, row)
    return unique


def _set_orders(name, current, prior, period, target, note=''):
    status = period.get('status', 'available')
    progress = period.get('time_progress', 0)
    if status == 'future' or not period.get('through_date'):
        actual = previous = None
        status = 'future'
    else:
        actual = _number(current.get(name, Decimal(0)))
        previous = _number(prior.get(name, Decimal(0)))
    return metric(actual, previous, target, progress, '单', status=status, note=note)


def _empty_metric(period, unit):
    if period.get('status') == 'future' or not period.get('through_date'):
        return metric(None, None, None, period.get('time_progress', 0), unit, status='future')
    return metric(0, 0, None, period.get('time_progress', 0), unit)


def _period_group_sums(period, baseline_rows):
    if period.get('status') == 'future' or not period.get('through_date'):
        return ({}, {}), ({}, {})
    start = _date(period['start_date'])
    through = _date(period['through_date'])
    prior_start, prior_through = _shift_year(start), _shift_year(through)
    current_source = _baseline_sums(baseline_rows, start, through)
    prior_source = _baseline_sums(baseline_rows, prior_start, prior_through)

    current_business, prior_business = defaultdict(Decimal), defaultdict(Decimal)
    for group, amount in current_source.items():
        current_business[_business_group(group)] += amount
    for group, amount in prior_source.items():
        prior_business[_business_group(group)] += amount
    return (current_source, prior_source), (current_business, prior_business)


def _append_unknown_business_group(rows, period, current, prior):
    unknown = {'name': UNKNOWN_GROUP,
               'orders': _set_orders(UNKNOWN_GROUP, current, prior, period, None),
               'cash': _empty_metric(period, '元'),
               'heads': _empty_metric(period, '人')}
    rows.append(unknown)
    return unknown


def _apply_total(period, team, market_rows):
    original_training_orders = team.get('lines', {}).get('training', {}).get('orders', {})
    target = original_training_orders.get('target')
    preserved_actual = original_training_orders.get('actual')
    preserved_prior = original_training_orders.get('prior')
    preserved_note = original_training_orders.get('note', '')
    progress = period.get('time_progress', 0)
    line_status = original_training_orders.get('status', period.get('status', 'available'))
    training_orders = metric(
        preserved_actual, preserved_prior, None, progress,
        original_training_orders.get('unit', '单'),
        status=line_status, note=preserved_note,
    )
    for key in ('target', 'completion', 'gap', 'time_gap'):
        training_orders.pop(key, None)
    team['lines']['training']['orders'] = training_orders

    (current_source, prior_source), (current_business, prior_business) = _period_group_sums(
        period, market_rows,
    )
    market_current = {'market': sum(current_source.values(), Decimal(0))}
    market_prior = {'market': sum(prior_source.values(), Decimal(0))}
    team['market_orders'] = _set_orders(
        'market', market_current, market_prior, period, target,
        note='语培被动工单按观远8类原始团队白名单统计，排除空团队；包含删除/回收，按工单ID去重。个人业绩剔除删除/回收。',
    )

    business_rows = team.setdefault('business_groups', [])
    business_by_name = {row.get('name'): row for row in business_rows}
    for name, row in business_by_name.items():
        old_orders = row.get('orders') or {}
        row['orders'] = _set_orders(
            name, current_business, prior_business, period, old_orders.get('target'),
        )
    if UNKNOWN_GROUP not in business_by_name:
        _append_unknown_business_group(
            business_rows, period, current_business, prior_business,
        )

    yoy_rows = team.setdefault('yoy_groups', [])
    yoy_by_name = {row.get('name'): row for row in yoy_rows}
    for name in (*SOURCE_GROUPS, UNKNOWN_GROUP):
        row = yoy_by_name.get(name)
        if row is None:
            continue
        old_orders = row.get('orders') or {}
        row['orders'] = _set_orders(
            name, current_source, prior_source, period, old_orders.get('target'),
        )
    if UNKNOWN_GROUP not in yoy_by_name:
        yoy_rows.append({
            'name': UNKNOWN_GROUP,
            'orders': _set_orders(UNKNOWN_GROUP, current_source, prior_source, period, None),
        })


def attach_market_orders(periods, market_rows):
    """Attach market-wide passive orders to total teams, leaving other data intact.

    market_rows is the per-order controlled result for the training total.
    """
    market_rows = list(_unique_market_orders(list(market_rows or [])).values())
    for period in periods:
        for team in period.get('teams', []):
            if team.get('id') == 'total':
                _apply_total(period, team, market_rows)
    return periods
