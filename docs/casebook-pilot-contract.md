# Casebook、内测回收与引导路由合同（S5 已实现）

## 1. 目标和非目标

S5 为 Data OXHor 的自由分析模块补充可追溯的案例留存、用户主动回收的内测反馈，以及客户工作区内的下一步引导。它解决宿主 Session 清理、换宿主或换会话后无法稳定复用业务经验的问题。

它不是自动学习平台、远程监控服务、跨客户记忆库或第二套 Agent/Session。所有客户数据默认留在客户机器；产品不得自动扫描、上传或打包整个 `runs/` 目录。

## 2. 三类本地资料

```text
runs/                       原始运行证据：查询 JSON、SQL、日志、交付物、临时材料
客户工作区 Work/Casebook/   已确认案例：可检索、可回查的最小证据包
客户工作区 Work/Evaluation/ 内测记录：测试包执行结果、人工评价、待导出的反馈包
```

`runs/` 是证据来源，不是长期记忆的直接输入。它可能包含临时产物、过期 Snapshot 或客户明细；确认案例时只复制所需的查询结果、SQL、哈希和必要交付物。原始客户输入继续由客户自己的归档策略保存。

## 3. Casebook v1

每个客户工作区独立保存案例，建议目录为：

```text
Work/
  Casebook/
    candidates/<case_id>/
    confirmed/<case_id>/
    rejected/<case_id>/
    superseded/<case_id>/
```

一个案例至少包含：

- `case.json`：`case_id`、`company_id`、主要角色、标签、状态、原始/规范化问题、创建与确认信息；
- `summary.md`：已确认结论、适用范围、限制、不可推出的结论；
- `evidence/`：受控查询 JSON、SQL、文件 SHA-256、实际 `referenced_source_ids`；
- `outputs/`：可选的已验收交付物。

`case.json` 必须绑定生成时的 `snapshot_id`、Pack/Bridge 版本和关键查询。案例状态只有 `candidate`、`confirmed`、`rejected`、`superseded`；已确认案例不原地改写，更新通过新案例与 `supersedes` / `superseded_by` 关系完成。

调用规则：Agent 只能检索当前客户、当前主要角色范围内的 `confirmed` 案例。命中案例只是分析线索；涉及时间、金额、状态等当前事实时，必须对当前 Snapshot 重新执行受控只读查询。旧案例的数字不得直接作为当前事实。

## 4. 内测测试包与回收

测试包是版本化问题卡，不是训练集。仓库仅保存合成或脱敏的合同 fixture；真实客户内测包和结果保留在客户工作区。

首批测试包应覆盖数据理解、经营诊断、关联分析、交付复用，以及来源越界、过期 Snapshot、未确认字段、夸大结论等反例。每条问题卡记录：角色、问题、允许来源、预期关键事实/范围、禁止结论、预期交付形式和人工验收规则。

用户本地执行后写入 `Work/Evaluation/sessions/<evaluation_id>/`。记录至少包含产品、Pack、Bridge、Casebook 和测试包版本，问题、命中案例、执行状态、耗时、回答/交付物验收、人工评分与反馈、错误码和脱敏日志。

回收使用用户主动导出的反馈包：

| 类型 | 默认内容 | 目的 |
|---|---|---|
| `metrics-only` | 版本、评分、错误码、耗时、脱敏反馈、失败分类 | 默认回收，不含原始客户数据 |
| `evidence-approved` | 用户逐项选择的查询结果、截图、交付物或日志 | 复现特定业务问题 |

产品不自动联网或上传。用户通过双方约定渠道主动交回反馈包；接收方校验版本、清单和哈希后，将其归类为代码缺陷、Bridge/口径问题、Skill 缺口、Casebook 缺口或体验问题。未经客户明确许可，不导出工作簿、DuckDB、Parquet 或整个 `runs/`。

## 5. 引导路由

引导路由是客户工作区内的本地状态检查和用户提示，不是跨客户公司/角色路由器，也不选择模型或管理宿主 Session。

最小路由规则：

1. 工作区未初始化：引导创建 `Input/Work/Output` 工作区并选择 Pack。
2. 当前数据未同步为 Snapshot：引导放入稳定来源槽位并运行现有 `sync-data`。
3. 当前 Snapshot 无已验证 Bridge：引导进入现有 `start → propose → answer → finalize` 对齐流程；未确认映射不进入语义分析。
4. 当前 Snapshot 有兼容 Bridge：引导进入分析、案例检索和交付流程。
5. 用户在当前公司与角色下重复处理同类已确认问题：提示创建 Casebook 候选或 Skill/模板沉淀候选。

