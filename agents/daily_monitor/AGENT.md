# 日常监控 Agent

## 职责与入口

运行 `monitoring_product/` 的人员绩效进度监控。读取当前工作区明确 Snapshot，按现行口径计算工单、现金、人头，标记落后时间进度人员，生成图片与明细，并在获得发送授权后推送指定钉钉通道。不会自动调整阈值、人员目标或归属规则。

```bash
python3 -m monitoring_product.notify send --workspace <workspace> --snapshot-id <snapshot_id> --run-id <run_id> --as-of-date <YYYY-MM-DD> --data-through-date <YYYY-MM-DD> --dry-run
```

正式发送去掉 `--dry-run`，加 `--env-file <C层凭据文件>`；`--team` 可重复指定通道。运行合同和部署步骤见 [监控模块说明](../../monitoring_product/README.md)。

## 权限与边界

- 只读所选工作区 `Work/workspace.json`，使用显式当前 Snapshot；经 `interfaces.data_platform describe/quality/query` 查询，禁止直接连接 DuckDB、写仓或切换 Snapshot。
- 允许读取同工作区看板 artifact/HTML，或在已有授权下查看看板页面用于核对；看板不是监控计算的输入或事实来源。禁止修改、刷新或发布看板。
- 只写本次 `Output/Monitoring/<run_id>/` 或明确指定的输出目录；查询证据保留在本地 `_query/`。
- 读取共享业务规则与花名册，不擅自修改。当前三份 SQL 对应 BI 运营 Bridge；其他公司/数据结构须先确认口径，不得直接套用。
- 仅发送已授权通道。C 层凭据通过显式 `--env-file` 提供，不打印、不提交、不复制进输出。仅允许上传本次生成的 PNG/XLSX，禁止上传数仓、源文件或 `evidence.json`。
- 所有选中通道先查数、计算成功，再生成和发送；任何查询失败整批阻断，预览亦然。正文、图片、附件必须共用最终结果。
- 外部宿主负责定时；本模块每次调用都生成进度播报，不具备跨次告警去重、冷却、自动重试或自动改口径能力。

以上是 Agent 运行权限合同；操作系统与宿主实际授权由部署者配置，本文件不授予系统权限。
