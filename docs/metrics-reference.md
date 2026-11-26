<!-- 由 config/metrics.yaml 生成，使用 ops render-rules 更新。 -->

# 经营分析指标索引

用 ./oxhor status 查看版本，再以 ./oxhor query --release-id 显式绑定同一封存仓。需要底层来源明细时使用 --layer raw 与 --snapshot-id。

| 指标 | 经营汇总关系 | 明细证据关系 | 默认范围 | 日期 | 限制 |
| --- | --- | --- | --- | --- | --- |
| 语培工单 | mart.team_metrics | core.training_orders_attributed | training / total / 被动，全部新老生 | 分配时间 | 按范围内工单 ID 去重；异业渠道可查 core.training_channel_orders_attributed。 |
| 语培现金 | mart.team_metrics | core.training_cash_attributed | training / total / 被动，全部新老生 | 业务日期 | 保留正、零和负向现金，按筛选范围汇总。 |
| 语培经营人头 | mart.team_metrics | core.training_heads_attributed | training / total / 被动，全部新老生 | 业务日期 | 按期间、范围、班级资格计算，按学员去重；渠道维度证据另见 core.dimension_heads_attributed。 |
| 留学及小语种资源 | mart.team_metrics | core.abroad_facts_attributed | abroad / total / 全部 | 分单日期 | 各范围排除 SSC；线上含虚拟人，独立来源缺覆盖不补零。 |
| 留学及小语种现金 | mart.team_metrics | core.abroad_facts_attributed | abroad / total / 全部 | 留学归档日期 / 小语种业务日期 | 仅纳入正向签约或实缴；保留按来源表的业务组口径。 |
| 留学及小语种签约人头 | mart.team_metrics | core.abroad_heads_attributed | abroad / total / 全部 | 留学归档日期 / 小语种业务日期 | 线上、线下和总计独立去重；留学客户和小语种学员分列。 |
| 官方留学记分卡 | mart.study_abroad_summary | ref.official_scorecard | 仅原文件明确的期间、范围、维度和指标 | 记分卡期间起止日 | 仅对齐范围、覆盖和统计口径后可比，无对齐证据时不计算差值。 |
| 渠道、学校及业务组 | mart.dimension_metrics | core.training_channel_orders_attributed | 显式选择期间、管理单元、获取范围、维度 | 对应经营工单日期或现金业务日期 | 子组人头不能相加替代父值。 |
