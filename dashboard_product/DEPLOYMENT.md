# 正式 BI 部署与运行

## 最新业务组筛选状态（2026-11-07）

正式 release `daily-sql-overview-group-20261107` 已激活。市场总览的业务组筛选为“市场总计／高中／大学／留学预备”；语培按所选业务组汇总线上、线下各渠道产出，留学及小语种固定显示总盘。11 张语培图联动该筛选，语培学校图已补入；其他页面的口径和样式保持不变。

原有 5,508 行指标与旧仓一致，新增 243 行分组指标与明细独立核算一致；40 项测试通过，2 项按条件跳过。费用为 4,041 行、43 个来源，标注截至 2026-11-06；复用同一批数据，不重采业务及费用源表、不触发日报推送。18 项正式指标与 MCP 5 项检查通过。bi-3 只读复查通过，采集、发布及通知回调均为 0；正式站 93 图、270 个业务分页已完成核对，字段、行数及记录集合全部一致；旧版已退役，服务器仅保留 1 份分析仓，投递状态逐字节不变。

公网默认总盘复查的图 327 在 `offset=800` 触发 cgroup OOM 并返回 HTTP 502，服务随后自动恢复。检查记录显示宿主总内存约 8 GB、`MemAvailable` 约 6.5 GB，而 dashboard 服务 `MemoryMax` 为 1400M；Gunicorn 为 3 threads，DuckDB 查询内存配置为 1,100 MB，说明现有服务 cgroup 上限未适配 SQL 查询模式。生产 `MemoryMax` 已通过 `systemctl set-property` 无重启调至 4G，并在持久 drop-in 中读回；`MainPID` 未变，`NRestarts=1` 为此前 OOM 自动恢复后的值。本次配置只改 `MemoryMax`，不改线程数、DuckDB 限制或数据。修正后已完成 3 并发故障分页复测与剩余 14 图的顺序补验，图 327 全部 46 页、2,291 行逐行逐顺序一致，前 79 图复用同一不可变版本的完整成功结果；服务未新增重启，全部有效业务分页已收齐。证据：[502-inspection.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/502-inspection.json>)、[memory-budget-application.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/memory-budget-application.json>)。

证据：[activation.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/activation.json>)、[publication-receipt.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/publication-receipt.json>)；本批审计目录：[overview-group-20261107](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/>).

最终核验：88 张图逐行顺序相同；5 张图（231、320、331、332、333）仅同值并列行换位，93 张图完整记录集合相同。保留原排序规则；图 231 原网页分页现象未作次排序修复，完整 CSV 的 59 条唯一记录与旧版一致。线上曾触发旧 1400M 服务限额 OOM，已持久调至 4G，3 并发与后续全页复验通过；未改数据、线程数或查询内存配置。

最终回执：[completion.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/completion.json>)。

## 历史：业务组筛选发布前的链路及费用恢复记录（2026-11-07）

当前正式费用版为 `daily-sql-20261107-153941950641-7520a35133`；语培、留学和费用更新标注均为 2026-11-06，费用受控查询确认 4,041 行、43 个来源。原总入口费用补跑已成功，最终 complete／退出码 0；复用今日双 Snapshot，不重新采集业务。18 条经营指标补跑前后相同，正式单仓、18 项激活指标、MCP 5 表及公网查询通过。

本次费用恢复没有发日报：发送入口调用 0 次，补跑前后全部 96 条投递记录逐值不变；今日此前 8 条 sent 保持原记录。最初业务实测的旧 88 条记录也未变；工单反馈此前新增 15 条且已读回。既有费用覆盖缺口仍如实展示，不补零。

最新证据见[费用补跑结果](</Users/akechi/Desktop/manager -CowH/.local/audits/sql-fee-recovery-20261107/费用补跑结果.md>)。此前[首次业务实测结果](</Users/akechi/Desktop/manager -CowH/.local/audits/sql-daily-e2e-20261107/完整流程实测结果.md>)记录了当时的费用认证失败；该阶段现已恢复。下方迁移首发记录保留当时批次和日期，当前状态以最新回执为准。

## 迁移首发部署记录（2026-11-07）：已切换并完成旧仓清理

