# 项目交接状态

本文件面向维护者，记录历史完成度、风险和后续工程事项。它不是客户日常使用说明，也不替代 `AGENTS.md` 的运行时宪法；Data OXHor 的默认产品角色是已部署客户工作区中的日常数据分析智能体。

## 当前状态

项目主线已完成 Data Foundation、Business Pack、Company Bridge、Bridge 对齐向导、首次部署引导层、Casebook/内测反馈和双宿主交付验证。业务核心保持宿主无关；客户通过自然语言进入 onboarding、Bridge 对齐、受控分析、案例沉淀和文件交付。

PPT Master v4.7.0 保持为固定上游完整树，Quick 入口仍由项目代码编排；正式 Bridge 和 reviewed 证据继续作为当前产品基线。

## 当前合同

首次部署引导层 v1 已加入公开入口 `python3 -m interfaces.onboarding`（安装 wheel 后也可使用 `onboarding`）：

```text
doctor -> init -> import-data -> sync -> handoff -> 宿主 Agent 对齐 Bridge
```

它负责运行时/Pack 检查、客户 `Input/Work/Output` 初始化、基础 XLSX/XLSM 来源槽位复制、不可变 Snapshot 发布、当前状态检查和 Bridge 会话交接。所有输出为 `onboarding_result.v1` JSON；来源槽位默认不可覆盖，刷新使用新的 `snapshot_id`。`handoff` 可重复读取同一会话。

它不负责模型候选生成、自然语言确认、Bridge 问题回答或正式 Bridge finalize；这些仍由宿主原生 Agent 与 `bridge-alignment-wizard` 完成。

完整输入、输出和错误语义见 [首次部署引导层合同](./onboarding-contract.md)。

Codex 的自然语言入口见 [首次部署自然语言 Skill](../.agents/skills/first-deployment-onboarding/SKILL.md)。用户可以直接说“帮我首次部署”“导入这批数据”或“建立 Bridge”，由 Skill 调用确定性引导 CLI 并在需要时逐步询问。

- 运行使用显式 `run_id`；查询和恢复使用显式 `snapshot_id`。
- Data Foundation 只负责原始 landing、身份、质量和只读查询，不理解教育业务。
- Pack 保存行业通用知识；Bridge 保存企业表头、列位、枚举、归一规则和 Override。
- 历史扫描只能生成候选；正式 Bridge 只接受人工复核的 `confirmed_review`。
- 向导模型候选始终是 proposed；只有客户决定或显式 optional unresolved 能进入 reviewed，关键歧义必须阻断。
- 客户工作区使用固定 `Input/Work/Output` 并保存相对路径，可整体复制；追加资料持久化到 `Input/Reference`，源码 checkout 的 `customers/` 默认忽略。
- 源文件承担长期归档；向导工作区只保留当前 Snapshot，不维护 `snapshot_history`。`sync-data` 先构建并切换新 Snapshot，再删除旧 Run；失败或存在未完成会话时保留旧状态。仅记录已用 ID，防止删除后复用；已完成会话为只读。
- Data Foundation 的 SHA-256 只负责导入完整性；向导候选、问题、决定和参考资料身份不使用哈希。Quick 冻结分析的证据 SHA-256 是交付身份合同，缺失或变化必须阻断。
- Snapshot 只用于运行兼容性校验，不写入 Bridge；Bridge 不通过 `latest` 或修改时间选择状态。
- 真实源工作簿、DuckDB、Parquet 和运行目录不进入 Git。

## 唯一待办

S4 Quick 真实性能回归仍待补齐。恢复时使用主线 Bridge 的现金明细与工单输入，通过新版冻结分析和共同 Quick 入口完成双宿主回归；不引入教务数据或 fake adapter 绕过门禁。

不要增加 MCP、独立强化插件、完整 Artifact 平台或通用工作流编排；新增治理必须对应可复现失败或明确客户要求。

## 已知风险

- DeepSeek Harness 仍是 Developer Preview，升级可能破坏插件接口；
- 当前 landing 关系名由 `source_id + sheet_name` 确定，源 Sheet 改名后必须重新做 Bridge 兼容性校验；
- fake adapter 只用于候选合同测试；正式推理由 Codex 或 DeepSeek Harness 的原生 Agent 承担，不建设宿主 Adapter；
- PPT Master attribution guard、文件树数量和 pinned tree digest 已通过离线复核；后续升级或重新装配仍需重新执行同一组检查。
- S5 不能以自动上传、自动打包 `runs/`、跨客户检索、宿主 Session 复制、向量库或自动发布 Skill 作为捷径；反馈证据只在用户明确授权时导出。

## 技术依据

- [系统架构](./architecture.md)
- [接入指南](./integration-guide.md)
- [Company Bridge v1 合同](./company-bridge-contract.md)
- [Bridge 对齐向导 v1 合同](./bridge-alignment-wizard-contract.md)
- [Casebook、内测回收与引导路由合同](./casebook-pilot-contract.md)
