# Data Foundation 接入指南

## 1. 当前公开入口

当前唯一已实现入口是 Python CLI：

```bash
python3 -m interfaces.data_foundation --help
```

已实现子命令：

| 命令 | 能力 |
|---|---|
| `inspect` | 可选诊断：根据 manifest 探查 XLSX 与候选表头，不输出完整明细 |
| `ingest` | 无计划直接发布每 Sheet landing DuckDB/Parquet Snapshot |
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
- `ingest` 输出 schema `data_foundation_ingest.v2`，Snapshot manifest 使用 `warehouse_snapshot.v2`；
- `inspect`、`ingest`、`quality`、`query` 和 `run-saved-query` 要求显式 `run_id`；`describe` 与 `promote-query` 按当前 CLI 参数不要求 `run_id`；
- ingest 不接收 cleaning plan，也不要求先运行 inspect；
- landing 保留源单元格值；Python 不决定空格、编号、数字、日期或文本类型；
- 模型入仓后自主生成 `TRIM`、`TRY_CAST`、日期解析等受控 SQL；存在合理歧义或需要长期固化时再请求人工确认并进入 Bridge；
- 每个 Sheet 自动生成 `landing.<target_table>`，列名固定为 `column_1...column_N`，表头/标题也作为源行保留；
- `ingest.sheets` 保存 `source_id`、`sheet_name`、`target_table`、`landing_rows` 和物理结构，宿主入仓后再查询前几行；
- Snapshot 发布后不可原地覆盖；
- 查询拒绝写操作、外部 reader、系统目录和绕过形式；
- 查询限制最大返回行数和结果字节数；
- 大查询结果和 Snapshot 登记到最小 `artifact_manifest.jsonl`；
- 保存查询写在 Snapshot 外部，不修改 DuckDB 文件。

源 SHA-256 用于 inspect/ingest 的 manifest 绑定和 Snapshot/Artifact manifest。它不需要成为每次查询、Session 或交付物都传播的公共身份字段。

这组能力不是完整 Run/Artifact 平台，也不是教育语义层。Data Foundation 已删除特定源表映射和 `semantic.registration_cash`；字段含义、表头选择、类型解释和企业口径必须在入仓后的受控 SQL、Pack 与 Bridge 中处理。

最小直接入仓调用：

```bash
python3 -m interfaces.data_foundation ingest \
  --run-id run_example_001 \
  --snapshot-id snapshot_example_001 \
  --output-root /explicit/workspace/runs \
  --manifest /explicit/workspace/source_manifest.json \
  --source department_export=/explicit/input/department.xlsx
```

入仓后先查询映射，不猜表名：

```sql
SELECT source_id, sheet_name, target_table, landing_rows
FROM ingest.sheets
ORDER BY source_id, sheet_name;
```

再通过 `query --sql-file` 执行 `SELECT * FROM landing.<target_table> ORDER BY source_row_number LIMIT 20`，由宿主在仓内识别标题行、表头和类型。所有正式查询仍受单 SELECT、schema 白名单和结果规模限制。

## 3. Agent Host 接入

CLI 是宿主无关边界，项目不指定默认宿主。任一 Agent Host 满足下列条件即可把本项目目录作为受控工作区：

- 能调用本地受控 Shell 和 Python；
- 能传入显式文件路径并读取 stdout JSON、退出码和产物；
- 能在需要时向用户请求确认；
- 不要求把业务代码复制到宿主安装目录。

满足条件的宿主直接执行：

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

### 当前兼容状态

| 宿主 | 当前状态 | 核心差异 |
|---|---|---|
| Codex | 可直接调用同一 CLI，已用于代码、测试和产物核验 | 使用 Codex 自身的权限、Session 和文件展示 |
| DeepSeek Harness `0.1.0-rc.6` | 已完成真实 headless Data Foundation 端到端调用 | Conversation Node、交互表格等为可选增强 |
| Hermes | 结构上兼容受控 Shell/CLI 边界，尚未做本项目真实验收 | 验收前不宣称 Session、权限或交付体验等价 |

“核心无损”指 Data Foundation、DuckDB 计算、Pack/Bridge、Analysis Contract/Evidence Gate、静态文件输出和长期质量资产可以复用；不承诺不同宿主的交互 UI、Session 行为、审批和文件展示完全一致。

### Codex

Codex 通过项目 Shell 直接调用上述命令，不增加新的数据服务。运行产物仍写入客户或任务的显式工作目录，不写入 Codex 安装目录。

### DeepSeek Harness

计划链路为：

```text
DeepSeek Harness → controlled shell → Python CLI → Data Foundation
```

真实 headless 模型已通过 Shell 完成一次无 inspect、无 cleaning plan 的跨部门直接 landing：3 个真实 XLSX、6 个 Sheet、47,087 个有内容行全部入仓；模型随后通过项目 query CLI 查看前五行，自主识别表头、转换数值并汇总四张排课表。Harness 自身聊天、Session 和 Deliverables 基础能力不属于本项目 Data Foundation 验收范围。

### Hermes 与其他宿主

接入时先验证 `--help → ingest → describe → query` 和显式路径/退出码合同；通过后即可消费同一项目目录。不要在验证前复制 Python 核心、增加兼容协议或宣称宿主专属交互能力已经可用。

## 4. Pack、Bridge 与 Analysis Contract 的未来接入

Pack 与 Bridge 将分别提供版本化 manifest。调用时先选择 Customer Profile，再冻结 `snapshot_id`、Pack version、Bridge version 和 Analysis Contract version。未确认 Bridge 项必须显式返回，不允许工具静默选择字段或枚举。

Pack/Bridge 稳定后增加宿主无关的 Analysis Record 和 Evidence Gate。模型提交结构化结论、查询/结果引用、口径引用、假设和限制；门禁返回 `supported`、`conditional` 或 `blocked`。宿主最终回答和 Renderer 不得把 `blocked` 结论包装成正式事实。

计划中的最小引用合同：

- `snapshot_id`；
- Analysis Contract ID 和版本；
- Pack/Bridge ID、版本及所用 metric/mapping 引用；
- 保存查询 ID 或 SQL 文件哈希；
- Artifact ID 或规范化内联结果摘要；
- `claim_id`、结论、方法、替代解释、正反证据、假设、限制和门禁状态。

这不是原始思考链存储。宿主无需暴露模型私有推理，只需提交可复核的分析摘要和证据绑定。
