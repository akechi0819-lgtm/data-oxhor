> **2026-10-28唯一正式数据源**：本机main只使用 `customers/shadow_bi_daily`。旧 `bi_operations` 与独立 `shadow_bi_operations` 数仓、c373客户副本和废弃派生成品已清理。原始输入、确认资产和必要证据保留；P1 Superset运行环境是测试依赖，不是另一套正式数仓。验收与回执见[开发文档](../DEVELOPMENT.md)。

日更入口为 `python -m ops run business`。现行调度以 `prepare_full_daily --publish --business-only` 转入同一业务链，发布正式 SQL release 后核验通知。费用通过 `ops ingest-cost` 独立录入。

通用核心回归可用已有Python3.12执行`python3 -B -m pytest tests dashboard_product/tests dashboard_product/management/tests monitoring_product/tests -p no:cacheprovider`；Superset认证测试在核心环境明确skip，必须另外在固定Superset环境运行`python -B -m unittest tests.test_shadow_bi_legacy_auth`。两类环境分别报告，不把skip计为通过。

# 维护者指南

本文件面向维护 Data OXHor 的开发者和 Agent，不是客户使用说明。项目定位、模块状态和主模块施工记录请先看根目录 [开发文档](../DEVELOPMENT.md)；客户入口请看 [用户指南](./user-guide.md)。

## 代码与测试

- Python 要求 `>=3.12`；运行时核心依赖 DuckDB `1.5.5`。
- 安装开发测试环境：`sh tools/install_runtime.sh test`。
- 运行完整回归：`sh tools/run_tests.sh -v`；入口使用项目 `.venv` 中的 pytest，覆盖 `tests`、`dashboard_product/tests`、`dashboard_product/management/tests`、`monitoring_product/tests`，默认不生成字节码缓存。
- CLI 冒烟使用 `python3 -m ops --help`、`python3 -m interfaces.data_platform --help`、`market_workspace/oxhor --help` 及 `python3 -m monitoring_product.shared_delivery --help`。
语培、留学、看板和通知按显式 Snapshot 与 release 追溯。历史静态与 39 表路径已退役。
- 看板回归：`python3 -m unittest discover -s dashboard_product/tests -v`。
- 通知投递适配回归：`python3 -m unittest monitoring_product.tests.test_shared_delivery -v`；mock 测试不连接服务器。服务器发布状态和接口边界以部署回执为准。
- PPT Master 属于宿主全局 Skill；不要在项目内恢复其副本、安装 profile 或完整性测试。

## 维护原则

- CLI 是公开机器接口；变更命令、JSON、路径、退出码或目录合同前，先更新对应合同文档和测试。
- 宿主 Agent、Session、模型和工具选择属于宿主；项目不包装第二层 Agent Loop 或模型路由。
- 只读门禁、Snapshot 身份、证据哈希和文件验收由确定性代码负责。
- 新增治理、适配器或平台层必须对应可复现失败或明确客户需求；不要为未来宿主预建协议层。
- 原始客户数据、DuckDB、Parquet、`runs/` 和 `customers/` 不进入 Git。

## 本地瘦身

正式日更维护范围为“原表入仓 → SQL warehouse build → P4 SQL release activation → BI 刷新”，不恢复静态看板。生产 `--publish` 路径不调用 `library.build()` 生成 39 张逐图 Python 结果表，历史 raw/候选说明仅供回溯。旧 verifier 已退役。已被用户明确废弃的静态 HTML/计算副本只保留退役说明和 hash，不因旧库存或旧 ROI 验收提及而长期保存大文件。

既有维护任务“项目旧产物与传输副本清理”（`bi-2`）的启停及执行时间以宿主调度记录为准。按用户2026-11-09最新确认，以现行依赖和任务是否已结束判断，不再为已被新版替代的发布传输包设置7天等待期。旧失败任务已被后续成功批次替代、所属流程退役或不再支持续跑时，删除无恢复用途的派生产物；只为明确仍在进行的恢复任务保留必要 `input_backup`。已入仓且另有有效主本/明确替代证明的无引用下载副本及时核销，同字节原表只留一份有效主本。

清理范围同时覆盖旧PPT/周报草稿、渲染图、校验PDF、重复导出、确认界面暂存、单次生成程序，以及已结束且不再支撑有效交付的单次拉表/分析记录。每个有价值项目留文档明确指定的一份最终版、不可替代的人工原稿与最小证据；近期未结束的工作保留。引用须追到具体文件及最小依赖闭包，不因历史README、旧脚本提及或缺少初次判断就把整个审计目录长期保护。旧数仓明确退役且现行更新只消费主目录输入/当前SQL仓时，旧日期全量工作簿和试验工作区原件不再属于现行输入；经实际读路径核查和当前输入可读验证后可核销，不要求为每份旧表找到相同SHA替身。旧P3/P4独立校验脚本的历史路径不等于正式SQL更新依赖。无法判定者记录具体依赖或缺失证明，不能笼统标“可能有用”。

保护当前 `Work/workspace.json`、留学current及 `Output/ShadowDaily/sql-current.json` 指定的身份、SQL候选和真实输入依赖，以及当前Snapshot、`Input/Data`主本、费用清单实际引用原表、官方记分卡、有效报告的必要证据、登录态/凭据、运行环境和DeliveryState。删除前记录具体路径/大小/SHA与完成或替代证据，删后复核保护文件和指针未变，并通过现有Data Platform受控入口验证当前双Snapshot与SQL库可读。保留小型清理清单及回执；受影响旧manifest/查询回执标记历史不可完整回放。该任务只做本地清理，不接管浏览器采集、数据更新、云端同步、BI发布、日报或日程，不恢复静态HTML产品。

