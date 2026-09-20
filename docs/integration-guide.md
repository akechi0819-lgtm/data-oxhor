# 核心 CLI 接入指南

> 2026-09-16 模块切换：人员进度与钉钉推送已迁至 `monitoring_product/`，看板不再承担发送。新入口要求 workspace、snapshot-id、run-id、as-of-date、data-through-date；正式发送另需显式 env-file。共享花名册在 `workspace_modeling/operations/people.json`。本地迁移完成不代表云端任务已切换；详见项目根目录 `monitoring_product/README.md`。

## 1. 当前公开入口

### 1.1 安装

发布包按能力提供依赖集合：

```bash
python3 -m pip install "data-oxhor[full]"
```

`core` 只安装数据分析运行时，`test` 增加项目测试依赖，`full` 覆盖当前项目的 Python 能力。源码用户可执行 `sh tools/install_runtime.sh test` 或 `sh tools/install_runtime.sh full`；不建议在系统 Python 中逐项安装。PPT Master、DeepSeek Harness、Office/字体和模型凭据属于宿主环境，不由项目 wheel 管理。

首次部署引导层使用同一 Python 环境：

```bash
python3 -m interfaces.workspace_modeling doctor --profile full
python3 -m interfaces.workspace_modeling init --workspace customers/company_customer --business-port operations
python3 -m interfaces.workspace_modeling import-data --workspace customers/company_customer --source-id cash --file /path/to/cash.xlsx
python3 -m interfaces.workspace_modeling sync --workspace customers/company_customer --snapshot-id snapshot_company_2026_08
python3 -m interfaces.workspace_modeling handoff --workspace customers/company_customer --session-id session_onboarding
```

引导层只编排确定性状态：运行时/Pack 检查、`Input/Work/Output` 初始化、工作簿复制、Snapshot 发布和 Bridge 会话交接。`import-data` 默认拒绝覆盖已有来源槽位，月度更新需显式 `--replace`；`sync` 使用新的显式 `snapshot_id`。引导层不会代替宿主 Agent 生成候选、理解自由回答、确认问题或发布正式 Bridge。所有命令 stdout 均为 `onboarding_result.v1` JSON；`doctor`、初始化、导入、同步和交接完成返回 0，仍需用户/宿主动作返回 2，合同或文件错误返回 1。

完整输入、输出、错误和边界见 [首次部署引导层合同](./onboarding-contract.md)。

Data Platform 的公开入口是 Python CLI：

```bash
python3 -m interfaces.data_platform --help
```

已实现子命令：

| 命令 | 所属模块 / 输入与依赖 | 输出 | 写入范围与外部副作用 |
|---|---|---|---|
| `inspect` | Data Platform；来源 manifest、工作簿、run_id | 结构/源哈希报告，不含明细行 | 显式本地输出；原始来源只读，无网络发送 |
| `ingest` | Data Platform；来源 manifest、新 snapshot_id、run_id | DuckDB/Parquet、Snapshot manifest | 发布新 Snapshot 与本地清单；不覆盖已有 Snapshot |
| `describe` | Data Platform；仓库路径、snapshot_id | schema/字段 JSON | 仓库只读，无外部副作用 |
| `quality` | Data Platform；仓库、snapshot_id、run_id、输出根 | 已登记质量问题的查询结果 | 仓库只读；所有成功结果写本地查询证据包 |
| `query` | Data Platform；仓库、snapshot_id、run_id、SQL/参数、输出根与限制 | 受控查询结果及来源 | 仓库只读；始终写 SQL/参数/完整结果/回执，无网络发送 |
| `promote-query` | Data Platform；仓库、snapshot_id、SQL、查询 ID/版本、确认人、registry_root | 保存查询登记 | 写仓库外新版本目录；不可覆盖版本，无业务确认推理 |
| `run-saved-query` | Data Platform；登记 ID/版本、参数、仓库、snapshot_id、run_id、输出根 | 同 query | 校验登记 SQL 哈希；只读仓库、本地结果写入 |

其他模块仍使用各自入口，不注册为 Data Platform 子命令：