正式 current 为 `daily-sql-20261106-cutover-20261107`，业务批次 `run_sql_online_exact_20261107`；绑定 2026-11-06 的原双 Snapshot，语培、留学和费用均截至 2026-11-05。仓库 SHA-256 `155840e6fd3cf348aa42f62ad7b97fc26b36b15283e22c6cd71b9740b1cc4fee`。本地同批核验的 93 份 CSV 字节一致、93 份 XLSX 语义一致；正式切换后 94/94 API 请求及 12 份导出与旧线上一致。

chart 231 保留原有分页表现：网页返回 59 行、58 条唯一记录，跨页重复一行；完整 CSV 含 59 条唯一记录，与旧导出一致，没有完整导出数据丢失。页面覆盖 7 个页签、43 个分区；截图对照不宣称逐像素相同。

bi-3 仍为每天 09:30，原命令、来源和日程不变；提示词仅更新两处 SQL 说明。本次未触发新日更、通知或推送。46 项运行文件哈希、18 项业务指标、MCP 5 项检查及 8 条 dry-run 通知状态均通过／保持不变；DeliveryState 未变，未发送通知。

旧服务器仓清理已完成：分析仓从 37 份收敛为 1 份；旧正式版本 164 个文件已归档本地，旧候选、校验仓及 raw 计算／传输目录已清理。保留必要运行文件、Superset 元数据库、配置密钥、DeliveryState 与有限运维日志。清理后运行检查通过，旧业务发布路径停用，通知路径保留。

完整验收证据已归档到主目录 `.local/archive/business-sql-local-20261111/sql-migration/online-acceptance-20261107/`，详见[上线结果与 bi-3 衔接回执](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/sql-migration/online-acceptance-20261107/上线结果与BI3衔接.md>)。原 checkout 的日更基线位于 `.local/sql-daily/candidates/`，显式指针位于 `customers/shadow_bi_daily/Output/ShadowDaily/sql-current.json`；本批验收证据保留在上述主目录归档。以下标明“历史”的未上线描述仅记录其当时状态，不是现行操作指令。

## 历史：SQL 切换前核验状态（2026-11-07）

本地候选 `.local/sql-migration/online-acceptance-20261107/candidate-current-lineage/warehouse.duckdb`（批次 `run_sql_online_exact_20261107`，SHA-256 `155840e6fd3cf348aa42f62ad7b97fc26b36b15283e22c6cd71b9740b1cc4fee`）使用 2026-11-06 同一双 Snapshot，业务和费用均截至 11 月 5 日，费用 3,975 行、43 个来源。93 份 CSV 字节一致、93 份 XLSX 工作簿语义一致；269 个 API 页仍在复验。图表 231 旧端分页有 1 条跨页重复并漏显 1 条独立记录，新端为 59 条唯一记录；完整 CSV/XLSX 一致，不把所有分页顺序宣称为完全一致。43 个分区覆盖 41 个完整分区及 2 个自然补拍；本期紫 `#454E7C`、同期绿 `#5AC189` 已在本地恢复，5 个分区还在补验。详情见[SQL迁移验收](../docs/shadow-bi-sql-local-migration.md)。

Mac 保持 bi-3 来源和日程不变；当前 worktree 的 `p5.daily` 使用 SQL 仓库发布段，不再调用 Python `calculate` 生成 39 张逐图结果表。服务器仍未切到该代码或候选。目标 release 为七个运行文件和一份 `warehouse.duckdb`，由 Superset、MCP 与通知共用同批仓库。费用刷新失败保留上一批已提交费用及其日期，不阻断已成功的业务发布和通知。旧 SQL release 仅在成功核验后经独立维护回执退役。

### 历史：切换前接线计划（现已完成，以顶部部署回执为准）

