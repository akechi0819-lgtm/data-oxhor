# Company Bridge v1 合同

## 1. 边界与消费者

Company Bridge 是企业侧语义资产，不是行业知识 Pack，也不是历史分析结果。Codex、DeepSeek Harness 等宿主通过 Python CLI 消费其版本化 JSON。历史扫描器和 Bridge 对齐向导都只能先生成候选集；模型提出的 proposed 不能生成正式 Bridge。

```text
Super Agent 历史资产（只读）
        │ scan-history
        ▼
company_bridge_candidates.v1 / historical_scan
        │ 人工确认后形成独立 reviewed 文件
        ▼
company_bridge_candidates.v1 / confirmed_review
        │ build + Pack
        ▼
company_bridge.v1
        │ optional compatibility check with Snapshot describe/quality
        ▼
current Snapshot 可运行
```

正式 Bridge 构建不读取 Super Agent 原始报告、SQL、数据库或工作簿；它接收 Pack manifest 和已确认候选集。Data Platform Snapshot 的描述/质量结果是可选的兼容性校验输入，用来检查当前数据是否能使用该 Bridge，不会成为 Bridge 的业务内容或长期绑定身份。

## 2. CLI

```bash
python3 -m interfaces.company_bridge --help

# 历史入口：只读扫描，输出只能放在扫描根目录之外
python3 -m interfaces.company_bridge scan-history \
  --root /path/to/super_agent \
  --output /path/to/candidates/scan.json \
  --company-id company_super_agent \
  --candidate-set-id scan_super_agent_20260814

# 候选校验
python3 -m interfaces.company_bridge validate-candidates \
  --input /path/to/candidates/confirmed.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json \
  --require-role confirmed_review

# 正式 Bridge 构建：只生成企业语义到 Pack 的连接
python3 -m interfaces.company_bridge build \
  --candidates /path/to/candidates/confirmed.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json \
  --bridge-id bridge_bi_operations \
  --bridge-version 1.1.0 \
  --company-id workspace_bi_operations \
  --output /path/to/bridge/company_bridge.v1_1_0.json

# 可选：用某一批当前 Snapshot 检查字段是否存在、质量是否通过
python3 -m interfaces.company_bridge validate \
  --bridge /path/to/bridge/company_bridge.v1_1_0.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json \
  --snapshot-description /path/to/snapshot-description.json \
  --snapshot-quality /path/to/snapshot-quality.json
```

所有命令输出结构化 JSON，并以非零退出码表示失败。输出文件已存在时失败，不覆盖已有版本；CLI 不使用 `latest`、修改时间或模糊文件名恢复状态。

## 3. 版本化 JSON 形状

正式 `company_bridge.v1` 的顶层正式内容只有以下六类：

| 类别 | 允许表达的内容 |
|---|---|
| `source_contracts` | 文件、Sheet、来源和客观字段结构 |
| `field_mappings` | 企业字段到 Pack `concept_id`/`dimension_id` 的映射 |
| `enum_mappings` | 企业枚举到 Pack taxonomy/member 的映射 |
| `normalization_rules` | 已确认的字段清洗、别名和规范化规则 |
| `overrides` | 企业相对行业 Pack 的特殊选择或口径覆盖 |
| `unresolved` | 已确认需要阻断的悬空或歧义项 |

其余顶层字段只是身份和追溯元数据：`schema_version`、`bridge_id`、`bridge_version`、`company_id`、`pack_ref`、`generated_from_candidate_ids`。Bridge 不保存数据行、Snapshot 身份、历史报告、周度结论、改善建议、原始正文、SQL 文本或 Skill 步骤；扫描器会在候选集的 `rejections` 中记录拒收原因。

## 4. 候选字段和状态

历史扫描产生的候选可能保留 `data_layer/...` 形式的 `source_locator` 和 `evidence_refs`。这些是旧 Super Agent 资料的历史审计坐标，不是当前仓库的运行路径；当前运行事实必须来自 `data_platform` Snapshot。

每个候选至少包含：

