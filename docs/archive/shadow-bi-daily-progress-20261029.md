# 看板日更阶段记录（上海2026-10-29）

> 本页保留10月29日施工过程与当时阻断，不作为当前运行说明。现行总入口、腾讯竞价＋品牌范围及104列工单反馈见[完整日更说明](shadow-bi-full-daily-20261028.md)；后续完成结果覆盖下方未通过、未启用及待确认状态。

已在用户Mac的唯一现行项目 `/Users/akechi/Desktop/manager -CowH` 跑通小红书、腾讯广告、巨量的正常授权独立HTTP采集，并刷新至10月28日。现金、工单和留学腾讯文档的新原件也已隔离落地。完整看板模拟尚未通过；没有发布、改current、发通知或启用09:30任务。

## 新采集的实际结果

| 来源 | 本次范围及原件 | 实测 | 证据 |
|---|---|---:|---|
| 小红书聚光MCC | 20子账户、58天、247335.79元；主账户不重复计费 | 6.281秒；T20261029000002 | simulation/xhs/state.json、native.xlsx、capture.json |
| 巨量本地推 | 已确认7账户；1858项目分日记录、416158.52元；1空账户有平台返回证明 | 七账户合计约5秒；无需服务端导出任务 | simulation/ocean/verification.json、逐账户原始JSON |
| 腾讯74749810旧搜索 | 58天、19965.62元、播放口径、原生“花费” | 2.229秒；117179623341 | simulation/tencent_search/state.json、native.csv |
| 腾讯74749810展示/多产品 | 选9/1—10/28，实际仍16行9/1—9/16，2278.58元；42天缺记录未补0 | 4.034秒；117179622764 | simulation/tencent_display/state.json、native.csv |
| BI工单 | 请求4/29—10/28，21799行，实际分配时间最大10/27 | 创建一次；原任务87fcd820-d2ee-11f1-b633-b992f32e319c恢复下载 | simulation/bi_raw/orders.xlsx、state.json |
| BI现金 | 同窗15639行，实际业务日期最大10/27 | 创建一次；b2b39900-d2ee-11f1-b633-b992f32e319c | simulation/bi_raw/cash.xlsx、state.json |
| 留学腾讯文档 | FY27前途市场看板整本；现行读取器读出资源4764、留学签约198、小语种93条 | 11.810秒；原件faddb336… | simulation/study_abroad_raw/state.json、business-raw-validation.json |

表中simulation统一指 `.local/audits/full-daily-20261029-simulation/`。全部是正常本机授权状态；本轮最新采集没有前台浏览器窗口。BI初次轮询HTTP500后沿原协议恢复同一工单任务，现金暂态500也只继续同任务轮询；未重建未知任务。原始文件保留，不推进双仓current。工单与现金选到28日但返回最大27日，不能因此宣称28日已完整。

历史9/1—10/27的巨量验收单列于 `.local/audits/ocean-http-20261029-seven-accounts-native-export/component-validation.json`：1829条406416.25元，7账户原生Excel与API逐自然键和费用完全一致。此历史成功不冒充最新28日成功。

新增巨量1880190728515692已单独真实查询，返回TotalCount=0及stat_cost=0；仍未确认业务组，不并入财务候选。已确认7账户继续可用；新账户不会被猜测归组。

## 已接入的工程

- `data_acquisition/connectors/advertising/ocean_requests.py`：真实v2完整导出查询、受保护Cookie优先、明确失效才一次正常登录、原始JSON封存、严格原生投影验证、候选桥接。不是此前有重复页的v3明细分页，也没有虚构导出任务接口。[具体命令与边界](../ocean-advertising-export.md)。
- 已有 `xhs_requests.py`、`tencent_requests.py` 在跨上海日期的新作业目录复用保存状态成功，无再次登录；旧原生采集流程保留兜底。
- 新 `dashboard_product/management/tencent_sources.py` 将两个原生CSV分别接入隔离费用候选，账户、产品、窗口、SHA与真实verified采集state绑定；金额忠实保留“花费”，不擅自换算现金、返佣、税率。
- `candidate_sources.py` 保持每平台单信源，拒绝集团汇总补齐，也拒绝在未证明互斥时把两类腾讯产品费用直接相加。腾讯广告候选保持原生腾讯广告桶；不搬动微信/视频号等现行业务分子，不改变既有ROI口径。
- `full_daily.py` 的prepare继续使用独立manifest；腾讯额外身份证据与巨量原始JSON均随同批输入封存。正常发布默认路径未改。已创建本轮期望范围 `.private/full-daily-sources.json`，明确4个已接来源及腾讯语培已知待接入；无新秘密、无计划启用。

