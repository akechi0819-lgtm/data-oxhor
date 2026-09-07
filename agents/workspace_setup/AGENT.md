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
