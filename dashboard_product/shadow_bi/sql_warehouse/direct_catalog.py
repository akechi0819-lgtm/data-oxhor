"""保留人员台账与明细展示合同；所有业务值读取同仓 SQL 结果。"""
from functools import lru_cache


def _line(expression):
    return f"CASE {expression} WHEN 'training' THEN '语培' WHEN 'abroad' THEN '留学及小语种' ELSE {expression} END"


def _presentation_double(expression):
    return f"CAST(CAST({expression} AS VARCHAR) AS DOUBLE)"


@lru_cache(maxsize=1)
def _legacy():
    from dashboard_product.shadow_bi.p3.catalog import VIEWS
    return {v.key:v.sql for v in VIEWS}


def _capacity():
    columns=['c.month AS 产能月份','c.person AS 人员',
        "CASE left(c.state,1) WHEN '1' THEN '包含' ELSE '不含' END AS 含删除回收",
        "CASE right(c.state,1) WHEN '1' THEN '包含' ELSE '不含' END AS 含死单",
        "concat("+_line('c.business_line')+",' · ',CASE WHEN c.business_line='abroad' THEN '留学' ELSE c.home_group END) AS 线下团队",
        "CASE WHEN c.business_line='abroad' THEN '留学' ELSE c.home_group END AS 所属业务组",
        _line('c.business_line')+' AS 主业务',
        "CASE c.product_scope WHEN 'all' THEN '合计' WHEN 'study_abroad' THEN '留学' ELSE '小语种' END AS 产品范围"]
    for field,label in [('self','自主创造'),('self_rate','自创率'),('target','目标'),('completion','本业务完成率'),
                        ('received','额外接收'),('own_total','本业务合计'),('output','额外输出'),('created_total','自创合计')]:
        for metric,suffix in [('orders','工单'),('cash','现金')]:
            columns.append(f"max(c.\"{field}\") FILTER(WHERE c.metric='{metric}')::DOUBLE AS \"{label+suffix}\"")
    columns += ["coalesce(p.pending_count,0)::DOUBLE AS 个人待核数",
        "CASE WHEN bool_or(c.confirmed_history) THEN '历史确认汇总；未提供状态及自创明细' ELSE '按已提供来源' END AS 历史细分覆盖"]
    return ("WITH pending AS (SELECT month,person,count(*) AS pending_count FROM business.contribution_pending, "
            "UNNEST(affected_people) a(person) GROUP BY month,person) SELECT "+','.join(columns)+
            " FROM business.contribution_capacity c LEFT JOIN pending p ON p.month=c.month AND p.person=c.person GROUP BY ALL")


def _annual_products():
    return ("SELECT name AS 六维人员,CASE domain WHEN 'training' THEN '语培' WHEN 'study_abroad' THEN '留学' "
            "WHEN 'small_language' THEN '小语种' ELSE '未归属产品' END AS 产品,"+
            _presentation_double('orders')+" AS 工单,"+_presentation_double('cash')+" AS 现金,"+
            _presentation_double('heads')+" AS 独立人头,"
            "CASE WHEN domain<>'unmapped' AND orders<>0 THEN heads/orders END AS 转化率 FROM business.radar_products")


def _annual_targets():
    return ("WITH products AS (SELECT name,CAST(json_group_object(domain,json_object('orders',orders,'cash',cash,'heads',heads,"
            "'conversion',CASE WHEN domain<>'unmapped' AND orders<>0 THEN heads/orders END)) AS VARCHAR) AS product_parts "
            "FROM business.radar_products GROUP BY name) SELECT r.name AS 六维人员,r.home_group AS 所属业务组,"+_line('r.business_line')+
            " AS 主业务,"+_presentation_double('r.orders')+" AS 年度工单,"+
            _presentation_double('r.cash')+" AS 年度现金,"+_presentation_double('r.heads')+" AS 年度人头,r.conversion AS 年度转化率,"
            "r.cash_capacity::DOUBLE AS 年度现金目标,r.cash_progress_completion AS 现金时间进度完成率,"
            "r.start_date AS 年度开始,r.through_date AS 年度截止,r.peer_count::VARCHAR AS 同组人数,p.product_parts AS 产品分域 "
            "FROM business.radar_people r JOIN products p USING(name)")


