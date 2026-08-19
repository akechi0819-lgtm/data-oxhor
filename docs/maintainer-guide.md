# 维护者指南

本文件面向维护 Data OXHor 的开发者和 Agent，不是客户日常使用说明。客户入口请看 [Agent 使用说明](./user-guide.md)。

## 代码与测试

- Python 要求 `>=3.12`；运行时核心依赖 DuckDB `1.5.5`。
- 安装开发测试环境：`sh tools/install_runtime.sh test`。
- 运行完整回归：`sh tools/run_tests.sh -v`。
- CLI 冒烟：`python3 -m interfaces.data_foundation --help`、`python3 -m interfaces.business_pack validate`、`python3 -m interfaces.onboarding --help`。
- PPT Master 固定树变更后，运行 `.venv/bin/python .agents/skills/ppt-master/scripts/attribution_guard.py` 和相关完整性测试。

## 维护原则

- CLI 是公开机器接口；变更命令、JSON、路径、退出码或目录合同前，先更新对应合同文档和测试。
- 宿主 Agent、Session、模型和工具选择属于宿主；项目不包装第二层 Agent Loop 或模型路由。
- 只读门禁、Snapshot 身份、Bridge 状态、证据哈希和文件验收由确定性代码负责。
- 新增治理、适配器或平台层必须对应可复现失败或明确客户需求；不要为未来宿主预建协议层。
- 原始客户数据、DuckDB、Parquet、`runs/` 和 `customers/` 不进入 Git。

## 发布前检查

1. `git status --short`，确认没有客户数据、运行产物或无关文件。
2. `git diff --check`。
3. 运行完整测试和涉及模块的 CLI 冒烟。
4. 检查 README、用户指南、架构和运维文档是否仍描述当前运行角色。
5. 检查第三方声明、上游固定版本和许可证文件。
6. 使用 GitHub CLI 提交并推送前，确认目标仓库、分支和提交范围。

## 当前交接

阶段历史、已完成能力、已知风险和暂挂事项集中记录在 [项目交接状态](./handoff.md)。交接文档可以保留历史事实，但不得被 `AGENTS.md` 或客户使用说明引用为日常操作步骤。
