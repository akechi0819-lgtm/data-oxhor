"""管理业务同批计算入口；旧页面与影子查询库复用同一组已验证规则。"""
from __future__ import annotations
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
import json
import re
import subprocess
import sys
from dashboard_product.online_team.build import (ROOT, MAPPING, read, write, sha, query, prepare_output, shanghai_today, source_label)
from dashboard_product.online_team.export import validate_public_data
HERE = Path(__file__).resolve().parent

def yearly_windows(start, end):
    while start < end:
        next_start = min(end, date(start.year + 1, 1, 1))
        yield start.isoformat(), next_start.isoformat()
        start = next_start


def _confirmed_adviser_lists(mapping_config):
    mappings = mapping_config['mappings']
    return (
        [row['source_adviser'] for row in mappings if row['labeled_team'] == '留学'],
        [row['source_adviser'] for row in mappings if row['labeled_team'] == '留学预备'],
    )


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


def calculate(args, *, output_area="DashboardManagement"):
    from dashboard_product.management.facts import normalize_facts
    from dashboard_product.management.study_abroad_facts import load_study_abroad_facts
    from dashboard_product.management.aggregate import aggregate
    from dashboard_product.management.breakdowns import enrich_periods
    from dashboard_product.management.cash_share import attach_passive_cash_share
    from dashboard_product.management.market_totals import attach_market_orders
    from dashboard_product.management.enhancements import selection_views
    from dashboard_product.management.study_abroad_progress import attach_progress
    from dashboard_product.management.team_scopes import attach_team_scope_views
    from dashboard_product.management.capacity_radar import build_radar
    from dashboard_product.management.personnel_contribution import (
        SOURCE_DIRECTORY, RESOURCE_FILENAME,
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
    out = prepare_output(ws / 'Output' / output_area / args.run_id, ws, args.run_id, args.snapshot_id, as_of)
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
                                  [start, end, attachment_start, study_advisers, prep_advisers, ['主动','被动']], f'training_{i}'))
        order_rows.extend(fetch(HERE / 'sql/orders.sql', [start, end, attachment_start], f'orders_{i}'))
    all_training_rows = training_rows
    training_rows = [r for r in all_training_rows if r['acquisition_mode'] == '被动']
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
    # 范围切换只筛事实，不截断现金关联工单的渠道证据；全范围归一也供P2复用。
    scope_training_facts, _ = normalize_facts(all_training_rows, order_rows, people, abroad_people, mapping,
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
    # 经营原始团队白名单不适用于个人历史资格，保留确认的空团队留学预备例外。
    person_facts, personal_diagnostics = normalize_facts(
        [r for r in training_rows if r['metric'] != 'cash' or r['actual_value'] > 0],
        order_rows, people, abroad_people, mapping, cash_team_overrides=read(cash_override_path),
        personal_qualification=True)
    person_facts.extend(study_source['facts'])
    diagnostics['personal_qualification'] = personal_diagnostics
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
    body = aggregate(facts, people, abroad_people, targets, read(abroad_target_path), read(online_target_path), through, abroad_source=abroad_source, person_facts=person_facts)
    personnel_resource_path = ws / SOURCE_DIRECTORY / RESOURCE_FILENAME
    from data_acquisition.jobs.study_abroad_snapshot_history import load_normalized_history
    personnel_standard = load_normalized_history(ws, args.study_abroad_snapshot_id, args.run_id + '_personnel')
    personnel_sources = load_sources(
        personnel_resource_path,
        normalized_source=personnel_standard,
        normalized_source_hashes={str(path): sha(path) for path in study_source['source_paths']},
    )
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
        person_facts, order_rows, people, abroad_people, personnel_sources, personnel_months, personnel_coverage)
    personnel_history_path = ws / SOURCE_DIRECTORY / HISTORY_FILENAME
    personnel_history = load_history(personnel_history_path)
    apply_history(body['capacity'], personnel_history)
    capacity_target_path = ROOT / 'dashboard_product/config/capacity_targets.json'
    body['capacity']['radar'] = {'start_date': '2026-06-01', 'through_date': through.isoformat(),
        'people': build_radar(person_facts, people, abroad_people, through, read(capacity_target_path))}
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
    attach_team_scope_views(body['periods'], facts, market_order_rows, targets, new_student_cash_rows)
    segments = selection_views(body['periods'], facts, people, targets)
    notes = [
        '语培市场总盘按观远工单总看板的8类原始团队及被动工单统计，不以顾问推断补入空团队；保留全部工单状态。',
        '团队按自然月，个人业绩按上月26日至本月25日；线下跨部门工单只计产能，线上虚拟人个人工单和现金按活动、录入人、描述中的姓名独立认领，不改团队归属。',
        '大学原本业务线工单目标不变，另一业务线目标为原月目标10%四舍五入；其他团队不强制下跨业务线目标。',
        '语培经营人头按观远口径：筛选范围内按学员编号和班级编码汇总报入现金，金额绝对值达到1500元且报名人次为正，按学员编号去重；个人业绩与产能维持原独立规则。',
        '留学工单、现金和人头消费独立留学仓，替换旧BI留学来源；小语种计入留学专项。客户ID/学员编号优先，缺编号按确认姓名规则同域暂定去重，跨系统不合成唯一人数；活动现金按各来源实际覆盖，不是利润率。',
        f"活动按当前Snapshot可用历史累计；工单起于{coverage['orders_start']}，现金起于{coverage['cash_start']}，均截至{through}，不保证覆盖活动完整生命周期。",
        'SSC及待确认归属只计留学总盘，不计线上/线下留学团队；国际市场资源按真实来源标记进入人员产能，SSC和unassigned范围保持既定规则；语培市场总盘不混入已确认留学工单。',
        '删除、回收工单计入总盘和各团队核算，但不计原个人业绩；现金资格不因关联工单状态改变。',
        '新版人员产能按自然月、语培/留学本业务拆分自创、接收和输出；BI一级渠道“双分”标记留学到语培，留学Snapshot国际市场标记语培到留学，关联现金保留签约/实缴本行归属；删除／回收与死单独立切换，默认排除删除／回收、包含死单，仅影响工单及相关率；主看板与通知留学工单、现金及人头消费独立仓事实。',
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
    sources = [Path(__file__), HERE / 'facts.py', HERE / 'aggregate.py', HERE / 'breakdowns.py', HERE / 'cash_share.py', HERE / 'market_totals.py', HERE / 'team_scopes.py', HERE / 'enhancements.py', HERE / 'study_abroad_progress.py', HERE / 'capacity_radar.py', capacity_target_path, HERE / 'personnel_contribution.py', HERE / 'personnel_history.py', HERE / 'notifications.py', HERE / 'online_view.py',
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
    online_data = online_view(public, facts, read(online_target_path), order_facts=scope_training_facts)
    from dashboard_product.management.advertising_costs import attach_advertising
    receipts.append(attach_advertising(online_data, facts, ws, args.snapshot_id, args.run_id, out,
                                     order_facts=scope_training_facts))
    sources.extend([HERE/'advertising_costs.py', HERE/'advertising_sources.py', HERE/'platforms.py', HERE/'sql/advertising_rollup.sql'])
    expense_manifest = ws/'Input/AdvertisingCosts/sources.json'
    if expense_manifest.exists():
        sources.append(expense_manifest)
    return dict(out=out, workspace=ws, public=public, online_data=online_data,
                facts=facts, person_facts=person_facts, personnel_details=personnel_details, receipts=receipts,
                diagnostics=diagnostics, segments=segments, notifications=notifications,
                sources=sources, training_rows=training_rows, order_rows=order_rows,
                market_order_rows=market_order_rows, new_student_cash_rows=new_student_cash_rows,
                people=people, abroad_people=abroad_people, coverage=coverage,
                all_training_rows=all_training_rows, scope_training_facts=scope_training_facts,
                through=through, coverage_start=coverage_start)