def _personal_channels(prep=False):
    sql = ("WITH channels AS (SELECT period_id,name,state,coalesce(nullif(trim(first_channel),''),'一级渠道待确认') AS first_channel,"
           "coalesce(nullif(trim(second_channel),''),'二级渠道待确认') AS second_channel,"
           "coalesce(sum(value*weight) FILTER(WHERE comparison='actual'),0)::DOUBLE AS orders "
           "FROM business.personal_events WHERE month_mode='calendar' AND business_line='abroad' AND metric='orders' GROUP BY ALL) "
           "SELECT ch.period_id AS 期间,ch.name AS 人员,CASE left(ch.state,1) WHEN '1' THEN '包含' ELSE '不含' END AS 含删除回收,"
           "CASE right(ch.state,1) WHEN '1' THEN '包含' ELSE '不含' END AS 含死单,m.start_date AS 窗口开始,m.through_date AS 窗口结束,"
           "ch.second_channel AS 二级渠道,ch.first_channel AS 一级渠道,m.actual::DOUBLE AS 本人工单分母,c.actual::DOUBLE AS 本人现金,"
           "ch.orders AS 工单,NULL::DOUBLE AS 同期,NULL::DOUBLE AS 同比,ch.orders/nullif(m.actual,0) AS 本人占比 "
           "FROM channels ch JOIN config.people p ON p.name=ch.name JOIN business.personal_metrics m "
           "ON m.period_id=ch.period_id AND m.name=ch.name AND m.state=ch.state AND m.month_mode='calendar' AND m.business_line='abroad' AND m.metric='orders' "
           "JOIN business.personal_metrics c ON c.period_id=ch.period_id AND c.name=ch.name AND c.state=ch.state AND c.month_mode='calendar' "
           "AND c.business_line='abroad' AND c.metric='cash' WHERE p.business_line='abroad' AND p.home_group='高中'")
    if not prep:return sql+" ORDER BY ch.first_channel DESC,ch.second_channel DESC"
    prefix="""{% set groups = filter_values('业务组', remove_filter=True) %}
{% set mask = (1 if '青少' in groups else 0) + (2 if '初中' in groups else 0) + (4 if '高中' in groups else 0) %}
"""
    return (prefix+'SELECT *,NULL::VARCHAR AS 业务组 FROM ('+sql+') selected '
            'WHERE ({{ mask }} & 4)<>0 ORDER BY 一级渠道 DESC,二级渠道 DESC')


def direct_sql(key):
    if key in ('overview_personal_channels','prep_personal_channels'):
        return _personal_channels(key.startswith('prep_'))
    if key=='capacity_month':return _capacity()
    if key=='capacity_annual_targets':return _annual_targets()
    if key=='capacity_annual_products':return _annual_products()
    if key=='capacity_pending_count':
        return ("SELECT c.month AS 产能月份,count(p.key) AS 全月待核数 FROM "
                "(SELECT DISTINCT month FROM business.contribution_capacity) c LEFT JOIN business.contribution_pending p "
                "ON p.month=c.month GROUP BY c.month")
    if key=='capacity_pending':
        return ("WITH expanded AS (SELECT month AS 产能月份,a.person AS 人员,source_label AS 来源,reason AS 原因 "
                "FROM business.contribution_pending,UNNEST(affected_people) a(person)), roster AS ("
                "SELECT DISTINCT month,person,concat("+_line('business_line')+",' · ',CASE WHEN business_line='abroad' THEN '留学' ELSE home_group END) AS 线下团队 "
                "FROM business.contribution_capacity WHERE state='01') SELECT e.产能月份,e.人员,r.线下团队,e.来源,e.原因,count(*) AS 待核记录数 "
                "FROM expanded e LEFT JOIN roster r ON r.month=e.产能月份 AND r.person=e.人员 GROUP BY ALL")
    if key=='capacity_markers':
        return ("SELECT month AS 产能月份,affected_people_text AS 涉及人员,source_label AS 来源,reason AS 原因,"
                "source_value AS 原值,"
                "work_order_id AS 工单ID,resource_id AS 资源ID FROM business.contribution_marker_diagnostics")
    if key=='facts':
        source="(SELECT * REPLACE(CAST(event_date AS DATE) AS event_date,CAST(source_record AS VARCHAR) AS source_record) FROM business.facts)"
        return _legacy()[key].replace('queries.acquisition_facts',source)
    if key in ('overview_window','virtual_window','prep_window','university_window','online_window'):
        period='线上期间' if key=='online_window' else '期间'
        return (f'SELECT period_id AS "{period}",label AS 统计期间,start_date::VARCHAR AS 开始日期,through_date::VARCHAR AS 截止日期,'
                "time_progress AS 时间进度,CASE status WHEN 'available' THEN '已提供' WHEN 'future' THEN '尚未开始' ELSE status END AS 状态 FROM business.periods")
    return None
