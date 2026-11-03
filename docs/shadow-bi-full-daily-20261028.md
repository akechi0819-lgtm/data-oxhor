# 完整日更接入状态（2026-10-28）

## 当前最新：新工单全历史与费用验版完成，旧仓已退役（2026-11-03）

云端代码后续已同步：正式`/srv/shadow-bi/code`及独立通知current均127源文件与本机SHA一致，代码版本`bi3-20261103-3fea1baf8401393a`；正式目录与通知服务身份各通过17品牌＋21原生费用检查。明日bi-3仍本机09:30采集，经新进程调用云端新版P4／通知；旧Cookie下载器已在两个现行目录退役。无业务数据发布或通知重发，current／DeliveryState和暂停raw状态保持。回执`.local/audits/tencent-brand-cloud-code-20261103/completion.md`。

后续补齐品牌非空自动流程：v2分日报表合同已替代空态管理合同，线上8分支对账通过，117项测试／9项子测试通过；所有品牌非空样本经正式费用解析器入仓验证，自动采集、对账和入仓不需人工补文件。验收见`.local/audits/tencent-brand-auto-20261103/acceptance.md`，本次未重导、重发或改正式版本。

正式双仓Snapshot后缀20261103_134820，61293个唯一工单，同ID按用户确认保留首行；两业务截止11/2。基础版daily-20261103_134820发布成功，原5通道8条日报已sent且未重发。费用版daily-20261103_141437已发布并完成本地／云端39表与关键指标回查，3809费用行、31条ROI公式通过。工单反馈正式104列追加231、已存在0、最大分配日期11/2，三个人工列未覆盖。

腾讯已按一级竞价＋品牌、排除智能完成8分支线上核验：展示16日2278.58元、搜索625广告日行21467.16元，日期-ID无交集、逐日对原生账户CSV差异0，合计23745.74元。16天对应竞价展示中已暂停的实际广告，不是仅脚本截断。品牌等本次为成功空态；品牌广告级404改由官方计划级成功查询核查，没有补零。新日更observed_contract逐次重查范围、分页和分日原件对账，合同在`.private/tencent-promotion-query-contracts.json`。品牌实时竞价和内容助推已改为正常分日报表查询；非空记录与合约品牌一起自动分页采集，分别核对V3／legacy原生账户CSV并随该账本入仓，不再因为首次非空要求人工补明细。内容合约仍为触达合约子集，只计一次；真实查询错误或对账不符才阻断费用。

本地35旧派生库及云端4旧版本、15旧BI物理库和15工单Parquet已删除，删除后回查通过；当前／previous都为同一新Snapshot的新版本，原件与投递状态保留，无旧工单仓兼容。腾讯语培缺口、SEM完成标记缺失及226条空金额保持如实缺失。只有bi-3更新，其余9份日程配置哈希不变。完整证据见 `.local/audits/bi-orders-full-rebuild-20261103/completion-summary.md`；下方暂停与失败小节均是此前阶段历史。
> 2026-11-03项目审计已核销本页历史候选中的派生库和重复传输表；原件、查询证据及验收回执保留，各批次`CLEANED.md`说明现状。逐文件记录见`.local/audits/project-audit-cleanup-20261103/`，历史路径不再表示可完整重发或重放。

## 历史阶段：新工单正式上云完成，费用登录恢复中（2026-11-03，已被文首完成回执取代）

用户已解除本轮云端暂停，并明确同工单ID保留首行。新源全历史正式仓为61293个唯一工单；双仓 Snapshot 后缀均为20261103_134820，两业务截止11/2。唯一总入口已发布基础版本 `daily-20261103_134820`，服务器current、39表及关键指标独立核验通过；原5通道8条钉钉全部sent，持久DeliveryState已核对，不再重发。工单反馈正式104列同步passed，新增231、已存在0、最大分配日期11/2；三个人工列保持。上述结果覆盖下方旧“仅本地/云端暂停”状态。

费用尚未发布：原批次 `.local/audits/full-daily-20261103-full-rebuild/` 的小红书/腾讯广告登录失效，巨量和SEM已采集结果保留。小红书11/3 14:02新专用状态保存后，独立任务查询验证通过；腾讯恢复曾在display query校验失败时提前关窗，尚未保存本次新状态，正在修复。业务正式current及8条sent不受影响。旧工单派生仓已盘点，正式删除尚未执行，不能报告清理完成。

广告来源正常运行先复用专用Cookie；缺失/明确失效才走一次原登录恢复入口，验证后续原任务/批次；不复制普通浏览器登录态。bi-3已通过应用工具仅更新此恢复规则，每日09:30、模型与项目不变，其余9份日程配置SHA完全不变。腾讯文档仍唯一官方MCP。证据 `.local/audits/bi-orders-full-rebuild-20261103/server-rebuild-independent-verification.json`、`server-final-delivery-verification.json` 及原批次回执。


## 历史阶段：新源全历史本地候选，云端暂停（2026-11-03，后续已解除）

用户先授权按新源全量重建并在验收后删除旧工单仓，随后明确“先不要推送云端，先在本地弄”，并要求列出重复明细。**当前仅本地核查；本轮候选未经重新授权不得发布、同步腾讯反馈记录或发送日报。** 旧正式仓删除也留待重复核查与正式替换完成后执行，日程配置未改。

新卡片按四个互不重叠日期段导出：2024/6/1—2025/8/31、2025/9/1—2026/2/28、2026/3/1—8/31、2026/9/1—11/3。四份原件全部取得，实际记录起于2025/3/1、止于2026/11/2；原始61777行、61293个唯一工单ID，旧仓60858个ID全部保留、新增435个。原件没有复用旧工单行。第四段读取遇浏览器断开后只恢复原任务下载，未重复提交。

原生导出有482个重复ID、484条后续重复行，均在第一段，跨段重复为0；481条仅年级属性不同，另有顾问差异1条、完全重复1条、多字段及日期差异1条。既有合并和SQL合同是同ID取第一物理行，本地候选沿此合同计算，原始61777行完整保留供核查。不能把候选规则执行成功当作重复字段已获业务确认。逐对核查中首行分配日期、年级属性均与旧仓一致；全部版本和Excel行号见本次重复核查表及 `duplicate-review-data.json`。

隔离副本 `.local/audits/bi-orders-full-rebuild-20261103/local-candidate/workspace` 已建立配对新Snapshot、38表业务库和39表本地投影，两业务截止均11/2。新工单源126列，不再合入旧“预计到访时间、是否邀约、录入来源”；当前导出表头决定schema，不保留旧列union。现金复用今日冻结完整原件：71895行、392620748.19元，65个业务字段的逐行多重集摘要与旧仓一致；留学原件沿用今日MCP导出及SHA。隔离副本不含`.private`，没有执行腾讯反馈写入、广告采集、云端发布或钉钉。正式本地workspace指针仍是早间 `snapshot_bi_operations_20261103_093405`。

在用户改为仅本地前，正式腾讯“工单反馈明细”已删除“录入来源”列并读回核验为104列，私有配置与程序也严格接受104列，不保留105列兼容。素材ID/账号来源/工单跟进情况位置不变，原已有人工值未被覆盖；尚未追加11月记录。本地候选的反馈读取预检231条通过，不能称正式同步完成。

