# 项目交接状态

## 截止 2026-08-14 已完成

- 确定 DeepSeek Harness 为默认客户运行宿主，同时冻结宿主可替换原则；
- 全局安装并静态验证 DeepSeek Harness `0.1.0-rc.6`；
- 在 Harness 机器级设置中配置模型 Provider/API Key，未将凭据写入仓库；
- 验证 Harness 真实模型回合、项目 Workspace 和受控 Shell；模型成功执行 Data Foundation 顶层 `--help`，退出码 0，并发现全部 7 个子命令；
- 完成 Data Foundation 的 XLSX 探查、不可变 Snapshot、DuckDB/Parquet、质量问题、只读 SQL 和保存查询；
- Data Foundation 使用 `run_id`、显式 Snapshot 身份和最小 Artifact manifest；源 SHA-256 保留在 inspect/ingest 与 manifest 内部，不作为跨 Session 强制字段；
- 确定 CLI 是 Data Foundation 唯一公开入口，Codex、DeepSeek Harness 等具备受控 Shell 的宿主直接调用同一 CLI；
- 确定当前不建设 MCP 或独立 Harness Reinforcement 插件，确定性约束由对应业务模块直接实现；
- 删除已废弃的 Codex→Hermes handoff schema、validator 和 5 项相关测试；
- 完成 Education Business Pack `education_training_operations_cn` v1.0.0，覆盖行业概念、指标、维度、三段客户旅程、漏斗和诊断 Playbook；
- 完成 Pack `validate` / `describe` CLI 与稳定 ID、交叉引用校验；
- 30 项现行 Python 测试通过；
- 明确 Pack 与 Bridge 从第一家企业起物理分离；
- 明确 Customer Profile 只是薄装配；
- 明确长期业务学习进入独立学习与质量工作区，而不是宿主 Session；
- 项目 Git 仓库已有基线提交 `a5df0b6`；当前工作树包含未提交施工改动。

## 尚未完成

- Harness 的完整 Data Foundation 数据链路、Session 恢复、项目 Skill 和 Deliverables 验收；
- 当前企业 Company Bridge；
- 首个 Customer Profile；
- 输出插件和确定性 Renderer；
- 学习与质量工作区。

## 下一步

先确认并实现当前企业 Company Bridge 的最小切片：字段、枚举、Selection、Override 和 unresolved。Pack 不接收企业字段、SQL、阈值或单次分析结论。

Data Foundation 宿主侧仍需补充验收：

1. 用一次性小型 fixture 在 DeepSeek Harness 中调用 `inspect/ingest/describe/quality/query`，确认 JSON、退出码和产物路径可直接消费；
2. 保持现有只读拒绝、Snapshot 身份和错误测试通过，不复制 Python 核心；
3. 在同一 Session 连续追问后重启恢复，并用显式 `run_id`/`snapshot_id` 继续；
4. 完成小型 Deliverable 验收。

不要开发 MCP、独立强化插件、PPT 或完整 Run/Artifact 平台。当前数据调用链只依赖 CLI、显式 `run_id` 和 `snapshot_id`；源 SHA-256 继续作为源绑定和 manifest 的内部完整性信息。

## 已知阻塞与风险

- 当前没有已知的外部阻塞；完整数据链路、Session 恢复和 Deliverables 仍需实际验证；
- DeepSeek Harness 是 Developer Preview，插件接口可能破坏兼容；
- 尚未确认可直接复用的官方 PPT/图表市场能力；
- 当前 `data_foundation/` 仍硬编码特定源表映射和 `semantic.registration_cash` 视图；这是待 Bridge 建设时分离的边界债务；
- 当前 Pack 施工仍未提交；交接时应以工作树和测试结果为准，不把基线提交误认为包含本次改动。

## 技术依据

- [DeepSeek Harness 调研卡](../research/projects/deepseek-harness.md)
