"""Shared calendar and metric formatting rules."""
import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('0.01')))

def window(start, end, through):
    future = through < start
    effective = None if future else min(end, through)
    return {'start_date': start.isoformat(), 'end_date': end.isoformat(),
            'through_date': effective.isoformat() if effective else None,
            'prior_start_date': start.replace(year=start.year - 1).isoformat(),
            'prior_through_date': effective.replace(year=effective.year - 1).isoformat() if effective else None,
            'time_progress': 0.0 if future else ((effective - start).days + 1) / ((end - start).days + 1),
            'status': 'future' if future else 'available'}

def metric(actual, prior, target, progress, unit, status='available', note=''):
    if status != 'available':
        actual = prior = None
    return {'actual': actual, 'prior': prior, 'target': target, 'unit': unit, 'status': status, 'note': note,
            'completion': actual / target if actual is not None and target not in (None, 0) else None,
            'yoy': actual / prior - 1 if actual is not None and prior not in (None, 0) else None,
            'gap': money(Decimal(str(actual)) - Decimal(str(target))) if actual is not None and target is not None else None,
            'time_gap': money(Decimal(str(actual)) - Decimal(str(target)) * Decimal(str(progress))) if actual is not None and target is not None else None}

def periods(through):
    definitions = [('FY27', '2027财年全年', 'year', date(2026, 6, 1), date(2027, 5, 31))]
    for i, (y, m) in enumerate([(2026, 6), (2026, 9), (2026, 12), (2027, 3)], 1):
        ey, em = (y + (m + 1) // 12, (m + 1) % 12 + 1)
        definitions.append((f'Q{i}', f'第{"一二三四"[i-1]}季度', 'quarter', date(y, m, 1), date(ey, em, calendar.monthrange(ey, em)[1])))
    for i in range(12):
        y, m = 2026 + (5 + i) // 12, (5 + i) % 12 + 1
        definitions.append((f'{y}-{m:02d}', f'{y}年{m}月', 'month', date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])))
    return [dict(id=k, label=label, kind=kind, **window(start, end, through)) for k, label, kind, start, end in definitions]

def study_target(config, period, kind):
    source = config['study_abroad']['resource_target'] if kind == 'orders' else config['cash']['total']
    if period['kind'] == 'year':
        value = source.get('annual')
    else:
        value = source.get('months' if period['kind'] == 'month' else 'quarters', {}).get(period['id'])
    return None if value is None else money(Decimal(str(value)) * (10000 if kind == 'cash' else 1))


def qualified_students(records):
    amounts=defaultdict(Decimal)
    enrolled=set()
    for row in records:
        student=str(row.get('student_id') or '').strip()
        if not student: continue
        key=(student,row.get('class_code'))
        amounts[key]+=Decimal(str(row.get('value') or 0))
        if Decimal(str(row.get('registration_count') or 0))>0:
            enrolled.add(key)
    return {student for student,course in enrolled if abs(amounts[(student,course)])>=1500}
