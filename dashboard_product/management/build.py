"""Build locally from explicit BI and isolated study-abroad Snapshots."""
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
    source_label,
)
from dashboard_product.online_team.export import export_site, validate_public_data

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


def _confirmed_adviser_lists(mapping_config):
    mappings = mapping_config['mappings']
    return (
        [row['source_adviser'] for row in mappings if row['labeled_team'] == '留学'],
        [row['source_adviser'] for row in mappings if row['labeled_team'] == '留学预备'],
    )


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


def reconciliation(result, old_rows, people, training_targets, facts):
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
                confirmed_delta = 0
                if kind == 'cash':
                    for fact in facts:
                        if (fact.get('team_override_reason') and fact['metric'] == 'cash'
                                and period['start_date'] <= fact['event_date'] <= period['through_date']
                                and (group is None or fact.get('business_group') == group)):
                            confirmed_delta += fact['value'] * (
                                int(fact.get('team_id') == tid) - int(fact.get('team_before_override') == tid))
                confirmed_delta = round(confirmed_delta, 2)
                status = ('matched' if difference == 0 else 'confirmed_change'
                          if confirmed_delta != 0 and difference == confirmed_delta else 'difference')
                rows.append({'label': f"{period['label']} · {team['name']} · 语培{'工单' if kind == 'orders' else '现金'}",
                             'baseline': before, 'current': after, 'difference': difference,
                             'status': status,
                             'reason': '用户确认的逐笔现金团队归属调整' if status == 'confirmed_change' else ''})
    return {'rows': rows, 'notes': [
        '基线为同一Snapshot、同一截止日按现有V14 SQL和现有归属代码复算，不是抓取公网旧页。',
        '空团队顾问标签修正、跨部门产能独立展示等变化应逐项解释，不要求无条件强行对齐。',
        '线下留学按已确认渠道范围汇总，不以在职人员名单限制历史完成；官方历史与当前范围不可直接互相覆盖。',
        '个人贡献允许多人共同归属，因此人员合计不能用来替代部门去重总量。',
    ]}


