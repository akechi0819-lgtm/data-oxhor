"""Superset dataset catalogue backed by the flat SQL warehouse.

The legacy catalog is loaded only for its presentation contract (key, columns,
filters and chart options). Its JSON warehouse SQL is never returned here.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class DatasetSQL:
    key: str
    title: str
    page: str
    section: str
    columns: tuple[str, ...]
    filters: dict
    sql: str | None
    unsupported: str | None = None
    viz: str = 'table'
    more: dict | None = None
    contract: object | None = None


def _q(value):
    return '"' + value.replace('"', '""') + '"'


def _lit(value):
    return "'" + value.replace("'", "''") + "'"


def _line(value):
    return f"CASE {value} WHEN 'training' THEN '语培' WHEN 'abroad' THEN '留学及小语种' ELSE {value} END"


def _status(value):
    return (f"CASE {value} WHEN 'available' THEN '已提供' WHEN 'partial' THEN '部分覆盖' "
            "WHEN 'missing' THEN '未提供' WHEN 'not_covered' THEN '该期间未覆盖' "
            "WHEN 'not_connected' THEN '未接入' WHEN 'not_configured' THEN '未配置' "
            "WHEN 'future' THEN '尚未开始' WHEN 'separate_counts' THEN '分域人数' "
            "WHEN 'zero_denominator' THEN '分母为零' WHEN 'over_100_percent' THEN '超过100%' "
            f"ELSE {value} END")


def _presentation_double(expression):
    """Keep legacy DOUBLE results without rounding DECIMAL through a cast."""
    return f"CAST(CAST({expression} AS VARCHAR) AS DOUBLE)"


def _presentation_bigint(expression):
    return f"CAST({expression} AS BIGINT)"


def _presentation_cash(expression):
    return f"CAST({expression} AS DECIMAL(24,2))"


_ACQUISITION = """{% set acquisition = filter_values('语培统计范围', remove_filter=True) %}
{% set acquisition_scope = acquisition[0] if acquisition|length == 1 and acquisition[0] in ['被动','主动','全部'] else '被动' %}
"""
_PREP_SELECTION = """{% set groups = filter_values('业务组', remove_filter=True) %}
{% set mask = (1 if '青少' in groups else 0) + (2 if '初中' in groups else 0) + (4 if '高中' in groups else 0) %}
{% set group_label = groups|join('、') %}
"""
_OVERVIEW_SELECTION = """{% set overview_units = filter_values('管理单元', remove_filter=True) %}
{% set overview_label = overview_units[0] if overview_units|length == 1 and overview_units[0] in ['市场总计','高中','大学','留学预备'] else '市场总计' %}
{% set overview_unit_id = {'市场总计':'total','高中':'overview_high','大学':'overview_university','留学预备':'overview_prep'}.get(overview_label,'total') %}
"""
_OVERVIEW_STUDENT_SELECTION = """{% set student_types = filter_values('新老生', remove_filter=True) %}
{% set student_label = student_types[0] if student_types|length == 1 and student_types[0] in ['全部','新生','老生'] else '全部' %}
{% set student_suffix = '|' ~ student_label if student_label in ['新生','老生'] else '' %}
"""


def _overview_scopes(base="'{{ acquisition_scope }}'"):
    """Return selected and unsuffixed scopes for overview's mixed training/abroad rows."""
    return ("list_value(" + base +
            "{% if student_suffix %}," + base + "||'{{ student_suffix }}'{% endif %})::VARCHAR[]")


def _overview_training_scope_match(alias, *, business_line='business_line'):
    """Use the selected student grain for training while leaving abroad unchanged."""
    return (f"(({business_line}='training' AND {alias}.acquisition_scope="
            "'{{ acquisition_scope }}{{ student_suffix }}') OR "
            f"({business_line}<>'training' AND {alias}.acquisition_scope='{{{{ acquisition_scope }}}}'))")


def _metadata():
    """Load legacy presentation metadata with local-only sentinel paths."""
    local = {
        'SHADOW_BI_AUDIT': str(ROOT / '.local/sql-migration/candidate/audit'),
        'SHADOW_BI_LIBRARY': str(ROOT / '.local/sql-migration/candidate/library'),
        'SHADOW_BI_BATCH': 'run_shadow_daily_20261106',
        'SHADOW_BI_SOURCE_LIBRARY': str(ROOT / '.local/sql-migration/candidate/source'),
        'SHADOW_BI_SOURCE_BATCH': 'run_shadow_daily_20261106_business',
    }
    with patch.dict(os.environ, local):
        p3 = importlib.import_module('dashboard_product.shadow_bi.p3.catalog')
        native = importlib.import_module('dashboard_product.shadow_bi.p35.native_catalog')
        base = [deepcopy(view) for view in p3.VIEWS]
        original_keys = {view.key for view in base}
        base.extend(deepcopy(view) for view in native.native_views()
                    if view.key not in original_keys)
    return base


def _period_filter(column='期间'):
    return ("{% set periods = filter_values('" + column + "', remove_filter=True) %}"
            "{% if periods %} AND period_id IN {{ periods|where_in }} {% endif %}")


def _acquisition_filter():
    return _ACQUISITION


def _unit(page, alias='unit_id'):
    if page == 'overview':
        return f"{alias} IN ('total','overview_prep','overview_high','overview_university')"
    if page == 'virtual':
        return f"{alias}='virtual'"
    if page == 'prep':
        return f"{alias}='selection_'||CAST({{{{ mask }}}} AS VARCHAR)"
    if page == 'university':
        return f"{alias}='university'"
    if page == 'online':
        return f"{alias}='online'"
    raise ValueError(page)


def _unit_label(alias='unit_id', page=None):
    labels = [f"WHEN {alias}='total' THEN '市场总计'",
              f"WHEN {alias}='overview_prep' THEN '留学预备'",
              f"WHEN {alias}='overview_high' THEN '高中'",
              f"WHEN {alias}='overview_university' THEN '大学'",
              f"WHEN starts_with({alias},'selection_') THEN 'prep_high'"]
    return 'CASE ' + ' '.join(labels) + f' ELSE {alias} END'


def _dimension_query_source(page, dimensions, *, period_name='期间', scope="['{{ acquisition_scope }}']::VARCHAR[]",
                           units=None):
    if units is None:
        units = {
            'overview': "['total','overview_prep','overview_high','overview_university']::VARCHAR[]",
            'virtual': "['virtual']::VARCHAR[]",
            'prep': "list_value('selection_'||CAST({{ mask }} AS VARCHAR))::VARCHAR[]",
            'university': "['university']::VARCHAR[]",
            'online': "['online']::VARCHAR[]",
        }[page]
    period_filter = ("{% set requested_periods=filter_values('"+period_name+"') %}"
                     "{% if requested_periods %}list_value{{ requested_periods|where_in }}::VARCHAR[]{% else %}NULL::VARCHAR[]{% endif %}") if period_name else 'NULL::VARCHAR[]'
    return ("business.dimension_query("+period_filter+","
            +units+","+scope+","+repr(list(dimensions))+"::VARCHAR[])")


def _overview_line_unit(alias='unit_id', line='business_line'):
    """Use the selected training scope and the unchanged total abroad scope."""
    return (f"(({line}='training' AND {alias}='{{{{ overview_unit_id }}}}') OR "
            f"({line}='abroad' AND {alias}='total'))")


def _overview_line_label(alias='unit_id', line='business_line'):
    """Keep total abroad rows visible under the selected overview filter label."""
    return (f"CASE WHEN {line}='abroad' THEN '{{{{ overview_label }}}}' "
            f"ELSE {_unit_label(alias, 'overview')} END")


def _status_metrics(actual='actual', prior='prior', target='target', status='status', progress='time_progress'):
    yoy = f"CASE WHEN {actual} IS NOT NULL AND {prior} IS NOT NULL AND {prior}<>0 THEN {actual}/{prior}-1 END"
    completion = f"CASE WHEN {actual} IS NOT NULL AND {target} IS NOT NULL AND {target}<>0 THEN {actual}/{target} END"
    gap = f"CASE WHEN {status}='partial' THEN NULL WHEN {actual} IS NOT NULL AND {target} IS NOT NULL THEN ROUND({actual}-{target},2) END"
    time_gap = f"CASE WHEN {status}='partial' THEN NULL WHEN {actual} IS NOT NULL AND {target} IS NOT NULL THEN ROUND({actual}-{target}*{progress},2) END"
    return yoy, completion, gap, time_gap


def _metric_projection(*, metric='metric', actual='actual', prior='prior', target='target',
                       status='status', progress='time_progress', display='display', note='note',
                       metric_filter=True):
    yoy, completion, gap, time_gap = _status_metrics(actual, prior, target, status, progress)
    fields = [
        f"CASE {metric} WHEN 'orders' THEN '工单' WHEN 'cash' THEN '现金（元）' WHEN 'heads' THEN '人头' ELSE {metric} END AS 指标",
        f'{_presentation_double(actual)} AS 当期', f'{display} AS 呈现',
        f'{_presentation_double(prior)} AS 同期', f'{yoy} AS 同比',
        (f"CASE WHEN {status} IN ('partial','not_covered','separate_counts') THEN '不可同比' "
         f"WHEN {prior} IS NULL OR {yoy} IS NULL THEN '无同期同比' ELSE '可比' END AS 同期状态"),
        f'{_presentation_double(target)} AS 目标', f"CASE WHEN {target} IS NULL THEN '未配置' ELSE '已配置' END AS 目标配置",
        f'{completion} AS 完成率', f'{_presentation_double(gap)} AS 目标差额', f'{time_gap} AS 时间进度差额',
        f'{_status(status)} AS 状态', f"COALESCE({note},'') AS 口径",
    ]
    return fields


def _metric_row_sql(source, *, where='TRUE', dimensions=(), metric='metric', actual='actual',
                    prior='prior', target='target', status='status', progress='time_progress',
                    display='display', note='note', extra=(), metric_filter=True):
    return ('SELECT ' + ', '.join([*dimensions, *_metric_projection(
        metric=metric, actual=actual, prior=prior, target=target, status=status,
        progress=progress, display=display, note=note, metric_filter=metric_filter), *extra]) +
            ' FROM ' + source + ' WHERE ' + where)


