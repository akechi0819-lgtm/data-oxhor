"""Server-side booklet filters for dashboard HTML.

Refresh still writes one full artifact.json. Render copies and trims the
embedded dashboard JSON so a booklet page does not contain other teams'
summaries or detail strings.
"""

from __future__ import annotations

import copy
import json

BOOKLET_IDS = ('full', 'online_private', 'online_platform', 'offline_market')

# None = every team including market_total. Team booklets drop market_total
# so a single board cannot be reassembled from sibling pages.
BOOKLET_TEAM = {
    'full': None,
    'online_private': 'online_private',
    'online_platform': 'online_platform',
    'offline_market': 'offline_market',
}

TEAM_DISPLAY_NAMES = {
    'online_private': '线上私域（虚拟人团队）',
    'online_platform': '线上平台',
    'offline_market': '线下市场',
    'market_total': '市场总计',
}

PERMISSION_TO_BOOKLET = {
    'all': 'full',
    '虚拟人': 'online_private',
    '平台': 'online_platform',
    '线下': 'offline_market',
}

SCHOOL_DRILL_GROUPS = ('高中', '大学')

FULL_TITLE = 'Cyber Shackles - 语培完成进度看板'
FULL_PERIOD_LINE = 'FY27 财年：2026-06-01 至 2027-05-31'
FULL_GRADE_KICKER = '目标区仍按留学预备、高中、大学；渠道同比和年级同比按青少、初中、高中、大学。现金用学员年级，工单用年级名称；高中、大学支持学校 → 年级下钻'
FULL_PEOPLE_GROUP_OPTIONS = (
    '<option value="all">全部团队</option>'
    '<option value="留学预备">留学预备</option>'
    '<option value="高中">高中</option>'
    '<option value="大学">大学</option>'
)


def validate_booklet(booklet):
    if booklet in (None, ''):
        return None
    if booklet not in BOOKLET_TEAM:
        raise ValueError(f'unknown booklet: {booklet}')
    return booklet


def booklet_filename(booklet):
    booklet = validate_booklet(booklet) or 'full'
    return f'{booklet}.html'


def drill_team_id(key):
    parts = str(key).split('|')
    if len(parts) < 2:
        return None
    return parts[1]


def _filter_drill_map_by_team(source, team_id):
    return {
        key: value
        for key, value in (source or {}).items()
        if drill_team_id(key) == team_id
    }


def _empty_team(team_id):
    return {
        'team_id': team_id,
        'display_name': TEAM_DISPLAY_NAMES.get(team_id, team_id),
        'cash_target': None,
        'orders_target': None,
        'groups': [],
        'yoy_groups': [],
        'people': [],
    }


def _rewrite_drilldowns(data, keep):
    drilldowns = data.get('drilldowns') or {}
    for period in ('current', 'prior'):
        period_block = drilldowns.get(period) or {}
        for metric in ('cash', 'orders'):
            metric_block = period_block.get(metric) or {}
            for kind in ('channel', 'school_grade'):
                metric_block[kind] = keep(metric_block.get(kind))


def filter_dashboard_for_booklet(dashboard, booklet=None):
    """Return a deep copy of dashboard JSON, trimmed to one team board.

    ``full`` / ``None`` keep every team including ``market_total``. Team
    booklets keep only that ``team_id``, drop ``market_total``, and drop
    sibling teams' groups, people, and drilldown keys so totals cannot be
    recovered from the page.
    """
    booklet = validate_booklet(booklet)
    data = copy.deepcopy(dashboard)
    team_id = BOOKLET_TEAM.get(booklet)
    if booklet in (None, 'full') or team_id is None:
        return data
    teams = [
        team for team in data.get('teams') or []
        if team.get('team_id') == team_id
    ]
    if not teams:
        teams = [_empty_team(team_id)]
    data['teams'] = teams
    _rewrite_drilldowns(data, lambda source: _filter_drill_map_by_team(source, team_id))
    data['booklet'] = booklet
    data['booklet_team'] = team_id
    return data


def booklet_chrome(booklet=None):
    """Template strings for a booklet. Team pages still list all business groups."""
    booklet = validate_booklet(booklet)
    team_id = BOOKLET_TEAM.get(booklet)
    if booklet in (None, 'full') or team_id is None:
        return {
            'page_title': FULL_TITLE,
            'period_line': FULL_PERIOD_LINE,
            'special_board_link': '<a class="special-board-link" href="online_market_special.html">进入线上团队特供看板 →</a>',
            'grade_kicker': FULL_GRADE_KICKER,
            'people_group_options': FULL_PEOPLE_GROUP_OPTIONS,
            'school_grade_groups_json': json.dumps(list(SCHOOL_DRILL_GROUPS), ensure_ascii=False),
        }
    team_label = TEAM_DISPLAY_NAMES.get(team_id, team_id)
    return {
        'page_title': f'{FULL_TITLE}（{team_label}）',
        'period_line': f'{FULL_PERIOD_LINE} · {team_label}分册',
        'special_board_link': '',
        'grade_kicker': FULL_GRADE_KICKER,
        'people_group_options': FULL_PEOPLE_GROUP_OPTIONS,
        'school_grade_groups_json': json.dumps(list(SCHOOL_DRILL_GROUPS), ensure_ascii=False),
    }
