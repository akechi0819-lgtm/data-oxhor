# 项目交接状态

## 截止 2026-08-16 已完成

- DeepSeek Harness `0.1.0-rc.6` 已完成 Web、Provider、真实模型、Workspace 和受控 Shell 基础验证；业务核心保持宿主无关。
- Data Foundation v2 已实现 XLSX 全 Sheet 探查、通用 `landing.column_N`、不可变 DuckDB/Parquet Snapshot、质量查询、受控只读 SQL 和保存查询。
- 三份真实工作簿已完成 `inspect → ingest → describe → quality → query`；14 个 Sheet 无需 cleaning plan 全量 landing。
- Education Business Pack `education_training_operations_cn` v1.0.0 已完成，包含 28 个概念、20 个指标、26 个维度、3 条旅程、3 个漏斗和 7 个诊断 Playbook。
- Company Bridge 合同、历史候选扫描、人工复核门禁、CLI 和 Snapshot 兼容性校验已完成。
- 当前 reviewed v3 含 119 个 confirmed 候选；正式 Bridge 1.2.0 含 3 个源合同、10 个字段映射、105 条归一规则、1 个 Override、0 个 unresolved。
- Bridge 1.2.0 已通过真实 Data Foundation v2 Snapshot 兼容性校验；企业字段与列位不再硬编码在 Data Foundation。
- `main` 已合并宿主验证、Data v2、Pack v1 和 Bridge v1.2.0；47 项 Python 测试通过。

## 当前合同

- 运行使用显式 `run_id`；查询和恢复使用显式 `snapshot_id`。
- Data Foundation 只负责原始 landing、身份、质量和只读查询，不理解教育业务。
- Pack 保存行业通用知识；Bridge 保存企业表头、列位、枚举、归一规则和 Override。
- 历史扫描只能生成候选；正式 Bridge 只接受人工复核的 `confirmed_review`。
- Snapshot 只用于运行兼容性校验，不写入 Bridge；Bridge 不通过 `latest` 或修改时间选择状态。
- 真实源工作簿、DuckDB、Parquet 和运行目录不进入 Git。

## 尚未完成

- 首个 Customer Profile；
- Harness Session 重启后通过显式 Snapshot/Pack/Bridge 身份继续；
- 项目 Skill 的真实调用；
- 小型 Deliverable 的生成、打开性验收和会话展示；
- 输出模块和学习与质量工作区。

## 唯一下一步

实现首个 Customer Profile，显式选择 Data Foundation endpoint、Snapshot、Pack 1.0.0、Bridge 1.2.0、模型、Skills 和隔离工作区。随后在 Harness 中验证 Session 恢复和一个小型 Deliverable。

不要增加 MCP、独立强化插件、完整 Artifact 平台或通用工作流编排；新增治理必须对应可复现失败或明确客户要求。

## 已知风险

- DeepSeek Harness 仍是 Developer Preview，升级可能破坏插件接口；
- 当前 landing 关系名由 `source_id + sheet_name` 确定，源 Sheet 改名后必须重新做 Bridge 兼容性校验；
- 尚未确认可直接复用的官方 PPT/图表市场能力。

## 技术依据

- [系统架构](./architecture.md)
- [接入指南](./integration-guide.md)
- [Company Bridge v1 合同](./company-bridge-contract.md)
- [DeepSeek Harness 调研卡](../research/projects/deepseek-harness.md)
