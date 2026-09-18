# 系统架构

## 1. 权威模型

系统由“原生 Agent Host + 可独立选择的模块 Agent + 稳定 CLI 边界 + 宿主无关 Data/Pack/Bridge + 客户工作区”构成。根目录 `AGENTS.md` 提供轻量板块导航，帮助调用者按任务定位目录及 `agents/` 下的说明，选定后按需读取，不预加载所有模块。项目不建设总控 Agent、跨模块调度或 Session 管理。

```text
┌──────────────────────────────────────────────┐
│ Agent Host                                   │
│ DeepSeek Harness（默认）/ Codex / Hermes / Claude │
│ 原生 Agent、对话、Session、模型、Skills、工具、UI │
└──────────────────────┬───────────────────────┘
                       │ controlled shell / CLI
┌──────────────────────▼───────────────────────┐
│ 客户工作区 + 项目 Skills                     │
│ Input / Work / Output + 分析与交付方法        │
└───────┬────────────┬──────────────┬───────────┘
        │            │              │
┌────────▼─────────┐ ┌───────────────┐ ┌─────────────────┐
│ Data Platform    │ │ Workspace     │ │ Analysis /      │
│ Snapshot/query   │ │ Modeling      │ │ Dashboard       │
│ landing/quality   │ │ Pack/Bridge   │ │ artifacts       │
└────────┬─────────┘ └──────┬────────┘ └────────┬────────┘
        └────────────┴───────────────┘
                         │
               ┌─────────▼──────────┐
               │ 本地案例与反馈沉淀 │
               │ Casebook/Skill    │
               │ Template/Pack/Bridge │
               └────────────────────┘
```

项目本地优先；已授权云端宿主可以执行固定定时、刷新、发布与托管，不承载个人自由分析主流程。本次演进不迁移现有云端任务。新增需求优先复用模块，仅在职责、权限或运行周期独立时评估新增 Agent 运行说明。

## 2. 为什么宿主可替换

核心模块只暴露 CLI、文件、JSON、SQL 和版本化 manifest，不接收 Harness 的 `ctx`、Session 类、Conversation Node 或 Codex 专属对象。Codex、DeepSeek Harness 或其他具备受控 Shell 的宿主根据任务选择 `agents/` 下的模块说明，再调用同一 CLI。项目不在宿主之上或之内再建设总 Agent、模型路由或对话调度；宿主可替换性不依赖 MCP。

可移植资产：

- `data_platform/` Python 代码与数据合同；
- Business Pack 与 Company Bridge manifest；
- 经真实需求验证的项目 Skills、模板和业务资产；

宿主专属资产：

- DeepSeek Harness Profile、Provider 和受控 Shell 配置；
- Conversation Node 和对话内交互图表；
- 各宿主的权限、沙箱和 Session 配置。

因此换宿主时，数据查询、表格/图表、DuckDB、数据预处理、确定性门禁和项目 Skills 不受影响；PPT 能力要求新宿主安装全局 `ppt-master`。业务执行继续使用 CLI；项目级上下文按明确用户需求独立建设只读服务及后续薄 MCP 适配器，不把现有宿主封装成另一套 Agent 系统。

## 3. 数据流和身份

```text
只读源文件
  → inspect（结构与源 SHA-256 绑定）
  → ingest（run_id + immutable snapshot_id）
  → DuckDB / Parquet
  → describe / quality / read-only query（实际 landing 关系与来源凭据）
  → result identity / artifact manifest
  → Bridge 对齐向导（profile → proposed → confirm → build/validate）
  → Pack + Bridge 解释
  → Skill 组织分析与交付方法
  → 宿主生成并交付文件
```