旧仓只读盘点已列出本地当前Snapshot及35个历史派生库、云端旧releases与暂停路径的旧BI快照；未执行正式清理。当前输入绑定已排除旧BI run，避免新候选依赖待删除的旧仓文件。相关完整回归1171 passed、1 skipped、214 subtests passed。证据均在 `.local/audits/bi-orders-full-rebuild-20261103/`，重点为 `full-export-result.json`、`full-history-reconciliation.json`、`local-warehouse-receipt.json`、`local-only-build-result.json`、`feedback-schema-migration.json` 和两份 retirement inventory。

## 历史阶段：BI工单导出入口迁移（2026-11-03）

用户确认原工单看板已移入历史区，当前入口为 `https://bibr.staff.xdf.cn/page/dc1bca538e57f49038476541` 的【工单】底稿导出用表。旧卡片仍能导出截至10/29的历史数据，后续查询又出现 `录入来源` 无法解析的卡片错误；不能继续把旧入口缺少11月记录解释为上游没有工单或导出生成慢。

在新页面手动设置8/3—11/3、不加团队筛选，通过开发者工具Network实际捕获 `POST /api/batchExportCardExcel`：工单卡片 `j7378d2612e2242ab85e3140`，日期筛选名称“分配日期”、字段 `bf9ab43250ab34a98836dcf4`、来源控件 `xa6e577520eb543e7913a773`，`exportType=PIVOT`、`saveType=MANY_SHEET`。工单连接器已据此更新页面、卡片、日期元数据与创建请求，删除旧请求路径；现金请求不变。本次三个月仅为显式诊断范围，日更默认六个月未改。

手动任务 `a5fe36f0-d737-11f1-b633-b992f32e319c` 实际生成122秒；随后连接器使用原BI专用登录态复用同一任务下载，没有重新创建任务或复制普通浏览器会话。原件SHA `de7a14bc8dddb6f3dc19bac6e50b0cd196647ccb8fc34db3b417e5c06bbdcad5`，126列、10553行，分配日期8/3—11/2，11/1为143行、11/2为88行，共231行11月记录。现有数仓原件读取器完整读取10553行，sheet仍为“工单明细导出用表”；工单/现金请求与重建定向11项测试通过。证据 `.local/audits/bi-orders-migration-20261103/`。

新原件缺少工单反馈正式105列中的“录入来源”，`_load_candidates` 只读核验明确报 `source_headers_missing_required_fields`，见 `feedback-reader-verification.json`。本轮不猜字段替代、不改远端表结构或人工列、不写正式工单反馈。本轮只修复并验收导出，未更新Snapshot、发布看板、发送日报或修改日程；11/3早间正式基础版仍为 `daily-20261103_093405`，不能将这份诊断原件视为日更已恢复。此前六个月与旧卡片三个月诊断任务的本地等待均已停止，任务ID和远端结果未知状态保留，不重提同范围任务。

## 腾讯文档下载唯一改为官方MCP（2026-11-02）

留学表下载已从Cookie网页接口切换到官方MCP，`downloader.py`、旧配置类、Cookie读取器、原CLI参数及生产脚本的TENCENT_DOC_ID/URL/COOKIE_FILE/CA_FILE环境变量全部移除，无兼容分支。工作区`.private/tencent-source.json`仅保存`file_id`和宿主全局`token_file`路径；已无调用方的`.private/tencent-cookies.json`已删除。工单反馈追加与留学下载共用`connectors/tencent_docs/mcp.py`，不在业务job中重复实现客户端。

在线流程为创建导出任务→查询进度→下载并核验整本XLSX，之后沿用原来的标准化、月份替换、Snapshot及发布门禁。导出目录持久保存任务ID；未知提交结果明确阻断，恢复同一任务时不重提，下载完成后校验同一文件/hash再复用。服务器raw接收的已校验本地原件仍通过`source_file`输入，这是现用入仓合同，不属于旧在线下载兼容。

新下载器真实导出、原件读取及同目录重复运行通过，重复运行复用相同任务ID、路径和SHA。完整回归1152 passed、1 skipped、214 subtests passed；证据位于`.local/audits/tencent-mcp-switch-20261102/`。此次不重新采集BI、不更新正式数仓指针、不发布看板或发送消息，下一次09:30由既有bi-3调用新入口。

## 工单反馈明细日更（现行104列；2026-11-02接入）

正式腾讯文档《新媒体内容组项目进度表》的“工单反馈明细”页签（`0apMZH`）现行合同为104列：11月2日曾追加“账号来源”形成105列，11月3日随新源迁移删除“录入来源”后恢复104列，旧105列绑定不再接受。`素材ID`、`账号来源`、`工单跟进情况`均为人工列，程序不写入、不覆盖。“数据反馈流水”等原页签不参与写入。连接使用宿主全局腾讯文档MCP，项目仅保存私有业务绑定。

`daily_warehouses.refresh_daily` 在BI成功入仓后复用本次 `export_orders`，调用 `data_acquisition.jobs.sync_content_work_orders.sync`。绑定配置为工作区私有文件 `.private/content-work-orders.json`，包含正式文档/页签、104列、`start_date=2026-11-01`及全局Token文件路径。未配置的工作区不启用此步骤。每次按“分配时间”筛选11月1日起至本次日期的记录，读取远端工单`ID`后只追加缺失项，后续日期会补齐晚到记录；不以学员号或资源ID去重，不清空历史、不按日期整段覆盖。

新增行分批写入源字段，最后提交工单ID；实际读回核对后记录结果。工作区锁防止手动同步与日更同时追加。同步回执独立保存于 `Work/ContentWorkOrders/Runs/<run_id>/receipt.json`，双仓回执的 `content_work_orders` 记录本次交付结果，BI来源的 `orders_export` 保存原件路径与SHA。同步失败单独报告，不把BI成功改成失败、不阻断原基础看板/日报/费用顺序；不得把失败或缺数据描述成已经同步完整。

恢复时先核对当前双仓回执及其 `orders_export` 原件/hash；旧回执未含该字段时，从显式当前Snapshot的 `snapshot_manifest.json` 中定位 `br_work_orders` 对应的冻结原表并核验SHA，不按mtime或模糊文件名选原件。使用新run_id执行：

```sh
.venv/bin/python -B -m data_acquisition.jobs.sync_content_work_orders \
  --workspace customers/shadow_bi_daily \
  --source-file '<已核验工单原件绝对路径>' \
  --as-of-date '<上海本次日期YYYY-MM-DD>' \
  --run-id '<本次唯一run_id>'
```

日更宿主还需在复用已完成同日业务批次时检查该独立回执，缺失或失败则仅恢复本步骤，不重抓原件、不重发日报。报告新增/已存在数量、原件实际最大分配日期与缺口；原件最大日期早于起始日且新增0时明确标注缺数，不能当作11月已无工单。`bi-3`维持每天09:30及原启停状态，只增加此步骤的核验与恢复说明。

接入验收：34项定向测试通过；核心完整回归1138 passed、1 skipped、214 subtests passed。正式同步模块在镜像“日更接入验收”完成真实源行首次新增1笔、重跑0笔、次日新增1笔，人工备注未被覆盖，验证后已清空；素材ID始终为空。正式首次运行`run_content_work_orders_20261102_enable`通过，候选/新增均0，原件最大分配日期为2026-10-29；该来源缺口仍需上游补齐。现有`bi-3`通过应用工具更新，prompt逐字读回一致，状态/时间/项目/模型等原字段不变，其余任务SHA逐份一致。证据为`.local/audits/content-work-orders-20261102/`中的`source-verification.json`、`live-mirror-module-verification.json`、`production-first-run.json`、`automation-update-verification.json`和`core-tests.txt`。

