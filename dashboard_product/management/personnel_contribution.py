"""人员贡献：BI语培事实与标准留学Snapshot通过真实来源标记核算。"""
from __future__ import annotations

from calendar import monthrange
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
import hashlib
from pathlib import Path
import re

from .aggregate import _roster
from workspace_modeling.operations.personnel import (
    DEFAULT_ORDER_STATUS_MODE, ORDER_STATUS_MODES, co_creation_weights,
    match_person_names, order_status_allowed,
)
from workspace_modeling.operations.study_abroad_source import read_sources

SOURCE_DIRECTORY = 'Input/Reference/人员产能'
RESOURCE_FILENAME = '资源与签约.xlsx'
BRACKETS = re.compile(r'（([^）]*)）|\(([^)]*)\)')
SOURCE_LABELS = {'resources': '留学资源', 'contracts': '留学签约', 'languages': '小语种签约'}
PRODUCT_SCOPES = ('study_abroad', 'small_language')


def _text(value):
    return '' if value is None else str(value).strip()


def resource_id(value):
    """资源编号可有ID前缀；明确的客户编号绝不能当作资源编号。"""
    text = _text(value)
    if '客户' in text or text in ('', '/', 'None'):
        return None
    text = re.sub(r'^(?:资源\s*ID|ID)\s*[:：]\s*', '', text, flags=re.I)
    if re.fullmatch(r'\d+\.0', text):
        text = text[:-2]
    return text if text.isdigit() else None


def _day(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f'人员贡献日期无效：{text}') from exc


def _month(value):
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:7] + '-01').isoformat()[:7]
    except ValueError as exc:
        raise ValueError(f'人员贡献月份无效：{text}') from exc


def _amount(value):
    text = _text(value).replace(',', '').replace('￥', '')
    if not text:
        raise ValueError('已归属的签约记录缺少金额')
    value = Decimal(text)
    if not value.is_finite():
        raise ValueError('签约金额必须为有限数值')
    return value


def _resource_product_scope(row):
    consultation_type = _text(row.get('consultation_type'))
    if consultation_type == '留学':
        return 'study_abroad'
    if consultation_type == '小语种':
        return 'small_language'
    raise ValueError(
        f"已归属留学资源咨询类型必须为留学或小语种："
        f"第{row.get('source_row_number')}行，值={consultation_type or '未提供'}"
    )


def _number(value, money=False):
    value = value.quantize(Decimal('0.01')) if money else value
    return int(value) if value == value.to_integral_value() else float(value)


def _personnel_snapshot_rows(kind, rows):
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f'标准留学来源 {kind} 包含无效记录')
        origin_row_number = row.get('origin_row_number')
        if origin_row_number in (None, ''):
            raise ValueError(f'标准留学来源 {kind} 缺少原始行号')
        converted = {**row, 'source_row_number': origin_row_number,
                     '_normalized_snapshot_row': True}
        if kind == 'resources':
            converted['date'] = row.get('event_date')
        elif kind == 'contracts':
            converted['archive_date'] = row.get('event_date')
        else:
            converted['date'] = row.get('event_date')
        result.append(converted)
    return result


def _has_resource_record(row):
    return bool(resource_id(row.get('resource_id')) or _text(row.get('record_key')))


