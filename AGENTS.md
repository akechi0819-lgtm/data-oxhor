# AGENTS.md

本文件是项目内所有 Agent 的唯一规则与项目事实源。不得为 Claude、Codex 或其他宿主维护第二套根目录规则文件；宿主差异只记录在对应接入文档或配置中。

## 当前阶段

项目已完成 Data Foundation CLI 的真实宿主接入验证，进入 Education Business Pack 施工准备阶段。项目不设默认宿主；版本化项目目录是可移植核心，Codex、DeepSeek Harness、Hermes 或其他具备受控 Shell 的宿主按部署选择。不得把本地验证环境描述成正式客户系统，也不得执行正式外部业务动作。

## 固定架构边界

1. 所选 Agent Host 负责对话、Session、模型、Skills、工具装配和宿主 UI；本项目不建设通用 Agent Loop。
2. Data Foundation、Education Business Pack、Company Bridge、Analysis Contract/Evidence Gate、确定性输出器和学习与质量工作区是本项目资产，不写入任何宿主的安装目录或上游源码。
3. Data Foundation 保持 Python 核心，CLI 是唯一公开入口。Codex、DeepSeek Harness、Hermes 和其他具备受控 Shell 的宿主直接调用同一 CLI；当前不建设 MCP，也不得为迁移宿主而重写成熟逻辑。
4. Business Pack 与 Company Bridge 从第一家企业起物理分离。Pack 保存行业标准知识；Bridge 保存企业术语、字段、枚举、选择和 Override。
5. Customer Profile 只负责选择宿主、Data、Pack、Bridge、Analysis Contract、Skills、模型和工作区，不承载业务逻辑。
6. Skills 只承载分析方法和操作说明；只读查询、数据身份、语义引用、结论—证据绑定和文件验收必须由确定性代码完成。
7. Data Foundation 的入仓是无计划原始 landing：XLSX 通过身份与可读性校验后，所有 Sheet 的非空源单元格值进入 `landing.column_N` 宽表。Python 不判断或修改空格、编号、数字、日期和文本类型；模型在入仓后通过受控 SQL 自主理解结构并决定查询级清洗。不得在入仓前要求模型逐 Sheet 制定 cleaning plan、选择业务字段或逐行清洗。
8. 宿主 Session 只承担短期对话上下文。长期业务 Memory、Good/Bad Case、Eval 和 Promotion 进入独立学习与质量工作区。
9. 新宿主优先通过受控 Shell 消费同一套 Python CLI、Pack、Bridge、Skills 和输出器；只有出现不支持 Shell 的真实消费者时才评估薄适配器，不提前建设协议层。
10. 只读、不可覆盖、unresolved 阻断和文件验收由各自业务模块的确定性代码负责；没有可复现失败时不建设独立强化插件、统一治理层或跨模块身份平台。
11. 空格处理、编号/数字/日期识别、类型转换和候选字段选择由模型在 landing 后自主判断并生成受控 SQL；证据明确时可直接用于当前查询。存在多个合理业务解释或要晋升为长期规范字段时，必须通过自然语言请求人工确认；确认结果结构化、版本化写入 Company Bridge，再由确定性执行器生成新的不可变规范数据层。不得覆盖 landing 或把企业映射硬编码回 Data Foundation。
12. DuckDB/Parquet、Pack/Bridge、静态文件输出和学习质量资产必须跨宿主复用；交互表格、Session、审批和文件展示属于可选宿主体验，不得成为核心施工门槛。
13. 模型负责推理，不保存或要求逐 Token 私有思考链；Analysis Skill/Pack Playbook 指导问题拆解、假设、替代解释、反证和不确定性，正式资产保存可审计 Analysis Record。每个 claim 必须引用 Snapshot、查询定义/结果和所用 Pack/Bridge 口径，Evidence Gate 输出 `supported / conditional / blocked`。Renderer 和正式回答不得消费 `blocked` claim。

## 当前已实现事实

- Python `>=3.12`，运行时依赖 DuckDB `1.5.5`；
- `data_foundation/` 已实现 XLSX 全 Sheet 探查、OOXML 流式读取、所有 Sheet 无计划原始 landing、不可变 DuckDB/Parquet Snapshot、结构质量查询和受控只读 SQL；
- `interfaces/data_foundation.py` 已提供 `inspect`、`ingest`、`describe`、`quality`、`query`、`run-saved-query`、`promote-query`；
- Data Foundation 已要求关键运行入口携带 `run_id`，查询通过显式 `snapshot_id` 定位仓库，并为 Snapshot 与大结果写入最小 Artifact manifest；这不是完整 Run/Artifact 平台；
- DeepSeek Harness `@deepseek-ai/dsh@0.1.0-rc.6` 是已验证可选宿主；真实 headless 模型已在不运行 inspect、不生成 cleaning plan 的条件下，将 3 个跨部门 XLSX 的 6 个 Sheet、47,087 个有内容行直接 landing，并在入仓后自主通过受控 SQL 完成结构识别、类型转换和排课汇总；Codex 可直接消费同一 CLI；Hermes 尚未做本项目真实验收；
- 现行 Python 测试 22 项通过；Data Foundation 不再包含特定源表映射或 `semantic.registration_cash`；
- 项目 Git 仓库已在 `main` 分支初始化，尚无首个提交；
- Business Pack、Bridge、Analysis Contract/Evidence Gate、Customer Profile、输出模块和学习与质量工作区尚未实现；MCP 不在当前计划内。

## 当前最小红线

- 原始输入只读，已发布 Snapshot 不得原地覆盖；
- Agent 只能通过受控入口执行只读 SQL；
- 未确认 Bridge 映射不得作为正式事实；
- 人工确认后的字段、单位、优先级、空值和冲突规则必须进入 Bridge；在正式规范层发布前保持可追溯、可复核；
- Analysis Contract 实现后，正式结论必须绑定证据并通过门禁；实现前不得声称当前模型回答已经通过确定性结论验收；
- 运行使用显式 `run_id`，查询和恢复使用显式 `snapshot_id`；源 SHA-256 只用于 inspect/ingest 的源绑定和 manifest，不要求在每次查询、Session 或交付物中传播；
- 正式文件必须可打开并通过最小内容检查；
- 不通过 `latest`、修改时间或模糊文件名继承状态；
- 不提前建设 MCP、通用 DAG、多 Agent 编排、多层 Reviewer、独立强化插件或完整治理平台；新增治理必须对应可复现失败或明确客户要求。

## 开发顺序

Data Foundation CLI 宿主接入与跨部门未知 XLSX 直接 landing 已完成，当前数据接入模块验收成功。下一施工项是 Education Business Pack；随后依次建设 Company Bridge、Analysis Contract/Evidence Gate、Customer Profile 和输出。Bridge 完成“模型自主判断 → 歧义时人工确认 → 规则固化 → 规范层发布”，Analysis Contract 再完成“结论 → 证据与口径引用 → supported/conditional/blocked”的正式门禁。所有新模块以项目目录和宿主无关合同交付。

## 文档路由

- `README.md`：五分钟项目总览；
- `开发文档.md`：开发原则与模块合同；
- `分段施工计划.md`：阶段顺序与退出条件；
- `docs/architecture.md`：权威架构与可移植性边界；
- `docs/integration-guide.md`：现有 CLI 与各宿主的调用方式；
- `docs/operator-runbook.md`：本地运行、验证和排障；
- `docs/handoff.md`：当前完成度、阻塞和唯一下一步。