def _team_source(page, line_filter=None):
    prefix = (_PREP_SELECTION if page == 'prep' else
              _OVERVIEW_SELECTION + _OVERVIEW_STUDENT_SELECTION if page == 'overview' else '')
    scoped_line = line_filter or ('training' if page == 'prep' else None)
    line_clause = f" AND t.business_line='{scoped_line}'" if scoped_line else ''
    unit_expr = (_overview_line_unit('t.unit_id', 't.business_line') if page == 'overview'
                 else _unit(page, 't.unit_id'))
    unit_label = (_overview_line_label('t.unit_id', 't.business_line') if page == 'overview'
                  else _unit_label('t.unit_id', page))
    acquisition = _acquisition_filter()
    # team_values is the source of split-head presentation; it has one actual
    # row per team metric key and keeps the two abroad domains separate.
    source = ("(SELECT tm.*,tv.study_heads,tv.language_heads FROM business.team_metrics tm "
              "LEFT JOIN business.team_values tv ON tv.period_id=tm.period_id AND tv.unit_id=tm.unit_id "
              "AND tv.acquisition_scope=tm.acquisition_scope AND tv.business_line=tm.business_line "
              "AND tv.comparison='actual') t")
    actual_display = ("CASE WHEN t.metric='heads' AND t.status='separate_counts' THEN "
                      "'留学'||CAST(t.study_heads AS BIGINT)::VARCHAR||'人／小语种'||"
                      "CAST(t.language_heads AS BIGINT)::VARCHAR||'人' END")
    dimensions = ["t.period_id AS 期间", f'{unit_label} AS 管理单元',
                  f'{_line("t.business_line")} AS 业务线']
    extra = (["NULL::VARCHAR AS 业务组"] if page == 'prep' else [])
    extra.append("'{{ acquisition_scope }}' AS 语培统计范围")
    scope_clause = (_overview_training_scope_match('t', business_line='t.business_line')
                    if page == 'overview' else "t.acquisition_scope='{{ acquisition_scope }}'")
    sql = (prefix + acquisition + _metric_row_sql(
        source, where=f"{unit_expr}{line_clause} AND {scope_clause}",
        dimensions=dimensions, metric='t.metric', actual='t.actual', prior='t.prior',
        target='t.target', status='t.status', progress='t.time_progress', display=actual_display,
        note='t.note', extra=extra) +
        " AND t.metric IN ('orders','cash','heads')")
    return sql


def _dimension_sql(page, dimension_type, *, detail=False, country=False, business_line=None, push_period_filter=True):
    prefix = (_PREP_SELECTION if page == 'prep' else
              _OVERVIEW_SELECTION if page == 'overview' else '')
    if country:
        table = 'business.dimension_countries' if detail else 'business.dimension_country_groups'
        extra_keys = ['country'] if detail else []
        unit_label = "'市场总计'" if page == 'overview' else _unit_label('d.unit_id', page)
        unit_filter = "d.unit_id='total'" if page == 'overview' else _unit(page, 'd.unit_id')
        dims = ["d.period_id AS 期间", f"{unit_label} AS 管理单元",
                "d.line AS 条线"]
        if detail:
            dims.append('d.country AS 国家')
        measures = ['online', 'offline', 'unassigned', 'total']
        fields = [f'd.{name} AS '+_q(label) for name, label in zip(measures, ['线上','线下','待确认','合计'])]
        sql = (prefix + _ACQUISITION + 'SELECT ' + ', '.join([*dims, *fields]) +
               f' FROM {table} d WHERE {unit_filter} '
               "AND d.acquisition_scope='{{ acquisition_scope }}'")
        return sql
    unit_clause = (_overview_line_unit('d.unit_id', 'd.business_line') if page == 'overview'
                   else _unit(page, 'd.unit_id'))
    unit_label = (_overview_line_label('d.unit_id', 'd.business_line') if page == 'overview'
                  else _unit_label('d.unit_id', page))
    where = [f"d.dimension_type='{dimension_type}'", unit_clause]
    scope_source = (_overview_scopes() if page == 'overview'
                    else "['{{ acquisition_scope }}']::VARCHAR[]")
    if page == 'overview':
        where.append(_overview_training_scope_match('d', business_line='d.business_line'))
    else:
        where.append("d.acquisition_scope='{{ acquisition_scope }}'")
    if business_line:
        where.append(f"d.business_line='{business_line}'")
    dims = ["d.period_id AS 期间", f"{unit_label} AS 管理单元",
            f"{_line('d.business_line')} AS 业务线"]
    # Preserve established P3 label spelling and ordering.
    if dimension_type in ('channel','channel_group','channel_school'):
        dims += ['d.dim1 AS 渠道', "CASE WHEN d.first_channel='∅' THEN NULL ELSE d.first_channel END AS 一级渠道"]
        if dimension_type != 'channel':
            dims.append('d.dim2 AS 业务组名称' if dimension_type == 'channel_group' else 'd.dim2 AS 学校类别')
        if dimension_type == 'channel_school':
            dims.append('d.dim3 AS 学校')
    elif dimension_type in ('school','school_grade'):
        dims.append('d.dim1 AS 学校')
        if dimension_type == 'school_grade':
            dims.append('d.dim2 AS 年级')
    elif dimension_type == 'grade':
        dims.append('d.dim1 AS 年级')
    elif dimension_type in ('business_group','comparison_group'):
        dims.append('d.dim1 AS 业务组名称')
    dimensions = ', '.join(dims)
    extra = []
    # Flat dimension columns are already calculated by the warehouse SQL.
    for metric, label, field in [
        ('orders','工单','actual'),('orders','工单同期','prior'),('orders','工单同比','yoy'),
        ('cash','现金','actual'),('cash','现金同期','prior'),('cash','现金同比','yoy'),
        ('heads','人头','actual'),('heads','人头同期','prior'),('heads','人头同比','yoy'),
        ('orders','工单占比','share'),('cash','现金占比','cash_share'),('heads','分域人数','display'),
        ('orders','工单状态','status'),('cash','现金状态','status'),('heads','人数状态','status'),
    ]:
        expression = f'MAX({_status("d."+field)})' if field == 'status' else f'MAX(d.{field})'
        extra.append(f"{expression} FILTER(WHERE d.metric='{metric}') AS {_q(label)}")
    extra.append("CASE WHEN MAX(d.yoy) FILTER(WHERE d.metric='orders') IS NULL THEN '无同期同比' ELSE '可比' END AS 同期状态")
    if dimension_type in ('channel_group','channel_school'):
        extra.append("MAX(d.channel_cash_share) FILTER(WHERE d.metric='cash') AS 渠道内现金占比")
    if dimension_type in ('grade',):
        extra.append("CASE d.dim1 " + ' '.join(f"WHEN {_lit(name)} THEN {i}" for i,name in enumerate([
            '学龄前','幼儿','幼儿园小班','幼儿园中班','幼儿园大班','一年级','二年级','三年级','四年级','五年级','六年级',
            '初一','初二','初三','高一','高二','高三','10年级(国外高中)','11年级(国外高中)','12年级(国外高中)',
            '13年级(国外高中)','大一','大二','大三','大四','大五','研一','研二','研三','研究生以上','博一','博二',
            '博士在读','博士毕业','大学已毕业','在职','年级待确认'])) + ' ELSE 999 END AS 年级顺序')
    source = _dimension_query_source(page,[dimension_type],scope=scope_source,
                                     period_name='期间' if push_period_filter else None)
    if page == 'prep':
        extra.append("NULL::VARCHAR AS 业务组")
    extra.append("'{{ acquisition_scope }}' AS 语培统计范围")
    group_by = ', '.join(str(i+1) for i in range(len(dims)))
    student_selection = _OVERVIEW_STUDENT_SELECTION if page == 'overview' else ''
    sql = (prefix + _ACQUISITION + student_selection + 'SELECT ' + dimensions + ', ' + ', '.join(extra) +
           ' FROM ' + source + ' d WHERE ' + ' AND '.join(where) +
           " AND d.metric IN ('orders','cash','heads') GROUP BY " + group_by)
    return sql


def _school_pairs_sql(page):
    """Return the legacy school row with exact parent and grade measures."""
    prefix = _PREP_SELECTION if page == 'prep' else _OVERVIEW_SELECTION if page == 'overview' else ''
    prefix += _ACQUISITION
    unit = (_overview_line_unit('d.unit_id', 'd.business_line') if page == 'overview'
            else _unit(page, 'd.unit_id'))
    scope_source = (_overview_scopes() if page == 'overview'
                    else "['{{ acquisition_scope }}']::VARCHAR[]")
    selection_filter = (" AND d.business_line='training'" if page == 'prep' else '')

    def pivot(alias, prefix_name):
        columns = []
        for label, metric, field in [
            ('工单','orders','actual'),('工单同期','orders','prior'),('工单同比','orders','yoy'),
            ('现金','cash','actual'),('现金同期','cash','prior'),('现金同比','cash','yoy'),
            ('人头','heads','actual'),('人头同期','heads','prior'),('人头同比','heads','yoy'),
            ('工单占比','orders','share'),('现金占比','cash','cash_share'),
        ]:
            columns.append(f"MAX({alias}.{field}) FILTER(WHERE {alias}.metric='{metric}') AS {_q(prefix_name+label)}")
        for label, metric, field in [('分域人数','heads','display'),('工单状态','orders','status'),
                                     ('现金状态','cash','status'),('人数状态','heads','status')]:
            value = f"MAX({alias}.{field}) FILTER(WHERE {alias}.metric='{metric}')"
            columns.append(f"{value} AS {_q(prefix_name+label)}")
        return columns

    parent = ','.join(pivot('d','父'))
    child = ','.join(pivot('d','子'))
    keys = "period_id,unit_id,acquisition_scope,business_line,dim1"
    parent_cte = ("parents AS (SELECT d.period_id,d.unit_id,d.acquisition_scope,d.business_line,d.dim1 AS school,"+parent+
                  " FROM scoped d WHERE d.dimension_type='school' GROUP BY "+keys+")")
    child_cte = ("children AS (SELECT d.period_id,d.unit_id,d.acquisition_scope,d.business_line,d.dim1 AS school,d.dim2 AS grade,"+child+
                 " FROM scoped d WHERE d.dimension_type='school_grade' GROUP BY "+keys+",d.dim2)")
    unit_label = (_overview_line_label('p.unit_id', 'p.business_line') if page == 'overview'
                  else _unit_label('p.unit_id', page))
    fields = ["p.period_id AS 期间",f"{unit_label} AS 管理单元",
              f"{_line('p.business_line')} AS 业务线",'p.school AS 学校','c.grade AS 年级']
    measure_labels = [
        '工单','工单同期','工单同比','现金','现金同期','现金同比','人头','人头同期','人头同比','工单占比','现金占比',
        '分域人数','工单状态','现金状态','人数状态']
    fields += [f'{alias}.{_q(prefix+label)}' for label in measure_labels
               for alias,prefix in [('p','父'),('c','子')]]
    if page == 'prep':
        fields.append('NULL::VARCHAR AS 业务组')
    fields.append("'{{ acquisition_scope }}' AS 语培统计范围")
    source = _dimension_query_source(page,['school','school_grade'],scope=scope_source)
    scope_filter = (_overview_training_scope_match('d', business_line='d.business_line')
                    if page == 'overview' else "d.acquisition_scope='{{ acquisition_scope }}'")
    scoped_projection = ("d.* REPLACE (split_part(d.acquisition_scope,'|',1) AS acquisition_scope)"
                         if page == 'overview' else 'd.*')
    cte = ("WITH scoped AS (SELECT "+scoped_projection+" FROM "+source+" d WHERE "+unit+
           selection_filter+" AND "+scope_filter+"), "+
           parent_cte+","+child_cte+" SELECT "+','.join(fields)+" FROM parents p JOIN children c ON "+
           "p.period_id=c.period_id AND p.unit_id=c.unit_id AND p.acquisition_scope=c.acquisition_scope "
           "AND p.business_line=c.business_line AND p.school=c.school")
    student_selection = _OVERVIEW_STUDENT_SELECTION if page == 'overview' else ''
    return prefix+student_selection+cte


