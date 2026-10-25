# 影子 BI P2 业务查询库合同

本合同只覆盖本地可重建业务库；P3页面、P4部署和应用权限另验。业务定义继续归现有业务模块，派生库不是第二份权威原始来源。

## 输入与构建

`dashboard_product.management.calculation.calculate` 是唯一管理业务编排入口，复用原SQL及Python规则，返回内存模型和真实受控查询回执。旧 `management.build` 仅调用它并打包旧页面；`shadow_bi.library` 调用它建立派生库。没有规则引擎、配置语言或工单×现金明细连接。

构建必须显式提供工作区、BI Snapshot、留学 Snapshot、run-id和as-of-date。工作区指针仍由原受控入口核对。每批输出 `Output/ShadowBI/<run-id>/library/`，存在即拒绝覆盖；失败不切换任何旧状态。`copy-inputs` 复制 `Work`、`Input` 和留学历史查询证据目录（包括lineage明确依赖的三份父Snapshot回执），不复制旧看板结果。历史查询证据属于来源闭包，不能因它位于Output目录就删去。

`library_manifest.json` 的 `business_query_library.v1` 绑定两个来源Snapshot、实际覆盖、规则/SQL/配置文件SHA、源输入及父Snapshot历史证据SHA、本次实际受控查询回执、各表行数/逻辑摘要，以及关闭写连接后的 `business.duckdb` 大小/SHA。计算前后、派生库封口前分别核对输入和规则未变。重建比较表内完整逻辑内容，数据库二进制、批次身份和执行时间允许不同。旧输出仅由独立验收程序读取，构建程序不读取它们。

## 实际消费者与表

所有表位于现有允许的 `queries` schema，没有放开新的全局schema。每行另保留 `row_json` 完整对象；已知筛选字段为标量列，嵌套 `view` / `person` 列为JSON文本，可用DuckDB JSON函数取值。事实金额为DECIMAL，原精度贡献的 `weight`、`source_value`、`credited_value` 为原Decimal文本，不能先舍入再汇总。人数和比率优先使用既有预计算视图，不把任意GROUP BY之和当独立总数。

| 表 | 粒度/消费者 |
|---|---|
| facts | 唯一fact_id；工单/现金/留学事实，保留状态、来源键、身份域、归属、计入标记、逐行来源；明细下钻与审计 |
| order_source_rows、training_source_rows | 原受控查询完整结果；人员规则/状态和来源回查，分别保存，不相互直接多对多连接 |
| market_orders | 总盘工单已验证逐ID范围；不能用normalized facts的计数替代 |
| new_student_cash | 被动现金占比分母输入；团队切换不改变全渠道新生正向报入分母 |
| contributions、pending_contributions、marker_diagnostics | 人员×源事件×分配桶，原精度贡献、待核及跨线例外，保留状态inclusion四态 |
| periods、team_periods | 期间元数据与期间×管理单元完整结果；含总盘/目标/学校/渠道/年级/国家/团队作用域及空值状态 |
| person_periods | 期间×管理单元×月模式×人员×双状态组合；person保存固定现金/人头/目标，view保存该状态下的既有工单指标 |
| selection_team_periods | 7种既有业务组选择×期间；保留青少/初中/高中有限组合，不新增自由规则语言 |
| capacity_people、radar_axes | 自然月×人员×状态贡献视图，以及年度本人/同组均值六维；年度不随个人月份广播 |
| activities | 活动实际累计，保留语培/留学/总量、人头/现金和覆盖；投入仍为P1会话交互，不写库 |
| online_lines、online_platforms、online_groups、online_daily | 线上期间/业务线、平台、业务组和日明细；保留各自覆盖及ROI共同窗口 |
| people、schools、channels、calendar | 实际消费者需要的名单/业务线身份域学校/渠道、自然月和绩效月；不合并跨系统学员身份 |
| expense_rows、expense_sources、advertising_rollup、platform_audit | 原粒度费用、覆盖来源、同窗结果、平台匹配依据；期间费用不拆日、缺失不补零 |
| target_roster_references、personnel_history、coverage | 实际目标及名单配置、已有历史汇总、来源覆盖；未配置、未提供、无同期与0不同 |

官方记分卡不导入任何表。manifest只绑定该外部文件摘要；留学官方覆盖内的回答仍先读原记分卡并优先使用，数仓用于明细、诊断和对账。历史6—8月汇总由原 `apply_history` 复用，不伪造逐笔状态或自创贡献。

## Agent 受控查询

入口：`python3 -B -m interfaces.business_library describe|query`。必填 `--library`、`--batch-id`；query另需 `--sql-file`、`--run-id`、`--output-root`，可提供 `--params-json`、`--max-rows`、`--max-result-bytes`。只接受一个SELECT、只读连接且关闭外部访问；沿用Data Platform外部读取/系统schema/多语句门禁，并拒绝未登记业务关系。行数或字节超限报错，不返回截断结果；完整明细应明确分页。

`business_query_result.v1` / `business_query_receipt.v1` 与原Snapshot回执分开，不能把派生批次冒称原始Snapshot。每份回执记录实际SQL/参数/完整结果的大小和SHA、查询run、业务批次、库manifest和数据库摘要、两个Snapshot身份、源查询链、规则/参考绑定摘要、实际关系与限制。`read_library_result`验证路径/字节/行列/响应身份；Agent不得直接连接客户DuckDB或派生库绕过此入口。Superset驱动由P1验证，应用权限及文件隔离仍由P4完成。

本阶段没有发布、服务器写入、生产任务或通知投递。留学截至2026-10-13；观远160/23/20差异仍open。
