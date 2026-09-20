> 历史存档：原路径 `dashboard_product/docs/BRIDGE_SAVED_QUERY_UPGRADE_PLAN.md`，于 2026-09-18 目录整理时归档。以下状态、命令、版本与凭据配置描述仅代表记录当时，不是当前操作入口。当前项目状态见 [DEVELOPMENT.md](../../../DEVELOPMENT.md)；看板现行操作见 [DEPLOYMENT.md](../../../dashboard_product/DEPLOYMENT.md)。

# 市场归属现金：Bridge 与 Saved Query 升级计划

**状态：看板已实施；刷新运行口径以 `dashboard_actuals/v7` 的实际 SQL 为准（当前 2026-09-09）。**

已基于验收后的现金逻辑登记可复用逐笔底稿。看板继续使用 `dashboard_actuals/v7`；其同比 artifact 投影已独立修复为按上一财年逐月切片，不改变该 Saved Query 的 SQL。正式 Bridge 用于字段与业务语义校验，刷新不直接执行 Bridge 的现金业务组 Override。

## 目标

将看板内已经确认的“被动报入现金筛选、工单关联和市场团队归属”沉淀为企业级可复用事实底稿。该底稿供看板、市场团队贡献分析和异常分析使用，避免各处重复维护现金归属 SQL。

它只定义**被动获客的正向报入现金收入**，不等同于净现金、退款或团队全部业绩。

## 边界与职责

| 内容 | 归属 |
| --- | --- |
| 字段语义、现金明细粒度、工单关联语义、团队归属业务政策 | Company Bridge |
| 筛选、关联、日期解析、分配优先级的可执行 SQL | Data Platform Saved Query |
| 看板的展示聚合 | `dashboard_product` |
| 当前 Snapshot 的金额、对账结果和异常样例 | 受控查询结果；需要复用方法时可另存 Casebook |

Bridge 不保存 SQL。Saved Query 不保存旧 Snapshot 的结论或历史金额；Saved Query manifest 也不绑定某个日期的 Snapshot，日常运行使用调用方显式传入并由仓库元数据验证的当前 Snapshot。

## 已升级 Bridge

基线 `bridge_bi_operations` v1.1.0 已升级为 [`company_bridge.bi_operations.v1_2_0.json`](../../../tests/fixtures/company_bridge/company_bridge.bi_operations.v1_2_0.json)。客户工作区已明确引用 v1.2.0。

### 新增字段语义

| 物理字段 | Bridge 目标 | 已确认含义 |
| --- | --- | --- |
| `报入现金收入` | `cash.payment` | 被动市场贡献口径使用的现金流入字段；该口径只统计正向值。 |
| `业务日期` | `time.cash_transaction_date` | 现金事实的统计日期。 |

现有 `现金收入 -> cash.net_cash` 映射保留。`报入现金收入` 不能被当成 `现金收入` 或净现金的别名。

### 明细与关联政策

1. 一条现金源明细行是一条现金事实；同一工单可有多条现金明细，不能因工单关联而去重。
2. 现金 `工单ID` 与工单 `ID` 只允许非空、修剪后的文本精确匹配；Saved Query 不做数值化转换。
3. 被动市场现金范围为 `渠道属性 = 被动`、`新老生类型 = 新生` 且 `报入现金收入 > 0`。
4. 未关联工单时，现金业务组映射为：青少 -> 青少；初中、初中国际学科 -> 初中；高中、ICC、国际学科 -> 高中；大学 -> 大学。现金不跟工单业务组改口；目标区再把青少+初中滚成留学预备。

### 团队归属政策

该政策只适用于上面范围内的现金记录。

1. 工单 ID 精确关联到有效工单时，采用工单的业务组和团队归属。
2. 工单 ID 未关联时，依次判断：
   1. 市场活动名称含“虚拟人” -> `online_private`（线上私域）。
   2. 否则，市场活动名称含“线上” -> `online_platform`（线上平台）。
   3. 否则，渠道含“TMK” -> `offline_market`（线下市场）。
   4. 否则，市场活动名称含“校代” -> `offline_market`（线下市场）。
   5. 其余 -> `online_platform`（线上平台）。

