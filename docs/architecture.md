# 系统架构

## 1. 权威模型

系统由“原生 Agent Host + 可独立选择的模块 Agent + 稳定 CLI 边界 + 宿主无关 Data/Pack/Bridge + 客户工作区”构成。项目是模块化运营数据中台，不提供默认主 Agent 或跨模块自然语言路由；调用者按任务选择 `agents/` 下的模块 Agent。

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

因此换宿主时，PPT、表格、图表、DuckDB、数据预处理、确定性门禁和项目 Skills 不受影响；主要变化是宿主自己的对话、Session、工具授权和 UI。只有未来真实宿主不能调用 CLI 时，才为该消费者评估最薄调用适配器；不把现有宿主封装成另一套 Agent 系统。

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

固定看板发布走另一条只读链路，不经过分析交付：

```text
当前 Snapshot
  → dashboard_actuals/v9（Data Platform run-saved-query）
  → artifact.json（全量，不进公网；目标区三组，同比区青少/初中/高中/大学；查询 12 列含 student_id）
  → 四分册 HTML + 可选钉钉人员图/表（现金可跨月用工单 ID 回查全量工单）
  → 服务器只托管静态文件
```

钉钉 webhook 和发布 SSH 密码属于 C 层，不进入公开仓库或 MCP。

## 4. 确定性边界

项目不建设独立 Harness Reinforcement 插件。确定性约束由拥有数据或文件的模块直接实现：

- Data Platform 保证源文件只读、Snapshot 不原地覆盖、查询入口只读并限制结果规模；
- Pack 校验器检查稳定 ID 和交叉引用；Bridge 建成后由语义模块阻断未确认映射成为正式事实；
- Bridge 对齐向导把模型候选限制为 proposed，以不可覆盖决定生成 confirmed_review；关键问题未答时阻断，非关键未答项显式 unresolved 并禁用能力；
- 多来源重叠和清洗由项目 Skill 提示模型使用 Data Platform 只读查询举证；客户确认业务键、来源优先级和 SQL 后，以 saved query 固化。Bridge 只保存企业语义映射，不保存物理去重或合并 SQL；
- 已冻结的短数据 PPT 使用项目 Quick 入口：冻结清单绑定证据哈希、Snapshot、关键查询和受控查询生成的来源凭据；项目只调用 PPT Master 官方 Quick checker/exporter，拒绝 Default 混用和本地静态 Quick 不允许的媒体/动画；
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

自由分析的调用说明位于 `agents/ad_hoc_analysis/AGENT.md`，宿主 Skill `.agents/skills/business-analysis-routing` 提供更细的调用步骤；`analysis_product/` 只承载确定性分析交付代码（当前为 PPT Quick）。Agent 文件是可选择的运行合同，不实现项目内 Agent Loop、Session 或模型路由。

Codex、DeepSeek Harness 等宿主已具备 HTML、图表和文件生成/交付能力。项目已装配固定版本的 `ppt-master` Skill，Skill 负责方法和模板，宿主负责执行与交付；表格和可视化先复用宿主能力。两个宿主已完成主线分析和可打开 PPTX 的交付验证。PPT 交付是通用会话合同，按需求选择直接回答、表格/查询结果或 PPTX，不固化教育业务页序。首轮验收关闭自动更新、外部研究、生图、TTS、旁白和本地 Web 辅助界面；只有出现宿主无法满足的可复现文件正确性问题时，才增加最小确定性工具。当前不建设独立 Renderer 或 Deliverables 平台。

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