| 入口 | 所属模块 / 主要输入与依赖 | 输出与读写范围 | 外部副作用 |
|---|---|---|---|
| `interfaces.workspace_modeling`、`interfaces.bridge_alignment` | Workspace Modeling；显式工作区、来源/Pack、确认决定 | Input/Work/Output、Snapshot 切换、对齐会话、正式 Bridge；详见各合同 | 本地复制与状态写入；不得替用户确认；sync 切换后可能清理旧 Snapshot |
| `interfaces.business_pack` | Workspace Modeling；Pack 文件 | validate/describe JSON，只读 | 无 |
| `interfaces.company_bridge` | Workspace Modeling；Pack、候选/Bridge、可选 Snapshot 画像 | 校验/扫描结果或 build 正式 Bridge；按子命令写显式输出 | 无自动业务确认或发送 |
| `interfaces.casebook` | Workspace Modeling；工作区、角色、用户选择的证据/评价 | guide/search/verify 只读；create/capture/confirm 等写本工作区 Casebook；反馈导出写本地 ZIP | 不自动上传，不自动确认案例 |
| `dashboard_product.refresh` | Dashboard；工作区、run、已确认保存查询与目标/花名册 | refresh 写本地业务 artifact；render 写 HTML | refresh/render 不等同发布；部署脚本另需发布授权 |
| `monitoring_product.notify` | Monitoring；workspace、snapshot、run、日期、花名册；正式发送需 env-file | 独立查询、digest、图片/Excel/证据；写显式本地输出 | dry-run 不发送；正式 send 上传并发送已授权钉钉通道 |
| `market_workspace/oxhor` | 市场工作面；固定数据工作区、显式 Snapshot/run | 只读 CLI 调用，写市场 Evidence；不提供导入/发布 | 无 |
| `project_intelligence` CLI / stdio MCP | Project Intelligence；批准代码/文档、工作区结构元数据 | 只读上下文，不返回业务明细、不执行业务 SQL | 服务内无业务写入；远程接入边界见专门文档 |

这是一份静态能力说明，精确参数与写入目录仍以各命令 `--help` 和模块合同为准。自由分析交付由宿主组织，不增加 `analyze` 核心服务或运行时 Capability Registry。

每个子命令的精确参数以 `--help` 为准，例如：

```bash
python3 -m interfaces.data_platform inspect --help
python3 -m interfaces.data_platform ingest --help
python3 -m interfaces.data_platform query --help
```

输入源由 manifest 绑定；不要把真实客户工作簿复制进仓库。运行产物应写入项目代码目录之外的显式工作区。

## 2. 已实现合同

- `inspect` 输出 schema `data_foundation_inspection.v2`；
- `ingest` 输出 schema `data_foundation_ingest.v2`，Snapshot manifest 为 `warehouse_snapshot.v2`；
- `inspect`、`ingest`、`quality`、`query` 和 `run-saved-query` 要求显式 `run_id`；`describe` 与 `promote-query` 按当前 CLI 参数不要求 `run_id`；
- Snapshot 发布后不可原地覆盖；
- 查询拒绝写操作、外部 reader、系统目录和绕过形式；
- 查询限制最大返回行数和结果字节数；
- Snapshot 登记到最小 `artifact_manifest.jsonl`；查询使用各自独立的回执目录，不再追加该账本；
- 保存查询写在 Snapshot 外部，不修改 DuckDB 文件。

源 SHA-256 用于 inspect/ingest 的 manifest 绑定和 Snapshot/Artifact manifest。它不需要成为每次查询、Session 或交付物都传播的公共身份字段。

这组能力不是完整 Run/Artifact 平台。所有 Sheet 按实际表头名进入 landing，`ingest.sheets.target_table` 给出实际关系名。业务表头、字段含义和清洗口径必须从 Company Bridge 获取，不能在 Data Platform 中硬编码。

### 2.1 公共证据合同（查询与自由分析已实现）

合同区分查询回执、文件身份、业务交付清单，完整字段责任与样例见 [公共证据合同](./evidence-contract.md)。该文档本轮未加入 Project Intelligence 读取白名单；通过本节仍可获取关键边界，未扩大只读服务权限。

