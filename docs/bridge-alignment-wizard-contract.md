# Bridge 对齐向导 v1 合同

## 1. 消费者与产品目录

客户拿到的是一个可整体复制的自包含工作目录，不要求它是 Git 仓库，也不依赖目录外的绝对路径。Agent Host 是 CLI 和机器 JSON 的直接消费者；客户只通过自然语言提供文件、回答问题并接收结果，不读取内部 JSON。

```text
CustomerWorkspace/
  Input/
    Data/<source_id>/       当前数据；每个稳定来源槽位放一个 XLSX/XLSM
    Reference/              数据字典、表头说明等长期补充资料
  Work/
    workspace.json          当前 Snapshot、Pack、Bridge 参考和已用 ID
    Pack/pack.json          当前 Pack 的工作区副本
    Runs/                   当前 Data Foundation Snapshot
    Sessions/<session_id>/session.json
  Output/
    Bridge/<bridge_version>/confirmed_review.json
    Bridge/<bridge_version>/company_bridge.v1.json
    Bridge/<bridge_version>/validation.json
```

源码 checkout 中默认忽略 `customers/`，避免误提交客户数据；这只是 Git 策略，不是运行路径限制。产品被复制给其他人后，上述目录仍可独立工作。

## 2. 月度数据更新

`Input/Data/<source_id>/` 是稳定逻辑来源槽位，例如 `Input/Data/cash/`。客户可以用八月现金表替换七月现金表；文件名可以变化，但 `source_id=cash` 不变。

`sync-data` 自动检查每个来源槽位恰有一个工作簿，内部生成 Data Foundation 所需 manifest，并发布新的显式 `snapshot_id`。当前输入可以替换，单个已发布 Snapshot 永不原地覆盖；向导先完整生成新 Snapshot、更新 `current_snapshot_id` 和仓库指针，再删除旧 Snapshot Run。工作区不保存 `snapshot_history`，只保留已成功使用的 `snapshot_id` 字符串以禁止删除后复用身份；源文件承担长期归档，也不通过 `latest`、修改时间或模糊文件名猜测当前状态。

如果新 Snapshot 构建失败，当前指针和旧 Snapshot 保持不变。如果当前 Snapshot 仍有未完成的对齐会话，`sync-data` 返回 `ACTIVE_SESSION_EXISTS`；会话完成后才允许刷新。切换成功但旧 Run 清理失败时，新 Snapshot 仍是当前事实，返回成功结果及 `warnings`，残留旧 Run 只作为待清理文件，不重新进入状态。已完成会话为只读终态；刷新后不能再用它修改或重新生成旧 Snapshot 的 Bridge。

### 2.1 两类重叠场景

同一端口的全量刷新不做跨 Snapshot 合并。例如六月文件覆盖 `2025-01-01..2026-06-01`，七月文件仍从 `2025-01-01` 开始但延长到 `2026-07-01`：客户在同一 `source_id` 槽位替换当前文件并执行 `sync-data`。新 Snapshot 只查询七月全量文件，成功切换后删除六月 Snapshot，因此不会重复累计。

同一 Snapshot 内确实需要并存的多个端口或分段文件，重叠识别与查询时去重属于 Data Foundation 的受控只读分析，不属于 Bridge。宿主模型先通过 `describe/query` 检查日期范围、候选业务键、重复率和内容冲突；日期交集只表示“可能重叠”，不能单独删除记录。经客户确认的业务键与来源优先级形成只读 SQL，使用现有 `promote-query` 保存并通过 `run-saved-query` 重用。Bridge 只保存字段和业务语义映射，不保存物理合并 SQL。刷新后的上一版 Bridge 只作为企业口径参考，未通过新 Snapshot 的字段兼容性校验前不被标注为当前可运行 Bridge。

## 3. CLI

```text
python3 -m interfaces.bridge_alignment_wizard <command>
```

