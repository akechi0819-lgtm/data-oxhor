# AGENTS.md

本文件是项目内所有 Agent 的唯一规则与项目事实源。不得为 Claude、Codex 或其他宿主维护第二套根目录规则文件；宿主差异只记录在对应接入文档或配置中。

## 当前阶段

项目处于“业务模块独立开发 + CLI 宿主接入验证”阶段。DeepSeek Harness 是默认客户运行宿主，Codex 是可直接验证的另一宿主；业务核心必须保持宿主无关。不得把本地验证环境描述成正式客户系统，也不得执行正式外部业务动作。

## 固定架构边界

1. DeepSeek Harness 负责对话、Session、模型、Skills、工具装配和插件生命周期；本项目不建设通用 Agent Loop。
2. Data Foundation、Education Business Pack、Company Bridge、确定性输出器和学习与质量工作区是本项目资产，不写入 Harness 上游源码。
3. Data Foundation 保持 Python 核心，CLI 是唯一公开入口。Codex、DeepSeek Harness 和其他具备受控 Shell 的宿主直接调用同一 CLI；当前不建设 MCP，也不得为迁移宿主而重写成熟逻辑。
4. Business Pack 与 Company Bridge 从第一家企业起物理分离。Pack 保存行业标准知识；Bridge 保存企业术语、字段、枚举、选择和 Override。
5. Customer Profile 只负责选择宿主、Data、Pack、Bridge、Skills、模型和工作区，不承载业务逻辑。
6. Skills 只承载分析方法和操作说明；只读查询、数据身份、语义引用检查和文件验收必须由确定性代码完成。
7. 宿主 Session 只承担短期对话上下文。长期业务 Memory、Good/Bad Case、Eval 和 Promotion 进入独立学习与质量工作区。
8. 新宿主优先通过受控 Shell 消费同一套 Python CLI、Pack、Bridge、Skills 和输出器；只有出现不支持 Shell 的真实消费者时才评估薄适配器，不提前建设协议层。
9. 只读、不可覆盖、unresolved 阻断和文件验收由各自业务模块的确定性代码负责；没有可复现失败时不建设独立强化插件、统一治理层或跨模块身份平台。

## 当前已实现事实

- Python `>=3.12`，运行时依赖 DuckDB `1.5.5`；
- `data_foundation/` 已实现 XLSX 全 Sheet 探查、OOXML 流式读取、不可变 Snapshot、DuckDB/Parquet 入仓、质量问题查询和受控只读 SQL；
- `interfaces/data_foundation.py` 已提供 `inspect`、`ingest`、`describe`、`quality`、`query`、`run-saved-query`、`promote-query`；
- Data Foundation 已要求关键运行入口携带 `run_id`，查询通过显式 `snapshot_id` 定位仓库，并为 Snapshot 与大结果写入最小 Artifact manifest；这不是完整 Run/Artifact 平台；
- DeepSeek Harness `@deepseek-ai/dsh@0.1.0-rc.6` 已安装到本机全局环境，Web 健康检查通过；模型 Provider/API Key 已配置，真实模型回合可用，并已在项目 Workspace 通过 Shell 成功执行 Data Foundation 顶层 `--help`（退出码 0、发现 7 个子命令）；
- 项目 Git 仓库已在 `main` 分支初始化，尚无首个提交；
- Business Pack、Bridge、Customer Profile、输出插件和学习与质量工作区尚未实现；MCP 不在当前计划内。

## 当前最小红线

- 原始输入只读，已发布 Snapshot 不得原地覆盖；
- Agent 只能通过受控入口执行只读 SQL；
- 未确认 Bridge 映射不得作为正式事实；
- 运行使用显式 `run_id`，查询和恢复使用显式 `snapshot_id`；源 SHA-256 只用于 inspect/ingest 的源绑定和 manifest，不要求在每次查询、Session 或交付物中传播；
- 正式文件必须可打开并通过最小内容检查；
- 不通过 `latest`、修改时间或模糊文件名继承状态；
- 不提前建设 MCP、通用 DAG、多 Agent 编排、多层 Reviewer、独立强化插件或完整治理平台；新增治理必须对应可复现失败或明确客户要求。

## 开发顺序

唯一当前施工项是：用现有 Data Foundation CLI 完成宿主接入验证。普通模型回合、Workspace、Shell 和 CLI 顶层发现已经通过；下一步用一次性小型 fixture 完成“探查 → 入仓 → 描述 → 质量 → 查询”，随后验证 Session 恢复和小型文件交付。完成前不并行施工 Pack、Bridge 或输出插件。

## 文档路由

- `README.md`：五分钟项目总览；
- `开发文档.md`：开发原则与模块合同；
- `分段施工计划.md`：阶段顺序与退出条件；
- `docs/architecture.md`：权威架构与可移植性边界；
- `docs/integration-guide.md`：现有 CLI 与各宿主的调用方式；
- `docs/operator-runbook.md`：本地运行、验证和排障；
- `docs/handoff.md`：当前完成度、阻塞和唯一下一步。