S5 首版只记录和展示建议。Skill/模板不能因次数自动创建、修改或发布；企业字段仍只进 Bridge，跨企业行业定义仍只进 Pack。建议的初始触发条件为同一客户、同一主要角色、同一问题类别在 90 天内出现至少 3 次已确认运行，且每次都有可用证据和人工评价。具体阈值在真实内测后再调整，不提前做复杂配置系统。

## 6. 验收和优化闭环

S5 的合同测试使用 `tests/fixtures/casebook/` 和 `tests/fixtures/pilot_feedback/` 的合成/脱敏样例。至少覆盖：客户隔离、证据哈希、过期案例、候选确认/拒绝/替代、测试包版本、默认不含原始数据的导出、用户授权证据白名单、反馈包校验，以及引导路由的四种状态。

真实内测的验收标准：高风险反例必须全部通过；来源和数据可回查边界必须全部通过；常规问题、文件打开性和人工可用性按测试包记录。回收后的可复现代码失败转为仓库合成回归测试；企业口径进入对应客户 Bridge；跨客户稳定方法经人工审核进入 Skill/模板或 Pack；高价值单客户问题进入该客户 Casebook。

## 7. S5.1--S5.3 施工合同（2026-08-18，已实现）

### 7.1 共同入口与边界

新增唯一公开 CLI：`python3 -m interfaces.casebook <command> ...`。stdout 为 `casebook_pilot_result.v1` JSON；成功退出 `0`，需人工确认/没有可执行下一步退出 `2`，合同或校验失败退出 `1`。所有客户工作区命令只接收显式 `--workspace`；独立 `feedback-verify` 只校验用户交回 ZIP，因此只接收显式 `--feedback`。CLI 复用既有 `Work/workspace.json` 的 `company_id`、Pack、当前 Snapshot 与 Bridge 参考，不新建项目侧 Session。

所有持久化路径必须为工作区相对路径。`Work/Runs/` 只能由调用者逐个指定证据文件，S5 不递归扫描、复制或导出整个目录。解析后路径必须位于工作区内，拒绝符号链接逃逸；反馈一律拒绝 `Input/Data`、工作簿、DuckDB 与 Parquet。

### 7.2 S5.1：Casebook 基础

`casebook/` 只负责案例目录、状态门禁、最小证据副本、哈希校验和同客户/角色的 confirmed 检索；不执行 SQL，不把旧数字当当前事实，也不调用宿主模型。

```text
Work/Casebook/
  candidates/<case_id>/case.json
  candidates/<case_id>/summary.md
  candidates/<case_id>/evidence/<ordinal>-<name>
  confirmed/<case_id>/...
  rejected/<case_id>/...
  superseded/<case_id>/...
```

`case.json` 是 `casebook_case.v1`，必填：`case_id`、`company_id`、`primary_role`、`question_category`、`status`、`question`、`normalized_question`、`snapshot_id`、`pack_ref`、`bridge_ref`、`key_queries`、`evidence`、`created_at`、`created_by`、`summary_sha256`。每项 `evidence` 必含相对 `path`、`sha256`、`kind`（`query_result`、`sql`、`artifact`、`log`）和非空 `referenced_source_ids`（只有 artifact 可为空）。创建时必须绑定当前 Snapshot 和工作区 Pack/Bridge。

创建只产生 candidate。确认/拒绝以原子目录移动改状态且需要非空 `decided_by`、说明；confirmed 不可原地编辑。替代必须先创建并确认新案例，新的 `supersedes` 指向旧 ID，再将旧案例移至 superseded 并写入 `superseded_by`。检索只返回相同公司、角色的 confirmed；可按类别缩小，旧 Snapshot 标记 `stale_for_current_snapshot` 但作为线索不阻断。

命令：`case-create`、`case-capture`、`case-confirm`、`case-reject`、`case-supersede`、`case-search`、`case-verify`。`case-create` 逐项列出证据，禁止目录参数；`case-capture` 只读取一个显式工作区相对 `casebook_capture.v1` JSON manifest，然后委托同一创建门禁；它不扫描 `runs/`、不执行 SQL，也不跳过人工确认。`case-verify` 重算摘要与证据 SHA-256。

### 7.3 S5.2：内测测试包与反馈回收

`pilot_feedback/` 只验证/保存问题卡、评价、授权证据与反馈包；不执行问题、不抓取宿主回答、不联网、不上传。

```text
Work/Evaluation/
  test-packages/<pack_id>/<version>/test_package.json
  sessions/<evaluation_id>/evaluation.json
  sessions/<evaluation_id>/evidence/<evidence_id>-<name>
  exports/<feedback_id>.zip
```

测试包为 `pilot_test_package.v1`，顶层必填 `pack_id`、`version`、`title`、`cards`；每卡必填 `card_id`、`primary_role`、`question`、`allowed_sources`、`expected_key_facts`、`forbidden_conclusions`、`expected_delivery`、`acceptance_rules`，同包 card ID 唯一。真实包只进客户工作区，仓库仅保存合成 fixture。

