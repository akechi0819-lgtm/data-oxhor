# 看板交接

更新时间：2026-09-05

## 产品边界

`dashboard_product` 是静态看板生成器。它不直接访问 DuckDB，不修改 Bridge，不依赖 `latest` 指针；所有事实来自当前工作区 Snapshot 的 Data Platform Saved Query 结果。

## 运行合同

从 `/Users/akechi/Desktop/manager -CowH` 执行：

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/bi_operations --run-id run_dashboard_<id>
python3 -m dashboard_product.refresh render --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json
```

刷新读取 `customers/bi_operations/Work/workspace.json` 的 `current_snapshot_id`，调用 `dashboard_actuals/v6` 两次：当前窗口和上一财年对应窗口。输出写入 `customers/bi_operations/Output/Dashboard/<run_id>/`。

## Artifact 合同

顶层字段：`schema_version`、`artifact_id`、`run_id`、`snapshot_id`、`created_at`、`query_results`、`errors`、`dashboard`。

`dashboard` 至少包含：

- `months`: `2026-06` 至 `2027-05`
- `prior_months`: `2025-06` 至 `2026-05`
- `teams[].groups[].monthly_actuals`: FY27 现金/工单数组
- `teams[].groups[].prior_monthly_actuals`: FY26 对应现金/工单数组
- `teams[].groups[].quarter_targets`、`annual_targets`
- `teams[].people[].monthly_actuals`: 绩效月数组

渲染器只接受当前结构；旧 `metrics`、`prior_totals`、`bus_monthly` 结构不再兼容。Q1 是 FY27 的 2026-06 至 2026-08，FY26 同比取 2025-06 至 2025-08。

## 业务口径

现金和工单独立计算。现金筛选 `渠道属性=被动`、`新老生类型=新生`、`报入现金收入>0`，按现金表 `团队` 映射业务组；现金通过 `工单ID` 左连接工单表获取一级、二级渠道，无法关联时渠道固定为 `暂无归属`。团队归属仍按“工单匹配→虚拟人→线上→TMK→校代→默认线上平台”顺序处理。

Bridge v1.2 与 Saved Query 已对齐：正式 Bridge 为 `artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json`；可复用逐笔底稿为 `attributed_passive_reported_cash/v1`。

## 验收与限制

2026-09-05 已完成核心看板和 FY26/FY27 Q1 对账：留学预备 FY27 `2,184,474.60` 元、FY26 `2,145,863.30` 元；高中 FY27 `1,465,735.50` 元；大学 FY27 `4,988,473.20` 元、FY26 数仓 `4,699,695.10` 元。大学差异 `6,979.90` 元，业务方确认可接受。

未关联工单的现金仍保留在总量中，并仅在渠道维度标记为 `暂无归属`；负向现金不自动解释为退款。`push` 尚未实现。

## 验证

```bash
cd "/Users/akechi/Desktop/manager -CowH"
python3 -m unittest discover -s dashboard_product/tests -v
python3 -m interfaces.company_bridge validate \
  --bridge artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
```