def build(args):
    from dashboard_product.management.facts import normalize_facts
    from dashboard_product.management.study_abroad_facts import load_study_abroad_facts
    from dashboard_product.management.aggregate import aggregate
    from dashboard_product.management.breakdowns import enrich_periods
    from dashboard_product.management.cash_share import attach_passive_cash_share
    from dashboard_product.management.market_totals import attach_market_orders
    from dashboard_product.management.enhancements import selection_views
    from dashboard_product.management.study_abroad_progress import attach_progress
    from dashboard_product.management.capacity_radar import build_radar
    from dashboard_product.management.personnel_contribution import (
        SOURCE_DIRECTORY, RESOURCE_FILENAME, TRANSFER_FILENAME,
        load_sources, build_contribution,
    )
    from dashboard_product.management.personnel_history import HISTORY_FILENAME, load_history, apply_history
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
    confirmed_mapping = read(MAPPING)
    study_advisers, prep_advisers = _confirmed_adviser_lists(confirmed_mapping)
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
    # Full source columns are needed only for the current notification windows.
    from workspace_modeling.operations.personnel import date_to_perf_month
    from dashboard_product.management.aggregate import _calendar_month_window
    personal_start, _ = _calendar_month_window({'kind': 'month', 'id': date_to_perf_month(through.isoformat())})
    attachment_start = min(through.replace(day=1), personal_start).isoformat()
    training_rows, order_rows = [], []
    for i, (start, end) in enumerate(yearly_windows(coverage_start, through + timedelta(days=1))):
        training_rows.extend(fetch(HERE / 'sql/training_details.sql',
                                  [start, end, attachment_start, study_advisers, prep_advisers], f'training_{i}'))
        order_rows.extend(fetch(HERE / 'sql/orders.sql', [start, end, attachment_start], f'orders_{i}'))
    new_student_cash_rows = fetch(
        HERE / 'sql/new_student_cash.sql',
        ['2026-06-01', (through + timedelta(days=1)).isoformat()], 'new_student_cash',
    )
    people_path = ROOT / 'workspace_modeling/operations/people.json'
    abroad_people_path = ROOT / 'dashboard_product/config/offline_market_people.json'
    training_target_path = ROOT / 'dashboard_product/config/project_targets.json'
    abroad_target_path = ROOT / 'dashboard_product/config/offline_market_targets.json'
    online_target_path = ROOT / 'dashboard_product/online_team/config/study_abroad_targets.json'
    reference_path = ws / 'Input/Reference/留学-FY26-资源表.xlsx'
    people, abroad_people = read(people_path), read(abroad_people_path)
    mapping = {r['source_adviser']: r['labeled_team'] for r in confirmed_mapping['mappings']}
    cash_override_path = ROOT / 'dashboard_product/config/confirmed_cash_team_overrides.json'
    facts, diagnostics = normalize_facts(training_rows, order_rows, people, abroad_people, mapping,
                                         cash_team_overrides=read(cash_override_path))
    study_source = load_study_abroad_facts(workspace=ws,
        snapshot_id=args.study_abroad_snapshot_id, run_id=args.run_id + '_study', as_of_date=as_of)
    study_identity = {'snapshot_id': args.study_abroad_snapshot_id,
                      'source_sha256': study_source['coverage']['source_sha256']}
    study_identity_path = out / '_study_abroad_identity.json'
    if study_identity_path.exists() and read(study_identity_path) != study_identity:
        raise ValueError('output directory belongs to a different study-abroad source')
    write(study_identity_path, study_identity)
    facts.extend(study_source['facts'])
    receipts.extend(study_source['query_receipts'])
    diagnostics['study_abroad_source'] = study_source['diagnostics']
    abroad_source = study_source['coverage']
    ids = [r['fact_id'] for r in facts]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate normalized fact identity')
    order_ids = [r['work_order_id'] for r in facts if r['metric'] == 'orders' and r.get('work_order_id')]
    if len(order_ids) != len(set(order_ids)):
        raise ValueError('one work order cannot enter both business lines')
    targets = read(training_target_path)
    body = aggregate(facts, people, abroad_people, targets, read(abroad_target_path), read(online_target_path), through, abroad_source=abroad_source)
    personnel_resource_path = ws / SOURCE_DIRECTORY / RESOURCE_FILENAME
    personnel_transfer_path = ws / SOURCE_DIRECTORY / TRANSFER_FILENAME
    from data_acquisition.jobs.study_abroad_snapshot_history import load_normalized_history
    personnel_standard = load_normalized_history(ws, args.study_abroad_snapshot_id, args.run_id + '_personnel')
    personnel_sources = load_sources(personnel_resource_path, personnel_transfer_path,
                                    normalized_source=personnel_standard,
                                    normalized_source_hashes={str(path): sha(path) for path in study_source['source_paths']})
    history_receipts = personnel_standard['source_metadata']
    for kind, receipt in history_receipts['query_receipts'].items():
        receipts.append({'schema_version': 'controlled_query_result.v2', 'status': 'passed',
                         'snapshot_id': args.study_abroad_snapshot_id,
                         'run_id': history_receipts['query_run_ids'][kind], 'receipt': receipt})
    personnel_months = [period['id'] for period in body['periods']
                        if re.fullmatch(r'\d{4}-\d{2}', period['id']) and period['id'] <= as_of[:7]]
    personnel_coverage = {**coverage, 'orders_end': min(coverage['orders_end'], through.isoformat()),
                          'cash_end': min(coverage['cash_end'], through.isoformat())}
    body['capacity'], personnel_details = build_contribution(
        facts, order_rows, people, abroad_people, personnel_sources, personnel_months, personnel_coverage)
    personnel_history_path = ws / SOURCE_DIRECTORY / HISTORY_FILENAME
    personnel_history = load_history(personnel_history_path)
    apply_history(body['capacity'], personnel_history)
    capacity_target_path = ROOT / 'dashboard_product/config/capacity_targets.json'
    body['capacity']['radar'] = {'start_date': '2026-06-01', 'through_date': through.isoformat(),
        'people': build_radar(facts, people, abroad_people, through, read(capacity_target_path))}
    if personnel_history is not None:
        personnel_details['history'] = personnel_history
    enrich_periods(body['periods'], facts, targets, read(abroad_target_path), read(online_target_path))
    attach_progress(body['periods'])
    old_rows = fetch(HERE / 'sql/baseline_training.sql',
                     ['2025-06-01', (through + timedelta(days=1)).isoformat()], 'baseline')
    market_order_rows = fetch(HERE / 'sql/market_orders.sql',
                              ['2025-06-01', (through + timedelta(days=1)).isoformat()], 'market_orders')
    attach_market_orders(body['periods'], market_order_rows)
    attach_passive_cash_share(body['periods'], new_student_cash_rows)
    segments = selection_views(body['periods'], facts, people, targets)
    notes = [
        '市场总盘工单按原被动有效工单范围统计，包含业务组暂无法拆分；业务线按已确认范围独立统计，不与总盘相加。',
        '团队按自然月，个人业绩按上月26日至本月25日；线下跨部门工单只计产能，线上虚拟人个人工单和现金按活动、录入人、描述中的姓名独立认领，不改团队归属。',
        '大学原本业务线工单目标不变，另一业务线目标为原月目标10%四舍五入；其他团队不强制下跨业务线目标。',
        '语培人头按被动新生正向报入现金的学员编号去重，不设1500元门槛；同一人员重复学员取最大分摊权重。',
        '留学资源与毛签消费独立留学仓，替换旧BI留学来源；小语种计入留学专项。签约人数按客户ID/学员编号分别去重，跨系统不合成唯一人数；活动现金按各来源实际覆盖，不是利润率。',
        f"活动按当前Snapshot可用历史累计；工单起于{coverage['orders_start']}，现金起于{coverage['cash_start']}，均截至{through}，不保证覆盖活动完整生命周期。",
        'SSC、国际市场及待确认归属仅计留学总盘并单列，不计线上/线下留学团队；国际市场不进入语培、虚拟人或个人归属。原BI语培市场总盘不因留学换仓改变。',
        '删除、回收工单计入总盘和各团队核算，但不计原个人业绩；现金资格不因关联工单状态改变。',
        '新版人员产能按自然月、语培/留学本业务拆分自创、接收和输出；删除／回收与死单独立切换，默认排除删除／回收、包含死单，仅影响工单及相关率；人员产能共创算法保留，主看板与通知留学资源和毛签改为独立仓事实。',
        '留学团队归属以本sheet市场归属人为权威，通过花名册/已确认映射拆分；现金不从关联资源覆盖归属。缺覆盖期间不补零，留学不做同比。',
    ]
    public = {'schema_version': 'dashboard_rebuild.v1', 'metadata': {
        'title': '市场经营 · 管理融合看板', 'snapshot_id': args.snapshot_id, 'run_id': args.run_id,
        'data_through': through.isoformat(), 'coverage_start': coverage_start.isoformat(),
        'capacity_start': '2026-06-01', 'orders_coverage_start': coverage['orders_start'],
        'cash_coverage_start': coverage['cash_start'],
        'created_at': datetime.now(timezone.utc).isoformat(), 'notes': notes,
        'study_abroad_source': abroad_source}, **body}
    public['reconciliation'] = reconciliation(public, old_rows, people, targets, facts)
    public['reconciliation']['notes'].append('旧BI留学对账路径已移除；新留学明细通过独立Snapshot回执核对，不与旧BI渠道范围强求一致。')
    scorecard_path = ws / 'Input/Reference/留学板块-官方记分卡.json'
    if scorecard_path.exists():
        scorecard = read(scorecard_path)
        public['metadata']['notes'].append('已读取官方记分卡；历史官方完成只作对照，不回写当前数仓明细或补齐独立留学仓未覆盖期间。')
        q1 = next(p for p in public['periods'] if p['id'] == 'Q1')
        for scope, team_id in [('online', 'online'), ('offline', 'university')]:
            official = next(r for r in scorecard[scope]['rows'] if r['period'] == 'FY27-Q1')['累计']['资源数']
            actual = next(t for t in q1['teams'] if t['id'] == team_id)['lines']['abroad']['orders']['actual']
            scope_note = '官方历史记分卡与当前独立留学仓覆盖期不同；不以9月样本补造Q1事实或同比。'
            public['reconciliation']['rows'].append({'label': f'Q1 {scope} 留学 · 官方历史参考（非同口径对数）',
                'baseline': official, 'current': actual, 'difference': None if actual is None else actual-official,
                'status': 'not_comparable', 'scope_note': scope_note})
    validate_public_data(public)
    sources = [Path(__file__), HERE / 'facts.py', HERE / 'aggregate.py', HERE / 'breakdowns.py', HERE / 'cash_share.py', HERE / 'market_totals.py', HERE / 'enhancements.py', HERE / 'study_abroad_progress.py', HERE / 'capacity_radar.py', capacity_target_path, HERE / 'personnel_contribution.py', HERE / 'personnel_history.py', HERE / 'notifications.py', HERE / 'online_view.py',
               ROOT / 'dashboard_product/refresh.py', ROOT / 'dashboard_product/online_team/build.py', ROOT / 'workspace_modeling/operations/personnel.py', ROOT / 'workspace_modeling/operations/study_abroad_source.py', people_path, abroad_people_path,
               training_target_path, abroad_target_path, online_target_path, cash_override_path, MAPPING, reference_path,
               ws / 'Work/Bridge/reference.json',
               *sorted((HERE / 'web').glob('*')),
               *sorted((ROOT / 'dashboard_product/online_team/web').glob('*')), *sorted((HERE / 'sql').glob('*.sql'))]
    if scorecard_path.exists():
        sources.append(scorecard_path)
    sources.extend(study_source['source_paths'])
    sources.extend(Path(path) for path in personnel_sources['source_hashes'])
    if personnel_history is not None:
        sources.append(personnel_history_path)
    from dashboard_product.management.notifications import build_notifications
    from dashboard_product.management.online_view import online_view
    notifications = build_notifications(public, facts, people, abroad_people)
    notifications['metadata'] = {**public['metadata'], 'as_of_date': as_of,
                                 'preview_only': True}
    write(out / 'notifications.json', notifications)
    online_data = online_view(public, facts, read(online_target_path))
    write(out / 'online_shared_result.json', online_data)
    private = {'schema_version': 'management_details.v1', 'metadata': public['metadata'], 'records': facts,
               'personnel_contribution': personnel_details,
               'query_receipts': receipts, 'diagnostics': diagnostics}
    write(out / 'details.json', private)
    write(out / 'shared_result.json', {**public, 'prep_high_selections': segments, 'query_receipts': receipts, 'diagnostics': diagnostics,
        'source_hashes': {source_label(p, ws): sha(p) for p in sources},
        'notifications_ref': {'path': 'notifications.json', 'sha256': sha(out / 'notifications.json')},
        'online_ref': {'path': 'online_shared_result.json', 'sha256': sha(out / 'online_shared_result.json')},
        'details_ref': {'path': 'details.json', 'sha256': sha(out / 'details.json'), 'record_count': len(facts)}})
    write(out / 'reconciliation.json', public['reconciliation'])
    report = ['# P2 同窗对数', '', f'Snapshot：{args.snapshot_id}；截止：{through}', '',
              '| 项目 | 参考值 | 当前值 | 算术差额 | 状态 |', '| --- | ---: | ---: | ---: | --- |']
    report.extend(f"| {r['label']} | {r['baseline']} | {r['current']} | {r['difference']} | {'非同口径，不代表漏单' if r['status'] == 'not_comparable' else '已确认归属调整' if r['status'] == 'confirmed_change' else '待核差异'} |" for r in public['reconciliation']['rows'] if r['status'] != 'matched')
    report.extend(['', *[r['scope_note'] for r in public['reconciliation']['rows'] if r.get('scope_note')]])
    report.extend(['', *public['reconciliation']['notes'], '', *notes])
    (out / 'reconciliation.md').write_text('\n'.join(report)+'\n', encoding='utf-8')
    view_data = presentation_data({key: value for key, value in public.items() if key != 'reconciliation'})
    # 新页的null区分未接入与已接入的真实0；不能沿用其他页省略可选字段的序列化。
    view_data['capacity'] = public['capacity']
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
        if name == 'app.js': shared_js += '\n' + (HERE / 'web/capacity-view.js').read_text(encoding='utf-8') + '\n' + (HERE / 'web/capacity-radar.js').read_text(encoding='utf-8')
        asset.write_text(shared_js + '\n' + asset.read_text(encoding='utf-8'), encoding='utf-8')
    for name in ('styles.css','boards.css'):
        asset = out / 'site' / name
        extra_css = nav_css + '\n' + (HERE / 'web/flat-tables.css').read_text(encoding='utf-8')
        if name == 'styles.css': extra_css += '\n' + (HERE / 'web/capacity-view.css').read_text(encoding='utf-8') + '\n' + (HERE / 'web/capacity-radar.css').read_text(encoding='utf-8')
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
    online_dir = out / 'packages/online'
    online_dir.mkdir(parents=True, exist_ok=True)
    online_web = ROOT / 'dashboard_product/online_team/web'
    for asset in ('index.html', 'styles.css', 'app.js'):
        shutil.copy2(online_web / asset, online_dir / asset)
    write_site_json(online_dir / 'data.json', online_data)
    export_site(online_dir, out / 'online.html')
    online_html = (out / 'online.html').read_text(encoding='utf-8')
    online_html = online_html.replace('<body>', '<body data-page="online">', 1)
    online_html = online_html.replace('</head>', '<style>' + nav_css + '</style></head>', 1)
    online_html = online_html.replace('</body>', '<script>' + nav_js + '</script></body>', 1)
    (out / 'site/online.html').write_text(online_html, encoding='utf-8')
    (out / 'online.html').write_text(online_html, encoding='utf-8')
    write(out / 'online_reference.json', {'run_id': args.run_id, 'snapshot_id': args.snapshot_id,
          'data_through': through.isoformat(), 'source': 'same_management_batch', 'sha256': sha(out / 'online.html')})
    return {'status': 'built', 'output_dir': str(out), 'snapshot_id': args.snapshot_id,
            'data_through': through.isoformat(), 'facts': len(facts), 'periods': len(public['periods']),
            'activities': len(public['activities']), 'diagnostics': diagnostics, 'html': exported,
            'department_pages': departments}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', type=Path, default=ROOT / 'customers/bi_operations')
    p.add_argument('--snapshot-id', required=True)
    p.add_argument('--study-abroad-snapshot-id', required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--as-of-date')
    print(json.dumps(build(p.parse_args()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
