# 维护者指南

本文件面向维护 Data OXHor 的开发者和 Agent，不是客户使用说明。项目定位、模块状态和主模块施工记录请先看根目录 [开发文档](../DEVELOPMENT.md)；客户入口请看 [用户指南](./user-guide.md)。

## 代码与测试

- Python 要求 `>=3.12`；运行时核心依赖 DuckDB `1.5.5`。
- 安装开发测试环境：`sh tools/install_runtime.sh test`。
- 运行完整回归：`sh tools/run_tests.sh -v`。
- CLI 冒烟：`python3 -m interfaces.data_platform --help`、`python3 -m interfaces.business_pack validate`、`python3 -m interfaces.workspace_modeling --help`、`python3 -m dashboard_product.refresh --help`。
- 看板回归：`python3 -m unittest discover -s dashboard_product/tests -v`。
- PPT Master 属于宿主全局 Skill；不要在项目内恢复其副本、安装 profile 或完整性测试。
- 项目上下文服务见 [Project Intelligence](./project-intelligence.md)。定向回归：`.venv/bin/python -B -m unittest tests.project_intelligence.test_service -v`，已由主测试发现入口覆盖。新增暴露文件须评审 `project_intelligence/policy.py`，不得直接放开整个目录。

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

## 当前状态与历史记录

当前状态、已知限制与本次施工记录统一维护在 [DEVELOPMENT.md](../DEVELOPMENT.md)。[历史交接](history/project-handoff-through-20260918.md) 仅保留过去决策与验收事实，不作为日常操作入口；看板运行以模块 README 和 DEPLOYMENT 为准。

## Project Intelligence MCP 可选测试

在既有虚拟环境安装 `mcp==2.2.0` 或项目 `.[mcp]` extra 后，运行 `.venv/bin/python -B -m unittest tests.project_intelligence.test_service tests.project_intelligence.test_mcp -v`。协议测试启动真实 stdio 子进程，未安装可选依赖时明确 skip，不能据此宣称 MCP 验收通过。详见 [stdio MCP](./project-intelligence-mcp.md)。
