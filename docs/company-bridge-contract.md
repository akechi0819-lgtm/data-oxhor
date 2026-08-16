# Company Bridge v1 合同

## 1. 边界与消费者

Company Bridge 是企业侧语义资产，不是行业知识 Pack，也不是历史分析结果。宿主通过 Python CLI 消费它；后续 Customer Profile 和确定性分析模块消费版本化 JSON。历史扫描器是另一条入口，只能生成候选集，不能生成正式 Bridge。

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

正式 Bridge 构建不读取 Super Agent 原始报告、SQL、数据库或工作簿；它接收 Pack manifest 和已确认候选集。Data Foundation Snapshot 的描述/质量结果是可选的兼容性校验输入，用来检查当前数据是否能使用该 Bridge，不会成为 Bridge 的业务内容或长期绑定身份。

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
  --pack business_pack/packs/education_training_operations_cn/pack.json \
  --require-role confirmed_review

# 正式 Bridge 构建：只生成企业语义到 Pack 的连接
python3 -m interfaces.company_bridge build \
  --candidates /path/to/candidates/confirmed.json \
  --pack business_pack/packs/education_training_operations_cn/pack.json \
  --bridge-id bridge_company_super_agent \
  --bridge-version 1.1.0 \
  --company-id company_super_agent \
  --output /path/to/bridge/company_bridge.v1_1_0.json

# 可选：用某一批当前 Snapshot 检查字段是否存在、质量是否通过
python3 -m interfaces.company_bridge validate \
  --bridge /path/to/bridge/company_bridge.v1_1_0.json \
  --pack business_pack/packs/education_training_operations_cn/pack.json \
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

每个候选至少包含：

```json
{
  "candidate_id": "cand_cash_payment_date",
  "candidate_type": "field_mapping",
  "source_locator": "data_layer/docs/数据接口对齐清单.md#canonical_schema.business_date",
  "evidence_summary": "业务日期是现金交易日期角色的候选。",
  "proposed_mapping_or_rule": {
    "source_id": "br_cash",
    "relation": "clean.cash_ledger",
    "field_name": "business_date",
    "target_type": "dimension",
    "target_id": "time.cash_transaction_date"
  },
  "status": "proposed",
  "evidence_refs": ["data_layer/docs/数据接口对齐清单.md"]
}
```

状态语义如下：

- `proposed`：扫描器或模型提出，不能进入正式 Bridge；
- `confirmed`：人工确认，或仅对文件名、Sheet、列名等客观结构做确定性登记；
- `rejected`：人工明确拒收，并在候选记录中给出 `decision_note`；
- `unresolved`：人工确认该项必须继续阻断。它可以进入正式 Bridge 的 `unresolved` 类别，但不能被当成映射使用。

正式构建只接受 `candidate_set_role=confirmed_review`，且只接受 `confirmed`/`unresolved`。历史扫描输出的 `candidate_set_role=historical_scan` 永远不能直接构建 Bridge。

## 5. 合法与非法样例

合法：确认一个结构和一个明确的字段映射。

```json
{
  "schema_version": "company_bridge.v1",
  "bridge_id": "bridge_company_super_agent",
  "bridge_version": "1.0.0",
  "company_id": "company_super_agent",
  "pack_ref": {
    "pack_id": "education_training_operations_cn",
    "pack_version": "1.0.0"
  },
  "generated_from_candidate_ids": ["cand_cash_payment_date"],
  "source_contracts": [],
  "field_mappings": [
    {
      "candidate_id": "cand_cash_payment_date",
      "source_locator": "data_layer/docs/数据接口对齐清单.md#canonical_schema.business_date",
      "evidence_summary": "已确认现金业务日期角色。",
      "evidence_refs": ["data_layer/docs/数据接口对齐清单.md"],
      "status": "confirmed",
      "source_id": "br_cash",
      "relation": "clean.cash_ledger",
      "field_name": "business_date",
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

这里的 Snapshot 不是“某个现成的数据库文件”，而是 Data Foundation 针对一批明确输入发布的、不可原地覆盖的数据版本。它至少有三层含义：

- `snapshot_id`：明确指向哪一批数据，不能用 `latest`、修改时间或模糊文件名猜测；
- `warehouse_description.v1`：由 Data Foundation `describe` 生成，列出该 Snapshot 实际存在的关系、列名和类型，校验 Bridge 映射没有悬空到不存在的列；
- `controlled_query_result.v1`：由 Data Foundation `quality` 生成，必须引用同一个 `snapshot_id` 且 `status=passed`。它检查文件/表结构、登记的质量问题和结果载荷是否满足运行门槛，不替代业务口径确认，也不等于所有业务数字都已经正确。

因此，Bridge 可以先独立完成并复用；当要在某一批真实数据上运行时，再用 Snapshot 描述和质量结果核对“映射指向的结构”和“这批结构通过质量门”。如果只构建 Bridge，不需要先发布 Snapshot；如果提供了 Snapshot 描述，就必须同时提供同一 Snapshot 的质量结果，校验器会检查关系/列引用和质量状态。不能把 Super Agent 的 SQLite 或历史工作簿直接冒充为 Data Foundation Snapshot。

## 8. 当前扫描与审核结果

2026-08-14 对 `/Users/akechi/Desktop/super_agent` 的扫描结果写入本项目独立候选区：

`artifacts/company_bridge/candidates/super_agent_history_scan_20260814_v6.json`

结果已用当前 Pack 校验：136 个候选、851 个拒收记录；候选中 19 个是文件/Sheet/技术表头等客观源结构并标记 `confirmed`，其余语义映射、清洗或 unresolved 候选在历史扫描文件中保持 `proposed`。扫描没有修改 Super Agent；其现有未提交数据刷新改动也未被处理。用户在 2026-08-15 确认后，独立 reviewed 文件晋升 135 个 confirmed 候选，并用一个 `customer.payer` Override 指向 `customer.student`；两个历史 unresolved 不再作为首版阻断项。

产品候选特别保留一条条件规则：标准现金产品字段先保留 `raw_product=剑五`，同一记录的 `班型` 为 `KET` 或 `PET` 时，二次归一为对应独立产品，并归入提能线/小高；其他班型保留剑五并告警。该规则已在 reviewed 文件中确认。扫描还明确拒收“默认看新生”的分析筛选偏好。

日报明细候选把三件事拆开：`现金收入/报入现金收入/实缴金额` 的正负值用于净现金有符号求和；只有 `退班退费`、`储值账户退费`、`返款退费` 等明确业务形式，或排除“放储值/转班/重报”后的明确原因，才归为退款；`转出`、`转入`、`退班放储值`、转班/退班重报归为 `adjustment`。用户已确认退款规则，且付款人统计沿用学员身份；1500 人头资格门槛仍不进入 Bridge。

第一版 reviewed 闭环已覆盖收款/退款方向、现金交易日期、校区、产品、学员身份和交易类型。按真实 Data Foundation 三表字段对齐的 `confirmed_review` v2 已生成正式 Bridge 1.1.0，并在 `snapshot_super_agent_inputs_20260815_v2` 上通过兼容性校验；现金明细中的 `产品=剑五` 通过 `班型` 二次筛出 KET/PET，真实查询结果为 KET 4,143 行、PET 1,337 行。