评价记录为 `pilot_evaluation.v1`，顶层必填 `evaluation_id`、`company_id`、`product_version`、`pack_ref`、`bridge_ref`、`casebook_version`、`test_pack_ref`、`status`、`started_at`、`cards`。Pack/Bridge 引用必须与当前工作区显式引用一致。执行卡记录 `card_id`、`status`、`duration_seconds`、`matched_case_ids`、`acceptance`、`score`、`feedback`、`error_codes`、`redacted_log`、`reviewed_by`、`reviewed_at`。只允许记录包内的卡；只有所有卡终态才能完成。

`metrics-only` 是含 `manifest.json` 与脱敏 `feedback.json` 的可验证 ZIP，默认仅含版本、评分、耗时、错误码、失败分类、脱敏反馈及哈希案例 ID，不含问题正文、回答、原始路径、明细、工作簿、DuckDB、Parquet 或 runs。`evidence-approved` 仅能附加本会话 `evidence/` 中经 `attach-evidence` 显式复制、逐项列 ID 且带 SHA-256 的文件。禁止附件来源 `Input/Data`、`Work/Runs`、工作簿、DuckDB、Parquet 或目录。`feedback-verify` 校验 ZIP 清单、白名单与 SHA-256，绝不发送数据。

命令：`test-pack-import`、`evaluation-start`、`evaluation-record-card`、`evaluation-complete`、`evaluation-attach-evidence`、`feedback-export`、`feedback-verify`。

### 7.4 S5.3：工作区引导与候选沉淀提醒

`casebook/router.py` 只读工作区，返回固定优先级的一条下一步建议和可选重复问题候选；不写 Pack、Bridge、Skill、模板、客户配置或宿主 Session。

`guide` 顺序：工作区缺失/无效（`initialize_workspace`）→ 无当前 Snapshot（`sync_data`）→ 当前 Snapshot 无可验证 Bridge（`align_bridge`）→ 可分析（`analyze`）。Bridge 仅从明确 `current_bridge_path` 或 `bridge_reference_path` 读取，并用当前 Snapshot 的 describe/quality 走现有 Bridge 校验；不按目录排序或修改时间选择。`repeat-candidates` 统计同客户、同角色、同类别、90 天内至少 3 个 confirmed 案例，且每例关联已完成并以 `reviewed_by`/ `reviewed_at` 明确记录人工评价的 evaluation ID。达到门槛只返回 `skill_or_template_candidate` 和内联 `skill_candidate_draft.v1` 审阅草案，绝不创建、修改或发布 Skill/模板资产。

命令：`guide`、`repeat-candidates`。分析建议必须写明 Casebook 命中只是线索，当前数字仍需在当前 Snapshot 执行受控查询。宿主 Agent 的日常分析调用顺序和保存边界见项目级 [业务分析路由 Skill](../.agents/skills/business-analysis-routing/SKILL.md)：`guide` →（可选）`case-search`/`case-verify` → 当前 Snapshot 的 Data Platform 受控查询 →（可选）交付；用户明确验收后才创建 candidate，`repeat-candidates` 不自动发布 Skill。

### 7.5 依赖顺序与测试矩阵

先落实本节合同与共享 JSON/path 校验，再并行实施，最后接单一 CLI 并做端到端验收：

| 顺序 | 子模块 | 写入范围 | 核心测试 |
|---|---|---|---|
| 0 | 共同合同 | 本文档、合成 fixture | JSON、路径、错误语义 |
| 1a | S5.1 Casebook | `casebook/`、`Work/Casebook/` | 隔离、哈希、状态移动、替代、过期标记 |
| 1b | S5.2 Evaluation | `pilot_feedback/`、`Work/Evaluation/` | 版本、卡片状态、脱敏、授权白名单、ZIP 校验 |
| 1c | S5.3 Router | `casebook/router.py` | 四段路由、Bridge 兼容、90 天/3 次/人工评价 |
| 2 | 集成 | `interfaces/casebook_pilot.py` | CLI 退出码、合成工作区 E2E、全量回归 |
| 3 | 独立审查 | 只读审核和必要小修 | 过度设计、门禁冗余、与 Data/Bridge/Quick 冲突 |

合成 fixture 仅位于 `tests/fixtures/casebook/` 和 `tests/fixtures/pilot_feedback/`。必须覆盖客户/角色隔离、篡改证据、confirmed 不可编辑、rejected/superseded、过期 Snapshot、测试包版本冲突、未完成评价不可导出、默认包无原始数据、禁止或未授权附件、篡改反馈、四种引导状态，以及次数不足/跨角色/无人工评价不提醒。S4 Quick 真实性能回归不属于本矩阵，继续挂起。
