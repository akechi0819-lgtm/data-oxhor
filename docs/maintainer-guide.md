> 正式BI维护入口：`dashboard_product/DEPLOYMENT.md`与`docs/bi-production-baseline-20261025.md`。通用核心回归可用已有Python3.12执行`python3 -B -m pytest tests dashboard_product/tests dashboard_product/management/tests monitoring_product/tests -p no:cacheprovider`；Superset认证测试在核心环境明确skip，必须另外在固定Superset环境运行`python -B -m unittest tests.test_shadow_bi_legacy_auth`。两类环境分别报告，不把skip计为通过。

# 维护者指南

本文件面向维护 Data OXHor 的开发者和 Agent，不是客户使用说明。项目定位、模块状态和主模块施工记录请先看根目录 [开发文档](../DEVELOPMENT.md)；客户入口请看 [用户指南](./user-guide.md)。

## 代码与测试

- Python 要求 `>=3.12`；运行时核心依赖 DuckDB `1.5.5`。
- 安装开发测试环境：`sh tools/install_runtime.sh test`。
- 运行完整回归：`sh tools/run_tests.sh -v`；入口使用项目 `.venv` 中的 pytest，覆盖 `tests`、`dashboard_product/tests`、`dashboard_product/management/tests`、`monitoring_product/tests`，默认不生成字节码缓存。Project Intelligence的MCP协议测试在未独立安装SDK时明确skip。
- CLI 冒烟：`python3 -m interfaces.data_platform --help`、`python3 -m interfaces.business_pack validate`、`python3 -m interfaces.workspace_modeling --help`、`python3 -m dashboard_product.management.build --help`、`python3 -m monitoring_product.shared_delivery --help`。
- `dashboard_product/refresh.py` 是仍被管理构建导入的内部 source helper，不是命令行库；不要将 `python -m dashboard_product.refresh` 当作 CLI。
- 看板回归：`python3 -m unittest discover -s dashboard_product/tests -v`。
- 部署/投递适配回归：`python3 -m unittest dashboard_product.tests.test_management_activation monitoring_product.tests.test_shared_delivery -v`；激活 dry-run 本地校验，mock 测试不连接服务器。
- PPT Master 属于宿主全局 Skill；不要在项目内恢复其副本、安装 profile 或完整性测试。
- 项目上下文服务见 [Project Intelligence](./project-intelligence.md)。定向回归：`.venv/bin/python -B -m unittest tests.project_intelligence.test_service -v`，已由主测试发现入口覆盖。新增暴露文件须评审 `project_intelligence/policy.py`，不得直接放开整个目录。

## 维护原则

- CLI 是公开机器接口；变更命令、JSON、路径、退出码或目录合同前，先更新对应合同文档和测试。
- 宿主 Agent、Session、模型和工具选择属于宿主；项目不包装第二层 Agent Loop 或模型路由。
- 只读门禁、Snapshot 身份、Bridge 状态、证据哈希和文件验收由确定性代码负责。
- 新增治理、适配器或平台层必须对应可复现失败或明确客户需求；不要为未来宿主预建协议层。
- 原始客户数据、DuckDB、Parquet、`runs/` 和 `customers/` 不进入 Git。

## 本地瘦身

- 先核对磁盘占用、当前工作树、`Work/workspace.json`、明确封存/验收批次及未完成迁移。不得按 `latest`、修改时间或目录名猜测保留对象，也不撤销其他任务的未提交改动。
- 可再生成的 Python/测试缓存可清理。看板试制批次被明确最终版替代后，可删除其重复网页、展示包与计算副本；保留查询证据、回执、对账/验收记录和批次身份，并在原批次写清清理记录。正式交付及其引用闭包不随试制缓存删除。
- BI重建的本次下载、合并及两个来源临时保留位于 `Work/Runs/_bi_rebuild_tmp/<本次唯一目录>/`；正常成功或明确失败恢复后删除。错误中明确标记保留的 `input_backup/` 是失败恢复所需文件，不按缓存删除。旧 `_bi_downloads` 不再是运行入口，历史残留只在任务停止且所需导出另有有效留存后按清单核销。`_bi_export_keep/<snapshot_id>` 保存原始BI导出审计副本；旧Snapshot、历史landing与原始输入不按年龄批删。
- 同步outbox、staging及backup在目标安装/接收验收前保留；包哈希代表固定批次，清理本机后不原地改写已有包。后续传输须明确使用原封存包或重新制作瘦身后的新批次。登录profile、auth session、密钥及投递去重状态不纳入缓存扫描。
- 清理只按具体路径清单执行，不跟随软链；删除前记录路径、用途、体积和哈希，删除后验证保留文件、证据及最终产物可用。审计和回执放 `.local/audits/<任务>/`，不新增常驻清理服务。

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

在既有虚拟环境单独安装 `mcp==2.2.0`，从源码根目录运行 `.venv/bin/python -B -m unittest tests.project_intelligence.test_service tests.project_intelligence.test_mcp -v`。当前 `pyproject.toml` 不提供 `.[mcp]` extra、Project Intelligence包或console入口，不使用旧安装说明。协议测试启动真实 stdio 子进程，未安装可选依赖时明确 skip，不能据此宣称 MCP 验收通过。详见 [stdio MCP](./project-intelligence-mcp.md)。
