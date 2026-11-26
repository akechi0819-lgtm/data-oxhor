"""单仓发布的身份、Superset 元数据及原子切换；不采集或发送通知。"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from data_platform.query.evidence import resolve_file


DATABASE_NAME = '市场经营 · 2026-10-22独立批次'
LABEL_COLORS = {'同期现金': '#5AC189', '本期现金': '#454E7C',
                '目标现金': '#1FA8C9', '语培': '#1FA8C9', '留学及小语种': '#454E7C'}


def load_release(library):
    library = Path(library).resolve(strict=True)
    release = json.loads((library/'release.json').read_bytes())
    if release.get('schema_version') != 'sql_warehouse_release.v1':
        raise ValueError('单仓发布合同无效')
    candidate_path = resolve_file(library, release['candidate'])
    if candidate_path != library/'candidate.json':
        raise ValueError('候选描述路径无效')
    candidate = json.loads(candidate_path.read_bytes())
    if (candidate.get('schema_version') != 'sql_warehouse_candidate.v1'
            or release['candidate']['sha256'] != release['candidate_sha256']
            or candidate['database']['sha256'] != release['database_sha256']
            or candidate['batch_id'] != release['batch_id']
            or candidate['snapshots'] != release['snapshots']
            or candidate['as_of_date'] != release['as_of_date']
            or candidate['through_date'] != release['coverage']['data_through']):
        raise ValueError('单仓发布身份不匹配')
    database = resolve_file(library, candidate['database'])
    if database != library/'warehouse.duckdb':
        raise ValueError('单仓数据库路径无效')
    return release, candidate, database


def version(library, database):
    release, candidate, _ = load_release(library)
    with database.get_sqla_engine() as engine:
        with engine.connect() as con:
            batch = con.exec_driver_sql('SELECT batch_id FROM meta.identity').scalar()
    return {'batch_id': batch, 'manifest_batch_id': candidate['batch_id'],
            'release': Path(library).resolve().parent.name,
            'coverage': release['coverage'], 'matched': batch == candidate['batch_id'],
            'storage_mode': 'sql_warehouse'}


def metadata_snapshot():
    from superset import db
    from superset.models.core import Database
    from superset.models.dashboard import Dashboard
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.slice import Slice
    from dashboard_product.shadow_bi.p4.roi_dashboard import CHARTS, table_name
    database = db.session.query(Database).filter_by(database_name=DATABASE_NAME).one()
    dashboard = db.session.query(Dashboard).filter_by(slug='shadow-bi-native').one()
    tables = db.session.query(SqlaTable).filter_by(database_id=database.id).all()
    retired_ids = [table.id for table in tables if table.table_name.endswith(' · SSC · 留学就地摘要')]
    retired_charts = (db.session.query(Slice).filter(
        Slice.datasource_type == 'table', Slice.datasource_id.in_(retired_ids)).all()
        if retired_ids else [])
    charts = {chart.id: chart for chart in [*dashboard.slices, *retired_charts]}
    roi_tables = {table_name(role) for role, _, _ in CHARTS.values()}
    return {'database_id': database.id, 'sqlalchemy_uri': database.sqlalchemy_uri,
            'extra': database.extra, 'dashboard_id': dashboard.id,
            'position_json': dashboard.position_json, 'json_metadata': dashboard.json_metadata,
            'dataset_sql': {str(table.id): table.sql for table in tables},
            'dataset_names': {str(table.id): table.table_name for table in tables},
            'column_names': {str(column.id): column.column_name for table in tables for column in table.columns},
            'roi_dataset_ids': [table.id for table in tables if table.table_name in roi_tables],
            'chart_params': {str(chart.id): chart.params for chart in charts.values()},
            'chart_names': {str(chart.id): chart.slice_name for chart in charts.values()},
            'chart_viz_types': {str(chart.id): chart.viz_type for chart in charts.values()},
            'chart_ids': [chart.id for chart in dashboard.slices]}


def restore_metadata(snapshot):
    from superset import db
    from superset.models.core import Database
    from superset.models.dashboard import Dashboard
    from superset.connectors.sqla.models import SqlaTable, TableColumn
    from superset.models.slice import Slice
    database = db.session.get(Database, snapshot['database_id'])
    database.sqlalchemy_uri = snapshot['sqlalchemy_uri']
    database.extra = snapshot['extra']
    dashboard = db.session.get(Dashboard, snapshot['dashboard_id'])
    dashboard.position_json = snapshot['position_json']
    dashboard.json_metadata = snapshot['json_metadata']
    if 'chart_ids' in snapshot:
        dashboard.slices = [db.session.get(Slice, chart_id) for chart_id in snapshot['chart_ids']]
    for key, sql in snapshot['dataset_sql'].items():
        db.session.get(SqlaTable, int(key)).sql = sql
    for key, name in snapshot.get('dataset_names', {}).items():
        db.session.get(SqlaTable, int(key)).table_name = name
    for key, params in snapshot['chart_params'].items():
        db.session.get(Slice, int(key)).params = params
    for key, name in snapshot.get('chart_names', {}).items():
        db.session.get(Slice, int(key)).slice_name = name
    for key, viz_type in snapshot.get('chart_viz_types', {}).items():
        db.session.get(Slice, int(key)).viz_type = viz_type
    for dataset_id in snapshot.get('roi_dataset_ids', []):
        dataset = db.session.get(SqlaTable, dataset_id)
        for column in list(dataset.columns):
            if str(column.id) not in snapshot['column_names']:
                db.session.delete(column)
    for key, name in snapshot['column_names'].items():
        db.session.get(TableColumn, int(key)).column_name = name
    db.session.commit()


def _metadata_call(action, library=None, *, snapshot=None):
    # 正式元数据库使用 PostgreSQL peer authentication，须沿用 shadowbi 身份。
    command = ['runuser', '-u', 'shadowbi', '--preserve-environment', '--',
               sys.executable, '-m', 'dashboard_product.shadow_bi.p4.sql_release',
               '--metadata-action', action]
    if library is not None:
        command.append(str(library))
    result = subprocess.run(command, input=json.dumps(snapshot) if snapshot is not None else '',
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def configure_overview_group_filter(metadata, options_dataset_id, ignored_chart_ids,
                                    additional_chart_ids=(), positions=None):
    """只替换总览语培业务组控件，留学图表不接收该筛选。"""
    matches = [item for item in metadata['native_filter_configuration']
               if any(target.get('datasetId') == options_dataset_id
                      and target.get('column', {}).get('name') == '管理单元'
                      for target in item.get('targets', []))]
    if len(matches) != 1:
        raise ValueError('市场总览业务组筛选身份不唯一')
    item = matches[0]
    ignored = set(ignored_chart_ids)
    additional = set(additional_chart_ids)
    charts = (set(item['chartsInScope']) | additional) - ignored
    if positions is not None:
        chart_nodes = [node for node in positions.values()
                       if isinstance(node, dict) and node.get('type') == 'CHART']
        active = {node['meta']['chartId'] for node in chart_nodes}
        charts &= active
    if not ignored or not charts:
        raise ValueError('市场总览语培／留学筛选范围无效')
    item['name'] = '业务组'
    item['description'] = '语培按业务组汇总各渠道；留学及小语种保持市场总盘。'
    item['chartsInScope'] = sorted(charts)
    if positions is None:
        item['scope']['excluded'] = sorted((set(item['scope']['excluded']) | ignored) - additional)
    else:
        item['scope']['excluded'] = sorted(active - charts)
        item['tabsInScope'] = sorted({parent for node in chart_nodes
                                     if node['meta']['chartId'] in charts
                                     for parent in node.get('parents', [])
                                     if positions.get(parent, {}).get('type') == 'TAB'})


def _without_ssc_title(name):
    return name.replace('业务组同期对比 · 含 SSC', '业务组同期对比').replace(
        '留学专项 · 国际市场 / SSC / 待确认', '留学专项 · 国际市场 / 待确认')


def _remove_chart_from_layout(positions, metadata, chart_id):
    removed = {key for key, node in positions.items()
               if isinstance(node, dict) and node.get('type') == 'CHART'
               and node.get('meta', {}).get('chartId') == chart_id}
    if len(removed) != 1:
        raise ValueError('SSC图表在布局中缺失或不唯一')
    for key in removed:
        del positions[key]
    for node in positions.values():
        if isinstance(node, dict) and isinstance(node.get('children'), list):
            node['children'] = [child for child in node['children'] if child not in removed]
    empty_rows = {key for key, node in positions.items() if isinstance(node, dict)
                  and node.get('type') == 'ROW' and not node.get('children')}
    for key in empty_rows:
        del positions[key]
    for node in positions.values():
        if isinstance(node, dict) and isinstance(node.get('children'), list):
            node['children'] = [child for child in node['children'] if child not in empty_rows]
    for item in metadata.get('native_filter_configuration', []):
        for container, key in ((item, 'chartsInScope'), (item.get('scope', {}), 'excluded')):
            if key in container:
                container[key] = [value for value in container[key] if value != chart_id]


def _retire_ssc(tables, dashboard, positions, metadata, charts=None):
    retired = [table for table in tables if table.table_name.endswith(' · SSC · 留学就地摘要')]
    if retired:
        retired_ids = {table.id for table in retired}
        ssc_charts = [chart for chart in (charts if charts is not None else dashboard.slices)
                      if chart.datasource_type == 'table' and chart.datasource_id in retired_ids]
        attached = [chart for chart in dashboard.slices
                    if chart.datasource_type == 'table' and chart.datasource_id in retired_ids]
        if len(attached) > 1 or (len(dashboard.slices) == 93 and len(attached) != 1):
            raise ValueError('SSC看板图表身份不唯一')
        if attached:
            _remove_chart_from_layout(positions, metadata, attached[0].id)
            dashboard.slices.remove(attached[0])
        for chart in ssc_charts:
            chart.slice_name = f'archived_retired_chart_{chart.id}'
        for table in retired:
            table.sql = "SELECT NULL AS 期间, NULL AS 管理单元, NULL AS 工单, NULL AS \"现金（元）\", NULL AS 人头 WHERE FALSE"
            table.table_name = f'archived_retired_dataset_{table.id}'
    if len(dashboard.slices) != 92:
        raise ValueError('看板图表迁移数量不符')


def install_metadata(library, *, current_library=None):
    """更新 SQL、连接和日期文案；按发布合同调整市场总览筛选，保留对象身份及图表展示参数。"""
    from superset import db
    from superset.models.core import Database
    from superset.models.dashboard import Dashboard
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.slice import Slice
    from dashboard_product.shadow_bi.p35.expense_coverage import LIMITATION
    release, candidate, _ = load_release(library)
    catalogue = json.loads(resolve_file(Path(library), release['superset_catalogue']).read_bytes())
    if catalogue.get('schema_version') != 'sql_superset_catalogue.v1':
        raise ValueError('单仓数据集合同无效')
    entries = catalogue['datasets']
    if len(entries) != 167 or len({x['table_name'] for x in entries}) != 167:
        raise ValueError('必须包含158个数据集和9个筛选来源')
    database = db.session.query(Database).filter_by(database_name=DATABASE_NAME).one()
    dashboard = db.session.query(Dashboard).filter_by(slug='shadow-bi-native').one()
    positions = json.loads(dashboard.position_json)
    metadata = json.loads(dashboard.json_metadata)
    from dashboard_product.shadow_bi.p35.bootstrap_native import configure_overview_student_filter
    configure_overview_student_filter(metadata, positions, dashboard, database)
    tables = db.session.query(SqlaTable).filter_by(database_id=database.id).all()
    by_name = {_without_ssc_title(table.table_name): table for table in tables}
    if len(by_name) != len(tables) or not {x['table_name'] for x in entries} <= by_name.keys():
        raise ValueError('原数据集身份缺失或不唯一')
    dashboard = db.session.query(Dashboard).filter_by(slug='shadow-bi-native').one()
    positions = json.loads(dashboard.position_json)
    headers = [node for node in positions.values() if isinstance(node, dict)
               and node.get('type') == 'MARKDOWN'
               and '## 观近 · 市场经营' in node.get('meta', {}).get('code', '')]
    fees = [node for node in positions.values() if isinstance(node, dict)
            and node.get('type') == 'MARKDOWN'
            and LIMITATION in node.get('meta', {}).get('code', '')]
    if len(headers) != 1 or len(fees) != 1 or len(dashboard.slices) not in (92, 93):
        raise ValueError('原看板组件身份不符')
    if len(metadata['native_filter_configuration']) != 87:
        raise ValueError('原看板筛选身份不符')
    retired_ids = [table.id for table in tables if table.table_name.endswith(' · SSC · 留学就地摘要')]
    retired_charts = (db.session.query(Slice).filter(
        Slice.datasource_type == 'table', Slice.datasource_id.in_(retired_ids)).all()
        if retired_ids else [])
    _retire_ssc(tables, dashboard, positions, metadata, retired_charts)
    for table in tables:
        table.table_name = _without_ssc_title(table.table_name)
    for entry in entries:
        by_name[entry['table_name']].sql = entry['sql']
        for column in by_name[entry['table_name']].columns:
            column.column_name = column.column_name.replace('被动现金占新生收入', '被动现金占收入').replace(
                '新生现金固定分母', '现金固定分母')
    for chart in dashboard.slices:
        chart.slice_name = _without_ssc_title(chart.slice_name)
        chart.params = chart.params.replace('被动现金占新生收入', '被动现金占收入').replace(
            '新生现金固定分母', '现金固定分母')
    if catalogue.get('overview_filter_mode') == 'training_business_group':
        ignored = catalogue['overview_group_ignored_datasets']
        if not ignored or not set(ignored) <= by_name.keys():
            raise ValueError('市场总览留学数据集身份缺失')
        ignored_ids = {by_name[name].id for name in ignored}
        additional = catalogue['overview_group_additional_datasets']
        if not additional or not set(additional) <= by_name.keys():
            raise ValueError('市场总览语培学校数据集身份缺失')
        additional_ids = {by_name[name].id for name in additional}
        configure_overview_group_filter(
            metadata, by_name['p35_overview_options_1'].id,
            [chart.id for chart in dashboard.slices
             if chart.datasource_type == 'table' and chart.datasource_id in ignored_ids],
            [chart.id for chart in dashboard.slices
             if chart.datasource_type == 'table' and chart.datasource_id in additional_ids],
            positions)
    if catalogue.get('roi_dashboard') is True:
        from dashboard_product.shadow_bi.p4.roi_dashboard import install_roi_dashboard
        install_roi_dashboard(dashboard, by_name, positions, metadata)
    headers[0]['meta']['code'] = candidate['dashboard_coverage_note']
    fees[0]['meta']['code'] = release['expense_coverage_note']
    metadata['label_colors'] = LABEL_COLORS
    dashboard.position_json = json.dumps(positions, ensure_ascii=False)
    dashboard.json_metadata = json.dumps(metadata, ensure_ascii=False)
    database.sqlalchemy_uri = 'duckdb:///' + str(Path(current_library or library)/'warehouse.duckdb')
    extra = json.loads(database.extra or '{}')
    connect = extra.setdefault('engine_params', {}).setdefault('connect_args', {})
    connect['read_only'] = True
    connect.setdefault('config', {}).update(threads=1, memory_limit='1100MB',
                                           enable_external_access=False, lock_configuration=True)
    database.extra = json.dumps(extra)
    db.session.commit()
    return {'datasets': len(entries), 'charts': 92, 'filters': 87}


def _wait_health():
    for _ in range(60):
        if subprocess.run(['curl', '-fsS', 'http://127.0.0.1:18090/health'],
                          capture_output=True).returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError('看板服务未就绪')


def verify_http(target, audit):
    from dashboard_product.shadow_bi.p4.verify_server import session, payload
    from dashboard_product.shadow_bi.p3.catalog import AUDIT
    from data_platform.sql_candidate import query_candidate
    target, audit = Path(target), Path(audit)
    release, candidate, _ = load_release(target/'library')
    base = 'http://127.0.0.1:18090'
    client = session(AUDIT/'runtime/credentials.json', base=base)
    response = client.get(base+'/p4/version', timeout=30)
    response.raise_for_status()
    identity = response.json()
    if not identity['matched'] or identity['release'] != target.name or identity['batch_id'] != candidate['batch_id']:
        raise ValueError('新模式实际连接身份不符')
    client.headers['X-Shadow-BI-Release'] = target.name
    native = json.loads((AUDIT/'evidence/bootstrap.json').read_bytes())
    checks = []
    for number, scope in enumerate(('被动', '主动', '全部')):
        expected = query_candidate(candidate=target/'library', batch_id=candidate['batch_id'],
            sql="SELECT metric,actual,prior FROM business.team_metrics WHERE period_id='FY27' AND unit_id='total' AND business_line='training' AND acquisition_scope=?",
            parameters=[scope], run_id='run_sql_activate_scope_'+str(number), output_root=audit/'queries', max_rows=3)
        filters = [{'col': key, 'op': 'IN', 'val': [value]} for key, value in
                   {'期间': 'FY27', '管理单元': '市场总计', '语培统计范围': scope}.items()]
        response = client.post(base+'/api/v1/chart/data', json=payload(
            native['datasets']['native_overview_training'], ['指标', '本期完成', '上年同期'], filters), timeout=120)
        response.raise_for_status()
        results = response.json()['result']
        if any(item.get('error') for item in results):
            raise ValueError('新模式图表查询失败')
        displayed = {row['指标']: row for row in results[0]['data']}
        if len(expected['result']['rows']) != 3 or len(displayed) != 3:
            raise ValueError('关键指标缺行')
        for metric, actual, prior in expected['result']['rows']:
            label = {'orders': '工单', 'cash': '现金（元）', 'heads': '人头'}[metric]
            for key, value in [('本期完成', actual), ('上年同期', prior)]:
                text = displayed[label][key]
                if (text != '—' if value is None else abs(float(text.replace(',', ''))-float(value)) >= .005):
                    raise ValueError('关键显示值与单仓查询不同')
        checks.append({'scope': scope, 'rows': results[0]['data'], 'receipt': expected['receipt']})
    response = client.get(base+'/api/v1/dashboard/shadow-bi-native', timeout=30)
    response.raise_for_status()
    positions = json.loads(response.json()['result']['position_json'])
    notes = [node.get('meta', {}).get('code', '') for node in positions.values()
             if isinstance(node, dict) and node.get('type') == 'MARKDOWN']
    if candidate['dashboard_coverage_note'] not in notes or release['expense_coverage_note'] not in notes:
        raise ValueError('正式业务／费用日期与单仓不同')
    result = {'status': 'passed', 'identity': identity, 'metrics_compared': 18, 'checks': checks,
              'header_matches': True, 'expense_note_matches': True}
    catalogue = json.loads(resolve_file(target/'library', release['superset_catalogue']).read_bytes())
    if catalogue.get('roi_dashboard') is True:
        from dashboard_product.shadow_bi.p4.roi_dashboard import verify_roi_dashboard
        result['roi_dashboard'] = verify_roi_dashboard(
            client, base, positions, native['datasets'], candidate['through_date'][:7])
    return result


def verify_acceptance(library, release, *, contract_file=Path('/var/lib/shadow-bi/app/sql-contract.json')):
    acceptance = json.loads(resolve_file(Path(library), release['acceptance']).read_bytes())
    if acceptance.get('candidate_sha256') != release['candidate_sha256']:
        raise ValueError('验收回执与本批候选不匹配')
    fields = ('numbers_match', 'functions_match', 'interface_match')
    if acceptance.get('mode') != 'runtime_contract':
        if not all(acceptance.get(key) is True for key in fields):
            raise ValueError('数字、功能和界面三项尚未验收通过')
        return acceptance
    raw = Path(contract_file).read_bytes()
    contract = json.loads(raw)
    runtime = acceptance['runtime_contract']
    if (hashlib.sha256(raw).hexdigest() != acceptance['migration_acceptance']['sha256']
            or not all(contract.get(key) is True for key in fields)
            or runtime.get('status') != 'passed'
            or runtime.get('candidate_identity_passed') is not True
            or runtime.get('source_gates_passed') is not True
            or runtime.get('catalogue_sha256') != release['superset_catalogue']['sha256']
            or runtime['catalogue_sha256'] != contract['catalogue_sha256']):
        raise ValueError('日更SQL合同或本批来源校验未通过')
    return acceptance


def _activate(target, *, expected_current):
    """维护窗口内换数据和元数据；失败时恢复原元数据和 current。"""
    base = Path('/var/lib/shadow-bi')
    target = Path(target).resolve(strict=True)
    if target.parent != base/'releases':
        raise ValueError('单仓候选不在发布目录')
    release, candidate, _ = load_release(target/'library')
    if release['release_id'] != target.name:
        raise ValueError('单仓发布目录身份不符')
    verify_acceptance(target/'library', release)
    current = base/'current'
    old = current.resolve(strict=True)
    if old.name != expected_current:
        raise ValueError('正式版本已变化，必须重新同批核对')
    before = _metadata_call('snapshot')
    backup = base/'app'/'sql-cutover'/target.name
    backup.mkdir(parents=True, exist_ok=False)
    (backup/'metadata.json').write_text(json.dumps(before, ensure_ascii=False))
    (backup/'metadata.json').chmod(0o600)
    maintenance = Path('/run/shadow-bi-maintenance')
    maintenance.touch(mode=0o644)
    subprocess.run(['systemctl', 'stop', 'shadow-bi'], check=True)
    def point(path):
        next_path = base/'next'
        next_path.unlink(missing_ok=True)
        next_path.symlink_to(path)
        next_path.replace(current)
    try:
        point(target)
        _metadata_call('install', target/'library')
        subprocess.run(['systemctl', 'start', 'business-data-mcp-acl-sync.service'], check=True)
        subprocess.run(['systemctl', 'restart', 'business-data-mcp.service'], check=True)
        subprocess.run(['systemctl', 'start', 'shadow-bi'], check=True)
        _wait_health()
        verified = verify_http(target, backup)
        probe = subprocess.run(['runuser', '-u', 'business-mcp', '--',
            '/srv/business-data-mcp/venv/bin/python', '-m', 'business_data_mcp.deploy.verify_current',
            '--expected-release', target.name], text=True, capture_output=True, check=True,
            cwd='/srv/business-data-mcp', env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin',
                'HOME': '/var/lib/business-data-mcp', 'LANG': 'C.UTF-8',
                'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'PYTHONNOUSERSITE': '1'})
        mcp_verified = json.loads(probe.stdout.strip().splitlines()[-1])
        if mcp_verified.get('status') != 'passed' or mcp_verified.get('release') != target.name:
            raise ValueError('正式查询服务核验失败')
        verified['business_data_mcp'] = mcp_verified
        (backup/'verification.json').write_text(json.dumps(verified, ensure_ascii=False, indent=2))
        previous = base/'previous'
        previous.unlink(missing_ok=True)
        previous.symlink_to(old)
        maintenance.unlink()
        return {'status': 'activated', 'current': target.name, 'previous': old.name,
                'batch_id': candidate['batch_id'], 'verification': verified}
    except BaseException:
        subprocess.run(['systemctl', 'stop', 'shadow-bi'], check=True)
        point(old)
        _metadata_call('restore', snapshot=before)
        subprocess.run(['systemctl', 'start', 'business-data-mcp-acl-sync.service'], check=True)
        subprocess.run(['systemctl', 'restart', 'business-data-mcp.service'], check=True)
        subprocess.run(['systemctl', 'start', 'shadow-bi'], check=True)
        _wait_health()
        maintenance.unlink(missing_ok=True)
        raise


def activate(target, *, expected_current):
    with Path('/var/lib/shadow-bi/.foundation-candidate.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _activate(target, expected_current=expected_current)


def retire_previous(target, *, expected_previous):
    """新仓实测通过后移除明确的上一份 SQL 发布；原件和回执仍留本机。"""
    base = Path('/var/lib/shadow-bi')
    with (base/'.foundation-candidate.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = Path(target).resolve(strict=True)
        current = (base/'current').resolve(strict=True)
        previous_link = base/'previous'
        previous = previous_link.resolve(strict=True)
        if (target != current or current.parent != base/'releases'
                or previous.parent != current.parent or previous == current
                or previous.name != expected_previous):
            raise ValueError('退役对象与已验证发布指针不符')
        load_release(current/'library')
        old, _, _ = load_release(previous/'library')
        verified = json.loads((base/'app/sql-cutover'/current.name/'verification.json').read_bytes())
        if (old['release_id'] != expected_previous or verified.get('status') != 'passed'
                or verified.get('metrics_compared') != 18):
            raise ValueError('新仓尚无实际核验回执')
        names = {'candidate.json', 'warehouse.duckdb', 'notification-preview.json',
                 'release.json', 'superset-catalogue.json', 'landing-description.json', 'acceptance.json'}
        if (set(previous.iterdir()) != {previous/'library'}
                or set((previous/'library').iterdir()) != {previous/'library'/name for name in names}
                or any(path.is_symlink() or not path.is_file() for path in (previous/'library').iterdir())):
            raise ValueError('旧发布包含未核销内容，保留待检查')
        shutil.rmtree(previous)
        previous_link.unlink()
        return {'status': 'retired', 'current': current.name, 'removed': expected_previous,
                'warehouse_count_in_releases': len(list((base/'releases').glob('*/library/warehouse.duckdb')))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path, nargs='?')
    parser.add_argument('--expected-current')
    parser.add_argument('--metadata-action', choices=('snapshot', 'install', 'restore'))
    parser.add_argument('--retire-previous')
    args = parser.parse_args()
    if args.metadata_action:
        from superset.app import create_app
        app = create_app()
        with app.app_context():
            if args.metadata_action == 'snapshot':
                result = metadata_snapshot()
            elif args.metadata_action == 'install':
                if args.target is None:
                    parser.error('metadata install requires a library')
                result = install_metadata(args.target,
                    current_library=Path('/var/lib/shadow-bi/current/library'))
            else:
                restore_metadata(json.load(sys.stdin))
                result = {'status': 'restored'}
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.retire_previous:
        if args.target is None:
            parser.error('retirement requires the verified current target')
        print(json.dumps(retire_previous(args.target, expected_previous=args.retire_previous)))
        return
    if args.target is None or args.expected_current is None:
        parser.error('activation requires target and --expected-current')
    print(json.dumps(activate(args.target, expected_current=args.expected_current), ensure_ascii=False))


if __name__ == '__main__':
    main()