def _school_tree_raw_sql(page):
    """Flat wide rows used by the legacy native school-tree renderer."""
    units = {
        'overview': "list_value('{{ overview_unit_id }}','total')::VARCHAR[]",
        'virtual': "['virtual']::VARCHAR[]",
        'prep': "list_value('selection_'||CAST({{ mask }} AS VARCHAR))::VARCHAR[]",
    }
    if page not in units:
        raise ValueError(f'unsupported school tree page: {page}')
    scope_filter = '学校主被动' if page == 'overview' else '语培统计范围'
    default_scope = '全部' if page == 'overview' else '被动'
    prefix = (_OVERVIEW_SELECTION if page == 'overview' else '') + ("{% set periods=filter_values('期间',remove_filter=True) %}"
              "{% set chosen_period=periods[0] if periods|length==1 else 'FY27' %}"
              "{% set selected=filter_values("+repr(scope_filter)+",remove_filter=True) %}"
              "{% set acquisition_scope=selected[0] if selected|length==1 and selected[0] in ['全部','主动','被动'] else "+repr(default_scope)+" %}")
    if page == 'overview':
        prefix += _OVERVIEW_STUDENT_SELECTION
    if page == 'prep':
        prefix += ("{% set groups=filter_values('业务组',remove_filter=True) %}"
                   "{% set mask=(1 if '青少' in groups else 0)+(2 if '初中' in groups else 0)+(4 if '高中' in groups else 0) %}")
    if page == 'overview':
        scope_source = ("{% if student_suffix %}"
                        "['全部','主动','被动','全部{{ student_suffix }}','主动{{ student_suffix }}','被动{{ student_suffix }}']::VARCHAR[]"
                        "{% else %}['全部','主动','被动']::VARCHAR[]{% endif %}")
        source = ("(SELECT d.* REPLACE (split_part(d.acquisition_scope,'|',1) AS acquisition_scope) "
                  "FROM business.dimension_query(['{{ chosen_period }}']::VARCHAR[],"+units[page]+
                  ","+scope_source+",['school','school_grade']::VARCHAR[]) d WHERE "
                  "((d.business_line='training' AND d.acquisition_scope IN ('全部{{ student_suffix }}','主动{{ student_suffix }}','被动{{ student_suffix }}')) "
                  "OR (d.business_line='abroad' AND d.acquisition_scope IN ('全部','主动','被动'))))")
    else:
        source = ("business.dimension_query(['{{ chosen_period }}']::VARCHAR[],"+units[page]+
                  ",[ '全部','主动','被动']::VARCHAR[],['school','school_grade']::VARCHAR[])")
    prep_filter = " AND business_line='training'" if page == 'prep' else ''
    overview_filter = (" WHERE ((unit_id='{{ overview_unit_id }}' AND business_line='training') "
                       "OR (unit_id='total' AND business_line='abroad'))" if page == 'overview' else '')

    def measures(alias, prefix):
        fields=[]
        for label,metric,field in [
            ('工单','orders','actual'),('工单同期','orders','prior'),('工单同比','orders','yoy'),
            ('现金','cash','actual'),('现金同期','cash','prior'),('现金同比','cash','yoy'),
            ('人头','heads','actual'),('人头同期','heads','prior'),('人头同比','heads','yoy'),
            ('工单占比','orders','share'),('现金占比','cash','cash_share'),('分域人数','heads','display'),
        ]:
            fields.append(f"MAX({alias}.{field}) FILTER(WHERE {alias}.metric='{metric}') AS {_q(prefix+label)}")
        return ','.join(fields)

    parent = ("parents AS (SELECT d.period_id,d.unit_id,d.acquisition_scope,d.business_line,d.dim1 AS school,"+
              measures('d','父')+" FROM scoped d WHERE d.dimension_type='school'"+prep_filter+
              " GROUP BY d.period_id,d.unit_id,d.acquisition_scope,d.business_line,d.dim1)")
    child = ("children AS (SELECT d.period_id,d.unit_id,d.acquisition_scope,d.business_line,d.dim1 AS school,d.dim2 AS grade,"+
             measures('d','子')+" FROM scoped d WHERE d.dimension_type='school_grade'"+prep_filter+
             " GROUP BY d.period_id,d.unit_id,d.acquisition_scope,d.business_line,d.dim1,d.dim2)")
    fields = [
        "p.period_id AS 期间", ("p.unit_id AS 管理单元" if page == 'virtual' else
                                  f"{_overview_line_label('p.unit_id', 'p.business_line')} AS 管理单元" if page == 'overview'
                                  else f"{_unit_label('p.unit_id', page)} AS 管理单元"),
        f"{_line('p.business_line')} AS 业务线",
        "CASE WHEN p.business_line='training' THEN p.acquisition_scope ELSE '不区分' END AS 主被动",
        "p.school AS 学校", "c.grade AS 年级", "'{{ acquisition_scope }}' AS 语培统计范围",
        "p.acquisition_scope AS 节点范围",
    ]
    measure_labels=['工单','工单同期','工单同比','现金','现金同期','现金同比','人头','人头同期','人头同比','工单占比','现金占比','分域人数']
    fields.extend(f'{alias}.{_q(prefix+label)} AS {_q(prefix+label)}'
                  for label in measure_labels for alias,prefix in [('p','父'),('c','子')])
    if page == 'prep':
        fields.append('NULL::VARCHAR AS 业务组')
    return (prefix+"WITH scoped AS (SELECT * FROM "+source+overview_filter+"),"+parent+","+child+
            " SELECT "+','.join(fields)+" FROM parents p JOIN children c ON p.period_id=c.period_id "
            "AND p.unit_id=c.unit_id AND p.acquisition_scope=c.acquisition_scope "
            "AND p.business_line=c.business_line AND p.school=c.school "
            "ORDER BY CASE p.acquisition_scope WHEN '被动' THEN 1 WHEN '主动' THEN 2 WHEN '全部' THEN 3 ELSE 4 END, "
            "CASE p.business_line WHEN 'abroad' THEN 1 WHEN 'training' THEN 2 ELSE 3 END, "
            "p.\"父工单\" DESC NULLS LAST, p.school ASC, c.grade ASC")


def _groups_sql(page, dimension_type):
    prefix = _PREP_SELECTION if page == 'prep' else _OVERVIEW_SELECTION if page == 'overview' else ''
    unit_clause = ("d.unit_id='{{ overview_unit_id }}'" if page == 'overview'
                   else _unit(page, 'd.unit_id'))
    period_clause = _period_filter('期间')
    line_clause = " AND d.business_line='training'"
    # The comparison-group table is the legacy same-period comparison view;
    # business-group rows remain separate for target presentation.
    prefix += _ACQUISITION
    student_selection = _OVERVIEW_STUDENT_SELECTION if page == 'overview' else ''
    prefix += student_selection
    source = _dimension_query_source(
        page, [dimension_type],
        scope=("['{{ acquisition_scope }}{{ student_suffix }}']::VARCHAR[]"
               if page == 'overview' else "['{{ acquisition_scope }}']::VARCHAR[]")) + " d"
    dimensions = ["d.period_id AS 期间", f"{_unit_label('d.unit_id', page)} AS 管理单元",
                  'd.dim1 AS 业务组名称']
    extra = ["'{{ acquisition_scope }}' AS 语培统计范围"]
    if page == 'prep':
        extra = ["NULL::VARCHAR AS 业务组", *extra]
    return (prefix + _metric_row_sql(
        source, where=f"{unit_clause} AND d.dimension_type={_lit(dimension_type)}{line_clause} "
                     + ("AND d.acquisition_scope='{{ acquisition_scope }}{{ student_suffix }}' "
                        if page == 'overview' else "AND d.acquisition_scope='{{ acquisition_scope }}' ")
                     + "AND d.metric IN ('orders','cash','heads')",
        dimensions=dimensions, metric='d.metric', actual='d.actual', prior='d.prior', target='d.target',
        status='d.status', progress='d.time_progress', display='d.display', note='d.note',extra=extra))


def _target_sql(abroad=False):
    if abroad:
        return (_OVERVIEW_SELECTION + "WITH scope_units(目标团队,unit_id) AS (VALUES ('全部','online'),('全部','university'),"
                "('线上','online'),('线下','university')) SELECT tm.period_id AS 期间,'市场总计' AS 管理单元,"
                "scope_units.目标团队,CASE tm.unit_id WHEN 'online' THEN '线上留学' ELSE '线下留学' END AS 业务组名称,"
                + ', '.join(_metric_projection(metric='tm.metric', actual='tm.actual', prior='tm.prior',
                     target='tm.target', status='tm.status', progress='tm.time_progress',
                     display="CASE WHEN tm.metric='heads' AND tm.status='separate_counts' THEN '留学'||CAST(tv.study_heads AS BIGINT)::VARCHAR||'人／小语种'||CAST(tv.language_heads AS BIGINT)::VARCHAR||'人' END",
                     note='tm.note')) +
                " FROM scope_units JOIN business.team_metrics tm USING(unit_id) LEFT JOIN business.team_values tv ON tv.period_id=tm.period_id AND tv.unit_id=tm.unit_id "
                "AND tv.acquisition_scope=tm.acquisition_scope AND tv.business_line=tm.business_line AND tv.comparison='actual' "
                "WHERE tm.unit_id IN ('online','university') AND tm.business_line='abroad' "
                "AND tm.acquisition_scope='全部' AND tm.metric IN ('orders','cash','heads')")
    target_source = _dimension_query_source('overview',['business_group'],scope="['被动{{ student_suffix }}']::VARCHAR[]",
                                            units="list_value('{{ overview_unit_id }}')::VARCHAR[]")
    partition='d.period_id,d.unit_id,d.business_line,d.dim1'
    shares = [
        f"MAX(d.cash_share_numerator) FILTER(WHERE d.metric='cash') OVER(PARTITION BY {partition}) AS 被动现金分子",
        f"MAX(d.cash_share_denominator) FILTER(WHERE d.metric='cash') OVER(PARTITION BY {partition}) AS 现金固定分母",
        f"MAX(d.passive_cash_share) FILTER(WHERE d.metric='cash') OVER(PARTITION BY {partition}) AS 被动现金占比",
        _status(f"MAX(d.passive_cash_share_status) FILTER(WHERE d.metric='cash') OVER(PARTITION BY {partition})")+" AS 占比状态",
    ]
    metrics = ', '.join(_metric_projection(metric='d.metric', actual='d.actual', prior='d.prior',
        target='d.target', status='d.status', progress='d.time_progress', display='d.display', note='d.note'))
    return (_OVERVIEW_SELECTION + _ACQUISITION + _OVERVIEW_STUDENT_SELECTION + "SELECT d.period_id AS 期间,CASE d.unit_id WHEN 'total' THEN '市场总计' "
            "WHEN 'overview_prep' THEN '留学预备' WHEN 'overview_high' THEN '高中' "
            "WHEN 'overview_university' THEN '大学' WHEN 'online_scope' THEN '线上团队' ELSE '线下团队' END AS 管理单元,"
            "CASE d.unit_id WHEN 'total' THEN '全部' WHEN 'overview_prep' THEN '全部' "
            "WHEN 'overview_high' THEN '全部' WHEN 'overview_university' THEN '全部' "
            "WHEN 'online_scope' THEN '线上' ELSE '线下' END AS 目标团队,d.dim1 AS 业务组名称,"
            + ', '.join(shares+[metrics])+" "
            "FROM "+target_source+" d WHERE d.dimension_type='business_group' AND d.business_line='training' "
            "AND d.unit_id='{{ overview_unit_id }}' AND d.acquisition_scope='被动{{ student_suffix }}' "
            "AND d.metric IN ('orders','cash','heads')")


