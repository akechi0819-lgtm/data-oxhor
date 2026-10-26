# 公共证据合同

2026-09-18。第 2 轮已实现查询与自由分析证据闭环。原定看板、监控最终产物统一改造已取消；两者保留现有业务产物结构和已接入的查询回执校验。能力入口见 [集成指南](./integration-guide.md)。

## 1. 三类对象与模块归属

- **查询回执**记录一次实际执行：身份、SQL、参数、结果、来源及执行约束。Data Platform 生产和校验，不解释企业口径。成功的小结果和大结果都保存完整证据；stdout 的内联数据只是读取便利，不是唯一证据。
- **文件身份**记录一个具体文件的不可变字节、相对路径和摘要。文件生产模块负责生成；读取者先检查路径、大小、哈希。文件内容相同不代表来自同一次运行，不能只用内容哈希充当身份。
- **业务交付清单**由自由分析宿主调用组包 API 生成，关联业务上下文、交付文件及一份或多份查询回执；本合同不要求看板和监控改造各自最终产物。它不是查询回执，也不替代 Casebook 案例状态。

不建设统一注册中心、目录扫描器、调度或通用渲染服务。现有 Snapshot 的 `artifact_manifest.jsonl` 不因此改造成全局账本。证据有效性只证明文件与执行上下文关联完整，不自动证明业务结论正确。

## 2. 字段与责任

以下为查询与自由分析的当前运行合同。协议为 `query_receipt.v1`、`business_delivery.v1`；查询 CLI 返回升级为 `controlled_query_result.v2`。文件引用为嵌入对象，不另建文件协议。下列业务清单字段描述已实现的自由分析交付包；看板和监控只复用查询证据读取，不升级最终产物 schema，也不要求嵌入这些业务字段。

| 字段 | 必填层级与含义 | 生产者 | 消费者与校验职责 |
|---|---|---|---|
| `schema_version` | 每种回执/业务清单必填；标识该文档协议 | 所属模块 | 读取者拒绝未知运行协议，不增加旧版回退 |
| `evidence_id` | 每次查询执行必填，独立于内容摘要 | Data Platform | 业务生产者、Casebook 检查唯一引用与身份一致性 |
| `artifact_id` | 每个交付文件必填，独立于内容摘要 | 文件生产者 | 清单读取者检查重复/冲突，不能跨运行按内容去重身份 |
| `run_id`、`snapshot_id` | 查询回执、业务清单必填；业务产物可引用同 Snapshot 的多个子查询 run | 查询调用方显式提供；业务生产者组织父 run | Data Platform 检查仓库 Snapshot；业务生产者与 Casebook 检查所有引用 Snapshot 相同，保留各子 run，不强迫等于父 run |
| `created_at`、`producer` | 回执与业务清单必填；UTC 时间；producer 为 `{name, version}`，可选 `revision` | 项目模块 version 取安装包 data-oxhor 元数据；源码使用同一 pyproject 版本；宿主交付由生成程序显式声明名称/版本，不推断模型版本 | 读取者校验非空和格式；缺少生产版本拒收，不能写 unknown 冒充版本 |
| `kind`、`media_type` | 回执 kind 为 `query`，自由分析清单 kind 为 `analysis`；每个文件引用必填 IANA media_type | 所属生产者 | 消费者按类型选择读取/验证，禁止把回执当交付文件 |
| `snapshot_ref` | 查询回执必填 `{snapshot_id, manifest_sha256, warehouse_sha256}`；manifest_sha256 对本次读取的 manifest 字节计算，warehouse_sha256 是 manifest 登记的发布时摘要，不代表本次重算 | Data Platform 从传入 warehouse 的同目录 snapshot_manifest.json 读取并校验身份、登记路径/大小和仓库 Snapshot | 业务层比对所选工作区指向的 manifest；Casebook 保存前比对，归档后验证封存身份而不读取当前数仓 |
| `path`、`sha256`、`size_bytes` | 每个文件引用必填；路径仅定位，哈希指实际文件字节 | 文件生产者 | 每个消费者按第 4 节解析并重算，不能仅相信文件存在 |
| `sql`、`parameters`、`result` | 查询回执必填的文件引用，分别指实际执行 SQL、参数 JSON、完整结果 JSON | Data Platform | Data Platform 写后验证；业务生产者与 Casebook 在使用/复制时检查三个摘要及结果行列完整性 |
| `saved_query_ref` | 使用保存查询时必填 `query_id`、`version`；临时查询不填 | Data Platform 的 run-saved-query | 执行前校验登记 SQL 哈希；回执仍保存实际 SQL，归档后不依赖原 registry |
| `row_count`、`columns`、`limits` | 查询回执必填；limits 含本次行数、字节上限 | Data Platform | 读取者校验完整结果与回执相符；超限失败不得伪装为完整截断结果 |
| `referenced_relations`、`referenced_source_ids` | 查询回执必填数组；沿用 ingest.sheets 物理来源规则，合法无 landing 查询可为空 | Data Platform | 执行时反查来源；业务清单不得手写替换来源；不是完整 SQL 血缘承诺 |
| `workspace_ref` | 业务清单必填，引用受选定 `Work/workspace.json` 管理的工作区身份，至少含 `company_id`；物理路径不是身份 | 工作区调用层读取配置 | 业务生产者与 Casebook 检查选定工作区、仓库指针、Snapshot 匹配；纯数据 CLI 不强制新增公司字段 |
| `primary_role`、`pack_ref`、`bridge_ref` | 企业分析清单必填；沿用 Pack/Bridge 既有 ID、版本字段 | 业务生产者读取工作区与已确认 Bridge | 业务层检查公司、Pack/Bridge 兼容及角色；Casebook 核对当前保存上下文，禁止用当前身份重贴历史证据 |
| `metric_refs` | 当前必须为空数组；不宣称已验证指标执行关联 | 自由分析组包 API；指标定义权威仍为 Pack.metrics | 校验器拒绝非空引用；执行关联待实际口径问题证明需要后再评估，Data Platform 不做指标编译 |
| `query_refs`、`files` | 业务清单必填非空数组；查询引用包含 evidence_id 及回执文件身份，files 为交付文件身份 | 业务生产者 | 交付前及 Casebook 保存/验证时验证引用闭包、上下文一致性和字节摘要 |

