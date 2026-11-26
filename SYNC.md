# 正式看板同步边界

正式看板与日报使用云端同一套数仓，以固定 SQL 更新。业务数据仅同步经校验的基础表增量。费用仅同步独立确认的明细。旧阶段的整 Snapshot、39 表投影及本机成品库传输见下方历史回执。当前命令、来源及回滚路径见[看板部署说明](dashboard_product/DEPLOYMENT.md)和[运维手册](docs/operator-runbook.md)。

## 历史：SQL 看板迁移同步边界（2026-11-07）

## 最新完整链路实测及费用恢复（2026-11-07）

当前正式费用版为 `daily-sql-20261107-153941950641-7520a35133`；语培、留学和费用更新标注均为 2026-11-06，费用受控查询确认 4,041 行、43 个来源。原总入口费用补跑已成功，最终 complete／退出码 0；复用今日双 Snapshot，不重新采集业务。18 条经营指标补跑前后相同，正式单仓、18 项激活指标、MCP 5 表及公网查询通过。

本次费用恢复没有发日报：发送入口调用 0 次，补跑前后全部 96 条投递记录逐值不变；今日此前 8 条 sent 保持原记录。最初业务实测的旧 88 条记录也未变；工单反馈此前新增 15 条且已读回。既有费用覆盖缺口仍如实展示，不补零。

最新证据见[费用补跑结果](</Users/akechi/Desktop/manager -CowH/.local/audits/sql-fee-recovery-20261107/费用补跑结果.md>)。此前[首次业务实测结果](</Users/akechi/Desktop/manager -CowH/.local/audits/sql-daily-e2e-20261107/完整流程实测结果.md>)记录了当时的费用认证失败；该阶段现已恢复。下方迁移首发记录保留当时批次和日期，当前状态以最新回执为准。

## 迁移首发部署记录（2026-11-07）：已切换并完成旧仓清理

正式 current 为 `daily-sql-20261106-cutover-20261107`，业务批次 `run_sql_online_exact_20261107`；绑定 2026-11-06 的原双 Snapshot，语培、留学和费用均截至 2026-11-05。仓库 SHA-256 `155840e6fd3cf348aa42f62ad7b97fc26b36b15283e22c6cd71b9740b1cc4fee`。本地同批核验的 93 份 CSV 字节一致、93 份 XLSX 语义一致；正式切换后 94/94 API 请求及 12 份导出与旧线上一致。

chart 231 保留原有分页表现：网页返回 59 行、58 条唯一记录，跨页重复一行；完整 CSV 含 59 条唯一记录，与旧导出一致，没有完整导出数据丢失。页面覆盖 7 个页签、43 个分区；截图对照不宣称逐像素相同。

bi-3 仍为每天 09:30，原命令、来源和日程不变；提示词仅更新两处 SQL 说明。本次未触发新日更、通知或推送。46 项运行文件哈希、18 项业务指标、MCP 5 项检查及 8 条 dry-run 通知状态均通过／保持不变；DeliveryState 未变，未发送通知。

旧服务器仓清理已完成：分析仓从 37 份收敛为 1 份；旧正式版本 164 个文件已归档本地，旧候选、校验仓及 raw 计算／传输目录已清理。保留必要运行文件、Superset 元数据库、配置密钥、DeliveryState 与有限运维日志。清理后运行检查通过，旧业务发布路径停用，通知路径保留。

完整验收证据已归档到主目录 `.local/archive/business-sql-local-20261111/sql-migration/online-acceptance-20261107/`，详见[上线结果与 bi-3 衔接回执](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/sql-migration/online-acceptance-20261107/上线结果与BI3衔接.md>)。原 checkout 的日更基线位于 `.local/sql-daily/candidates/`，显式指针位于 `customers/shadow_bi_daily/Output/ShadowDaily/sql-current.json`；本批验收证据保留在上述主目录归档。以下标明“历史”的未上线描述仅记录其当时状态，不是现行操作指令。