def _countries_sql(page, child=False):
    return _dimension_sql(page, '', country=True, detail=child)


def _online_country_sql(child=False):
    label = ',country AS 国家' if child else ''
    parent_group = 'period_id,business_line,line,country' if child else 'period_id,business_line,line'
    select_country = ',country' if child else ''
    aggregate = 'MAX' if child else 'SUM'
    return ("WITH v AS (SELECT period_id,business_line,COALESCE(NULLIF(line,''),'条线待确认') AS line,"
            "COALESCE(NULLIF(country,''),'国家待确认') AS country,comparison,SUM(value) AS orders "
            "FROM business.period_events WHERE unit_id='online' AND acquisition_scope='被动' AND metric='orders' "
            "AND business_line='abroad' GROUP BY period_id,business_line,line,country,comparison), p AS ("
            "SELECT period_id,business_line,line"+select_country+f",{aggregate}(actual) AS actual,{aggregate}(prior) AS prior FROM ("
            "SELECT period_id,business_line,line,country,MAX(orders) FILTER(WHERE comparison='actual') AS actual,"
            "MAX(orders) FILTER(WHERE comparison='prior') AS prior FROM v GROUP BY period_id,business_line,line,country) child_rows "
            "GROUP BY "+parent_group+") "
            "SELECT period_id AS 线上期间,"+_line('business_line')+" AS 业务线,line AS 条线"+label+
            ","+_presentation_double('actual')+" AS 工单,"+_presentation_double('prior')+
            " AS 同期,CASE WHEN prior<>0 THEN actual/prior-1 END AS 同比 FROM p")


def _metric_page_sql(key, page):
    if key == 'overview_market':
        # Overview selects one training business scope; its order target is
        # supplied by team_targets for that same scope.
        return (_OVERVIEW_SELECTION + _ACQUISITION +
                "SELECT tm.period_id AS 期间,CASE tm.unit_id WHEN 'total' THEN '市场总计' "
                "WHEN 'overview_prep' THEN '留学预备' WHEN 'overview_high' THEN '高中' "
                "WHEN 'overview_university' THEN '大学' END AS 管理单元,"
                "'语培总盘逐ID工单' AS 指标,"
                "" + _presentation_double("CASE WHEN tm.unit_id IN ('total','overview_prep','overview_high','overview_university') THEN tm.actual END") + " AS 当期,NULL::VARCHAR AS 呈现,"
                "" + _presentation_double("CASE WHEN tm.unit_id IN ('total','overview_prep','overview_high','overview_university') THEN tm.prior END") + " AS 同期,"
                "CASE WHEN tm.unit_id IN ('total','overview_prep','overview_high','overview_university') AND tm.prior<>0 THEN tm.actual/tm.prior-1 END AS 同比,"
                "CASE WHEN tm.unit_id NOT IN ('total','overview_prep','overview_high','overview_university') THEN '无同期同比' "
                "WHEN tm.prior IS NULL OR tm.prior=0 THEN '无同期同比' ELSE '可比' END AS 同期状态,"
                "" + _presentation_double("CASE WHEN tm.unit_id IN ('total','overview_prep','overview_high','overview_university') AND tm.acquisition_scope='被动' THEN tt.target END") + " AS 目标,"
                "CASE WHEN tm.unit_id IN ('total','overview_prep','overview_high','overview_university') AND tm.acquisition_scope='被动' AND tt.target IS NOT NULL "
                "THEN '已配置' ELSE '未配置' END AS 目标配置,"
                "CASE WHEN tm.unit_id IN ('total','overview_prep','overview_high','overview_university') AND tm.acquisition_scope='被动' AND tt.target<>0 "
                "THEN tm.actual/tt.target END AS 完成率,"
                "" + _presentation_double("CASE WHEN tm.unit_id IN ('total','overview_prep','overview_high','overview_university') AND tm.acquisition_scope='被动' THEN tm.actual-tt.target END") + " AS 目标差额,"
                "CASE WHEN tm.unit_id IN ('total','overview_prep','overview_high','overview_university') AND tm.acquisition_scope='被动' "
                "THEN ROUND(tm.actual-tt.target*tm.time_progress,2) END AS 时间进度差额,"
                "CASE WHEN tm.unit_id IN ('total','overview_prep','overview_high','overview_university') THEN " + _status('tm.status') + " END AS 状态,"
                "CASE WHEN tm.unit_id NOT IN ('total','overview_prep','overview_high','overview_university') THEN NULL "
                "WHEN tm.acquisition_scope='被动' THEN '语培被动工单按观远8类原始团队白名单统计，排除空团队；包含删除/回收，按工单ID去重。个人业绩剔除删除/回收。' "
                "WHEN tm.acquisition_scope='主动' THEN '语培主动工单按观远原始团队白名单及主被动字段统计；包含删除/回收。' "
                "ELSE '语培全部工单按观远原始团队白名单及主被动字段统计；包含删除/回收。' END AS 口径,"
                "tm.acquisition_scope AS 语培统计范围 "
                "FROM business.team_metrics tm LEFT JOIN business.team_targets tt "
                "ON tt.period_id=tm.period_id AND tt.unit_id=tm.unit_id "
                "AND tt.business_line=tm.business_line AND tt.metric=tm.metric "
                "WHERE tm.unit_id='{{ overview_unit_id }}' AND tm.business_line='training' "
                "AND tm.metric='orders' AND tm.acquisition_scope='{{ acquisition_scope }}'")
    if key.endswith('_market'):
        prefix = _PREP_SELECTION if page == 'prep' else ''
        unit = {'overview': "tm.unit_id='total'", 'virtual': "tm.unit_id='virtual'"}.get(page)
        if not unit:
            return None
        label = "CASE WHEN tm.unit_id='virtual' THEN '团队合并工单' ELSE '语培总盘逐ID工单' END"
        return (_ACQUISITION + "SELECT tm.period_id AS 期间,CASE WHEN tm.unit_id='total' THEN '市场总计' ELSE tm.unit_id END AS 管理单元,"
                + label + " AS 指标,"+_presentation_double('tm.actual')+" AS 当期,NULL::VARCHAR AS 呈现,"+_presentation_double('tm.prior')+" AS 同期,"
                "CASE WHEN tm.prior<>0 THEN tm.actual/tm.prior-1 END AS 同比,"
                "CASE WHEN tm.prior IS NULL OR tm.prior=0 THEN '无同期同比' ELSE '可比' END AS 同期状态,"
                +_presentation_double('tm.target')+" AS 目标,CASE WHEN tm.target IS NULL THEN '未配置' ELSE '已配置' END AS 目标配置,"
                "tm.actual/NULLIF(tm.target,0) AS 完成率,"+_presentation_double('tm.actual-tm.target')+" AS 目标差额,"
                "tm.actual-tm.target*tm.time_progress AS 时间进度差额,"+_status('tm.status')+" AS 状态,"+
                ("'语培被动工单按观远8类原始团队白名单统计，排除空团队；包含删除/回收，按工单ID去重。个人业绩剔除删除/回收。' AS 口径" if key=='overview_market' else "'' AS 口径")+
                (",'{{ acquisition_scope }}' AS 语培统计范围 " if key=='overview_market' else ' ')+
                "FROM business.team_metrics tm WHERE "+unit+" AND tm.business_line='training' AND tm.metric='orders' "
                "AND tm.acquisition_scope='{{ acquisition_scope }}'")
    if key.endswith('_lines') or key == 'online_summary':
        return _team_source(page)
    if key.endswith('_groups'):
        return _groups_sql(page, 'business_group')
    if key.endswith('_yoy'):
        return _groups_sql(page, 'comparison_group')
    if key.endswith('_targets'):
        return _target_sql(key.endswith('_abroad_targets'))
    if key.endswith('_supplemental'):
        prefix = _OVERVIEW_SELECTION if page == 'overview' else ''
        page_filter = '' if page == 'overview' else ' AND FALSE'
        return (prefix + _ACQUISITION + "SELECT tm.period_id AS 期间,'市场总计' AS 管理单元,CASE tm.unit_id WHEN 'international_market' THEN '国际市场' "
                "WHEN 'ssc' THEN 'SSC' ELSE '归属待确认' END AS 补充范围,"
                + ', '.join(_metric_projection(metric='tm.metric', actual='tm.actual', prior='tm.prior',
                    target='tm.target', status='tm.status', progress='tm.time_progress',
                    display="CASE WHEN tm.metric='heads' AND tm.status='separate_counts' THEN '留学'||CAST(tv.study_heads AS BIGINT)::VARCHAR||'人／小语种'||CAST(tv.language_heads AS BIGINT)::VARCHAR||'人' END",
                    note='tm.note')) +
                " FROM business.team_metrics tm LEFT JOIN business.team_values tv ON tv.period_id=tm.period_id AND tv.unit_id=tm.unit_id "
                "AND tv.acquisition_scope=tm.acquisition_scope AND tv.business_line=tm.business_line AND tv.comparison='actual' "
                "WHERE tm.unit_id IN ('international_market','ssc','unassigned') "
                "AND tm.business_line='abroad' AND tm.acquisition_scope='{{ acquisition_scope }}' "
                "AND tm.metric IN ('orders','cash','heads')"+page_filter)
    return None