| 命令 | 作用 |
|---|---|
| `init` | 创建自包含客户工作目录，复制 Pack 和可选同公司 Bridge |
| `sync-data` | 将当前 `Input/Data` 发布为新 Snapshot 并更新明确的 current pointer |
| `start` | 基于当前 Snapshot、Pack 和 Bridge 建立对齐会话 |
| `propose` | 调用宿主注入的 `CandidateAdapter`，生成并校验 proposed 候选 |
| `answer` | Host 将客户自然语言理解为一个内部选项，记录原回答、选项和确认人 |
| `add-evidence` | 把目录/U 盘中的支持文件复制进 `Input/Reference`，重新计算候选 |
| `finalize` | 生成 `confirmed_review`、正式 Bridge 和当前 Snapshot 验证结果 |

完成当前阶段且无需客户输入时退出 `0`；等待确认或被关键问题阻断时退出 `2`；合同、身份、adapter、文件或验证错误退出 `1`。stdout JSON 是 Host 机器接口，不是客户回答格式。

## 4. 哈希边界

SHA-256 只保留在 Data Foundation 的 inspect/ingest 内部，用于确认导入期间源文件未变化和 Snapshot 中复制文件完整。客户不填写、不查看哈希；向导不使用哈希作为证据身份、批次名、问题 ID、决定 ID 或业务版本。

补充证据以 `Input/Reference` 下的相对路径为身份。同一路径内容变化表示更新；文件会保存在客户工作目录中，拔掉 U 盘后仍可复查。

## 5. 模型与确认

核心只依赖 `CandidateAdapter.propose(model_input) -> document`，不依赖宿主 SDK。模型输出只包含候选类型、proposal、置信度、证据、替代解释和可选问题；模型不生成业务身份。

核心根据 `candidate_type + source_id + relation + field_name/source_value + capability` 生成确定性 `candidate_key`。确认绑定该语义键，因此追加证据后即使模型改变临时候选顺序或名称，已确认决定仍优先且不得静默覆盖。

模型候选始终是 proposed，不能直接进入正式 Bridge。关键歧义必须生成问题并阻断 finalize；未确认的非关键候选显式进入 unresolved，并返回被禁用能力。Host 负责理解客户自由表达并选择内部选项；核心的 `answer` 不宣称自己具有自然语言理解能力。

## 6. JSON 边界

保留结构化 JSON 的机器边界：adapter 输入/输出、工作区当前指针、单一 `session.json`、`confirmed_review`、正式 `company_bridge.v1`、Snapshot 验证结果、CLI 错误码和产物路径。

客户不需要操作 `profile.json`、`questions.json`、`decisions.jsonl` 等散文件；这些状态收敛在 `Work/Sessions/<session_id>/session.json`。正式 Bridge 仍必须经过现有确定性 schema 和引用校验，不能改成自由文本。

## 7. 追加资料与 finalize

`add-evidence` 只读取指定目录，把支持的文本、CSV、JSON、XLSX/XLSM 复制到 `Input/Reference`。相同相对路径直接更新；其他文件保留。随后重建证据画像并调用同一 adapter，已有 `candidate_key` 决定保持不变。

`finalize` 只把客户 confirmed 和显式 unresolved 转换成固定 `company_bridge_candidates.v1 / confirmed_review`，随后复用现有 `build_bridge` 和 `validate_bridge`。任何关键问题未答时返回原问题且不生成正式文件。正式版本目录已存在时失败，不覆盖已发布 Bridge。

## 8. 验证

- 工作区可创建在产品目录内且所有持久路径相对工作区；
- 七月文件替换为八月文件后生成新 Snapshot，成功切换后删除旧 Snapshot；
- 新 Snapshot 失败或存在未完成会话时保留旧 Snapshot 和当前指针；
- 同公司新 Snapshot 复用企业口径而不复制旧字段绑定；
- 新公司只加载 Pack；
- 追加证据后候选临时身份变化仍保留语义确认；
- 关键问题阻断，确认后自动 build/validate。
