> **2026-10-28唯一正式数据源**：本机main只使用 `customers/shadow_bi_daily`。旧 `bi_operations` 与独立 `shadow_bi_operations` 数仓、c373客户副本和废弃派生成品已清理。原始输入、确认资产和必要证据保留；P1 Superset运行环境是测试依赖，不是另一套正式数仓。验收与回执见[开发文档](../DEVELOPMENT.md)。

> 正式BI维护入口：`dashboard_product/DEPLOYMENT.md`与`docs/bi-production-baseline-20261025.md`。10月26日暂停前回执，服务器raw计算链路已部署并实际运行到39张业务表；真实批次因截止门禁失败而未发布。有效新包正式发布、持续日更和唯一生产者收口分别待验收。通用核心回归可用已有Python3.12执行`python3 -B -m pytest tests dashboard_product/tests dashboard_product/management/tests monitoring_product/tests -p no:cacheprovider`；Superset认证测试在核心环境明确skip，必须另外在固定Superset环境运行`python -B -m unittest tests.test_shadow_bi_legacy_auth`。两类环境分别报告，不把skip计为通过。

# 维护者指南

本文件面向维护 Data OXHor 的开发者和 Agent，不是客户使用说明。项目定位、模块状态和主模块施工记录请先看根目录 [开发文档](../DEVELOPMENT.md)；客户入口请看 [用户指南](./user-guide.md)。

## 代码与测试

- Python 要求 `>=3.12`；运行时核心依赖 DuckDB `1.5.5`。
- 安装开发测试环境：`sh tools/install_runtime.sh test`。
- 运行完整回归：`sh tools/run_tests.sh -v`；入口使用项目 `.venv` 中的 pytest，覆盖 `tests`、`dashboard_product/tests`、`dashboard_product/management/tests`、`monitoring_product/tests`，默认不生成字节码缓存。Project Intelligence的MCP协议测试在未独立安装SDK时明确skip。
- CLI 冒烟：`python3 -m interfaces.data_platform --help`、`python3 -m interfaces.business_pack validate`、`python3 -m interfaces.workspace_modeling --help`、`python3 -m dashboard_product.shadow_bi.p5.raw_inputs --help`、`python3 -m monitoring_product.shared_delivery --help`。
- `dashboard_product/management/calculation.py`、`dashboard_product/online_team/build.py` 和 `dashboard_product/refresh.py` 保留共享计算、受控查询、来源归属及历史对账 helpers；由 raw worker 和原生BI模块调用，不是独立命令行入口。
- 看板回归：`python3 -m unittest discover -s dashboard_product/tests -v`。
- 通知投递适配回归：`python3 -m unittest monitoring_product.tests.test_shared_delivery -v`；mock 测试不连接服务器。服务器发布状态和接口边界以部署回执为准。
- PPT Master 属于宿主全局 Skill；不要在项目内恢复其副本、安装 profile 或完整性测试。
- 项目上下文服务见 [Project Intelligence](./project-intelligence.md)。定向回归：`.venv/bin/python -B -m unittest tests.project_intelligence.test_service -v`，已由主测试发现入口覆盖。新增暴露文件须评审 `project_intelligence/policy.py`，不得直接放开整个目录。

## 维护原则

- CLI 是公开机器接口；变更命令、JSON、路径、退出码或目录合同前，先更新对应合同文档和测试。
- 宿主 Agent、Session、模型和工具选择属于宿主；项目不包装第二层 Agent Loop 或模型路由。
- 只读门禁、Snapshot 身份、Bridge 状态、证据哈希和文件验收由确定性代码负责。
- 新增治理、适配器或平台层必须对应可复现失败或明确客户需求；不要为未来宿主预建协议层。
- 原始客户数据、DuckDB、Parquet、`runs/` 和 `customers/` 不进入 Git。

## 本地瘦身

正式维护范围为“原表入仓 → 上游SQL数仓更新 → BI刷新”，不恢复静态看板。`library.build()`不再写旧验证用 `calculated/*.json`，raw worker从内存model取原关键指标；旧 verifier已退役。已被用户明确废弃的静态HTML/计算副本只保留退役说明和hash，不因旧库存或旧ROI验收提及而长期保存大文件。

独立维护heartbeat“BI已入仓传输原表清理”每周日18:00（Asia/Shanghai）执行，保留期7天。仅清理有完成入仓/新版替代证明且当前与未完成任务不再使用的传输原表、下载/上传暂存及明确退役的原表归档；归档从退役日期起算，不能只凭原文件mtime删除。当前 `Input/Data` 主本、当前Snapshot必要源文件、费用清单引用原表、未完成/失败恢复 `input_backup`、登录态/凭据和业务资产保留。删前存路径/大小/hash及判定证据，删后核对current和数仓可读；没有可删文件就保持安静。该任务不重算、发布BI或变更日更，不维护旧HTML。

2026-10-28已按用户确认完成旧BI数仓退役；清理结果和逐文件SHA见 `.local/audits/single-warehouse-cleanup-20261028/`。只有 `customers/shadow_bi_daily/Work/workspace.json` 及其独立留学current指针定义当前BI数据，不从退役归档恢复为第二个默认数据源。旧结果被清理的回执仅保留历史身份，不再宣称其result/封存包可完整重放。

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

旧静态退出后的进一步死代码/入口复查见[第二轮记录](dashboard-second-pass-20261026.md)。历史阶段文档不作为启动指令，P1环境/依赖锁保留不代表P1实验入口仍在main。

以下为10月26日历史收口状态，10月28日整合见文首。10月26日本地代码、文档与工作树收口见[整合记录](local-project-alignment-20261026.md)。`main`为整合基线；c373保留数据、证据和稳定运行路径，其源码对齐main后以detached HEAD保留，不作为另一条开发分支。服务器raw receiver、只读历史基线、受限双Snapshot/quality/共享聚合计算和固定publisher已有实际部署及运行回执；本地来源完成证明门禁本轮未部署。有效raw包发布、持续日更、唯一生产者切换以及实时调度状态另行验收，本地代码收口不代表这些事项完成。

当前状态、已知限制与本次施工记录统一维护在 [DEVELOPMENT.md](../DEVELOPMENT.md)。[历史交接](history/project-handoff-through-20260918.md) 仅保留过去决策与验收事实，不作为日常操作入口；看板运行以模块 README 和 DEPLOYMENT 为准。

## Project Intelligence MCP 可选测试

在既有虚拟环境单独安装 `mcp==2.2.0`，从源码根目录运行 `.venv/bin/python -B -m unittest tests.project_intelligence.test_service tests.project_intelligence.test_mcp -v`。当前 `pyproject.toml` 不提供 `.[mcp]` extra、Project Intelligence包或console入口，不使用旧安装说明。协议测试启动真实 stdio 子进程，未安装可选依赖时明确 skip，不能据此宣称 MCP 验收通过。详见 [stdio MCP](./project-intelligence-mcp.md)。
