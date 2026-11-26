# Bridge 与看板口径对照（2026-11-23）

> 本文是 2026-11-23 的逐项核对和版本回执。留学线上、SSC、签约团队的经营汇总规则于 2026-11-26 更新，现行执行范围见[集成指南](integration-guide.md#22-隔离留学仓与腾讯更新现行)；本文保留当时证据。

本次核对以工作区绑定的 Bridge 和本地看板代码为依据。经营现金与项目毛签的初中归属已由业务确认。工作区绑定 `Work/Bridge/reference.json`，身份 `bridge_bi_operations`、版本 `1.7.4`，SHA-256 为 `3e6434ee5dd61ba91e1121dfac858e2c7349971641435121850741ab1eb5e068`。原 1.7.3 已保存，其 SHA-256 `937c378eb6cd77651cffd21484dda4dc92829bbc978714b7d3a1b464f5e60db7` 与本次 11 月 23 日 SQL release 的 `semantics` 登记值相同。对照的是 [本次 release](../customers/shadow_bi_daily/Output/ShadowDaily/run_shadow_daily_20261123_121908/sql-attempts/daily-sql-20261123-122141104860-ab4a707d7a/release-output/daily-sql-20261123-122141104860-ab4a707d7a/library/release.json)，并非对服务器当前指针的独立核验。release 将 Bridge 摘要封存，见 [发布实现](../dashboard_product/shadow_bi/p5/sql_bundle.py#L126)。

| 条目 | 对照结论 | 证据与处理 |
|---|---|---|
| 现金项目组 | **已修正**：原 1.7.3 将初中和初中国际学科归高中，且未列高中；1.7.4 按用户确认将二者归留学预备，并补高中归高中。 | [Bridge](../customers/shadow_bi_daily/Work/Bridge/reference.json#L730)、[项目现金 SQL](../dashboard_product/management/sql/new_student_cash.sql#L9)。现行项目汇总为青少、初中、初中国际学科→留学预备；高中、ICC、国际学科→高中；大学→大学；其他不可拆分。训练明细先分青少、初中、高中、大学，再把青少和初中合并项目组，见 [明细](../dashboard_product/management/sql/training_details.sql#L95)、[归一](../dashboard_product/shadow_bi/sql_warehouse/training.py#L286)。用户已确认此为经营现金和项目毛签的项目汇总口径。 |
| 被动报入现金 | 已一致于当前明细范围：按请求渠道属性筛选，保留报入现金正、零、负，新老生可筛选。 | [Bridge](../customers/shadow_bi_daily/Work/Bridge/reference.json#L715)、[明细](../dashboard_product/management/sql/training_details.sql#L106)。负数原因不得推断为退款。 |
| 毛签与被动现金 | 适用范围不同：Bridge 的毛签取正报入现金；项目现金 SQL 取正数但还按新老生类型分组，不能把它直接当作被动净额或断言 SQL 已实现新签/续费筛选。 | [Bridge](../customers/shadow_bi_daily/Work/Bridge/reference.json#L766)、[项目现金 SQL](../dashboard_product/management/sql/new_student_cash.sql#L1)。当前登记的保存查询未实现这项项目毛签筛选，详见下方调用范围。 |
| 现金渠道与团队归属 | 不能用单一默认归属概括：先取工单渠道；后续归属先处理 TMK激活-平台，其余依次判断 TMK/激活、冲突、虚拟人、原团队、讲座、活动文本、平台等。 | [关联](../dashboard_product/management/sql/training_details.sql#L114)、[优先顺序](../dashboard_product/shadow_bi/sql_warehouse/training.py#L413)。具体条件包括原团队为空或现金渠道含 TMK；推断标志会影响个人考核，见 [人头](../dashboard_product/shadow_bi/sql_warehouse/sql/personal.sql#L86)。Bridge 的自然语言概述不应替代完整条件；是否修订为完整规则待业务确认。 |
| 人头、工单 | 范围不同，不能互换：个人训练人头为正现金且有学员 ID 的去重结果，并排除推断归属；留学和小语种人头分别按 ID 去重。 | [个人计算](../dashboard_product/shadow_bi/sql_warehouse/sql/personal.sql#L86)。留学资源经入仓及 SQL 两阶段处理，签约保留事实明细；资源删除/回收标记为不计完成，签约取正额，见 [留学事实](../dashboard_product/shadow_bi/sql_warehouse/abroad.py#L348)及[完成规则](../dashboard_product/shadow_bi/sql_warehouse/abroad.py#L576)。 |
| 留学、小语种 | 适用范围不同：当前经营来源为资源、留学签约、小语种签约三表；Bridge 中旧工单渠道筛选已标明仅用于旧 BI 工单归因和历史复算。 | [来源](../data_acquisition/jobs/build_study_abroad_warehouse.py#L57)、[Bridge 限定](../customers/shadow_bi_daily/Work/Bridge/reference.json#L866)、[产品划分](../dashboard_product/shadow_bi/sql_warehouse/sql/contribution.sql#L75)。官方记分卡覆盖范围仍以记分卡为准。 |
| 学校 | 范围不同：训练事实按学校属性和大学名单匹配，留学事实当前 school_name 为空；Bridge 未提供可直接套用的学校分类定义。 | [训练学校](../dashboard_product/shadow_bi/sql_warehouse/training.py#L552)、[留学字段](../dashboard_product/shadow_bi/sql_warehouse/abroad.py#L629)。 |

下游方面，留学建仓读取已确认的 Bridge 渠道规范化规则与部分年级覆盖，见 [解析](../dashboard_product/shadow_bi/sql_warehouse/abroad.py#L106)和[配置](../dashboard_product/shadow_bi/sql_warehouse/abroad.py#L172)；MCP 业务上下文校验 release 中的 Bridge 摘要，见 [校验](../business_data_mcp/context.py#L78)。本次未发现 Python 消费者直接执行现金项目组 override，但宿主可读取该语义文本，错误仍可能误导分析。历史测试 fixture 是 1.2.0，不代表当前 Bridge。

正式修订应按 [Bridge 合同](company-bridge-contract.md#1-边界与消费者)准备候选并经人工确认，再以新版本构建、做 Pack 和当前 Snapshot 兼容检查；对齐服务禁止覆盖已有版本，见 [finalize](../workspace_modeling/bridge_alignment/service.py#L341)。保留已封存 release；若需要新发布，应独立生成新 release 并验证摘要。不能将看板代码观察自动标记为新业务规则的确认。本记录不等同于对所有页面和消费者的全面验收。


## 补充核查：保存查询、经营统计与留学归属

**项目毛签调用范围。** 当前工作区 `Work/SavedQueries` 只有 `dashboard_actuals` 的 v9、v10、v12、v14 和 `attributed_passive_reported_cash` v1；逐个检索没有项目毛签或 `新签&续费` 条件。登记配置明确两类是历史查询，当前 SQL 日更不消费，见 [保存查询登记](../dashboard_product/config/saved_queries.json#L5)。历史 [attributed v1](../customers/shadow_bi_daily/Work/SavedQueries/attributed_passive_reported_cash/v1/query.sql#L39) 确实执行旧映射及被动、新生、正数限定，仍可通过受控 saved-query 接口被显式调用，不能当作当前看板口径。现行 [new_student_cash.sql](../dashboard_product/management/sql/new_student_cash.sql#L1) 汇总全部渠道正数并保留新老生维度，不含新签/续费筛选；SQL 建仓 [绑定](../dashboard_product/shadow_bi/sql_warehouse/build.py#L78)，供 [维度分母](../dashboard_product/shadow_bi/sql_warehouse/sql/dimensions.sql#L420) 使用。它不是已验证实现 Bridge 项目毛签的查询；因此不能由该 SQL 的分母反推项目毛签。

**经营与个人口径。** [经营统计](../dashboard_product/shadow_bi/sql_warehouse/sql/metrics.sql#L87) 先按团队、主被动、新老生与期间选范围，再对训练现金按学员 ID 和班级编码聚合，金额合计绝对值至少 1500 且至少一行报名人次大于零，最后按学员 ID 去重；并非个人考核的人头算法。留学及小语种经营人头按正签约的客户 ID 分别去重，两个产品同时存在时分别展示，不直接相加。经营工单数是范围内 `orders` 事实的值之和；训练工单来源按非空工单 ID 取源行首条，每条值 1，见 [明细](../dashboard_product/management/sql/training_details.sql#L18)；留学资源事实值为 1。事实保留删除/回收并携带完成资格标志，个人事件还有状态模式筛选，见 [个人筛选](../dashboard_product/shadow_bi/sql_warehouse/sql/personal.sql#L70)；不可据此笼统声称经营工单和个人工单相同。

**留学资源两阶段。** [入仓](../data_acquisition/jobs/build_study_abroad_warehouse.py#L155) 遍历每类来源行，对同一非空资源 ID 保留输入顺序首次遇到的行；不能仅凭该逻辑称其为最新日期。[SQL 阶段](../dashboard_product/shadow_bi/sql_warehouse/abroad.py#L342) 先对 fact_id 取源行序靠前者，再在已输入事实中对规范化资源 ID 取事件日期最新，日期相同时取源行序靠前者；没有规范化资源 ID 时按 fact_id。前一阶段已丢弃的行不会由后一阶段恢复。

**留学渠道和团队归属顺序。** [渠道映射](../dashboard_product/shadow_bi/sql_warehouse/abroad.py#L380) 先精确匹配已确认的三层渠道；否则根渠道别名归一，线上依次使用特殊规则、参考表（参考值“其他”转 SSC），新东方学校推荐取已知部门或其他推荐，渠道合作取对应映射，市场活动依次取交叉、直接、合并规则，未命中保留未解决。仅当目标一级渠道符合已确认年级策略且二级缺失时，才用资源对应年级补高校/中学活动；冲突或缺失保留诊断，见 [年级补充](../dashboard_product/shadow_bi/sql_warehouse/abroad.py#L530)。[团队分段](../dashboard_product/shadow_bi/sql_warehouse/abroad.py#L552) 仅对原分段为留学线下或线上依次判断虚拟人、SSC、网络资源/平台归线上，其余保留来源分段；国际市场、未分配等不由上述条件重新分类。渠道映射与团队分段是两层处理，不能把旧工单渠道规则直接视为三表全量资格规则。

## 1.7.4 生效记录

2026-11-23 用户明确确认经营现金及项目毛签中初中、初中国际学科归留学预备。已用 confirmed_review 构建 1.7.4，并以当前 Pack 与 `snapshot_bi_operations_20261123_121908` 的 describe、quality 回执验证通过；确认输入、校验和旧版存于工作区 `Output/Bridge/1.7.4`、`Output/Bridge/1.7.3`。当前 `Work/Bridge/reference.json` 已切换 1.7.4。已封存的 11 月 23 日 release 未修改，继续绑定 1.7.3 的摘要及其发布时业务上下文；下一次构建将读取当前 1.7.4，须正常生成并验证新 release，本次未发布。

旧版 Bridge 中部分历史 `evidence_refs` 指向已退役的 `customers/bi_operations/Work/workspace.json`、旧 `unified_market_mapping.md` 和旧 `留学-FY26-资源表.xlsx` 路径；旧升级计划迁至 [历史计划](history/dashboard/BRIDGE_SAVED_QUERY_UPGRADE_PLAN.md)。这些路径保留为历史追溯坐标，不替换成新的事实证明。现行工作区入口是 `customers/shadow_bi_daily/Work/workspace.json`，留学参考材料位于其 `Input/Reference/`。1.7.4 本次现金修订候选单独引用当前训练明细、项目现金 SQL 和归一实现作为证据。

## 2026-11-26 留学汇总复核

Bridge 1.7.4 中的虚拟人、SSC 和国际市场是来源分段。正式看板按 [SQL 汇总范围](../dashboard_product/shadow_bi/sql_warehouse/sql/metrics.sql) 计算工单、现金和分产品去重人头，线上包含虚拟人，留学总计排除 SSC 并包含国际市场。签约或实缴无法匹配个人时，明确的线上或线下团队按[留学入仓规则](tencent-docs-study-source.md)计入团队。此次业务确认适用于入仓和看板汇总，Bridge 来源映射无需升版。

[MCP 看板口径摘要](../business_data_mcp/dashboard_business_rules.md)记录上述汇总规则。查询正式指标使用同批看板数据，按来源分段的独立留学仓查询用于对账。新摘要随下一次 SQL release 封存，已发布的上下文仍对应其发布时的摘要。