“默认线上平台”是业务兜底，不表示工单 ID 已关联成功。实现和分析输出必须保留关联状态，不能将团队已分配误表述为工单已对账。

## 已登记 Saved Query

| 项目 | 契约 |
| --- | --- |
| Query ID | `attributed_passive_reported_cash` |
| 当前版本 | `v1` |
| 输入 | `start_date`、`end_date`；按业务日期使用 `[start_date, end_date)` |
| 输出粒度 | 现金源明细行，不做现金去重 |
| 数据来源 | 当前显式 Snapshot 的现金明细表和工单明细表 |
| 执行方式 | `run-saved-query`，每次显式提供 `snapshot_id`、`run_id` 和输出目录 |

### 最小输出字段

| 字段 | 含义 |
| --- | --- |
| `cash_date` | 业务日期 |
| `reported_cash_amount` | 正向报入现金收入 |
| `business_group` | 留学预备、高中、大学；未映射记录不进入正式看板汇总 |
| `team_id` | `offline_market`、`online_private`、`online_platform` |
| `is_work_order_matched` | 是否按工单 ID 精确关联成功 |
| `attribution_rule` | `work_order_match`、`campaign_virtual_human`、`campaign_online`、`channel_tmk`、`campaign_campus_agent`、`default_online_platform` 之一 |
| `cash_work_order_id` | 现金侧工单 ID |
| `cash_channel` | 现金侧渠道 |
| `cash_campaign_name` | 现金侧市场活动名称 |
| `cash_source_row_number` | 现金源行号，用于逐笔对账 |
| `source_relation` | 当前 Snapshot 中的来源关系 |

`business_group` 的无法归属与 `is_work_order_matched = false` 是两个不同问题，必须分别保留和报告。

## 接入与回归

1. 已复核验收后的现金筛选、粒度、业务组映射和未匹配优先级，并通过 Data Platform 正式登记 `attributed_passive_reported_cash/v1`。
2. 已升级 Bridge v1.2.0：新增 `报入现金收入 -> cash.payment`，并登记被动新生正向报入现金范围、现金业务组映射、工单文本精确关联和团队兜底归属政策。
3. Saved Query 回归运行：`run_attributed_passive_reported_cash_v1_20260905`，Snapshot 为 `snapshot_bi_work_order_id_20260904`，返回 5,030 条现金源明细；团队归属为空为 0，查询输出保留 `is_work_order_matched=false` 与 `attribution_rule`。
4. Q1（2026-06-01 至 2026-09-01）汇总为 `12,748,539.70` 元，当时与 `dashboard_actuals/v6` 同窗口的现金汇总一致。
5. 当前看板不纳入未映射业务组记录；工单未关联记录仍按确认的团队兜底规则归属，渠道统一显示为 `暂无归属`。
6. 看板未改为消费逐笔底稿，仍消费 `dashboard_actuals/v7`；刷新链路保持不变。新查询供后续异常分析、自由探索和未来看板重构时直接复用。

## 后续使用

当问题属于“线下市场团队贡献”“线上/线下市场归属”“被动获客现金异常”时，分析应先运行该 Saved Query，再按团队、业务组、校区、产品或时间窗口汇总下钻。若问题问的是团队全部业绩、净现金、退款或工单量，则必须另行确认适用事实和指标，不能把本底稿扩大使用。

## 验证凭据

- Saved Query registry：`customers/bi_operations/Work/SavedQueries/attributed_passive_reported_cash/v1/`
- Saved Query SHA-256：`78d3bd7a2e707bd6d4e1e81c25e6e8d659825d37849844f362c9e72ef63715b4`
- Bridge 校验：`python3 -m interfaces.company_bridge validate --bridge artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json`，结果 `passed`。