## 模拟实际停在哪里

最新小红书+巨量的3018条候选已通过单信源及跨文件重复校验：小红书247335.79元、巨量416158.52元。两类腾讯CSV也各自通过现行费用解析（58条及16条），但没有相加。

已实际调用总入口：

```sh
python3 -m dashboard_product.shadow_bi.p5.full_daily \
  --workspace customers/shadow_bi_daily --date 2026-10-29 --prepare \
  --capture-receipt .local/audits/full-daily-20261029-simulation/incomplete-capture.json
```

真实结果为退出2、`blocked: source_scope_mismatch`，因为SEM最新有效回执和可合并的腾讯来源尚未齐。该命令是**阻断验收命令**，不能当作全源日更成功命令；没有生成新的39表完整看板。总回执simulation-result.json记录实际prepare结果路径，production-protection-verification.json核对5个既有正式manifest/current摘要前后相同。

剩余事项明确如下：

1. **SEM最新原表**：正常网页此前已成功导出17sheet，保留为已验证取得路径，不重做纯HTTP化。此次恢复现有钉钉页前，`mcp__cua_repl`的`cua.getState()`报`failed to start Node runtime: No such file or directory (os error 2)`。这只说明当前CUA执行器未启动，Mac shell/HTTP正常；没有执行浏览器操作、没有未知SEM导出任务。需由可运行的原浏览器执行会话恢复工具、在同一真实SEM入口下载最新整本并核对10/27和28消费是否填齐；旧成功原件不伪装当天新采集，不将空白或缓存公式零视为已完成。
2. **腾讯范围互斥证明**：旧搜索和展示两入口的账户日期重合16天，原生CSV只有账户分日六列，无产品/广告ID。不同接口和UI标签不足以独立证明费用互斥。因此合并门禁为`candidate_tencent_product_overlap_unverified`。需要平台原生产品/计划维度身份或明确互斥范围证据，才能合并；不回退旧集团汇总、不猜换算。展示缺42日和未观察的其他产品仍如实保留，腾讯语培未接入不当零。
3. **当天业务完整性**：新工单/现金原件已真实取得，窗口内没有越界行，但返回日期最大10/27；目前还不能证明10/28完整。旧双仓current仍是10/28 10:47批次。新原件尚未发布为10/29联合Snapshot，不以旧pair冒充当日新pair。
4. **最终无人值守总宿主**：真实模块及候选片段已具备，总入口目前消费`--capture-receipt`。SEM正常网页阶段与腾讯产品合并未就绪，仍未验收一条能无人值守完成全源采集、计算并安全发布的命令。不能因模块单测或广告采集成功就启用09:30任务。

不需要用户重复登录已成功的三个广告专用会话。当前没有待用户扫码窗口、没有活动未知导出。用户睡后能完成的后台下载和组件验证已继续做；未改旧Dot/raw/群推、周清理、表格同步或17:50巡检。

## 验收与生产状态

完整项目回归记录在simulation/final-tests.txt；最终完整结果1020 passed、1 skipped、207 subtests passed。此结果只证明代码回归，不代替全源真实验收。未自动提交、部署、发布或设置定时。

最后本地已发布回执仍为 `daily-20261028_104710`。本轮没有SSH查询线上新状态或切版，不能把本地未变摘要说成重新完成线上验版。

## 后续收口验收

新增最小采集宿主 `data_acquisition.jobs.prepare_full_daily`，复用已有真实模块，进入现有full_daily生产锁后采集/恢复并汇总来源报告；没有另建调度或登录框架。以下命令已真实执行，同日目录复用已完成作业，没有创建新导出任务：

```sh
python3 -m data_acquisition.jobs.prepare_full_daily \
  --workspace customers/shadow_bi_daily \
  --batch-dir .local/audits/full-daily-20261029-simulation \
  --source-contracts .local/audits/full-daily-browser-20261028-reconnected \
  --xhs-scope .local/audits/xhs-request-authorization-20261028/verified-source.json
```

