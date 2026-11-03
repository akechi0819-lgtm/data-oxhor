> **2026-10-28唯一正式BI数据源**：本机main使用 `customers/shadow_bi_daily`，旧正式仓、独立基线仓和c373数据镜像已退役；不维护双轨。语培/留学Snapshot仍是这一套链路内部的必要分工。原始输入及少量正式附件归档保留，当前状态见[开发文档](../DEVELOPMENT.md)。本轮未操作服务器或日程；以下旧日期记录保留历史边界。

> **当前日更代码入口（2026-11-03）**：Mac 本地 `prepare_full_daily --publish` 按“业务基础发布→立即通知→采集并发布广告费用”执行；默认模式（含 `--prepare`）只生成隔离候选。11/3 完成回执记录 127 个云端源文件与本机 SHA 一致，并记载次日 bi-3 仍由本机 09:30 执行；这是日期回执，不是实时调度核验。服务器 raw 接收/计算/发布目前未启用，10/26 暂停及失败批次是历史事实。完整状态见[日更说明](shadow-bi-full-daily-20261028.md)。

> **历史部署背景（2026-10-26）**：当日 Mac `p5.daily` 更新了 `daily-20261026_094052`；服务器 raw worker 跑到39张表后因截止不匹配以 `failed/published=false` 结束，没有发布 raw release。10/26 清理回执记录暂停 raw 接收/计算/发布；11/3 完成回执仍记载 raw 路径未启用。旧批次、Dot 10:00 通知记录与当前 Mac 日更入口各自独立。部署细节见[正式基线](bi-production-baseline-20261025.md)、[raw接收回执](server-raw-receiver-deployment-20261026.md)及[固定发布回执](server-raw-fixed-publisher-20261026.md)。

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
               │ Casebook            │
               │ ↓ 人工审核后沉淀    │
               │ Skill/Template/Pack/Bridge │
               └────────────────────┘
```

项目本地优先；已授权云端宿主可以执行固定定时、刷新、发布与托管，不承载个人自由分析主流程。本次演进不迁移现有云端任务。新增需求依次评估：**复用已有模块 → 扩展已有接口 → 新增模块 → 新增 Agent**。只有前三种方式无法满足，并且职责、权限边界或运行周期确有独立需求时，才新增 Agent 运行说明。

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

公共证据演进只统一查询回执、文件身份与业务交付清单的公共字段和引用，不统一产品业务内容，也不建设 Artifact Registry。Data Platform 生产物理执行证据，业务层绑定工作区与 Pack/Bridge，Casebook 复制最小引用闭包并验证；Pack.metrics 保持指标定义权威，不新建第二套指标库。字段责任、路径和分轮状态见 [公共证据合同](./evidence-contract.md)。第 2 轮已实现自由分析链路：查询始终落盘回执，交付组包与 Casebook 可独立验证；自由分析和市场入口通过 Data Platform 受控查询读取。BI 产品界面为 Superset 原生看板，服务器计算链路复用同一份业务计算代码；通知只消费固定正式 release，不独立查询数仓。

固定看板和推送共用一条管理批次链路，不经过自由分析交付：

```text
当前日更：Mac bi-3 → prepare_full_daily --publish
  → 双Snapshot / 共同计算 → 基础BI release / current
                  ├→ 固定通知入口 → shared_delivery → 8条通知
                  └→ 复用同批 Snapshot 采集费用 → 费用 / ROI release

当前 raw 路径未启用：Dot三Excel → raw receiver / 双仓worker / 固定publisher
  （10/26 的暂停与失败状态保留为历史；11/3 回执仍记载该路径未启用）
