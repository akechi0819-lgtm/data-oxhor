# Data OXHor

面向教育机构的对话式业务分析系统。它把脏 Excel 转成可追溯的数据快照，再用教育行业知识和企业语义映射支撑持续追问、自由下钻、图表和交付物生成。

默认客户运行宿主是 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)，Codex 是直接运行与验证宿主。两者都使用自身原生的 Agent、模型、Session、Skills、记忆清理、工具和文件交付系统；本项目不再包装一层 Agent，而是通过 CLI、Pack、Bridge、对齐向导和项目级 Skills 补充教育业务能力。Data Foundation、Business Pack 和 Company Bridge 均通过稳定 Python CLI 暴露，不需要额外 MCP 服务。

如果你是第一次使用，请先阅读 [Agent 使用说明](./docs/user-guide.md)；本 README 主要用于了解项目结构和开发边界。

## 架构一览

```text
      DeepSeek Harness（默认）/ Codex / 其他 Agent Host
        原生 Agent / 对话 / Session / 模型 / Skills / 受控 Shell
                               │ CLI / files / JSON
                 客户工作区 + 项目 Skills
                               │
     ┌──────────────┬──────────┴─────────┐
     │              │                    │
Data Foundation  业务语义组          宿主原生交付
脏数据/Snapshot  Pack + Bridge       项目 Skills
     │              │                    │
     └──────────────┴──────────┬─────────┘
                               │
             本地案例与内测反馈的按需沉淀
     Casebook / Feedback / Skill / Template / Pack / Bridge
```

核心边界：

- Data Foundation 不理解教育业务，只负责原始 landing、身份、质量和受控只读查询；
- Business Pack 不伪装成某家企业事实；
- Company Bridge 不与 Pack 合并，即使第一家企业存在少量内容重复；
- Skill 指导模型，确定性工具负责数据权限、身份、计算和文件生成；
- CLI 是 Data Foundation 的唯一公开入口；宿主可替换性不依赖 MCP；
- 只读、Snapshot 不覆盖、unresolved 阻断和文件验收由对应模块的确定性代码承担，不建设独立强化层；
- 宿主 Session 是短期对话记忆；客户工作区的 Casebook 保存已确认、可回查的业务案例；
- DeepSeek 专属交互 UI 可以增强体验，但不能成为核心分析能力的唯一入口。

## 客户使用流程

客户只需要和宿主 Agent 对话，项目 CLI 在后台提供确定性门禁。完整主线可以压缩为六步：

1. **首次部署**：`first-deployment-onboarding` Skill 先询问业务端口，再引导检查运行时、创建工作区、放入流水表并发布新的 Snapshot。依赖由安装脚本或发布包 extras 统一安装，不要求用户逐项寻找；Snapshot 发布后自动交接到 Bridge 对齐。
2. **建立 Bridge**：宿主 Agent 启动 Bridge 对齐向导，读取当前 Snapshot 和 Business Pack，提出字段映射候选；用户通过多轮对话确认企业字段、枚举和业务口径。未确认的关键映射不能进入分析。
3. **日常分析**：`business-analysis-routing` Skill 先检查工作区状态，可选检索同公司同角色的 confirmed Casebook 案例，再要求宿主 Agent 使用当前 Snapshot、Pack 和 Bridge 编排问题。SQL 必须通过 Data Foundation 的受控只读入口执行，不能直接扫 DuckDB。
4. **交付与验收**：宿主 Agent 根据当前查询结果回答问题，按需调用现有表格、图表或 PPT 路线。交付物必须能回查本次查询；客户可以继续追问或要求修正口径。
5. **案例沉淀**：客户明确验收并希望复用时，Agent 用 `case-create` 或 `case-capture` 保存最小证据包，先进入 `candidate`；哈希校验通过后仍需用户明确 `case-confirm`，才能成为后续检索线索。
6. **内测反馈与方法升级**：用户可执行版本化评价并主动导出脱敏反馈。重复问题达到现有人工评价门槛时，`repeat-candidates` 只返回 Skill/模板草案；是否沉淀为项目 Skill、行业 Pack、企业 Bridge 或继续保留在 Casebook，必须人工审核决定。

职责边界保持简单：宿主 Agent 负责自然语言理解、追问、候选 SQL 和交付编排；项目代码负责 Snapshot、Bridge、路径、查询、哈希和文件状态门禁；用户负责上传数据、确认业务口径、验收结果和授权反馈。Casebook 是方法线索，不是当前事实；Skill 是调用说明，不是第二个 Agent。

## 已实现