运行以显式 `run_id` 区分，查询和恢复以显式 `snapshot_id` 定位仓库。源 SHA-256 用于 inspect/ingest 的源绑定以及 Snapshot/Artifact manifest。每个受控查询结果同时记录由 `ingest.sheets` 反查的 `referenced_relations` 与 `referenced_source_ids`；这只服务于冻结分析的来源校验，不扩张为统一血缘平台。SQL 是直接查询输入或保存查询内容。Education Pack 1.0.0 与 Company Bridge 按企业工作区独立版本化；Data Platform 不伪造 Pack/Bridge 选择。

公共证据演进只统一查询回执、文件身份与业务交付清单的公共字段和引用，不统一产品业务内容，也不建设 Artifact Registry。Data Platform 生产物理执行证据，业务层绑定工作区与 Pack/Bridge，Casebook 复制最小引用闭包并验证；Pack.metrics 保持指标定义权威，不新建第二套指标库。字段责任、路径和分轮状态见 [公共证据合同](./evidence-contract.md)。第 2 轮已实现自由分析链路：查询始终落盘回执，交付组包与 Casebook 可独立验证；看板、监控和市场入口已同步查询读取，看板保持静态图表定位，监控保持现有产物结构；原定最终产物统一改造已取消。后续只针对现有能力无法解决的实际问题调整，不为格式一致而扩建。

固定看板发布走另一条只读链路，不经过分析交付：

```text
当前 Snapshot
  → dashboard_actuals/v10（Data Platform run-saved-query）
  → artifact.json（全量，不进公网；目标区三组，同比区青少/初中/高中/大学；查询 12 列含 student_id）
  → 四分册 HTML
  → 服务器只托管静态文件
```

钉钉 webhook 和发布 SSH 密码属于 C 层，不进入公开仓库或 MCP。

## 4. 确定性边界

项目不建设独立 Harness Reinforcement 插件。确定性约束由拥有数据或文件的模块直接实现：

- Data Platform 保证源文件只读、Snapshot 不原地覆盖、查询入口只读并限制结果规模；
- Pack 校验器检查稳定 ID 和交叉引用；Bridge 建成后由语义模块阻断未确认映射成为正式事实；
- Bridge 对齐向导把模型候选限制为 proposed，以不可覆盖决定生成 confirmed_review；关键问题未答时阻断，非关键未答项显式 unresolved 并禁用能力；
- 多来源重叠和清洗由项目 Skill 提示模型使用 Data Platform 只读查询举证；客户确认业务键、来源优先级和 SQL 后，以 saved query 固化。Bridge 只保存企业语义映射，不保存物理去重或合并 SQL；
- PPT 由宿主全局 `ppt-master` 按需路由 Quick 或 Default；项目只提供当前 Snapshot 的受控查询证据、口径、时间范围、来源与限制，不实现第二套路由或 Renderer；
- 交付文件由宿主打开检查，数字必须可回查到同一查询结果；只有真实失败才增加最小确定性工具；
- 状态恢复使用显式 `run_id`、`snapshot_id` 和后续 Pack/Bridge 版本，不通过 `latest`、修改时间或模糊文件名猜测。

Session 存储、沙箱、用户审批、模型路由、工具选择和计划管理继续使用宿主现成能力。只有可复现失败证明模块内约束不足时，才增加新的治理组件。

## 5. 语义边界

| 模块 | 回答的问题 | 禁止内容 |
|---|---|---|
| Data Platform | 文件有什么结构、能否稳定查询 | 教育口径推断 |
| Education Pack | 教育行业通常如何定义 | 某客户当前事实 |
| Company Bridge | 这家客户如何命名和映射 | 修改行业标准概念身份 |
| Bridge 对齐向导 | 哪些新结构映射需要客户确认 | 让模型候选直接成为正式事实 |
| 客户工作区 | 当前公司的 Input/Work/Output 和已发布资产 | 跨公司动态路由和宿主状态管理 |

第一家企业可能让 Pack 和 Bridge 看起来近似，但物理分离能保证第二家企业只新增 Bridge，跨行业时新增 Pack 与 Bridge。

