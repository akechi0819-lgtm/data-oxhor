# 工作区初始化 Agent

## 负责范围

为一个明确的客户工作区完成首次部署、导入或更新数据、发布新 Snapshot，并组织 Company Bridge 对齐。它只处理工作区准备，不输出未经确认的业务分析结论，也不负责固定看板发布。

## 运行入口

```bash
python3 -m interfaces.workspace_modeling doctor --profile full
python3 -m interfaces.workspace_modeling init --workspace customers/<company> --business-port <port>
python3 -m interfaces.workspace_modeling import-data --workspace customers/<company> --source-id <source> --file <file>
python3 -m interfaces.workspace_modeling sync --workspace customers/<company> --snapshot-id <snapshot_id>
python3 -m interfaces.workspace_modeling handoff --workspace customers/<company> --session-id <session_id>
```

随后使用 `python3 -m interfaces.bridge_alignment` 完成候选、确认和 `finalize`。精确参数与输出以 [接入指南](../../docs/integration-guide.md) 和 [首次部署合同](../../docs/onboarding-contract.md) 为准。

## 必须遵守

- 只操作一个明确工作区，所有 Snapshot 和查询身份使用显式 ID。
- 不覆盖已发布 Snapshot；更新数据必须发布新的 `snapshot_id`。
- 字段、枚举、日期与金额口径由用户确认后才进入正式 Bridge。
- 不直接连接客户 DuckDB，不上传源文件或整个运行目录。

## 固定看板数据更新职责

本 Agent 负责单一客户工作区的初始化、数据导入/同步和 Bridge 交接；不负责原生 BI 日更、发布、通知或调度。固定看板的当前部署入口与操作边界见[正式 BI 部署说明](../../dashboard_product/DEPLOYMENT.md)和[看板发布 Agent](../dashboard_publisher/AGENT.md)。

当前服务器 raw 链路接收固定三 Excel，由受限 worker 基于 root 只读历史基线建立双 Snapshot、运行 quality 与共享计算，生成39张业务表；达到 `prepared` 后才可由 root publisher 按 P4 流程验收并切换 release。详见[raw 链路合同](../../docs/server-raw-pipeline-contract.md)。Mac `p5.daily` 仍是手动入口，不代表默认生产调度。来源完整性证明门禁已合入本地 `main`，10月26日部署回执对应的服务器版本尚未包含它；具体状态按[部署说明](../../dashboard_product/DEPLOYMENT.md)及对应回执核实。

10月26日后续[清理回执](../../docs/server-cleanup-20261026.md)记载raw路径暂停、保留Mac更新；上述服务器raw分工描述已部署能力，不表示它当前启用。本Agent不恢复服务或日程。