def _people_sql(page):
    prefix = (_PREP_SELECTION if page == 'prep' else
              _OVERVIEW_SELECTION + _OVERVIEW_STUDENT_SELECTION if page == 'overview' else '')
    period = "{% set months = filter_values('个人月份', remove_filter=True) %}{% if months %} AND m.period_id IN {{ months|where_in }} {% endif %}"
    mode = "{% set modes = filter_values('月模式', remove_filter=True) %}{% set month_mode = 'calendar' if modes and modes[0]=='自然月' else 'performance' %}"
    state = ("{% set deleted = filter_values('含删除回收', remove_filter=True) %}"
             "{% set dead = filter_values('含死单', remove_filter=True) %}"
             "{% set state = ('1' if deleted and deleted[0]=='包含' else '0')~('1' if dead and dead[0]=='包含' else '0') %}")
    if page == 'overview':
        state += "{% set state = state ~ student_suffix %}"
    if page == 'overview':
        people_scope = ("{% if overview_label == '市场总计' %}"
                        "SELECT p.*,'total' AS selected_unit FROM config.people p"
                        "{% else %}"
                        "SELECT p.*,'{{ overview_unit_id }}' AS selected_unit FROM config.people p "
                        "WHERE p.business_line='training' AND p.home_group='{{ overview_label }}' UNION ALL "
                        "SELECT p.*,'total' AS selected_unit FROM config.people p WHERE p.business_line='abroad'"
                        "{% endif %}")
        person_filter = 'TRUE'
    elif page == 'virtual':
        people_scope = "SELECT p.*,'virtual' AS selected_unit FROM config.people p"
        person_filter = "list_contains(p.team_ids,'online_private')"
    elif page == 'prep':
        people_scope = "SELECT p.*,'prep' AS selected_unit FROM config.people p"
        person_filter = "p.selection_group IN (CASE WHEN ({{ mask }}&1)>0 THEN '青少' END, CASE WHEN ({{ mask }}&2)>0 THEN '初中' END, CASE WHEN ({{ mask }}&4)>0 THEN '高中' END)"
    else:
        people_scope = "SELECT p.*,'university' AS selected_unit FROM config.people p"
        person_filter = "p.home_group='大学' AND NOT list_contains(p.team_ids,'online_private')"
    metric_set = ("SELECT m.*,p.home_group,p.business_line AS primary_line,p.selection_group,p.team_ids,"
                  "p.training_roster,p.selected_unit FROM business.personal_metrics m JOIN ("+people_scope+
                  ") p USING(name) WHERE "+person_filter)
    window_start = 'CAST(window_start AS VARCHAR)' if page == 'prep' else 'window_start'
    window_end = 'CAST(window_end AS VARCHAR)' if page == 'prep' else 'window_end'
    return (prefix + mode + state + " WITH x AS (" + metric_set + "), picked AS (SELECT * FROM x m WHERE m.month_mode='{{ month_mode }}' " + period +
            " AND m.state='{{ state }}'), wide AS (SELECT period_id,month_mode,state,name,home_group,primary_line,selection_group,"
            "training_roster,selected_unit,team_ids,MIN(status) AS window_status,"
            "MIN(start_date) AS window_start,MAX(through_date) AS window_end,MAX(end_date) AS window_target_end,MAX(time_progress) AS window_progress,"
            "MAX(actual) FILTER(WHERE business_line='training' AND metric='orders') AS training_orders,"
            "MAX(target) FILTER(WHERE business_line='training' AND metric='orders') AS training_target,"
            "MAX(actual) FILTER(WHERE business_line='abroad' AND metric='orders') AS abroad_orders,"
            "MAX(target) FILTER(WHERE business_line='abroad' AND metric='orders') AS abroad_target,"
            "MAX(coverage_status) FILTER(WHERE business_line='abroad' AND metric='orders') AS abroad_order_status,"
            "MAX(actual) FILTER(WHERE business_line='training' AND metric='cash') AS training_cash,"
            "MAX(target) FILTER(WHERE business_line='training' AND metric='cash') AS training_cash_target,"
            "MAX(actual) FILTER(WHERE business_line='abroad' AND metric='cash') AS abroad_cash,"
            "MAX(target) FILTER(WHERE business_line='abroad' AND metric='cash') AS abroad_cash_target,"
            "MAX(actual) FILTER(WHERE business_line='training' AND metric='heads') AS training_heads,"
            "MAX(actual) FILTER(WHERE business_line='abroad' AND metric='heads') AS abroad_heads,"
            "MAX(heads_display) FILTER(WHERE business_line='abroad' AND metric='heads') AS abroad_heads_display,"
            "MAX(coverage_status) FILTER(WHERE business_line='abroad' AND metric='heads') AS abroad_heads_status,"
            "MAX(coverage_status) FILTER(WHERE business_line='abroad' AND metric='cash') AS abroad_cash_status "
            "FROM picked GROUP BY period_id,month_mode,state,name,home_group,primary_line,selection_group,training_roster,selected_unit,team_ids), totals AS (SELECT *,"
            "CASE WHEN list_contains(team_ids,'online_private') THEN training_orders "
            "WHEN abroad_order_status IN ('available','partial') THEN COALESCE(training_orders,0)+COALESCE(abroad_orders,0) END AS combined_orders,"
            "training_target AS combined_target,"
            "CASE WHEN abroad_order_status='not_covered' THEN NULL ELSE abroad_orders END AS covered_abroad_orders,"
            "CASE WHEN abroad_cash_status='not_covered' THEN NULL ELSE abroad_cash END AS covered_abroad_cash,"
            "CASE WHEN abroad_heads_status='not_covered' THEN NULL ELSE abroad_heads END AS covered_abroad_heads,"
            "CASE WHEN training_roster THEN training_cash ELSE CASE WHEN abroad_cash_status='not_covered' THEN NULL ELSE abroad_cash END END AS cash,"
            "CASE WHEN training_roster THEN training_cash_target ELSE abroad_cash_target END AS cash_target,"
            "CASE WHEN training_roster THEN training_heads ELSE CASE WHEN abroad_heads_status='not_covered' THEN NULL ELSE abroad_heads END END AS heads,"
            "CASE WHEN training_roster THEN 'available' ELSE abroad_cash_status END AS cash_coverage,"
            "CASE WHEN training_roster THEN 'available' ELSE abroad_heads_status END AS heads_coverage "
            "FROM wide) SELECT period_id AS 个人月份,"
            + (f"{_unit_label('selected_unit', 'overview')} AS 管理单元," if page == 'overview' else '') +
            "CASE month_mode WHEN 'calendar' THEN '自然月' ELSE '绩效月' END AS 月模式,"
            "CASE left(state,1) WHEN '1' THEN '包含' ELSE '不含' END AS 含删除回收,CASE right(state,1) WHEN '1' THEN '包含' ELSE '不含' END AS 含死单,"
            "name AS 人员,home_group AS 所属业务组,"+_line('primary_line')+" AS 主业务,"+window_start+" AS 窗口开始,"+window_end+" AS 窗口结束,"
            "CASE WHEN window_status='future' OR window_target_end IS NULL THEN 0.0 ELSE window_progress END AS 时间进度,"
            "training_orders AS 语培工单,covered_abroad_orders AS 留学工单,combined_orders AS 合计工单,"
            "training_orders/NULLIF(training_target,0) AS 语培完成率,"
            "CASE WHEN abroad_order_status='available' THEN covered_abroad_orders/NULLIF(abroad_target,0) END AS 留学完成率,"
            "CASE WHEN list_contains(team_ids,'online_private') OR abroad_order_status='available' THEN combined_orders/NULLIF(combined_target,0) END AS 合计完成率,"
            +_presentation_double('training_target')+" AS 语培目标,"+_presentation_double('abroad_target')+" AS 留学目标,"+_presentation_double('combined_target')+" AS 合计目标,cash AS 现金,"+_presentation_double('cash_target')+" AS 现金目标,cash/NULLIF(cash_target,0) AS 现金完成率,"
            "heads AS 人头,CASE WHEN training_roster THEN NULL ELSE abroad_heads_display END AS 分域人数,"
            + _status("CASE WHEN window_status='future' THEN 'future' WHEN training_roster THEN 'available' ELSE cash_coverage END") + " AS 现金状态,"
            + _status("CASE WHEN window_status='future' THEN 'future' WHEN training_roster THEN 'available' ELSE heads_coverage END") + " AS 人数状态"+
            (",NULL::VARCHAR AS 业务组" if page=='prep' else '')+","
            "CASE WHEN training_target IS NULL THEN '未配置' ELSE '已配置' END AS 语培目标状态,CASE WHEN abroad_target IS NULL THEN '未配置' ELSE '已配置' END AS 留学目标状态,"
            "CASE WHEN cash_target IS NULL THEN '未配置' ELSE '已配置' END AS 现金目标状态 FROM totals")


def _personal_channels_sql(page):
    prefix = _PREP_SELECTION if page == 'prep' else ''
    group_filter = "{% set groups=filter_values('业务组', remove_filter=True) %}{% set mask=(1 if '青少' in groups else 0)+(2 if '初中' in groups else 0)+(4 if '高中' in groups else 0) %}"
    group = " AND p.selection_group='高中'" + (" AND ({{ mask }} & 4)<>0" if page == 'prep' else '')
    state = "{% set deleted=filter_values('含删除回收',remove_filter=True) %}{% set dead=filter_values('含死单',remove_filter=True) %}{% set state=('1' if deleted and deleted[0]=='包含' else '0')~('1' if dead and dead[0]=='包含' else '0') %}"
    period = "{% set periods=filter_values('期间',remove_filter=True) %}{% set selected_period=periods[0] if periods|length==1 else 'FY27' %}"
    return (prefix+group_filter+state+period+" WITH ev AS (SELECT e.*,p.home_group,p.selection_group FROM business.personal_events e JOIN config.people p USING(name) "
            "WHERE e.period_id='{{ selected_period }}' AND e.month_mode='calendar' AND e.state='{{ state }}' AND e.business_line='abroad'"+group+"), totals AS ("
            "SELECT name,SUM(value) FILTER(WHERE metric='orders' AND comparison='actual') AS denominator,"
            "SUM(value) FILTER(WHERE metric='cash' AND comparison='actual') AS cash FROM ev GROUP BY name), cells AS ("
            "SELECT name,COALESCE(second_channel,'二级渠道待确认') AS second_channel,COALESCE(first_channel,'一级渠道待确认') AS first_channel,"
            "SUM(value) FILTER(WHERE metric='orders' AND comparison='actual') AS orders,"
            "SUM(value) FILTER(WHERE metric='orders' AND comparison='prior') AS prior FROM ev GROUP BY name,second_channel,first_channel) "
            "SELECT '{{ selected_period }}' AS 期间,c.name AS 人员,CASE left('{{ state }}',1) WHEN '1' THEN '包含' ELSE '不含' END AS 含删除回收,CASE right('{{ state }}',1) WHEN '1' THEN '包含' ELSE '不含' END AS 含死单,"
            "CAST((SELECT start_date FROM business.periods WHERE period_id='{{ selected_period }}') AS VARCHAR) AS 窗口开始,"
            "CAST((SELECT through_date FROM business.periods WHERE period_id='{{ selected_period }}') AS VARCHAR) AS 窗口结束,"
            "c.second_channel AS 二级渠道,c.first_channel AS 一级渠道,t.denominator AS 本人工单分母,t.cash AS 本人现金,"
            "c.orders AS 工单,c.prior AS 同期,CASE WHEN c.prior<>0 THEN c.orders/c.prior-1 END AS 同比,"
            "c.orders/NULLIF(t.denominator,0) AS 本人占比"+
            (",'{{ groups|join('、') }}' AS 业务组" if page=='prep' else '')+" FROM cells c JOIN totals t USING(name)")