本任务网络写入只针对新增工单页（及镜像验收页），未向原“数据反馈流水”提交写入。期间两次只读抓取的原反馈页有828个单元格差异，可能来自其他协作编辑或重算；不能宣称整张反馈页前后完全不变，也未回滚这些变化。观察记录为同目录`feedback-observation.json`。

历史接入验收时，追加“账号来源”后的105列表头、私有绑定和同步程序曾对齐（现已由104列合同取代）；素材ID、账号来源、工单跟进情况均跳过写入。实际正式读取核验通过；当时完整回归1140 passed、1 skipped、214 subtests passed，证据位于`.local/audits/content-account-source-20261102/`。随后已完成上方MCP下载器切换；早先仅导出对照的证据保留在`.local/audits/tencent-mcp-export-20261102/`。

## 现行运行顺序：业务优先、费用后置（2026-10-30接入）

现有 `prepare_full_daily --publish` 已改为唯一业务优先总入口，命令参数不变，依次执行：

1. 更新 BI 与腾讯文档现金、工单双仓，校验同日配对并发布基础看板。
2. 基础看板发布成功后立即调用固定 `server_notify send-published`，不等待10点；原5通道8消息全部确认后继续。仍校验当天正式release和DeliveryState，不新建日程。
3. 复用同一双仓 Snapshot 采集费用，保持全来源、金额、输入冻结及发布门禁；通过后补充发布费用和ROI。

基础构建显式使用本批空费用清单，不读取或绑定 `Input/AdvertisingCosts` 的原件；费用暂显示缺失，不补零。空费用表保留查询列定义，服务器重建也保留该结构。费用采集、校验或后续发布失败时，保留已成功的基础正式current与日报，只把费用阶段记录为失败；不再用失败批次覆盖正式current。默认及显式 `--prepare` 仍是隔离的本地费用候选，不发送或发布。

`batch-dir/pipeline-result.json` 分别保存业务、通知、费用阶段。完整重跑先核对正式版本，不重发通知；部分续跑复用已确认业务配对，未知发送结果保留原attempt、日志及DeliveryState，先查服务器，不盲目重发。费用仍只走原full_daily门禁及既有publisher，没有新增发布路径。

现有本地自动任务 `bi-3` 已通过应用工具更新并读回：仍为ACTIVE、每天09:30，项目、模型、工作目录、创建时间和规则均未变，只改prompt与更新时间；其余9份自动任务配置SHA逐份不变。新prompt已明确授权按该顺序发送钉钉日报，禁止微信，保留其他日程原状。

本次验证为83项定向测试、10项子测试通过；另用今天双仓构建39表基础候选，现金/工单事实、个人事实、个人期间及市场工单与已发布版摘要一致，团队期间仅有15处cash_share浮点尾差（最大2.78e-17），展示精度内一致。零费用表的覆盖查询正常，原5通道8消息包可独立构建。服务器仅更新p4空表重建代码并做无客户数据的空表探针，未切换current、未重发今天消息。证据在 `.local/audits/business-first-20261030/` 的 business-candidate-verification.json、business-notification-verification.json、server-empty-schema-verification.json、automation-update-verification.json。

补充验收：用户要求取消10点等待后，本地适配器和服务器固定入口已同步 `send-published`，76项测试、12项子测试及服务器无发送探针通过；原 `send-scheduled` 和其他日程保持不变。证据 `.local/audits/immediate-notify-20261030/`。

今天已完成的真实生产全链仍是下节的 `daily-20261030_101406`，8条消息均sent；新顺序通过本地候选、阶段回归及服务器空表探针验收，未另做一次生产重复发布/投递。

## 10月30日首次完整日更与人工恢复记录

2026-10-30 首次定时执行在广告来源采集被阻断，未发布。用户随后明确授权恢复专用登录、排查采集失败，并在本次发布成功后发送钉钉日报。该人工授权不改未来自动任务原先的禁群消息要求；本轮没有修改任何日程。

小红书原批次恢复为 T20261030000283，20子账户、59天、252671.71元；腾讯搜索117418293554为59行20125.02元，展示117418362011仍仅9/1—16的16行2278.58元，未报告43天不补零，按原用户确认相加。两份腾讯任务各提交一次；关闭专用浏览器后，独立Python进程使用保存状态查询仍成功。本轮修复腾讯登录恢复只看展示请求、未切换旧搜索取得认证字段便保存的问题；现在同一专用窗口验证展示与搜索两个查询后才保存。没有复制普通浏览器会话。

SEM菜单点击后立即计数造成竞态，已改为先等待可见再检查唯一性。复用原专用登录态单次恢复导出32216263803成功；15叶整本SHA为f13a612c176639c7fef9d89bba26682a3b33876f122af7803f059f190fb91b53。按用户本次确认，业务归属不明的3029、条线-智能体、360、B站、微博归留学，明确语培两叶不变；正式映射和来源scope同步15叶。435条日期记录中196条空消费保持missing，已知金额107643.41元。完成标记仍缺，采用最新整本并报告该限制，不称为全部填报完成。

BI现金、工单及腾讯文档同批双仓均已成功，Snapshot为snapshot_bi_operations_20261030_100405039185与snapshot_study_abroad_20261030_100405039185。首次计算因全入口微秒批次名叠加历史查询后缀超长失败；最终将全入口批次名改为与既有daily一致的秒级时间戳。历史读取源码保持原件，未改写Snapshot源码绑定或关闭门禁。后续严格复用当天已通过且身份未变的双仓回执，从同一总入口及原发布器续算，没有重复采集双仓。

正式发布为daily-20261030_101406，39张业务表、3577条费用记录，业务截至10/29；服务器current与现金/工单/人头关键指标验版通过。随后原固定通知入口返回8条sent／原5通道，deduplicated=0，无失败或unknown，原持久投递状态保留。证据统一在`.local/audits/full-daily-20261030-scheduled/`：collection-report.json、tencent-recovery-verification.json、sem-scope-confirmation.json、verified-business-pair-for-resume.json、dingtalk-send-result.json、formal-and-dingtalk-verification.json；发布回执为客户`Output/ShadowDaily/Full/run_shadow_daily_20261030_101406/result.json`。已知缺口仍为tencent_ads_training。

本节记载首次恢复完成时点；此后业务优先、费用后置的调整已完成，现行顺序与验收边界以上方最新小节为准。

## 本地完整日更日程启用记录（2026-10-29）

本节记录当前自动化状态；下文为分阶段历史记录，如有冲突以本节为准。