工作区绑定不依赖新增全局 workspace registry：公司身份不足以区分同公司不同物理工作区，保存时必须同时验证所选配置文件、当前仓库指针和显式 Snapshot。查询回执归入该工作区的受控执行输出后，业务层才可把它绑定为该工作区证据；不得仅凭同名 snapshot_id 接受外来回执。第 2 轮按 snapshot_ref 绑定来源，不能通过调用者自填 company_id 代替校验。当前 ingest 固定发布 `output_root/run_id/data/snapshots/snapshot_id/warehouse.duckdb` 与同目录 `snapshot_manifest.json`（`data_platform/snapshots/ingest.py`）；查询从显式 warehouse 的 parent 定位该固定文件，不搜索其他目录。执行前校验 manifest 的 snapshot_id、warehouse.duckdb 登记路径和大小与实际文件一致，并沿用仓库 ingest.sources 的显式 Snapshot 身份检查；缺失或不符拒绝。回执保存本次计算的 manifest 摘要和 manifest 登记的仓库发布时摘要，不要求每次查询重新扫描全库计算哈希。业务层用当前配置指向的同一 manifest 比对。这证明受信任不可变 Snapshot 的上下文绑定，不承诺检测任意事后数据库篡改；全量文件完整性属于 Snapshot 质量/完整性检查，不在查询链路增加缓存或快速回退。合成 fixture 已补齐为正式 Snapshot fixture，不提供裸库回退。纯数据层不校验 Pack/Bridge。

### 查询成功响应

`controlled_query_result.v2` 成功响应固定包含 `schema_version`、`status="passed"`、`run_id`、`snapshot_id`、`receipt`、`result`、`errors=[]`。其中 receipt 为 `{evidence_id, path, sha256, size_bytes, media_type}`，path 相对本次 `output_root/run_id`，指向执行子目录内的回执。result 仅是小结果的 `{columns, rows}` 内联副本，大结果为 null；完整数据始终由回执的 result 文件引用定位。行列数量、来源、SQL 和参数的权威记录在回执中，响应不再另设旧 artifact 字段。读取者先验证回执及其文件引用，再使用内联副本或文件数据。失败沿用 CLI 非零退出和结构化错误约定，不返回成功证据引用。

