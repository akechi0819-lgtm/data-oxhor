"""按现有费用来源元数据生成原展示说明，不参与业务发布门禁。"""


def expense_note_sql(line, *, platform=None, group=None, status, scope="'被动'"):
    predicates=['s.business_line='+line]
    for column,expression in [('platform',platform),('business_group',group)]:
        if expression is not None:
            predicates.append(f"(nullif({expression},'') IS NULL OR s.{column}={expression})")
    body = ("SELECT CASE WHEN count(*)=0 THEN '未提供对应平台费用，不能按0元处理。' ELSE "
        "CASE WHEN count(*) FILTER(WHERE start_date IS NOT NULL AND end_date IS NOT NULL)>0 THEN "
        "'已提供费用来源：'||min(start_date) FILTER(WHERE end_date IS NOT NULL)::VARCHAR||'至'||"
        "max(end_date) FILTER(WHERE start_date IS NOT NULL)::VARCHAR||'；只覆盖已提供账户。' "
        "ELSE '已登记费用来源，但当前来源没有可用日期行；不按0元处理。' END||"
        f"CASE WHEN coalesce({status},'missing')<>'complete' THEN 'ROI与单条工单成本按费用共同覆盖日期计算。' ELSE '' END||"
        "CASE WHEN coalesce(sum(missing_amount_count),0)>0 THEN '来源中'||sum(missing_amount_count)::BIGINT::VARCHAR||"
        "'条日期金额为空，保持缺失、不按零计。' ELSE '' END||"
        "CASE WHEN coalesce(sum(try_cast(json_extract_string(summary_json,'$.missing_date_count') AS BIGINT)),0)>0 THEN "
        "'来源未提供'||sum(try_cast(json_extract_string(summary_json,'$.missing_date_count') AS BIGINT))::BIGINT::VARCHAR||'个日期行。' ELSE '' END END||"
        f"CASE WHEN {line}='abroad' AND count(*)>0 AND bool_and(grain='period') THEN '留学费用来自期间总表，不拆分到日。' ELSE '' END||"
        "CASE WHEN bool_or(coalesce(json_extract_string(summary_json,'$.derivation'),'') NOT IN ('','null','{}','[]')) "
        "THEN '9月费用由9—10月累计减10月当月取得。' ELSE '' END FROM expenses.expense_sources s WHERE "+' AND '.join(predicates))
    return f"CASE WHEN {line}='training' AND {scope}<>'被动' THEN NULL ELSE ("+body+') END'
