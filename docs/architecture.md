# 系统架构

## 1. 权威模型

系统由“可替换宿主 + 稳定 CLI 边界 + 宿主无关业务模块 + 薄客户装配 + 独立学习工作区”构成。

```text
┌──────────────────────────────────────────────┐
│ Agent Host                                   │
│ DeepSeek Harness（默认）/ Codex / Hermes / Claude │
│ 对话、Session、模型、Skills、工具调用、UI         │
└──────────────────────┬───────────────────────┘
                       │ controlled shell / CLI
┌──────────────────────▼───────────────────────┐
│ Customer Profile                             │
│ 选择 Data / Pack / Bridge / Skills / Model / Workspace │
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
               │ 学习与质量工作区  │
               │ Memory/Cases/Eval │
               │ Promotion/Archive │
               └────────────────────┘
```

## 2. 为什么宿主可替换

核心模块只暴露 CLI、文件、JSON、SQL 和版本化 manifest，不接收 Harness 的 `ctx`、Session 类或 Conversation Node。Codex、DeepSeek Harness 或其他具备受控 Shell 的宿主直接调用同一 CLI，并通过各自 Skill 学习调用方式。宿主可替换性不依赖 MCP。

可移植资产：

- `data_foundation/` Python 代码与数据合同；
- Business Pack 与 Company Bridge manifest；
- 可移植 Skills 与确定性 Renderers；
- 学习与质量工作区的数据格式和 Eval。

宿主专属资产：

- DeepSeek Harness Profile、Provider 和受控 Shell 配置；
- Conversation Node 和对话内交互图表；
- 各宿主的权限、沙箱和 Session 配置。

因此换宿主时，PPT、HTML、DuckDB、数据预处理、确定性门禁和大部分 Skills 不受影响；主要损失是 DeepSeek 专属对话交互和 UI。只有未来真实宿主不能调用 CLI 时，才为该消费者评估适配器。

## 3. 数据流和身份

```text
只读源文件
  → inspect（结构与源 SHA-256 绑定）
  → ingest（run_id + immutable snapshot_id）
  → DuckDB / Parquet
  → describe / quality / read-only query
  → result identity / artifact manifest
  → Pack + Bridge 解释
  → Skill 组织分析
  → Renderer 生成交付物
```

运行以显式 `run_id` 区分，查询和恢复以显式 `snapshot_id` 定位仓库。源 SHA-256 用于 inspect/ingest 的源绑定以及 Snapshot/Artifact manifest，不要求在每次查询、Session 或交付物中继续传播。SQL 是直接查询输入或保存查询内容，不建立额外的统一血缘平台。Education Pack 1.0.0 与 Company Bridge 1.2.0 已独立版本化；Data Foundation 不伪造 Pack/Bridge 选择。

## 4. 确定性边界

项目不建设独立 Harness Reinforcement 插件。确定性约束由拥有数据或文件的模块直接实现：

- Data Foundation 保证源文件只读、Snapshot 不原地覆盖、查询入口只读并限制结果规模；
- Pack 校验器检查稳定 ID 和交叉引用；Bridge 建成后由语义模块阻断未确认映射成为正式事实；
- Renderer 建成后由输出模块完成文件打开性与最小内容验收；
- 状态恢复使用显式 `run_id`、`snapshot_id` 和后续 Pack/Bridge 版本，不通过 `latest`、修改时间或模糊文件名猜测。

Session 存储、沙箱、用户审批、模型路由、工具选择和计划管理继续使用宿主现成能力。只有可复现失败证明模块内约束不足时，才增加新的治理组件。

## 5. 语义边界

| 模块 | 回答的问题 | 禁止内容 |
|---|---|---|
| Data Foundation | 文件有什么结构、能否稳定查询 | 教育口径推断 |
| Education Pack | 教育行业通常如何定义 | 某客户当前事实 |
| Company Bridge | 这家客户如何命名和映射 | 修改行业标准概念身份 |
| Customer Profile | 当前部署选择哪些模块 | 业务逻辑和事实 |

第一家企业可能让 Pack 和 Bridge 看起来近似，但物理分离能保证第二家企业只新增 Bridge，跨行业时新增 Pack 与 Bridge。

Data Foundation v2 将每个 Sheet 原样落入 `landing.column_N`，并在 `ingest.sheets` 登记目标表。表头行、企业业务列名、枚举和清洗规则由 Company Bridge 保存；Data Foundation 不再包含特定源表映射或企业语义视图。

## 6. 输出和交互

确定性输出器生成 PPTX、HTML、XLSX 或图片，Skill 负责内容策略，宿主负责触发和交付。静态产物属于可移植核心；DeepSeek Harness 的 Conversation Node 或 Client Plugin 属于可选交互增强。

## 7. 记忆与晋升

宿主 Session 只保存短期对话。长期资产的晋升目的地按内容决定：

| 候选内容 | 晋升目的地 |
|---|---|
| 企业字段、术语、枚举和特殊口径 | Company Bridge |
| 跨企业稳定的行业知识 | Business Pack |
| 可复用分析策略 | Business Memory |
| 可稳定复现的成功或失败 | Eval / Good Case / Bad Case |

Memory Extractor 或模型只能生成候选，不能直接修改长期资产。客户工作区必须隔离。

## 8. 复杂度门槛

第一版只保留模块内已有或随模块实现的必要约束：只读查询、Snapshot 不覆盖、unresolved 阻断和文件验收。MCP、独立强化插件、完整 Run Manager、Artifact Registry、Reviewer、Promotion 自动化、Retention 和恢复平台都不是默认内容；只有失败 fixture 或明确客户要求证明必要时才增加。
