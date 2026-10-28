"""平台页费用提示：引用当前批次来源覆盖，不把缺费用当零消费。"""
from datetime import datetime

FEE_PLATFORMS = {
    'training': ['抖音', '百度', '小红书', '微信', '腾讯广告', '美团/大众点评', '官网/自有入口', '高德'],
    'abroad': ['抖音', '百度', '必应', '闲鱼', '小红书', '微信', '腾讯广告', '美团/大众点评', '官网/自有入口', '腾讯地图', '高德'],
}
LIMITATION = '留学费用仅提供整体×平台，暂不支持国家条线／语种费用筛选。'


def format_coverage(rows):
    lines = []
    for business, label in [('training', '语培'), ('abroad', '留学')]:
        dates = {}
        for line, platform, through, grain in rows:
            if line != business or platform not in FEE_PLATFORMS[business]:
                continue
            key = (str(through), grain)
            if platform not in dates or key[0] > dates[platform][0]:
                dates[platform] = key
        daily = {}
        old = {}
        missing = []
        for platform in FEE_PLATFORMS[business]:
            if platform not in dates:
                missing.append(platform)
                continue
            through, grain = dates[platform]
            (daily if grain == 'daily' else old).setdefault(through, []).append(platform)
        parts = [f'{"、".join(platforms)}截至{through}' for through, platforms in sorted(daily.items(), reverse=True)]
        parts += [f'{"、".join(platforms)}仅有旧汇总（截至{through}，待补流水）' for through, platforms in sorted(old.items(), reverse=True)]
        if missing:
            parts.append('尚未提供费用：' + '、'.join(missing))
        lines.append(f'**{label}**：' + '；'.join(parts) + '。')
    return '\n\n'.join(lines + ['未提供费用不代表零消费；投入产出按已有费用的共同日期窗口计算。' + LIMITATION])


def expense_coverage_note(library, batch, audit):
    from data_platform.business_library import execute_library_query, read_library_result
    result = execute_library_query(
        library=library, batch_id=batch,
        sql='SELECT business_line, platform, CAST(MAX(end_date) AS VARCHAR), grain FROM queries.expense_sources GROUP BY business_line, platform, grain ORDER BY business_line, platform, grain',
        run_id='run_expense_coverage_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'),
        output_root=audit / 'expense-coverage', max_rows=200)
    return format_coverage(read_library_result(result, output_root=audit / 'expense-coverage')['rows'])