Data Platform v2 将每个 Sheet 按实际表头名原样落入 landing，并在 `ingest.sheets` 登记目标表和表头元数据。表头行、企业业务列名、枚举和清洗规则由 Company Bridge 保存；Data Platform 不再包含特定源表映射或企业语义视图。

首次部署先由宿主 Skill 询问业务端口（例如高中、初中、市场、运营、教学），再通过 workspace-modeling CLI 初始化工作区、导入来源并发布 Snapshot。工作区配置中的 `business_port` 是用户选择的业务范围；`company_id` 只作为由工作区路径生成的内部隔离身份，不要求用户提供公司名称。Snapshot 发布后，Skill 自动调用 `handoff` 进入 Bridge 对齐；候选生成和关键口径确认仍由宿主原生 Agent 与用户完成。

向导工作区是可整体复制的客户产品目录：`Input` 保存当前数据与参考资料，`Work` 保存 Pack、当前指针、当前不可变 Snapshot 和对齐会话文件，`Output` 保存正式 Bridge。源文件承担历史归档，工作区不保存 Snapshot 历史；刷新先成功发布并切换新 Snapshot，再清理旧 Run，失败或存在未完成会话时不动当前 Snapshot。仅保存已用 Snapshot ID，防止同名指向不同输入。路径相对工作区，不要求目录位于源码外；源码 checkout 仅通过 `.gitignore` 排除 `customers/`。宿主原生模型负责提出候选和理解客户回答，核心只校验候选、保存决定并确定性 build/validate，不依赖 Harness SDK 或 Codex SDK。旧 Bridge 只在 `company_id` 与 Pack 身份都相同时提供企业口径摘要，旧字段定位不会复用到新 Snapshot，也不在刷新后被标记为当前可运行 Bridge。

一套正常客户工作区默认对应一家公司和一个主要角色。Codex 或 DeepSeek Harness 直接在该工作区使用 Data、Pack、Bridge 和项目 Skills；换公司或换角色时由宿主创建新会话或清理记忆，再进入另一工作区。不建设 Customer Profile、公司/角色路由器或项目清理按钮。

## 6. 输出和交互

自由分析的调用说明位于 `agents/ad_hoc_analysis/AGENT.md`，宿主 Skill `.agents/skills/business-analysis-routing` 提供更细的调用步骤；`analysis_product/` 保留为未来确定性分析代码边界，当前不承载 PPT 实现。Agent 文件是可选择的运行合同，不实现项目内 Agent Loop、Session 或模型路由。

Codex、DeepSeek Harness 等宿主已具备 HTML、图表和文件生成/交付能力。表格和可视化先复用宿主能力；PPT 由宿主全局 `ppt-master` 负责方法、路由、模板和质量门禁。PPT 交付不固化教育业务页序，也不在项目中复制全局 Skill。只有出现宿主无法满足的可复现文件正确性问题时，才增加最小确定性工具。当前不建设独立 Renderer 或 Deliverables 平台。

## 7. Casebook、内测回收与真实使用中的沉淀

宿主 Session 负责对话上下文、角色切换和记忆清理。`runs/` 保留客户本地的原始运行证据，但不自动成为 Agent 记忆，也不自动上传。S5 在每个客户工作区增加 Casebook：只将人工确认的最小证据包、结论、适用范围和限制作为可检索案例保存；案例需绑定 Snapshot、Pack/Bridge 版本和关键查询。命中案例只是线索，当前事实必须回到当前 Snapshot 的受控查询验证。

用户本地内测以版本化问题卡执行，生成评价记录和用户主动导出的反馈包。默认反馈包只含版本、评分、错误码、耗时和脱敏反馈；业务证据仅能由用户逐项授权附带。开发侧回收后按下表处理：

| 候选内容 | 晋升目的地 |
|---|---|
| 企业字段、术语、枚举和特殊口径 | Company Bridge |
| 跨企业稳定的行业知识 | Business Pack |
| 反复使用的分析或交付方法 | 项目 Skill / 模板 |
| 可稳定复现的代码失败 | 对应模块回归测试 |

