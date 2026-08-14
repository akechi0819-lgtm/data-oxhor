# 项目交接状态

## 截止 2026-08-14 已完成

- 确定 DeepSeek Harness 为默认客户运行宿主，同时冻结宿主可替换原则；
- 全局安装并静态验证 DeepSeek Harness `0.1.0-rc.6`；
- 完成 Data Foundation 的 XLSX 探查、不可变 Snapshot、DuckDB/Parquet、质量问题、只读 SQL 和保存查询；
- Data Foundation 使用 `run_id`、显式 Snapshot 身份和最小 Artifact manifest；源 SHA-256 保留在 inspect/ingest 与 manifest 内部，不作为跨 Session 强制字段；
- 确定 CLI 是 Data Foundation 唯一公开入口，Codex、DeepSeek Harness 等具备受控 Shell 的宿主直接调用同一 CLI；
- 确定当前不建设 MCP 或独立 Harness Reinforcement 插件，确定性约束由对应业务模块直接实现；
- 删除已废弃的 Codex→Hermes handoff schema、validator 和 5 项相关测试；
- 21 项现行 Python 测试通过；
- 明确 Pack 与 Bridge 从第一家企业起物理分离；
- 明确 Customer Profile 只是薄装配；
- 明确长期业务学习进入独立学习与质量工作区，而不是宿主 Session；
- 在项目根初始化 Git 仓库，默认分支为 `main`，尚无首个提交。

## 尚未完成

- Codex 对现有 CLI 完整命令链和错误处理的宿主侧验证；
- Harness 的真实模型回合、Session 恢复、项目 Skill、CLI 调用和 Deliverables 验收；
- Education Business Pack；
- 当前企业 Company Bridge；
- 首个 Customer Profile；
- 输出插件和确定性 Renderer；
- 学习与质量工作区。

## 唯一下一步

直接用现有 Data Foundation CLI 完成宿主接入验证：

1. 在 Codex 工作区调用 `inspect/ingest/describe/quality/query/promote-query/run-saved-query`，确认现有 JSON、退出码和产物路径可直接消费；
2. 保持现有只读拒绝、Snapshot 身份和错误测试通过，不复制 Python 核心；
3. 为 DeepSeek Harness 配置项目 Workspace、受控 Shell 和最小 CLI 调用说明；
4. 用户配置模型 Provider 后完成真实 Session、重启恢复和小型 Deliverable 验收。

不要先开发 MCP、独立强化插件、Pack、Bridge、PPT 或完整 Run/Artifact 平台。当前调用链只依赖 CLI、显式 `run_id` 和 `snapshot_id`；源 SHA-256 继续作为源绑定和 manifest 的内部完整性信息。这个切片验证“同一 CLI 可由多个宿主直接消费”和“DeepSeek Harness 能作为默认运行宿主”两个关键假设。

## 已知阻塞与风险

- 真实模型验收需要用户在本机 Harness 中配置 Provider/API Key；
- DeepSeek Harness 是 Developer Preview，插件接口可能破坏兼容；
- 尚未确认可直接复用的官方 PPT/图表市场能力；
- 当前 `data_foundation/` 仍硬编码特定源表映射和 `semantic.registration_cash` 视图；这是待 Pack/Bridge 建设时分离的边界债务；
- Git 仓库尚无首个提交，因此当前仍没有可引用的项目 commit hash。

## 技术依据

- [DeepSeek Harness 调研卡](../research/projects/deepseek-harness.md)