def load_sources(resource_path: Path, *, normalized_source=None, normalized_source_hashes=None):
    """Read the explicit standard source when supplied, otherwise the page workbook."""
    result = {'resources': [], 'contracts': [], 'languages': [],
              'resources_connected': False, 'source_hashes': {}}
    normalized_tables = (normalized_source.get('tables')
                         if isinstance(normalized_source, dict) else None)
    if normalized_tables is not None:
        if not isinstance(normalized_tables, dict):
            raise ValueError('标准留学来源 tables 必须是对象')
        for key in ('resources', 'contracts', 'languages'):
            rows = normalized_tables.get(key)
            if not isinstance(rows, list):
                raise ValueError(f'标准留学来源缺少 {key} 记录表')
            result[key] = _personnel_snapshot_rows(key, rows)
        result['resources_connected'] = True
        result['source_hashes'].update(dict(normalized_source_hashes or {}))
    elif resource_path.is_file():
        study_abroad = read_sources(resource_path)
        for key in ('resources', 'contracts', 'languages'):
            result[key] = study_abroad[key]
        result['resources_connected'] = True
        result['source_hashes'][str(resource_path)] = study_abroad['source_sha256']
    for path, digest in result['source_hashes'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError('人员贡献输入在读取过程中发生变化')
    return result


def _name(value, people):
    text = _text(value)
    # 系统姓名末尾工号，如师顺盈1；人工归属仍须明确匹配，不能推断归属。
    matches = [name for name in people if text == name or re.fullmatch(re.escape(name) + r'\d+', text)]
    return matches[0] if len(matches) == 1 else None


def _participants(event, people):
    campaign = event.get('campaign', '')
    outside = BRACKETS.sub(' ', _text(campaign))
    description = BRACKETS.sub(' ', _text(event.get('description')))
    names = list(people)
    primary = match_person_names(names, outside, event.get('entry_person'), description)
    secondary = [name for name in names
                 if any(name in (m.group(1) or m.group(2) or '') for m in BRACKETS.finditer(_text(campaign)))]
    if not primary and event.get('owner') and event['owner'] not in secondary:
        primary = [event['owner']]
    primary_lines = {people[name]['business_line'] for name in primary}
    # 同业务括号内人员仍是共创者；跨业务接收另以实际业务源行和明确活动姓名判断。
    if len(primary_lines) == 1:
        primary += [name for name in secondary if people[name]['business_line'] in primary_lines]
    return list(dict.fromkeys(primary)), list(dict.fromkeys(secondary))


def _ordinary_allocation(event, names, people):
    return [(name, 'self' if people[name]['business_line'] == event['line'] else 'output', weight,
             'ordinary_co_creation')
            for name, weight in co_creation_weights(names, people).items()]


def _activity_market_handoff(event, primary, secondary, people):
    """Allocate an actual cross-line event when its parties and source owner agree."""
    if not primary:
        return None
    primary_lines = {people[name]['business_line'] for name in primary}
    if len(primary_lines) != 1:
        return None
    primary_line = next(iter(primary_lines))
    if primary_line == event['line']:
        # The real source agrees with the creator's own business. Cross-line
        # bracketed names do not receive a contribution from this source.
        return None
    if (event['source'] != 'bi'
            and event.get('owner') not in set(primary + secondary)):
        # Manual ownership is authoritative when activity text names unrelated
        # current employees.
        return None

    creators = [name for name in primary if 'offline_market' in people[name]['team_ids']]
    creator_weights = co_creation_weights(creators, people)
    if not creator_weights:
        return None
    receivers = [name for name in secondary
                 if people[name]['business_line'] == event['line']
                 and 'offline_market' in people[name]['team_ids']]
    receiver_weights = co_creation_weights(receivers, people)
    if receiver_weights:
        return ([(name, 'output', weight * Decimal('0.5'), 'activity_market_handoff')
                 for name, weight in creator_weights.items()] +
                [(name, 'received', weight * Decimal('0.5'), 'activity_market_handoff')
                 for name, weight in receiver_weights.items()])
    return [(name, 'output', weight, 'independent_cross_output')
            for name, weight in creator_weights.items()]


def _cross_business_marker(row, *, source):
    if source == 'bi':
        if _text(row.get('first_channel')) != '双分':
            return None
        return {
            'kind': 'bi_first_channel', 'value': '双分',
            'direction': 'abroad_to_training',
            'source_business_line': 'abroad', 'destination_business_line': 'training',
            'source_owner': row.get('resource_entry_person'),
            'source_key': _text(row.get('work_order_id')) or None,
            'source_row_number': row.get('source_row_number'),
        }
    market_group = _text(row.get('market_group'))
    source_group = _text(row.get('source_group'))
    segment_id = _text(row.get('segment_id'))
    if market_group or segment_id:
        if ((market_group and market_group != '国际市场')
                or (segment_id and segment_id != 'international_market')):
            return None
        if market_group != '国际市场' and segment_id != 'international_market':
            return None
    elif source_group != '国际市场':
        return None
    marker_value = ('国际市场' if market_group == '国际市场' else
                    '国际市场' if source_group == '国际市场' else segment_id)
    return {
        'kind': 'study_abroad_international_market', 'value': marker_value,
        'direction': 'training_to_abroad',
        'source_business_line': 'training', 'destination_business_line': 'abroad',
        'source_owner': row.get('source_owner'),
        'source_key': _text(row.get('record_key')) or None,
        'source_row_number': row.get('origin_row_number') or row.get('source_row_number'),
        'source_sha256': row.get('origin_sha256'),
        'source_filename': row.get('origin_filename'),
        'source_sheet': row.get('origin_sheet'),
        'campaign': row.get('campaign'),
        'description': row.get('description'),
        'resource_id': resource_id(row.get('resource_id')),
    }


def _standard_personnel_row_eligible(row):
    if not row.get('_normalized_snapshot_row'):
        return True
    return (_text(row.get('market_eligible')).casefold() != 'false'
            and _text(row.get('personal_eligible')).casefold() != 'false'
            and row.get('segment_id') not in {'ssc', 'unassigned'})


def _marker_receivers(event, marker, people):
    destination = marker['destination_business_line']
    eligible = [name for name, person in people.items()
                if person['business_line'] == destination
                and (person['abroad_roster'] or 'offline_market' in person['team_ids'])]
    return match_person_names(eligible, event.get('campaign'), '', event.get('description'))


def _marker_source_participants(event, marker, people):
    source_line = marker['source_business_line']
    eligible = [name for name, person in people.items()
                if person['business_line'] == source_line]
    authoritative = match_person_names(eligible, '', marker.get('source_owner'), '')
    activity = match_person_names(eligible, event.get('campaign'), '', event.get('description'))
    conflict = (marker.get('kind') == 'study_abroad_international_market'
                and bool(authoritative) and bool(activity)
                and not set(authoritative).intersection(activity))
    return authoritative, activity, conflict


def _marker_source_creators(event, marker, people):
    authoritative, activity, conflict = _marker_source_participants(event, marker, people)
    if not authoritative:
        return []
    if conflict:
        return authoritative
    return list(dict.fromkeys(authoritative + activity))


def _marked_allocation(event, marker, people):
    source_line = marker['source_business_line']
    if event['line'] != marker['destination_business_line']:
        return []
    authoritative, activity, conflict = _marker_source_participants(event, marker, people)
    if conflict:
        return [(name, 'output', weight, 'source_marker_owner_authoritative')
                for name, weight in co_creation_weights(authoritative, people).items()]
    source_creators = (list(dict.fromkeys(authoritative + activity))
                       if authoritative else [])
    source_weights = co_creation_weights(source_creators, people)
    receivers = _marker_receivers(event, marker, people)
    if source_weights and receivers:
        return ([(name, 'output', weight * Decimal('0.5'), 'source_marker_handoff')
                 for name, weight in source_weights.items()] +
                [(name, 'received', weight * Decimal('0.5'), 'source_marker_handoff')
                 for name, weight in co_creation_weights(receivers, people).items()])
    if source_weights:
        return [(name, 'output', weight, 'source_marker_independent_output')
                for name, weight in source_weights.items()]
    if receivers:
        return [(name, 'received', weight * Decimal('0.5'), 'source_marker_without_active_source_owner')
                for name, weight in co_creation_weights(receivers, people).items()]
    return []


def _allocation(event, people):
    marker = event.get('cross_business_marker')
    if marker and event.get('apply_cross_business_marker', True):
        return _marked_allocation(event, marker, people)

    # Only a real opposite-business source plus explicit activity names
    # supports an unmarked activity handoff.
    primary, secondary = _participants(event, people)
    if event['source'] != 'bi':
        owner = event.get('owner')
        if not owner or not primary or owner not in set(primary + secondary):
            return _ordinary_allocation(event, [owner] if owner else [], people)
        handoff = _activity_market_handoff(event, primary, secondary, people)
        if handoff is not None:
            return handoff
        return _ordinary_allocation(event, [owner], people)

    handoff = _activity_market_handoff(event, primary, secondary, people)
    if handoff is not None:
        return handoff
    return _ordinary_allocation(event, primary, people)


def _events(facts, order_rows, sources, people, diagnostics):
    orders = {_text(row.get('work_order_id')): row for row in order_rows}
    for kind in ('resources', 'contracts', 'languages'):
        for row in sources[kind]:
            market_group = _text(row.get('market_group'))
            source_group = _text(row.get('source_group'))
            segment_id = _text(row.get('segment_id'))
            if ((market_group and segment_id
                 and (market_group == '国际市场') != (segment_id == 'international_market'))
                    or (source_group == '国际市场'
                        and ((market_group and market_group != '国际市场')
                             or (segment_id and segment_id != 'international_market')))):
                diagnostics['international_marker_mapping_conflicts'] += 1
    latest_resource_dates = {}
    for row in sources['resources']:
        rid = resource_id(row.get('resource_id'))
        day = _day(row.get('date')) if row.get('date') else None
        if rid and day:
            latest_resource_dates[rid] = max(day, latest_resource_dates.get(rid, day))
    resource_markers = {}
    for row in sources['resources']:
        if not _standard_personnel_row_eligible(row):
            continue
        rid = resource_id(row.get('resource_id'))
        marker = _cross_business_marker(row, source='standard')
        if not rid or marker is None:
            continue
        day = _day(row.get('date')) if row.get('date') else None
        if day != latest_resource_dates.get(rid):
            continue
        prior = resource_markers.get(rid)
        if prior and (prior.get('source_owner'), prior.get('source_key')) != (
                marker.get('source_owner'), marker.get('source_key')):
            raise ValueError(f'同一留学资源的国际市场标记冲突：{rid}')
        resource_markers[rid] = marker

    for fact in facts:
        if fact['business_line'] != 'training':
            continue  # BI留学事实绝不进入新版人员贡献。
        source = orders.get(_text(fact.get('work_order_id')), {})
        marker = _cross_business_marker(source, source='bi') if source else None
        if marker:
            marker['source_row_number'] = source.get('source_row_number') or fact.get('source_row_number')
        order_status = _text(fact.get('order_status') or source.get('order_status')) or None
        if fact['metric'] == 'orders' and order_status == '删除':
            diagnostics['deleted_training_orders'] += 1
        event = {'key': fact['fact_id'], 'source': 'bi', 'source_row_number': fact.get('source_row_number'),
                 'line': 'training', 'product_scope': 'training',
                 'metric': fact['metric'], 'month': fact['event_date'][:7],
                 'order_status': order_status,
                 'value': Decimal(str(fact['value'])), 'resource_id': resource_id(source.get('resource_id')),
                 'work_order_id': fact.get('work_order_id'),
                 'campaign': source.get('campaign_name') or fact.get('campaign_name'),
                 'entry_person': source.get('resource_entry_person'), 'description': source.get('resource_description'),
                 'cross_business_marker': marker, 'apply_cross_business_marker': bool(marker)}
        yield event
    seen = {}
    resource_rows = []
    for row in sources['resources']:
        rid = resource_id(row.get('resource_id'))
        record_key = _text(row.get('record_key'))
        if not rid and not record_key:
            diagnostics['invalid_abroad_resource_id'] += 1
            continue
        marker = _cross_business_marker(row, source='standard')
        owner = _name(row.get('owner'), people)
        if not owner and not marker:
            diagnostics['blank_abroad_owner' if not _text(row.get('owner')) else 'owner_outside_roster'] += 1
            continue
        day = _day(row.get('date'))
        if not day:
            raise ValueError('已归属的留学记录缺少统计月份')
        resource_rows.append((row, rid, record_key, owner, day, marker))

    rows_by_kind = {
        'resources': resource_rows,
        'contracts': [(row, resource_id(row.get('resource_id')), _text(row.get('record_key')), None, None, None)
                      for row in sources['contracts']],
        'languages': [(row, resource_id(row.get('resource_id')), _text(row.get('record_key')), None, None, None)
                      for row in sources['languages']],
    }
    for kind, metric in (('resources', 'orders'), ('contracts', 'cash'), ('languages', 'cash')):
        for row, row_resource_id, record_key, resolved_owner, resource_day, direct_marker in rows_by_kind[kind]:
            marker = direct_marker if kind == 'resources' else resource_markers.get(row_resource_id)
            if not _standard_personnel_row_eligible(row):
                continue
            if kind == 'contracts' and not _text(row.get('contract_id')):
                continue  # 无合同编号的工作表尾部辅助单元格不是签约记录。
            if kind == 'resources' and row_resource_id and resource_day < latest_resource_dates[row_resource_id]:
                diagnostics['superseded_abroad_resource_rows'] += 1
                continue
            if kind != 'resources' and row.get('_normalized_snapshot_row'):
                amount_status = _text(row.get('amount_status')).casefold()
                if amount_status == 'missing' or row.get('amount') is None:
                    diagnostics['diagnostics_missing_amount'] += 1
                    continue
            order_status = _text(row.get('status')) or None if kind == 'resources' else None
            if kind == 'resources' and order_status == '删除':
                diagnostics['deleted_abroad_orders'] += 1
            owner = resolved_owner if kind == 'resources' else _name(row.get('owner'), people)
            if not owner and (kind != 'resources' or marker is None):
                diagnostics['blank_abroad_owner' if not _text(row.get('owner')) else 'owner_outside_roster'] += 1
                continue
            if kind == 'contracts':
                archive_date = _day(row.get('archive_date'))
                if not archive_date:
                    raise ValueError('已归属的留学签约记录缺少归档日期')
                month = _month(row.get('month'))
            else:
                day = resource_day if kind == 'resources' else _day(row.get('date'))
                month = _month(day)
            if not month:
                raise ValueError('已归属的留学记录缺少统计月份')
            if kind == 'resources':
                product_scope = _resource_product_scope(row)
            else:
                product_scope = 'study_abroad' if kind == 'contracts' else 'small_language'
            value = Decimal(1) if metric == 'orders' else _amount(row.get('amount'))
            business_key = (row_resource_id or record_key if kind == 'resources' else
                            _text(row.get('contract_id')) if kind == 'contracts' else
                            record_key or str(row['source_row_number']))
            key = (kind, business_key)
            identity = (product_scope, month, owner, value, order_status,
                        _text(row.get('campaign')) if kind == 'resources' else '',
                        marker.get('kind') if marker else None,
                        marker.get('source_owner') if marker else None)
            if key in seen:
                if seen[key] != identity:
                    raise ValueError(f'同一留学记录存在冲突：{key}')
                diagnostics['exact_duplicate_abroad_rows'] += 1
                continue
            seen[key] = identity
            apply_marker = bool(marker)
            if metric == 'cash' and marker:
                event_candidate = {'line': 'abroad', 'source': kind, 'owner': owner,
                                   'campaign': row.get('campaign') or marker.get('campaign'),
                                   'description': row.get('description') or marker.get('description')}
                apply_marker = bool(owner and people[owner]['business_line'] == marker['source_business_line']
                                    and owner in _marker_source_creators(event_candidate, marker, people))
            activity_campaign = row.get('campaign')
            activity_description = row.get('description')
            if metric == 'cash' and marker and apply_marker:
                activity_campaign = activity_campaign or marker.get('campaign')
                activity_description = activity_description or marker.get('description')
            yield {'key': ':'.join(key), 'source': kind, 'source_row_number': row['source_row_number'],
                   'line': 'abroad', 'product_scope': product_scope,
                   'order_status': order_status,
                   'metric': metric, 'month': month, 'value': value,
                   'owner': owner, 'resource_id': resource_id(row.get('resource_id')),
                   'work_order_id': row.get('work_order_id'),
                   'campaign': activity_campaign,
                   'description': activity_description,
                   'record_key': row.get('record_key'),
                   'origin_sha256': row.get('origin_sha256'),
                   'origin_filename': row.get('origin_filename'),
                   'origin_sheet': row.get('origin_sheet'),
                   'origin_row_number': row.get('origin_row_number'),
                   'source_owner': row.get('source_owner'),
                   'cross_business_marker': marker,
                   'apply_cross_business_marker': apply_marker}


def _validate_resource_scopes(sources, people):
    for row in sources['resources']:
        if not _has_resource_record(row):
            continue
        if not _name(row.get('owner'), people) and not _cross_business_marker(row, source='standard'):
            continue
        if not row.get('date'):
            raise ValueError('已归属的留学资源缺少日期')
        _day(row.get('date'))
        _resource_product_scope(row)


def _end(month):
    year, number = map(int, month.split('-'))
    return date(year, number, monthrange(year, number)[1]).isoformat()


def _coverage(sources, month, bi_coverage):
    abroad_order_months = {_month(_day(r.get('date'))) for r in sources['resources'] if _has_resource_record(r)}
    abroad_cash_months = {_month(r.get('month')) for r in sources['contracts'] if _text(r.get('contract_id'))}
    abroad_cash_months |= {_month(_day(r.get('date'))) for r in sources['languages'] if _day(r.get('date'))}
    training = {'label': '语培'}
    for metric in ('orders', 'cash'):
        start, end = bi_coverage[f'{metric}_start'], bi_coverage[f'{metric}_end']
        training[f'{metric}_through'] = min(end, _end(month)) if start[:7] <= month <= end[:7] else None
    order_dates = [_day(r.get('date')) for r in sources['resources']
                   if _has_resource_record(r) and _month(_day(r.get('date'))) == month]
    cash_dates = [_day(r.get('archive_date')) for r in sources['contracts']
                  if _text(r.get('contract_id')) and _month(r.get('month')) == month and r.get('archive_date')]
    cash_dates += [_day(r.get('date')) for r in sources['languages'] if _month(_day(r.get('date'))) == month]
    abroad = {'label': '留学（含小语种）', 'connected': month in abroad_order_months or month in abroad_cash_months,
              'orders_through': max(order_dates) if order_dates else None,
              'cash_through': max(cash_dates) if cash_dates else None}
    return {'training': training, 'abroad': abroad}


def _scope_coverage(sources, month, people):
    dates = {scope: {'orders': [], 'cash': []} for scope in PRODUCT_SCOPES}
    for row in sources['resources']:
        if not _has_resource_record(row):
            continue
        day = _day(row.get('date'))
        if not day or _month(day) != month:
            continue
        try:
            scope = _resource_product_scope(row)
        except ValueError:
            # Unowned rows do not establish component coverage or a contribution.
            if not _name(row.get('owner'), people):
                continue
            raise
        dates[scope]['orders'].append(day)
    for row in sources['contracts']:
        if _text(row.get('contract_id')) and _month(row.get('month')) == month:
            if row.get('archive_date'):
                dates['study_abroad']['cash'].append(_day(row['archive_date']))
    for row in sources['languages']:
        day = _day(row.get('date')) if row.get('date') else None
        if day and _month(day) == month:
            dates['small_language']['cash'].append(day)
    return {scope: {metric: max(values) if values else None
                    for metric, values in by_metric.items()}
            for scope, by_metric in dates.items()}


def _metric_values(values, targets, own_connected, output_connected):
    result = {key: {} for key in
              ('self', 'received', 'own_total', 'targets', 'completion', 'self_rate', 'output', 'created_total')}
    for metric in ('orders', 'cash'):
        self_value = values['self'][metric]
        received = values['received'][metric]
        output = values['output'][metric]
        own_total = self_value + received
        for key, value in (('self', self_value), ('received', received), ('own_total', own_total)):
            result[key][metric] = _number(value, metric == 'cash') if own_connected[metric] else None
        result['output'][metric] = _number(output, metric == 'cash') if output_connected[metric] else None
        result['created_total'][metric] = (
            _number(self_value + output, metric == 'cash')
            if own_connected[metric] and output_connected[metric] else None
        )
        result['targets'][metric] = targets.get(metric)
        result['completion'][metric] = (
            float(own_total / Decimal(str(targets[metric])))
            if own_connected[metric] and targets.get(metric) else None
        )
        result['self_rate'][metric] = (
            float(self_value / own_total) if own_connected[metric] and own_total else None
        )
    return result


def _new_totals():
    return defaultdict(lambda: defaultdict(lambda: defaultdict(Decimal)))


def build_contribution(facts, order_rows, people_config, abroad_people_config, sources, months, bi_coverage):
    roster = _roster(people_config, abroad_people_config)
    people = {row['name']: row for row in roster}
    if any(row['business_line'] == 'training+abroad' for row in roster):
        raise ValueError('人员本业务存在双重配置，需明确唯一所属业务')
    offline = {name: row for name, row in people.items()
               if row['abroad_roster'] or 'offline_market' in row['team_ids']}
    diagnostics = Counter()
    _validate_resource_scopes(sources, people)
    status_totals = {mode: _new_totals() for mode in ORDER_STATUS_MODES}
    status_scope_totals = {mode: _new_totals() for mode in ORDER_STATUS_MODES}
    ledger = []
    pending = []
    marker_diagnostics = []
    pending_counts = Counter()
    pending_groups = Counter()
    for event in _events(facts, order_rows, sources, people, diagnostics):
        if event['month'] not in months:
            continue
        allocation = _allocation(event, people)
        if not allocation:
            diagnostics['unattributed_events'] += 1
            if event.get('cross_business_marker'):
                reason = '标记来源人员或明确接收人员未匹配当前名单'
                source = SOURCE_LABELS.get(
                    event['source'], '语培工单' if event['metric'] == 'orders' else '语培现金')
                marker = event['cross_business_marker']
                source_people = {name: person for name, person in people.items()
                                 if person['business_line'] == marker['source_business_line']}
                source_owner = _name(marker.get('source_owner'), source_people)
                receivers = _marker_receivers(event, marker, people)
                affected = sorted({name for name in receivers + [source_owner, event.get('owner')]
                                   if name in offline})
                marker_record = {**{key: event.get(key) for key in (
                    'key', 'source', 'source_row_number', 'month', 'resource_id', 'work_order_id',
                    'line', 'metric', 'product_scope', 'order_status', 'record_key',
                    'origin_sha256', 'origin_filename', 'origin_sheet', 'origin_row_number',
                    'cross_business_marker')},
                    'reason': reason, 'affected_people': affected,
                    'source_label': source, 'source_value': str(event['value']),
                    'campaign_name': event.get('campaign')}
                marker_diagnostics.append(marker_record)
                if affected:
                    pending_allowed = (event['metric'] != 'orders'
                                       or order_status_allowed(
                                           event.get('order_status'), DEFAULT_ORDER_STATUS_MODE))
                    if pending_allowed:
                        pending.append(marker_record)
                        for name in affected:
                            pending_counts[(event['month'], name)] += 1
                            pending_groups[(event['month'], name, source, reason)] += 1
                else:
                    diagnostics['marker_outside_personnel_scope'] += 1
        for name, bucket, weight, rule in allocation:
            if name not in offline:
                continue
            amount = event['value'] * weight
            scopes = PRODUCT_SCOPES if event['product_scope'] == 'training' else (event['product_scope'],)
            order_status = event.get('order_status')
            is_order = event['metric'] == 'orders'
            included = {
                mode: (not is_order or order_status_allowed(order_status, mode))
                for mode in ORDER_STATUS_MODES
            }
            for mode in ORDER_STATUS_MODES:
                if not included[mode]:
                    continue
                status_totals[mode][(event['month'], name)][bucket][event['metric']] += amount
                for scope in scopes:
                    status_scope_totals[mode][(event['month'], name, scope)][bucket][event['metric']] += amount
            marker = event.get('cross_business_marker') or {}
            ledger.append({**{key: event.get(key) for key in (
                'key', 'source', 'source_row_number', 'month', 'resource_id', 'work_order_id',
                'line', 'metric', 'product_scope', 'order_status', 'record_key', 'origin_sha256',
                'origin_filename', 'origin_sheet', 'origin_row_number')},
                'person': name, 'bucket': bucket, 'weight': str(weight),
                'source_value': str(event['value']), 'credited_value': str(amount), 'rule': rule,
                'inclusion': included,
                'cross_business_marker': event.get('cross_business_marker'),
                'marker_source_owner': marker.get('source_owner'),
                'marker_source_key': marker.get('source_key'),
                'marker_source_row_number': marker.get('source_row_number')})
    periods = []
    for month in sorted(set(months)):
        coverage = _coverage(sources, month, bi_coverage)
        scope_coverage = _scope_coverage(sources, month, people)
        rows = []
        for name, person in offline.items():
            own = person['business_line']
            other = 'abroad' if own == 'training' else 'training'
            row = {'name': name, 'business_line': own,
                   'pending_count': pending_counts[(month, name)],
                   'home_group': person['home_group'] if own == 'training' else '留学',
                   'peer_group': own + '|' + (person['home_group'] if own == 'training' else '留学')}
            targets = person['targets'][own].get(month) or {}
            own_connected = {
                metric: (sources['resources_connected'] if own == 'abroad'
                         else bool(coverage[own][f'{metric}_through']))
                for metric in ('orders', 'cash')
            }
            output_connected = {
                metric: (sources['resources_connected'] if other == 'abroad'
                         else bool(coverage[other][f'{metric}_through']))
                for metric in ('orders', 'cash')
            }
            row['order_status_views'] = {}
            for mode in ORDER_STATUS_MODES:
                view = _metric_values(
                    status_totals[mode][(month, name)], targets,
                    own_connected, output_connected,
                )
                view['breakdowns'] = {}
                for scope in PRODUCT_SCOPES:
                    if own == 'training':
                        component_own_connected = own_connected
                        component_output_connected = {
                            metric: sources['resources_connected']
                            for metric in ('orders', 'cash')
                        }
                    else:
                        component_own_connected = {
                            metric: sources['resources_connected']
                            for metric in ('orders', 'cash')
                        }
                        component_output_connected = output_connected
                    view['breakdowns'][scope] = _metric_values(
                        status_scope_totals[mode][(month, name, scope)], targets,
                        component_own_connected, component_output_connected,
                    )
                row['order_status_views'][mode] = view
            default_view = row['order_status_views'][DEFAULT_ORDER_STATUS_MODE]
            for key in ('self', 'received', 'own_total', 'targets', 'completion',
                        'self_rate', 'output', 'created_total'):
                row[key] = dict(default_view[key])
            row['breakdowns'] = {
                scope: {bucket: dict(values) for bucket, values in breakdown.items()}
                for scope, breakdown in default_view['breakdowns'].items()
            }
            rows.append(row)
        periods.append({'id': month, 'label': month[:4] + '年' + str(int(month[5:])) + '月',
                        'coverage': coverage, 'people': rows,
                        'pending_count': sum(record['month'] == month for record in pending),
                        'pending': [{'name': name, 'source': source, 'reason': reason, 'count': count}
                                    for (m, name, source, reason), count in sorted(pending_groups.items()) if m == month]})
    return ({'schema_version': 'personnel_contribution.v1', 'periods': periods},
            {'schema_version': 'personnel_contribution_details.v1', 'records': ledger, 'pending': pending,
             'marker_diagnostics': marker_diagnostics,
             'diagnostics': dict(diagnostics), 'source_hashes': sources['source_hashes']})
