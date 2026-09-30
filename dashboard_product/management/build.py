"""Build P2 locally from one explicit Snapshot through controlled read-only queries."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys

from dashboard_product.online_team.build import (
    ROOT, MAPPING, read, write, sha, query, prepare_output, shanghai_today,
    source_label, study_facts,
)
from dashboard_product.online_team.export import export_site, validate_public_data
from data_acquisition.jobs.work_order_cleaning import load_work_order_reference

HERE = Path(__file__).resolve().parent


def yearly_windows(start, end):
    while start < end:
        next_start = min(end, date(start.year + 1, 1, 1))
        yield start.isoformat(), next_start.isoformat()
        start = next_start


def presentation_data(value):
    """Omit absent optional presentation fields; private calculation output stays complete."""
    if isinstance(value, dict):
        return {key: presentation_data(item) for key, item in value.items()
                if item is not None and item != ''}
    if isinstance(value, list):
        return [presentation_data(item) for item in value]
    return value


def write_site_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')


def export_department(out, public, page, team_ids):
    """Package each independently composed board with only its management units."""
    package = out / 'packages' / page
    package.mkdir(parents=True, exist_ok=True)
    data = {**public, 'periods': [{**period, 'teams': [team for team in period['teams'] if team['id'] in team_ids]}
                                for period in public['periods']]}
    data.pop('reconciliation', None)
    data.pop('capacity', None)
    data.pop('activities', None)
    write_site_json(package / 'data.json', data)
    write_site_json(out / 'site' / f'{page}.data.json', data)
    html = (HERE / 'web' / f'{page}.html').read_text(encoding='utf-8')
    html = html.replace('./boards.css', './styles.css').replace('./boards.js', './app.js')
    (package / 'index.html').write_text(html, encoding='utf-8')
    shutil.copy2(out / 'site/boards.css', package / 'styles.css')
    shutil.copy2(out / 'site/boards.js', package / 'app.js')
    return export_site(package, out / f'{page}.html')


def reconciliation(result, old_rows, people, training_targets):
    """Independent current V14 and accepted P1 calculations, same window/identity."""
    from dashboard_product.refresh import project, DASHBOARD_QUERY_COLUMNS
    columns = list(DASHBOARD_QUERY_COLUMNS)
    old = [{k: r.get(k) for k in columns} for r in old_rows]
    current = {'result': {'rows': [[r[k] for k in columns] for r in old if '2026-06-01' <= r['event_date'] <= result['metadata']['data_through']]}}
    end = date.fromisoformat(result['metadata']['data_through'])
    cutoff = end.replace(year=end.year - 1).isoformat()
    prior = {'result': {'rows': [[r[k] for k in columns] for r in old if '2025-06-01' <= r['event_date'] <= cutoff]}}
    baseline = project(current, prior, training_targets, people)
    rows = []
    team_map = {'prep': ('offline_market', '留学预备'), 'high': ('offline_market', '高中'),
                'university': ('offline_market', '大学'), 'virtual': ('online_private', None),
                'online': ('online_platform', None)}
    for period in result['periods']:
        if period['status'] == 'future':
            continue
        month_keys = [f'2026-{m:02d}' for m in range(6, 13)] + [f'2027-{m:02d}' for m in range(1, 6)]
        indexes = [i for i, m in enumerate(month_keys) if period['start_date'][:7] <= m <= period['through_date'][:7]]
        for team in period['teams']:
            if team['id'] not in team_map:
                continue
            tid, group = team_map[team['id']]
            bt = next(t for t in baseline['teams'] if t['team_id'] == tid)
            groups = [g for g in bt['groups'] if group is None or g['display_name'] == group]
            for kind in ('orders', 'cash'):
                before = round(sum(g['monthly_actuals'][kind][i] for g in groups for i in indexes), 2)
                after = team['lines']['training'][kind]['actual']
                difference = None if after is None else round(after-before, 2)
                rows.append({'label': f"{period['label']} · {team['name']} · 语培{'工单' if kind == 'orders' else '现金'}",
                             'baseline': before, 'current': after, 'difference': difference,
                             'status': 'matched' if difference == 0 else 'difference'})
    return {'rows': rows, 'notes': [
        '基线为同一Snapshot、同一截止日按现有V14 SQL和现有归属代码复算，不是抓取公网旧页。',
        '空团队顾问标签修正、跨部门产能独立展示等变化应逐项解释，不要求无条件强行对齐。',
        '大学留学按已确认八人贡献归属；与官方记分卡范围/截止日不一致的完成值不得互相覆盖。',
        '个人贡献允许多人共同归属，因此人员合计不能用来替代部门去重总量。',
    ]}


def build(args):
    from dashboard_product.management.facts import normalize_facts
    from dashboard_product.management.aggregate import aggregate
    from dashboard_product.management.breakdowns import enrich_periods
    from dashboard_product.management.enhancements import enhance_capacity, selection_views
    ws = Path(args.workspace).resolve()
    cfg = read(ws / 'Work/workspace.json')
    if cfg['current_snapshot_id'] != args.snapshot_id:
        raise ValueError('explicit snapshot must match workspace current pointer')
    if not re.fullmatch(r'run_[a-z0-9_-]{3,45}', args.run_id):
        raise ValueError('invalid run_id')
    as_of = args.as_of_date or shanghai_today()
    out = prepare_output(ws / 'Output/DashboardManagement' / args.run_id, ws, args.run_id, args.snapshot_id, as_of)
    guide = json.loads(subprocess.check_output([sys.executable, '-m', 'interfaces.casebook', 'guide', '--workspace', str(ws)], cwd=ROOT, text=True))
    if guide['next_step'] != 'analyze':
        raise ValueError('workspace is not ready for controlled analysis')
    receipts = []
    def fetch(path, params, suffix):
        records, receipt = query(path, params, suffix, args.run_id, args.snapshot_id,
                                 ws / cfg['current_warehouse_path'], out, out / '_query')
        receipts.append(receipt)
        return records
    coverage = fetch(HERE / 'sql/coverage.sql', [], 'coverage')[0]
    if not all(coverage[k] for k in ('orders_start', 'orders_end', 'cash_start', 'cash_end')):
        raise ValueError('missing source date coverage')
    through = min(date.fromisoformat(coverage[k]) for k in ('orders_end', 'cash_end'))
    through = min(through, date.fromisoformat(as_of) - timedelta(days=1))
    if not date(2026, 6, 1) <= through <= date(2027, 5, 31):
        raise ValueError('this dashboard covers FY27')
    coverage_start = min(date.fromisoformat(coverage[k]) for k in ('orders_start', 'cash_start'))
    training_rows, order_rows = [], []
    for i, (start, end) in enumerate(yearly_windows(coverage_start, through + timedelta(days=1))):
        training_rows.extend(fetch(HERE / 'sql/training_details.sql', [start, end], f'training_{i}'))
        order_rows.extend(fetch(HERE / 'sql/orders.sql', [start, end], f'orders_{i}'))
    people_path = ROOT / 'workspace_modeling/operations/people.json'
    abroad_people_path = ROOT / 'dashboard_product/config/offline_market_people.json'
    training_target_path = ROOT / 'dashboard_product/config/project_targets.json'
    abroad_target_path = ROOT / 'dashboard_product/config/offline_market_targets.json'
    online_target_path = ROOT / 'dashboard_product/online_team/config/study_abroad_targets.json'
    capacity_target_path = ROOT / 'dashboard_product/config/capacity_targets.json'
    reference_path = ws / 'Input/Reference/留学-FY26-资源表.xlsx'
    people, abroad_people = read(people_path), read(abroad_people_path)
    mapping = {r['source_adviser']: r['labeled_team'] for r in read(MAPPING)['mappings']}
    reference = load_work_order_reference(reference_path)
    facts, diagnostics = normalize_facts(training_rows, order_rows, people, abroad_people, mapping, reference)
    ids = [r['fact_id'] for r in facts]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate normalized fact identity')
    order_ids = [r['work_order_id'] for r in facts if r['metric'] == 'orders']
    if len(order_ids) != len(set(order_ids)):
        raise ValueError('one work order cannot enter both business lines')
    if any(r['business_line'] == 'abroad' and str(r['second_channel']).casefold() == 'ssc' for r in facts):
        raise ValueError('SSC must not enter management facts')
    targets = read(training_target_path)
    body = aggregate(facts, people, abroad_people, targets, read(abroad_target_path), read(online_target_path), through,
                     capacity_config=read(capacity_target_path))
    enrich_periods(body['periods'], facts, targets, read(abroad_target_path), read(online_target_path))
    enhance_capacity(body, facts, people, abroad_people, through, read(capacity_target_path))
    segments = selection_views(body['periods'], facts, people, targets)
    notes = [
        '团队按自然月，个人业绩按上月26日至本月25日；跨部门工单只计产能，不计个人考核完成。',
        '大学原本业务线工单目标不变，另一业务线目标为原月目标10%四舍五入；其他团队不强制下跨业务线目标。',
        '语培人头按被动新生正向报入现金的学员编号去重，不设1500元门槛；同一人员重复学员取最大分摊权重。',
        '留学现金及人头未接入；活动回收倍数仅以已接入的语培现金计算，不是利润率。',
        f"活动按当前Snapshot可用历史累计；工单起于{coverage['orders_start']}，现金起于{coverage['cash_start']}，均截至{through}，不保证覆盖活动完整生命周期。",
        '已确认SSC渠道统一排除；小语种不因目标差额被排除。',
        '已确认留学八人名单统一从JSON维护表读取，未识别人员的记录保留为待归属，不按学生年级猜团队。',
    ]
    public = {'schema_version': 'dashboard_rebuild.v1', 'metadata': {
        'title': '市场经营 · 管理融合看板', 'snapshot_id': args.snapshot_id, 'run_id': args.run_id,
        'data_through': through.isoformat(), 'coverage_start': coverage_start.isoformat(),
        'capacity_start': '2026-06-01', 'orders_coverage_start': coverage['orders_start'],
        'cash_coverage_start': coverage['cash_start'],
        'created_at': datetime.now(timezone.utc).isoformat(), 'notes': notes}, **body}
    old_rows = fetch(ROOT / 'dashboard_product/online_team/baseline/dashboard_actuals_v14.sql',
                     ['2025-06-01', (through + timedelta(days=1)).isoformat()], 'baseline')
    public['reconciliation'] = reconciliation(public, old_rows, people, targets)
    public['reconciliation']['notes'].extend([
        '同一留学工单同时满足线上渠道和大学八人认领时，部门优先归大学留学；来源仍记线上，不重复计入线上平台部门。',
        '八人归属中的括号协作不作为主责认领；旧SQL可能抓取括号内姓名，相关差异需业务验收。',
    ])
    p1_abroad, _, _ = study_facts([r for r in order_rows if not r.get('source_team')], mapping, reference)
    for period in public['periods']:
        if not period.get('through_date'):
            continue
        before = sum(r['value'] for r in p1_abroad if period['start_date'] <= r['event_date'] <= period['through_date'])
        after = next(t for t in period['teams'] if t['id'] == 'online')['lines']['abroad']['orders']['actual']
        public['reconciliation']['rows'].append({
            'label': f"{period['label']} · 线上留学 · 已验收P1口径（排除SSC）",
            'baseline': before, 'current': after, 'difference': None if after is None else after-before,
            'status': 'matched' if before == after else 'difference'})
    old_offline = fetch(HERE / 'sql/baseline_offline.sql',
                        ['2025-06-01', (through + timedelta(days=1)).isoformat()], 'baseline_offline')
    for period in public['periods']:
        if period['status'] == 'future':
            continue
        before = sum(float(r['actual_value']) for r in old_offline
                     if period['start_date'] <= r['event_date'] <= period['through_date'])
        after = next(t for t in period['teams'] if t['id'] == 'university')['lines']['abroad']['orders']['actual']
        public['reconciliation']['rows'].append({
            'label': f"{period['label']} · 大学留学 · 原八人线下口径",
            'baseline': before, 'current': after, 'difference': None if after is None else after-before,
            'status': 'matched' if before == after else 'difference'})
    scorecard_path = ws / 'Input/Reference/留学板块-官方记分卡.json'
    if scorecard_path.exists():
        scorecard = read(scorecard_path)
        public['metadata']['notes'].append('已读取官方记分卡；历史官方完成只作对照，不回写当前数仓明细或未接入的现金。')
        q1 = next(p for p in public['periods'] if p['id'] == 'Q1')
        for scope, team_id in [('online', 'online'), ('offline', 'university')]:
            official = next(r for r in scorecard[scope]['rows'] if r['period'] == 'FY27-Q1')['累计']['资源数']
            actual = next(t for t in q1['teams'] if t['id'] == team_id)['lines']['abroad']['orders']['actual']
            public['reconciliation']['rows'].append({'label': f'Q1 {scope} 留学 · 官方完成对照（范围可能不同）',
                'baseline': official, 'current': actual, 'difference': None if actual is None else actual-official,
                'status': 'matched' if actual == official else 'difference'})
    validate_public_data(public)
    sources = [Path(__file__), HERE / 'facts.py', HERE / 'aggregate.py', HERE / 'breakdowns.py', HERE / 'enhancements.py',
               ROOT / 'dashboard_product/refresh.py', ROOT / 'workspace_modeling/operations/personnel.py', people_path, abroad_people_path,
               training_target_path, abroad_target_path, online_target_path, capacity_target_path, MAPPING, reference_path,
               ws / 'Work/Bridge/reference.json',
               *sorted((HERE / 'web').glob('*')), *sorted((HERE / 'sql').glob('*.sql'))]
    if scorecard_path.exists():
        sources.append(scorecard_path)
    private = {'schema_version': 'management_details.v1', 'metadata': public['metadata'], 'records': facts,
               'query_receipts': receipts, 'diagnostics': diagnostics}
    write(out / 'details.json', private)
    write(out / 'shared_result.json', {**public, 'prep_high_selections': segments, 'query_receipts': receipts, 'diagnostics': diagnostics,
        'source_hashes': {source_label(p, ws): sha(p) for p in sources},
        'details_ref': {'path': 'details.json', 'sha256': sha(out / 'details.json'), 'record_count': len(facts)}})
    write(out / 'reconciliation.json', public['reconciliation'])
    report = ['# P2 同窗对数', '', f'Snapshot：{args.snapshot_id}；截止：{through}', '',
              '| 项目 | 旧值 | 新值 | 差异 |', '| --- | ---: | ---: | ---: |']
    report.extend(f"| {r['label']} | {r['baseline']} | {r['current']} | {r['difference']} |" for r in public['reconciliation']['rows'] if r['status'] != 'matched')
    report.extend(['', *public['reconciliation']['notes'], '', *notes])
    (out / 'reconciliation.md').write_text('\n'.join(report)+'\n', encoding='utf-8')
    view_data = presentation_data({key: value for key, value in public.items() if key != 'reconciliation'})
    view_data['metadata'].pop('notes', None)
    for period in view_data['periods']:
        period.pop('countries', None)
    site_data = {**view_data, 'periods': [{**period, 'teams': [t for t in period['teams']
                                                            if t['id'] in {'total','virtual','online'}]}
                                        for period in view_data['periods']]}
    write_site_json(out / 'site/data.json', site_data)
    for asset in (HERE / 'web').iterdir():
        if asset.is_file() and asset.suffix in ('.html', '.css', '.js'):
            shutil.copy2(asset, out / 'site' / asset.name)
    nav_js = (HERE / 'web/suite-nav.js').read_text(encoding='utf-8')
    nav_css = (HERE / 'web/suite-nav.css').read_text(encoding='utf-8')
    for name in ('app.js','boards.js'):
        asset = out / 'site' / name
        shared_js = nav_js + '\n' + (HERE / 'web/flat-tables.js').read_text(encoding='utf-8')
        if name == 'app.js': shared_js += '\n' + (HERE / 'web/capacity-view.js').read_text(encoding='utf-8')
        asset.write_text(shared_js + '\n' + asset.read_text(encoding='utf-8'), encoding='utf-8')
    for name in ('styles.css','boards.css'):
        asset = out / 'site' / name
        extra_css = nav_css + '\n' + (HERE / 'web/flat-tables.css').read_text(encoding='utf-8')
        if name == 'styles.css': extra_css += '\n' + (HERE / 'web/capacity-view.css').read_text(encoding='utf-8')
        asset.write_text(asset.read_text(encoding='utf-8') + '\n' + extra_css, encoding='utf-8')
    exported = export_site(out / 'site', out / 'index.html')
    departments = [export_department(out, view_data, 'university', {'university'})]
    segment_payloads = {}
    for mask, period_data in segments.items():
        cleaned = presentation_data(period_data)
        for p in cleaned: p.pop('countries', None)
        payload = {'schema_version': view_data['schema_version'], 'metadata': view_data['metadata'], 'periods': cleaned}
        segment_payloads[mask] = payload
        write_site_json(out / 'site' / f'prep_high.{mask}.data.json', payload)
    full_prep = {**segment_payloads['7'], 'selection_views': segment_payloads}
    departments.append(export_department(out, full_prep, 'prep_high', {'prep_high'}))
    # Local multi-file preview loads only the chosen precomputed selection.
    write_site_json(out / 'site/prep_high.data.json', segment_payloads['7'])
    from dashboard_product.online_team.build import build as build_online
    online_id = args.run_id + '_online'
    online_result = build_online(argparse.Namespace(workspace=ws, snapshot_id=args.snapshot_id,
                                  run_id=online_id, as_of_date=as_of, output_dir=None))
    online_dir = Path(online_result['output_dir'])
    export_site(online_dir / 'site', online_dir / 'online_market_special.html')
    online_html = (online_dir / 'online_market_special.html').read_text(encoding='utf-8')
    online_html = online_html.replace('<body>', '<body data-page="online">', 1)
    online_html = online_html.replace('</head>', '<style>' + nav_css + '</style></head>', 1)
    online_html = online_html.replace('</body>', '<script>' + nav_js + '</script></body>', 1)
    (out / 'site/online.html').write_text(online_html, encoding='utf-8')
    (out / 'online.html').write_text(online_html, encoding='utf-8')
    write(out / 'online_reference.json', {'run_id': online_id, 'snapshot_id': args.snapshot_id,
          'data_through': online_result['data_through'], 'sha256': sha(out / 'online.html')})
    return {'status': 'built', 'output_dir': str(out), 'snapshot_id': args.snapshot_id,
            'data_through': through.isoformat(), 'facts': len(facts), 'periods': len(public['periods']),
            'activities': len(public['activities']), 'diagnostics': diagnostics, 'html': exported,
            'department_pages': departments}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', type=Path, default=ROOT / 'customers/bi_operations')
    p.add_argument('--snapshot-id', required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--as-of-date')
    print(json.dumps(build(p.parse_args()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
