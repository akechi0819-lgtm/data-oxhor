"""P1: one read-only calculation batch for static pages and future notifications."""
from __future__ import annotations

import argparse
import calendar
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from data_platform.query.evidence import read_query_result, resolve_file, verify_receipt
from dashboard_product.fallback_mapping import resolve_cash_channel, infer_team
from dashboard_product.refresh import remap_tmk_school_agent_team, TARGET_GROUP, YOY_GROUPS
from workspace_modeling.operations.personnel import is_displayable_person
from data_acquisition.jobs.work_order_cleaning import clean_work_order_rows, load_work_order_reference

DEFAULT_WORKSPACE = ROOT / 'customers/bi_operations'
MAPPING = HERE / 'config/confirmed_team_mapping.json'
GROUPS = ['留学预备', '高中', '大学']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def text(value):
    return str(value or '').strip()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('0.01')))


def total(records, metric):
    amount = sum((Decimal(str(r['value'])) for r in records if r['metric'] == metric), Decimal(0))
    return int(amount) if metric == 'orders' else money(amount)


def classify_team(source_team, adviser, mapping):
    original = text(source_team)
    return original if original else mapping.get(text(adviser))


def abroad_eligible(root, active):
    return (root == '网络资源' and active in ('主动', '被动')) or (root == '新媒体' and active == '被动')


def is_ssc(channel):
    return text(channel).casefold() == 'ssc'


def allocate_targets(annual, weights):
    denominator = sum(weights.values())
    if annual < 0 or denominator <= 0 or any(v < 0 for v in weights.values()):
        raise ValueError('target allocation requires nonnegative amounts and positive total weight')
    exact = {k: Fraction(annual * v, denominator) for k, v in weights.items()}
    allocated = {k: int(v) for k, v in exact.items()}
    ranked = sorted(weights, key=lambda k: (-(exact[k] - allocated[k]), k))
    for k in ranked[:annual - sum(allocated.values())]:
        allocated[k] += 1
    return allocated


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


def training_facts(rows, people):
    offline_names = {p['display_name'] for t in people['teams'] if t['team_id'] == 'offline_market'
                     for g in t['groups'] for p in g['members'] if is_displayable_person(p)}
    facts = []
    for r in rows:
        team, group = r['team_id'], r['business_group']
        first, second = r['first_channel'], r['second_channel']
        kind = 'cash' if r['metric'] == 'passive_reported_cash' else 'orders'
        if kind == 'cash':
            channel = resolve_cash_channel(r['cash_channel'], r['cash_campaign_name'] or r['campaign_name'],
                                           first, second, r['work_order_active_type'])
            first, second = channel['first_channel'], channel['second_channel']
            if not team or 'TMK' in text(r['cash_channel']).upper():
                team, _ = infer_team(team, r['cash_channel'], r['cash_campaign_name'] or r['campaign_name'],
                                     first, second, channel['decision'])
        team = remap_tmk_school_agent_team(team, first, r['campaign_name'], r['entry_person'], offline_names)
        if team != 'online_platform' or group not in YOY_GROUPS:
            continue
        facts.append({'line_id': 'training', 'metric': kind, 'event_date': r['event_date'],
                      'value': money(r['actual_value']) if kind == 'cash' else int(r['actual_value']),
                      'source_row_number': r.get('source_row_number'), 'work_order_id': r.get('work_order_id'),
                      'student_id': r.get('student_id'), 'business_group': TARGET_GROUP[group],
                      'first_channel': first or '一级渠道待确认', 'second_channel': second or '二级渠道待确认',
                      'campaign_name': r.get('campaign_name'), 'team_id': team})
    return facts