def _facts_sql():
    return (_ACQUISITION + "SELECT fact_id AS 事实ID,"+_line('business_line')+" AS 业务线,metric AS 指标,event_date AS 日期,value AS 数值,"
            "school_name AS 学校,grade_name AS 年级,first_channel AS 一级渠道,second_channel AS 二级渠道,owner AS 人员,"
            "order_status AS 工单状态,source_kind AS 来源,source_record AS 来源记录,"
            "'{{ acquisition_scope }}' AS 语培统计范围 FROM business.facts WHERE business_line<>'training' "
            "OR acquisition_mode='{{ acquisition_scope }}' OR '{{ acquisition_scope }}'='全部'")


def _online_sql(key):
    if key in ('online_summary','online_groups'):
        from dashboard_product.shadow_bi.sql_warehouse.expense_note import expense_note_sql
        grouped = key == 'online_groups'
        record = "'group'" if grouped else "'line'"
        period_prefix = ("{% set requested_periods=filter_values('线上期间') %}" if grouped else '')
        period_clause = (" AND ({% if requested_periods %}m.period_id IN {{ requested_periods|where_in }}{% else %}TRUE{% endif %})" if grouped else '')
        base = (_ACQUISITION + period_prefix + "WITH tm AS (SELECT m.*,tv.study_heads,tv.language_heads FROM business.team_metrics m LEFT JOIN business.team_values tv "
                "ON tv.period_id=m.period_id AND tv.unit_id=m.unit_id AND tv.acquisition_scope=m.acquisition_scope "
                "AND tv.business_line=m.business_line AND tv.comparison='actual' "
                "WHERE m.unit_id='online' AND m.acquisition_scope='{{ acquisition_scope }}'"+period_clause+"), "
                "ad AS (SELECT * FROM business.scoped_advertising_rollup WHERE acquisition_scope='{{ acquisition_scope }}' AND record_type="+record+" AND period_id IN (SELECT period_id FROM tm)) ")
        if grouped:
            # Training group rows come from dimension metrics; the abroad line is
            # the online aggregate because it has no further business-group key.
            dimension_source = _dimension_query_source('online',['business_group'],period_name='线上期间')
            dims = ("SELECT period_id,unit_id,acquisition_scope,business_line,dim1 AS business_group,metric,actual,prior,target,status,time_progress,yoy,completion,gap,time_gap,display,note "
                    "FROM "+dimension_source+" WHERE dimension_type='business_group' AND unit_id='online' AND business_line='training' "
                    "AND acquisition_scope='{{ acquisition_scope }}'")
            base += ', dm AS ('+dims+') '
            metrics = _metric_projection(metric='dm.metric',actual='dm.actual',prior='dm.prior',target='dm.target',status='dm.status',progress='dm.time_progress',display='dm.display',note='dm.note')
            ad_fields = [_presentation_double('ad.spend')+" AS 花费", f"{_status('ad.spend_status')} AS 费用状态",'ad.roi AS 回收倍数','ad.cost_per_order AS 单条工单成本',_presentation_double('ad.roi_cash')+' AS 同窗现金',_presentation_double('ad.roi_spend')+' AS 同窗费用',_presentation_double('ad.roi_orders')+' AS 同窗工单','CAST(ad.roi_start_date AS VARCHAR) AS 费用窗口开始','CAST(ad.roi_through_date AS VARCHAR) AS 费用窗口结束',expense_note_sql('dm.business_line',group="CASE WHEN dm.business_line='training' THEN dm.business_group END",status='ad.spend_status',scope="'{{ acquisition_scope }}'")+" AS 费用说明"]
            return (base+"SELECT dm.period_id AS 线上期间,"+_line('dm.business_line')+" AS 业务线,dm.business_group AS 业务组名称,"+','.join(ad_fields+metrics)+",'{{ acquisition_scope }}' AS 语培统计范围"+
                    " FROM dm LEFT JOIN ad ON ad.period_id=dm.period_id AND ad.business_line=dm.business_line AND (ad.business_group=dm.business_group OR dm.business_line='abroad' AND ad.business_group IS NULL) "
                    "WHERE dm.metric IN ('orders','cash','heads')")
        team = _metric_projection(metric='tm.metric',actual='tm.actual',prior='tm.prior',target='tm.target',status='tm.status',progress='tm.time_progress',display="CASE WHEN tm.metric='heads' AND tm.status='separate_counts' THEN '留学'||CAST(tm.study_heads AS BIGINT)::VARCHAR||'人／小语种'||CAST(tm.language_heads AS BIGINT)::VARCHAR||'人' END",note='tm.note')
        ad_fields = [_presentation_double('ad.spend')+" AS 花费", f"{_status('ad.spend_status')} AS 费用状态",'ad.roi AS 回收倍数','ad.cost_per_order AS 单条工单成本',_presentation_double('ad.roi_cash')+' AS 同窗现金',_presentation_double('ad.roi_spend')+' AS 同窗费用',_presentation_double('ad.roi_orders')+' AS 同窗工单','CAST(ad.roi_start_date AS VARCHAR) AS 费用窗口开始','CAST(ad.roi_through_date AS VARCHAR) AS 费用窗口结束',expense_note_sql('tm.business_line',status='ad.spend_status',scope="'{{ acquisition_scope }}'")+" AS 费用说明"]
        return (base+"SELECT tm.period_id AS 线上期间,"+_line('tm.business_line')+" AS 业务线,"+','.join(ad_fields+team)+",'{{ acquisition_scope }}' AS 语培统计范围"+
                " FROM tm LEFT JOIN ad ON ad.period_id=tm.period_id AND ad.business_line=tm.business_line "
                "WHERE tm.metric IN ('orders','cash','heads')")
    if key == 'online_platforms':
        from dashboard_product.shadow_bi.sql_warehouse.expense_note import expense_note_sql
        return (_ACQUISITION + "WITH raw AS (SELECT * FROM business.scoped_advertising_rollup WHERE acquisition_scope='{{ acquisition_scope }}' AND record_type='platform' AND platform IS NOT NULL), "
                "p AS (SELECT r.*,CASE WHEN r.business_line='training' AND periods.through_date=clock.through_date THEN r.today_orders END AS display_today_orders "
                "FROM raw r LEFT JOIN business.periods periods ON periods.period_id=r.period_id AND periods.kind='month' CROSS JOIN config.clock clock), "
                "totals AS (SELECT period_id,business_line,SUM(orders) AS all_orders FROM p GROUP BY ALL) "
                "SELECT p.period_id AS 线上期间,"+_line('p.business_line')+" AS 业务线,"+_line('p.business_line')+" AS 平台业务线,"
                "p.platform AS 平台,"+_presentation_bigint('p.orders')+" AS 工单,"+_presentation_double("CASE WHEN p.business_line='abroad' THEN NULL ELSE p.prior_orders END")+" AS 工单同期,"
                "CASE WHEN p.business_line='abroad' OR p.prior_orders=0 THEN NULL ELSE p.orders/p.prior_orders-1 END AS 工单同比,"
                "p.orders/NULLIF(t.all_orders,0) AS 工单占比,"+_presentation_bigint('p.display_today_orders')+" AS 截止日新增,"+_presentation_cash('p.cash')+" AS 现金,"
                +_presentation_double("CASE WHEN p.business_line='abroad' THEN NULL ELSE p.prior_cash END")+" AS 现金同期,"
                "CASE WHEN p.business_line='abroad' OR p.prior_cash=0 THEN NULL ELSE p.cash/p.prior_cash-1 END AS 现金同比,"+_presentation_double('p.spend')+" AS 花费,"+_status('p.spend_status')+" AS 费用状态,"
                "p.roi AS 回收倍数,p.cost_per_order AS 单条工单成本,"+_presentation_double('p.roi_cash')+" AS 同窗现金,"+_presentation_double('p.roi_spend')+" AS 同窗费用,"+_presentation_double('p.roi_orders')+" AS 同窗工单,"
                "CAST(p.roi_start_date AS VARCHAR) AS 费用窗口开始,CAST(p.roi_through_date AS VARCHAR) AS 费用窗口结束,"+expense_note_sql('p.business_line',platform='p.platform',status='p.spend_status',scope="'{{ acquisition_scope }}'")+" AS 费用说明,'{{ acquisition_scope }}' AS 语培统计范围 "
                "FROM p JOIN totals t USING(period_id,business_line) "
                "ORDER BY CASE WHEN p.period_id LIKE 'FY%' THEN 0 WHEN p.period_id LIKE 'Q%' THEN 1 ELSE 2 END,"
                "p.period_id,CASE p.business_line WHEN 'training' THEN 0 ELSE 1 END,p.orders DESC NULLS LAST,p.platform")
    if key == 'online_platform_groups':
        from dashboard_product.shadow_bi.sql_warehouse.expense_note import expense_note_sql
        return (_ACQUISITION + "WITH raw AS (SELECT * FROM business.scoped_advertising_rollup WHERE acquisition_scope='{{ acquisition_scope }}' AND record_type='leaf'), "
                "p AS (SELECT r.*,CASE WHEN r.business_line='training' AND periods.through_date=clock.through_date THEN r.today_orders END AS display_today_orders "
                "FROM raw r LEFT JOIN business.periods periods ON periods.period_id=r.period_id AND periods.kind='month' CROSS JOIN config.clock clock) "
                "SELECT period_id AS 线上期间,"+_line('business_line')+" AS 业务线,platform AS 平台,business_group AS 业务组名称,"
                +_presentation_double('orders')+" AS 工单,"+_presentation_double("CASE WHEN business_line='abroad' THEN NULL ELSE prior_orders END")+" AS 工单同期,"+_presentation_double('display_today_orders')+" AS 截止日新增,"+_presentation_double('cash')+" AS 现金,"
                +_presentation_double("CASE WHEN business_line='abroad' THEN NULL ELSE prior_cash END")+" AS 现金同期,"+_presentation_double('spend')+" AS 花费,"
                +_status('spend_status')+" AS 费用状态,roi AS 回收倍数,cost_per_order AS 单条工单成本,"+_presentation_double('roi_cash')+" AS 同窗现金,"+_presentation_double('roi_spend')+" AS 同窗费用,"
                +_presentation_double('roi_orders')+" AS 同窗工单,CAST(roi_start_date AS VARCHAR) AS 费用窗口开始,CAST(roi_through_date AS VARCHAR) AS 费用窗口结束,"+expense_note_sql('p.business_line',platform='p.platform',group='p.business_group',status='p.spend_status',scope="'{{ acquisition_scope }}'")+" AS 费用说明,"
                "'{{ acquisition_scope }}' AS 语培统计范围 FROM p WHERE p.business_line='training'")
    if key in ('online_daily','online_trend','online_trend_spend','online_trend_cash','online_latest'):
        base = (_ACQUISITION + "WITH d AS (SELECT period_id,event_date,business_line,orders,cash,spend,spend_status,roi FROM business.scoped_online_daily WHERE acquisition_scope='{{ acquisition_scope }}') ")
        fields = "period_id AS 线上期间,event_date AS 日期,"+_line('business_line')+" AS 业务线,"+_presentation_double('orders')+" AS 工单,"+_presentation_double('cash')+" AS 现金,"+_presentation_double('spend')+" AS 花费,roi AS 回收倍数,"+_status('spend_status')+" AS 费用状态"
        latest = " QUALIFY event_date=MAX(event_date) OVER(PARTITION BY period_id)" if key == 'online_latest' else ''
        # The original daily table is chronological; its CROSS JOIN emits
        # training then abroad. Keep that input traversal for aggregate export
        # queries whose metric sort has equal values.
        line_order = (" ORDER BY CASE business_line WHEN 'training' THEN 1 WHEN 'abroad' THEN 2 ELSE 3 END,"
                      "CASE WHEN period_id LIKE 'FY%' THEN 0 WHEN period_id LIKE 'Q%' THEN 1 ELSE 2 END,"
                      "period_id,event_date")
        return base+'SELECT '+fields+' FROM d'+latest+line_order
    if key in ('online_countries','online_countries_child'):
        return _online_country_sql(key.endswith('_child'))
    if key == 'online_window':
        return "SELECT period_id AS 线上期间,label AS 统计期间,CAST(start_date AS VARCHAR) AS 开始日期,CAST(through_date AS VARCHAR) AS 截止日期,time_progress AS 时间进度,"+_status('status')+" AS 状态 FROM business.periods WHERE kind='month'"
    return None


