# Data Foundation 接入指南

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

- `inspect` 输出 schema `data_foundation_inspection.v1`；
- `ingest` 输出 schema `data_foundation_ingest.v1`；
- `inspect`、`ingest`、`quality`、`query` 和 `run-saved-query` 要求显式 `run_id`；`describe` 与 `promote-query` 按当前 CLI 参数不要求 `run_id`；
- Snapshot 发布后不可原地覆盖；
- 查询拒绝写操作、外部 reader、系统目录和绕过形式；
- 查询限制最大返回行数和结果字节数；
- 大查询结果和 Snapshot 登记到最小 `artifact_manifest.jsonl`；
- 保存查询写在 Snapshot 外部，不修改 DuckDB 文件。

源 SHA-256 用于 inspect/ingest 的 manifest 绑定和 Snapshot/Artifact manifest。它不需要成为每次查询、Session 或交付物都传播的公共身份字段。

这组能力不是完整 Run/Artifact 平台。当前代码仍有为已确认脏数据语料建立的特定源表映射和 `semantic.registration_cash` 视图；不要把它误认为完整 Education Pack 或企业语义层。

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

Harness 全局安装、Web、真实模型回合、项目 Workspace、受控 Shell 和 Data Foundation 顶层 `--help` 已通过。完整数据链路、Session 恢复及 Deliverables 仍待验收。

## 4. Education Business Pack

首版 Pack 可通过同一 Python 环境调用：

```bash
python3 -m interfaces.business_pack validate
python3 -m interfaces.business_pack describe
```

`validate` 校验 manifest schema、稳定 ID、重复项以及概念、指标、维度、旅程、漏斗和 Playbook 的交叉引用；失败返回结构化 JSON 和非零退出码。`describe` 返回版本、范围和精简清单，不展开全部知识正文。两条命令都可用 `--pack PATH` 指向待校验的 Pack。

内置 Pack 为 `education_training_operations_cn` v1.0.0。它不接收 `snapshot_id`，也不包含当前企业字段、枚举、SQL 或清洗选择。

## 5. Bridge 的未来接入

Bridge 将提供独立版本化 manifest。调用时先选择 Customer Profile，再冻结 `snapshot_id`、Pack version 和 Bridge version。未确认 Bridge 项必须显式返回，不允许工具静默选择字段或枚举。
