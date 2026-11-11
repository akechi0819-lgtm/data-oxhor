"""Pure dashboard coverage Markdown formatting."""


def coverage_note(coverage):
    return '![观近头像](/p3/assets/01-avatar.png) ![观近数据助手](/p3/assets/02-data-tablet.png)\n\n## 观近 · 市场经营\n\n语培截至 '+coverage['data_through']+' · 留学截至 '+coverage['study_abroad_source']['through_date']+' · 金额单位：元'
