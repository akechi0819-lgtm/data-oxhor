# Dashboard Product

独立的静态看板生成器。它读取已确认工作区的当前 Snapshot，通过 Data Platform 的受控 Saved Query 生成不可变 `artifact.json`，再从该 artifact 渲染 `artifact.html`。看板不直接连接 DuckDB，不读取 `latest` 指针，也不修改 Bridge。

## 运行

在项目父目录执行：

```bash
cd "/Users/akechi/Desktop/manager -CowH"
python3 -m dashboard_product.refresh refresh \
  --workspace customers/bi_operations \
  --run-id run_dashboard_<yyyymmdd>
python3 -m dashboard_product.refresh render \
  --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<yyyymmdd>/artifact.json
```

输出目录为 `customers/bi_operations/Output/Dashboard/<run_id>/`，包含 `artifact.json` 和 `artifact.html`。`push` 子命令目前明确返回 `not_started`。

## 当前数据口径

- 现金与工单独立计算。现金先按现金表 `团队` 映射业务组：青少→留学预备；初中、初中国际学科、ICC、国际学科→高中；大学→大学；其余→暂无法匹配。
- 现金范围为 `渠道属性=被动`、`新老生类型=新生`、`报入现金收入>0`，按现金明细行保留，不去重。
- 工单只统计被动工单并按工单 `ID` 去重。工单 ID 仅在同一业务组内用于拆分渠道，不改变现金业务组总额。
- 未匹配工单的现金按顺序归属：市场活动名含“虚拟人”→线上私域；含“线上”→线上平台；渠道含“TMK”→线下；市场活动名含“校代”→线下；其余→线上平台。兜底归属不等于工单匹配成功。
- 业务组和团队按自然月聚合；人员按每月 26 日至次月 25 日的绩效月聚合。
- 同比按月序列切片：FY27 月序列为 2026-06 至 2027-05，FY26 对应为 2025-06 至 2026-05。选择 Q1 时双方都只取 6-8 月。

## 配置与来源

`config/project_targets.json` 保存 FY27 目标，`config/people.json` 保存人员组织配置。查询合同见 [`config/saved_queries.json`](config/saved_queries.json)；正式 SQL 位于客户工作区的 Saved Query registry：`dashboard_actuals/v6` 供刷新使用，`attributed_passive_reported_cash/v1` 供逐笔对账和后续分析使用。

当前工作区和 Bridge 由 `customers/bi_operations/Work/workspace.json` 指定；当前 Bridge 为 `company_bridge.bi_operations.v1_2_0.json`。

## 验收状态

截至 2026-09-05，核心展示与筛选已完成。Q1 对账结果：留学预备 FY27 `2,184,474.60` 元、FY26 `2,145,863.30` 元；高中 FY27 `1,465,735.50` 元；大学 FY27 `4,988,473.20` 元、FY26 数仓 `4,699,695.10` 元。大学 FY26 与线上看板差异 `6,979.90` 元，业务方确认可接受。

详细状态见 [`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md) 和 [`docs/HANDOFF.md`](docs/HANDOFF.md)。
