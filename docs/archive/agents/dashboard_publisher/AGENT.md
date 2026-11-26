# 看板发布 Agent

## 最新业务组筛选状态（2026-11-07）

正式 release `daily-sql-overview-group-20261107` 已激活。市场总览的业务组筛选为“市场总计／高中／大学／留学预备”；语培按所选业务组汇总线上、线下各渠道产出，留学及小语种固定显示总盘。11 张语培图联动该筛选，语培学校图已补入；其他页面的口径和样式保持不变。

原有 5,508 行指标与旧仓一致，新增 243 行分组指标与明细独立核算一致；40 项测试通过，2 项按条件跳过。费用为 4,041 行、43 个来源，标注截至 2026-11-06；复用同一批数据，不重采业务及费用源表、不触发日报推送。18 项正式指标与 MCP 5 项检查通过。bi-3 只读复查通过，采集、发布及通知回调均为 0；正式站 93 图、270 个业务分页已完成核对，字段、行数及记录集合全部一致；旧版已退役，服务器仅保留 1 份分析仓，投递状态逐字节不变。

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

本地候选 `run_sql_online_exact_20261107` 使用 2026-11-06 的双 Snapshot，业务和费用均截至 11 月 5 日；费用 3,975 行、43 个来源，warehouse SHA-256 `155840e6fd3cf348aa42f62ad7b97fc26b36b15283e22c6cd71b9740b1cc4fee`。93 份 CSV 字节一致、93 份 XLSX 工作簿语义一致，269 个 API 页仍在复验。图表 231 旧端分页出现 1 行跨页重复并漏显 1 条独立记录，新端返回 59 条唯一记录；完整导出一致，不宣称全部分页有序一致。当前 43 个分区由 41 个完整分区和 2 个自然补拍组成；本期紫 `#454E7C`、同期绿 `#5AC189` 已在本地恢复，5 个分区补验中。详见[SQL 迁移验收](../../../shadow-bi-sql-local-migration.md)。候选与代码未安装到服务器，未切换生产 `current`。

Mac 保持现有 bi-3 来源与日程。本 worktree 中 `prepare_full_daily --publish` 的业务优先阶段进入 `p5.daily` SQL 路径：本地建仓、打包七个运行文件并由 P4 SQL activation 发布单一 warehouse；不再调用 Python `calculate` 生成 39 张逐图业务表。业务通知仍沿原同批顺序；费用刷新失败保留上批已提交费用与原费用日期，不阻断已完成业务发布后的通知。

生产切换须在本地同批核验完成后另行办理：Superset `/srv/shadow-bi/code`、旧 receiver `/srv/shadow-bi/raw-code`、通知 `/srv/shadow-bi-notify/current` 与 `/usr/local/sbin/shadow-bi-notify`、MCP venv `site-packages` 和 `/usr/local/libexec/business-data-mcp/acl_sync.py`／venv `ExecStart` drop-in 指向同一 release。停旧 `shadow-bi-publisher.path`、`shadow-bi-receiver-publish.path` 及 raw 业务处理入口，保留 `shadow-bi-receiver-notify.path`；切换失败回滚 current 与 URI。旧仓先本地归档，核销 32+4 份旧仓依赖后再收敛至单仓。旧 SQL release 在成功核验后另走独立维护回执退役。本轮不操作服务器、日程、正式数据、消息或 `DeliveryState`。

## 历史：云端基础仓日更（2026-11-04）

正式日更由 Mac 采集配对基础 Snapshot，服务器执行受控 SQL 和共享计算后发布 Superset。费用使用单批表格快照。验版成功后只保留当前版本。发布与排查见[现行日更说明](../../shadow-bi-full-daily-20261028.md)。下文带日期的旧部署记录仅供追溯。

> **当前 Mac 日更入口**：`data_acquisition.jobs.prepare_full_daily --publish` 按业务基础发布→立即通知→广告费用采集与发布执行；默认模式（含 `--prepare`）只生成隔离候选。11/3回执记录云端127个源文件SHA与本机一致，并记载次日 bi-3 由本机09:30采集；该日期回执不是当前实时调度核验。服务器 raw 接收/计算/发布 path 仍 inactive；10/26暂停与失败批次保留为历史。

## 历史：切换前 Mac 日更总入口说明

正式 BI 产品继续为 Superset 原生看板，稳定代码路径为 `dashboard_product.shadow_bi`。`prepare_full_daily --publish` 的来源和 bi-3 日程保持原样；当前 worktree 将业务优先后的仓库构建／发布段接到 `p5.daily` SQL producer。未指定 `--publish` 时仍只生成隔离候选。此 SQL producer 是本地源码状态，不代表正式服务器已经安装或切换。

11/3完成回执记录正式代码目录与独立通知 current 的127个源文件 SHA 均与本机一致；本次代码同步验收未伴随业务数据发布或通知重发。回执记载 bi-3 次日仍由 Mac 本机09:30执行，但它是有日期的验收记录，不是实时调度状态查询。腾讯文档下载统一走官方 MCP，旧 Cookie 下载器已从两个现行代码目录退役。

费用采集不是仅靠人工上传：已配置来源由总入口采集并执行来源门禁。腾讯广告品牌非空数据可自动分页、对账与入仓，无需人工补品牌明细；这项自动流程不覆盖所有来源。腾讯语培费用源尚未接入，SEM 完成标记缺失及226条空金额仍如实缺失，不能补零或把缺口说成完整。

10/26清理回执记录服务器 raw 接收/计算/发布暂停；11/3完成回执仍记载该路径未启用。10/26 Dot raw 批次因业务截止不匹配以 `failed/published=false` 结束，没有生成 raw release。此前 `received`、`prepared`、`failed`、`published` 状态机和固定 raw publisher合同仅用于该服务器路径；不得据此恢复未启用路径。正式部署状态及历史操作边界见[部署说明](../../../../dashboard_product/DEPLOYMENT.md)、[接收回执](../../server-raw-receiver-deployment-20261026.md)和[publisher回执](../../server-raw-fixed-publisher-20261026.md)。

本地 `main` 另加入受保护来源完成证明门禁，要求计算、候选复用和固定发布校验同一证明。10月26日服务器部署回执对应版本尚不含此项新门禁，不能把本地整合说成服务器已安装。合同见[raw链路](../../../server-raw-pipeline-contract.md)和[来源完整性](../../../server-source-completion-candidate.md)。

## 共享计算与通知

旧 raw／39 表路线中的 `management/calculation.py` 仍属历史共享计算入口；新 SQL producer 通过 `dashboard_product.shadow_bi.sql_warehouse` 生成单库，不调用该函数重建 39 张图表结果表。人员规则及花名册仍归 `workspace_modeling/operations/`。

正式通知入口为 `monitoring_product.server_notify`，由 `release_notifications` 从固定正式 release 构建通知包，再调用 `shared_delivery` 去重投递；通知不独立查询或重算数仓。10月26日历史通知批次有8条 `sent` 记录，关联HTTP job仍为 `unknown`，只读对账不等于该job自身发送成功；不得据此重发或清空 DeliveryState。详见[通知作业回执](../../notification-job-receipt-repair-20261026.md)。

数据查询遵循已确认工作区、Snapshot、Pack、Bridge、来源和参考资料边界。不得读取或复制凭据，不将客户输入、整个工作区或运行产物加入Git。未来MCP权限不由BI上线自动授予。

本机 SQL 候选的保留与核销由既有清理任务按[维护者指南](../../../maintainer-guide.md)执行。发布任务按批次记录激活、退役及待恢复状态，便于清理任务识别仍在使用的仓库。
