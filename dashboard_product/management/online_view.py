"""Project the accepted online layout from the management batch, without queries."""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta

from dashboard_product.online_team.build import channel_rows, dimensions, select, study_target


def online_view(public, facts, abroad_targets):
    through = public['metadata']['data_through']
    valid = [f for f in facts if f.get('counts_toward_completion', True)
             and f.get('team_id') == 'online_platform']
    output = []
    for period in public['periods']:
        p = {k: deepcopy(v) for k, v in period.items()
             if k in ('id', 'label', 'kind', 'start_date', 'end_date', 'through_date',
                      'prior_start_date', 'prior_through_date', 'time_progress', 'status')}
        team = next(t for t in period['teams'] if t['id'] == 'online')
        p['lines'], p['daily'], p['notes'] = {}, [], []
        daily = {line: Counter() for line in ('training', 'abroad')}
        for line_id in ('training', 'abroad'):
            records = [dict(f, first_channel=f.get('first_channel') or '一级渠道待确认',
                            second_channel=f.get('second_channel') or '二级渠道待确认',
                            country=f.get('country') or '国家待确认', line=f.get('line') or '条线待确认')
                       for f in valid if f['business_line'] == line_id]
            now = select(records, p['start_date'], p['through_date'])
            prior = select(records, p['prior_start_date'], p['prior_through_date'])
            line = deepcopy(team['lines'][line_id])
            line.update(label='语培' if line_id == 'training' else '留学',
                        scope='与管理看板同批结果；删除、回收不计完成，明细保留',
                        notices=[], groups=[], dimensions=[])
            if line_id == 'training':
                line['groups'] = deepcopy(team['business_groups'])
            else:
                # Preserve the previously displayed gross-sign target as a
                # target only; actual study-abroad cash remains unconnected.
                line['cash']['target'] = study_target(abroad_targets, p, 'cash')
                line['cash']['note'] = '留学现金实际未接入；目标沿用已配置毛签目标。'
                if p['status'] != 'future':
                    line['dimensions'] = dimensions(now, prior)
            line['channels'] = channel_rows(now, prior, line_id, through, p) if p['status'] != 'future' else []
            p['lines'][line_id] = line
            for f in now:
                if f['metric'] == 'orders':
                    daily[line_id][f['event_date']] += f['value']
        if p['through_date']:
            day, end = date.fromisoformat(p['start_date']), date.fromisoformat(p['through_date'])
            while day <= end:
                key = day.isoformat()
                p['daily'].append({'date': key, 'training_orders': daily['training'][key],
                                   'abroad_orders': daily['abroad'][key]})
                day += timedelta(days=1)
        output.append(p)
    return {'schema_version': public['schema_version'],
            'metadata': {**public['metadata'], 'title': '线上团队 · 经营进度',
                         'default_period': through[:7]}, 'periods': output,
            'reconciliation': {'cells': [], 'notes': ['同一管理批次投影，无独立线上取数。']}}
