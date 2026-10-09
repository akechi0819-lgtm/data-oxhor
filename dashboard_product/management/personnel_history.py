"""读取并应用业务确认的留学人员历史月度产能。"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path


HISTORY_FILENAME = '留学人员历史产能.xlsx'
SHEET_NAME = 'FY27市场人员产能'
MONTH_BLOCKS = (
    ('2026-06', 11, '6月'),
    ('2026-07', 19, '7月'),
    ('2026-08', 27, '8月'),
    ('2026-09', 35, '9月'),
)
PERSON_ROWS = range(13, 21)
PERSON_GROUP = '线下-高校组'


def _text(value):
    return '' if value is None else str(value).replace('\n', '').strip()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value, cell: str, *, cash: bool = False):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f'历史产能数值无效：{cell}')
    try:
        number = Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise ValueError(f'历史产能数值无效：{cell}') from exc
    if not number.is_finite():
        raise ValueError(f'历史产能数值必须为有限数：{cell}')
    if cash:
        number *= Decimal('10000')
    return int(number) if number == number.to_integral_value() else float(number)


def _validate_headers(ws):
    if _text(ws['B1'].value) != '人员' or _text(ws['C1'].value) != 'FY27':
        raise ValueError('历史产能表头无效：B1须为人员，C1须为FY27')
    for month, start, month_label in MONTH_BLOCKS:
        if _text(ws.cell(1, start).value) != month_label:
            raise ValueError(f'历史产能月份表头无效：{ws.cell(1, start).coordinate}')
        abroad_label = _text(ws.cell(2, start + 2).value)
        training_label = _text(ws.cell(2, start + 3).value)
        total_order_label = _text(ws.cell(2, start + 4).value)
        if '总留学' not in abroad_label or '总语培' not in training_label:
            raise ValueError(f'历史产能业务线表头无效：{month_label}')
        if month != '2026-09' and not all(
                '工单' in label for label in (abroad_label, training_label, total_order_label)):
            raise ValueError(f'历史产能工单表头无效：{month_label}')
        if month == '2026-09' and not all(
                '资源' in label for label in (abroad_label, training_label, total_order_label)):
            raise ValueError('9月历史产能来源表头无效')
        for col, expected in ((start + 5, '留学签约'), (start + 6, '语培签约'),
                              (start + 7, '总签约金额')):
            if expected not in _text(ws.cell(2, col).value):
                raise ValueError(f'历史产能签约表头无效：{ws.cell(2, col).coordinate}')
        if month == '2026-06' and any(
                '万元' not in _text(ws.cell(2, col).value) for col in (start + 5, start + 6)):
            raise ValueError('6月留学及小语种签约金额单位须为万元')
    if _text(ws['A13'].value) != PERSON_GROUP:
        raise ValueError(f'历史产能人员组别无效：A13须为{PERSON_GROUP}')


def load_history(path: Path):
    """只读加载客户副本中的历史结果；客户未提供该可选文件时返回None。"""
    path = Path(path)
    if not path.is_file():
        return None

    import openpyxl
    from openpyxl.utils import get_column_letter

    source_sha256 = _digest(path)
    formulas_book = openpyxl.load_workbook(path, read_only=True, data_only=False)
    values_book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET_NAME not in formulas_book.sheetnames or SHEET_NAME not in values_book.sheetnames:
            raise ValueError(f'历史产能工作簿缺少工作表：{SHEET_NAME}')
        formulas = formulas_book[SHEET_NAME]
        values = values_book[SHEET_NAME]
        formulas.reset_dimensions()
        values.reset_dimensions()
        _validate_headers(values)

        inherited_group = ''
        people = []
        for row in PERSON_ROWS:
            group_value = _text(values.cell(row, 1).value)
            if group_value:
                inherited_group = group_value
            name = _text(values.cell(row, 2).value)
            if name and inherited_group == PERSON_GROUP:
                people.append((row, name))
        names = [name for _, name in people]
        if len(names) != len(set(names)):
            raise ValueError('历史产能表中线下高校组人员姓名重复')

        rows = []
        for month, start, _ in MONTH_BLOCKS:
            for row, name in people:
                cell_map = {
                    'components.study_abroad.orders': start + 2,
                    'components.small_language.orders': start + 3,
                    'source_total.orders': start + 4,
                    'components.study_abroad.cash': start + 5,
                    'components.small_language.cash': start + 6,
                    'source_total.cash': start + 7,
                }
                metrics = {'components': {'study_abroad': {}, 'small_language': {}},
                           'source_total': {}}
                source_cells = {}
                source_labels = {}
                for key, col in cell_map.items():
                    cell = formulas.cell(row, col)
                    value = values.cell(row, col).value
                    coordinate = f'{get_column_letter(col)}{row}'
                    if cell.data_type == 'f' and value is None:
                        raise ValueError(f'历史产能公式缺少缓存值：{coordinate}')
                    bucket, metric = key.split('.', 1)
                    if bucket == 'components':
                        component, metric = metric.split('.', 1)
                        metrics[bucket][component][metric] = _number(
                            value, coordinate, cash=metric == 'cash')
                    else:
                        metrics[bucket][metric] = _number(
                            value, coordinate, cash=metric == 'cash')
                    source_cells[key] = coordinate
                    source_labels[key] = _text(values.cell(2, col).value)
                rows.append({'month': month, 'name': name, **metrics,
                             'source_labels': source_labels,
                             'source_cells': source_cells})
    finally:
        formulas_book.close()
        values_book.close()

    if _digest(path) != source_sha256:
        raise ValueError('历史产能输入在读取过程中发生变化')
    return {'source_path': str(path), 'source_sha256': source_sha256,
            'sheet': SHEET_NAME, 'rows': rows}


def _completion(actual, target):
    if actual is None or target is None:
        return None
    denominator = Decimal(str(target))
    if not denominator.is_finite() or denominator == 0:
        return None
    return float(Decimal(str(actual)) / denominator)


def _component_sum(components, metric):
    values = [components[name].get(metric) for name in ('study_abroad', 'small_language')]
    if any(value is None for value in values):
        return None
    total = sum((Decimal(str(value)) for value in values), Decimal(0))
    return int(total) if total == total.to_integral_value() else float(total)


def _breakdown(component, targets, output):
    unknown = {'orders': None, 'cash': None}
    return {
        'self': dict(unknown),
        'received': dict(unknown),
        'self_rate': dict(unknown),
        'created_total': dict(unknown),
        'own_total': dict(component),
        'targets': dict(targets),
        'completion': {metric: _completion(component.get(metric), targets.get(metric))
                       for metric in ('orders', 'cash')},
        'output': dict(output),
    }


def apply_history(capacity, history):
    """用业务确认结果覆盖6–8月已配置的留学人员行。"""
    if not history:
        return None

    by_month = {}
    for item in history.get('rows', []):
        if item.get('month') in ('2026-06', '2026-07', '2026-08'):
            by_month.setdefault(item['month'], {})[item['name']] = item

    adopted = 0
    for period in capacity.get('periods', []):
        month = period.get('id')
        month_history = by_month.get(month)
        if not month_history:
            continue
        adopted_names = []
        for person in period.get('people', []):
            name = person.get('name')
            item = month_history.get(name)
            if not item or person.get('business_line') != 'abroad':
                continue
            components = item['components']
            person['own_total'] = {
                metric: _component_sum(components, metric) for metric in ('orders', 'cash')
            }
            for bucket in ('self', 'received', 'self_rate', 'created_total'):
                person[bucket] = {'orders': None, 'cash': None}
            targets = person.get('targets') or {}
            person['completion'] = {
                metric: _completion(person['own_total'].get(metric), targets.get(metric))
                for metric in ('orders', 'cash')
            }
            output = dict(person.get('output') or {'orders': None, 'cash': None})
            person['breakdowns'] = {
                name: _breakdown(component, targets, output)
                for name, component in components.items()
            }
            for mode, status_view in (person.get('order_status_views') or {}).items():
                status_output = dict(status_view.get('output') or {'orders': None, 'cash': None})
                status_view['own_total'] = dict(person['own_total'])
                status_view['completion'] = dict(person['completion'])
                for bucket in ('self', 'received', 'self_rate', 'created_total'):
                    status_view[bucket] = {'orders': None, 'cash': None}
                status_view['breakdowns'] = {
                    name: _breakdown(component, targets, status_output)
                    for name, component in components.items()
                }
            person['pending_count'] = 0
            person['source_kind'] = 'confirmed_history'
            adopted_names.append(name)
            adopted += 1

        if not adopted_names:
            continue
        coverage = period.setdefault('coverage', {})
        coverage['history'] = {'label': '留学及小语种历史结果',
                               'adopted_people': adopted_names,
                               'split_available': False,
                               'order_status_detail_available': False}
        coverage.setdefault('abroad', {})['connected'] = True
        # The period total counts unique pending events, while the detail is
        # grouped by person and can repeat an event. Keep its original count.
        if isinstance(period.get('pending'), list):
            period['pending'] = [entry for entry in period['pending']
                                 if entry.get('name') not in set(adopted_names)]
    return {'adopted_rows': adopted}
