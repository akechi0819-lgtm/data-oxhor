# 看板发布 Agent

## 负责范围

运行已确认的固定查询，刷新看板 artifact、渲染四分册 HTML 并发布。不得在刷新时改变业务口径。

```bash
python3 -m dashboard_product.refresh refresh --workspace <workspace> --run-id <run_id>
python3 -m dashboard_product.refresh render --artifact <artifact.json> --all-booklets
```

人员进度计算和钉钉推送由 [日常监控 Agent](../daily_monitor/AGENT.md) 与 `monitoring_product/` 负责，不属于看板发布入口。

## 必须遵守

- 只使用已确认的 saved query 和明确 Snapshot。
- 业务口径变更先完成证据核对和人工确认。
- 只发布四分册静态 HTML；不得上传源文件、数仓、全量 artifact 或密钥。
- 发布前验证文件可打开且内容非空。
- 与监控共用 `workspace_modeling/operations/` 的绩效月、人员匹配规则及花名册，不复制维护第二份。
- 部署见 [看板部署说明](../../dashboard_product/DEPLOYMENT.md)。
