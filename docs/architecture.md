# 系统架构

## 1. 权威模型

系统由“原生 Agent Host + 稳定 CLI 边界 + 宿主无关 Data/Pack/Bridge + 客户工作区 + 项目级 Skills”构成。

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
┌───────▼────────┐ ┌─▼──────────┐ ┌─▼────────────┐
│ Data Foundation│ │ Business   │ │ Output       │
│ ingest/snapshot│ │ Pack+Bridge│ │ Skill+Render │
│ DuckDB/query   │ │ 行业+企业  │ │ files/UI     │
└───────┬────────┘ └─┬──────────┘ └─┬────────────┘
        └────────────┴───────────────┘
                         │
               ┌─────────▼──────────┐
               │ 按真实使用沉淀    │
               │ Skill/Template    │
               │ Pack/Bridge       │
               └────────────────────┘
```

## 2. 为什么宿主可替换

核心模块只暴露 CLI、文件、JSON、SQL 和版本化 manifest，不接收 Harness 的 `ctx`、Session 类、Conversation Node 或 Codex 专属对象。Codex、DeepSeek Harness 或其他具备受控 Shell 的宿主使用自身原生 Agent 直接调用同一 CLI，并通过项目 Skills 学习业务操作方式。项目不在宿主之上或之内再建设一层 Agent、模型路由或对话调度；宿主可替换性不依赖 MCP。

可移植资产：

- `data_foundation/` Python 代码与数据合同；
- Business Pack 与 Company Bridge manifest；
- 经真实需求验证的项目 Skills、模板和业务资产；

宿主专属资产：

- DeepSeek Harness Profile、Provider 和受控 Shell 配置；
- Conversation Node 和对话内交互图表；
- 各宿主的权限、沙箱和 Session 配置。

因此换宿主时，PPT、HTML、DuckDB、数据预处理、确定性门禁和项目 Skills 不受影响；主要变化是宿主自己的对话、Session、工具授权和 UI。只有未来真实宿主不能调用 CLI 时，才为该消费者评估最薄调用适配器；不把现有宿主封装成另一套 Agent 系统。

## 3. 数据流和身份

```text
只读源文件
  → inspect（结构与源 SHA-256 绑定）
  → ingest（run_id + immutable snapshot_id）
  → DuckDB / Parquet
  → describe / quality / read-only query
  → result identity / artifact manifest
  → Bridge 对齐向导（profile → proposed → confirm → build/validate）
  → Pack + Bridge 解释
  → Skill 组织分析与交付方法
  → 宿主生成并交付文件