2026-10-28已按用户确认完成旧BI数仓退役；清理结果和逐文件SHA见 `.local/audits/single-warehouse-cleanup-20261028/`。只有 `customers/shadow_bi_daily/Work/workspace.json` 及其独立留学current指针定义当前BI数据，不从退役归档恢复为第二个默认数据源。旧结果被清理的回执仅保留历史身份，不再宣称其result/封存包可完整重放。

- 先核对磁盘占用、当前工作树、`Work/workspace.json`、明确封存/验收批次及未完成迁移。不得按 `latest`、修改时间或目录名猜测保留对象，也不撤销其他任务的未提交改动。
- 可再生成的 Python/测试缓存可清理。看板试制批次被明确最终版替代后，可删除其重复网页、展示包与计算副本；保留查询证据、回执、对账/验收记录和批次身份，并在原批次写清清理记录。正式交付及其引用闭包不随试制缓存删除。
- BI重建的本次下载、合并及两个来源临时保留位于 `Work/Runs/_bi_rebuild_tmp/<本次唯一目录>/`；正常成功或明确失败恢复后删除。错误中明确标记保留的 `input_backup/` 若仍为进行中的恢复任务所需，不按缓存删除；旧任务已被替代或不再支持续跑时按最新清理规则核销。旧 `_bi_downloads` 不再是运行入口，历史残留只在任务停止且所需导出另有有效留存后按清单核销。`_bi_export_keep/<snapshot_id>` 保存原始BI导出审计副本；旧Snapshot、历史landing与原始输入不按年龄批删。
- 同步outbox、staging及backup在目标安装/接收验收前保留；包哈希代表固定批次，清理本机后不原地改写已有包。后续传输须明确使用原封存包或重新制作瘦身后的新批次。登录profile、auth session、密钥及投递去重状态不纳入缓存扫描。
- 清理只按具体路径清单执行，不跟随软链；删除前记录路径、用途、体积和哈希，删除后验证保留文件、证据及最终产物可用。审计和回执放 `.local/audits/<任务>/`，不新增常驻清理服务。

已退役的 SQL release 可按退役回执的 `removed` 精确匹配旧 release。在 `Output/ShadowDaily/<批次>/sql-attempts/<release>/release-output/` 核对传输包和封装仓，确认 `.local/sql-daily/candidates/<release>/warehouse.duckdb` 实物摘要与发布清单一致后，核销已完成传输的包与重复仓。保护当前指针、验收合同、处于恢复中的批次及具体仍在使用的历史文件。

每次清理还要逐份核对 `.local/sql-daily/candidates/`。本机日更通过 `load_sql_current` 读取 `sql-current.json` 指定的费用基线和迁移验收 JSON。验收文件登记旧仓摘要，仅在有现行代码或明确复算任务实际读取旧仓时才保留相应实物。发布激活失败时，回滚代码在服务器上恢复切换前的正式 release；成功切换并完成核验后，退役回执的 `removed` 标识已退役版本。核验发布锁和恢复任务，有并发更新时延期。

保留当前指针所指候选，以及正在执行的构建、回滚、恢复或明确复算任务实际读取的候选及必要附件。旧候选曾用于上一步传输包比对，完成比对后即可按同一规则核销。已替代或已结束的失败候选按具体任务回执清理，并留下批次、SHA、替代依据和原路径不可完整回放说明。清后再跑 `load_sql_current`、双 Snapshot 受控读取和 SQL 候选只读查询。发布逻辑见[本机日更](../dashboard_product/shadow_bi/p5/sql_daily.py)及[服务端切换与退役](../dashboard_product/shadow_bi/p4/sql_release.py)。

## 发布前检查

1. `git status --short`，确认没有客户数据、运行产物或无关文件。
2. `git diff --check`。
3. 运行完整测试和涉及模块的 CLI 冒烟。
4. 检查 README、用户指南、架构和运维文档是否仍描述当前运行角色。
5. 检查第三方声明、上游固定版本和许可证文件。
6. 使用 GitHub CLI 提交并推送前，确认目标仓库、分支和提交范围。

## 当前状态与历史记录

旧静态退出后的进一步死代码/入口复查见[第二轮记录](archive/dashboard-second-pass-20261026.md)。历史阶段文档不作为启动指令，P1环境/依赖锁保留不代表P1实验入口仍在main。

以下为10月26日历史收口状态，10月28日整合见文首。10月26日本地代码、文档与工作树收口见[整合记录](archive/local-project-alignment-20261026.md)。`main`为整合基线；c373保留数据、证据和稳定运行路径，其源码对齐main后以detached HEAD保留，不作为另一条开发分支。服务器raw receiver、只读历史基线、受限双Snapshot/quality/共享聚合计算和固定publisher当时已有实际部署及运行回执；raw候选因截止门禁失败而未发布。此段仅记录历史状态；旧 raw 通道后于 2026-11-07 SQL 切换时退役，当前发布入口与状态见本页顶部及[看板部署说明](../dashboard_product/DEPLOYMENT.md)。

当前状态、已知限制与本次施工记录统一维护在 [DEVELOPMENT.md](../DEVELOPMENT.md)。[历史交接](history/project-handoff-through-20260918.md) 仅保留过去决策与验收事实，不作为日常操作入口；看板运行以模块 README 和 DEPLOYMENT 为准。