- 当前 `controlled_query_result.v2`：成功查询始终保存 SQL、参数、完整结果和 `query_receipt.v1`；stdout 提供回执文件身份，小结果另有内联副本。读取使用 `read_query_result` 验证证据；看板与监控仍保留各自最终业务 artifact。
- 每次成功查询都保存实际 SQL、参数、完整结果与可验证回执；run/Snapshot、独立执行身份、时间/生产版本、来源与文件 SHA-256 必须可追溯。数据层不承担 Pack/Bridge/metric 语义。
- 业务清单由宿主/产品生成，绑定所选工作区配置和实际仓库/Snapshot 来源、角色、Pack/Bridge，引用同 Snapshot 的一份或多份子查询及交付文件；不能只凭同名 Snapshot 或自填公司字段接受外来证据。正式指标定义沿用 Pack.metrics；当前交付包的 metric_refs 为空，指标执行关联不排期，待具体口径问题证明需要后再评估。
- 文件路径限制在显式证据包根内；Casebook 复制明确选择的最小引用闭包并保留包内相对目录，复制后重验，删源后仍可验证。新写入不沿用扁平复制回执而丢失内部引用；已封存案例不回写，不能宣称旧证据已满足新协议。
- 看板、监控、市场 CLI 已使用新查询校验读取；看板与监控最终产物保持现状，原定统一改造已取消。现有查询证据校验保留，不增加兼容运行分支。