def study_facts(rows, mapping, reference):
    current, legacy, labels = [], [], Counter()
    for r in rows:
        labeled = classify_team(r['source_team'], r['adviser'], mapping)
        labels[labeled or '待确认'] += 1
        source = {'ID': r['work_order_id'], '团队': r['source_team'], '主被动': r['main_active_type'],
                  '资源主被动': r['resource_active_type'], '咨询方式一级渠道': r['source_path'],
                  '渠道': r['source_channel'], '一级渠道': r['first_channel'], '二级渠道': r['second_channel'],
                  '意向国家/地区': r['intended_country_source'], '资源描述': r['resource_description']}
        original_active = source['主被动']
        cleaned, _ = clean_work_order_rows([source], reference, include_audit=True)
        source = cleaned[0]
        source['主被动'] = original_active
        root = text(r['source_path']).split('-', 1)[0]
        if not abroad_eligible(root, text(r['resource_active_type'])):
            continue
        channel = source['二级渠道'] if source.get('留学渠道清洗状态') == '已命中' else '当前规则未命中'
        # Preserve the accepted dashboard's SSC bucket mapping. 小语种 remains
        # its own corrected channel and is not filtered with 其他.
        channel = {'其他': 'ssc'}.get(channel, channel)
        if is_ssc(channel):
            channel = 'SSC'
        fact = {'line_id': 'abroad', 'metric': 'orders', 'value': 1, 'event_date': r['event_date'],
                'source_row_number': r['source_row_number'], 'work_order_id': r['work_order_id'],
                'adviser': r['adviser'], 'original_team': r['source_team'], 'labeled_team': labeled,
                'main_active_type': original_active, 'resource_active_type': r['resource_active_type'],
                'first_channel': source.get('一级渠道') or root, 'second_channel': channel,
                'source_path': r['source_path'], 'original_first_channel': r['first_channel'],
                'original_second_channel': r['second_channel'], 'business_group': root,
                'country': source.get('意向国家') or '国家待确认', 'line': source.get('矫正条线') or '条线待确认'}
        # Keep old-scope rows only as reconciliation baselines. New facts,
        # details, channels, and public rollups exclude the confirmed SSC bucket.
        legacy.append(fact)
        if labeled == '留学' and not is_ssc(channel):
            current.append(fact)
    return current, legacy, dict(labels)


def select(records, start, end):
    return [] if end is None else [r for r in records if start <= r['event_date'] <= end]


def periods(through):
    definitions = [('FY27', 'FY27 全年', 'year', date(2026, 6, 1), date(2027, 5, 31))]
    for i, (y, m) in enumerate([(2026, 6), (2026, 9), (2026, 12), (2027, 3)], 1):
        ey, em = (y + (m + 1) // 12, (m + 1) % 12 + 1)
        definitions.append((f'Q{i}', f'Q{i}', 'quarter', date(y, m, 1), date(ey, em, calendar.monthrange(ey, em)[1])))
    for i in range(12):
        y, m = 2026 + (5 + i) // 12, (5 + i) % 12 + 1
        definitions.append((f'{y}-{m:02d}', f'{y}年{m}月', 'month', date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])))
    return [dict(id=k, label=label, kind=kind, **window(start, end, through)) for k, label, kind, start, end in definitions]


def training_target(config, period, kind, group=None):
    field = 'work_order_target' if kind == 'orders' else 'passive_cash_target'
    values = []
    for item in config['business_groups'].values():
        if group and item['display_name'] != group:
            continue
        if period['kind'] == 'month':
            values.append(item.get('months', {}).get(period['id'], {}).get('online_platform', {}).get(field))
        else:
            keys = ['Q1', 'Q2', 'Q3', 'Q4'] if period['kind'] == 'year' else [period['id']]
            values.extend(item['quarters'][k]['online_platform'].get(field) for k in keys)
    return None if not values or any(v is None for v in values) else money(sum(Decimal(str(v)) for v in values))


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


def compare_cell(period, line_id, kind, baseline, current, reason, baseline_label='旧看板同源复算'):
    delta = None if baseline is None or current is None else float(Decimal(str(current)) - Decimal(str(baseline)))
    return {'period_id': period, 'line_id': line_id, 'metric': kind, 'baseline': baseline, 'current': current,
            'delta': delta, 'status': 'unavailable' if delta is None else 'matched' if abs(delta) < .000001 else 'difference',
            'reason': reason, 'baseline_label': baseline_label}


def shanghai_today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()