def _capacity_sql(key):
    if key == 'capacity_month':
        return ("{% set months=filter_values('产能月份',remove_filter=True) %}{% set products=filter_values('产品范围',remove_filter=True) %}"
                "{% set product_scopes=[] %}{% for product in products %}{% if product=='留学' %}{% set _=product_scopes.append('study_abroad') %}{% elif product=='小语种' %}{% set _=product_scopes.append('small_language') %}{% elif product=='合计' %}{% set _=product_scopes.append('all') %}{% endif %}{% endfor %}"
                "{% set deleted=filter_values('含删除回收',remove_filter=True) %}{% set dead=filter_values('含死单',remove_filter=True) %}"
                "{% set state=('1' if deleted and deleted[0]=='包含' else '0')~('1' if dead and dead[0]=='包含' else '0') %}"
                "WITH c AS (SELECT * FROM business.contribution_capacity WHERE state='{{ state }}' {% if months %} AND month IN {{ months|where_in }} {% endif %} "
                "{% if products and product_scopes %} AND product_scope IN {{ product_scopes|where_in }} {% endif %}), w AS ("
                "SELECT month,person,home_group,business_line,product_scope,"
                "MAX(self) FILTER(WHERE metric='orders') AS self_orders,MAX(self) FILTER(WHERE metric='cash') AS self_cash,"
                "MAX(self_rate) FILTER(WHERE metric='orders') AS self_rate_orders,MAX(self_rate) FILTER(WHERE metric='cash') AS self_rate_cash,"
                "MAX(target) FILTER(WHERE metric='orders') AS target_orders,MAX(target) FILTER(WHERE metric='cash') AS target_cash,"
                "MAX(completion) FILTER(WHERE metric='orders') AS completion_orders,MAX(completion) FILTER(WHERE metric='cash') AS completion_cash,"
                "MAX(received) FILTER(WHERE metric='orders') AS received_orders,MAX(received) FILTER(WHERE metric='cash') AS received_cash,"
                "MAX(own_total) FILTER(WHERE metric='orders') AS own_total_orders,MAX(own_total) FILTER(WHERE metric='cash') AS own_total_cash,"
                "MAX(output) FILTER(WHERE metric='orders') AS output_orders,MAX(output) FILTER(WHERE metric='cash') AS output_cash,"
                "MAX(created_total) FILTER(WHERE metric='orders') AS created_total_orders,MAX(created_total) FILTER(WHERE metric='cash') AS created_total_cash,"
                "BOOL_OR(confirmed_history) AS confirmed_history "
                "FROM c GROUP BY month,person,home_group,business_line,product_scope) SELECT month AS 产能月份,person AS 人员,"
                "CASE WHEN home_group IS NULL THEN '—' ELSE home_group END AS 所属业务组,"+_line('business_line')+" AS 主业务,"
                "CASE product_scope WHEN 'all' THEN '合计' WHEN 'study_abroad' THEN '留学' ELSE '小语种' END AS 产品范围,"
                "self_orders AS 自主创造工单,self_cash AS 自主创造现金,self_rate_orders AS 自创率工单,self_rate_cash AS 自创率现金,"
                "target_orders AS 目标工单,target_cash AS 目标现金,completion_orders AS 本业务完成率工单,completion_cash AS 本业务完成率现金,"
                "received_orders AS 额外接收工单,received_cash AS 额外接收现金,own_total_orders AS 本业务合计工单,own_total_cash AS 本业务合计现金,"
                "output_orders AS 额外输出工单,output_cash AS 额外输出现金,created_total_orders AS 自创合计工单,created_total_cash AS 自创合计现金,"
                "(SELECT COUNT(*) FROM business.contribution_pending p WHERE p.month=w.month AND list_contains(p.affected_people,w.person)) AS 个人待核数,"
                "CASE WHEN confirmed_history THEN '历史确认汇总；未提供状态及自创明细' ELSE '按已提供来源' END AS 历史细分覆盖 "
                "FROM w")
    if key == 'capacity_pending':
        return ("{% set months=filter_values('产能月份',remove_filter=True) %} SELECT p.month AS 产能月份,a.person AS 人员,"
                "p.source_label AS 来源,p.reason AS 原因,COUNT(*) AS 待核记录数 FROM business.contribution_pending p "
                "CROSS JOIN UNNEST(p.affected_people) AS a(person) {% if months %} WHERE p.month IN {{ months|where_in }} {% endif %} "
                "GROUP BY p.month,a.person,p.source_label,p.reason")
    if key == 'capacity_pending_count':
        return ("{% set months=filter_values('产能月份',remove_filter=True) %} SELECT month AS 产能月份,COUNT(*) AS 全月待核数 "
                "FROM business.contribution_pending {% if months %} WHERE month IN {{ months|where_in }} {% endif %} GROUP BY month")
    if key == 'capacity_markers':
        return ("{% set months=filter_values('产能月份',remove_filter=True) %} SELECT month AS 产能月份,affected_people AS 涉及人员,source_label AS 来源,reason AS 原因,"
                "value AS 原值,work_order_id AS 工单ID,resource_id AS 资源ID FROM business.contribution_marker_diagnostics "
                "{% if months %} WHERE month IN {{ months|where_in }} {% endif %}")
    if key == 'capacity_radar_values':
        return ("SELECT name AS 六维人员,label AS 维度,value AS 本人,mean AS 同组均值,scale AS 轴上限,relative AS 相对同组,"
                "through_date AS 年度截止,'2026-06-01' AS 年度开始 FROM business.radar_axes "
                "ORDER BY name,CASE axis WHEN 'orders' THEN 1 WHEN 'heads' THEN 2 WHEN 'conversion' THEN 3 "
                "WHEN 'partner' THEN 4 WHEN 'tmk' THEN 5 WHEN 'campaign' THEN 6 END")
    if key == 'capacity_radar':
        return ("SELECT name AS 六维人员,label AS 维度,'本人' AS 系列,value/NULLIF(scale,0) AS 比例 FROM business.radar_axes "
                "UNION ALL SELECT name,label,'同组均值',mean/NULLIF(scale,0) FROM business.radar_axes")
    if key == 'capacity_annual_targets':
        return ("SELECT name AS 六维人员,home_group AS 所属业务组,"+_line('business_line')+" AS 主业务,orders AS 年度工单,cash AS 年度现金,heads AS 年度人头,"
                "conversion AS 年度转化率,cash_capacity AS 年度现金目标,cash_progress_completion AS 现金时间进度完成率,"
                "CAST(start_date AS VARCHAR) AS 年度开始,CAST(through_date AS VARCHAR) AS 年度截止,peer_count AS 同组人数 FROM business.radar_people")
    if key == 'capacity_annual_products':
        return ("SELECT name AS 六维人员,CASE domain WHEN 'training' THEN '语培' WHEN 'study_abroad' THEN '留学' WHEN 'small_language' THEN '小语种' ELSE '未归属产品' END AS 产品,"
                "orders AS 工单,cash AS 现金,heads AS 独立人头,heads/NULLIF(orders,0) AS 转化率 FROM business.radar_products")
    return None


def _direct_sql(key, page):
    if key in ('activities',):
        return ("SELECT activity AS 活动,"+_presentation_bigint('training_orders')+" AS 语培工单,"+
                _presentation_bigint('abroad_orders')+" AS 留学工单,"+_presentation_bigint('orders')+" AS 合计工单,"+
                _presentation_cash('cash')+" AS 现金,"+_presentation_bigint('heads')+" AS 人头,"
                "heads_display AS 分域人数,CAST(heads_parts AS VARCHAR) AS 分域明细,cash_status AS 现金状态 "
                "FROM business.activities ORDER BY activity ASC")
    if key == 'overview_classification':
        return ("{% set periods=filter_values('期间',remove_filter=True) %} SELECT period_id AS 期间,scope AS 核查范围,"
                "actual_unclassified AS 当期未分类工单,prior_unclassified AS 同期未分类工单,note AS 说明 FROM business.classification "
                "{% if periods %} WHERE period_id IN {{ periods|where_in }} {% endif %}")
    if key == 'facts':
        return _facts_sql()
    if key.endswith('_window'):
        column = '线上期间' if page == 'online' else '期间'
        kind = "'month'" if page == 'online' else "'year'"
        return (f"SELECT period_id AS {_q(column)},label AS 统计期间,CAST(start_date AS VARCHAR) AS 开始日期,"
                "CAST(through_date AS VARCHAR) AS 截止日期,time_progress AS 时间进度,"+_status('status')+
                f" AS 状态 FROM business.periods WHERE kind={kind}")
    if key.endswith('_people'):
        return _people_sql(page)
    if key.endswith('_personal_channels'):
        return _personal_channels_sql(page)
    if key.startswith('online_'):
        return _online_sql(key)
    if key.startswith('capacity_'):
        return _capacity_sql(key)
    return None


def _ordered_sql(sql, columns, default):
    prefix = ("{% set bases=filter_values('排序依据',remove_filter=True) %}"
              "{% set sort_basis=bases[0] if bases|length==1 and bases[0] in "+repr(list(columns))+" else '' %}"
              "{% set directions=filter_values('排序方向',remove_filter=True) %}"
              "{% set sort_direction=directions[0] if directions|length==1 and directions[0] in ['升序','降序'] else '降序' %}")
    expression = "{% if sort_basis == '' %}"+default
    for label, expr in columns.items():
        expression += "{% elif sort_basis == "+_lit(label)+" %}"+expr
    expression += "{% endif %} {% if sort_direction == '升序' %} ASC {% else %} DESC {% endif %} NULLS LAST"
    return prefix+'SELECT ordered.*,ROW_NUMBER() OVER(ORDER BY '+expression+') AS 排列顺序 FROM ('+sql+') ordered'