```

同批通知内容、查询回执和 DeliveryState 保存在受限工作目录，不发布到 BI 页面根；只将投递所需的图片与表格资源提供给固定通知资产路径。钉钉 webhook 和发布凭据属于 C 层，不进入公开仓库或 MCP。

本地main的raw计算与固定发布代码另要求受保护来源完成证明：计算预检缺证据则停止，候选封口/复用及固定发布前复核同一证明；最大记录日与经验证截止分开。10月26日部署回执对应服务器已安装版本，不含本轮本地新增的完成证明门禁，因此不能推断该新门禁已在服务器生效。合同见[来源完整性](server-source-completion-candidate.md)。

11/3 完成回执记录正式云端代码与本机 127 个源文件 SHA 一致，次日 bi-3 仍计划由 Mac 09:30 采集，再调用云端 P4 与通知入口；回执没有实读当前调度平台。当天双仓基础版、费用版已发布，日报 8 条已 sent 且本次未重发；正式current为 `daily-20261103_141437`。服务器 raw 计算与发布路径仍未启用。

10/26 历史日期回执记录当时 current `daily-20261026_094052`（数据截止10-25），由 Mac `p5.daily` 更新。Dot 批次 `raw-20261026-dot-001` 跑完双Snapshot、quality及39表计算后，因业务截止不匹配以 `failed/published=false` 结束，未激活新版本；10/26 清理回执暂停 raw 路径。Dot 10:00 日程记录针对通知，与 BI 采集／刷新分开；Grok 例行按用户要求停止。详见[通知作业修复回执](./notification-job-receipt-repair-20261026.md)、[接收部署回执](./server-raw-receiver-deployment-20261026.md)和[固定发布回执](./server-raw-fixed-publisher-20261026.md)。

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

向导工作区是可整体复制的客户产品目录：`Input` 保存当前数据与参考资料，`Work` 保存 Pack、当前指针、当前不可变 Snapshot 和对齐会话文件，`Output` 保存正式 Bridge。业务确认的官方记分卡放在 `Input/Reference/`，不进 Snapshot、不进 Bridge 数据行；覆盖范围内的指标以记分卡为准，数仓查询只作明细、拆解和对账。源文件承担历史归档，工作区不保存 Snapshot 历史；刷新先成功发布并切换新 Snapshot，再清理旧 Run，失败或存在未完成会话时不动当前 Snapshot。仅保存已用 Snapshot ID，防止同名指向不同输入。路径相对工作区，不要求目录位于源码外；源码 checkout 仅通过 `.gitignore` 排除 `customers/`。宿主原生模型负责提出候选和理解客户回答，核心只校验候选、保存决定并确定性 build/validate，不依赖 Harness SDK 或 Codex SDK。旧 Bridge 只在 `company_id` 与 Pack 身份都相同时提供企业口径摘要，旧字段定位不会复用到新 Snapshot，也不在刷新后被标记为当前可运行 Bridge。

一套正常客户工作区默认对应一家公司和一个主要角色。Codex 或 DeepSeek Harness 直接在该工作区使用 Data、Pack、Bridge 和项目 Skills；换公司或换角色时由宿主创建新会话或清理记忆，再进入另一工作区。不建设 Customer Profile、公司/角色路由器或项目清理按钮。

## 6. 输出和交互

自由分析的调用说明位于 `agents/ad_hoc_analysis/AGENT.md`，宿主 Skill `.agents/skills/business-analysis-routing` 提供更细的调用步骤；确定性交付组包已由 `workspace_modeling.delivery` 实现；空占位包 `analysis_product/` 已删除，不恢复独立交付占位模块。Agent 文件是可选择的运行合同，不实现项目内 Agent Loop、Session 或模型路由。

Codex、DeepSeek Harness 等宿主已具备 HTML、图表和文件生成/交付能力。表格和可视化先复用宿主能力；PPT 由宿主全局 `ppt-master` 负责方法、路由、模板和质量门禁。PPT 交付不固化教育业务页序，也不在项目中复制全局 Skill。只有出现宿主无法满足的可复现文件正确性问题时，才增加最小确定性工具。当前不建设独立 Renderer 或 Deliverables 平台。

## 7. Casebook、内测回收与真实使用中的沉淀

宿主 Session 负责对话上下文、角色切换和记忆清理。`runs/` 保留客户本地的原始运行证据，但不自动成为 Agent 记忆，也不自动上传。S5 在每个客户工作区增加 Casebook：只将人工确认的最小证据包、结论、适用范围和限制作为可检索案例保存；案例需绑定 Snapshot、Pack/Bridge 版本和关键查询。命中案例只是线索，当前事实默认必须回到当前 Snapshot 的受控查询验证。官方记分卡已覆盖的留学完成值与目标除外：以 `Input/Reference` 记分卡为准，不以 Casebook 或数仓核算值覆盖。

用户本地内测以版本化问题卡执行，生成评价记录和用户主动导出的反馈包。默认反馈包只含版本、评分、错误码、耗时和脱敏反馈；业务证据仅能由用户逐项授权附带。开发侧回收后按下表处理：

| 候选内容 | 晋升目的地 |
|---|---|
| 企业字段、术语、枚举和特殊口径 | Company Bridge |
| 跨企业稳定的行业知识 | Business Pack |
| 反复使用的分析或交付方法 | 项目 Skill / 模板 |
| 可稳定复现的代码失败 | 对应模块回归测试 |

模型只能生成候选，不能直接修改 Pack、Bridge、Skill 或模板。客户工作区内的引导路由只检查初始化、当前 Snapshot、兼容 Bridge 和重复问题，不做跨客户路由、模型路由或 Session 管理。无兼容 Bridge 时进入现有对齐向导；重复已确认问题只提示沉淀候选。当前不预建向量库、自动上传、自动 Promotion 或统一学习治理平台；客户工作区保持隔离即可。完整合同见 [Casebook、内测回收与引导路由合同](./casebook-pilot-contract.md)。

## 8. 复杂度门槛

保留模块内已有的必要约束：只读查询、Snapshot 不覆盖、unresolved 阻断和文件验收。本次核查后的有限修复只补齐既有模块连接，不新增总 Agent、Capability Registry 系统、独立 Metric Layer 或 Artifact 平台；复杂度门槛不是恢复已取消施工的授权。其他扩展须由具体问题或明确新需求提出，按复用模块、扩展接口、新增模块、新增 Agent 的顺序另行评估。

## 9. 通知投递（当前代码合同）

管理构建和日常钉钉投递按同一批次身份运行：

```text
正式 BI release → release_notifications 构建与核验通知包
  → 固定服务器通知执行入口 → shared_delivery / transport
  → 8条消息 / 原5个通道，DeliveryState 持久去重