- Superset 数据集、页眉及 options 接入 `/srv/shadow-bi/code`；保留 159 个数据集、8 个 options、图表、筛选与权限元数据，改用同一仓库 URI，并清除旧结果缓存、dispose 旧连接。
- 旧业务 receiver 代码位于 `/srv/shadow-bi/raw-code`。新链路通过门禁后退役旧 39 表业务上传／计算通道；通知接收仍保留。
- 通知接线位于 `/srv/shadow-bi-notify/current` 和固定入口 `/usr/local/sbin/shadow-bi-notify`。读取 SQL release 通知预览，保留原 `DeliveryState`、消息去重和 no-backfill；不重发已发送消息。
- MCP 使用 `/srv/business-data-mcp/venv/lib/python3.12/site-packages`，ACL 同步入口为 `/usr/local/libexec/business-data-mcp/acl_sync.py`，需同步 venv `ExecStart` drop-in；查询与 Superset 使用同一个显式 release。
- 切换时停用旧 `shadow-bi-publisher.path`、`shadow-bi-receiver-publish.path` 及 raw 接收／计算／发布入口；保留 `shadow-bi-receiver-notify.path`。失败时回滚 URI 与 `current`。首轮先将旧仓归档到本地，核销 32+4 份旧仓依赖后再收敛为单仓。

## 历史部署记录：云端基础仓日更（2026-11-04）

正式看板继续使用原生 Superset。服务器 `/srv/shadow-bi/code` 中的 `dashboard_product.shadow_bi.p5.foundation_candidate prepare` 接收显式配对的基础 Snapshot 并执行共享计算，P4 切换 current，P5 对照普通看板数据验版。语培签约来源是现金明细，`现金收入` 和 `报入现金收入` 分列。留学签约采用签约金额，小语种采用实缴金额。看板筛选只作用于业务库。原始基础仓仅面向被授权的服务端查询执行者。

在服务器固定 `release=$(readlink -f /var/lib/shadow-bi/current)`，从两个基础指针读取 Snapshot ID 和仓库相对路径。使用 `/srv/shadow-bi/venv/bin/python -m interfaces.data_platform describe --warehouse "$release/foundation/<对应相对路径>" --snapshot-id <显式ID>` 查看字段。查询改用 `query`，另传 `--sql-file <只读SQL> --run-id <唯一run_标识> --output-root <私有回执目录>`。项目代码工作目录为 `/srv/shadow-bi/code`。完整基础表为语培 landing 下的 br_work_orders、br_cash 两表，以及留学 landing 下的 resources、contracts、languages 三表。物理表名由 describe 返回。跨日重新固定 release，过期版本不再提供查询。

单次费用快照进入当批计算。服务器仅保留当前成功发布，旧版保留至候选验版通过。文件交付与指标对账证据在本机 `.local/audits/cloud-foundation-20261104/`，机器交接说明在 `.local/handoffs/business-data-mcp-foundation-20261104/completion.json`。

> **2026-11-04 明确线上来源纠正验收**：本机与云端current为`daily-20261104-online-routing`，最终批次online3，数据仍截至11/3。明确平台投放归平台，虚拟人与SSC归对应板块，三个团队独立；外呼、死单返打等保护记录未迁移，国家分布口径按用户要求保持原样。58项测试/23个子测试、两端普通读者82项查询导出和8组团队指标通过，19源码SHA一致，服务active。全期间全范围市场工单、现金、去重人头不变。无重采、通知、日程操作。证据见`.local/audits/online-source-routing-20261104/`。

> **2026-11-04 TMK平台归属修正验收**：该轮本机与云端current为`daily-20261104-tmk-platform`，数据截至11/3。原资源或规范一级渠道为“TMK激活-平台”统一归线上平台，大学、高中、留学预备及虚拟人旧归属同步纠正，其他TMK规则保持。FY27被动共转入线上20条工单及1,791,660.50元现金；市场各期间/范围的工单、现金、去重人头不变。60项测试及5个子测试、本机大学下钻、两端普通读者82项查询/导出检查通过，17文件SHA一致，服务active。学校分类与可读导出保留。同步前磁盘不足仅影响传输，核对本机完整封存与已安装摘要后清理明确的重复中转包，正式及回滚版本保留。未重采、通知或改日程。证据见`.local/audits/tmk-platform-routing-20261104/`。

