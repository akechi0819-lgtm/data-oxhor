"""市场总览目标表的团队范围，按同源明细重算而非累加去重人头。"""
from copy import deepcopy

from .aggregate import _date, _valid_facts
from .breakdowns import _business_groups
from .cash_share import attach_passive_cash_share
from .market_totals import attach_market_orders


TEAM_SCOPES = {
    'online': ('online_private', 'online_platform'),
    'offline': ('offline_market',),
}


def attach_team_scope_views(periods, facts, market_rows, training_targets, cash_rows):
    """只投影目标进度两表；全部保留未归因市场工单，筛选不猜归属。"""
    through = max(_date(period['through_date']) for period in periods if period.get('through_date'))
    valid = _valid_facts(facts, through, include_non_completion=True)
    for period in periods:
        total = next(team for team in period['teams'] if team['id'] == 'total')
        total['team_scope_views'] = {'all': {
            'business_groups': deepcopy(total['business_groups']),
            'study_abroad_progress': deepcopy(total['abroad_progress']),
        }}
    for scope, team_ids in TEAM_SCOPES.items():
        scoped_facts = [fact for fact in valid if fact.get('team_id') in team_ids]
        projected = []
        for period in periods:
            total = next(team for team in period['teams'] if team['id'] == 'total')
            team = {
                'id': 'total', 'lines': deepcopy(total['lines']),
                'business_groups': _business_groups(
                    scoped_facts, 'total', period, training_targets, team_ids),
            }
            projected.append({**period, 'teams': [team]})
        attach_market_orders(projected, [row for row in market_rows if row.get('team_id') in team_ids])
        attach_passive_cash_share(projected, cash_rows)
        for period, scoped_period in zip(periods, projected):
            total = next(team for team in period['teams'] if team['id'] == 'total')
            abroad_id = 'online' if scope == 'online' else 'university'
            total['team_scope_views'][scope] = {
                'business_groups': scoped_period['teams'][0]['business_groups'],
                'study_abroad_progress': deepcopy([
                    row for row in total['abroad_progress'] if row['id'] == abroad_id]),
            }