```json
{
  "candidate_id": "cand_cash_payment_date",
  "candidate_type": "field_mapping",
  "source_locator": "data_layer/docs/数据接口对齐清单.md#canonical_schema.business_date",
  "evidence_summary": "业务日期是现金交易日期角色的候选。",
  "proposed_mapping_or_rule": {
    "source_id": "br_cash",
    "relation": "landing.br_cash__sheet_39b8dee2e4b3",
    "field_name": "业务日期",
    "header_label": "业务日期",
    "target_type": "dimension",
    "target_id": "time.cash_transaction_date"
  },
  "status": "confirmed",
  "evidence_refs": ["data_layer/docs/数据接口对齐清单.md"]
}
```

### 字段定位规则（2026-09-02 起）

`field_name` 直接使用源工作表实际表头，是 Bridge 和 Snapshot 之间唯一的字段定位（例如 `工单ID`、`ID`、`业务日期`、`分配时间`）。禁止使用 `column_N`、列序或位置推断语义；校验器会直接拒绝这类字段。重复表头由落地层按出现次序加 `__2` 等后缀，引用时使用落地层实际字段名。`header_label` 如存在，必须与 Snapshot 中该字段的原始表头一致。

工单主键 `ID` 和现金 `工单ID` 是标识符，不是金额或数值指标。入仓时科学计数法数值无损展开为普通十进制文本；关联只允许非空、修剪后的文本精确匹配，禁止 `DOUBLE`、`BIGINT` 或列序推断。Bridge 只能声明由运行路径实际执行的规范化规则。

状态语义如下：

- `proposed`：扫描器或模型提出，不能进入正式 Bridge；
- `confirmed`：人工确认，或仅对文件名、Sheet、列名等客观结构做确定性登记；
- `rejected`：人工明确拒收，并在候选记录中给出 `decision_note`；
- `unresolved`：人工确认该项必须继续阻断。它可以进入正式 Bridge 的 `unresolved` 类别，但不能被当成映射使用。

正式构建只接受 `candidate_set_role=confirmed_review`，且只接受 `confirmed`/`unresolved`。历史扫描输出的 `candidate_set_role=historical_scan` 永远不能直接构建 Bridge。

Bridge 对齐向导把这条人工门禁产品化：宿主原生 Agent 的模型提出包含置信度、证据、替代解释和提问建议的 proposed 候选；宿主理解客户自由回答并传入内部选项后，确定性服务才生成固定 `confirmed_review`。代码中的 adapter 仅是程序化候选注入测试缝，不是正式宿主架构。关键问题未答时不生成 review/Bridge；完整会话合同见 [Bridge 对齐向导 v1 合同](./bridge-alignment-wizard-contract.md)。

## 5. 合法与非法样例

合法：确认一个结构和一个明确的字段映射。

```json
{
  "schema_version": "company_bridge.v1",
  "bridge_id": "bridge_bi_operations",
  "bridge_version": "1.0.0",
  "company_id": "workspace_bi_operations",
  "pack_ref": {
    "pack_id": "education_training_operations_cn",
    "pack_version": "1.0.0"
  },
  "generated_from_candidate_ids": ["cand_landing_br_cash_20260816", "cand_cash_payment_date"],
  "source_contracts": [
    {
      "candidate_id": "cand_landing_br_cash_20260816",
      "source_locator": "customers/bi_operations/Work/workspace.json",
      "evidence_summary": "现金明细表通过 Data Platform v2 全量 landing。",
      "evidence_refs": ["customers/bi_operations/Work/workspace.json"],
      "status": "confirmed",
      "source_id": "br_cash",
      "sheet_name": "现金明细表",
      "relation": "landing.br_cash__sheet_39b8dee2e4b3",
      "field_names": ["业务日期"],
      "source_kind": "data_foundation_landing"
    }
  ],
  "field_mappings": [
    {
      "candidate_id": "cand_cash_payment_date",
      "source_locator": "data_layer/docs/数据接口对齐清单.md#canonical_schema.business_date",
      "evidence_summary": "已确认现金业务日期角色。",
      "evidence_refs": ["data_layer/docs/数据接口对齐清单.md"],
      "status": "confirmed",
      "source_id": "br_cash",
      "relation": "landing.br_cash__sheet_39b8dee2e4b3",
      "field_name": "业务日期",
      "target_type": "dimension",
      "target_id": "time.cash_transaction_date"
    }
  ],
  "enum_mappings": [],
  "normalization_rules": [],
  "overrides": [],
  "unresolved": []
}
```