当前 SQL 候选和接线代码只在隔离 worktree 验收。候选批次 `run_sql_online_exact_20261107` 绑定 2026-11-06 的同一双 Snapshot，业务／费用截至 11 月 5 日，费用 3,975 行、43 个来源；warehouse SHA-256 为 `155840e6fd3cf348aa42f62ad7b97fc26b36b15283e22c6cd71b9740b1cc4fee`。93 份 CSV 字节一致、93 份 XLSX 工作簿语义一致；269 个 API 页仍在复验。图表 231 的旧分页有 1 行跨页重复并漏显 1 条独立记录，新端 59 条唯一记录；旧端完整 CSV/XLSX 与新端一致。43 个分区有 41 个完整采集、2 个自然补拍；本期紫 `#454E7C`、同期绿 `#5AC189` 已本地恢复，5 个分区仍在补验。细节见[本地 SQL 迁移验收](docs/shadow-bi-sql-local-migration.md)。

Mac 仍按原 bi-3 来源和日程运行；worktree 中的 `p5.daily` 新路径从本地 SQL 建仓、打包后提交 SQL release，不运行 Python `calculate` 生成旧 39 张逐图业务结果表。服务器未接线、未切 `current`，未更改正式 warehouse、旧 release、ACL 或 `DeliveryState`。

切换计划为单一 warehouse 与七个运行文件：Superset 使用 `/srv/shadow-bi/code`，旧业务 receiver 在 `/srv/shadow-bi/raw-code`，通知共享 `/srv/shadow-bi-notify/current` 和 `/usr/local/sbin/shadow-bi-notify`，MCP 更新其 venv `site-packages`、`/usr/local/libexec/business-data-mcp/acl_sync.py` 及 venv `ExecStart` drop-in。切换时停旧 `shadow-bi-publisher.path`、`shadow-bi-receiver-publish.path` 和 raw 业务处理入口，保留 `shadow-bi-receiver-notify.path`；原子切换失败回滚。旧仓先归档本地，核销 32+4 份旧仓引用后再保留单仓；旧 SQL release 的退役另留成功核验维护回执。费用阶段失败沿用上批已提交费用及日期，不阻断业务发布后的通知。

## 历史：云端基础仓与看板 SQL（日更切换于 2026-11-05）

以下为此前的双仓／Python 39 表日更历史，不是当前 SQL 候选状态。11 月 4 日双仓批次曾在 BI 服务器重算并发布；语培与留学工单、签约／现金使用云端基础 Snapshot，费用作为单批表格快照。原 09:30 入口继续采集和校验来源。完整历史见[原日更说明](docs/archive/shadow-bi-full-daily-20261028.md)，该说明本轮未修改。

> **2026-11-03云端日更代码已对齐**：按明确A层清单同步正式`/srv/shadow-bi/code`，127源文件逐项SHA一致（更新47）；固定通知入口的`/srv/shadow-bi-notify/current`也已切至`bi3-20261103-3fea1baf8401393a`，同127文件一致。新工单源、腾讯竞价＋品牌v2非空自动采集入仓、MCP及总入口均已安装；两个现行目录的旧Cookie downloader已删除。云端正式目录及实际通知身份各通过17品牌＋21原生费用入仓检查。bi-3仍由Mac上海09:30启动，来源私有合同与登录态留在Mac，服务器用新进程执行P4与通知。未重采/发版/发消息/改日程/恢复raw；业务current、DeliveryState、crontab不变。真实回执见`.local/audits/tencent-brand-cloud-code-20261103/completion.md`；下方早期未同步状态均为历史。

> **2026-10-28本地收口**：main唯一正式BI数据工作区为 `customers/shadow_bi_daily`。旧仓、c373客户数据镜像、废弃计算成品及已验收10月12日B层传输副本已核销；原始输入保留。旧outbox残留的hash/manifest只作历史记录，不能把残缺批次重新当作可发送封存包。未同步Grok/服务器、未刷新、未改外部日程；以下同步回执保留各日期事实。