- XLSX 全 Sheet 探查和 OOXML 流式读取；
- 所有 Sheet 无需 cleaning plan 直接进入通用 `landing.column_N`，并发布不可变 DuckDB/Parquet Snapshot；
- Schema 描述、数据质量问题、受控只读 SQL、保存查询；
- `run_id`、Snapshot 身份、源 SHA-256 绑定和最小 Artifact manifest；受控查询结果会记录实际引用的 landing 关系和 `referenced_source_ids`，供冻结分析交付校验；
- Education Business Pack v1：行业概念、指标、维度、客户旅程、漏斗和诊断 Playbook；
- Pack 的 `validate` / `describe` CLI 与确定性交叉引用校验；
- Company Bridge 1.2.0：当前源合同、企业字段映射、归一规则和 Override；
- Bridge 对齐向导 v1：提供自包含 `Input/Work/Output` 客户工作区、稳定数据源槽位和月度替换同步；工作区只保留当前 Snapshot，刷新成功后清理旧 Snapshot，宿主原生模型提出候选并收集关键确认，确定性服务自动生成 confirmed_review、build 和 Snapshot validate；
- 首次部署引导层 v1：`onboarding doctor/init/import-data/sync/status/handoff` 统一检查运行时、初始化客户工作区、复制基础工作簿、发布 Snapshot，并向宿主 Agent 交接 Bridge 对齐会话；不自动替用户确认或 finalize Bridge；
- Codex 自然语言引导 Skill：`.agents/skills/first-deployment-onboarding`，用户可直接说“帮我首次部署/导入数据/建立 Bridge”，由 Codex 调用引导层并逐步询问缺失信息；
- 项目 Skill `diagnose-source-overlap`：提示模型主动检查全量刷新、日期范围、候选业务键、重复率和冲突；客户确认后用现有保存查询固化去重，不增加专用重叠平台；
- 项目 Skill `ppt-master` v4.7.0 已按固定上游提交装配到 `.agents/skills/ppt-master`，保留 MIT 许可证、模板、脚本、工作流和 notices；旁边的 `ppt-master.upstream.json` 记录来源与完整树摘要，并有离线完整性回归测试；
- 短数据 PPT 通过 `tools/run_s4_local.sh quick-ppt prepare|finalize` 走共同 Quick 路线：冻结分析身份校验、官方最终 checker 与 Quick exporter；不建设第二套 Renderer、确认或 Spec 流程；
- DeepSeek Harness 可作为默认宿主运行；宿主健康检查、模型回合和受控 Shell 能力不属于本项目 Python 核心。

主线 Bridge 1.2.0 对应现金明细与工单数据；项目不建设正式宿主模型 Adapter、Customer Profile、项目侧 Session 管理或独立输出平台。MCP 不在当前开发计划内。

Data Foundation 不再保存企业 Sheet 白名单、业务列名或 `semantic.registration_cash`。企业表头与 `column_N` 的对应关系、枚举和清洗口径只进入 Company Bridge。

## 本地检查

```bash
python3 -m interfaces.data_foundation --help
python3 -m interfaces.business_pack validate
python3 -m interfaces.business_pack describe
python3 -m interfaces.company_bridge validate \
  --bridge artifacts/company_bridge/bridges/company_bridge.v1_2_0.json \
  --pack business_pack/packs/education_training_operations_cn/pack.json
python3 -m interfaces.bridge_alignment_wizard --help
python3 -m interfaces.onboarding --help
tools/run_tests.sh -v
/Users/akechi/.local/bin/dsh --version
```

## 安装运行时

发布包提供分层 extras，不要求用户逐个寻找依赖：

```bash
python3 -m pip install "data-oxhor[full]"
```

`full` 覆盖当前项目的核心分析、Bridge/Casebook 和 PPT Master 运行时。只做数据分析时可安装基础包；只需要 Quick PPT 时使用 `data-oxhor[ppt]`。从源码运行全量测试时，使用 `tools/install_runtime.sh test`，脚本会组合安装 `test + ppt`，因此包含 `pathops` 和 `uharfbuzz`；测试命令使用 `tools/run_tests.sh`。DeepSeek Harness、Office/字体和宿主 API Key 不属于 Python 包依赖，仍由宿主或操作系统提供。

`data-foundation` 的完整命令和输入合同见 [接入指南](./docs/integration-guide.md)，Harness 启动与排障见 [运维手册](./docs/operator-runbook.md)。

首次部署使用宿主无关的引导入口：

```bash
python3 -m interfaces.onboarding doctor --profile full
python3 -m interfaces.onboarding init --workspace customers/company_customer --business-port operations
python3 -m interfaces.onboarding import-data --workspace customers/company_customer --source-id cash --file /path/to/cash.xlsx
python3 -m interfaces.onboarding sync --workspace customers/company_customer --snapshot-id snapshot_company_2026_08
python3 -m interfaces.onboarding handoff --workspace customers/company_customer --session-id session_onboarding
```

`handoff` 的 JSON 是宿主 Agent 的交接合同；宿主仍负责提出候选、向用户提问，并调用 Bridge 对齐向导的 `answer` / `finalize`。

## 当前状态

S5「Casebook、内测回收与引导路由」已完成：客户工作区支持案例候选/确认/检索/证据校验、版本化内测评价、默认脱敏反馈 ZIP、用户授权证据和本地引导。入口为 `python3 -m interfaces.casebook_pilot --help`，完整边界见 [S5 合同](./docs/casebook-pilot-contract.md)。

S4 Quick 的真实性能回归仍待补齐；恢复时继续使用主线 Bridge 的现金明细与工单输入。

## 文档导航

- [Agent 使用说明](./docs/user-guide.md)
- [权威架构](./docs/architecture.md)
- [接入指南](./docs/integration-guide.md)
- [Company Bridge v1 合同](./docs/company-bridge-contract.md)
- [Bridge 对齐向导合同](./docs/bridge-alignment-wizard-contract.md)
- [首次部署引导层合同](./docs/onboarding-contract.md)
- [Codex 首次部署自然语言 Skill](./.agents/skills/first-deployment-onboarding/SKILL.md)
- [运维手册](./docs/operator-runbook.md)
- [S4 Quick PPT 宿主提示词](./docs/s4-ppt-quick-prompt.md)
- [S5 Casebook、内测回收与引导路由合同](./docs/casebook-pilot-contract.md)
- [交接状态](./docs/handoff.md)
- [第三方声明](./THIRD_PARTY_NOTICES.md)