```

`release_notifications` 从固定的正式 BI release 读取受控表和人员参考，构建同批通知包并绑定来源、规则与查询回执；`shared_delivery` 校验身份、渲染附件并按持久状态逐消息去重，不重新查询或重算数仓。大学与线上平台各两条消息分别共用原群；人员匹配、绩效月和花名册仍共用 `workspace_modeling/operations/`。

2026-10-26 手动通知批次的 8 条消息均有 sent 记录；对应 HTTP job 原状态仍为 `unknown`，只读对账回执关联此前已完成的发送，不能把该 job 记为成功发送或重发消息。已有记录建立 Dot 每日上海 10:00 通知日程；它与 BI 采集刷新分属不同任务。本次未实读该日程当前启停。Grok 例行已按用户要求停止。服务器调度、C 层凭据与权限由宿主管理；运行状态以相应日期回执为准。

## 市场日常启动目录

`market_workspace/` 是当前公司市场角色的日常工作面，只读绑定 `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/` 正式数据工作区，不另建公司身份，不复制 Snapshot，不改变原 operations 端口或 Bridge。底层模块继续由项目维护；生成代码、临时脚本和交付物与底层实现分开存放。

市场入口 `oxhor` 只绑定路径、检查 guide 与显式 Snapshot、固定本地 Evidence 输出，再调用已有 casebook/Data Platform CLI；不实现 SQL 引擎或第二套业务口径。Programs/Scratch 可按任务清理，Reports/Evidence/Notes 按成果保留。不用目录软链暴露数仓，也不声称有 OS 级权限隔离。该目录是本次为现有工作区装配的入口，首次部署 init 的行为没有改变；未来其他端口按实际需求装配，不预建路由器。

## Project Intelligence 本地上下文边界（2026-09-17）

用户确认新增独立 `project_intelligence/`，用于项目架构讨论与评审。第一阶段提供本地 Python API / CLI，对批准代码文档分段读取，对工作区仅投影身份与结构元数据。它单向复用 Data Platform describe 与 Bridge 合同校验，不调用会取样本的 guide/profile，不提供业务 SQL 或任何写操作。

现已在原服务外新增独立 stdio MCP 协议适配器，保持五个工具与服务实现不变；后续已通过项目外的官方 Secure MCP Tunnel 接入 ChatGPT Developer Mode，MCP 内核不新增网络监听。接入不改变既有宿主、模块 Agent、调度与 Session 边界，也不建设本机与 Grok 双向控制。远端状态保持未核验，文档记录、代码声明和本机实查分别带来源。范围、限制和命令见 [Project Intelligence](./project-intelligence.md)。
