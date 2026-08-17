# 项目交接状态

## 截止 2026-08-16 已完成

- DeepSeek Harness `0.1.0-rc.6` 已完成 Web、Provider、真实模型、Workspace 和受控 Shell 基础验证；业务核心保持宿主无关。
- Data Foundation v2 已实现 XLSX 全 Sheet 探查、通用 `landing.column_N`、不可变 DuckDB/Parquet Snapshot、质量查询、受控只读 SQL 和保存查询。
- 三份真实工作簿已完成 `inspect → ingest → describe → quality → query`；14 个 Sheet 无需 cleaning plan 全量 landing。
- Education Business Pack `education_training_operations_cn` v1.0.0 已完成，包含 28 个概念、20 个指标、26 个维度、3 条旅程、3 个漏斗和 7 个诊断 Playbook。
- Company Bridge 合同、历史候选扫描、人工复核门禁、CLI 和 Snapshot 兼容性校验已完成。
- 当前 reviewed v3 含 119 个 confirmed 候选；正式 Bridge 1.2.0 含 3 个源合同、10 个字段映射、105 条归一规则、1 个 Override、0 个 unresolved。
- Bridge 1.2.0 已通过真实 Data Foundation v2 Snapshot 兼容性校验；企业字段与列位不再硬编码在 Data Foundation。
- Bridge 对齐向导 S3.5 已完成：显式会话、Snapshot 画像、候选合同、少量关键确认、追加目录只读扫描、确认不可覆盖、自动 confirmed_review/build/validate。
- 陌生四表 + 七月到八月当前文件替换 + 补充数据字典 fixture 已覆盖工作区内数据管理、同公司语义复用、新公司隔离、关键问题阻断和最终 Bridge；工作区只保留当前 Snapshot，成功刷新清理旧 Run，失败或未完成会话不切换；61 项 Python 测试通过。
- 2026-08-16 的既有 S3.5 记录曾用三张真实教务表完成跨端口结构识别和查询验证；S4 使用独立的 `s4_teaching_validation` 工作区重新对齐，当前教务 Bridge 仍待宿主 proposed 候选和人工确认，不得用既有 Bridge 代替。
- 真实运行暴露并修复空候选会话可 finalize 的门禁缺陷；现在必须先 propose。当前 Harness headless 对单次长结构化任务异常只返回内部 `SESSION_ID`，短步骤原生 Agent 调用可用；这是宿主已知风险，不通过建设正式 Adapter 或第二层 Agent 解决，也不阻断 S3.5 完成。
- 重叠处理边界已确定：不新增 Bridge 重叠模块。项目 Skill `diagnose-source-overlap` 已通过 Harness 真实调用，模型用 Data Foundation `describe/query` 自主检查日期范围、候选业务键、重复与冲突，确认后以保存查询固化 SQL；日期区间交集本身不能触发删除。
- S4 已按官方 Skill Installer 装配 `hugohe3/ppt-master` v4.7.0（提交 `e8323bfaee249cffe1301ec40fca5875eb544d46`），保留 MIT、模板、脚本、工作流和 notices；provenance、精确依赖锁和离线完整性测试已加入项目。PPT 交付合同保持通用，不固定教务页序；首轮禁用自动更新、外部研究、生图、TTS、旁白和本地 Web 辅助界面。

## 当前合同

- 运行使用显式 `run_id`；查询和恢复使用显式 `snapshot_id`。
- Data Foundation 只负责原始 landing、身份、质量和只读查询，不理解教育业务。
- Pack 保存行业通用知识；Bridge 保存企业表头、列位、枚举、归一规则和 Override。
- 历史扫描只能生成候选；正式 Bridge 只接受人工复核的 `confirmed_review`。
- 向导模型候选始终是 proposed；只有客户决定或显式 optional unresolved 能进入 reviewed，关键歧义必须阻断。
- 客户工作区使用固定 `Input/Work/Output` 并保存相对路径，可整体复制；追加资料持久化到 `Input/Reference`，源码 checkout 的 `customers/` 默认忽略。
- 源文件承担长期归档；向导工作区只保留当前 Snapshot，不维护 `snapshot_history`。`sync-data` 先构建并切换新 Snapshot，再删除旧 Run；失败或存在未完成会话时保留旧状态。仅记录已用 ID，防止删除后复用；已完成会话为只读。
- Data Foundation 的 SHA-256 只负责导入完整性；向导候选、问题、决定和参考资料身份不使用哈希。
- Snapshot 只用于运行兼容性校验，不写入 Bridge；Bridge 不通过 `latest` 或修改时间选择状态。
- 真实源工作簿、DuckDB、Parquet 和运行目录不进入 Git。

## 当前未完成

- 先由原生宿主完成 `session_s4_align_01` 的 proposed 候选并由用户确认关键歧义，生成当前 Snapshot 兼容的正式 Bridge；再完成 Codex 与 DeepSeek Harness 双宿主的真实 PPTX/查询交付验收。当前不得以既有 Bridge 或 fake adapter 绕过门禁。

## 唯一下一步

继续 S4 双宿主验收：在 `customers/s4_teaching_validation/` 建立当前 Snapshot 和确认后的教务 Bridge，由 Codex 与 DeepSeek Harness 原生 Agent 分别发现并调用 `ppt-master`，完成同题查询/PPT 与随机临场 PPT，随后做 PPTX 打开、逐页渲染、内容非空、数字回查和候选空档表述检查。不要开发 Customer Profile、清理按钮、Renderer、HTML 平台或 Deliverables 系统。

不要增加 MCP、独立强化插件、完整 Artifact 平台或通用工作流编排；新增治理必须对应可复现失败或明确客户要求。

## 已知风险

- DeepSeek Harness 仍是 Developer Preview，升级可能破坏插件接口；
- 当前 landing 关系名由 `source_id + sheet_name` 确定，源 Sheet 改名后必须重新做 Bridge 兼容性校验；
- fake adapter 只用于候选合同测试；正式推理由 Codex 或 DeepSeek Harness 的原生 Agent 承担，不建设宿主 Adapter；
- PPT Master 已固定来源并通过离线完整性检查；Codex/Harness 的 Skill 发现、生成和交付兼容性仍待双宿主真实验收。

## 技术依据

- [系统架构](./architecture.md)
- [接入指南](./integration-guide.md)
- [Company Bridge v1 合同](./company-bridge-contract.md)
- [Bridge 对齐向导 v1 合同](./bridge-alignment-wizard-contract.md)
- [DeepSeek Harness 调研卡](../research/projects/deepseek-harness.md)