已通过 `mcp__codex_app__automation_update` 的 `create` 成功创建唯一新任务 `bi-3`（名称：`完整BI日更与门禁发布`）：状态 `ACTIVE`，本地 `cron`，项目“新版牛马数据处理”（project_id `75f0ceef-27aa-458b-8e87-ad9f7824b595`），工作目录 `/Users/akechi/Desktop/manager -CowH`，每日 09:30。创建时间为 2026-10-29 21:56:30 `+08:00`；Mac 实测时区为 CST `+0800`，与 `Asia/Shanghai` 一致。`create` 返回了 `automationId` 和状态；随后 `view` 成功渲染任务卡片，但工具没有返回 `next_run` 或时区字段。因此，按已保存规则和主机时区推算，首次匹配运行时间为 2026-10-30 09:30 `+08:00`；这是推算，不是工具返回的 `next_run`，也没有实跑记录。

旧 `automation-2`、`automation-3` 仍为 `PAUSED`；`bi-2` 每周日 18:00 保持 `ACTIVE`。三个文件摘要与本轮前一致；小时任务和 17:50 任务未触碰。Python 3.12 解释器可执行（系统由 root/admin 管理）；配置与合同路径已存在。专用登录态目录权限为 `0700`，文件为 `0600`。本轮没有读取秘密、运行采集或发布，正式指针未由本轮改变。

任务执行的命令如下（本轮仅记录，未运行）：

```bash
cd '/Users/akechi/Desktop/manager -CowH' && DAY="$(TZ=Asia/Shanghai date +%Y%m%d)" && .venv/bin/python -u -m data_acquisition.jobs.prepare_full_daily --workspace customers/shadow_bi_daily --batch-dir ".local/audits/full-daily-${DAY}-scheduled" --source-contracts .local/audits/full-daily-browser-20261028-reconnected --xhs-scope .local/audits/xhs-request-authorization-20261028/verified-source.json --sem-auto --sem-executable-path '/Users/akechi/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing' --tencent-scope-confirmation .local/audits/full-daily-20261029-morning/tencent-scope-explicit-addition-approval-20261029.json --publish
```

仅当采集、费用校验和现有发布门禁全部通过时才发布。程序现有默认仍是 `prepare`；上面记录的命令显式使用 `--publish`。失败保留正式 `current`；导出结果未知时先核对同一任务，不盲目重提。SEM采用最新整本覆盖，空金额保持 `missing`；腾讯搜索与展示按已确认口径相加。语培广告报告仍有已知缺口，不补零；禁止发送微信或钉钉群消息。

## 最新本地全链验收（2026-10-29）

`data_acquisition.jobs.prepare_full_daily` 的 `--prepare`（默认）只构建本地候选；新增显式 `--publish` 才进入完整来源采集、双仓更新和既有受控发布路径。相关 CLI/SEM/候选门禁定向回归67项通过；完整项目回归为1084 passed、1 skipped、214 subtests passed，`git diff --check`通过。今天没有调用发布模式。

复用本地已封存原件的候选批次 `run_shadow_daily_20261029_175725788462` 已通过封包校验：39张表、3370条费用记录，封存表SHA与manifest摘要一致。SEM 280条日期记录中41个金额保持缺失，非零已知金额合计107643.41；腾讯搜索与展示按用户确认相加为22244.20。已知缺口仍为 `tencent_ads_training`。候选状态`prepared`、`published=false`、`publish_outcome=not_attempted`；正式 `current.json` 仍为 `run_shadow_daily_20261029_ui`，SHA-256 `f96c2e2766e7fa9503f94a78b45f5351ee480dcb5c9fdfda37a549acee2e28d2`。

计划建立新的本地例行：每日09:30 Asia/Shanghai，首次2026-10-30；旧09:30日更与旧静态看板任务保持暂停，`bi-2`周日18:00清理不动。本记录写入时，新日程尚未创建：父线程的本地自动化工具返回“Automations are only supported for local threads”；随后新建的本地接续线程已完成项目/运行条件核验，但状态显示`waitingOnApproval`，尚无创建工具调用或任务ID。未改写本地TOML或改用云端日程。

> 最新实况（上海10/29凌晨）：见[日更当前进展](shadow-bi-daily-progress-20261029.md)。下文为分阶段历史记录；巨量缺2账户、尚无保存登录等旧描述已被后续真实验收更新。

> 最新执行纠正：用户要求复用已登录页。网络能力由浏览器拥有线程先实测，工程线程不新建临时浏览器、不要求重登、不抢焦点。此前临时上下文提案未执行且已作废；以`.local/audits/full-daily-main-20261028/request-export-readiness/EXISTING-SESSION-CONTRACT.md`为当前交接。网络监听、同会话请求执行、文件落盘三项分别验证，不凭Playwright能力推断CUA支持。

## 固定请求主路线：尚未接通

用户最新明确：固定抓包/请求脚本是唯一主交付，Computer Use点击下载只作兜底。当前真正已生产运行的请求导出只有BI工单/现金和留学腾讯文档；广告的Ocean/XHS/SEM是未连接登录Page宿主的UI适配器，腾讯广告只有CSV解析，并非已经运行的抓包导出脚本。auth源码只注册bi，不能扩大其授权给广告；普通Chrome已有广告登录，但不等于脚本上下文已连接。full_daily仍只消费外部捕获回执。

本轮仅本地盘点：小红书原生任务服务端生成2秒；4份巨量从文件名时间到核验约21—35秒（含复制/校验）；腾讯有一次下载工具调用493秒、另一约5秒，不能把工具调用墙钟时间都当服务端生成；SEM无可靠计时。不能凭今天反复UI耗时断言日更必然很慢，也不能在请求E2E未验前承诺稳定耗时。

禁止继续唤醒Chrome补原件当主线。待用户允许一次准备窗口后，建立受支持、正常授权的广告脚本请求上下文；若需新独立持久会话，先获明确批准并由用户正常网站登录，不复制cookies、不改端口、不复用BI权限、不绕被拒子帧。观察真实创建/状态/文件请求后才实现固定provider，独立计时创建响应、生成轮询、文件传输；未知结果先核对同任务，不盲重提。当前无合法已观察广告请求可在非前台直接接通，未写假接口或空壳冒充交付。

细项证据、实际耗时和最短动作见`.local/audits/full-daily-main-20261028/request-export-readiness/result.json`及README.md。本轮未调用浏览器或GUI、未读登录秘密、未改运行代码或日程。真实固定脚本E2E通过前不启明日生产定时。

## 统一信源原则与10月28日候选覆盖记录

下述覆盖表及未完成状态记录10月28日候选阶段，后续验收以文首和各平台现行说明为准。每个平台只采用一款权威信源，优先本平台原生流水；多个已确认账户或经证实互不重叠的产品可在同一信源内汇总。集团《网络数据-分公司数据 (4).xlsx》《本月.xlsx》属于延迟跨平台聚合，新候选禁止使用，不补齐、不裁定原生数据、不推导换算、不静默回退；旧原件和现行正式生产保留，待验收发布后再替换来源。

SEM原始整本是用户单独指定信源，保留已有明确映射。SEM与已接原生来源若覆盖同一平台，报冲突，不双计或自动猜删。缺源报缺，无当前费用证据不等于0。腾讯旧集团金额差异不再是阻塞，实际产品互斥、缺日和其余产品覆盖仍需验证；原始花费字段忠实保留。

候选实现集中在management/candidate_sources.py，接入full_daily验收、library显式候选manifest和费用计算显式manifest入口。拒绝集团来源及期间差额；同平台多权威报candidate_authority_conflict；拒绝重复账户日、SEM叶表日、巨量项目日和未排重的旧小红书分表/MCC整表混合。正式默认读取行为未改。