模型只能生成候选，不能直接修改 Pack、Bridge、Skill 或模板。客户工作区内的引导路由只检查初始化、当前 Snapshot、兼容 Bridge 和重复问题，不做跨客户路由、模型路由或 Session 管理。无兼容 Bridge 时进入现有对齐向导；重复已确认问题只提示沉淀候选。当前不预建向量库、自动上传、自动 Promotion 或统一学习治理平台；客户工作区保持隔离即可。完整合同见 [Casebook、内测回收与引导路由合同](./casebook-pilot-contract.md)。

## 8. 复杂度门槛

第一版只保留模块内已有或随模块实现的必要约束：只读查询、Snapshot 不覆盖、unresolved 阻断和文件验收。MCP、独立强化插件、完整 Run Manager、Artifact Registry、Reviewer、Promotion 自动化、Retention 和恢复平台都不是默认内容；只有失败 fixture 或明确客户要求证明必要时才增加。

## 9. 日常监控模块（2026-09-16）

`monitoring_product/` 已从看板独立，首个场景是人员绩效进度与钉钉日报。调用链为：

```text
外部宿主定时 / 人工调用
  → daily_monitor Agent
  → monitoring_product.notify（显式 workspace / snapshot_id / run_id / 日期）
  → Data Platform 受控只读查询（三份通知 SQL，含跨月工单回查）
  → 同一份最终 digest → 图片 / Excel / 正文 → 已授权的钉钉通道
```

与看板共同使用 `workspace_modeling/operations/` 的人员匹配、绩效月与 BI 运营花名册；监控不再导入看板 Python 模块、不消费看板 artifact。Agent 可只读查看看板以核对，但不得自行刷新或发布。当前公司专用 SQL/花名册不宣称跨公司通用。

查询凭据与实际 SQL 留在本地 `_query/`；最终结果保存在 `evidence.json`。小查询即使由 Data Platform 内联返回，也保存查询回执，避免丢失来源凭据。所有选中通道成功取数后才生成交付物；任一失败整批阻断，不把失败当零。外部调度、密钥和服务器托管权限仍由宿主管理。

## 市场日常启动目录

`market_workspace/` 是当前公司市场角色的日常工作面，绑定现有 `customers/bi_operations/` 数据工作区，不另建公司身份，不复制 Snapshot，不改变原 operations 端口或 Bridge。底层模块继续由项目维护；生成代码、临时脚本和交付物与底层实现分开存放。

市场入口 `oxhor` 只绑定路径、检查 guide 与显式 Snapshot、固定本地 Evidence 输出，再调用已有 casebook/Data Platform CLI；不实现 SQL 引擎或第二套业务口径。Programs/Scratch 可按任务清理，Reports/Evidence/Notes 按成果保留。不用目录软链暴露数仓，也不声称有 OS 级权限隔离。该目录是本次为现有工作区装配的入口，首次部署 init 的行为没有改变；未来其他端口按实际需求装配，不预建路由器。

## Project Intelligence 本地上下文边界（2026-09-17）

用户确认新增独立 `project_intelligence/`，用于项目架构讨论与评审。第一阶段提供本地 Python API / CLI，对批准代码文档分段读取，对工作区仅投影身份与结构元数据。它单向复用 Data Platform describe 与 Bridge 合同校验，不调用会取样本的 guide/profile，不提供业务 SQL 或任何写操作。

现已在原服务外新增独立 stdio MCP 协议适配器，保持五个工具与服务实现不变；后续已通过项目外的官方 Secure MCP Tunnel 接入 ChatGPT Developer Mode，MCP 内核不新增网络监听。接入不改变既有宿主、模块 Agent、调度与 Session 边界，也不建设本机与 Grok 双向控制。远端状态保持未核验，文档记录、代码声明和本机实查分别带来源。范围、限制和命令见 [Project Intelligence](./project-intelligence.md)。
