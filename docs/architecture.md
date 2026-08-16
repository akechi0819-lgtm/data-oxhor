# 系统架构

## 1. 权威模型

系统由“可替换宿主 + 稳定 CLI 边界 + 宿主无关业务模块 + 分析证据门禁 + 薄客户装配 + 独立学习工作区”构成。

```text
┌──────────────────────────────────────────────┐
│ Agent Host                                   │
│ Codex / DeepSeek Harness / Hermes / 其他宿主 │
│ 对话、Session、模型、Skills、工具调用、UI         │
└──────────────────────┬───────────────────────┘
                       │ controlled shell / CLI
┌──────────────────────▼───────────────────────┐
│ Customer Profile                             │
│ 选择 Data / Pack / Bridge / Analysis / Skills / Model / Workspace │
└───────────┬────────────────┬──────────────────┘
            │                │
┌───────────▼──────┐ ┌───────▼────────────┐
│ Data Foundation  │ │ Business           │
│ landing/snapshot │ │ Pack + Bridge      │
│ DuckDB/query     │ │ 行业 + 企业语义    │
└───────────┬──────┘ └───────┬────────────┘
            └────────┬───────┘
             ┌───────▼────────────────────┐
             │ Analysis Contract          │
             │ Analysis Record + Evidence Gate │
             └───────┬────────────────────┘
             ┌───────▼──────────────┐
             │ Output / Renderer    │
             │ files / optional UI  │
             └───────┬──────────────┘
             ┌───────▼──────────────┐
             │ 学习与质量工作区     │
             │ Memory/Cases/Eval    │
             └──────────────────────┘
```

## 2. 为什么宿主可替换

项目不指定默认宿主。核心模块只暴露 CLI、文件、JSON、SQL 和版本化 manifest，不接收任何宿主的 Session、插件或 UI 对象。Codex、DeepSeek Harness、Hermes 或其他具备受控 Shell 的宿主直接调用同一 CLI，并通过各自 Skill 或项目说明学习调用方式。宿主可替换性不依赖 MCP。

可移植资产：

- `data_foundation/` Python 代码与数据合同；
- Business Pack 与 Company Bridge manifest；
- Analysis Contract、Analysis Record 和 Evidence Gate；
- 可移植 Skills 与确定性 Renderers；
- 学习与质量工作区的数据格式和 Eval。

宿主专属资产：

- 各宿主的 Profile、Provider、权限、沙箱和 Session 配置；
- DeepSeek Harness Conversation Node、Codex 可视化或其他宿主的交互表格；
- 宿主自己的文件展示、审批和插件生命周期。

因此换宿主时，DuckDB/Parquet Snapshot、受控 SQL、Pack、Bridge、静态 PPT/HTML/XLSX、确定性门禁、长期学习资产和大部分 Skills 保持不变。变化主要在 Session 体验、审批方式、文件展示和交互表格；交互表格是可选增强，不是核心分析能力。只有真实宿主不能调用 CLI 时，才为该消费者评估薄适配器。

可移植交付边界就是一个版本化项目目录：现有 `data_foundation/`、`interfaces/`、测试和文档，加上后续独立的 Pack、Bridge、Analysis Contract/Evidence Gate、Skills、Renderers、Customer Profile 与学习工作区。该目录不嵌入任一宿主安装目录；宿主只需把它作为受控工作区并调用公开 CLI。

## 3. 数据流和身份

```text
只读源文件
  → ingest 内部快速校验（文件身份、XLSX 可读、全 Sheet 边界）
  → 源单元格值写入 landing.column_N
  → immutable DuckDB / per-Sheet Parquet
  → ingest.sheets 映射 / describe / quality / read-only query
  → 模型在入仓后用 SELECT/CTE 识别表头、转换类型和组合计算
  → 模型自主清洗与类型判断；歧义口径请求人工确认
  → Pack 约束概念 / Bridge 固化企业映射与口径
  → 确定性 SQL/Python 发布不可变规范层
  → Skill 指导模型分析并生成结构化 Analysis Record
  → Evidence Gate 校验结论、证据、口径、假设和 unresolved
  → supported / conditional / blocked
  → Renderer 生成交付物
```

运行以显式 `run_id` 区分，查询和恢复以显式 `snapshot_id` 定位仓库。源 SHA-256 用于 inspect/ingest 的源绑定以及 Snapshot/Artifact manifest，不要求在每次查询、Session 或交付物中继续传播。`inspect` 是可选诊断，不是 ingest 前置门槛；ingest 不接收 cleaning plan，不选择业务字段，也不推断表头。SQL 是直接查询输入或保存查询内容，不建立额外的统一血缘平台。Pack/Bridge 尚未实现，当前 Data Foundation 不伪造其版本。

## 4. 确定性边界

项目不建设宿主专属强化插件。确定性约束由拥有数据或文件的模块直接实现：