| 平台 | 唯一权威来源 | 已取覆盖 | 当前缺口 |
|---|---|---|---|
| 小红书 | 星火/聚光原生MCC账户分日 | 20子账户、57天；5个零消费主账户排除 | 本次该范围已验 |
| 抖音 | 巨量原生项目分日 | 大学、高中、预备、JR留学、H留学，共5账户 | 1810699393202185、1813785787039897 |
| 腾讯 | 腾讯原生账户CSV | 74749810：旧搜索57天、多产品16天 | 多产品缺41天；产品互斥/其他产品范围、正式费用源映射未完成 |
| 百度 | 指定SEM原始整本 | 已有8个映射叶表 | 27日原始消费空，完成证明缺失 |
| 必应 | 指定SEM原始整本 | bing叶表 | 同上 |
| 闲鱼 | 指定SEM原始整本 | 闲鱼叶表 | 同上 |
| 其他尚无当前费用原件的平台 | 未指定或未取得 | 不借集团汇总 | 报缺，不补0；不推定必有费用 |

真实新候选`.local/audits/full-daily-main-20261028/single-authority-candidate/sources.json`仅含小红书、巨量大学，共1478条，单信源校验通过；完整来源门禁仍source_scope_mismatch，不是全源39表候选。正式manifest若直接作为本次候选会被candidate_group_aggregate_forbidden拒绝。完整核心946 passed、1 skipped、207 subtests passed；生产manifest/current摘要不变。明细及覆盖表见同目录result.json、platform-authorities.json、README.md。

下方各阶段数字/调查保留历史；与本节信源优先级或旧汇总阻塞描述冲突时以本节为准。

用户指定每天 Asia/Shanghai 09:30、所有可获取来源更新后统一发布。腾讯广告语培是已确认待接入项；腾讯留学不能据旧失败记录排除。SEM通常前一日18:00更新，但整月预置零不能证明昨日已完成。

## 本轮代码范围

`dashboard_product.shadow_bi.p5.full_daily` 是待接入下载器的批次验收/计算/发布入口，尚不是已完成的自动采集器。它接收宿主本次实际下载的广告捕获清单，复用现有广告解析、双仓采集及 `p5.daily` 的构建、发布和验版。没有本次捕获回执时返回 blocked，不能拿旧输入冒充采集完成。

现有命令 `python3 -u -m dashboard_product.shadow_bi.p5.daily --workspace customers/shadow_bi_daily` 默认行为保持原样，不自动刷新广告、不发送通知。

今天仅允许prepare候选；必须已有本次真实全源捕获，以下不是已完成的无人值守入口：

```bash
python3 -u -m dashboard_product.shadow_bi.p5.full_daily \
  --workspace customers/shadow_bi_daily --prepare \
  --capture-receipt /absolute/path/to/current-capture.json
```

该命令会先取得与旧日更相同的生产锁。独立 `.private/full-daily-sources.json` 的 `expected_sources` 指定必要来源、账户、窗口及解析来源ID；本轮没有在客户工作区创建生产配置。回执中的来源集合必须与它一致，已知腾讯广告语培缺口不按零、不作为必要来源。

捕获清单包含 `manifest_path`、`sources`。每来源必须声明 `source_id/status/captured_at/start_date/through_date/account_ids/files/evidence/completion`；原件及证据逐份绑定SHA256。时间必须带时区且为上海当天，范围截至昨日；密集账户日报/SEM逐配置账户或叶表核对每天；项目日报仍保留稀疏原始行，不补造零。SEM还要求来源自身完成标志，不能以下载时刻或一般填报时点代替。

正常发布模式在广告来源验收后刷新业务双仓；prepare模式只复用上海当天已验收的双仓联合回执，未就绪时阻断，不刷新双仓指针。同批输入、来源身份、选定费用清单及显式计算源码在构建/发布前复核。相同真实输入仅复查已发布版本；同日费用或业务字节改变允许新批次。失败会保留回执，尚未发布则不改变线上current；若发布请求结果不确定，回执明确记录uncertain，必须核对服务器后续跑，不盲目重发。

## Desktop main集成与真实单源验收（10月28日续）

唯一正式工作区已迁入 `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily`，c373仅保留开发及本次采集证据。主线原有full_daily/daily与开发树一致；本次仅追加广告连接器包、Ocean和XHS/SEM页面适配器、原件路径intake及3份测试，共7个文件。未覆盖主线library.py去除旧模型JSON的改动或P3现行路径解析。

在主线运行新增intake，追加复制真实小红书任务T20261028000823原件；SHA-256为6325bdbc4381a92f0b355adf48212a94c06a3a0df76170560c0c4180181e25d7。正式解析后20个子账户、57天、1140条费用、242905.85元，5个零消费品牌主账户不计。费用候选与c373独立候选逐条一致。受控main业务库查询run_main_xhs_20261028_candidate复算10/1—27单平台回收倍数，结果一致；这是单源组件验证，未完整重建39表。

候选标为“现行cash口径回收倍数”：留学cash来自gross_signing_amount且筛正向；语培来自报入现金收入，现行团队路径并非普遍只取正数。本次小红书窗无负向记录，不能据此改写历史口径或未来期间定义。生产计算未修改。

真实原件接入命令（output-dir必须是尚不存在的新批次目录，intake不注册正式费用）：

```bash
cd '/Users/akechi/Desktop/manager -CowH'
.venv/bin/python -B -m data_acquisition.jobs.intake_advertising \
  --inventory /absolute/path/to/raw_inventory.json \
  --output-dir /absolute/path/to/new-intake-directory
```

Computer Use提供显式原件path字符串；intake通过adopt_download_path追加复制、校验XLSX和SHA，不假设CUA下载对象具备Playwright的save_as。received_with_gaps保留缺项，不等于正式源完整。

主线验收：定向66 passed；完整核心917 passed、1 skipped、198 subtests passed。证据 `.local/audits/full-daily-main-20261028/` 内 integration-receipt.json、real-xhs-verification.json、same-window-candidate-query.json、targeted-tests.txt、full-tests.txt。受保护代码、正式费用manifest和current摘要均未改变。

## 独立候选输入交验

新增library build的可选参数 `--advertising-manifest`，calculate和attach_advertising沿现有路径传递；显式输入丢失或校验失败立即失败，不回退正式费用。未提供参数时继续原正式费用路径。prepare仅在本次候选目录生成candidate-sources.json，并将其SHA与捕获原件一起冻结；业务库binding额外保存advertising_inputs，不覆盖旧来源登记。候选报告只写本次目录，不推进current。

中断恢复后核对 `/tmp/verify_independent_xhs.py` 和目标目录均不存在，确认先前创建进程失败没有执行。随后真实运行既有费用计算器，显式使用新小红书候选manifest，经Data Platform读取同批封存事实，并执行正式advertising_rollup.sql。10/1—27结果：语培费用79359.81、分子173988、回收倍数2.1923943618；留学费用41767.13、分子97200、回收倍数2.3271888684。正式费用manifest、当日发布回执、双仓和看板current摘要前后相同。全来源门禁以source_scope_mismatch拒绝单一小红书回执，未塞入旧数据补齐其他来源。

