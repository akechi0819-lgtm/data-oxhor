# Data OXHor 运行时宪法

本文件只定义 Data OXHor 各模块 Agent 在运行中的全局规则和安全边界。项目没有默认主 Agent 或跨模块路由器；调用者从 `agents/` 选择工作区初始化、自由分析、看板发布或其他模块 Agent。开发状态、测试结果、版本历史和发布步骤见 `DEVELOPMENT.md` 与 `docs/maintainer-guide.md`。

## 默认职责

1. Agent Host 负责自然语言理解、追问、候选 SQL、分析叙事和文件交付；项目 CLI、Pack、Bridge 和 Skills 提供确定性业务能力。
2. 每次日常分析都针对一个明确的客户工作区、一个主要角色和一个当前 Snapshot。不得跨公司、跨角色或跨工作区猜测事实。
3. 当前业务事实必须来自当前 Snapshot 的受控只读查询。Casebook 只能提供方法线索，历史数字不能直接回答当前问题。
4. 用户看到的是业务问题、结论、来源和限制；机器 JSON、内部 ID 和 CLI 只是宿主编排边界，不要求用户手工编辑。

## 自由分析 Agent 的运行顺序

只有选择 `agents/ad_hoc_analysis/AGENT.md` 时，才按以下顺序处理业务分析请求：

1. 用 `python3 -m interfaces.casebook guide --workspace <workspace>` 检查工作区状态。
2. 若未初始化、没有当前 Snapshot 或没有兼容 Bridge，停止分析并引导到对应的首次部署、数据同步或 Bridge 对齐流程。
3. 状态为 `analyze` 时，读取显式 `snapshot_id`、当前 Pack 和 Bridge；按角色和问题类别可选检索同公司已确认 Casebook。
4. 使用 Data Platform 的 `describe`、`quality`、`query` 或已确认的 `run-saved-query` 取得当前事实。每次查询携带显式 `run_id`、`snapshot_id` 和输出目录。
5. 回答时说明时间范围、指标口径、来源和限制。用户明确要求文件时，再生成表格、图表或 PPT，并确保数字可回查本次查询。
6. 用户明确验收且希望复用时，才创建 Casebook candidate；不得自动确认案例、修改 Pack/Bridge/Skill 或发布模板。

## 首次部署与状态切换

- 首次使用、导入数据、更新数据或建立口径时，使用 `first-deployment-onboarding` 和 Bridge 对齐流程；不要绕过向导直接分析。
- 用户必须确认业务端口、来源槽位、字段含义、枚举、日期、金额和关键口径；模型猜测只能作为 proposed 候选。
- Snapshot 不原地覆盖。更新数据使用新的显式 `snapshot_id`；新 Snapshot 成功切换前不删除旧状态，存在未完成对齐会话时不得刷新。
- 一套工作区默认对应一家公司和一个主要角色。换公司或角色时使用宿主的新任务/会话并切换到另一工作区，不建设项目侧公司路由器或 Session 管理器。

## 数据与证据红线

- 原始输入只读；不得上传客户文件、整个 `runs/`、DuckDB、Parquet 或工作区到外部服务。
- Agent 只能通过 Data Platform 受控入口执行只读 SQL，不直接连接客户 DuckDB，不使用 `latest`、修改时间或模糊文件名选状态。
- 未确认 Bridge 映射不能作为正式事实；日期重叠只是风险信号，不能直接当作重复或退款。
- 负向现金必须按数据事实表述为负向现金，原因需业务确认，不得自动称为退款。
- 正式文件必须可打开、内容非空，关键数字必须回查同一受控查询；Quick PPT 还必须满足冻结证据和来源凭据门禁。

## 模块边界

- Data Platform：原始 landing、Snapshot 身份、质量检查和受控只读查询，不解释教育业务。
- Business Pack：跨企业的行业概念、指标和方法，不保存客户事实。
- Company Bridge：单一公司的术语、字段、枚举和 Override，不替代 Pack，不保存物理去重 SQL。
- Agents：按业务场景提供可独立选择的运行说明，不是项目内 Agent Loop、Session 管理器或模型路由器。
- Skills：分析方法和确定性操作说明，不是第二个 Agent 或 SQL 编译器。
- Casebook：人工确认的最小方法证据，不是当前事实库或自动学习平台。

## 文档路由

- 客户日常使用：`docs/user-guide.md`
- 系统边界与数据流：`docs/architecture.md`
- CLI/宿主接入：`docs/integration-guide.md`
- 本地运维与故障排查：`docs/operator-runbook.md`
- 开发、测试、发布和文档维护：`docs/maintainer-guide.md`
- Bridge、Onboarding、Casebook、PPT 合同：对应 `docs/*-contract.md` 和 `docs/s4-ppt-quick-prompt.md`
- 当前开发状态与决策：`DEVELOPMENT.md`
- 当前完成度与历史交接：`docs/handoff.md`
- 看板发布与钉钉：`dashboard_product/DEPLOYMENT.md`、`agents/dashboard_publisher/AGENT.md`
- 云电脑分层同步：`SYNC.md`（A 代码 / B 数据 / C 密钥；不建设双向 MCP）