确定性组包 API 为 `workspace_modeling.delivery.create_delivery`；完整可调用示例见 [公共证据合同第 7 节](./evidence-contract.md#7-宿主确定性组包-api)。Bridge 的 `--snapshot-quality` 指向实际 quality 查询回执文件，而非 stdout JSON。

## 3. Agent Host 接入

CLI 是宿主无关边界。Codex、DeepSeek Harness 和其他具备受控 Shell 的 Agent Host 都在项目工作区直接执行：

```bash
python3 -m interfaces.data_platform <command> ...
```

宿主侧只需要：

- 把项目目录设置为受控工作区；
- 使用宿主原生 Agent、模型、Session 和工具系统；
- 允许调用项目 Python 环境和 Data Platform CLI；
- 用 Skill 或项目说明告诉模型子命令、参数和输出约定；
- 读取 stdout JSON、进程退出码和显式产物路径；
- 把 API Key、客户路径和源数据留在机器或客户工作区，不提交仓库。

当前业务操作使用 CLI，不要求不同宿主安装同一协议插件，也不把 Codex 或 DeepSeek Harness 再封装成项目内 Agent。已存在的 Project Intelligence stdio MCP 只读项目上下文，不开放业务 SQL。Business MCP 后置评估，必须复用工作区/语义检查与 Data Platform 受控入口，不直连 DuckDB。

### Codex

Codex 已通过项目 Shell 完成 CLI 命令链和错误处理验证，不增加新的数据服务。日常直接在对应客户工作区调用同一 CLI；换公司或角色时使用 Codex 原生新任务/记忆清理并切换工作区。

### DeepSeek Harness

计划链路为：

```text
DeepSeek Harness → controlled shell → Python CLI → Data Platform
```

Harness 全局安装、Web、真实模型回合、项目 Workspace、受控 Shell、真实三表 `inspect → ingest → describe → quality → query`、项目 Skill `diagnose-source-overlap` 调用，以及三张真实教务表的陌生结构识别、Bridge 生成、教师课量查询和图表输出均已通过。主线现金明细与工单分析、可打开 PPTX 生成及渲染回查也已通过。该流程直接使用 Harness 原生 Agent，不依赖正式 `CandidateAdapter`。

### 重叠与清洗

同一端口全量文件更新时替换同一 `Input/Data/<source_id>` 当前文件并发布新 Snapshot，不跨 Snapshot 合并。当前 Snapshot 内多来源可能重叠时，宿主使用项目 Skill `diagnose-source-overlap`，通过现有 `describe/query` 自主检查日期范围、候选业务键、重复和冲突；客户确认业务键与来源优先级后，再用 `promote-query` / `run-saved-query` 固化只读 SQL。该逻辑不进入 Bridge，也不修改 landing。

## 4. Education Business Pack

首版 Pack 可通过同一 Python 环境调用：

```bash
python3 -m interfaces.business_pack validate
python3 -m interfaces.business_pack describe
```

`validate` 校验 manifest schema、稳定 ID、重复项以及概念、指标、维度、旅程、漏斗和 Playbook 的交叉引用；失败返回结构化 JSON 和非零退出码。`describe` 返回版本、范围和精简清单，不展开全部知识正文。两条命令都可用 `--pack PATH` 指向待校验的 Pack。

内置 Pack 为 `education_training_operations_cn` v1.0.0。它不接收 `snapshot_id`，也不包含当前企业字段、枚举、SQL 或清洗选择。

## 5. Company Bridge

Company Bridge 通过同一 Python 环境调用：

```bash
python3 -m interfaces.company_bridge --help
python3 -m interfaces.company_bridge validate-candidates \
  --input /path/to/confirmed_candidates.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json \
  --require-role confirmed_review
python3 -m interfaces.company_bridge validate \
  --bridge /absolute/path/to/confirmed-workspace-bridge.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
```

当前 BI 工作区正式 Bridge 为 `bridge_bi_operations` v1.2.0。它引用当前 `landing.*` 关系，直接使用源表头名定位字段；具体运行时可额外传入同一 Snapshot 的 `--snapshot-description` 与 `--snapshot-quality` 做兼容性校验。

历史扫描使用 `scan-history`，但输出角色是 `historical_scan`，不能直接构建正式 Bridge。只有人工复核后的 `confirmed_review` 可以传给 `build`；未确认项必须保留为 `unresolved` 或拒收，不能静默选择。完整合同见 [Company Bridge v1 合同](./company-bridge-contract.md)。

## 6. Bridge 对齐向导

首次部署优先使用上面的 `workspace-modeling` 入口：用户只需选择业务端口，工作区路径会自动生成内部 `company_id`。下面是需要直接编排 Bridge 向导时的低层 CLI 示例，其中 `--company-id` 仅是机器身份字段，不是用户需要填写的公司名称。

公开入口：

```bash
python3 -m interfaces.bridge_alignment --help
python3 -m interfaces.bridge_alignment init \
  --workspace customers/company_customer \
  --company-id company_customer \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
python3 -m interfaces.bridge_alignment sync-data \
  --workspace customers/company_customer \
  --snapshot-id snapshot_customer_2026_08
```

`init` 创建 `Input/Work/Output`，并把 Pack 与可选同公司 Bridge 复制进工作区。客户把当前文件分别放进 `Input/Data/<source_id>/`；每个稳定来源槽位只放一个 XLSX/XLSM。七月换八月时直接替换当前文件，再用新的显式 `snapshot_id` 执行 `sync-data`；向导先发布并切换新 Snapshot，再删除旧 Snapshot，工作区只保留当前 Snapshot。导入失败或当前 Snapshot 尚有未完成会话时不会切换。

`start` 从当前 Snapshot 建立一个对齐会话目录及其 `session.json`；同公司的旧 Bridge 仅作为企业口径参考，不代表已适配当前 Snapshot。宿主原生 Agent 负责读取画像、调用自己的模型、向客户提问，并通过 CLI 提交确定性决定与 `finalize`。现有 `propose --adapter module:attribute` 是程序化候选注入入口，供合同测试或批处理集成使用；它不是需要建设的 Harness/Codex Adapter 服务。`add-evidence` 把 U 盘/目录资料复制进 `Input/Reference`；`finalize` 写入 `Output/Bridge/<version>`。新公司不得传上一家 Bridge。

CLI 完成当前阶段且无需客户输入时退出 `0`，等待确认或被关键问题阻断时退出 `2`，合同、身份、候选注入、文件或验证错误退出 `1`。stdout JSON 是宿主机器接口，客户不需要查看或编写。测试 fake adapter 只验证模型候选合同；生产运行由当前宿主原生 Agent 主控。精确合同见 [Bridge 对齐向导 v1 合同](./bridge-alignment-wizard-contract.md)。

## 7. Casebook、内测回收与引导路由（S5 已实现）

S5 通过单一宿主无关 CLI 提供 Casebook、内测评价与本地引导：

```bash
python3 -m interfaces.casebook --help
python3 -m interfaces.casebook guide --workspace customers/company_customer
```

`runs/` 保持本地原始证据，不能作为长期记忆被整目录读取或自动上传。Casebook 使用 `case-create` 逐项指定证据，或使用 `case-capture --manifest Work/analysis_capture.json` 读取一个由宿主 Agent 明确整理的 `casebook_capture.v2` manifest；确认后用 `case-confirm`，检索使用 `case-search`。两种入口都复制最小查询证据、SQL、哈希、版本和限制，后续只能在同一客户与角色范围内检索；涉及当前事实时仍须查询当前 Snapshot。`case-verify` 校验归档引用闭包及封存身份，删除原运行目录后仍可验证。

本地部署的内测用户用 `test-pack-import`、`evaluation-start`、`evaluation-record-card` 和 `evaluation-complete` 执行版本化测试包，主动用 `feedback-export --export-type metrics-only` 导出默认脱敏反馈；用户可用 `evaluation-attach-evidence` 显式选择附加证据，再导出 `evidence-approved`。`feedback-verify` 只校验 ZIP 清单和哈希，不联网。项目不自动上传客户工作簿、DuckDB、Parquet 或 `runs/`。引导路由只提示工作区初始化、数据同步、Bridge 对齐、分析或 `repeat-candidates` 候选沉淀，既不取代宿主 Session，也不自动发布 Skill。实现接口与目录合同以 [S5 合同](./casebook-pilot-contract.md) 为准。

已完成 Bridge 对齐后，宿主 Agent 可使用项目级 [业务分析路由 Skill](../.agents/skills/business-analysis-routing/SKILL.md) 处理日常问题。它只规定最小调用顺序：先用 `guide` 检查当前工作区状态，再按角色/问题类别用 `case-search` 找同公司确认案例；案例只提供方法线索，当前数字必须通过 Data Platform 以显式 `snapshot_id`、`run_id` 的只读 `describe`/`quality`/`query`（或确认后的 `run-saved-query`）重新取得。用户明确验收后才用 `case-create` 保存 candidate，交付物需回查本次查询；保存时逐项核对交付清单与当前工作区 Snapshot/Pack/Bridge 身份，`casebook_capture.v2` manifest 不重复传入这些字段；`repeat-candidates` 只提出人工审核候选，不自动生成或发布 Skill。该 Skill 不实现 Agent Loop、Session、SQL 编译器或额外存储。

## 8. 宿主交付能力

项目不新增通用输出平台，也不内置 PPT Master。电子表格和数据可视化先使用宿主原生能力；PPTX 由宿主全局 `ppt-master` Skill 负责，项目不固化 Quick/Default 分流。

自由分析将当前 Snapshot 的受控查询结果、分析结论、口径、时间范围、来源和限制作为 PPT 输入。全局 Skill 按它的当前路由规则选择 Quick 或 Default；项目不复制其 SVG、模板、Renderer、依赖或质量门禁。无论选择哪种模式，交付文件都必须可打开、内容非空，关键数字能回查到同一受控查询。全局 Skill 不可用时，只阻断 PPT 交付，不使已完成的分析或证据失效。

## 9. 固定看板与钉钉

看板不是 Data Platform 新 CLI，而是模块入口：

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/bi_operations --run-id run_dashboard_<id>
python3 -m dashboard_product.refresh render --artifact <artifact.json> --all-booklets
python3 -m monitoring_product.notify send --workspace <workspace> --snapshot-id <snapshot_id> --run-id <run_id> --as-of-date <YYYY-MM-DD> --data-through-date <YYYY-MM-DD> --dry-run
```

刷新只消费已确认 `dashboard_actuals/v10`。目标区留学预备/高中/大学，同比区青少/初中/高中/大学。全量页另有「市场人员产能」页签。四分册发布和 Nginx 门口见 [`dashboard_product/DEPLOYMENT.md`](../dashboard_product/DEPLOYMENT.md)。Webhook 属于 C 层，不在本接入指南展开。