本轮完整核心924 passed、1 skipped、201 subtests passed；包括prepare成功/拒绝/异常的零正式清单与current写入、候选丢失不得回退、候选原件摘要变动阻断和生产默认路径回归。真实证据在 `.local/audits/full-daily-main-20261028/independent-xhs-component/result.json`，SQL受控查询回执由该文件actual_fee_query_receipt引用；测试日志independent-manifest-full-tests.txt。本轮没有执行完整39表全源候选或生产发布。

## 巨量大学与SEM新原件组件续验

已从浏览器独立回执追加封存两份原件并核对SHA，未修改采集目录。巨量大学1862323317815369原18列、9/1—10/27、338条114734.10元；57天均有项目明细。与正式旧原件330自然键逐条金额相同、无删项，新增27日8条2582.09元；10月费用62706.83。现行受控费用SQL算出的大学×抖音同窗为153工单、cash51100、回收倍数0.8149032569；只作该已登记来源的组件候选，不能当巨量全账户已齐或账户级客户归因。

SEM整本17sheet、15叶，既有10叶映射保留。27日15叶原始消费全空，现金公式缓存0不作为完成证明，未生成27日零费用候选。26日有6个已映射叶明确填值，按每日到分现金费用合计5065.33；不能据局部填值认定整本昨日完整。旧1—25日窗口有3条回填：2907的23/24/25日费用由0变771.46、757.19、524.33，增加2052.98。其余247条映射叶表日金额不变；后续应替换整个当月窗口，不能只追加昨天。未登记5叶本次原始消费全空，不猜业务归属。

真实门禁分别返回account_scope_mismatch:ocean、native_completion_missing:sem，完整全源仍blocked。证据 `.local/audits/full-daily-main-20261028/source-components-1412/`：result.json、ocean-validation.json、sem-validation.json、ocean-component/result.json及README.md。正式费用manifest和双仓/看板current摘要不变；未发布或修改任务。

## 腾讯留学范围候选续验

已核验网页账户74749810，追加封存两份原六列CSV（播放口径），未相加或正式登记。旧搜索57天19761.93元、27日232.02，日期覆盖仅能证明该搜索范围。多产品原生16天2278.58元、实际9/1—9/16，所选57天缺41天；10月无记录保留缺失，不补0，品牌等其他产品未覆盖。

新增tencent_native范围解析器和intake显式tencent_account_csv格式；原件以账户/窗口/产品范围分开接收，同一产品重复仍拒绝。CSV不含账户/产品ID，这些身份来自绑定的浏览器核验回执。原件解析和封存不等于正式广告费用口径登记。

旧网络费用中9月微信搜索11387元，新搜索11883.87；10/1—11旧3020、新3140.01；旧9月视频号2191、新多产品2278.58且实际只有16天。金额不等不能据此证明不重复或自动换算返佣。定向61 passed，完整核心935 passed、1 skipped、207 subtests passed。现行业务渠道优先具体微信标签，发布平台产品与微信获客渠道的对应未确认；本轮不将两份报表都并入腾讯广告桶、不整桶替换微信、不计算未对齐渠道的零收入ROI。原生产品互斥和剩余产品范围未证实，账户完整性保持false。

证据 `.local/audits/full-daily-main-20261028/tencent-components-1442/` 内result.json、legacy_search-candidate.json、display_plus-candidate.json、registered-wechat-tencent-costs.json、intake/intake-receipt.json与README.md。全源仍blocked，正式费用/current摘要不变；源目录未修改、未发布或创建任务。

## 非前台巨量4份原件续验

用户要求停止前台后，仅做本地读取/复制/受控SQL，无任何浏览器或GUI调用。新增高中424条123747.47元、预备207条31009.81元、JR留学373条57612.67元、H留学480条78872.68元；4份SHA、原18列和真实行数全部吻合。重叠自然键分别412/205/369/474个，金额全同、无删项；新增12/2/4/6条均属27日，分别1955.76/1.27/1329.33/1547.50元。预备原生项目行实际从9/3开始，9/1—2未补0。

大学沿用原件未重复封存，巨量当前5/7账户合1822条405976.73元。与小红书组成仅原生的6文件2962条候选，单信源及跨文件自然键排重通过，并实际完成现行费用SQL组件计算；不把缺账户时的比值当完整平台ROI。完整全源门禁保持source_scope_mismatch。未补齐的两账户、SEM昨日和腾讯产品范围仍缺，禁止集团回填。

证据 `.local/audits/full-daily-main-20261028/ocean-five-account-candidate/` 内result.json、各账户validation.json、component-result.json、platform-authorities.json及README.md。正式manifest/current摘要不变；本轮未改运行代码，不重复申报此前946项测试为新生产成功，也未发布或改日程。

## 尚未完成，禁止按单源或测试成功启用定时

- Ocean已取得并独立验收5/7账户，1810699393202185、1813785787039897仍待原件；SEM整本17sheet已取得，但10/27全部15叶原始消费为空、完成证明缺失；腾讯广告留学已取得旧搜索57行及多产品16行原生CSV，但多产品缺41天、全产品范围和产品互斥未确认（集团旧金额不再作门禁）。SEM填报18:00惯例不证明完成。腾讯语培保持已知未接入，不补零。
- main尚无独立full-daily-sources配置或完整捕获回执。现有页面适配器要求调用者传入正常登录的同步Playwright Page；未创建浏览器/登录持久化，也未接通Computer Use页面到该对象的支持连接。BI自己的Playwright宿主及OXHOR_BI_CDP仅供原BI来源，不能直接当作广告登录态使用。
- 用户要求的固定请求导出主通道尚缺：各平台真实授权导出请求的接口/筛选负载、返回任务ID、状态查询和结果下载的已验证契约，以及在同一正常授权会话内执行这些请求的受支持连接点。此项已被下节小红书真实请求链路证据部分更新；巨量和腾讯仍缺实际请求契约。不能猜API或抢占浏览器任务；专用状态持久化已有用户授权，仍须使用工具支持的本地路径。原生UI下载为已验证小红书兜底路线；导出任务未知结果须先核查同一任务，不盲目重提。
- full_daily --prepare已改为独立candidate-sources.json，沿library build --advertising-manifest传入原计算器；候选manifest及原件闭包另绑定摘要。成功、失败和异常均不写正式费用manifest、双仓current、看板current或Full/current，不执行清单恢复；正常发布默认输入与发布行为不变。该实现已完成单源真实组件验证和隔离门禁测试，全源候选仍等待其余来源。
- 今天禁止切正式current、通知或生产定时。本次未访问服务器、发送或修改任务。目标为完整真实候选通过后首跑2026-10-29 09:30 Asia/Shanghai；尚未配置。新bi-2为每周清理任务，保持不动，不能当作旧日更收口对象。表格ID同步、17:50巡检及已暂停Dot/raw/通知保持原状。


## 小红书真实请求链路与本机模块（17:30续验）

浏览器线程在原登录会话通过受支持CDP Runtime.evaluate执行POST创建、POST任务查询、浏览器内存中的下载链接下载，任务T20261028001653。创建往返116ms，服务端生成3秒；原件20子账户57天242905.85元，SHA72554b3e081267048083d0d6c8911f20561cde6e14f7dfdfa6e99d27b2d4feed。本线程独立复核并追加隔离intake，正式manifest/current摘要不变；证据 `.local/audits/full-daily-main-20261028/xhs-request-module/result.json`。该原件是小红书同窗替代候选，不与先前导出相加。