> **2026-11-04大学渠道与导出更新验收**：该轮本机与云端current为`daily-20261104-channels2`，复用11/4既有双Snapshot，数据仍截至11/3。大学渠道支持“渠道→学校分类→学校”，全看板CSV/XLSX下载转换为中文层级与数值列。普通阅读账号在两端各完成79张表双格式下载和3组大学期间查询，留学预备筛选权限同步复验通过；11个运行源文件SHA一致，服务active。首次导出内存失败已回滚并通过期间预筛选修复，最终完整复验通过，未提高服务内存限制。没有重采、通知或日程操作。规则与验收见`shadow_bi/README-P3.md`和`.local/audits/university-channel-export-20261104/`。

> **2026-11-03云端源码更新验收**：正式代码`/srv/shadow-bi/code`与固定通知代码current（`bi3-20261103-3fea1baf8401393a`）均完成127文件SHA核对及隔离品牌非空／原生费用入仓回归。当前日更由Mac bi-3上海09:30运行`data_acquisition.jobs.prepare_full_daily`，用新BI来源与腾讯竞价＋品牌v2合同采集后，通过新进程执行云端P4和原通知入口；不是恢复raw采集。业务current仍`daily-20261103_141437`，DeliveryState未变，raw path仍inactive，未新增日程、未重新发布或发送。同步仅A层源码，不含Mac登录态或MCP密钥。详见`.local/audits/tencent-brand-cloud-code-20261103/completion.md`。下方旧日期记录不代表当前源码未部署。

> **2026-10-29进度与目标更新**：云端及本地发布指针已同步为 `daily-20261029-ui`，复用当天既有双 Snapshot，数据仍截至10月28日，没有重新采集或更新数仓。经营页顶部时间进度随月、季度、全年筛选；个人区使用独立月份与绩效月/自然月窗口。大学四人11月语培目标合计271、留学目标合计110；11月留学采用用户明确目标，历史月份维持原10%规则。47项相关测试、20组经营窗口、12组个人窗口及18项业务指标验收通过；证据在 `.local/audits/progress-bars-20261029/`。未改通知或日程。

> **2026-10-28本地收口**：main唯一正式数据工作区为 `customers/shadow_bi_daily`；旧正式仓、重导基线仓、c373客户镜像和旧派生成品已退役。当时本地发布回执为 `daily-20261028_104710`，该轮没有重新发布或核验服务器current，也未修改外部日程。P3默认从该工作区current指针定位库；服务器显式环境配置不变。状态与清理验收见[开发文档](../DEVELOPMENT.md)。

> **10月26日运行记录**：raw接收/计算/发布已暂停，保留Mac更新链路与既有成品/通知入口；服务器数仓和聚合代码能力仍保留。以[清理与暂停回执](../docs/server-cleanup-20261026.md)区分能力部署与当前启停。本轮未实读或修改服务器/日程，以下raw说明为代码/已部署能力合同，不是恢复运行指令。

> **以下为暂停前的部署/验收回顾；最新运行安排以上方清理回执为准。** 正式产品为 Superset 原生 BI。已部署服务器 raw receiver、root 只读历史基线、受限双 Snapshot / quality / 共享计算 worker 和固定 publisher。10月26日真实 Dot 批次已在服务器实际完成双 Snapshot、两份 quality 查询并运行到39张表，最终因业务截止不匹配以 `failed/published=false` 结束，没有发布 raw release。Mac `p5.daily` 是仍存在的手动入口；日期回执记录它更新了 `daily-20261026_094052`（数据截至10-25），不代表长期默认路径。有效新 raw 包正式发布、持续日更和唯一生产者收口仍待分别验收。

## 历史：旧服务器部署能力与暂停前验收