回执目录只有在全部必需文件写入并完成校验后才发布成功；同一 run 可有多个独立 evidence_id，不覆盖已有执行目录。失败只清理本次未完成目录，不删除该 run 的其他成功证据。

## 3. SQL、参数和结果的字节约定

SQL 保存实际提交给执行器的 UTF-8 文本；哈希计算保存字节，不能保存另一份格式化 SQL。保存查询还保留其登记版本身份。参数统一保存 JSON：无参数为 `null`，位置参数保持数组顺序，命名参数保持键和值及 JSON 类型。结果沿用 `{columns, rows}` 结构及当前日期、Decimal、bytes 的 JSON 转换规则；精确字节摘要不代表浮点或 SQL 语义等价。

JSON 写出使用固定 UTF-8 序列化规则（无 ASCII 转义、紧凑分隔符、对象键排序、拒绝 NaN/Infinity）；所有摘要均对实际保存字节计算，校验时不重新序列化后再比摘要。结果顺序以实际返回为准，需要稳定复算时查询必须显式排序。内联副本必须与已落地结果一致，空结果也保留结果文件。失败查询不生成 `passed` 回执；不把失败转零。

## 4. 路径与 Casebook 归档

查询证据置于显式 `output_root/run_id` 内独立执行目录；回执内文件路径相对回执目录。交付清单中路径相对清单目录；其查询引用可定位同一显式证据包内的子目录。拒绝绝对路径、`..`、软链逃逸、重复身份绑定不同字节、缺失文件或越过证据包根。哈希不能作为越界读取的理由。不在公开看板目录放 SQL、参数、完整结果或本地清单。

Casebook 仅接受工作区内显式选择的 `business_delivery.v1` 清单。case-create/case-capture 验证并复制明确选中的最小证据闭包。采用**保持每个证据包内部相对目录结构**的复制方式，将包放在案例 `evidence/delivery_<序号>/` 下；回执、交付清单字节不改写，案例最外层记录复制后的入口与摘要。不递归收集未引用文件，不复制整个 runs、客户原始文件或数仓。

保存前检查业务清单与当前工作区的公司、角色、Snapshot、Pack/Bridge 一致；复制后再次验证闭包，再让 candidate 对外可见。失败清理本次未完成 candidate，不留下可检索半成品。`case-verify` 在归档包根验证，删除原运行目录后仍能校验；无需源数仓仍可验证字节与已封存上下文，但重新计算必须使用可用且匹配的 Snapshot。

已封存案例不回写、不删除，不承诺其旧证据具有新合同保证。新写入只使用新合同，不保留旧写入口或自动转换；既有案例状态/检索保留，旧记录按原有证据强度识别，不伪称新协议闭包已验证。具体旧档只读识别是保存历史记录的边界，不扩展为通用兼容层。

市场工作面 Evidence 在数据工作区外，当前 Casebook 不接受这些外部路径。第 2 轮已在同一合成工作区验证完整证据包；市场 CLI 已同步验证新查询回执。若要从市场成果保存案例，须明确把选定包复制到已授权数据工作区内再调用原入口，不放宽 Casebook 根边界、不建软链。

## 5. 已实现链路与产品边界

| 样例 | 公共表达 | 实施轮次 |
|---|---|---|
| 小查询 `SELECT …` 返回一行 | run_a / snapshot_s / evidence_a；query.sql、parameters.json、result.json、receipt.json 均落地；stdout 可同时内联；HTML 交付清单引用 receipt；复制后删原目录仍可 case-verify | 第 2 轮 |
| 大查询超过内联阈值但未超上限 | 同样四份文件；stdout 只返回明确文件引用；相同数字的另一次执行使用新 evidence_id；SQL/参数/结果篡改均拒收 | 第 2 轮 |
| 看板当前期与同期查询 | 已验证回执后读取当前期和同期结果，继续生成现有静态图表；主页面仍不新增独立最终交付清单 | 查询读取已实现；最终产物改造取消 |
| 监控多个通道/跨月回查 | 已验证各次查询回执后读取结果；保持 digest、现有 evidence 及失败阻断，不新增统一业务清单 | 查询读取已实现；最终产物改造取消 |

