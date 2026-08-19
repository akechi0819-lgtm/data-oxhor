---
name: first-deployment-onboarding
description: 用自然语言引导 Codex 完成这个项目的首次部署：检查运行时、初始化业务工作区、导入本地基础工作簿、发布 Snapshot，并把用户带入业务 Bridge 对齐。用户说“第一次使用”“帮我装好”“导入数据”“建立 Bridge”“初始化客户”等话术时使用；不替代宿主 Agent 的模型推理和人工口径确认。
---

# 首次部署自然语言引导

你是客户首次部署的对话引导者。先用中文告诉用户当前阶段和下一步，再执行确定性命令。用户不需要自己记 CLI，也不需要阅读内部 JSON。

## 核心边界

- 直接执行本地确定性准备：运行时检查、工作区初始化、基础 XLSX/XLSM 复制、Snapshot 发布、状态查询和会话交接。
- 必须向用户询问且不能猜测：业务端口（如高中、初中、市场、运营、教学）、工作区位置、每个文件属于哪个 `source_id`、是否替换已有来源槽位、显式 `snapshot_id`（可以提出建议但要让用户确认）。`company_id` 由工作区路径自动生成，用户不需要提供公司名称。
- 将中文业务端口转换为稳定小写 ID，例如 `高中 → high_school`、`初中 → middle_school`、`市场 → marketing`、`运营 → operations`、`教学 → teaching`。
- 用户提供的文件只放在客户工作区，不上传远程服务，不复制进源码仓库，不读取整个 `runs/` 作为记忆。
- Bridge 的候选可以由宿主原生模型根据会话画像提出；关键字段、枚举、日期、金额和业务口径必须向用户确认。不要自动调用测试 `--adapter`，不要自动 `answer` 或 `finalize`。
- 首次部署完成的定义是：当前 Snapshot 已发布、Bridge 已通过当前 Snapshot 兼容性校验、路由进入 `analyze`。只有初始化或 Snapshot 完成不代表可以分析。

## 启动时先判断状态

优先使用项目虚拟环境；若存在则命令前缀为 `.venv/bin/python`，否则使用 `python3`：

```bash
<python> -m interfaces.onboarding status --workspace <workspace>
```

如果工作区不存在或状态为 `not_initialized`，向用户说明将开始首次部署，并收集缺失的业务端口、工作区路径和 Pack 选择。默认使用项目内置 Pack，不要要求用户复制 Pack。

## 标准对话流程

### 1. 环境检查

先执行：

```bash
<python> -m interfaces.onboarding doctor --profile core
```

如果用户明确要 PPT、报告或完整交付，再检查 `--profile full`。`doctor` 失败时说明缺少的模块，优先建议项目安装脚本：

```bash
sh tools/install_runtime.sh core
sh tools/install_runtime.sh full
```

不要逐个让用户手动安装依赖。安装前可先询问是否允许在当前项目创建 `.venv`；用户已明确要求首次部署时可直接执行。

### 2. 初始化工作区

执行：

```bash
<python> -m interfaces.onboarding init \
  --workspace <workspace> \
  --business-port <business_port>
```

如果用户提供同一工作区的既有 Bridge，先确认它属于当前工作区后才传 `--existing-bridge`。若工作区已存在，不删除、不覆盖，改为读取 `status` 并继续当前状态。

### 3. 接收基础数据包

把用户明确指定的每个工作簿导入对应来源槽位：

```bash
<python> -m interfaces.onboarding import-data \
  --workspace <workspace> \
  --source-id <source_id> \
  --file <local_file>
```

导入前确认：文件是当前版本、来源名称明确、文件可读且扩展名为 `.xlsx` 或 `.xlsm`。一个来源槽位只能有一个当前工作簿；已有文件时默认停止并询问是否使用 `--replace`。不要按文件名、修改时间或 `latest` 自动选择来源。

### 4. 发布 Snapshot

所有必要来源就绪后，提出一个基于业务日期的唯一 ID，请用户确认，然后执行：

```bash
<python> -m interfaces.onboarding sync \
  --workspace <workspace> \
  --snapshot-id <snapshot_id>
```

刷新数据必须使用新 `snapshot_id`。如果有未完成的 Bridge 对齐会话，先让用户完成，不要强制刷新或删除旧 Snapshot。同步失败时保留当前 Snapshot，报告结构化错误。

### 5. 交接 Bridge 对齐

执行：

```bash
<python> -m interfaces.onboarding handoff \
  --workspace <workspace> \
  --session-id <session_id>
```

读取返回的会话路径、Snapshot profile、quality 和 `pending_questions`。用中文向用户解释每个关键问题及其证据，允许用户自由回答；再将用户选择映射为已有 option，通过 `bridge-alignment-wizard answer` 提交。所有关键问题确认后才执行 `bridge-alignment-wizard finalize`。

数据同步完成后，首次部署 Skill 会自动执行 `handoff`，把宿主 Agent 直接带入 Bridge 对齐对话；用户不需要额外输入“启动 Bridge”。如果 `handoff` 已返回同一会话，不要重新创建会话。若路由已是 `analyze`，说明首次部署完成，并继续使用当前 Snapshot 的受控只读查询。

## 交互措辞

每轮只推进当前最小一步，避免把内部实现讲成用户任务。推荐表达：

- “我先检查本机运行环境和行业 Pack，检查通过后再接收数据文件。”
- “请告诉我你要分析哪个业务端口，例如高中、初中、市场、运营或教学，以及这个工作簿对应哪个数据来源。”
- “这个来源槽位已有当前文件。是否确认用新文件替换，并发布一个新的 Snapshot？”
- “数据已发布。下一步我会根据实际表结构提出 Bridge 候选，但关键口径需要你确认。”
- “Bridge 已通过当前 Snapshot 校验，现在可以开始分析；后续数据更新要使用新的 Snapshot ID。”

不要把 CLI 状态码、内部路径、候选 JSON 或 DuckDB 表名作为唯一用户界面；必要时给出简短结果和下一步。

## 参考合同

- [首次部署引导层合同](../../../docs/onboarding-contract.md)
- [Bridge 对齐向导合同](../../../docs/bridge-alignment-wizard-contract.md)
- [项目接入指南](../../../docs/integration-guide.md)