- Superset、`shadow-bi.service`、代码 `/srv/shadow-bi/code`、环境 `/srv/shadow-bi/venv` 和私有数据 `/var/lib/shadow-bi` 已部署；`current/library/business.duckdb` 为正式 BI 的业务库，PostgreSQL 保存 Superset 元数据。
- 服务器raw链路已部署、最新记录为暂停：外部接收写入固定队列；受限 worker 读取 root 只读历史基线，在新副本内合并历史、建立双 Snapshot、运行 quality 和共享业务计算，生成39张封存业务表；root 固定 publisher 使用 P4 重建、校验和原子切版。
- **真实计算已在服务器运行。** `raw-20261026-dot-001` 三源/TAR hash 与输入一致，双 Snapshot、两份 quality 查询及39个 JSONL 文件/类型库完整性核验有回执。最终候选 `data_through=2026-10-24`，低于当日要求的 `2026-10-25`，在最终业务截止门禁失败，状态 `failed/published=false`；该批没有发布或切换 current。截止门禁先于物理库 COUNT 门禁，因此不能称为全门禁通过或正式发布。
- 固定 publisher 已独立部署并通过权限、负例及HTTP边界验证；worker 不能写生产 current/releases。publisher 只处理明确为 `prepared` 的同批候选，失败后保留开始时 current 并记录结果。10月26日失败候选未达到 `prepared`，没有调用它发布该批。
- 该日期的 BI current 记录为 `daily-20261026_094052`（数据截止10-25）；回执记录由 Mac `dashboard_product.shadow_bi.p5.daily` 手动更新。最新清理回执明确保留该Mac命令更新链路；本轮不改其日程。当前实时 current 应在需要操作时按服务器 manifest 核验；本轮未实读。
- 服务器计算与发布能力已落地；尚待验收的是有效新 raw 包正式发布、持续日更安排及唯一生产者收口。来源完整性证明门禁已进入本地 `main`，10月26日部署的服务器版本不含该新门禁，不能据此声称服务器已启用。

详细服务权限、基线和批次证据见[raw接收部署回执](../docs/server-raw-receiver-deployment-20261026.md)、[固定publisher回执](../docs/server-raw-fixed-publisher-20261026.md)及[raw链路合同](../docs/server-raw-pipeline-contract.md)。

### 历史 raw 代码合同（路径当前暂停）

固定外部接口为 `POST /shadow-bi/v1/raw-batches` 与 `GET /shadow-bi/v1/raw-batches/<batch>`。只接收合同规定的三 Excel 包；请求不能指定服务器路径、命令、SQL、Snapshot ID 或发布参数。接收、入队、计算、prepare 和正式发布是不同状态；超时或HTTP错误后按同一批次ID查询状态，不盲目重传。

发布使用同批固定请求 `POST /shadow-bi/v1/raw-batches/<batch>/publish-prepared`，请求体只能是空对象 `{}`。只有 `prepared` 且来源任务、输入窗口、Snapshot 身份和质量已经核实后，才按明确授权触发；该请求不支持跳过门禁、指定路径或任意命令。状态以 GET 回执为准。received/queued 或计算达到39表都不等于 prepared，更不等于 published。

10月26日真实批次 `raw-20261026-dot-001` 的候选业务覆盖实际到10月24日，低于入口要求的10月25日。未改日期、未重算；候选和失败日志保留，既有 current 未被该批修改。将来若获授权恢复raw，才按`raw-20261026`部署代码对应的合同验收完整输入、双 Snapshot、quality、39表、业务身份、实际查询和页面；对本地新增的来源完成证明门禁也须先完成服务器部署验收，不能从旧回执推断它已生效。

服务器使用 `shadow_bi/p4/rebuild.py` 重建候选库，并由固定publisher在持锁状态下完成 manifest、页面/业务查询、失败恢复和切换。P4用于发布已验收批次；它不是把任意候选或失败批次提升为正式数据的绕行入口。历史切版演练不授权正常发布倒退截止日。

### 历史通知与自动化记录

服务器通知适配已部署：`monitoring_product.release_notifications` 从正式 BI release 构建同批通知包，`shared_delivery` 执行状态去重与传输；通知不独立查询或重算数仓。2026-10-26 人工触发有8条 `sent` 记录。HTTP job `9cbbb2…` 仍保留 `unknown/retryable=false`；独立只读对账回执将它关联到此前已发送的8条消息，`no_send_performed=true`，不表示该job自身成功发送。不得重发这些消息或清空 DeliveryState。详见[通知作业修复回执](../docs/notification-job-receipt-repair-20261026.md)。

记录中自2026-10-26起的 Dot 上海10:00日程用于通知触发，和 BI 采集/刷新分开管理；Grok 例行按用户要求停止。日期回执曾记录 Mac `bi-2` 为 ACTIVE/09:40，但本轮未读取调度平台实时状态，不据此推断当前任务启停。持续日更和唯一生产者切换须分别留下验收回执，不从代码合并、通知日程或单次计算推断完成。
