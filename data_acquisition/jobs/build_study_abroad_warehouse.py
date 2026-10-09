"""Prepare an isolated study-abroad Snapshot from one explicit full workbook."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil

from interfaces.data_platform import RUN_ID, ingest_sources, inspect_sources
from data_platform.connectors.xlsx import sha256_file
from data_platform.snapshots.ingest import SNAPSHOT_ID
from workspace_modeling.operations.personnel import (
    BUSINESS_GROUP_BY_ROSTER_GROUP, is_displayable_person,
)
from workspace_modeling.operations.study_abroad_source import read_sources


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ID = 'study_abroad_market'
SCHEMA = 'study_abroad_warehouse.v1'
GROUP_SEGMENTS = {
    '线上组': 'study_abroad_online',
    '线下组': 'study_abroad_offline',
    '国际市场': 'international_market',
    'SSC': 'ssc',
}
NON_MARKET_GROUPS = frozenset({'非市场'})
COMMON_COLUMNS = (
    'origin_sha256', 'origin_filename', 'origin_sheet', 'origin_row_number',
    'owner', 'source_owner', 'source_owner_original', 'ownership_mapping_source', 'source_group', 'market_group', 'segment_id',
    'team_eligible', 'market_eligible', 'roster_group', 'roster_status',
    'personal_eligible', 'event_date', 'record_key', 'source_date_conflict', 'source_date_resolution',
)
SHEET_COLUMNS = {
    'resources': COMMON_COLUMNS + (
        'resource_id', 'status', 'consultation_type', 'raw_consultation_type', 'consultation_mapping_source', 'country', 'stage',
        'business_line', 'dashboard_category', 'channel_source',
        'first_channel', 'second_channel', 'third_channel', 'campaign', 'description',
    ),
    'contracts': COMMON_COLUMNS + (
        'resource_id', 'contract_id', 'customer_id', 'customer_name', 'customer_key', 'customer_key_basis', 'amount', 'amount_status',
        'month', 'country', 'stage', 'first_channel', 'second_channel',
        'third_channel', 'campaign', 'contract_status',
    ),
    'languages': COMMON_COLUMNS + (
        'resource_id', 'work_order_id', 'student_id', 'customer_name', 'customer_key', 'customer_key_basis', 'amount', 'amount_status',
        'language', 'course_code', 'business_type', 'signup_type',
        'first_channel', 'second_channel', 'third_channel',
    ),
}
SOURCE_SHEETS = {'resources': '资源', 'contracts': '留学签约', 'languages': '小语种签约'}


def _text(value):
    return '' if value is None else str(value).strip()


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def _identifier(value):
    text = _text(value)
    if re.fullmatch(r'\d+\.0', text):
        text = text[:-2]
    return text if text not in {'', '/', 'None', 'null'} else None


def _day(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f'留学来源日期无效：{text}') from exc


def _money(value):
    text = _text(value).replace(',', '').replace('￥', '').replace('¥', '')
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError('留学来源金额不是有效数值') from exc
    if not amount.is_finite() or amount != amount.quantize(Decimal('0.01')):
        raise ValueError('留学来源金额必须为有限数值且精确到分')
    return format(amount, '.2f')


def _roster(people, abroad):
    result = {}
    for team in people.get('teams', []):
        for group in team.get('groups', []):
            for person in group.get('members', []):
                name = _text(person.get('display_name'))
                if not name or person.get('status') == 'vacant':
                    continue
                result[name] = {
                    'market_group': '国际市场',
                    'roster_group': person.get('business_group') or BUSINESS_GROUP_BY_ROSTER_GROUP.get(group.get('display_name'), ''),
                    'roster_status': person.get('status', 'active'),
                    'personal_eligible': is_displayable_person(person),
                }
    for person in abroad.get('people', []):
        name = _text(person.get('display_name'))
        if name:
            if name in result:
                raise ValueError(f'人员花名册跨业务身份冲突：{name}')
            result[name] = {
                'market_group': '线下组', 'roster_group': person.get('business_group', ''),
                'roster_status': person.get('status', 'active'),
                'personal_eligible': is_displayable_person(person),
            }
    return result


def normalize_sources(source, people, abroad):
    """Retain raw ownership while resolving the confirmed market segments once."""
    roster = _roster(people, abroad)
    groups = {}
    for row in source['group_mapping']:
        owner, group = _text(row['owner']), _text(row['source_group'])
        if not owner:
            continue
        if owner in groups and groups[owner] != group:
            raise ValueError(f'同一市场归属人的团队映射冲突：{owner}')
        groups[owner] = group
    # 历史表使用这些明确的部门占位归属；不是新建个人花名册成员。
    for owner, group in (('SSC', 'SSC'), ('ssc', 'SSC'),
                         ('线上离职', '线上组'), ('线下离职', '线下组')):
        groups.setdefault(owner, group)
    names = set(groups) | set(roster)
    tables = {kind: [] for kind in SOURCE_SHEETS}
    diagnostics = {
        'blank_owner': {}, 'non_market_owner': {}, 'unmapped_owner': {},
        'source_group_disagreements': {}, 'exact_duplicate_keys': {},
        'superseded_resource_rows': {},
        'missing_amount_rows': {},
    }
    for kind, rows in ((kind, source[kind]) for kind in SOURCE_SHEETS):
        seen = {}
        for key in diagnostics:
            diagnostics[key][kind] = 0
        if kind == 'resources':
            # 用户确认同资源ID跨日期重复保留最新分单日期；同日冲突仍拒绝。
            latest = {}
            for raw in rows:
                resource_id, event_date = _identifier(raw.get('resource_id')), _day(raw.get('date'))
                if resource_id and event_date:
                    latest[resource_id] = max(event_date, latest.get(resource_id, event_date))
            selected = []
            for raw in rows:
                resource_id, event_date = _identifier(raw.get('resource_id')), _day(raw.get('date'))
                if resource_id and event_date and event_date < latest[resource_id]:
                    diagnostics['superseded_resource_rows'][kind] += 1
                else:
                    selected.append(raw)
            rows = selected
        for raw in rows:
            owner = _text(raw['owner'])
            if owner.startswith('#'):
                raise ValueError(f'{SOURCE_SHEETS[kind]}市场资源归属人含Excel错误：第{raw["source_row_number"]}行')
            canonical_owner = owner
            if owner and owner not in names:
                matches = [name for name in names if re.fullmatch(re.escape(name) + r'\d+', owner)]
                if len(matches) == 1:
                    canonical_owner = matches[0]
            person = roster.get(canonical_owner, {})
            source_group = _text(raw.get('source_group'))
            historical_group = {'线上': '线上组', '线下': '线下组', 'ssc': 'SSC'}.get(source_group, source_group)
            market_group = groups.get(canonical_owner, person.get('market_group', ''))
            if not market_group and raw.get('historical_import') and historical_group in {*GROUP_SEGMENTS, '非市场'}:
                market_group = historical_group
            market = bool(owner) and market_group not in NON_MARKET_GROUPS and owner not in {'非市场', '国外部签约流转'}
            segment = GROUP_SEGMENTS.get(market_group, 'unassigned') if market else 'excluded'
            comparable_group = historical_group if raw.get('historical_import') else source_group
            if comparable_group and not comparable_group.startswith('#') and market_group and comparable_group != market_group:
                diagnostics['source_group_disagreements'][kind] += 1
            if not owner:
                diagnostics['blank_owner'][kind] += 1
            elif not market:
                diagnostics['non_market_owner'][kind] += 1
            elif segment == 'unassigned':
                diagnostics['unmapped_owner'][kind] += 1
            event_date = _day(raw.get('archive_date') if kind == 'contracts' else raw.get('date'))
            row = {
                **raw,
                'origin_sha256': raw.get('origin_sha256', source['source_sha256']),
                'origin_filename': raw.get('origin_filename', Path(source['source_path']).name),
                'origin_sheet': raw.get('origin_sheet', source.get('source_sheets', {}).get(kind, SOURCE_SHEETS[kind])),
                'origin_row_number': raw.get('origin_row_number', raw['source_row_number']),
                'record_key': raw.get('technical_record_key') or (
                    f"{raw.get('origin_sha256', source['source_sha256'])}:"
                    f"{raw.get('origin_sheet', source.get('source_sheets', {}).get(kind, kind))}:{raw['source_row_number']}"),
                'source_owner': owner, 'owner': canonical_owner,
                'source_owner_original': raw.get('source_owner_original', owner),
                'ownership_mapping_source': raw.get('ownership_mapping_source') or (
                    'legacy_color_legend' if raw.get('historical_import') and '6月' in Path(source['source_path']).name
                    else 'source_owner_column'),
                'source_group': source_group, 'market_group': market_group,
                'segment_id': segment, 'market_eligible': str(market).lower(),
                'team_eligible': str(segment in {'study_abroad_online', 'study_abroad_offline'}).lower(),
                'roster_group': person.get('roster_group', ''),
                'roster_status': person.get('roster_status', 'not_in_roster'),
                'personal_eligible': str(person.get('personal_eligible', bool(owner))).lower(),
                'event_date': event_date,
                'resource_id': _identifier(raw.get('resource_id')),
            }
            if market and not event_date:
                raise ValueError(f'{SOURCE_SHEETS[kind]}已归属记录缺少日期：第{raw["source_row_number"]}行')
            if kind == 'resources':
                row['raw_consultation_type'] = _text(raw.get('raw_consultation_type', raw.get('consultation_type')))
                row['consultation_type'] = _text(raw.get('consultation_type'))
                if raw.get('historical_import') and row['consultation_type'] == '语培':
                    row['consultation_type'] = '小语种'
                if market and row['consultation_type'] not in {'留学', '小语种'}:
                    raise ValueError('市场资源咨询类型必须为留学或小语种')
                if market and not row['resource_id'] and not raw.get('historical_import'):
                    raise ValueError('市场资源缺少资源ID')
                business_key = row['resource_id'] or row['record_key']
            else:
                row['amount'] = _money(raw.get('amount'))
                row['amount_status'] = 'available' if row['amount'] is not None else 'missing'
                if market and row['amount'] is None and not raw.get('historical_import'):
                    raise ValueError(f'{SOURCE_SHEETS[kind]}已归属记录缺少金额')
                if market and row['amount'] is None:
                    diagnostics['missing_amount_rows'][kind] += 1
                customer_id = _identifier(raw.get('customer_id') if kind == 'contracts' else raw.get('student_id'))
                if market and not customer_id and not _text(raw.get('customer_name')):
                    raise ValueError(f'{SOURCE_SHEETS[kind]}已归属记录缺少客户编号和姓名，不能核算人头')
                row['customer_key'] = f'{kind}:{customer_id}' if customer_id else None
                if kind == 'contracts':
                    row['customer_id'] = customer_id
                    month_value = raw.get('month')
                    row['month'] = month_value.isoformat()[:7] if isinstance(month_value, (date, datetime)) else _text(month_value)
                    if market and row['month'] != event_date[:7]:
                        raise ValueError('留学合同归档月份与归档日期不一致')
                    business_key = _text(raw['contract_id'])
                else:
                    row['student_id'] = customer_id
                    row['work_order_id'] = _identifier(raw.get('work_order_id'))
                    business_key = None  # No stable receipt key: never discard equal-looking enrolments.
            if business_key:
                identity = tuple(_text(row.get(column)) for column in SHEET_COLUMNS[kind]
                                 if column not in {'origin_row_number', 'record_key'})
                if business_key in seen:
                    if seen[business_key] != identity:
                        label = '资源' if kind == 'resources' else '合同'
                        raise ValueError(f'同一{label}的来源记录存在冲突：{business_key}')
                    diagnostics['exact_duplicate_keys'][kind] += 1
                seen[business_key] = identity
            tables[kind].append({column: row.get(column) for column in SHEET_COLUMNS[kind]})
    from data_acquisition.jobs.study_abroad_identity import align_customer_keys
    diagnostics['customer_identity'] = align_customer_keys(tables)
    return tables, diagnostics


def _write_source(path, tables):
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    book = Workbook(write_only=True)
    for name, columns in SHEET_COLUMNS.items():
        sheet = book.create_sheet(name)
        sheet.append(list(columns))
        for row in tables[name]:
            cells = []
            for column in columns:
                value = row.get(column)
                if column == 'origin_row_number' and value is not None:
                    # 受控landing查询返回文本；源Excel物理行号在标准工作簿中保持整数。
                    value = int(value)
                cell = WriteOnlyCell(sheet, value=value)
                if isinstance(value, str):
                    cell.data_type = 's'
                cells.append(cell)
            sheet.append(cells)
    book.save(path)
    book.close()


@contextmanager
def _lock(path):
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('已有留学建仓任务正在运行') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _historical_import_source(source_file, history_files, legacy_files, refresh_months, legacy_date_preference=None):
    """一次性清洗历史；在线导出只更新明确当前月份，避免重写已封存历史。"""
    from data_acquisition.jobs.study_abroad_legacy import read_legacy_sources
    loaded = [read_legacy_sources(Path(path)) for path in legacy_files]
    loaded.extend(read_sources(Path(path)) for path in history_files)
    current = read_sources(source_file)
    current_resource_dimensions = {_identifier(row.get('resource_id')): row for row in current['resources']}
    current_exact_resources = {(_identifier(row.get('resource_id')), _day(row.get('date'))): row
                               for row in current['resources']}
    months = set(refresh_months)
    if not months:
        raise ValueError('一次性历史导入必须明确在线来源刷新月份')
    combined = {kind: [] for kind in SOURCE_SHEETS}
    metadata = []
    for part in [*loaded, current]:
        is_current = part is current
        metadata.append({'path': part['source_path'], 'sha256': part['source_sha256'],
                         'filename': Path(part['source_path']).name,
                         'source_sheets': part.get('source_sheets', {}),
                         'historical_import': bool(part.get('historical_import'))})
        for kind in SOURCE_SHEETS:
            for raw in part[kind]:
                raw = dict(raw)
                if (kind == 'languages' and part.get('historical_import') and not raw.get('date')
                        and legacy_date_preference in {'full', 'component'}):
                    raw['date'] = raw.get(f'date_{legacy_date_preference}_candidate')
                    raw['source_date_conflict'] = 'true'
                    raw['source_date_resolution'] = legacy_date_preference
                if kind == 'resources' and part.get('historical_import'):
                    raw['raw_consultation_type'] = raw.get('consultation_type')
                    # 7月已有团队但缺个人：只引用同资源、同分单日、同团队的已确认人工归属。
                    original_group = _text(raw.get('source_group'))
                    canonical_group = {'线上': '线上组', '线下': '线下组', 'ssc': 'SSC'}.get(original_group, original_group)
                    if not raw.get('owner') and '7月' in Path(part['source_path']).name:
                        dimension = current_exact_resources.get((_identifier(raw.get('resource_id')), _day(raw.get('date'))))
                        if (dimension and dimension.get('owner') and canonical_group in GROUP_SEGMENTS
                                and _text(dimension.get('source_group')) == canonical_group):
                            raw['source_owner_original'] = None
                            raw['owner'] = dimension['owner']
                            raw['ownership_mapping_source'] = 'current_manual_owner_same_resource_id_date_team'
                    if ',' in _text(raw.get('consultation_type')):
                        dimension = current_resource_dimensions.get(_identifier(raw.get('resource_id')))
                        if dimension and dimension.get('consultation_type') in {'留学', '小语种'}:
                            raw['consultation_type'] = dimension['consultation_type']
                            raw['consultation_mapping_source'] = 'same_resource_id_current_optimized_type'
                day = _day(raw.get('archive_date') if kind == 'contracts' else raw.get('date'))
                if is_current and day and day[:7] not in months:
                    continue
                combined[kind].append({**raw, 'origin_sha256': part['source_sha256'],
                                      'origin_filename': Path(part['source_path']).name,
                                      'origin_sheet': raw.get('origin_sheet', part.get('source_sheets', {}).get(kind, SOURCE_SHEETS[kind])),
                                      'origin_row_number': raw['source_row_number'],
                                      'historical_import': bool(part.get('historical_import'))})
    return {**current, **combined, 'source_files': metadata,
            'current_source_sha256': current['source_sha256'],
            'update_mode': 'one_time_legacy_standardization',
            'legacy_diagnostics': [part.get('diagnostics', {}) for part in loaded if part.get('historical_import')]}


def build(*, workspace: Path, source_file: Path, run_id: str, snapshot_id: str,
          through_date: str, people_path: Path | None = None,
          abroad_people_path: Path | None = None, history_files: list[Path] | None = None,
          refresh_months: list[str] | None = None, legacy_files: list[Path] | None = None,
          history_snapshot_id: str | None = None, legacy_date_preference: str | None = None,
          standardized_source: bool = False) -> dict:
    workspace, source_file = Path(workspace).resolve(), Path(source_file).resolve()
    config_path = workspace / 'Work/workspace.json'
    config_before = config_path.read_bytes()
    config = json.loads(config_before)
    if not config.get('company_id'):
        raise ValueError('留学仓必须绑定现有客户身份')
    if not RUN_ID.fullmatch(run_id) or not SNAPSHOT_ID.fullmatch(snapshot_id):
        raise ValueError('run_id或snapshot_id无效')
    through_date = date.fromisoformat(through_date).isoformat()
    people_path = people_path or ROOT / 'workspace_modeling/operations/people.json'
    abroad_people_path = abroad_people_path or ROOT / 'dashboard_product/config/offline_market_people.json'
    isolated = workspace / 'Work/StudyAbroad'
    isolated.mkdir(parents=True, exist_ok=True)
    with _lock(isolated / '.build.lock'):
        current_path = isolated / 'current.json'
        previous = _json(current_path) if current_path.exists() else {}
        if previous and (previous.get('schema_version') != SCHEMA or previous.get('company_id') != config['company_id']):
            raise ValueError('现有留学仓指针的版本或客户身份不匹配')
        if snapshot_id in previous.get('used_snapshot_ids', []):
            raise ValueError('留学Snapshot ID已使用，不能覆盖或重复发布')
        run_root = isolated / 'Runs' / run_id
        if run_root.exists():
            raise ValueError('留学运行目录已存在，需使用新的显式run_id')
        people_before, abroad_before = people_path.read_bytes(), abroad_people_path.read_bytes()
        if standardized_source and (legacy_files or history_files or history_snapshot_id):
            raise ValueError('标准源直接入仓不与原件导入或Snapshot历史复用混用')
        if legacy_files and history_snapshot_id:
            raise ValueError('一次性原件导入和标准Snapshot历史复用不能同时选择')
        history_context = None
        if standardized_source:
            from data_acquisition.jobs.study_abroad_standard_source import read_standard_source
            standard = read_standard_source(source_file, SHEET_COLUMNS)
            source = {**standard, 'update_mode': 'already_standardized_source', 'group_mapping': []}
            tables, diagnostics = standard['tables'], standard['diagnostics']
        elif history_snapshot_id:
            if history_files or not refresh_months:
                raise ValueError('标准Snapshot历史复用只接受明确刷新月份，不重复读取历史原件')
            from data_acquisition.jobs.study_abroad_snapshot_history import load_normalized_history
            history_context = load_normalized_history(workspace, history_snapshot_id, run_id)
            source = read_sources(source_file)
            for kind in SOURCE_SHEETS:
                source[kind] = [row for row in source[kind]
                                if not _day(row.get('archive_date') if kind == 'contracts' else row.get('date'))
                                or _day(row.get('archive_date') if kind == 'contracts' else row.get('date'))[:7] in refresh_months]
            source['update_mode'] = 'reuse_normalized_snapshot_replace_explicit_months'
        elif legacy_files:
            source = _historical_import_source(source_file, history_files or [], legacy_files, refresh_months or [], legacy_date_preference)
        elif history_files or refresh_months:
            from data_acquisition.jobs.study_abroad_history import read_retained_sources
            source = read_retained_sources(source_file, history_files or [], refresh_months or [])
        else:
            source = read_sources(source_file)
        if not standardized_source:
            tables, diagnostics = normalize_sources(source, json.loads(people_before), json.loads(abroad_before))
        if history_context:
            from data_acquisition.jobs.study_abroad_snapshot_history import replace_normalized_months
            from data_acquisition.jobs.study_abroad_identity import align_customer_keys
            tables = replace_normalized_months(history_context['tables'], tables, refresh_months)
            diagnostics['customer_identity'] = align_customer_keys(tables)
        run_root.mkdir(parents=True)
        inputs = run_root / 'input'
        inputs.mkdir()
        raw_copy = inputs / ('original_' + source_file.name if source_file.name == 'study_abroad_market.xlsx' else source_file.name)
        shutil.copyfile(source_file, raw_copy)
        primary_sha = source.get('current_source_sha256', source['source_sha256'])
        if sha256_file(raw_copy) != primary_sha:
            raise ValueError('留学来源在复制时发生变化')
        origin_files = []
        for index, item in enumerate(source.get('source_files', [])):
            original = Path(item['path'])
            if original.resolve() == source_file:
                frozen = raw_copy
            else:
                frozen = inputs / 'history' / f'{index:03}_{original.name}'
                frozen.parent.mkdir(exist_ok=True)
                shutil.copyfile(original, frozen)
            if sha256_file(frozen) != item['sha256']:
                raise ValueError('留学历史来源在复制时发生变化')
            origin_files.append({**item, 'path': str(frozen.relative_to(run_root))})
        (inputs / 'people.json').write_bytes(people_before)
        (inputs / 'abroad_people.json').write_bytes(abroad_before)
        prepared = inputs / 'study_abroad_market.xlsx'
        if prepared == raw_copy:
            raise ValueError('原始文件名与规范化来源名冲突')
        _write_source(prepared, tables)
        manifest_path = inputs / 'manifest.json'
        _write_json(manifest_path, {'sources': {SOURCE_ID: {'filename': prepared.name, 'sha256': sha256_file(prepared)}}})
        values = [f'{SOURCE_ID}={prepared}']
        inspection = inspect_sources(run_id=run_id, manifest_path=manifest_path, source_values=values)
        _write_json(run_root / 'inspection.json', inspection)
        if inspection['status'] not in {'passed', 'passed_with_warnings'}:
            raise ValueError('留学规范化来源结构检查失败')
        ingested = ingest_sources(run_id=run_id, snapshot_id=snapshot_id, output_root=isolated / 'Runs',
                                  manifest_path=manifest_path, source_values=values)
        _write_json(run_root / 'ingest.json', ingested)
        if ingested['status'] != 'passed':
            raise ValueError('留学Snapshot发布失败：' + json.dumps(ingested['errors'], ensure_ascii=False))
        warehouse = run_root / 'data/snapshots' / snapshot_id / 'warehouse.duckdb'
        hashes = {
            'source': primary_sha,
            'people': hashlib.sha256(people_before).hexdigest(),
            'abroad_people': hashlib.sha256(abroad_before).hexdigest(),
            'normalizer': sha256_file(Path(__file__)),
            'reader': sha256_file(ROOT / 'workspace_modeling/operations/study_abroad_source.py'),
            'identity_reader': sha256_file(ROOT / 'data_acquisition/jobs/study_abroad_identity.py'),
        }
        if standardized_source:
            hashes['standard_source_reader'] = sha256_file(ROOT / 'data_acquisition/jobs/study_abroad_standard_source.py')
        elif legacy_files:
            hashes['legacy_reader'] = sha256_file(ROOT / 'data_acquisition/jobs/study_abroad_legacy.py')
        elif history_files or (refresh_months and not history_context):
            hashes['history_reader'] = sha256_file(ROOT / 'data_acquisition/jobs/study_abroad_history.py')
        if history_context:
            hashes['snapshot_history_reader'] = sha256_file(ROOT / 'data_acquisition/jobs/study_abroad_snapshot_history.py')
        lineage = {
            'schema_version': SCHEMA, 'company_id': config['company_id'],
            'run_id': run_id, 'snapshot_id': snapshot_id, 'through_date': through_date,
            'update_mode': source.get('update_mode', 'one_explicit_full_workbook'), 'source_hashes': hashes,
            'origin_file': str(raw_copy.relative_to(run_root)),
            'prepared_file': str(prepared.relative_to(run_root)),
            'roster_files': {'people': 'input/people.json', 'abroad_people': 'input/abroad_people.json'},
            'row_counts': {kind: len(rows) for kind, rows in tables.items()},
            'diagnostics': diagnostics,
            'amount_basis': {'contracts': '签约金额', 'languages': '实缴金额'},
            'rules': {
                'blank_owner': 'excluded', 'department_deleted_resource': 'included',
                'personal_deleted_resource': 'excluded', 'signature': 'positive_gross_only',
                'resource_identity': 'resource_id_latest_assignment_date_same_day_conflict_rejected',
                'contract_customer_key': '客户ID优先；缺失按姓名暂定去重',
                'language_customer_key': '学员编号优先；缺失按姓名暂定去重',
                'cross_system_customer_identity': 'not_aligned',
                'international_market': 'total_and_supplemental_only',
                'comparison': 'not_available',
            },
        }
        if origin_files:
            lineage.update({'origin_files': origin_files,
                            'retained_months': source.get('retained_months', {}),
                            'refresh_months': refresh_months or [],
                            'source_bundle_sha256': source['source_sha256']})
        if legacy_files:
            lineage['legacy_diagnostics'] = source['legacy_diagnostics']
            lineage['historical_cash_basis'] = '用户确认6/7月小语种签约金额视为实收；六月颜色归属，未标色排除'
            lineage['legacy_date_preference'] = legacy_date_preference
        if history_context:
            lineage['normalized_history'] = history_context['source_metadata']
            lineage['refresh_months'] = refresh_months
        _write_json(run_root / 'source_lineage.json', lineage)
        # The BI pointer and source slots are never written. Stop if somebody
        # changed the customer identity while this isolated build was running.
        if config_path.read_bytes() != config_before or people_path.read_bytes() != people_before or abroad_people_path.read_bytes() != abroad_before:
            raise ValueError('客户或花名册配置在留学建仓时变化，未切换留学指针')
        pointer = {
            'schema_version': SCHEMA, 'company_id': config['company_id'],
            'run_id': run_id, 'snapshot_id': snapshot_id, 'through_date': through_date,
            'source_sha256': primary_sha,
            'warehouse': str(warehouse.relative_to(workspace)),
            'source_lineage': str((run_root / 'source_lineage.json').relative_to(workspace)),
            'used_snapshot_ids': [*previous.get('used_snapshot_ids', []), snapshot_id],
        }
        temporary = current_path.with_suffix('.tmp')
        _write_json(temporary, pointer)
        temporary.replace(current_path)
        return {**pointer, 'warehouse': str(warehouse), 'current_pointer': str(current_path),
                'row_counts': lineage['row_counts'], 'diagnostics': diagnostics}


def main():
    parser = argparse.ArgumentParser(description='从明确的完整工作簿构建隔离留学仓，不更新BI仓或看板')
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--source-file', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--snapshot-id', required=True)
    parser.add_argument('--through-date', required=True)
    parser.add_argument('--history-file', dest='history_files', type=Path, action='append', default=[],
                        help='保留历史的明确工作簿，按从旧到新顺序提供；当前来源覆盖它含有的月份')
    parser.add_argument('--refresh-month', dest='refresh_months', action='append', default=[],
                        help='明确刷新的YYYY-MM；即使当前导出该月无记录，也清空该月旧记录')
    parser.add_argument('--legacy-file', dest='legacy_files', type=Path, action='append', default=[],
                        help='一次性清洗的已确认6/7/8月历史原件')
    parser.add_argument('--history-snapshot-id', help='后续更新复用明确的已标准化留学Snapshot，不重读旧Excel')
    parser.add_argument('--legacy-date-preference', choices=['full', 'component'],
                        help='历史两个日期冲突时的明确口径；不指定则冲突会阻断导入')
    parser.add_argument('--standardized-source', action='store_true',
                        help='直接导入已通过清洗的标准三表源，不重新解析历史旧格式')
    args = parser.parse_args()
    try:
        print(json.dumps({'status': 'passed', **build(**vars(args))}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