def build(args):
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f'data workspace does not exist: {workspace}')
    run_id = args.run_id
    if not re.fullmatch(r'run_[a-z0-9][a-z0-9_-]{2,67}', run_id) or len(run_id) > 58:
        raise ValueError('run_id must use run_ followed by lowercase letters, digits, _ or - and leave room for query suffixes')
    as_of_date = args.as_of_date or shanghai_today()
    date.fromisoformat(as_of_date)
    config = read(workspace / 'Work/workspace.json')
    if args.snapshot_id != config['current_snapshot_id']:
        raise ValueError('explicit Snapshot differs from workspace current pointer')
    requested_out = (Path(args.output_dir).expanduser() if args.output_dir else
                     workspace / 'Output' / 'DashboardOnline' / run_id)
    out = prepare_output(requested_out, workspace, run_id, args.snapshot_id, as_of_date)
    evidence_root = out / '_query'
    guide = json.loads(subprocess.check_output([sys.executable, '-m', 'interfaces.casebook', 'guide', '--workspace', str(workspace)], cwd=ROOT, text=True))
    if guide['next_step'] != 'analyze':
        raise ValueError('workspace is not ready for controlled analysis')
    warehouse = workspace / config['current_warehouse_path']
    receipts = []
    def fetch(sql, params, suffix):
        records, receipt = query(sql, params, suffix, run_id, args.snapshot_id, warehouse, out, evidence_root)
        receipts.append(receipt)
        return records
    dates = fetch(HERE / 'sql/data_through.sql', [], 'checked_dates')[0]
    if not dates.get('work_orders_max_date') or not dates.get('cash_max_date'):
        raise ValueError('missing source data-through date')
    through = min(date.fromisoformat(dates[k]) for k in ('work_orders_max_date', 'cash_max_date'))
    through = min(through, date.fromisoformat(as_of_date) - timedelta(days=1))
    if not date(2026, 6, 1) <= through <= date(2027, 5, 31):
        raise ValueError('P1 currently covers FY27')
    params = ['2025-06-01', (through + timedelta(days=1)).isoformat()]
    training_rows = fetch(HERE / 'sql/training_details.sql', params, 'training')
    baseline_rows = fetch(HERE / 'baseline/dashboard_actuals_v14.sql', params, 'baseline')
    raw_abroad = fetch(HERE / 'sql/blank_team_detail.sql', params, 'abroad')
    people = read(ROOT / 'workspace_modeling/operations/people.json')
    training, old_training = training_facts(training_rows, people), training_facts(baseline_rows, people)
    mapping_doc = read(MAPPING)
    mapping = {r['source_adviser']: r['labeled_team'] for r in mapping_doc['mappings']}
    if Counter(mapping.values()) != {'留学': 57, '留学预备': 2}:
        raise ValueError('confirmed adviser mapping differs from approved 57/2 split')
    reference_path = workspace / 'Input/Reference/留学-FY26-资源表.xlsx'
    if not reference_path.is_file():
        raise FileNotFoundError(f'missing study-abroad channel reference workbook: {reference_path}')
    abroad, old_abroad, label_counts = study_facts(raw_abroad, mapping, load_work_order_reference(reference_path))
    training_target_path = ROOT / 'dashboard_product/config/project_targets.json'
    training_config = read(training_target_path)
    abroad_config = read(HERE / 'config/study_abroad_targets.json')
    resource_target = abroad_config['study_abroad']['resource_target']
    allocation_basis = resource_target['allocation_basis']
    expected_months = allocate_targets(resource_target['annual'], allocation_basis['months'])
    if resource_target['months'] != expected_months:
        raise ValueError('monthly targets do not match the confirmed annual target and allocation weights')
    months = sorted(expected_months)
    expected_quarters = {f'Q{i+1}': sum(expected_months[k] for k in months[i*3:i*3+3]) for i in range(4)}
    if resource_target['quarters'] != expected_quarters:
        raise ValueError('quarter targets must equal their allocated months')
    scorecard_path = workspace / 'Input/Reference/留学板块-官方记分卡.json'
    scorecard = read(scorecard_path) if scorecard_path.is_file() else None
    official_q1 = (next(r for r in scorecard['online']['rows'] if r['period'] == 'FY27-Q1')['累计']['资源数']
                   if scorecard else None)
    official_target = (next(r for r in scorecard['online']['rows'] if r['period'] == 'FY27-target')['累计']
                       if scorecard else None)
    views, cells = [], []
    for p in periods(through):
        now = {k: select(v, p['start_date'], p['through_date']) for k, v in [('training', training), ('abroad', abroad)]}
        prior = {k: select(v, p['prior_start_date'], p['prior_through_date']) for k, v in [('training', training), ('abroad', abroad)]}
        p['lines'], p['notes'] = {}, []
        for line_id in ('training', 'abroad'):
            a, b = now[line_id], prior[line_id]
            line = {'label': '语培' if line_id == 'training' else '留学',
                    'scope': '被动工单 / 被动新生正向报入现金' if line_id == 'training' else '线上留学工单按清洗后渠道统计',
                    'notices': [], 'groups': [], 'dimensions': []}
            for kind, unit in [('orders', '条'), ('cash', '元')]:
                target = training_target(training_config, p, kind) if line_id == 'training' else study_target(abroad_config, p, kind)
                status = 'future' if p['status'] == 'future' else 'not_connected' if line_id == 'abroad' and kind == 'cash' else 'available'
                note = ''
                if line_id == 'abroad' and kind == 'cash':
                    note = '留学现金实际待接入。' + ('本期现金目标未配置。' if target is None else '目标为现行看板毛签目标。')
                if line_id == 'abroad' and kind == 'orders':
                    note = '年度目标 6,715 条；按原 5,315 条的月度比例分配，季度按新月度目标加总。'
                if line_id == 'training' and p['kind'] == 'month':
                    note = '月度目标沿用语培暂行配置；月度合计不等于现有季度目标。'
                line[kind] = metric(total(a, kind), total(b, kind), target, p['time_progress'], unit, status, note)
            line['channels'] = channel_rows(a, b, line_id, through.isoformat(), p) if p['status'] != 'future' else []
            if line_id == 'training':
                for group in GROUPS:
                    ga, gb = [r for r in a if r['business_group'] == group], [r for r in b if r['business_group'] == group]
                    item = {'name': group}
                    for kind, unit in [('orders', '条'), ('cash', '元')]:
                        item[kind] = metric(total(ga, kind), total(gb, kind), training_target(training_config, p, kind, group), p['time_progress'], unit, p['status'])
                    line['groups'].append(item)
            else:
                if p['status'] != 'future':
                    line['dimensions'] = dimensions(a, b)
            p['lines'][line_id] = line
        p['daily'] = []
        if p['status'] != 'future':
            counts = {k: Counter() for k in ('training', 'abroad')}
            for k in ('training', 'abroad'):
                for r in now[k]:
                    if r['metric'] == 'orders':
                        counts[k][r['event_date']] += r['value']
            day, last = date.fromisoformat(p['start_date']), date.fromisoformat(p['through_date'])
            while day <= last:
                s = day.isoformat()
                p['daily'].append({'date': s, 'training_orders': counts['training'][s], 'abroad_orders': counts['abroad'][s]})
                day += timedelta(days=1)
            for line_id, old in [('training', old_training), ('abroad', old_abroad)]:
                for kind in ('orders', 'cash') if line_id == 'training' else ('orders',):
                    for is_prior in (False, True):
                        records = select(old, p['prior_start_date'] if is_prior else p['start_date'], p['prior_through_date'] if is_prior else p['through_date'])
                        old_value = total(records, kind)
                        current = p['lines'][line_id][kind]['prior' if is_prior else 'actual']
                        reason = '原规则在同一主Snapshot、同窗复算。'
                        if line_id == 'abroad' and current != old_value:
                            reason = '本版留学统计统一排除 SSC 渠道；旧基线保留原统计范围，差异用于说明口径变化。'
                        if is_prior and current != old_value and kind == 'orders' and line_id == 'training':
                            reason = '两位语培顾问的历史空团队记录恢复归留学预备，改变同期基数；当前完成未因此增加。'
                        cells.append(compare_cell(p['id'], line_id, ('prior_' if is_prior else '') + kind, old_value, current, reason))
        if p['id'] == 'Q1' and scorecard is not None:
            actual = p['lines']['abroad']['orders']['actual']
            p['lines']['abroad']['notices'].append(f'留学Q1官方完成为 {official_q1} 条，本页数仓拆解为 {actual} 条；官方完成以记分卡为准，差异单独待核。')
            cells.append(compare_cell(p['id'], 'abroad', 'orders', official_q1, actual, '官方记分卡与数仓口径存在既有差异，本页数仓拆解不替代官方完成。', '官方记分卡'))
        if p['id'] == 'FY27' and scorecard is not None:
            cells.append(compare_cell(p['id'], 'abroad', 'target_orders', official_target['资源数'], p['lines']['abroad']['orders']['target'], '用户确认全年采用6715，原5315仅保留为月度分配权重。', '官方年度目标'))
        if p['id'] == 'FY27' and scorecard is not None:
            cells.append(compare_cell(p['id'], 'abroad', 'target_cash', official_target['毛签万元'] * 10000,
                                     p['lines']['abroad']['cash']['target'],
                                     f"官方累计{official_target['毛签万元']}万元，配置按渠道相加{p['lines']['abroad']['cash']['target'] / 10000:.2f}万元；不自动回写。",
                                     '官方年度目标'))
        views.append(p)
    scorecard_note = ('留学官方记分卡已载入，并仅用于历史对照。' if scorecard is not None else
                      '未载入官方记分卡；仅展示数仓结果和已确认目标，不填补官方指标。')
    unclassified_count = label_counts.get('待确认', 0)
    notes = ['所有页面指标由同一批结果提供，推送后续直接消费该结果。',
             f'本页展示主仓受控查询的数仓口径；{scorecard_note}',
             f'空团队中未命中已确认顾问名单的记录数：{unclassified_count}；这些记录不计入语培或留学归属。',
             '语培现金沿用原V14资格和渠道归属；留学工单渠道重洗不回灌改变语培现金归属。',
             '留学统计统一排除原确认的 SSC 桶（包含清洗后“其他”映射）；小语种作为独立渠道保留。年度目标为6715，按原5315月度比例分配。',
             '完整明细和查询回执保留本地，不包含在网页发布目录。']
    actual_differences = [c for c in cells if c['baseline_label'] == '旧看板同源复算'
                          and c['metric'] in ('orders', 'cash') and c['status'] == 'difference']
    actual_note = (f'同源同窗当前完成对比有 {len(actual_differences)} 项差异，见对数表。' if actual_differences
                   else '语培与留学同窗当前完成未发现差异。')
    reconciliation = {'summary': '与同源同窗旧看板复算对数；如已载入官方记分卡则单列历史差异。', 'cells': cells,
                      'notes': [actual_note,
                                '此处旧看板指现行源码同窗复算，不代表已实查线上部署；历史页面截止日可能不同，不能直接相减。',
                                '数值不同不自动判新旧正误，业务差异留待确认。']}
    metadata = {'run_id': run_id, 'snapshot_id': args.snapshot_id, 'data_through': through.isoformat(),
                'created_at': datetime.now(timezone.utc).isoformat(), 'default_period': through.strftime('%Y-%m'),
                'notes': notes, 'title': '线上团队 · 经营进度'}
    public = {'schema_version': 'dashboard_rebuild.v1', 'metadata': metadata, 'periods': views, 'reconciliation': reconciliation}
    bridge_path = workspace / 'Work/Bridge/reference.json'
    config_files = [training_target_path, HERE / 'config/study_abroad_targets.json', MAPPING, reference_path,
                    ROOT / 'workspace_modeling/operations/people.json', ROOT / 'dashboard_product/config/cash_channel_fallback_rules.json',
                    bridge_path]
    if scorecard is not None:
        config_files.append(scorecard_path)
    shared = {**public, 'query_receipts': receipts,
              'source_hashes': {source_label(p, workspace): sha(p) for p in config_files},
              'normalization_counts': label_counts, 'details_file': 'details.json'}
    write(out / 'details.json', {'schema_version': 'dashboard_rebuild_details.v1', 'metadata': metadata,
                               'query_receipts': receipts, 'records': training + abroad})
    shared['details_ref'] = {'path': 'details.json', 'sha256': sha(out / 'details.json'), 'record_count': len(training) + len(abroad)}
    shared['calculation_sources'] = {source_label(p, workspace): sha(p) for p in [
        Path(__file__), ROOT / 'dashboard_product/refresh.py', ROOT / 'dashboard_product/fallback_mapping.py',
        ROOT / 'data_acquisition/jobs/work_order_cleaning.py']}
    write(out / 'shared_result.json', shared)
    (out / 'site').mkdir(parents=True, exist_ok=True)
    (out / 'site/data.json').write_text(json.dumps(public, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    write(out / 'reconciliation.json', reconciliation)
    report = ['# P1 对数结果', '', f'数据截止：{through}。旧看板为同一主Snapshot、同窗现行源码复算；不声称已核验线上部署。', '',
              '## 差异清单', '', '| 期间 | 业务线 | 指标 | 对照来源 | 对照值 | 新结果 | 差异 | 依据 |', '| --- | --- | --- | --- | ---: | ---: | ---: | --- |']
    for c in cells:
        if c['status'] == 'difference':
            report.append(f"| {c['period_id']} | {c['line_id']} | {c['metric']} | {c['baseline_label']} | {c['baseline']} | {c['current']} | {c['delta']} | {c['reason']} |")
    report += ['', '## 范围与限制', '', *[f'- {n}' for n in notes + reconciliation['notes']], '',
               '## 查询证据', '', *[f'- `{source_label(p, workspace)}`' for p in receipts]]
    (out / 'reconciliation.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    for name in ('index.html', 'styles.css', 'app.js'):
        shutil.copy2(HERE / 'web' / name, out / 'site' / name)
    return {'status': 'built', 'output_dir': str(out), 'data_through': through.isoformat(), 'periods': len(views),
            'training_fact_rows': len(training), 'abroad_fact_rows': len(abroad), 'normalization_counts': label_counts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument('--snapshot-id', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--as-of-date')
    result = build(parser.parse_args(argv))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