> **10月26日后续记录**：[清理回执](docs/archive/server-cleanup-20261026.md)记载raw路径已暂停，保留Mac命令更新及原成品/通知接口；已部署的服务器数仓和聚合能力仍保留。下方更早摘要记录施工时点，本轮未实读服务器或修改调度。

> **2026-10-26 日期回执摘要（非实时调度核验）**：正式 BI 产品为 Superset 原生界面。服务器 raw receiver、root 只读历史基线、受限双 Snapshot / quality / 共享计算 worker 和固定 publisher 已部署；真实 Dot 批次完成双 Snapshot、两份 quality 查询并实际运行到39张业务表，最终因业务截止不匹配以 `failed/published=false` 结束，没有发布 raw release。Mac `p5.daily` 是仍存在的手动入口，日期回执记录它更新了 `daily-20261026_094052`（数据截至10-25）；这项生产记录不代表长期默认路径。有效新 raw 包正式发布、持续日更和唯一生产者收口仍待分别验收，本轮未实读服务器或调度平台。服务器通知适配已部署，10-26 人工触发8条消息为 sent；相应HTTP job仍为 `unknown`，只读对账关联到此前发送。Dot每日上海10:00的建立记录是通知日程，与BI采集／刷新分开；Grok例行按用户要求停止。详见[部署说明](dashboard_product/DEPLOYMENT.md)、[通知回执](docs/archive/notification-job-receipt-repair-20261026.md)、[接收回执](docs/archive/server-raw-receiver-deployment-20261026.md)和[固定发布回执](docs/archive/server-raw-fixed-publisher-20261026.md)。

# Data OXHor 同步边界

本机核心源码是 `/Users/akechi/Desktop/manager -CowH`。同步按明确文件清单与 SHA-256 执行，不将云端角色积累、临时程序或工作数据混入核心代码。

## 2026-10-15学校排名排序微调同步

用户授权后，固定A包 `school-sort-20261015-A.tar.gz` 已经既有Grok本机执行／CopyToBox安装到 `/home/box/oxhor/dashboard`。包SHA-256为 `b2521fbbe8c25137841e1ec2bff5dd73831b5288cd9576a879a04f3151abf87b`，仅含学校排名脚本与对应管理说明两个安装目标；云端预检、安装、Node语法与五指标／双顺序／双业务线模拟校验均退出0，2/2文件摘要与本机固定包及当前源码一致，原共享软链保留。回执时间2026-10-15 14:11:11（上海），回执见 `.local/sync/inbox/school-sort-20261015/receipt.json`，本机独立核验见 `.local/audits/school-sort-20261015/cloud-sync-verification.json`。此次只完成源码同步，不重抓数据、不重建或激活公网、不发通知，不改Snapshot、例行、凭据或DeliveryState；线上当前静态页面仍需后续正常重建发布才应用本次交互。

## 2026-10-12本轮统一源码与完整当前双仓同步

用户已明确授权：三个看板改造统一清理、Git提交，并将本机完整当前BI／留学Snapshot及配套输入同步到既有Grok工作区。当前BI为 `snapshot_bi_operations_20261012_full_orders_1640`，留学为 `snapshot_study_abroad_20261012_local_1138`；本次传完整当前仓的历史数据，不仅增量工单。A源码、B客户数据分包，不传C凭据、不提交客户数据到Git。旧日期段落描述各轮当时状态，不限制本轮明确授权。

ROI仅由用户手工提供费用表后更新；本机与Grok同模式。费用清单使用客户目录内相对路径与SHA。美国云端的BI Cookie注入是当地适配，本机仍沿用弹窗登录下载；五份云端专用源码回传备查，A包明确不覆盖。今天本机已发8条消息，本次仅安装与构建验收，不补发或自动激活公网，也不变原例行时刻／启停、软链或凭据。同步过程与当前回执状态见[统一清理与同步](docs/archive/dashboard-unified-cleanup-20261012.md)。

