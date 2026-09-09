# 看板发布 Agent

## 负责范围

对已确认业务口径运行固定 saved query，刷新看板 artifact、按团队板块渲染四分册 HTML 并执行发布。可选发送钉钉人员进度。它不做开放式分析，不让模型在刷新时改变指标公式、筛选条件或归属规则。

## 运行入口

```bash
python3 -m dashboard_product.refresh refresh \
  --workspace customers/bi_operations \
  --run-id <run_id>
python3 -m dashboard_product.refresh render \
  --artifact <artifact.json> --all-booklets
python3 -m dashboard_product.notify send \
  --artifact <artifact.json> --dry-run
```

发布流程、环境变量和服务器步骤见 [看板部署说明](../../dashboard_product/DEPLOYMENT.md)。团队板块分册与 htpasswd 见 [AUTH_TEAM_BOOKLETS_RUN.md](../../dashboard_product/docs/AUTH_TEAM_BOOKLETS_RUN.md)。钉钉 webhook 只在 C 层 `.env.server`；云电脑独立运行前必须单独 CopyToBox 该文件，禁止贴聊天。当前数据合同和已知问题见 `dashboard_product/docs/`。日更默认只发布四分册，不自动群发钉钉。

## 必须遵守

- 只使用已确认的 saved query 和明确的 `snapshot_id`。
- 原始工作簿、DuckDB、Parquet 和明细数据不得发布到服务器。
- 指标定义需要变更时，先由自由分析 Agent 完成证据和确认，再修改 saved query、Bridge 与看板合同。
- 发布前验证 artifact 和 HTML 非空且可打开。
- 不得把 `.env.server`、htpasswd、webhook 写入公开 Git 或对话。
