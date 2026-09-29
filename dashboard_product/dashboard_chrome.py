"""Rendering metadata for the single full dashboard."""

import json


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


def dashboard_chrome():
    return {
        'page_title': FULL_TITLE,
        'period_line': FULL_PERIOD_LINE,
        'special_board_link': '<a class="special-board-link" href="online_market_special.html">进入线上团队融合看板 →</a> <a class="special-board-link" href="offline_market_special.html">进入留学线下市场特供看板 →</a>',
        'grade_kicker': FULL_GRADE_KICKER,
        'people_group_options': FULL_PEOPLE_GROUP_OPTIONS,
        'school_grade_groups_json': json.dumps(list(SCHOOL_DRILL_GROUPS), ensure_ascii=False),
    }