本轮v2同步已于2026-10-12 23:41验收：Git源码`aabe6fcb`，A包53份文件／73目标逐项摘要一致；B包81文件，79文件逐字节一致，两个指针仅并集保留两端`used_snapshot_ids`，回传原文已在本机独立核验。完整当前BI／留学仓指针及已有仓核验配对均通过门禁；云端`run_management_unified_portable_20261012`数据截至10月11日，17期间、人员、活动及线上期间四项业务摘要与本机全同。208项／77子测试、8条空跑及18文件组包通过。五份云端Cookie适配摘要未变；生产batch、DeliveryState、凭据与例行未动，本轮未重抓、未补发、未公网激活。B包超过CopyToBox 100MiB限制，按既有通道拆为四个40MB块、合并后核验原包SHA，通过同一目的地完成传输。回执在`.local/sync/inbox/dashboard-unified-20261012/`，根独立核验在`.local/audits/dashboard-unified-20261012/cloud_sync_verification.json`。

## 2026-10-03阶段同步记录（历史）

本节记录当时在 Grok 上完成的 P3/P4/P5 静态页面版本及其源码同步，不是当前 BI 产品或调度状态。2026-10-25 正式 BI 已切换到 Superset 原生界面；旧静态部署材料见[历史归档](docs/history/dashboard/static-deployment-through-20261025.md)。Pawsy迁移当时已取消。2026-10-03历史回执见[施工计划第32节](docs/dashboard-static-rebuild-plan.md)，第30节保留方案变更过程。

- 当时本机为核心源码真源；Grok端必要修复按已有inbox/明确版本回审，不直接覆盖本机未提交工作。该阶段继续原A/B/C分层与现有Grok工作区，不为替换宿主另搬全部业务数据或复制生产库。
- 2026-10-03先完成14份源码及4份原文比对，随后用户明确授权源码同步。固定v2包和既有上下文模块补充包已安装；96个目标/14个重点源码与本机哈希一致，137项定向合成测试及doctor/依赖检查通过。原始包、清单与机器回执保存在本轮grok-source-align outbox/inbox。源码同步和数仓更新分别处理：本任务没有运行BI、客户ingest/sync、数据回写或修改指针，没有启停既有例行；数仓由用户按需手动更新。
- P3先实读Grok目录、Snapshot指针、运行版本及权威调度状态，再同步实际需要的代码、SQL、模板和配置。当时看板及8条／5通道推送消费同一共同结果，群和节奏沿用当时确认。
- 当时已验收的产物和通用发布/投递适配继续复用；P3/P4/P5静态页面通过当时的原鉴权及独立哈希验证。2026-10-03记录的09:45恢复、09:30数仓及10:24暂停只描述当时状态，不是当前入口。原上线回执见施工计划第32节，锁屏中断为历史过程。
- 2026-10-03用户另行明确授权核销Pawsy旧压缩包与staging副本。四个pawsy outbox批次的清单、哈希、回执保留，嵌套身份/版本材料收口到各批次 `retained-metadata/`；约1.77 GiB冗余包已删除。原历史回执仍描述当时已打包状态，各批次 `CLEANED.md` 标明现状，不再当作可重发包。客户原件、正式成果、查询证据及Grok上线回执保留；本次没有操作远端草稿或上传数据。

## 2026-10-12语培工单边界修复与源码安装

用户按刷新→线上发布→Grok Box同步顺序授权执行。修订批次`run_management_scope_fix_20261012`沿用本机11:38当天passed双仓，截至10月11日；18静态文件已正式激活，manifest SHA-256 `13333f3135938ec052984fd3edc0ad5201c9406245b142678a1068ec7bd61d71`。公网全年8,482、未知组50，全部/线上/线下50/13/37与同批输出匹配；本次没有重发通知。

