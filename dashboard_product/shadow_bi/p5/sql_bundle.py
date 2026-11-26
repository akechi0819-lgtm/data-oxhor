"""封装单 SQL 数仓及必要运行元数据；不携带双基础库或原始客户文件。"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile

from data_platform.query.evidence import file_ref, resolve_file
from data_platform.query.service import describe_warehouse
from data_platform.sql_candidate import query_candidate


OPTION_SQL = {
 'p3_school_options': "SELECT DISTINCT COALESCE(dim1,'暂无归属') AS 学校 FROM business.dimension_metrics WHERE dimension_type='school' AND NULLIF(TRIM(dim1),'') IS NOT NULL",
 'p3_person_options': "SELECT DISTINCT name AS 人员 FROM business.personal_metrics WHERE NULLIF(TRIM(name),'') IS NOT NULL",
 'p3_person_month_options': "SELECT DISTINCT period_id AS 个人月份 FROM business.personal_windows WHERE regexp_matches(period_id,'^[0-9]{4}-[0-9]{2}$')",
 'p35_platform_group_options': "SELECT DISTINCT business_group AS 平台业务组 FROM business.scoped_advertising_rollup WHERE record_type='leaf' AND business_line='training' AND business_group IS NOT NULL",
 'p35_prep_period_options': "SELECT DISTINCT period_id AS 期间 FROM business.team_metrics WHERE starts_with(unit_id,'selection_') AND business_line='training' AND acquisition_scope='被动'",
 'p35_platform_options': "SELECT DISTINCT platform AS 平台 FROM business.scoped_advertising_rollup WHERE record_type='platform' AND platform IS NOT NULL",
 'p35_overview_options_0': "SELECT DISTINCT period_id AS 期间 FROM business.team_metrics WHERE unit_id IN ('total','virtual','online') AND acquisition_scope='被动'",
 'p35_overview_options_1': "SELECT group_label AS 管理单元 FROM (VALUES ('市场总计'),('高中'),('大学'),('留学预备')) AS options(group_label)",
 'p35_overview_student_options': "SELECT unnest(['全部','新生','老生']) AS 新老生",
}


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def prepare_release(*, candidate, workspace, release_id, output_dir, coverage_template, acceptance):
    from dashboard_product.shadow_bi.sql_warehouse.catalog import build_catalogue, catalogue_status
    from dashboard_product.shadow_bi.sql_warehouse.foundation import TABLES
    from dashboard_product.shadow_bi.p35.expense_coverage import format_coverage
    candidate, workspace, output_dir = map(lambda p: Path(p).resolve(), (candidate, workspace, output_dir))
    if not re.fullmatch(r'daily-[a-zA-Z0-9_-]{1,90}', release_id):
        raise ValueError('单仓发布名称无效')
    manifest = json.loads((candidate/'candidate.json').read_bytes())
    if manifest.get('schema_version') != 'sql_warehouse_candidate.v1':
        raise ValueError('单仓候选无效')
    resolve_file(candidate, manifest['database'])
    resolve_file(candidate, manifest['notification_preview'])
    output_dir.mkdir(parents=True, exist_ok=False)
    library = output_dir/release_id/'library'
    library.mkdir(parents=True)
    for name in ('candidate.json', 'warehouse.duckdb', 'notification-preview.json'):
        shutil.copyfile(candidate/name, library/name)
    catalogue = build_catalogue()
    if catalogue_status(catalogue)['status'] != 'pass':
        raise ValueError('单仓 SQL 数据集合同未通过')
    from dashboard_product.shadow_bi.p3.catalog import PAGES
    entries = [{'table_name': PAGES.get(item.page, '市场活动')+' · '+item.title, 'sql': item.sql}
               for item in catalogue.values() if item.sql and not item.unsupported]
    if len(entries) != 158:
        raise ValueError('单仓 SQL 数据集数量不符')
    entries += [{'table_name': key, 'sql': value} for key, value in OPTION_SQL.items()]
    overview_group_ignored_keys = {
        'overview_abroad_targets', 'native_overview_abroad_targets',
        'overview_supplemental',
        'overview_countries', 'overview_countries_child', 'native_overview_country_tree',
        'native_overview_abroad', 'native_overview_grades_abroad',
        'native_overview_schools_abroad', 'native_overview_channel_tree_abroad',
    }
    ignored_datasets = [
        PAGES.get(item.page, '市场活动')+' · '+item.title
        for item in catalogue.values()
        if item.key in overview_group_ignored_keys and item.sql and not item.unsupported
    ]
    _write(library/'superset-catalogue.json', {
        'schema_version': 'sql_superset_catalogue.v1',
        'roi_dashboard': True,
        'overview_filter_mode': 'training_business_group',
        'overview_group_ignored_datasets': ignored_datasets,
        'overview_group_additional_datasets': [
            PAGES.get(item.page, '市场活动')+' · '+item.title
            for item in catalogue.values() if item.key == 'native_overview_schools_training'
        ],
        'datasets': entries,
    })
    pointers = {
        'training': json.loads((workspace/'Work/workspace.json').read_bytes()),
        'study': json.loads((workspace/'Work/StudyAbroad/current.json').read_bytes()),
    }
    descriptions = {}
    for domain, snapshot_key, path_key, allowed in (
        ('training', 'training', 'current_warehouse_path', TABLES['training']),
        ('study', 'abroad', 'warehouse', TABLES['abroad']),
    ):
        snapshot = manifest['snapshots'][snapshot_key]
        description = describe_warehouse(warehouse=workspace/pointers[domain][path_key], snapshot_id=snapshot)
        description['relations'] = [item for item in description['relations']
                                   if item['schema'] == 'landing' and item['name'] in allowed]
        if len(description['relations']) != len(allowed):
            raise ValueError('原始公开表结构不完整')
        descriptions[domain] = description
    _write(library/'landing-description.json', descriptions)
    provenance = {}
    for response in manifest['source_queries']:
        receipt_path = resolve_file(candidate/'source-evidence'/response['run_id'], response['receipt'])
        receipt = json.loads(receipt_path.read_bytes())
        relations, sources = receipt['referenced_relations'], receipt['referenced_source_ids']
        if len(relations) != 1 or len(sources) != 1:
            raise ValueError('基础导入回执不是单表来源')
        domain = 'training' if response['snapshot_id'] == manifest['snapshots']['training'] else 'study'
        snapshot = manifest['snapshots']['training' if domain == 'training' else 'abroad']
        if response['snapshot_id'] != snapshot or receipt['snapshot_id'] != snapshot:
            raise ValueError('基础导入回执 Snapshot 身份不符')
        value = {'source_id': sources[0], 'snapshot_id': snapshot, 'domain': domain}
        if relations[0] in provenance and provenance[relations[0]] != value:
            raise ValueError('同一基础表来源不一致')
        provenance[relations[0]] = value
    expected = {'landing.'+name for names in TABLES.values() for name in names}
    if set(provenance) != expected:
        raise ValueError('基础表来源血缘不完整')
    fees = query_candidate(candidate=candidate, batch_id=manifest['batch_id'],
        sql='SELECT business_line,platform,CAST(MAX(end_date) AS VARCHAR),grain FROM business.expense_sources GROUP BY business_line,platform,grain ORDER BY business_line,platform,grain',
        run_id='run_sql_release_fee_note', output_root=output_dir/'evidence', max_rows=200)
    preview = json.loads((candidate/'notification-preview.json').read_bytes())
    source_coverage = next(message['source_coverage'] for message in preview['messages']
                           if message['business_line'] == 'abroad')
    coverage = deepcopy(coverage_template)
    coverage.update(data_through=manifest['through_date'], snapshot_id=manifest['snapshots']['training'],
                    study_abroad_source=source_coverage, run_id=manifest['batch_id'],
                    created_at=datetime.now(timezone.utc).isoformat())
    reference = 'Work/Bridge/reference.json'
    semantics = {reference: hashlib.sha256((workspace/reference).read_bytes()).hexdigest()}
    acceptance = {**acceptance, 'candidate_sha256': hashlib.sha256((library/'candidate.json').read_bytes()).hexdigest()}
    _write(library/'acceptance.json', acceptance)
    from business_data_mcp.build_context import build_bundle
    business_context = build_bundle(workspace=workspace)
    if business_context["manifest"]["source_sha256"]["bridge"] != semantics[reference]:
        raise ValueError("发布口径与 Bridge 不一致")
    release = {
        'schema_version': 'sql_warehouse_release.v1', 'release_id': release_id,
        'candidate': file_ref(library/'candidate.json', library, 'application/json'),
        'candidate_sha256': acceptance['candidate_sha256'],
        'database_sha256': manifest['database']['sha256'],
        'batch_id': manifest['batch_id'], 'snapshots': manifest['snapshots'],
        'as_of_date': manifest['as_of_date'], 'coverage': coverage,
        'business_context': business_context,
        'semantics': semantics, 'binding': {'inputs': semantics, 'candidate_inputs': manifest['input_binding'], 'rules': manifest['rules']},
        'landing_description': file_ref(library/'landing-description.json', library, 'application/json'),
        'landing_provenance': provenance,
        'superset_catalogue': file_ref(library/'superset-catalogue.json', library, 'application/json'),
        'expense_coverage_note': format_coverage(fees['result']['rows']),
        'acceptance': file_ref(library/'acceptance.json', library, 'application/json'),
    }
    _write(library/'release.json', release)
    archive = output_dir/'sql-release.tar'
    with tarfile.open(archive, 'w') as target:
        target.add(library, arcname=release_id+'/library', recursive=True)
    return {'release': release_id, 'library': str(library), 'archive': str(archive),
            'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'release_manifest': file_ref(library/'release.json', library, 'application/json')}
