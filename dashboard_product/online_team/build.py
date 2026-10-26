"""Shared calculation and controlled-query helpers used by native BI."""
from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from data_platform.query.evidence import read_query_result, resolve_file, verify_receipt

MAPPING = HERE / 'config/confirmed_team_mapping.json'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('0.01')))


def total(records, metric):
    amount = sum((Decimal(str(r['value'])) for r in records if r['metric'] == metric), Decimal(0))
    return int(amount) if metric == 'orders' else money(amount)


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


def query(sql, params, suffix, run_id, snapshot, warehouse, out, evidence_root):
    cache = out / 'query_responses' / f'{suffix}.json'
    qrun = f'{run_id}_{suffix}'
    if cache.exists():
        response = read(cache)
        if response['run_id'] != qrun:
            raise ValueError('output directory belongs to a different run_id')
        receipt_path = resolve_file(evidence_root / response['run_id'], response['receipt'])
        receipt, _ = verify_receipt(receipt_path)
        if response['snapshot_id'] != snapshot or receipt['sql']['sha256'] != sha(sql):
            raise ValueError('cached query identity/SQL changed; use a new output directory and run_id')
        saved_params = read(receipt_path.parent / receipt['parameters']['path'])
        if saved_params != params:
            raise ValueError('cached query window changed; use a new output directory and run_id')
    else:
        cmd = [sys.executable, '-m', 'interfaces.data_platform', 'query', '--warehouse', str(warehouse),
               '--snapshot-id', snapshot, '--run-id', qrun, '--output-root', str(evidence_root),
               '--sql-file', str(sql), '--params-json', json.dumps(params),
               '--max-rows', '100000', '--max-result-bytes', '50000000']
        done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if done.returncode:
            raise RuntimeError(done.stdout or done.stderr)
        response = json.loads(done.stdout)
        if response.get('status') != 'passed' or response.get('run_id') != qrun:
            raise ValueError(response.get('errors'))
        write(cache, response)
    result = read_query_result(response, output_root=evidence_root)
    receipt_path = resolve_file(evidence_root / response['run_id'], response['receipt'])
    return [dict(zip(result['columns'], row)) for row in result['rows']], str(receipt_path)


def source_label(path, workspace):
    resolved = Path(path).resolve()
    for base, prefix in ((Path(workspace).resolve(), 'workspace/'), (ROOT.resolve(), 'repo/')):
        try:
            return prefix + resolved.relative_to(base).as_posix()
        except ValueError:
            pass
    return str(resolved)


def prepare_output(out, workspace, run_id, snapshot_id, as_of_date):
    workspace = Path(workspace).resolve()
    allowed = (workspace / 'Output').resolve()
    out = Path(out).resolve()
    if not out.is_relative_to(allowed):
        raise ValueError('output must remain under workspace/Output')
    identity = {'run_id': run_id, 'snapshot_id': snapshot_id, 'as_of_date': as_of_date,
                'workspace': str(workspace)}
    marker = out / '_build_identity.json'
    if out.exists():
        if not marker.is_file() or read(marker) != identity:
            raise ValueError('output directory exists for another or unknown batch; choose a new run_id/output directory')
    else:
        out.mkdir(parents=True)
        write(marker, identity)
    return out


def select(records, start, end):
    return [] if end is None else [r for r in records if start <= r['event_date'] <= end]


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


def channel_rows(now, prior, line_id, through, period):
    names = sorted({r['second_channel'] for r in now + prior})
    denominator = total(now, 'orders')
    result = []
    for name in names:
        a, b = [r for r in now if r['second_channel'] == name], [r for r in prior if r['second_channel'] == name]
        orders, prior_orders = total(a, 'orders'), total(b, 'orders')
        cash, prior_cash = (total(a, 'cash'), total(b, 'cash')) if line_id == 'training' else (None, None)
        result.append({'name': name, 'first_channels': sorted({r['first_channel'] for r in a + b}),
                       'orders': orders, 'prior_orders': prior_orders,
                       'orders_yoy': orders / prior_orders - 1 if prior_orders else None,
                       'share': orders / denominator if denominator else None,
                       'today_orders': total([r for r in a if r['event_date'] == through], 'orders') if period['through_date'] == through else None,
                       'cash': cash, 'prior_cash': prior_cash,
                       'cash_yoy': cash / prior_cash - 1 if cash is not None and prior_cash else None})
    return sorted(result, key=lambda r: (-r['orders'], r['name']))


def dimensions(now, prior):
    result = []
    for name in sorted({r['line'] for r in now + prior}):
        a, b = [r for r in now if r['line'] == name], [r for r in prior if r['line'] == name]
        children = []
        for country in sorted({r['country'] for r in a + b}):
            n, p = sum(r['country'] == country for r in a), sum(r['country'] == country for r in b)
            children.append({'name': country, 'orders': n, 'prior_orders': p, 'yoy': n / p - 1 if p else None, 'children': []})
        result.append({'name': name, 'orders': len(a), 'prior_orders': len(b), 'yoy': len(a) / len(b) - 1 if b else None,
                       'children': sorted(children, key=lambda r: -r['orders'])})
    return sorted(result, key=lambda r: -r['orders'])


def shanghai_today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
