"""大学渠道的学校属性：现金原行优先，工单只用学校名的唯一映射。"""
from collections import defaultdict
import re
import unicodedata

OTHER = '毕业及其他'
UNIVERSITY_SCHOOLS = (
    '天津师范大学', '天津商业大学', '天津科技大学', '天津财经大学',
    '天津理工大学', '天津美术学院', '天津城建大学', '天津外国语大学',
    '天津大学', '天津工业大学', '南开大学', '河北工业大学',
)


def canonical_university_school(value):
    name = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))
    for school in UNIVERSITY_SCHOOLS:
        if name == school:
            return school
        if not name.startswith(school):
            continue
        suffix = name[len(school):]
        # 校区是同一学校，附属学校、独立学院仍按其自身名称处理。
        if any(token in suffix for token in ('附属', '附中', '附小', '中学', '小学', '幼儿园', '学院')):
            continue
        campus = suffix.strip('()·-—')
        if '校区' in campus or campus in ('八里台', '津南', '北洋园', '卫津路', '泰达'):
            return school
    return None


def school_attribute(value):
    name = str(value or '').strip()
    if name in ('本地大学', '本地其他大学'):
        return '本地大学'
    return name if name in ('归巢大学', '国外大学') else OTHER


def attach_school_attributes(training_rows, source_rows):
    by_row = {}
    by_school = defaultdict(set)
    for row in source_rows:
        category = school_attribute(row['school_attribute'])
        by_row[row['source_row_number']] = category
        name = str(row['school_name'] or '').strip()
        if name:
            by_school[name].add(category)
    for row in training_rows:
        school = canonical_university_school(row.get('school_name'))
        if school:
            row['channel_school_name'] = school
            row['school_attribute'] = '大学*'
            row['school_attribute_status'] = '重点大学名单'
        elif row['metric'] == 'passive_reported_cash':
            row['school_attribute'] = by_row[row['source_row_number']]
            row['school_attribute_status'] = '现金原行'
        else:
            categories = by_school.get(str(row.get('school_name') or '').strip(), set())
            row['school_attribute'] = next(iter(categories)) if len(categories) == 1 else OTHER
            row['school_attribute_status'] = ('学校唯一映射' if len(categories) == 1 else
                                               '学校属性冲突' if categories else '学校属性未匹配')