固定A包`market-order-boundary-20261012-A.tar.gz`仅五份源码/合成测试，用户另明确同意传输及安装。包SHA-256 `b8eace69e437dacda12bff05642115e46347f70494c64afe731131e266d4586e`。首轮预检两份基线摘要不符停止，回传文件与本机修复前HEAD逐字节相同；本机审查后仅修订云端解包manifest两处预检基线，原压缩包、五份源码和安装脚本字节不变，不放宽检查。随后云端`INSTALLED_OK`，5目标摘要与本机当前源码一致、9项测试通过，原共用软链保留。实际import及日更脚本加载新版build，SQL留学顾问第三参数来自既有确认配置。

包与清单在`.local/sync/outbox/market-order-boundary-20261012-A/`；真实回执、原件差异、基线审查及测试日志在`.local/sync/inbox/market-order-boundary-20261012/`，独立核对在`.local/audits/market-training-boundary-20261012/cloud-sync-verification.json`。本次源码同步未抓数、改客户Snapshot/联合回执、修改Cookie/例行、云端发版或发通知。业务差异与本机激活证据见[工单边界与同期对账](docs/archive/dashboard-order-boundary-audit-20261012.md)。

## 2026-10-12线下分配与团队筛选源码安装

随后用户授权一次本机完整运行：本机 `run_daily_sources_local_20261012_1138` 两仓与当天门禁passed，`run_management_local_20261012_1138` 18文件已正式激活（截至10月11日），8条／5通道通知全部sent。此为本机来源和实际现网发布，不代表下述Grok失败配对已恢复；没有上传整个数仓、写入云端指针或修改例行。恢复Grok后如处理本日批次，先对照本机已经发送的8条回执，不重复补发。真实运行见[本机正式运行](docs/archive/local-production-run-20261012.md)。

用户明确授权后，固定A层包 `market-allocation-20261012-A.tar.gz` 已通过既有本机执行／CopyToBox安装到Grok。包摘要 `1d1c9d21ce14eed89369de6576acb63d435e6ac543afb95234b924af28b1a28c`，17份唯一文件／21安装目标与清单逐项匹配，基线无未知差异，现有共享软链保留；云端管理／监控145项及8子测试通过。回执在 `.local/sync/inbox/market-allocation-20261012/receipt.json`，本机独立摘要核对在 `.local/audits/market-allocation-20261012/cloud_sync_verification.json`。

安装完成不代表新版已上线：当天 `run_daily_sources_20261012_094030` 整体failed，BI扫码登录待本人处理，留学单源成功不准入。生产batch仍为 `run_management_20261011_095118`（截至10月10日）；本次未重建、预览新批次、组包、激活或发送，未改原例行、群、凭据与去重状态。新个人分配、未分配签约附件及全部／线上／线下筛选须在当天双仓passed后重建同批结果才能生效，不以本机10月8日封存数据覆盖现网。业务与回归见[修正证据](docs/archive/dashboard-allocation-regression-20261012.md)。

## 2026-10-09早期留学与人员同步阶段（已被下方腾讯版本取代）

用户授权后，源码提交 `6c95bf6d`、`cc56a897` 及三份人员产能参考输入已通过现有 Grok 本机执行／CopyToBox 流程安装到云端。固定 A/B 清单、包摘要、机器回执保存在 `.local/sync/outbox/grok-dashboard-study-20261009/` 和对应 inbox；78项源码变更的86个安装目标逐项匹配清单（含共用文档副本及删除）。未传整个客户目录、DuckDB、Parquet 或凭据。