结果为collection_incomplete，collection-report.json明确列出展示原生缺日、SEM当天回执缺失、腾讯产品互斥未证三项。此入口当前只验收了真实采集/恢复及阻断报告，完整全源准备仍未通过。原source_scope_mismatch准确指期望4来源，输入只有xhs/ocean，缺sem及可合并tencent_ads_abroad；不是已发现日期或SHA错误。

再次复查CUA，仍在任何浏览器操作前报相同Node runtime不存在，未装软件或改安全设置。腾讯静态核对确认旧查询只有PLATFORM_TYPE_ADQ等参数，没有明确BIDDING_SEARCH产品过滤；展示查询也没有排除旧搜索的字段。原生六列缺产品/广告身份，无法证明互斥。此项需要平台原生明细证据或用户口径确认，不用统计或测试充证明。

拟补的腾讯合并成功回执接线被自动审批拒绝，原因正是互斥未证，不得合并标成功；补丁未执行，原阻断未变，未换路重试。详见host-followup.json。

## 上海10/29早晨复核及用户接管

收到“今天日更由用户自己处理”后，不发布、不推送、不启定时、不再追加新采集或前台操作。收尾当时已提交的两个隔离BI任务，均已落地，无未知任务。检查时ShadowDaily生产锁和双仓刷新锁均未被持有；未据此启动生产。

早晨真实原件请求4/29—10/28：工单21893行，其中10/28有94条；现金15685行，其中10/28有46条，均无日期解析失败或越界。两个任务各创建一次，35.356秒完成，不入仓、不改current。凌晨只见27日、早晨已见28日，证明源状态有更新；仍不以最大日期证明28日完整。证据`.local/audits/full-daily-20261029-morning/bi-raw-validation.json`。

腾讯正常专用会话无前台只读复查成功，无需登录；产品列表/账户版本相关请求正常出现，尚无费用互斥新证据。未创建导出或改合并接线，随后停止浏览器工作以避开用户生产。证据simulation/tencent-live-scope-review.json。最小待确认口径是：旧搜索与展示/多产品是否为互斥消耗，还是后者包含前者；无确认则需要产品或广告ID维度明细，不能依据名称相加。

SEM的CUA再试仍在启动阶段报Node runtime找不到。Mac shell及普通Python/HTTP可运行，依赖工具另返回“Workspace dependency tools are only supported for local threads”；未假称整台Mac离线，未装软件、改端口或绕过权限。本轮SEM未新导出，完整看板候选仍未通过。

## 收尾范围调整与静态运行时诊断

按用户最新指令，今天不再刷新、下载或重复验证已通BI/腾讯文档链路；昨日填齐状态不再作为今日脚本施工阻塞，正式发布仍保留完整性门禁。只修复总宿主巨量部分完成后的恢复遗漏：同批已完成账户核验日期、原件和API证据摘要后复用，不重复请求；篡改及跨日阻断。新增纯文件测试4项通过，无真实来源请求。腾讯合并门禁未改。

只读核对官方unified-computer-use 26.1023.51421配置：命令和NODE_REPL_NODE_PATH指向`/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node`，配套node_repl和cua-repl.mjs均存在。Node直接版本探针v24.22.1正常。故无法把工具ENOENT归因为这些文件缺失；实际报错没有披露其失败子进程路径，现有许可范围不足以进一步定位。ps被系统拒绝后停止，没有扩大权限、扫描会话/凭据、安装软件、改配置或重启应用。

本机官方故障文档未给出此错误的明确免重启修复；不替换Node或引入另一个浏览器控制后端。用户生产空闲后，可由官方应用/工具会话重新加载并只试一次轻量清单；这是诊断建议，不是已证实的修复，当前不要求用户立即重启。详见`.local/audits/full-daily-20261029-morning/runtime-static-diagnosis.json`。

## 已有原件的39表隔离工程联跑完成

