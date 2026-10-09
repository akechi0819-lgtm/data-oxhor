"""Project the accepted online layout from the management batch, without queries."""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta

from dashboard_product.online_team.build import channel_rows, dimensions, select
from dashboard_product.management.aggregate import _team_fact_filter


def online_view(public, facts, abroad_targets):
    through = public['metadata']['data_through']
    scopes = {line: _team_fact_filter('online', line) for line in ('training', 'abroad')}
    valid = [f for f in facts if scopes[f['business_line']](f)]
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
                        scope='按线上团队归属范围汇总；团队包含删除、回收；个人业绩剔除',
                        notices=[], groups=[], dimensions=[])
            if line_id == 'training':
                line['groups'] = deepcopy(team['business_groups'])
            elif p['status'] != 'future':
                line['dimensions'] = dimensions([row for row in now if row['metric'] == 'orders'], [])
                for dimension in line['dimensions']:
                    for item in [dimension, *dimension['children']]:
                        item.update(prior_orders=None, yoy=None)
            if line_id == 'training':
                line['channels'] = channel_rows(now, prior, line_id, through, p) if p['status'] != 'future' else []
            else:
                line['channels'] = [{
                    'name': row['name'], 'first_channels': [row['first_channel']],
                    'orders': row['orders']['actual'], 'prior_orders': None, 'orders_yoy': None,
                    'share': row['share'], 'today_orders': None,
                    'cash': row['cash']['actual'], 'prior_cash': None, 'cash_yoy': None,
                } for row in team.get('channels', []) if row['business_line'] == 'abroad']
            p['lines'][line_id] = line
            for f in now:
                if f['metric'] == 'orders':
                    daily[line_id][f['event_date']] += f['value']
        if p['through_date']:
            day, end = date.fromisoformat(p['start_date']), date.fromisoformat(p['through_date'])
            while day <= end:
                key = day.isoformat()
                coverage = team['lines']['abroad']['source_coverage']
                abroad_day = daily['abroad'][key] if coverage['start_date'] <= key <= coverage['through_date'] else None
                p['daily'].append({'date': key, 'training_orders': daily['training'][key],
                                   'abroad_orders': abroad_day})
                day += timedelta(days=1)
        output.append(p)
    return {'schema_version': public['schema_version'],
            'metadata': {**public['metadata'], 'title': '线上团队 · 经营进度',
                         'default_period': min(through, public['metadata']['study_abroad_source']['through_date'])[:7]}, 'periods': output,
            'reconciliation': {'cells': [], 'notes': ['同一管理批次投影，无独立线上取数。']}}