- 云端以明确 BI `snapshot_bi_operations_20261009`（截至10月8日）构建，原BI指针不变；三份参考输入摘要匹配本机。独立留学仓为 `snapshot_study_abroad_grok_20260930_v1`，截至9月30日，从原始工作簿在云端建立，不复制本机仓库。腾讯文档抓取尚未接入。
- 云端管理批次 `run_grok_study_sync_20261009` 已完成152项测试、18文件静态组包及8条通知／原5通道空跑；9月留学核对总资源864、现金2,347,804.40元。三份云端旧修改已回传审查，部门含删除／回收、个人剔除的逻辑和测试仍保留在本机真源。
- 本轮仅完成安装、独立建仓及构建验证，尚未激活新版页面、切换生产通知批次或真实发送；生产批次仍为既有例行当日上午生成的 `run_management_20261009_101225`。既有例行时间、启停、接收者和凭据没有修改；旧 `automation.json` 不作为平台权威调度状态。实际发布或发送留待后续明确任务。

## 2026-10-09腾讯抓取与标准历史同步验收

抓包／更新源码 `935fa89c` 与多来源校验补丁 `73ae88b6` 已安装Grok；37个主包目标、3个补丁目标摘要与本机封存清单一致。B包仅6—9月规范历史三表和metadata，3592资源行／493合同行／363小语种行含排除审计记录；不传原始旧表、DuckDB或Mac Cookie。云端使用用户本人新登录的腾讯会话。

- 标准历史先建立独立seed，再实际导出腾讯整Excel，只刷新10月。云端当前留学为 `snapshot_grok_tencent_study_20261009`，截至10月9日；6—9月数据核对不变，10月233工单／451,960元现金／留学12人及小语种10人。两条8月无金额记录保留待补。新增本机标准仓 `snapshot_study_abroad_cloud_aligned_20261009_v5` 已用回传原件对齐同批数据。
- 来源校验保持各行真实原始SHA，以已校验的冻结规范表白名单检查；云端临时放宽版本已备份回审并由正式补丁替换，未伪造统一的10月来源SHA。
- 云端final批次 `run_grok_tencent_view_final_20261009` 使用BI `snapshot_bi_operations_20261009` 和新留学仓，人员贡献同Snapshot消费。补丁5项、管理210项测试通过；8消息／5通道空跑及18文件组包通过，manifest SHA `d301ea01bd184a5bcda36beb600d1618fbaac148d6e47aa466e5526d04b244f8`，内容路径、字节数与摘要18/18核对。本批次未取得activation回执、未切生产batch、未实际发送，例行时间／启停未由本次修改。回执未提供实时公网current链接，不能独立宣称此刻公网具体版本。看板共同BI期间截至10月8日，留学仓本身截至10月9日，二者不混称。
- 封存包位于 `.local/sync/outbox/grok-tencent-history-20261009/`，回执位于对应inbox（含patch_origins）；根独立验收见 `.local/audits/study-history-678-20261009/final_sync_verification.json`。此前“未同步”段落反映各轮当时状态。腾讯CLI已实抓，但每日抓取尚无接入调度链回执；现有看板例行若运行成功会尝试发布届时当前数据，并不先抓腾讯。

## 内容分层

| 内容 | 存放与同步规则 |
|---|---|
| A：已审查核心代码、合同、非密钥配置与正式查询 | 本机明确发布包同步到云端；云端必要核心修复先进入本机 inbox 审查，不直接覆盖源码 |
| B：客户输入、工作区、Snapshot 和正式成果 | 保留原 customers 身份与目录；例行回写只按明确 workspace、snapshot_id、run_id，禁止 latest/目录时间猜测 |
| C：密钥、凭据、登录态 | 独立通道和明确授权；不进 Git、常规包、公开仓或聊天。现有生效凭据路径不随本轮调整 |
| Grok 自管材料 | 存入独立 grok_workspace，Grok 自行维护；不默认当作核心 A 层，不自动回灌核心 checkout |

## 本机物理目录

