# 核心 CLI 接入指南

## 1. 当前公开入口

Data Foundation 的公开入口是 Python CLI：

```bash
python3 -m interfaces.data_foundation --help
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
python3 -m interfaces.data_foundation inspect --help
python3 -m interfaces.data_foundation ingest --help
python3 -m interfaces.data_foundation query --help
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

这组能力不是完整 Run/Artifact 平台。所有 Sheet 进入 `landing.column_N`；`ingest.sheets.target_table` 给出实际关系名。业务表头、字段含义和清洗口径必须从 Company Bridge 获取，不能在 Data Foundation 中硬编码。

## 3. Agent Host 接入

CLI 是宿主无关边界。Codex、DeepSeek Harness 和其他具备受控 Shell 的 Agent Host 都在项目工作区直接执行：

```bash
python3 -m interfaces.data_foundation <command> ...
```

宿主侧只需要：

- 把项目目录设置为受控工作区；
- 允许调用项目 Python 环境和 Data Foundation CLI；
- 用 Skill 或项目说明告诉模型子命令、参数和输出约定；
- 读取 stdout JSON、进程退出码和显式产物路径；
- 把 API Key、客户路径和源数据留在机器或客户工作区，不提交仓库。

不建设 MCP Server，也不要求不同宿主安装同一协议插件。若未来出现不能调用 Shell 的真实宿主，再根据该消费者的实际限制评估最薄适配器。

### Codex

Codex 可以通过项目 Shell 直接调用上述命令。Stage 1 需要用现有小型 fixture 验证完整命令链和错误处理，不增加新的数据服务。

### DeepSeek Harness

计划链路为：

```text
DeepSeek Harness → controlled shell → Python CLI → Data Foundation
```

Harness 全局安装、Web、真实模型回合、项目 Workspace、受控 Shell、真实三表 `inspect → ingest → describe → quality → query` 和项目 Skill `diagnose-source-overlap` 调用已通过。Session 恢复及 Deliverables 仍待验收。

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
  --input artifacts/company_bridge/reviewed/super_agent_confirmed_review_20260816_v3.json \
  --pack business_pack/packs/education_training_operations_cn/pack.json \
  --require-role confirmed_review
python3 -m interfaces.company_bridge validate \
  --bridge artifacts/company_bridge/bridges/company_bridge.v1_2_0.json \
  --pack business_pack/packs/education_training_operations_cn/pack.json
```

当前正式 Bridge 为 1.2.0。它引用 Data Foundation v2 的 `landing.*` 关系和 `column_N`，不绑定某个 Snapshot；具体运行时可额外传入同一 Snapshot 的 `--snapshot-description` 与 `--snapshot-quality` 做兼容性校验。

历史扫描使用 `scan-history`，但输出角色是 `historical_scan`，不能直接构建正式 Bridge。只有人工复核后的 `confirmed_review` 可以传给 `build`；未确认项必须保留为 `unresolved` 或拒收，不能静默选择。完整合同见 [Company Bridge v1 合同](./company-bridge-contract.md)。

## 6. Bridge 对齐向导

公开入口：

```bash
python3 -m interfaces.bridge_alignment_wizard --help
python3 -m interfaces.bridge_alignment_wizard init \
  --workspace customers/company_customer \
  --company-id company_customer \
  --pack business_pack/packs/education_training_operations_cn/pack.json
python3 -m interfaces.bridge_alignment_wizard sync-data \
  --workspace customers/company_customer \
  --snapshot-id snapshot_customer_2026_08
```

`init` 创建 `Input/Work/Output`，并把 Pack 与可选同公司 Bridge 复制进工作区。客户把当前文件分别放进 `Input/Data/<source_id>/`；每个稳定来源槽位只放一个 XLSX/XLSM。七月换八月时直接替换当前文件，再用新的显式 `snapshot_id` 执行 `sync-data`；旧 Snapshot 保留，工作区当前指针更新。

`start` 从当前 Snapshot 建立单一 `session.json`；`propose --adapter module:attribute` 调用宿主注入的 `CandidateAdapter`；宿主理解客户自由回答后，通过 `answer` 传 `candidate_key`、`option_id`、原回答和确认人；`add-evidence` 把 U 盘/目录资料复制进 `Input/Reference`；`finalize` 写入 `Output/Bridge/<version>`。新公司不得传上一家 Bridge。

CLI 完成当前阶段且无需客户输入时退出 `0`，等待确认或被关键问题阻断时退出 `2`，合同/身份/adapter/文件错误退出 `1`。stdout JSON 是宿主机器接口，客户不需要查看或编写。当前项目只提供 adapter 协议和测试 fake adapter，未把 DeepSeek Harness SDK 写入核心，也尚未提供正式宿主 adapter。精确合同见 [Bridge 对齐向导 v1 合同](./bridge-alignment-wizard-contract.md)。