非法：把一次周报结论写进 Bridge，或把未确认候选直接构建。

```json
{
  "weekly_anomaly": "某周退款上升",
  "analysis_conclusion": "校区经营恶化",
  "candidate_type": "field_mapping",
  "status": "proposed"
}
```

该内容会因顶层字段非法、历史分析污染和未确认状态被拒绝。未知企业内容不会通过增加临时类别来“容纳”；应写入候选集 `rejections` 并说明属于 Pack、Skill、单次分析或无法归类。

## 6. 映射重复与上下文

`normalization_rule` 的重复键包含关系、字段、操作、源值和条件上下文。因而同一个二级渠道在不同的“主被动 + 一级渠道”完整路径下可以分别映射；同一完整上下文出现两个不同归类仍会被确定性校验器报为冲突。渠道规则优先使用 `并归渠道`，`标准展示渠道` 只承担展示或缺省回退。

## 7. Snapshot 兼容性校验

这里的 Snapshot 不是“某个现成的数据库文件”，而是 Data Platform 针对一批明确输入发布的、不可原地覆盖的数据版本。它至少有三层含义：

- `snapshot_id`：明确指向哪一批数据，不能用 `latest`、修改时间或模糊文件名猜测；
- `warehouse_description.v1`：由 Data Platform `describe` 生成，列出该 Snapshot 实际存在的关系、列名和类型，校验 Bridge 映射没有悬空到不存在的列；
- `controlled_query_result.v1`：由 Data Platform `quality` 生成，必须引用同一个 `snapshot_id` 且 `status=passed`。它检查文件/表结构、登记的质量问题和结果载荷是否满足运行门槛，不替代业务口径确认，也不等于所有业务数字都已经正确。

因此，Bridge 可以先独立完成并复用；当要在某一批真实数据上运行时，再用 Snapshot 描述和质量结果核对“映射指向的结构”和“这批结构通过质量门”。如果只构建 Bridge，不需要先发布 Snapshot；如果提供了 Snapshot 描述，就必须同时提供同一 Snapshot 的质量结果，校验器会检查关系/列引用和质量状态。不能把 Super Agent 的 SQLite 或历史工作簿直接冒充为 Data Platform Snapshot。

## 8. 当前扫描与审核结果

2026-08-14 对 `/Users/akechi/Desktop/super_agent` 完成只读扫描，得到 136 个候选和 851 条拒收记录。历史扫描只作为审计来源，不进入当前运行入口。2026-08-15 完成人工业务确认；2026-08-16 将数据定位迁移到 Data Platform v2 的通用 landing 合同，业务决定不变。

产品候选特别保留一条条件规则：标准现金产品字段先保留 `raw_product=剑五`，同一记录的 `班型` 为 `KET` 或 `PET` 时，二次归一为对应独立产品，并归入提能线/小高；其他班型保留剑五并告警。该规则已在 reviewed 文件中确认。扫描还明确拒收“默认看新生”的分析筛选偏好。

日报明细候选把三件事拆开：`现金收入/报入现金收入/实缴金额` 的正负值用于净现金有符号求和；只有 `退班退费`、`储值账户退费`、`返款退费` 等明确业务形式，或排除“放储值/转班/重报”后的明确原因，才归为退款；`转出`、`转入`、`退班放储值`、转班/退班重报归为 `adjustment`。用户已确认退款规则，且付款人统计沿用学员身份；1500 人头资格门槛仍不进入 Bridge。

当前工作区使用 `artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_1_0.json`，并在 `snapshot_bi_work_order_id_20260904` 上通过兼容性校验；历史候选、旧列序和数值化 ID 不得作为当前事实。
