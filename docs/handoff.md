# 项目交接状态

## 截止 2026-08-19 已完成

- DeepSeek Harness `0.1.0-rc.6` 已完成 Web、Provider、真实模型、Workspace 和受控 Shell 基础验证；业务核心保持宿主无关。
- Data Foundation v2 已实现 XLSX 全 Sheet 探查、通用 `landing.column_N`、不可变 DuckDB/Parquet Snapshot、质量查询、受控只读 SQL 和保存查询。
- 三份真实工作簿已完成 `inspect → ingest → describe → quality → query`；14 个 Sheet 无需 cleaning plan 全量 landing。
- Education Business Pack `education_training_operations_cn` v1.0.0 已完成，包含 28 个概念、20 个指标、26 个维度、3 条旅程、3 个漏斗和 7 个诊断 Playbook。
- Company Bridge 合同、历史候选扫描、人工复核门禁、CLI 和 Snapshot 兼容性校验已完成。
- 当前 reviewed v3 含 119 个 confirmed 候选；正式 Bridge 1.2.0 含 3 个源合同、10 个字段映射、105 条归一规则、1 个 Override、0 个 unresolved。
- Bridge 1.2.0 已通过真实 Data Foundation v2 Snapshot 兼容性校验；企业字段与列位不再硬编码在 Data Foundation。
- Bridge 对齐向导 S3.5 已完成：显式会话、Snapshot 画像、候选合同、少量关键确认、追加目录只读扫描、确认不可覆盖、自动 confirmed_review/build/validate。
- 陌生四表 + 七月到八月当前文件替换 + 补充数据字典 fixture 已覆盖工作区内数据管理、同公司语义复用、新公司隔离、关键问题阻断和最终 Bridge；工作区只保留当前 Snapshot，成功刷新清理旧 Run，失败或未完成会话不切换。
- 2026-08-16 的 S3.5 记录曾用三张真实教务表完成跨端口结构识别和查询验证；这项历史验证已经结束，当前主线不再增加教务数据或重建教务 Bridge。
- 真实运行暴露并修复空候选会话可 finalize 的门禁缺陷；现在必须先 propose。当前 Harness headless 对单次长结构化任务异常只返回内部 `SESSION_ID`，短步骤原生 Agent 调用可用；这是宿主已知风险，不通过建设正式 Adapter 或第二层 Agent 解决，也不阻断 S3.5 完成。
- 重叠处理边界已确定：不新增 Bridge 重叠模块。项目 Skill `diagnose-source-overlap` 已通过 Harness 真实调用，模型用 Data Foundation `describe/query` 自主检查日期范围、候选业务键、重复与冲突，确认后以保存查询固化 SQL；日期区间交集本身不能触发删除。
- S4 已按官方 Skill Installer 装配 `hugohe3/ppt-master` v4.7.0（提交 `e8323bfaee249cffe1301ec40fca5875eb544d46`），保留 MIT、模板、脚本、工作流和 notices；provenance、精确依赖锁和离线完整性测试已加入项目。PPT 交付合同保持通用，不固定教务页序；首轮禁用自动更新、外部研究、生图、TTS、旁白和本地 Web 辅助界面。
- S4 短 PPT 性能链已收敛：`tools/s4_ppt_quick.py` 与 `tools/run_s4_local.sh quick-ppt` 统一 Codex/DeepSeek Harness 的冻结身份校验、Quick 初始化、最终 SVG checker 和 Quick export；不创建项目侧 Spec/Confirm/Renderer。
- Data Foundation 的受控查询结果现记录实际引用的 landing 关系与 `referenced_source_ids`。Quick 冻结清单以这些来源凭据、同一 Snapshot 和证据哈希限制交付，旧冻结格式一律阻断。
- Codex 与 DeepSeek Harness 均已完成主线 Bridge 的分析和 PPTX 生成；Codex 产物保存在 `runs/codex_mainbridge_acceptance_20260817/ppt/exports/`，Harness 的最终 PPTX 位于 `runs/deepseek_main_bridge_test_20260817/new_revenue_gap_20260818/projects/tanggu_cash_gap_ppt169_ppt169_20260818/exports/`。这两项宿主能力不再是施工阻塞。
- 2026-08-18 已决定在 S4 后增加 S5「Casebook、内测回收与引导路由」：`runs/` 只作为客户本地原始证据，已确认案例复制最小可回查证据；内测用户主动导出默认脱敏反馈包，开发侧回收后再转为回归测试、Bridge、Skill/模板或 Pack 改进。
- 2026-08-19 发布前功能对齐复核通过：项目 `.venv` 全量测试 102/102 通过，S4 PPT 预检通过，Pack 与 Company Bridge 校验通过，所有公开 CLI 帮助可调用，首次部署 `init → status` 烟测通过；PPT Master attribution guard 与 pinned tree digest 已复核一致。

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

## 当前状态

- S4 Quick 真实主线回归暂时挂起：用主线 Bridge 的现金明细与工单数据重新执行受控查询，生成带来源凭据的冻结分析；再由两个已验证宿主以共同 Quick 入口完成性能回归。不得引入教务数据、既有教务 Bridge 或 fake adapter 绕过门禁。
- S5 已完成：S5.1 Casebook 候选/确认/检索/证据校验，S5.2 版本化内测测试包、本地评价与用户主动反馈包导出/校验，S5.3 工作区引导路由与重复问题候选沉淀提示。集成 CLI 为 `python3 -m interfaces.casebook_pilot`；合同、目录/schema、错误语义和测试矩阵见 [S5 合同](./casebook-pilot-contract.md#7-s51--s53-施工合同2026-08-18已实现)。

## 后续施工项

S5 已完成：合成/脱敏 fixture 覆盖案例、反馈、授权、重打包 ZIP 与人工评价门禁；本地临时客户工作区完成了现有对齐向导、受控查询 artifact、Casebook、评价、默认反馈导出/复核的端到端验收。独立审查的有效发现均已修复并回归。完整边界见 [S5 合同](./casebook-pilot-contract.md)。

S4 Quick 性能回归不删除，保持挂起；恢复时继续执行新版冻结分析、双宿主 Quick、`validation/quick_run.json`、PPTX 打开与数字回查。不要把已有 Default PPTX 当成该验收结果。

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
- [DeepSeek Harness 调研卡](../research/projects/deepseek-harness.md)
