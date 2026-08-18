# AGENTS.md

本文件是项目内所有 Agent 的唯一规则与项目事实源。不得为 Claude、Codex 或其他宿主维护第二套根目录规则文件；宿主差异只记录在对应接入文档或配置中。

## 当前阶段

项目已完成宿主基础验证、Data Foundation v2、Education Business Pack v1、首个 Company Bridge v1.2.0、Bridge 对齐向导 S3.5（含 DeepSeek Harness 真实教务跨端口验收）以及 Codex/DeepSeek Harness 主线分析和 PPTX 双宿主交付验证。当前进入 S4 Quick 性能回归与真实使用。DeepSeek Harness 是默认客户运行宿主，Codex 是直接运行与验证宿主；二者都使用自身原生 Agent、模型、Session、Skills、记忆清理、工具和文件交付能力，本项目只补充宿主无关的业务资产与项目级操作 Skills。不得把本地验证环境描述成正式客户系统，也不得执行正式外部业务动作。

## 固定架构边界

1. Codex、DeepSeek Harness 等 Agent Host 负责对话、Session、模型、Skills、工具选择和调用；本项目不包装宿主，不建设第二层 Agent、通用 Agent Loop 或模型调度系统。
2. Data Foundation、Education Business Pack、Company Bridge、Bridge 对齐向导和项目 Skills 是对宿主的业务补充，不写入任何宿主的上游源码或安装目录。
3. Data Foundation 保持 Python 核心，CLI 是唯一公开入口。Codex、DeepSeek Harness 和其他具备受控 Shell 的宿主直接调用同一 CLI；当前不建设 MCP，也不得为迁移宿主而重写成熟逻辑。
4. Business Pack 与 Company Bridge 从第一家企业起物理分离。Pack 保存行业标准知识；Bridge 保存企业术语、字段、枚举、选择和 Override。
5. 一套正常客户工作区默认服务一家公司和一个主要角色；公司或角色变化时使用宿主原生的新会话/记忆清理并重新初始化工作区。不建设 Customer Profile、公司路由器、角色路由器或项目清理按钮。
6. Skills 只承载分析方法和操作说明；只读查询、数据身份、语义引用检查和文件验收必须由确定性代码完成。
7. 宿主 Session 承担对话上下文和记忆清理；当前不建设项目侧 Session 管理或预设的学习与质量平台。重复出现且值得长期复用的业务方法，按真实需求沉淀为项目 Skill、模板、Pack 或 Bridge。
8. 新宿主优先通过受控 Shell 消费同一套 Python CLI、Pack、Bridge、Skills 和输出器；只有出现不支持 Shell 的真实消费者时才评估薄适配器，不提前建设协议层。
9. 只读、不可覆盖、unresolved 阻断和文件验收由各自业务模块的确定性代码负责；没有可复现失败时不建设独立强化插件、统一治理层或跨模块身份平台。
10. Bridge 对齐向导只编排显式 Snapshot、Pack、可选同公司 Bridge、宿主原生模型提出的候选和人工确认；模型只能生成 proposed，确定性服务负责 confirmed_review、build 和 Snapshot validate。代码中的可注入 adapter 是程序化测试缝，不是正式宿主架构或后续施工目标。

## 当前已实现事实

