"""Project the confirmed online/offline study-abroad team progress."""
from copy import deepcopy


def attach_progress(periods):
    for period in periods:
        teams = {team['id']: team for team in period['teams']}
        rows = []
        for team_id, label in (('online', '线上留学'), ('university', '线下留学')):
            line = teams[team_id]['lines']['abroad']
            current = {'id': team_id, 'name': label,
                       **{kind: deepcopy(line[kind]) for kind in ('orders', 'cash', 'heads')}}
            teams[team_id]['abroad_progress'] = [current]
            rows.append(current)
        teams['total']['abroad_progress'] = rows
