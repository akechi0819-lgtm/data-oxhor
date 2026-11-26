"""Shared configuration rules for the SQL warehouse."""
from datetime import date
from typing import Any

from workspace_modeling.operations.personnel import BUSINESS_GROUP_BY_ROSTER_GROUP, is_displayable_person

ABROAD_OFFLINE_TEAM = 'offline_market'
ROSTER_GROUPS = {'youth': '青少', 'middle_school': '初中', 'high_school': '高中'}

UNIVERSITY_SCHOOL_ATTRIBUTES = (
    '大学*', '本地大学', '归巢大学', '国外大学', '毕业及其他',
)


def _text(value):
    return str(value or '').strip()


def _month_ids(period):
    kind = period['kind']
    if kind == 'month':
        return [period['id']]
    if kind == 'quarter':
        quarter_months = {
            'Q1': [(2026, 6), (2026, 7), (2026, 8)],
            'Q2': [(2026, 9), (2026, 10), (2026, 11)],
            'Q3': [(2026, 12), (2027, 1), (2027, 2)],
            'Q4': [(2027, 3), (2027, 4), (2027, 5)],
        }
        return [f'{year:04d}-{month:02d}' for year, month in quarter_months[period['id']]]
    return [f'{year:04d}-{month:02d}' for year, month in
            ([(2026, month) for month in range(6, 13)] + [(2027, month) for month in range(1, 6)])]


def _calendar_month_window(period):
    """Return the personal performance window matching a dashboard period."""
    months = _month_ids(period)
    first_year, first_month = map(int, months[0].split('-'))
    last_year, last_month = map(int, months[-1].split('-'))
    prior_month = first_month - 1
    prior_year = first_year
    if prior_month == 0:
        prior_year -= 1
        prior_month = 12
    start = date(prior_year, prior_month, 26)
    end = date(last_year, last_month, 25)
    return start, end


def _business_group(group, person):
    return person.get('business_group') or BUSINESS_GROUP_BY_ROSTER_GROUP.get(group)


def _roster(people_config, abroad_people_config):
    people = {}

    def entry(name):
        if name not in people:
            people[name] = {
                'name': name,
                'home_group': None,
                'team_ids': set(),
                'lines': set(),
                'targets': {'training': {}, 'abroad': {}},
                'training_roster': False,
                'abroad_roster': False,
            }
        return people[name]

    for team in people_config.get('teams', []):
        team_id = team.get('team_id')
        # Platform has no confirmed individual KPI roster.
        if team_id not in ('offline_market', 'online_private'):
            continue
        for group in team.get('groups', []):
            group_name = group.get('display_name')
            for person in group.get('members', []):
                if not is_displayable_person(person):
                    continue
                name = _text(person.get('display_name'))
                if not name:
                    continue
                row = entry(name)
                row['home_group'] = _business_group(group_name, person) or row['home_group']
                row['team_ids'].add(team_id)
                row['lines'].add('training')
                row['training_roster'] = True
                row['targets']['training'].update(person.get('monthly_targets') or {})

    for person in abroad_people_config.get('people', []):
        if not is_displayable_person(person):
            continue
        name = _text(person.get('display_name'))
        if not name:
            continue
        row = entry(name)
        business_group = _text(person['business_group'])
        if not row['training_roster']:
            row['home_group'] = business_group
        row['team_ids'].add(ABROAD_OFFLINE_TEAM)
        row['lines'].add('abroad')
        row['abroad_roster'] = True
        row['targets']['abroad'].update(person.get('monthly_targets') or {})

    result = []
    for row in people.values():
        row['team_ids'] = frozenset(row['team_ids'])
        row['lines'] = frozenset(row['lines'])
        if row['training_roster'] and row['abroad_roster']:
            row['business_line'] = 'training+abroad'
        elif row['training_roster']:
            row['business_line'] = 'training'
        else:
            row['business_line'] = 'abroad'
        result.append(row)
    return sorted(result, key=lambda row: row['name'])


def _training_roster(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for team in config.get("teams", []):
        team_id = team.get("team_id")
        if team_id not in ("offline_market", "online_private"):
            continue
        for group in team.get("groups", []):
            for person in group.get("members", []):
                if not is_displayable_person(person):
                    continue
                name = _text(person.get("display_name"))
                if not name:
                    continue
                row = result.setdefault(name, {
                    "name": name,
                    "business_line": "training",
                    "home_group": _business_group(group.get("display_name"), person),
                    "team_ids": set(),
                    "training_roster": True,
                    "monthly_targets": person.get("monthly_targets") or {},
                    "status": person.get("status"),
                })
                row["team_ids"].add(team_id)
                if not row["home_group"]:
                    row["home_group"] = _business_group(group.get("display_name"), person)
    return result


def _abroad_roster(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    source_team = config.get("team_id")
    team_id = {
        "study_abroad_offline": "offline_market",
        "study_abroad_online": "online_platform",
    }.get(source_team, "offline_market")
    for person in config.get("people", []):
        if not is_displayable_person(person):
            continue
        name = _text(person.get("display_name"))
        if not name:
            continue
        result[name] = {
            "name": name,
            "business_line": "abroad",
            # This matches the current contribution table's abroad|留学 selector.
            "home_group": "留学",
            "roster_group": _text(person.get("business_group")) or None,
            "team_ids": {team_id},
            "training_roster": False,
            "monthly_targets": person.get("monthly_targets") or {},
            "status": person.get("status"),
        }
    return result


def _group_members(people_config):
    result={}
    for team in people_config.get('teams',[]):
        if team['team_id']!='offline_market':continue
        for group in team.get('groups',[]):
            scope=ROSTER_GROUPS.get(group.get('group_id'))
            if scope:
                for person in group['members']:result[person['display_name']]=scope
    return result