### 合成包结构与完整最小清单

以下仅演示合同，`H_*` 是 SHA-256 占位符、size_bytes 为示意数字，不是可直接提交的有效证据；实际生成必须使用真实摘要和字节数。包根为工作区 `Output/run_demo/delivery_demo/`：

```text
delivery_demo/
  delivery.json
  report.html
  queries/evidence_demo/
    receipt.json
    query.sql
    parameters.json
    result.json
```

回执在 queries/evidence_demo/receipt.json，SQL 为 `SELECT 1 AS n`，参数文件为 `null`，结果为 `{"columns":["n"],"rows":[[1]]}`。本例无 landing 来源，所以两个来源数组为空；业务案例实际验收另使用有来源合成查询，以满足其既有来源约束。

```json
{
  "schema_version": "query_receipt.v1",
  "kind": "query",
  "evidence_id": "evidence_demo",
  "run_id": "run_demo_query",
  "snapshot_id": "snapshot_demo",
  "snapshot_ref": {"snapshot_id": "snapshot_demo", "manifest_sha256": "H_MANIFEST", "warehouse_sha256": "H_WAREHOUSE"},
  "created_at": "2026-09-18T00:00:00Z",
  "producer": {"name": "data_platform.query", "version": "0.1.0"},
  "sql": {"path": "query.sql", "sha256": "H_SQL", "size_bytes": 13, "media_type": "text/plain"},
  "parameters": {"path": "parameters.json", "sha256": "H_PARAMS", "size_bytes": 4, "media_type": "application/json"},
  "result": {"path": "result.json", "sha256": "H_RESULT", "size_bytes": 30, "media_type": "application/json"},
  "row_count": 1,
  "columns": ["n"],
  "limits": {"max_rows": 1000, "max_result_bytes": 1000000},
  "referenced_relations": [],
  "referenced_source_ids": []
}
```

业务清单 delivery.json：

```json
{
  "schema_version": "business_delivery.v1",
  "kind": "analysis",
  "run_id": "run_demo",
  "snapshot_id": "snapshot_demo",
  "created_at": "2026-09-18T00:01:00Z",
  "producer": {"name": "demo_report", "version": "1.0.0"},
  "workspace_ref": {"company_id": "company_demo"},
  "primary_role": "operations",
  "pack_ref": {"pack_id": "education_training_operations_cn", "pack_version": "1.0.0"},
  "bridge_ref": {"bridge_id": "bridge_demo", "bridge_version": "1.0.0"},
  "metric_refs": [],
  "query_refs": [{"evidence_id": "evidence_demo", "path": "queries/evidence_demo/receipt.json", "sha256": "H_RECEIPT", "size_bytes": 1000, "media_type": "application/json"}],
  "files": [{"artifact_id": "artifact_report_demo", "path": "report.html", "sha256": "H_REPORT", "size_bytes": 200, "media_type": "text/html"}]
}
```

查询服务先生成查询执行目录；宿主组包时只复制明确引用的查询目录到 queries/，保持 receipt 的局部相对路径和字节不变，再生成 delivery.json。Casebook 将整个已验证引用闭包放到 `evidence/delivery_1/`，以上两个 JSON 无需改写。大查询采用同一结构，只改变结果大小与 stdout 是否内联。看板和监控保留各自最终产物，本示例不构成其改造要求。

## 6. 实现与验收入口