def _native_sql(key):
    """Return the native SSC adapter that cannot reuse a P3 view verbatim."""
    if key == 'native_overview_ssc':
        source = _sql_for('overview_supplemental', 'overview')
        return ("SELECT 期间,管理单元,MAX(CASE WHEN 指标='工单' THEN 当期 END) AS 工单,"
                "MAX(CASE WHEN 指标='现金（元）' THEN 当期 END) AS \"现金（元）\","
                "MAX(CASE WHEN 指标='人头' THEN COALESCE(呈现,printf('%.1f',TRY_CAST(当期 AS DOUBLE)),'—') END) AS 人头 "
                "FROM ("+source+") s WHERE 补充范围='SSC' GROUP BY 期间,管理单元")
    return None


def _overview_native_grade_sql(sql, *, training=True):
    """Scope the native overview grade tree to selected training plus total abroad."""
    selection = _OVERVIEW_SELECTION
    if not training:
        selection += "{% set overview_unit_id = 'total' %}{% set overview_label = '市场总计' %}\n"
    sql = selection + sql
    sql = sql.replace("['total','virtual','online']", "list_value('{{ overview_unit_id }}','total')")
    sql = sql.replace("SELECT period_id AS 期间, team_id AS 管理单元, json_object('grades_by_line'",
                      "SELECT period_id AS 期间, '{{ overview_label }}' AS 管理单元, team_id AS __unit_id, json_object('grades_by_line'")
    sql = sql.replace("WHERE team_id IN ('total','virtual','online')",
                      "WHERE team_id IN ('{{ overview_unit_id }}','total')")
    sql = sql.replace(
        "FROM b, json_each(b.v, '$.grades_by_line') ln, json_each(ln.value) e)",
        "FROM b, json_each(b.v, '$.grades_by_line') ln, json_each(ln.value) e "
        "WHERE ('{{ overview_unit_id }}'='total' OR b.__unit_id<>'total' OR ln.key='abroad'))",
    )
    return sql


def _overview_student_variant_sql(sql):
    """Select the overview training tree at the chosen student grain."""
    if _ACQUISITION not in sql:
        raise ValueError('overview training dimension SQL is missing its acquisition selection')
    sql = sql.replace(_ACQUISITION, _ACQUISITION + _OVERVIEW_STUDENT_SELECTION, 1)
    sql = sql.replace("acquisition_scope='{{ acquisition_scope }}'",
                      "acquisition_scope='{{ acquisition_scope }}{{ student_suffix }}'")
    sql = sql.replace("['{{ acquisition_scope }}']",
                      "['{{ acquisition_scope }}{{ student_suffix }}']")
    return sql


def _overview_native_channel_sql(sql, *, training=True):
    """Use the selected training tree and total abroad tree in overview channels."""
    selection = _OVERVIEW_SELECTION
    if not training:
        selection += "{% set overview_unit_id = 'total' %}{% set overview_label = '市场总计' %}\n"
    sql = selection + sql
    sql = sql.replace(
        "SELECT period_id AS 期间, team_id AS 管理单元, json_object('channels'",
        "SELECT period_id AS 期间, '{{ overview_label }}' AS 管理单元, team_id AS __unit_id, json_object('channels'",
    )
    sql = sql.replace("WHERE team_id IN ('total','virtual','online')",
                      "WHERE team_id IN ('{{ overview_unit_id }}','total')")
    sql = sql.replace(
        "FROM b, json_each(b.v, '$.channels') e)",
        "FROM b, json_each(b.v, '$.channels') e "
        "WHERE ('{{ overview_unit_id }}'='total' OR b.__unit_id<>'total' "
        "OR json_extract_string(e.value,'$.business_line')='abroad'))",
    )
    sql = sql.replace(
        "FROM b, json_each(b.v, '$.channels') e, json_each(e.value, '$.groups') c)",
        "FROM b, json_each(b.v, '$.channels') e, json_each(e.value, '$.groups') c "
        "WHERE ('{{ overview_unit_id }}'='total' OR b.__unit_id<>'total' "
        "OR json_extract_string(e.value,'$.business_line')='abroad'))",
    )
    return sql


def _sql_for(key, page):
    from dashboard_product.shadow_bi.sql_warehouse.direct_catalog import direct_sql
    direct = direct_sql(key)
    if direct is not None:
        return direct
    if key.startswith('online_'):
        return _online_sql(key)
    if key.endswith('_supplemental'):
        return _metric_page_sql(key, page)
    if key.endswith('_personal_channels'):
        return _personal_channels_sql(page)
    if key.startswith('capacity_'):
        return _capacity_sql(key)
    if key == 'facts':
        return _facts_sql()
    if key in ('overview_groups','virtual_groups','prep_groups','university_groups'):
        return _groups_sql(page,'business_group')
    if key.endswith('_yoy'):
        return _groups_sql(page,'comparison_group')
    if key.endswith('_targets'):
        return _target_sql(key.endswith('_abroad_targets'))
    if key in ('overview_countries','virtual_countries','university_countries'):
        return _countries_sql(page,False)
    if key in ('overview_countries_child','virtual_countries_child','university_countries_child'):
        return _countries_sql(page,True)
    for kind in ('channels','channels_child','schools','schools_child','grades'):
        if key.endswith('_'+kind):
            if kind.startswith('channels'):
                return _dimension_sql(page,'channel_group' if kind.endswith('_child') else 'channel',detail=kind.endswith('_child'))
            if kind.startswith('schools'):
                return (_dimension_sql(page,'school_grade',detail=True) if kind.endswith('_child')
                        else _school_pairs_sql(page))
            return _dimension_sql(page,'grade')
    if key in ('overview_lines','virtual_lines','prep_lines','university_lines','online_summary','overview_market','virtual_market'):
        return _metric_page_sql(key,page)
    if key == 'overview_abroad_targets':
        return _metric_page_sql(key,page)
    return _direct_sql(key,page)


_UNSUPPORTED = {}


def _flat_native_views(metadata, flat_base):
    """Build the native presentation layer from the already-flat P3 views."""
    from dashboard_product.shadow_bi.sql_warehouse.native_school import native_school_sql

    native_module = importlib.import_module('dashboard_product.shadow_bi.p35.native_catalog')
    original = {view.key: view for view in metadata}

    def school_tree(page):
        key = 'native_'+page+'_schools'
        contract = original[key]
        if page == 'university':
            from .native_school_json import native_school_json_sql
            sql = native_school_json_sql(page, contract.sql)
        else:
            sql = native_school_sql(page, contract.sql, _school_tree_raw_sql)
        view = deepcopy(contract)
        view.sql = sql
        return view

    with patch.object(native_module, 'BASE', flat_base), patch.object(native_module, 'school_tree', school_tree):
        views = native_module.native_views()

    # The native SSC summary stringifies a DOUBLE head count (``3.0``). The
    # flat warehouse stores DECIMAL, so use an explicit one-decimal display.
    for view in views:
        if view.key == 'native_overview_ssc':
            view.sql = _native_sql(view.key)

    # Keep query-local JSON traversal where the unchanged native ROW_NUMBER
    # relies on the original parent/array iteration order for equal values.
    from .native_dimension_json import native_grade_json_sql, native_channel_json_sql
    from .native_channel_cache import university_channel_node_sources
    for view in views:
        if view.page in ('overview', 'virtual', 'prep', 'university') and view.key.startswith('native_') and '_grades' in view.key:
            view.sql = native_grade_json_sql(view.page, original[view.key].sql)
            if view.page == 'overview':
                if not view.key.endswith('_abroad'):
                    view.sql = _overview_student_variant_sql(view.sql)
                view.sql = _overview_native_grade_sql(
                    view.sql, training=not view.key.endswith('_abroad'))
        if view.page in ('overview', 'virtual', 'prep', 'university') and view.key.startswith('native_') and '_channel_tree' in view.key:
            view.sql = native_channel_json_sql(
                view.page,
                original[view.key].sql,
                university_channel_node_sources=(
                    university_channel_node_sources() if view.page == 'university' else None
                ),
            )
            if view.page == 'overview':
                if not view.key.endswith('_abroad'):
                    view.sql = _overview_student_variant_sql(view.sql)
                view.sql = _overview_native_channel_sql(
                    view.sql, training=not view.key.endswith('_abroad'))
    return {view.key: view for view in views}


def build_catalogue():
    """Return all legacy dataset contracts backed by flat warehouse SQL."""
    metadata = _metadata()
    p3_contracts = [contract for contract in metadata if not contract.key.startswith('native_')]
    flat_base = {}
    unsupported_by_key = {}
    for contract in p3_contracts:
        sql = _sql_for(contract.key, contract.page)
        unsupported = _UNSUPPORTED.get(contract.key)
        if sql is None and unsupported is None:
            unsupported = 'No complete flat SQL mapping is available for this dataset key.'
        unsupported_by_key[contract.key] = unsupported
        if sql is not None:
            view = deepcopy(contract)
            view.sql = sql
            flat_base[view.key] = view

    native_views = _flat_native_views(metadata, flat_base)
    entries = {}
    for contract in metadata:
        page = contract.page
        sql = flat_base[contract.key].sql if contract.key in flat_base else native_views.get(contract.key).sql if contract.key in native_views else None
        unsupported = unsupported_by_key.get(contract.key, _UNSUPPORTED.get(contract.key))
        if sql is None and unsupported is None:
            unsupported = 'No complete flat SQL mapping is available for this dataset key.'
        entry = DatasetSQL(
            key=contract.key, title=contract.title, page=page, section=contract.section,
            columns=tuple(contract.columns), filters=deepcopy(contract.filters), sql=sql,
            unsupported=unsupported, viz=contract.viz, more=deepcopy(contract.more), contract=contract)
        entries[entry.key] = entry
    return entries


def catalogue_status(catalogue=None):
    catalogue = catalogue or build_catalogue()
    unsupported = [dict(key=entry.key, columns=list(entry.columns), reason=entry.unsupported)
                   for entry in catalogue.values() if entry.unsupported]
    return {'status': 'fail' if unsupported else 'pass', 'dataset_count': len(catalogue),
            'supported_count': len(catalogue)-len(unsupported), 'unsupported': unsupported}


def supported_views(catalogue=None):
    """Return legacy-shaped View objects for the complete SQL mappings only."""
    catalogue = catalogue or build_catalogue()
    result = []
    for entry in catalogue.values():
        if entry.unsupported:
            continue
        view = deepcopy(entry.contract)
        view.sql = entry.sql
        result.append(view)
    return result


def render_dataset_sql(key, filters=None, catalogue=None, *, columns=None, groupby=None):
    """Render one Jinja dataset query using only the documented filter helpers."""
    from jinja2 import Environment

    catalogue = catalogue or build_catalogue()
    if key not in catalogue:
        raise KeyError(key)
    entry = catalogue[key]
    if entry.unsupported or entry.sql is None:
        raise ValueError(f'{key} is unsupported: {entry.unsupported}')
    filters = filters or {}
    def filter_values(column, remove_filter=False):
        value = filters.get(column, [])
        return value if isinstance(value, list) else [value]
    def where_in(values):
        return '(' + ', '.join(_lit(str(value)) for value in values) + ')'
    env = Environment(autoescape=False)
    env.globals['filter_values'] = filter_values
    env.globals['columns'] = columns or []
    env.globals['groupby'] = groupby or []
    env.filters['where_in'] = where_in
    return env.from_string(entry.sql).render()