```

运行以显式 `run_id` 区分，查询和恢复以显式 `snapshot_id` 定位仓库。源 SHA-256 用于 inspect/ingest 的源绑定以及 Snapshot/Artifact manifest，不要求在每次查询、Session 或交付物中继续传播。SQL 是直接查询输入或保存查询内容，不建立额外的统一血缘平台。Education Pack 1.0.0 与 Company Bridge 1.2.0 已独立版本化；Data Foundation 不伪造 Pack/Bridge 选择。

## 4. 确定性边界

项目不建设独立 Harness Reinforcement 插件。确定性约束由拥有数据或文件的模块直接实现：

- Data Foundation 保证源文件只读、Snapshot 不原地覆盖、查询入口只读并限制结果规模；
- Pack 校验器检查稳定 ID 和交叉引用；Bridge 建成后由语义模块阻断未确认映射成为正式事实；
- Bridge 对齐向导把模型候选限制为 proposed，以不可覆盖决定生成 confirmed_review；关键问题未答时阻断，非关键未答项显式 unresolved 并禁用能力；
- 多来源重叠和清洗由项目 Skill 提示模型使用 Data Foundation 只读查询举证；客户确认业务键、来源优先级和 SQL 后，以 saved query 固化。Bridge 只保存企业语义映射，不保存物理去重或合并 SQL；
- 交付文件由宿主打开检查，数字必须可回查到同一查询结果；只有真实失败才增加最小确定性工具；
- 状态恢复使用显式 `run_id`、`snapshot_id` 和后续 Pack/Bridge 版本，不通过 `latest`、修改时间或模糊文件名猜测。

Session 存储、沙箱、用户审批、模型路由、工具选择和计划管理继续使用宿主现成能力。只有可复现失败证明模块内约束不足时，才增加新的治理组件。

## 5. 语义边界

| 模块 | 回答的问题 | 禁止内容 |
|---|---|---|
| Data Foundation | 文件有什么结构、能否稳定查询 | 教育口径推断 |
| Education Pack | 教育行业通常如何定义 | 某客户当前事实 |
| Company Bridge | 这家客户如何命名和映射 | 修改行业标准概念身份 |
| Bridge 对齐向导 | 哪些新结构映射需要客户确认 | 让模型候选直接成为正式事实 |
| 客户工作区 | 当前公司的 Input/Work/Output 和已发布资产 | 跨公司动态路由和宿主状态管理 |

第一家企业可能让 Pack 和 Bridge 看起来近似，但物理分离能保证第二家企业只新增 Bridge，跨行业时新增 Pack 与 Bridge。

Data Foundation v2 将每个 Sheet 原样落入 `landing.column_N`，并在 `ingest.sheets` 登记目标表。表头行、企业业务列名、枚举和清洗规则由 Company Bridge 保存；Data Foundation 不再包含特定源表映射或企业语义视图。

向导工作区是可整体复制的客户产品目录：`Input` 保存当前数据与参考资料，`Work` 保存 Pack、当前指针、当前不可变 Snapshot 和单一会话文件，`Output` 保存正式 Bridge。源文件承担历史归档，工作区不保存 Snapshot 历史；刷新先成功发布并切换新 Snapshot，再清理旧 Run，失败或存在未完成会话时不动当前 Snapshot。仅保存已用 Snapshot ID，防止同名指向不同输入。路径相对工作区，不要求目录位于源码外；源码 checkout 仅通过 `.gitignore` 排除 `customers/`。宿主原生模型负责提出候选和理解客户回答，核心只校验候选、保存决定并确定性 build/validate，不依赖 Harness SDK 或 Codex SDK。旧 Bridge 只在 `company_id` 与 Pack 身份都相同时提供企业口径摘要，旧字段定位不会复用到新 Snapshot，也不在刷新后被标记为当前可运行 Bridge。

一套正常客户工作区默认对应一家公司和一个主要角色。Codex 或 DeepSeek Harness 直接在该工作区使用 Data、Pack、Bridge 和项目 Skills；换公司或换角色时由宿主创建新会话或清理记忆，再进入另一工作区。不建设 Customer Profile、公司/角色路由器或项目清理按钮。

## 6. 输出和交互

Codex、DeepSeek Harness 等宿主已具备 HTML、图表和文件生成/交付能力。项目优先装配成熟 PPT、表格和可视化 Skills，Skill 负责方法和模板，宿主负责执行与交付；只有出现宿主无法满足的可复现文件正确性问题时，才增加最小确定性工具。当前不建设独立 Renderer 或 Deliverables 平台。

## 7. 真实使用中的沉淀

宿主 Session 负责对话上下文、角色切换和记忆清理。只有重复出现且值得复用的内容才进入项目资产：

| 候选内容 | 晋升目的地 |
|---|---|
| 企业字段、术语、枚举和特殊口径 | Company Bridge |
| 跨企业稳定的行业知识 | Business Pack |
| 反复使用的分析或交付方法 | 项目 Skill / 模板 |
| 可稳定复现的代码失败 | 对应模块回归测试 |

模型只能生成候选，不能直接修改 Pack 或 Bridge。当前不预建 Memory、Cases、Eval、Promotion 或统一学习平台；客户工作区保持隔离即可。

## 8. 复杂度门槛

第一版只保留模块内已有或随模块实现的必要约束：只读查询、Snapshot 不覆盖、unresolved 阻断和文件验收。MCP、独立强化插件、完整 Run Manager、Artifact Registry、Reviewer、Promotion 自动化、Retention 和恢复平台都不是默认内容；只有失败 fixture 或明确客户要求证明必要时才增加。
