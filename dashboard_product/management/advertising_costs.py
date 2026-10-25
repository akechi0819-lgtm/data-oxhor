"""把已核验线上业务事实与费用分别聚合，经受控SQL匹配，不摊费用。"""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import json

from dashboard_product.management.aggregate import _team_fact_filter
from dashboard_product.management.advertising_sources import load_sources
from dashboard_product.management.platforms import canonical_platform, classify_business_fact
from dashboard_product.online_team.build import query, write

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / 'sql/advertising_rollup.sql'


def classified_facts(facts, *, order_facts=None):
    predicates = {line: _team_fact_filter('online', line) for line in ('training', 'abroad')}
    order_labels = {str(f['work_order_id']).strip():classify_business_fact(f)['raw_labels'] for f in (facts if order_facts is None else order_facts)
                    if f.get('business_line')=='training' and f.get('metric')=='orders' and f.get('work_order_id')}
    return [(f,classify_business_fact(f,order_labels)) for f in facts
            if f.get('business_line') in predicates and f.get('metric') in ('orders','cash')
            and predicates[f['business_line']](f)]


def business_daily(facts, periods, *, order_facts=None):
    starts = [p['prior_start_date'] for p in periods if p.get('through_date')]
    ends = [p['through_date'] for p in periods if p.get('through_date')]
    grouped = defaultdict(lambda: [Decimal(0), Decimal(0)])
    if not starts:
        return []
    for fact, classification in classified_facts(facts, order_facts=order_facts):
        line = fact['business_line']
        if not min(starts) <= fact['event_date'] <= max(ends):
            continue
        group = fact['business_group'] if line == 'training' else '留学整体'
        platform = classification['platform']
        key = (fact['event_date'], line, group, platform)
        grouped[key][0 if fact['metric'] == 'orders' else 1] += Decimal(str(fact['value']))
    return [(*key, int(values[0]), values[1]) for key, values in sorted(grouped.items())]


def _values(rows, types):
    def literal(value, sql_type):
        if value is None:
            return f'CAST(NULL AS {sql_type})'
        if sql_type in ('DATE', 'VARCHAR'):
            return "CAST('" + str(value).replace("'", "''") + "' AS " + sql_type + ')'
        return f'CAST({value} AS {sql_type})'
    rows = rows or [tuple(None for _ in types)]
    return ',\n'.join('(' + ','.join(literal(v, t) for v, t in zip(row, types, strict=True)) + ')' for row in rows)


def render_sql(periods, daily, costs):
    params = [(p['id'], p['start_date'], p['through_date'], p['prior_start_date'], p['prior_through_date'])
              for p in periods if p.get('through_date') and p.get('status') != 'future']
    expenses = [(r['source_id'],r['business_line'],r['business_group'],r['platform'],r['start_date'],r['end_date'],r['amount']) for r in costs['rows']]
    sources = [(r['source_id'],r['business_line'],r['business_group'],r['platform'],r['grain'],r['start_date'],r['end_date']) for r in costs['sources']]
    sql = TEMPLATE.read_text(encoding='utf-8')
    replacements = {
        'PERIODS': _values(params, ['VARCHAR','DATE','DATE','DATE','DATE']),
        'BUSINESS_DAILY': _values(daily, ['DATE','VARCHAR','VARCHAR','VARCHAR','BIGINT','DECIMAL(20,2)']),
        'EXPENSE_ROWS': _values(expenses, ['VARCHAR','VARCHAR','VARCHAR','VARCHAR','DATE','DATE','DECIMAL(20,2)']),
        'EXPENSE_SOURCES': _values(sources, ['VARCHAR','VARCHAR','VARCHAR','VARCHAR','VARCHAR','DATE','DATE']),
    }
    for token, values in replacements.items():
        sql = sql.replace('/* ' + token + ' */', values)
    return sql


def _advertising(row, line, costs):
    row = row or {}
    sources = [s for s in costs['sources'] if s['business_line'] == line
               and (not row.get('platform') or s['platform'] == row['platform'])
               and (not row.get('business_group') or s['business_group'] == row['business_group'])]
    status = row.get('spend_status', 'missing')
    if not sources:
        note = '未提供对应平台费用，不能按0元处理。'
    else:
        start = min(s['start_date'] for s in sources)
        end = max(s['end_date'] for s in sources)
        note = f'已提供费用来源：{start}至{end}；只覆盖已提供账户。'
        if status != 'complete':
            note += 'ROI与单条工单成本按费用共同覆盖日期计算。'
    if line == 'abroad' and sources and all(s['grain'] == 'period' for s in sources):
        note += '留学费用来自期间总表，不拆分到日。'
    if any(s.get('derivation') for s in sources):
        note += '9月费用由9—10月累计减10月当月取得。'
    return {'spend': row.get('spend'), 'spend_status': status, 'roi': row.get('roi'),
            'cost_per_order': row.get('cost_per_order'), 'note': note,
            **{key: row.get(key) for key in ('roi_start_date','roi_through_date','roi_spend','roi_cash','roi_orders')}}