新增 `data_acquisition/connectors/advertising/xhs_requests.py`：真实两POST契约、唯一新任务身份绑定、分阶段超时、结果未知只查原任务、恢复时不重建、完整已落地文件复核、文件SHA和现有intake。作业目录互斥；任务列表仅已观察成功枚举才下载。未观察的失败枚举不猜测。当前分页20条内必须有已核实参考任务，缺失会明确阻断，尚未作为跨日部署入口验收。

本模块可注入调用者拥有的请求/下载方法；默认Python HTTP仅按已授权专用Cookie文件构造请求，尚未实网验证，不能把浏览器内fetch成功冒称urllib成功。CLI如下（当前专用认证尚未保存，不能按已上线命令宣称成功）：

```sh
.venv/bin/python -B -m data_acquisition.connectors.advertising.xhs_requests \
  --workspace customers/shadow_bi_daily \
  --contract .local/audits/full-daily-browser-20261028-reconnected/xhs-network-sample/network-contract.json \
  --verification .local/audits/xhs-request-authorization-20261028/verified-source.json \
  --output-dir .local/audits/xhs-request-job-20261028 \
  --start 2026-09-01 --through 2026-10-27
```

该命令会发出一次平台导出创建请求、轮询、下载到专属作业目录并追加intake，不登记正式费用、不计算完整看板、不切current或通知；同一目录恢复不会重发创建。必须先确认无同范围未知任务，且通过完整来源门禁后才能进入全源候选。

现有 `write_auth_session` 保留cookies数组/localStorage对象格式，新增xhs/ocean/tencent_ads隔离目录，目录0700、临时文件写入前0600并原子替换。未读取、提取或保存真实广告凭据；三个cookies文件均不存在。BI仍使用原服务目录，未扩大登录范围。

当前桥接的精确缺口：受支持CDP返回值只存在CUA工具运行时，现有已展示工具文档仅列nodeRepl.write/emitImage输出，未列直接本地文件/子进程/调用Python函数的能力；functions.exec与CUA不共享运行时变量。不能经nodeRepl.write、聊天或命令参数中转Cookie。缺少storageState便利方法本身不是结论，缺少“运行时内值直接交既有本地writer”的已支持通道才是尚待核实处。没有执行被拒动作、读取浏览器私密库、开新浏览器、修改端口或临时公网接收器。原CDP宿主当前会话内重复采集已证明，但无人值守跨日与登录失效恢复仍未证明。

本轮请求模块及认证定向14 passed；主核心命令pytest -q tests：571 passed、1 skipped、130 subtests passed，日志xhs-request-module/core-tests.txt。直接从根目录自动发现另因market_workspace内既有同名test_data模块冲突而收集失败，见root-collection-test.txt；没有为此改动无关市场程序。git diff --check通过。

## 请求证据接入与样本接收（后续核验）

小红书模块新增build_candidate，复用正式manifest中唯一已确认xhs_mcc_daily条目的品牌映射和来源ID，只替换本次隔离输入路径、SHA及窗口，不复制其他集团汇总来源、不与旧小红书累加。成功CLI在作业目录生成candidate-sources.json、capture.json和candidate-validation.json，供full_daily现有门禁消费；单平台片段不具备全源完整性。真实T20261028001653原件已生成该片段，1140条子账户分日费用，来源ID沿用xhs_mcc_20261027（身份沿用不等于日期未更新）。证据xhs-request-module/source-bridge-result.json；正式manifest/current摘要不变。

新增dingtalk_contract仅解析已观察请求，不提供伪造的提交/轮询响应实现。任务32377865292文件已自然落地，SHA3eba3b323d41323d273b228506bed1235738324dbc1c9b00b5d6655cd5c9d2cd；独立读取时对所有sheet调用reset_dimensions后比较完整实际值/公式及缓存值，17sheet全部相同，10/27的15叶原始消费仍为空。HTTP200及最终文件不能补出已丢失响应JSON，也不代表脚本重放成功。监听已由浏览器线程关闭；无重复任务。证据xhs-request-module/dingtalk-native-validation.json与dingtalk-observed-validation.json。

浏览器线程的runtime-bridge-capabilities.json明确：没有直接变量写文件API，但仍在实测受支持标准下载的无秘密样本，不能把“无直接API”扩张为“所有安全传递均不可能”。本地现有auth_sessions新增import_auth_session_file，接收明确绝对路径+SHA，验证cookies数组/localStorage对象，默认save=False只返回数量与格式状态；save=True才调用原write_auth_session，保持0700/0600。只在收到明确样本路径后读取；本轮仅虚构临时样本测试，尚未读取真实广告秘密或向正式认证目录写入占位样本。

收样调用契约（由单一接收者使用，结果不得包含字段值）：

```python
from data_acquisition.auth.auth_sessions import AuthSessionPaths, import_auth_session_file
result = import_auth_session_file('xhs', source=explicit_sample_path,
    expected_sha256=explicit_sample_sha256,
    paths=AuthSessionPaths(explicit_workspace, 'xhs'), save=False)
```

完整核心本轮578 passed、1 skipped、130 subtests passed（收样函数加入前）；新增收样/认证/请求定向26 passed。最后一次完整核心结果另存source-bridge-core-tests.txt，不能将这些测试替代跨日实网验收。腾讯现网页账户归属未重新核验、巨量再次顶层权限拒绝已停止，工程侧不重试或绕路。未发布、启用日程或操作浏览器。

本阶段最终核心回归：584 passed、1 skipped、130 subtests passed，日志xhs-request-module/source-bridge-core-tests.txt；git diff --check通过。真实认证文件仍未保存，等待明确无秘密样本路径与SHA后接收；未把格式测试称为实际会话持久化。

## 认证桥接收口与唯一后续完成路径

浏览器auth-bridge-probe-20261028/result.json已实证：两个无秘密Blob下载变体都未取得文件或可靠path，没有拒绝但原因未知，已停止重试；本地写入器样本成功不能替代浏览器导出成功。没有实际广告认证文件，不再等待该失败路线的样本落地。

必要缺口：现有PlaywrightBIExportClient在自己拥有的context中读取cookies/localStorage并直接调用write_auth_session；当前小红书普通Chrome会话属于CUA宿主，没有已验证的状态落盘桥接，不能把BI的context/cookies扩成广告登录。当前CDP会话请求成功与本地Python无人值守宿主是两段不同的已验收程度。

只保留一条可执行完成路径：现有小红书请求入口新增显式--login，使用已安装Playwright启动独立普通Chrome上下文，在 https://mcc.xiaohongshu.com 正常登录一次，用户回终端按回车后，仅以已观察task/list查询验证登录，context.cookies([ORIGIN])+当前站点localStorage直接交原write_auth_session保存到工作区auth_sessions/xhs。没有BI会话扩权、Chrome私密库读取、端口修改或新网络接收器，不创建第二套认证格式或持久profile。此选项尚未真实启动；会新开窗口，需本人一次正常登录/扫码和回车。

完成命令（由安排好用户交互窗口的单一执行者执行，当前未执行）：

