# 核心 CLI 接入指南

## 1. 当前公开入口

### 1.1 安装

发布包按能力提供依赖集合：

```bash
python3 -m pip install "data-oxhor[full]"
```

`core` 只安装数据分析运行时，`test` 是最小基础测试依赖；`tools/install_runtime.sh test` 会组合安装 `test + ppt`，因此包含 S4 的 `skia-pathops` 与 `uharfbuzz`；`ppt` 增加 Quick PPT 所需组件，`full` 覆盖当前项目的 Python 能力。源码用户可执行 `sh tools/install_runtime.sh test` 或 `sh tools/install_runtime.sh full`；不建议在系统 Python 中逐项安装。DeepSeek Harness、Office/字体和模型凭据仍属于宿主环境，不由 Python wheel 管理。

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

| 命令 | 能力 |
|---|---|
| `inspect` | 根据 manifest 探查 XLSX，不输出明细行 |
| `ingest` | 发布不可变 DuckDB/Parquet Snapshot |
| `describe` | 描述 Snapshot 的 schema、表和字段 |
| `quality` | 查询已登记的数据质量问题 |
| `query` | 执行受控只读 SQL |
| `promote-query` | 经确认后登记保存查询 |
| `run-saved-query` | 执行已登记的保存查询 |

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
- 大查询结果和 Snapshot 登记到最小 `artifact_manifest.jsonl`；
- 保存查询写在 Snapshot 外部，不修改 DuckDB 文件。

源 SHA-256 用于 inspect/ingest 的 manifest 绑定和 Snapshot/Artifact manifest。它不需要成为每次查询、Session 或交付物都传播的公共身份字段。

这组能力不是完整 Run/Artifact 平台。所有 Sheet 按实际表头名进入 landing，`ingest.sheets.target_table` 给出实际关系名。业务表头、字段含义和清洗口径必须从 Company Bridge 获取，不能在 Data Platform 中硬编码。

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

不建设 MCP Server，不要求不同宿主安装同一协议插件，也不把 Codex 或 DeepSeek Harness 再封装成项目内 Agent。若未来出现不能调用 Shell 的真实宿主，再根据该消费者的实际限制评估最薄调用适配器。

### Codex

Codex 已通过项目 Shell 完成 CLI 命令链和错误处理验证，不增加新的数据服务。日常直接在对应客户工作区调用同一 CLI；换公司或角色时使用 Codex 原生新任务/记忆清理并切换工作区。

### DeepSeek Harness

计划链路为：

```text
DeepSeek Harness → controlled shell → Python CLI → Data Platform
```

Harness 全局安装、Web、真实模型回合、项目 Workspace、受控 Shell、真实三表 `inspect → ingest → describe → quality → query`、项目 Skill `diagnose-source-overlap` 调用，以及三张真实教务表的陌生结构识别、Bridge 生成、教师课量查询和图表输出均已通过。主线现金明细与工单分析、可打开 PPTX 生成及渲染回查也已通过；当前仅以新版冻结身份协议做 Quick 性能回归。该流程直接使用 Harness 原生 Agent，不依赖正式 `CandidateAdapter`。

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
  --bridge artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_1_0.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
```

当前 BI 工作区正式 Bridge 为 `bridge_bi_operations` v1.0.0。它引用当前 `landing.*` 关系，直接使用源表头名定位字段；具体运行时可额外传入同一 Snapshot 的 `--snapshot-description` 与 `--snapshot-quality` 做兼容性校验。

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

`runs/` 保持本地原始证据，不能作为长期记忆被整目录读取或自动上传。Casebook 使用 `case-create` 逐项指定证据，或使用 `case-capture --manifest Work/analysis_capture.json` 读取一个由宿主 Agent 明确整理的 `casebook_capture.v1` manifest；确认后用 `case-confirm`，检索使用 `case-search`。两种入口都复制最小查询证据、SQL、哈希、版本和限制，后续只能在同一客户与角色范围内检索；涉及当前事实时仍须查询当前 Snapshot。`case-verify` 可重算摘要和证据哈希。

本地部署的内测用户用 `test-pack-import`、`evaluation-start`、`evaluation-record-card` 和 `evaluation-complete` 执行版本化测试包，主动用 `feedback-export --export-type metrics-only` 导出默认脱敏反馈；用户可用 `evaluation-attach-evidence` 显式选择附加证据，再导出 `evidence-approved`。`feedback-verify` 只校验 ZIP 清单和哈希，不联网。项目不自动上传客户工作簿、DuckDB、Parquet 或 `runs/`。引导路由只提示工作区初始化、数据同步、Bridge 对齐、分析或 `repeat-candidates` 候选沉淀，既不取代宿主 Session，也不自动发布 Skill。实现接口与目录合同以 [S5 合同](./casebook-pilot-contract.md) 为准。

已完成 Bridge 对齐后，宿主 Agent 可使用项目级 [业务分析路由 Skill](../.agents/skills/business-analysis-routing/SKILL.md) 处理日常问题。它只规定最小调用顺序：先用 `guide` 检查当前工作区状态，再按角色/问题类别用 `case-search` 找同公司确认案例；案例只提供方法线索，当前数字必须通过 Data Platform 以显式 `snapshot_id`、`run_id` 的只读 `describe`/`quality`/`query`（或确认后的 `run-saved-query`）重新取得。用户明确验收后才用 `case-create` 保存 candidate，交付物需回查本次查询；保存时的 Snapshot/Pack/Bridge 身份由当前工作区自动绑定，`casebook_capture.v1` manifest 不重复传入这些字段；`repeat-candidates` 只提出人工审核候选，不自动生成或发布 Skill。该 Skill 不实现 Agent Loop、Session、SQL 编译器或额外存储。

## 8. 项目级交付 Skills（S4）

S4 不新增业务 CLI 或输出平台。项目已将上游 `hugohe3/ppt-master` v4.7.0（提交 `e8323bfaee249cffe1301ec40fca5875eb544d46`）固定版本装配到 `.agents/skills/ppt-master`，MIT 许可证、发布包 SHA-256 和树摘要见 `.agents/skills/ppt-master.upstream.json`；离线检查会执行其 `scripts/attribution_guard.py`。电子表格和数据可视化先使用宿主原生能力，不增加项目依赖。项目只增加 `analysis_product/s4_ppt_quick.py` 作为宿主无关的 Quick 编排入口，不复制 PPT Master 的 SVG、模板或 Renderer 实现。

宿主通过自然语言需求决定直接回答、表格/查询结果或 PPTX，PPT 不采用固定月报结构或页序。分析已冻结且没有复杂交付要求时，Codex 与 DeepSeek Harness 都使用 [S4 Quick PPT 宿主提示词](./s4-ppt-quick-prompt.md) 和同一 `quick-ppt prepare/finalize` 入口；冻结清单以 Snapshot、SHA-256 与由受控查询真实写入的 `referenced_source_ids` 约束可用查询证据，入口会复核导入副本，不接受 manifest 自报的来源作为唯一凭据。当前 BI 主线使用 `bridge_bi_operations`，包含现金明细与工单来源；历史 Bridge 和教务验收不属于当前交付输入。模板、人工确认、图片、预览、讲稿、旁白或复杂动画才进入 PPT Master Default。首轮验收只使用本地数据和原生可编辑 PPTX，关闭自动更新、外部研究、生图、TTS、旁白和本地 Web 辅助界面。缺少工作时间、请假和通勤规则时，当前未占用只能称“候选空档”。文件必须可打开、内容非空且关键数字可回查到同一只读查询结果。