def apply_result(online, rows, costs, classifications):
    # Data Platform保留DECIMAL为十进制文本；在展示边界转换，不在SQL中损失金额精度。
    numeric = ('orders','cash','prior_orders','prior_cash','today_orders','spend','roi','cost_per_order','roi_spend','roi_cash','roi_orders')
    rows = [{**row, **{key:float(Decimal(str(row[key]))) if row.get(key) is not None else None for key in numeric}} for row in rows]
    lookup = {(r['period_id'],r['business_line'],r['record_type'],r.get('business_group'),r.get('platform'),r.get('event_date')):r for r in rows}
    for period in online['periods']:
        pid = period['id']
        for line_id, line in period['lines'].items():
            summary = lookup.get((pid,line_id,'line',None,None,None))
            # 同仓同范围回查：新增费用不得改变现有完成值。
            for field, metric in [('orders','orders'),('cash','cash')]:
                expected = line[metric].get('actual')
                if summary and expected is not None and abs(float(summary[field])-expected) > .011:
                    raise ValueError(f'费用SQL业务量与线上看板不一致: {pid}/{line_id}/{field}')
            line['advertising'] = _advertising(summary, line_id, costs)
            names = defaultdict(set)
            for fact, classification in classifications:
                if fact['business_line']==line_id and (
                    period.get('through_date') and period['start_date']<=fact['event_date']<=period['through_date']
                    or period.get('prior_through_date') and period['prior_start_date']<=fact['event_date']<=period['prior_through_date']
                ):
                    names[classification['platform']].add(fact.get('first_channel') or '一级来源待确认')
            platform_rows = [r for r in rows if r['period_id']==pid and r['business_line']==line_id and r['record_type']=='platform']
            channels = []
            for row in platform_rows:
                name = row['platform']
                groups = [r for r in rows if r['period_id']==pid and r['business_line']==line_id and r['record_type']=='leaf' and r['platform']==name]
                orders = int(row['orders'])
                prior = row['prior_orders'] if line_id=='training' else None
                channels.append({'name':name,'first_channels':sorted(names[name]),'orders':orders,
                    'prior_orders':prior,'orders_yoy':orders/prior-1 if prior else None,
                    'share':orders/summary['orders'] if summary and summary['orders'] else None,
                    'today_orders':int(row['today_orders']) if line_id=='training' and period['through_date']==online['metadata']['data_through'] else None,
                    'cash':row['cash'],'prior_cash':row['prior_cash'] if line_id=='training' else None,
                    'cash_yoy':row['cash']/row['prior_cash']-1 if line_id=='training' and row['prior_cash'] else None,
                    'advertising':_advertising(row,line_id,costs),
                    'groups':[{'name':r['business_group'],'orders':int(r['orders']),'cash':r['cash'],
                               'prior_orders':r['prior_orders'],'prior_cash':r['prior_cash'],
                               'today_orders':int(r['today_orders']) if line_id=='training' and period['through_date']==online['metadata']['data_through'] else None,
                               'advertising':_advertising(r,line_id,costs)} for r in groups] if line_id=='training' else []})
            line['channels'] = sorted(channels,key=lambda r:(-r['orders'],r['name']))
            for group in line['groups']:
                name = group['name']
                result = lookup.get((pid,line_id,'group',name,None,None))
                group['advertising'] = _advertising(result,line_id,costs)
        for day in period['daily']:
            for line in ('training','abroad'):
                result = lookup.get((pid,line,'daily',None,None,day['date']))
                day[line+'_spend'] = result.get('spend') if result else None
                day[line+'_spend_status'] = result.get('spend_status','missing') if result else 'missing'
                cash_metric = period['lines'][line]['cash']
                coverage = cash_metric.get('source_coverage')
                cash_available = cash_metric.get('actual') is not None and (
                    not coverage or coverage['start_date']<=day['date']<=coverage['through_date'])
                day[line+'_cash'] = result.get('cash') if result and cash_available else None
                day[line+'_roi'] = result.get('roi') if result and cash_available else None
    return online


def attach_advertising(online, facts, workspace, snapshot_id, run_id, output, *, order_facts=None):
    workspace, output = Path(workspace), Path(output)
    manifest = workspace / 'Input/AdvertisingCosts/sources.json'
    costs = load_sources(manifest if manifest.exists() else None)
    classifications = classified_facts(facts, order_facts=order_facts)
    daily = business_daily(facts, online['periods'], order_facts=order_facts)
    sql_path = output / 'advertising.sql'
    sql_path.write_text(render_sql(online['periods'],daily,costs),encoding='utf-8')
    config = json.loads((workspace/'Work/workspace.json').read_text(encoding='utf-8'))
    records, receipt = query(sql_path, [], 'advertising', run_id, snapshot_id,
                             workspace/config['current_warehouse_path'], output, output/'_query')
    write(output/'advertising_sources.json',costs)
    write(output/'advertising_result.json',records)
    apply_result(online,records,costs,classifications)
    audit = defaultdict(lambda: {'orders':Decimal(0),'cash':Decimal(0)})
    for fact, classification in classifications:
        if not '2026-06-01'<=fact['event_date']<=online['metadata']['data_through']:
            continue
        window = '2026-10' if fact['event_date'].startswith('2026-10') else fact['event_date'][:7]
        labels = tuple(classification['raw_labels'])
        key = (window,fact['business_line'],classification['platform'],fact.get('second_channel'),labels,classification['basis'])
        audit[key][fact['metric']] += Decimal(str(fact['value']))
    write(output/'platform_classification_audit.json',[
        {'month':key[0],'business_line':key[1],'platform':key[2],'previous_channel':key[3],
         'raw_labels':list(key[4]),'basis':key[5],'orders':int(values['orders']),'cash':float(values['cash'])}
        for key, values in sorted(audit.items(),key=lambda item:str(item[0]))])
    return receipt
