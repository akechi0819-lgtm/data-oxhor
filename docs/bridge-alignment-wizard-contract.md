# Bridge 对齐向导 v1 合同

## 1. 消费者与边界

唯一直接消费者是具备受控 Shell 的 Agent Host。客户通过宿主自然语言交互，不读取或编写 Bridge JSON。向导只编排 Data Foundation Snapshot、Business Pack、可选同公司 Bridge、模型候选和 Company Bridge 确定性服务；它不入仓、不修改 Pack、不实现模型循环，也不执行正式外部业务动作。

## 2. CLI 与退出码

公开入口：

```text
python3 -m interfaces.bridge_alignment_wizard <command>
```

命令：

| 命令 | 输入 | 成功输出 |
|---|---|---|
| `start` | `session_id`、`company_id`、显式 `warehouse`/`snapshot_id`、`pack`、可选 `existing_bridge`、项目外 `workspace` | 会话、确定性画像、模型输入、问题与显式产物路径 |
| `propose` | 会话目录、实现 `CandidateAdapter` 的 adapter 引用 | 校验后的模型候选和重算问题 |
| `answer` | 会话目录、`question_id`、自然语言 `answer`、`confirmed_by` | 追加的不可变确认记录和剩余问题 |
| `add-evidence` | 会话目录、只读目录 | 补充证据画像、重算后的模型输入/候选/问题；已有确认不覆盖 |
| `finalize` | 会话目录、`bridge_id`、`bridge_version` | `confirmed_review`、正式 `company_bridge.v1` 和 Snapshot 验证结果 |

完成当前阶段且无需客户输入时退出 `0`；`awaiting_confirmation` 或 `blocked` 退出 `2`；合同、身份、adapter、文件或验证错误退出 `1`。所有命令只向 stdout 输出一个 JSON 对象，至少包含 `schema_version`、`status`、`session_id`、`artifacts`、`pending_questions`、`disabled_capabilities` 和 `errors`。

## 3. 身份输入

`start` 必须显式提供 `snapshot_id`、仓库路径、`pack_id`/`pack_version` 所在 Pack 文件和新的 `company_id`。仓库通过 Data Foundation `describe_warehouse` 验证 Snapshot 身份，Pack 通过现有校验器验证。

`existing_bridge` 仅允许同一 `company_id` 且 Pack 身份完全相同；其企业口径作为 `enterprise_decisions` 证据，旧 relation/field 绑定不得直接复制到新 Snapshot。新公司不传该参数，因此只能复用 Pack。

会话目录固定为 `<workspace>/<session_id>/`。已存在会话不覆盖，恢复必须显式传会话目录；不得使用 `latest`、修改时间或模糊文件名。

## 4. 确定性结构画像

`bridge_alignment_profile.v1` 固定包含：

```text
session_id / company_id / snapshot_id / pack_ref
relations[]: relation、source_id、sheet_name、columns[]、sample_rows[]、header_candidates[]
supplemental_evidence[]: 相对路径、类型、SHA-256、表头或截断文本摘录
enterprise_decisions[]: existing Bridge 中与企业口径相关的 confirmed override/enum/normalization 摘要
```

Snapshot 画像由只读 DuckDB 连接生成，只读取 `ingest.sheets` 与 `landing.*`，每表最多读取有限样本。补充目录扫描只支持普通文本、CSV/JSON/JSONL/XLSX/XLSM；跳过隐藏目录、符号链接、数据库和 Parquet，不输出完整客户数据。

## 5. 模型合同

核心只依赖可注入的 `CandidateAdapter.propose(model_input) -> document`。没有宿主 SDK 依赖；测试使用 fake adapter。`bridge_alignment_model_input.v1` 提供 Pack 概念/维度/指标摘要、确定性画像、可选企业口径、已有确认记录。

adapter 输出 `bridge_alignment_model_candidates.v1`：

```text
candidates[]:
  candidate_id
  candidate_type
  proposed_mapping_or_rule
  target: target_type / target_id
  confidence: 0..1
  evidence[]: locator / summary
  alternative_explanations[]
  must_ask: boolean
  criticality: critical | optional
  capability_id
  question: 非空问题或 null
  answer_options[]: option_id / label / resulting_status / proposal
```

候选 proposal 必须符合现有 `company_bridge_candidates.v1` 对应类型；模型候选始终是 `proposed`，不能直接进入正式 Bridge。`must_ask=true` 或 critical 低置信度候选必须生成客户问题。optional 低置信度可以由客户选择 unresolved，并明确写入 `disabled_capabilities`。

## 6. 客户问题与确认

`bridge_alignment_questions.v1` 每项包含 `question_id`、`candidate_id`、`prompt`、`criticality`、`why_it_matters`、`options[]` 和 `status`。宿主可把自然语言答案原样传给 `answer`；确定性解析只接受唯一 option id、唯一标签或无歧义包含匹配，否则返回 `ANSWER_AMBIGUOUS`。

确认以 JSONL 追加记录：`decision_id`、`question_id`、`candidate_id`、`selected_option_id`、`answer_text`、`resulting_status`、`proposal`、`confirmed_by`。同一问题已有决定时再次回答返回 `DECISION_EXISTS`，不得静默覆盖。

## 7. 追加扫描合并

`add-evidence` 对指定目录只读扫描，将本次 manifest 按 SHA-256 写入会话。相同 SHA-256 去重；新证据追加，旧证据和确认记录保持不变。然后重新生成 model input 并调用同一 adapter。

重算时 candidate_id 相同的候选更新未确认内容；已确认 candidate_id 的决定优先，模型不得改变其 proposal/status。消失的未确认候选移除。新候选生成新问题。证据目录本身不被复制或修改，所有扫描产物只写显式 workspace。

## 8. Review、Build 与错误语义

`finalize` 仅把客户决定为 `confirmed` 或 `unresolved` 的候选转换为固定 `company_bridge_candidates.v1` / `confirmed_review`。任何 `proposed` 映射都不会进入 review。

只要存在未回答 critical 问题，返回 `status=blocked`、错误 `CRITICAL_QUESTIONS_PENDING`、原待答问题和退出 `2`，且不生成 review/Bridge。未回答的 optional 问题在 finalize 时显式转为 unresolved，进入 review 并在输出中列出禁用能力，不会被静默当成映射。随后向导调用现有 `build_bridge`，再用当前 Snapshot description/quality 调用 `validate_bridge`；任一失败均退出 `1`，不声称完成。

## 9. 验证

- 合同测试覆盖身份、adapter 输出、问题和退出码；
- 单元测试覆盖同公司 Bridge 复用、新公司隔离、追加扫描去重和确认不可覆盖；
- 端到端 fixture 创建陌生 XLSX、入仓、追加数据字典、关键确认、review、build 和 Snapshot validate。
