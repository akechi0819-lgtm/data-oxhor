# 看板发布 Agent

## 负责范围

对已确认业务口径运行固定 saved query，刷新看板 artifact、渲染静态 HTML 并执行发布。它不做开放式分析，不让模型在刷新时改变指标公式、筛选条件或归属规则。

## 运行入口

```bash
python3 -m dashboard_product.refresh refresh \
  --workspace customers/bi_operations \
  --run-id <run_id>
python3 -m dashboard_product.refresh render \
  --artifact <artifact.json>
```

发布流程、环境变量和服务器步骤见 [看板部署说明](../../dashboard_product/DEPLOYMENT.md)。当前数据合同和已知问题见 `dashboard_product/docs/`。

## 必须遵守

- 只使用已确认的 saved query 和明确的 `snapshot_id`。
- 原始工作簿、DuckDB、Parquet 和明细数据不得发布到服务器。
- 指标定义需要变更时，先由自由分析 Agent 完成证据和确认，再修改 saved query、Bridge 与看板合同。
- 发布前验证 artifact 和 HTML 非空且可打开。