本轮没有刷新/下载任何来源，复用用户已完成的10/29 09:11:55双仓和既有小红书、巨量、SEM整本及腾讯原件，实际经过现行业务库计算、受控来源查询、投影、封包、表加载和输入摘要核验。腾讯各使用一个产品的两个独立分支分别得到39表，未把产品费用相加，均保留production_ready=false、full_financial_scope_complete=false，SEM为样本接线验证而非当日完成证明。总证据`.local/audits/full-daily-20261029-engineering-result.json`，候选分别位于engineering-candidates-v2/tencent_display/presentation及engineering-candidates-v3/tencent_search/presentation。

首个旧搜索尝试在封包后发现workspace_modeling/operations/people.json由其他工作更新，保护检查正确阻断；没有覆盖该修改。随后用当前规则重建成功。新增修复将广告原生解析/连接器纳入业务库和总入口冻结规则闭包；专门测试通过。最终完整回归1025 passed、1 skipped、207 subtests passed。规则/输入一致性与39表真实候选结果分别报告，不替代正式全来源门禁。

仍待腾讯费用互斥口径及合法联合回执接线、SEM正常浏览器运行时恢复。今日最新数据齐全与否不作为工程施工前置；正式自动日更启用前仍必须通过完整性和无人值守实跑验收。未发布、推送、改变正式current或启用日程。

## 继续收尾：新增可行动结果

腾讯新增只读产品/账户版本元数据核查，没有请求报表数据或新建导出。结果证实产品枚举是营销目的，不能证明两报表排他；已整理具体报表名称、同账户入口、金额及A/B/C最小选择，见docs/tencent-report-scope-choice.md。

SEM宿主追溯确认实际成功是CUA正常网页，当前独立Page导出函数无登录宿主，总入口原来只接手工receipt；本轮新增sem_candidate完成原件到manifest/receipt的自动文件接线，相对路径、证据摘要和样本非生产门禁有测试。既有17表原件真实接入280条，不伪造采集时间/填齐证明。宿主依赖和最小授权操作见docs/sem-host-handoff.md。

## 收尾核验（10/29）

- 腾讯账户74749810的产品枚举只描述营销目的，不能证明旧搜索报表与展示/多产品报表相互排斥。两份报表的入口、请求和原生范围、金额、缺日及最小A/B/C选择已整理在 `docs/tencent-report-scope-choice.md`。在收到口径选择或取得产品/广告ID范围证据前，代码继续拒绝合并；没有改用旧集团汇总。
- SEM的唯一已验证实采路径仍是CUA在钉钉正常网页下载整本；`native_exports.download_sem`要求调用方提供Playwright Page，现有总入口只接收回执。本轮把已存在17表样本接入现有候选manifest/回执路径：10个既有映射叶表、280条解析记录，原件SHA未变，且标记`sample_only`、无采集时间、未完成，不能通过当天来源门禁。宿主证据及最小下一步见 `docs/sem-host-handoff.md`。
- 官方CUA配置里声明的Node及repl文件均存在，Node版本探针v24.22.1成功，但CUA仍在启动阶段报`No such file or directory`且没有给出失败子进程路径。当前只能报告工具运行时不可用，不能据此替换运行时或宣称Mac离线；本轮没有刷新、下载、发布、启日程。
- 修复后完整项目回归：1040 passed、1 skipped、207 subtests passed（25.29秒）；`git diff --check`通过。腾讯互斥、SEM实时宿主与完整无人值守发布验收仍未完成，生产current未由本轮改动。

## 腾讯口径确认后的接线判断

用户已明确“竞价－展示投放 + 竞价－搜索投放”，并排除“搜索广告升级版”。该确认已保存为独立业务口径证据，明确标注它不是平台技术证明。复核现有B原件后发现其菜单说明汇总展示广告、搜索广告升级版、实时竞价、智能投放，CSV没有产品/广告ID；无法单独剥出用户确认要用的纯展示金额。A页面选项是`BIDDING_SEARCH`，但底层请求为`ACCOUNT_REPORT_BY_DATE`账户日报，未带显式该产品筛选，仍不能证明A只含搜索投放。

按新口径，候选校验器现拒绝B并返回`candidate_tencent_display_report_includes_excluded_search_upgrade`；用已有A+B原件做了只读候选校验，确实被此原因阻断，没有相加。相关针对性回归18项通过。要完成合并需要腾讯提供可单独筛选展示投放（排除搜索广告升级版）的原生报表/产品或广告级数据。此处理落实的是用户已确认的业务规则，不能说平台范围已经技术验明。