- `.local/sync/inbox/`：云端回传的 A/B 文件与验收回执，审查前不覆盖核心。
- `.local/sync/outbox/`：本机发布的明确 A/B 包和清单。
- `.local/sync/backup/`：同步过程中必要的本机备份，按批次验收后核销。
- `.local/private/sync/`：按来源分类隔离的历史 C 层中转材料；不随上述目录整体传输。
- `.local/history/`：从旧 runs/outputs 移入的本地历史成果；正式运行继续使用客户工作区 Output 或市场 Reports/Evidence。
- `.local/logs/dashboard/`：本机看板发布日志；脚本在所选 PROJECT_ROOT 下采用这一默认路径，显式 LOG_DIR 仍可指定。
- `grok_workspace/`：本机 Grok 自管工作面，只跟踪 README、AGENTS 和忽略规则；角色、笔记、程序和临时材料不进核心 Git。

旧 `.writeback-inbox`、`.sync-outbox`、`.writeback-backup` 不再是入口，不保留软链或自动回退。一次性路径迁移清单放在 `.local/audits/structure-20260918/`，只作人工追溯，不参与运行时路径解析。

## 云端边界

现有 `/home/box/oxhor/warehouse`、`dashboard`、`monitor` 保留稳定代码、环境与运行入口；共享模块已有有效软链继续用于单一实现，不属于旧路径兼容。客户数据仍在 warehouse 管理，不为目录整理复制数仓或改变 Snapshot 指针。

Grok 自管工作面采用 `/home/box/oxhor/grok_workspace/`。角色合同、临时脚本、笔记、试验及各自依赖可以在这里自行组织；核心项目不依赖这些临时代码。原岗位 ROLE 等材料收口到该区，由 Grok 自行调整读取路径；不要求与本机逐行一致，不把角色更名当成核心架构变更。

这属于目录与发布隔离，不宣称同一用户进程受到 OS 硬沙箱限制。核心改动仍须有具体任务、可审查差异与验证结果，不能靠自管脚本静默改变 SQL、公式、人员归属或目标配置。

## 切换与验收

1. 先核对实际目录、软链、版本和运行占用，再传明确清单。源文件比对使用 SHA-256；有未知修改先保留到 inbox 评审。
2. 路径调整同批更新调用方、脚本、文档和例行任务中的对应路径。已有任务时间、业务参数、接收者与凭据授权不因整理改变；不新增重复任务。
3. 看板 SQL、计算函数、人员规则和目标配置须与迁移前基线一致；移动文件核对字节，测试使用合成 fixture，未经任务要求不运行真实刷新、发布或群发。
4. 更新后回传实际文件路径/hash、测试命令与结果、导入位置、例行路径实读和未完成项；口头完成不替代回执。
5. 临时备份只用于本次失败恢复，验收后按明确清单核销，不作为旧版运行入口。历史证据、原始输入和凭据不得因目录名含 tmp/backup 就直接删除。

Grok 的人员分工由 Grok 自行协调；涉及核心和运行路径的变更须完成上述核对，不建设跨宿主双向 MCP 或总 Agent。网络通道失败时记录并反馈，不静默反复传输；不自行切换系统代理或登录态。

## 已完成记录

- [监控模块云端部署](docs/monitoring-cloud-deployment.md)
- [查询证据与来源修复同步](docs/evidence-cloud-deployment.md)
- [旧同步合同归档](docs/history/sync-contract-through-20260918.md)

历史包与回执已迁到本文件定义的新位置；记录里的旧路径只描述当时操作，查找现存文件应使用一次性迁移清单。私密中转仓仅在确有需要且已授权时作搬运缓冲，不成为代码或数据的新真源。

### 2026-10-12 调度读数（历史快照）

当日对原看板任务 `da973a5e-271f-57ef-9037-bedf4c5822d2`“看板日更”的界面读取记录为 ACTIVE、09:45（Asia/Shanghai）；平台当时只返回名称、时间和开关等元数据，未返回完整正文。该读数不代表 10-26 或当前启停，也与后续 Dot 10:00 通知日程不同。证据见 `.local/audits/market-training-boundary-20261012/routine-platform-ui.txt`。
