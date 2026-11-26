# 首次部署引导层 v1 合同

## 目标

`workspace-modeling` 是宿主无关的确定性工作区建模入口；其中首次部署负责环境、工作区、文件、Snapshot 和状态交接，宿主原生 Agent 负责对话、模型候选和用户确认。

## 入口

```bash
python3 -m interfaces.workspace_modeling doctor --profile core|full
python3 -m interfaces.workspace_modeling init --workspace PATH --business-port PORT [--pack PATH]
python3 -m interfaces.workspace_modeling import-data --workspace PATH --source-id ID --file FILE [--replace]
python3 -m interfaces.workspace_modeling sync --workspace PATH --snapshot-id ID
python3 -m interfaces.workspace_modeling status --workspace PATH
python3 -m interfaces.workspace_modeling handoff --workspace PATH [--session-id ID]
```

## 输出

每条命令输出 `onboarding_result.v1` JSON，至少包含：

- `status`：当前确定性状态；
- `next_step`：唯一建议的下一步；
- `pending_actions`：需要用户或宿主完成的动作；
- `errors`：结构化错误数组；
- 相关命令的 `workspace`、内部 `company_id`、`business_port`、`snapshot_id`、`session` 和显式文件路径。

常见状态为 `doctor_passed`、`workspace_ready`、`data_imported`、`snapshot_ready`、`handoff_ready`、`in_progress`、`ready` 和 `failed`。退出码 `0` 表示该命令阶段完成，`2` 表示仍需用户/宿主动作，`1` 表示合同、文件或运行时失败。

## 门禁与边界

Codex 用户可让宿主调用上述入口。首次使用、导入数据和建立 Bridge 时，宿主按本契约执行，并在缺少业务端口、来源槽位或替换确认时向用户提问。工作区初始化时由路径自动生成内部 `company_id`，用户无需提供公司名称。

- `doctor` 检查 DuckDB、Pack 和所选运行时 profile；不安装依赖。安装由 `tools/install_runtime.sh` 或发布包 extras 完成。全量回归使用 `tools/install_runtime.sh test`，不再组合PPT依赖；PPT由宿主全局Skill管理。`tools/run_tests.sh`覆盖主测试、看板（含管理融合）和监控测试。
- `init` 只创建新工作区；复制 Pack 和可选的同公司 Bridge，不接受跨公司 Bridge。
- `import-data` 只复制本地 XLSX/XLSM 到 `Input/Data/<source_id>/`，默认拒绝覆盖已有槽位；不联网、不上传。
- `sync` 复用 Bridge 对齐向导的不可变 Snapshot 发布；必须使用新 `snapshot_id`，不会覆盖或复用已使用身份。
- `handoff` 建立或重复读取当前 Snapshot 的对齐会话，并返回会话路径和宿主动作。首次部署 Skill 在 Snapshot 发布后自动调用它，随后进入 Bridge 对齐对话；它不会生成 proposed 候选、回答问题或 finalize Bridge。
- 正式 Bridge 仍必须通过 `interfaces.bridge_alignment answer` 和 `finalize`，关键问题未确认时阻断。