| 文件/边界 | 必要变更与直接消费方 |
|---|---|
| `data_platform/query/service.py`、`interfaces/data_platform.py` | 查询始终写证据包、保留 saved query 身份与显式来源绑定、提供可验证回执；query/run-saved-query/quality 同一执行路径同步。只在实际复用出现时抽出最小模块内读写校验函数 |
| `workspace_modeling/casebook/service.py`、`interfaces/casebook.py` | create/capture/verify 接入选定包的验证与复制；沿用四态和人工确认；按实际输入变化更新 CLI，不新增保存入口 |
| `dashboard_product/management/calculation.py`、`dashboard_product/shadow_bi/library.py`、`monitoring_product/release_notifications.py`、`market_workspace/tools/data.py` | 服务器共同计算通过 Data Platform 受控查询，library封存同批业务表；通知从正式release受控读取同批表并生成通知包，不重算原始数仓；投递校验身份与去重，市场工具保留自己的受控读取入口 |
| 自由分析入口说明、`docs/casebook-pilot-contract.md`、本合同与集成指南 | 宿主生成一个最小交付清单的确定性方法、授权 capture 输入与证据位置同步；不建设 Renderer |
| `tests/platform/test_query_service.py`、`tests/test_casebook.py`、`tests/test_casebook_pilot_cli.py`、`tests/test_market_workspace.py`、看板/监控相关读取测试 | 合成工作区覆盖内联/文件读取、空结果、同内容不同身份、SQL/参数/结果篡改、越界、错仓/错 Snapshot、复制后删源、原状态/隔离回归；发送与发布 mock |

本表记录已完成的证据链改动，不授权继续修改业务计算或统一产品格式。以后只有真实问题需要变更查询接口时，再检查 execute_query、quality_issues 和 stdout 的直接消费者并同步回归。

## 7. 宿主确定性组包 API

查询返回先用 `data_platform.query.evidence.read_query_result(response, output_root=...)` 验证回执、SQL、参数、结果及内联副本，再读取数值。`verify_receipt(receipt_path)` 返回 `(receipt, result)`。`workspace_modeling.delivery.create_delivery` 只复制明确选定内容，不渲染报告、不扫描目录：

```python
from pathlib import Path
from workspace_modeling.delivery import create_delivery

manifest = create_delivery(
    root=Path("/absolute/customer"),
    output_dir=Path("/absolute/customer/Output/run_analysis/delivery"),  # 必须不存在
    run_id="run_analysis", primary_role="operator",
    query_receipts=[Path("/absolute/customer/Output/run_query/data/query_results/evidence_ID/receipt.json")],
    files=[{"path": Path("/absolute/customer/Output/report.html"), "media_type": "text/html"}],
    producer={"name": "customer_report", "version": "1.0.0"},
)
```

输入须位于所选工作区；禁止把 Input 原始文件、Snapshot 文件、DuckDB/Parquet 数仓作为交付物组包。正式 Output 下的 Excel 报告可作为交付物。组包回查当前配置、Bridge 和 Snapshot manifest，复制选定查询四文件与交付物，产生 `delivery.json`；`verify_delivery(manifest)` 返回清单和引用闭包。API 不证明报告业务结论正确，正式指标引用本轮仅允许空数组。

`case-create --evidence-json '[{"path":"Output/run_analysis/delivery/delivery.json"}]'` 或 `casebook_capture.v2` 的 `evidence_sources` 使用相同形状。其余问题、摘要、角色和人工操作字段沿用原入口。新写入拒绝 `kind`/来源列表手填的旧扁平输入；物理来源只从验证过的回执取得。归档先写临时目录，全部验证后发布 candidate；外层仍为 `casebook_case.v1`，新记录增加封存 `snapshot_ref` 和 `evidence_contract=business_delivery.v1`，证据项 kind 为 delivery。旧封存记录仅按原摘要强度验证，不升级、不回写。

Bridge CLI `--snapshot-quality` 现在指向 quality 查询的实际 `query_receipt.v1` 文件，读取并验证后投影成内部 `snapshot_quality_profile.v1`。Bridge 对齐/guide 的只读画像使用后者，不制造受控查询回执，也不额外落运行文件。

回归：`.venv/bin/python -B -m unittest tests.test_evidence_closure -v` 包含正式合成 Snapshot、CLI 查询、HTML 组包、CLI capture/verify，以及删除原运行和 Snapshot 目录后的独立验证。测试不连接客户数仓、不发送或发布。

本轮交付文件应自包含（例如内嵌样式/图片的 HTML、独立 XLSX）；组包逐文件保存，不解析或修复网页相对 CSS/图片链接。多文件网页依赖由宿主先处理，不提供资源打包器。