```sh
.venv/bin/python -B -m data_acquisition.connectors.advertising.xhs_requests \\
  --workspace customers/shadow_bi_daily \\
  --contract .local/audits/full-daily-browser-20261028-reconnected/xhs-network-sample/network-contract.json \\
  --verification .local/audits/xhs-request-authorization-20261028/verified-source.json \\
  --output-dir .local/audits/xhs-request-authorization-20261028 \\
  --start 2026-09-01 --through 2026-10-27 --login
```

登录验证只查询任务，不创建导出；保存后默认HTTP先读取任务基线，未验证API成功或找不到已核实组织参考任务会阻断，不能宣称肯定能导出。基线通过才创建一次新任务并沿同一作业目录恢复。实际需验收该次请求/文件/intake/candidate，以及随后无--login重跑的幂等复用；这些尚未实网完成，更不能替代跨日真实验收。没有启动登录、请求导出或定时。钉钉响应体缺失保持明确阻塞，巨量拒绝不重试。

显式登录选项加入后的完整核心回归586 passed、1 skipped、130 subtests passed；日志xhs-request-module/login-option-core-tests.txt。CLI --help已验证，真实窗口未启动；正式manifest/current最终摘要仍相同。

## Cookie优先机制核对与新脚本对齐

原BI并非cookies.json注入HTTP：bi_downloads.py的PlaywrightBIExportClient.open复用专用持久profile（或显式OXHOR_BI_CDP原BI宿主），打开BI页，_wait_for_login按页面位置等待正常登录，_export_auth_session保存context.cookies/localStorage；trigger_export/poll_download在页内fetch，浏览器自动带登录态。认证JSON是输出，不是此入口的注入输入。导出超时重试与Cookie失效恢复是不同机制，原BI未实现独立HTTP先跑、401弹窗刷新再重试的闭环。

本节核对时的腾讯文档下载器曾以Cookie调用网页导出接口；该实现已于2026-11-02删除，当前唯一在线入口为官方MCP，详见文首。此处不再提供旧下载器的调用或恢复路径。

新小红书入口已默认Cookie优先：run_authenticated先直接执行现有请求流程，只有AuthSessionMissingError或AuthSessionExpiredError才调用一次save_login并恢复同一作业目录。已保存有效状态不弹窗；--login旧启动参数可保留，但不再强制登录。只把状态不存在、目标域/路径Cookie全部明确过期、HTTP401视为登录恢复条件；403、非零业务结果、错误域/格式/文件权限、超时、TLS或未知网络结果不触发登录。未观察的平台认证业务码不猜测。请求结果未知期间继续同一任务查询，不因重新登录重建导出。HTTPS使用项目已有certifi CA校验，不关闭证书验证。

当前唯一登录进程session73337仍使用启动时旧代码停在输入等待，未中断或重开；新Cookie优先机制用于后续新调用。用户登录确认后先恢复原进程，若其后请求失败，须检查状态/任务结果，再用更新入口重试同一目录，已有状态将直接复用，不再开窗。尚未收到网站登录完成确认，未写入真实广告认证。

Cookie优先改动最终核心回归598 passed、1 skipped、130 subtests passed；日志xhs-request-module/cookie-first-core-tests.txt，核对回执auth-mechanism-verification.json。尚无真实登录态/独立HTTP复用验收；现有73337单一等待会话未重启。


## 小红书独立HTTP真实验收通过（17:55）

用户完成原专用窗口登录后恢复同一session73337；页内站点/任务查询验证后保存专用xhs状态，目录0700、cookies.json与localStorage.json均0600。旧进程首次HTTP任务查询未确认，检查仅有.run.lock、无state.json，确认未提交导出；没有重开窗口。更新入口复用已保存状态，全程Python urllib独立请求、不启动浏览器，真实完成创建→查任务→下载→intake→候选，任务T20261028001714，只提交一次。

组织新东方国际教育，accountOrgCode1781165251519627264，20子账户57天9/1—10/27。原表1425行：1140子账户费用行242905.85元，285品牌主账户行合0；候选只含1140费用行。新原件SHA15d02cd83e4fe3b25d3864d24157cf2c3334fcae0a26d1efe4c67dfc03ac0c4d，245614字节；与上一原件所有1140个账户×日期费用自然键和金额一致，不相加。

阶段耗时：创建往返0.252秒，服务端生成2秒，下载+原件校验1.004秒；从创建前记录到原件捕获回执6.028秒（不是整个候选耗时），纯轮询耗时未单独计量。另一个新Python进程只用保存Cookie只读查询同一任务成功，耗时0.419秒。随后同目录重跑返回同一T1714，未创建第二任务。当前会话关闭后的独立状态复用已实测，下一自然日与未来登录过期恢复仍须按实况验收，不能把隔离跨日测试当明日生产成功。

来源配置改用verified-source.json中的实际组织身份、orgCode和20账户，不依赖固定T1653始终留在前20条任务列表。每次新任务先校验已确认组织在基线任务列表中；闭合start/through由调用者传入，跨日日期覆盖隔离测试已通过，同一作业目录变更窗口仍拒绝。配置源于本次真实任务验收，不猜账户。正式品牌映射沿用不改。

可复核产物：`.local/audits/xhs-request-authorization-20261028/` 中state.json、independent-verification.json、native.xlsx、verified-source.json、intake/intake-receipt.json、candidate-sources.json、capture.json、candidate-validation.json。三平台凭据不进入该审计目录，真实xhs状态仅保存在工作区data_acquisition/storage/auth_sessions/xhs，内容不输出。

最新可重复执行命令（同目录只验已完成任务，不提交新任务）：

```sh
.venv/bin/python -B -m data_acquisition.connectors.advertising.xhs_requests \\
  --workspace customers/shadow_bi_daily \\
  --contract .local/audits/full-daily-browser-20261028-reconnected/xhs-network-sample/network-contract.json \\
  --verification .local/audits/xhs-request-authorization-20261028/verified-source.json \\
  --output-dir .local/audits/xhs-request-authorization-20261028 \\
  --start 2026-09-01 --through 2026-10-27
```

新日期应由日更宿主生成新的作业目录及上海昨天through，沿同一确认组织/账户配置；此历史验收日期不是固定日更日期。真实来源只完成小红书，巨量2账户缺源且请求采样权限拒绝停止、SEM昨日15叶未填、腾讯请求宿主/产品范围未完整验证，完整全源仍blocked。未发布、发送或启用定时，正式manifest/current最终摘要不变。

来源绑定收口后核心600 passed、1 skipped、130 subtests passed；日志xhs-request-authorization-20261028/core-tests.txt。最终任务仍T1714、submissions=1；登录会话已结束，状态复用真实通过，下一自然日及过期恢复未实测。


## 腾讯两个已知范围独立HTTP验收完成

详见[腾讯原生报表采集](tencent-advertising-export.md)。展示/多产品T117172083687：16行2278.58元，连续1.894秒；旧搜索T117173583721：57行19761.93元，连续2.130秒。均关闭浏览器后独立HTTP创建、轮询、本站授权表单下载和intake，原件与原生历史SHA一致，保护状态复用成功。没有将内部CDN401改成绕过请求；实际正常浏览器下载使用/ap/async_task/download，已捕获并接通。未知创建通过实测任务列表唯一匹配，不盲目重发；截断CSV不接受为完整原件。两个产品分开保存、不相加、41天不补0；品牌等范围、费用候选映射和完整全源仍未通过，正式manifest/current与定时不动。