- Data Foundation 保证源文件只读、Snapshot 不原地覆盖、查询入口只读并限制结果规模；
- Pack/Bridge 建成后由语义模块阻断未确认映射成为正式事实；
- Analysis Contract 建成后由 Evidence Gate 阻断无证据、引用身份不一致或未披露冲突的正式结论；
- Renderer 建成后由输出模块完成文件打开性与最小内容验收；
- 状态恢复使用显式 `run_id`、`snapshot_id` 和后续 Pack/Bridge 版本，不通过 `latest`、修改时间或模糊文件名猜测。

Session 存储、沙箱、用户审批、模型路由、工具选择和计划管理继续使用宿主现成能力。只有可复现失败证明模块内约束不足时，才增加新的治理组件。

## 5. 语义边界

| 模块 | 回答的问题 | 禁止内容 |
|---|---|---|
| Data Foundation | 文件有什么结构、能否稳定查询 | 教育口径推断 |
| Education Pack | 教育行业通常如何定义 | 某客户当前事实 |
| Company Bridge | 这家客户如何命名和映射 | 修改行业标准概念身份 |
| Analysis Contract | 这个结论由什么证据支持、能否正式发布 | 替模型选择分析观点或保存私有思考链 |
| Customer Profile | 当前部署选择哪些模块 | 业务逻辑和事实 |

第一家企业可能让 Pack 和 Bridge 看起来近似，但物理分离能保证第二家企业只新增 Bridge，跨行业时新增 Pack 与 Bridge。

`data_foundation/` 已移除特定源表映射和 `semantic.registration_cash`。所有 Sheet 统一进入 landing；业务概念、企业字段映射和可复用转换归 Pack/Bridge，不能回流为 Data Foundation 硬编码。

模型负责在 landing 后判断空格处理、编号/数字/日期/文本类型、数据区域和候选映射，并生成受控 SQL；证据明确时可自主完成当前查询，不由 Python 预置清洗规则。模型不能自行把存在合理歧义的猜测晋升为企业事实：此时宿主发起自然语言确认，Company Bridge 保存确认后的结构化规则和版本，确定性执行器据此生成新的不可变规范表或 Snapshot。原始 landing 保持只读，Session 不承担长期口径存储，未确认项保持 `unresolved` 并阻断正式使用。

## 6. Analysis Record 与 Evidence Gate

模型负责提出假设、选择分析路径、执行受控查询、解释结果和寻找反证。Analysis Skill 约束问题拆解、替代解释、反证与不确定性表达，Pack Playbook 提供行业方法；后续 Eval/Golden Case 检查推理与结论正确性。项目不保存或要求模型逐 Token 的私有思考链；正式资产保存的是可审计推理摘要 `Analysis Record`。

第一版记录至少包含：

```text
analysis_id / run_id
snapshot_id
analysis_contract_id / analysis_contract_version
pack_id / pack_version / metric_refs
bridge_id / bridge_version / mapping_refs
claims[]:
  claim_id / statement
  evidence_refs[]
  counterevidence_refs[]
  method / alternatives_considered[]
  assumptions / caveats
  status: supported | conditional | blocked
```

`evidence_refs` 必须能定位查询定义和结果：保存查询 ID 或 SQL 文件哈希，加上 Artifact ID 或规范化内联结果摘要。只写自然语言“根据数据”不算证据引用。

确定性 Evidence Gate 只验证可审计性、引用一致性和发布资格，不代替模型推理，也不能单独证明叙事必然由证据推出：

- 没有证据引用的结论为 `blocked`；
- Snapshot、Pack 或 Bridge 身份不一致时为 `blocked`；
- 使用未确认 Bridge 映射的正式结论为 `blocked`；
- 证据冲突或关键假设尚未验证时，只能是 `conditional` 并披露限制；
- Renderer 和正式回答只能消费 `supported`，或明确标注限制的 `conditional`；不得消费 `blocked`。

Analysis Contract 是宿主无关核心模块，不是 Reviewer Agent、通用 Agent Loop 或完整 Artifact Registry。

## 7. 输出和交互

确定性输出器生成 PPTX、HTML、XLSX 或图片，Skill 负责内容策略，宿主负责触发和交付。静态产物属于可移植核心；任何宿主的交互表格、Conversation Node、Client Plugin 或专属可视化都属于可选增强。

## 8. 记忆与晋升

宿主 Session 只保存短期对话。长期资产的晋升目的地按内容决定：

| 候选内容 | 晋升目的地 |
|---|---|
| 企业字段、术语、枚举和特殊口径 | Company Bridge |
| 跨企业稳定的行业知识 | Business Pack |
| 可复用分析策略 | Business Memory |
| 可稳定复现的成功或失败 | Eval / Good Case / Bad Case |

Memory Extractor 或模型只能生成候选，不能直接修改长期资产。客户工作区必须隔离。

## 9. 复杂度门槛

第一版只保留模块内已有或明确要求的必要约束：只读查询、Snapshot 不覆盖、unresolved 阻断、结论—证据绑定和文件验收。MCP、独立强化插件、完整 Run Manager、Artifact Registry、Reviewer Agent、Promotion 自动化、Retention 和恢复平台都不是默认内容；只有失败 fixture 或明确客户要求证明必要时才增加。