- Python `>=3.12`，运行时依赖 DuckDB `1.5.5`；
- `data_foundation/` 已实现 XLSX 全 Sheet 探查、OOXML 流式读取、通用 `landing.column_N`、不可变 Snapshot、DuckDB/Parquet 入仓、质量问题查询和受控只读 SQL；Data Foundation 不包含企业 Sheet 白名单、业务表头或语义视图；
- `interfaces/data_foundation.py` 已提供 `inspect`、`ingest`、`describe`、`quality`、`query`、`run-saved-query`、`promote-query`；
- Data Foundation 已要求关键运行入口携带 `run_id`，查询通过显式 `snapshot_id` 定位仓库，并为 Snapshot 与大结果写入最小 Artifact manifest；这不是完整 Run/Artifact 平台；
- `business_pack/` 已提供 `education_training_operations_cn` v1.0.0，包含行业概念、指标、维度、三段客户旅程、漏斗和诊断 Playbook；`interfaces/business_pack.py` 提供 `validate`、`describe`；
- DeepSeek Harness `@deepseek-ai/dsh@0.1.0-rc.6` 已安装到本机全局环境，Web 健康检查通过；模型 Provider/API Key 已配置，真实模型回合可用，并已在项目 Workspace 通过 Shell 成功执行 Data Foundation 顶层 `--help`（退出码 0、发现 7 个子命令）；
- `company_bridge/` 已提供候选扫描、人工复核门禁、正式构建和 Snapshot 兼容性校验；当前 reviewed v3 生成正式 Bridge 1.2.0，映射 3 个真实 landing 源合同；
- 真实三表已通过 Data Foundation v2 全量 landing，Bridge 1.2.0 已对同一 Snapshot 兼容性校验通过；
- `bridge_alignment/` 与 `interfaces/bridge_alignment_wizard.py` 已提供 `start`、`propose`、`answer`、`add-evidence`、`finalize`，支持同公司口径复用、新公司隔离、追加只读证据、关键歧义阻断和自动 build/validate；核心不包含宿主 SDK、Agent Loop 或模型调度；
- Bridge 对齐工作区只保留当前 Snapshot：`sync-data` 先发布并切换新 Snapshot，再删除旧 Run；源文件承担历史归档，失败或存在未完成会话时不切换。仅保留已使用 `snapshot_id` 的标识符，禁止删除后复用身份；
- `.agents/skills/diagnose-source-overlap` 已通过 DeepSeek Harness 项目 Skill 真实调用；模型使用现有 Data Foundation `describe/query` 自主诊断全量刷新、日期重叠、候选业务键和冲突，确认后以 `promote-query/run-saved-query` 固化只读去重 SQL；
- DeepSeek Harness 曾用三张真实教务表完成陌生结构识别、字段角色判断、教务 Bridge 生成与验证、教师课量查询；这是 S3.5 历史跨端口验证，不再向当前主线增加教务数据或把教务 Bridge 用于 S4 交付；
- 受控查询结果依据实际 SQL 引用的 `landing.*` 关系写入 `referenced_relations` 与 `referenced_source_ids`。Quick 冻结分析必须使用 `s4_ppt_frozen_analysis.v1`，以同一 Snapshot、证据 SHA-256、`key_queries` 和这些来源凭据锁定可用证据；
- `ppt-master` v4.7.0 已按固定上游提交装配到 `.agents/skills/ppt-master`，保留 MIT 许可证、来源元数据与离线完整性测试；项目级 `tools/s4_ppt_quick.py` 只编排冻结身份、Quick 初始化、最终检查和导出，不复制上游 Renderer；Codex 与 DeepSeek Harness 的短数据 PPT 共用该入口；
- Codex 与 DeepSeek Harness 均已用主线 Bridge 跑通分析和可打开的 PPTX 生成；Quick 的后续工作是以新版冻结身份协议做性能回归，不把这项既有双宿主能力再写成阻塞；
- Customer Profile、项目侧 Session 管理、独立输出模块和学习治理平台均不再列为预设施工项；MCP 不在当前计划内。

## 当前最小红线

- 原始输入只读，已发布 Snapshot 不得原地覆盖；
- Agent 只能通过受控入口执行只读 SQL；
- 未确认 Bridge 映射不得作为正式事实；
- 运行使用显式 `run_id`，查询和恢复使用显式 `snapshot_id`；源 SHA-256 只用于 inspect/ingest 的源绑定和 manifest，不要求在每次查询、Session 或交付物中传播；例外是 Quick 冻结分析的证据文件 SHA-256，它是该交付的身份合同，缺失或变化必须阻断；
- 正式文件必须可打开并通过最小内容检查；
- 不通过 `latest`、修改时间或模糊文件名继承状态；
- 客户工作区采用固定 `Input/Work/Output` 目录，可随产品整体复制；源码 checkout 中的 `customers/` 默认忽略，不得提交客户源数据、DuckDB、Parquet 或运行产物；
- 客户工作区不保留 Snapshot 历史；更新输入后必须使用新 `snapshot_id`，成功切换才删除旧 Snapshot，未完成会话必须先完成；
- 不提前建设 MCP、通用 DAG、多 Agent 编排、多层 Reviewer、独立强化插件或完整治理平台；新增治理必须对应可复现失败或明确客户要求。

## 开发顺序

S0 宿主验证、S1 Data Foundation、S2 Pack、S3 Bridge、S3.5 Bridge 对齐向导与真实教务跨端口验收，以及主线分析/PPTX 双宿主交付验证均已完成。当前唯一施工阶段是 S4 的 Quick 性能回归：主线 Bridge `company_bridge.v1_2_0` 的现金明细与工单数据生成新版冻结分析；短数据、已冻结分析的 PPT 走项目 Quick 入口，复杂交付才走上游 Default；电子表格和可视化复用宿主能力；不开发 Renderer 或交付平台。不得向主线再增加教务数据。S4 后进入真实使用与按需迭代，不预排 S5/S6/S7 平台工程。企业字段与确认后的物理处理 SQL不回填 Pack；去重 SQL进入 Data Foundation 保存查询，不进入 Bridge。

## 文档路由

- `README.md`：五分钟项目总览；
- `开发文档.md`：开发原则与模块合同；
- `分段施工计划.md`：阶段顺序与退出条件；
- `docs/architecture.md`：权威架构与可移植性边界；
- `docs/integration-guide.md`：现有 CLI 与各宿主的调用方式；
- `docs/company-bridge-contract.md`：Bridge 候选、正式构建、状态门禁与兼容性校验；
- `docs/bridge-alignment-wizard-contract.md`：向导 CLI、模型候选、问题、追加扫描和 finalize 合同；
- `docs/operator-runbook.md`：本地运行、验证和排障；
- `docs/handoff.md`：当前完成度、阻塞和唯一下一步。
