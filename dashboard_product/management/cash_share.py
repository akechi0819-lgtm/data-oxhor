"""Attach total-board passive cash shares from controlled-query aggregates."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


BUSINESS_GROUPS = frozenset({'留学预备', '高中', '大学', '业务组暂无法拆分'})
CENT = Decimal('0.01')


def _date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _decimal(value):
    if value in (None, ''):
        raise ValueError('cash share amount is missing')
    return Decimal(str(value))


def _money(value):
    amount = value.quantize(CENT, rounding=ROUND_HALF_UP)
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def attach_passive_cash_share(periods, daily_rows):
    """Add the ratio only to total-board business groups for each calendar window.

    ``None`` means the denominator query result is unavailable; an empty result
    is a successful query with no qualifying positive new-student cash.
    """
    by_group = defaultdict(list)
    if daily_rows is not None:
        for row in daily_rows:
            group = str(row.get('business_group') or '').strip()
            if group not in BUSINESS_GROUPS:
                raise ValueError(f'unrecognized cash share business group: {group!r}')
            amount = _decimal(row.get('cash_amount'))
            if amount <= 0:
                raise ValueError('cash share query returned a non-positive aggregate')
            by_group[group].append((_date(row.get('cash_date')), amount))

    for period in periods:
        total = next((team for team in period.get('teams', []) if team.get('id') == 'total'), None)
        if total is None:
            continue
        is_future = period.get('status') == 'future' or not period.get('through_date')
        start = _date(period['start_date']) if not is_future else None
        through = _date(period['through_date']) if not is_future else None
        for group_row in total.get('business_groups', []):
            numerator = (group_row.get('cash') or {}).get('actual')
            if is_future:
                result = {'numerator': None, 'denominator': None, 'ratio': None,
                          'status': 'future', 'note': '统计期间尚未开始。'}
            elif daily_rows is None:
                result = {'numerator': numerator, 'denominator': None, 'ratio': None,
                          'status': 'unavailable', 'note': '全渠道新生现金分母查询结果缺失，无法计算。'}
            else:
                group = group_row.get('name')
                denominator_decimal = sum(
                    (amount for event_date, amount in by_group.get(group, [])
                     if start <= event_date <= through), Decimal(0),
                ).quantize(CENT, rounding=ROUND_HALF_UP)
                denominator = _money(denominator_decimal)
                if numerator is None:
                    result = {'numerator': None, 'denominator': denominator,
                              'ratio': None, 'status': 'unavailable',
                              'note': '被动现金分子尚未接入，无法计算。'}
                elif denominator_decimal == 0:
                    note = ('分母为零，无法计算占比。'
                            if _decimal(numerator) == 0 else
                            '分母为零但被动现金分子非零，请核对来源口径。')
                    result = {'numerator': numerator, 'denominator': denominator,
                              'ratio': None, 'status': 'zero_denominator', 'note': note}
                else:
                    ratio = float(_decimal(numerator) / denominator_decimal)
                    over_100 = ratio > 1
                    result = {
                        'numerator': numerator,
                        'denominator': denominator,
                        'ratio': ratio,
                        'status': 'over_100_percent' if over_100 else 'available',
                        'note': ('被动现金分子高于全渠道新生现金分母，超过100%；请核对来源口径。'
                                 if over_100 else ''),
                    }
            group_row['passive_cash_share'] = result
