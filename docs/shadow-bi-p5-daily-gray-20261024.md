> 2026-10-25最新正式版本为`daily-20261025_184644t`，两业务截至2026-10-24，详细来源及验收见本文末节。下方10月24日批次为历史交验记录；正式代码已收口，当前入口见[部署说明](../dashboard_product/DEPLOYMENT.md)。

# P5 每日更新与全量开放

当前运行版为 **daily-20261026_094052**，业务批次为 `run_shadow_daily_20261026_094052_business`。语培、留学均显示截至 **2026-10-25**。历史合并和主被动平台返修已由总线程独立验收。用户已确认灰度反馈良好并授权全量开放；新版已接入全部18个原账号的原密码，连续日更观察继续。

## 范围与运行

- 唯一施工目录：`/Users/akechi/.codex/worktrees/c373/manager -CowH`。不改Desktop/main、旧静态发布或钉钉任务。
- 首批三人灰度已获用户确认，现按后续授权向全部18个原账号开放完整看板，只读权限相同；不发送邀请或外部消息。
- 独立任务`bi-2`每天09:40（Asia/Shanghai）执行。成功静默，登录失效提示正常登录/扫码，持续失败保留旧批次并通知。
- 当前依赖Mac在线、应用运行及本机持久登录；未接Dot，不承诺电脑离线仍能采集。服务器负责封存业务表重建、核验与切换。
- 看板原生自动刷新默认900秒，跨批次请求自动重载已实测；无需用户每天手动刷新。
- 用户已接受首批性能表现并确认全量开放；不据此声称完成18人并发压测。首页及四个旧HTML入口已按授权跳转新版，旧文件留存用于恢复。

```bash
python3 -u -m dashboard_product.shadow_bi.p5.daily --workspace customers/shadow_bi_daily
```

入口复用现有BI/Tencent连接器、受控业务重算及P4构建/备份/激活。当天已成功时只复查服务器版本和18值，不重复采集。仅同日来源已成功、后续发布失败时可用`--resume <原run_id>`续跑；联合身份变化时拒绝混批。`--publish-prepared`用于发布已经联合回执校验的修复批次，不触发新采集。

## 10月24日来源与日更计数（历史记录，最新见文末）

- BI Snapshot：`snapshot_bi_operations_20261024_094415_repair`。
- 留学 Snapshot：`snapshot_study_abroad_20261024_091402`。
- 本轮修复复用10月24日已捕获窗口与原完整历史，不覆盖原Snapshot；回执保留捕获时间、来源摘要、`repair_of`及`reused_capture`。
- 当日成功回执：`customers/shadow_bi_daily/Output/ShadowDaily/2026-10-24.json`；联合来源状态：`Work/DailyWarehouseRefresh/current.json`及其明确指向的回执。
- 目前只有 **2026-10-24一个真实成功日期**。同日重试、历史重算和多次发布均不增加日更天数。尚需至少两个连续真实日更日期。用户已确认灰度反馈；连续日更观察未满不阻塞本次已授权全量开放，API验证不另计用户试用。

## 历史同期少1条返修

原完整Snapshot某工单连续两行日期为2025-06-01和5月31日。既有业务SQL按来源行号取首行，日更merge却取同ID末行，将工单移出了同期窗口。修复为同来源首行优先，新窗口仍覆盖历史。

受控查询检查原历史窗口482个重复ID：480条原始`grade_attr`变化、1条顾问变化、目标工单日期及明细恢复。它们不是空值噪声，也不等于图表的`grade_name`。482条修复记录的26个业务字段均与10月22日原Snapshot首行一致。

四张语义事实表各仅有目标工单一行实质变化。拆分影响已解释：六月/Q1/FY27的线上、留学预备、抖音及学校/年级同期工单增加1，同比重算；活动从“未填写活动”恢复至原活动。其他41个现金占比差异为浮点尾差，最大2.78×10⁻¹⁷，不改变金额及显示。

总线程观远“查看查询语句”的实际公式与页面已留证。卡片逐行SUM按当同期分组；当同期是上游预处理字段，本次结合独立同期导出和具体来源行证据，不由卡片原文推定全部ETL，也不取消既有业务去重。

| 范围 | 工单 当期/同期 | 现金 当期/同期（元） | 人头 当期/同期 |
| --- | --- | --- | --- |
| 被动 | 8,722 / 9,539 | 17,873,967.30 / 20,968,685.60 | 1,239 / 1,493 |
| 主动 | 3,320 / 3,373 | 19,013,577.40 / 23,371,363.80 | 1,121 / 1,369 |
| 全部已分类 | 12,042 / 12,912 | 36,887,544.70 / 44,340,049.40 | 2,358 / 2,861 |

未分类工单7/6单独保留核查；原始全盘12,049/12,918包含这些记录。人头按学员去重，不能把两范围人数直接相加。现金、人头12数的外部观远实查由总线程完成，本线程修复后核对保持不变。

## 平台主被动返修

原被动范围经费用步骤使用品牌归一，主动/全部直接使用二级渠道，导致“抖音”与“抖音来客”并存，且主动/全部缺业务组叶子。现三范围共用既有`classify_business_fact`，平台表、线上视图、业务组展开和筛选选项使用同一品牌桶。

关联现金先以同批完整工单上下文确定品牌，再按现金自身主被动筛选。新增可复现回归覆盖“被动工单抖音来客＋主动现金灵蹊”的跨范围关联，不改变现金自身主被动。三范围各自提供业务组叶子的工单、现金、同期及截止日新增，移除从被动广告叶子补主动/全部的路径。

平台和业务组选项来自三范围真实数据并集。业务组筛选只作用于语培平台，留学板块保持独立；留学费用保留整体×平台，国家/语种费用及ROI继续为空。主动/全部没有对应费用口径时不借用被动费用或ROI。

## 验证与恢复

私有证据统一放在`.local/audits/shadow-bi-p5-20261024/`：

- 历史修复：`repair-original-first-row-equality.json`、`repair-regression.json`、`repair-source-field-diff.json`、`repair-dimension-regression.json`、`repair-semantic-fact-diff.json`。
- 外部公式：`guanyuan-formula-comparison.json`和`parent-guanyuan-*`原文/页面。
- 平台修复：`platform-batch-regression.json`验证198条平台范围记录的品牌、父子及可加指标守恒；不直接相加人头。被动平台父值、留学及费用来源保持不变。
- 原生呈现：`platform-native-sql-regression.json`的6组同批SQL/HTML检查；`platform-live-api-summary.json`的113次真实API请求、24组回归，覆盖范围、业务组、展开、清除、排序、留学隔离及相邻视图。
- 单元/集成测试：`platform-tests-final.log`共70项通过；含无关business_query回执不阻塞下一批、本批损坏来源回执仍拒绝、跨范围关联现金、平台守恒与负向现金。
- 部署与权限：`platform-metadata-retry.log`、`platform-server-18.json`、`platform-readers.json`、`platform-server-final.txt`、`platform-code-sha256.json`及真实浏览器证据。

第一次元数据检查误用内部HTTP，Secure Cookie未发送，SQL Lab请求因缺CSRF会话令牌返回400；同一有效请求通过真实HTTPS返回403。保留`sql-lab-transport-diagnosis.json`和自动恢复日志，不放宽权限检查。重新部署后通过真实HTTPS三账号21项验证。

本次跨代码与元数据发布前备份为`/var/lib/shadow-bi/backups/20261024T021842Z`，含`metadata.dump`、`code-before.tar.gz`、配置及校验摘要。前一数据版本为`daily-20261024_094415r-retry100046`。本次前端回退需配套恢复代码、元数据和旧发布目录，不能只改current；正常后续日更继续使用既有P4数据切换及失败回滚。

## 运行观察待办

继续记录至少后两个连续真实日更日期，日更任务保持启用；同日重试和修复只计一天。全量开放及入口切换已获授权并实施，不再等待三人反馈。

## 原入口切换（2026-10-24 用户明确要求）

首页、index.html、online.html、prep_high.html、university.html的HTTP/HTTPS入口均302跳至新版原生看板，并发送Cache-Control: no-store。Superset现执行全部原账号的既有密码及完整看板只读权限。根线程已独立验证10入口响应，并在原online.html实际刷新看到新版及截至10月23日数据。证据parent-entry-redirects.json、parent-old-url-new-dashboard.png。Nginx备份：/root/shadow-bi-entry-backup-20261024T031123Z。此切换覆盖此前保留旧静态入口的安排，不代表连续三日更新观察已经完成。

## 原账号原密码接入（2026-10-24）

唯一业务认证权威为服务器原`/etc/nginx/dashboard.htpasswd`，18个原账号名称和密码条目保持原样。Superset以自定义认证管理器校验原APR1密码，不导入原密码摘要、不回退到新生成的业务密码；全部原账号映射为`Gamma + ShadowReaderData`。仅显式登记的两个既有维护/测试服务账号保留自身认证。

原密码文件内容摘要核对未变；通过ACL只授予`shadowbi`读取权，无写权，原Nginx读取权保留。旧三人随机凭据文件已从本地工作区和服务器删除，元数据库业务密码禁用。实现使用既有OpenSSL，无自建密码算法。

证据位于审计目录`legacy-auth/`：6项认证测试通过，`all-accounts.json`验证18个原条目全部映射、无业务Admin、无额外活跃业务账号、服务只读原密码文件；`readonly-seven.json`为总线程使用一个已知原密码执行的真实HTTPS七项只读验证。未知原密码没有猜测或重置，不宣称18人逐一实际登录。原入口实际进入新版的浏览器验收由总线程完成。

认证发布备份为`/var/lib/shadow-bi/backups/20261024T033022Z`，包含切换后的入口配置及此前代码/元数据库，恢复认证须使用此备份以保留已授权跳转。第一次检查因维护标记尚在得到503，已修正检查顺序并重新部署；`deploy-retry.log`记录成功及同批18指标通过。数据版本仍为`daily-20261024_101415q`，认证调整不产生新日更日期。

## 2026-10-25 手动补刷成功

用户要求重跑新版看板例行并补刷腾讯文档。本次仅在c373工作树执行，复用当天11:47已成功采集的BI `snapshot_bi_operations_20261025_114521`；重新核对原始工单/现金导出摘要及Snapshot全部manifest文件摘要后保留该身份。续用Chrome当前腾讯登录态重新导出并成功更新留学仓为 `snapshot_study_abroad_20261025_184644`，当前源已通过标准化，未猜补此前缺失咨询类型。原失败回执保留，新的联合批次显式记录BI复用来源及腾讯本次捕获，门禁passed。

已运行既有`p5.daily --publish-prepared`完成重算、服务器构建、备份和激活。当前版本`daily-20261025_184644t`，两业务均截至2026-10-24；实际current与成功回执一致，服务器三范围18数对账通过，Chrome刷新后日期和被动工单8749/同期9580等可见数值匹配。仅刷新看板，无钉钉投递或任务配置变更。10月24日及25日两天已有真实成功记录，仍不宣称三日观察完成。

当日回执：`customers/shadow_bi_daily/Output/ShadowDaily/2026-10-25.json`。审计：`.local/audits/shadow-bi-p5-20261025-manual/`，含`prepare_recovery.py`、`prepared.json`、`tencent-result.json`、`server-verification.json`和`live-dashboard.png`；发布完整日志在该日更批次的`publish.log`。


## 2026-10-26 手动运行成功

用户要求再次刷新今天的新版看板。在c373运行既有`p5.daily`，批次`run_shadow_daily_20261026_094052`；BI工单第一轮导出持续HTTP 500且超时，既有第二轮重试成功，现金第一轮成功，未调整重试配置或业务规则。BI/腾讯均重新采集，双仓`Snapshot`分别为`snapshot_bi_operations_20261026_094052`及`snapshot_study_abroad_20261026_094052`，联合门禁passed。

已备份并激活`daily-20261026_094052`，服务器实际current与当日成功回执一致，三范围18项关键值核对通过。Chrome刷新后语培/留学均显示截至10月25日，被动FY27工单8791/同期9616、现金18247578.60/同期21702015.50、人头1260/同期1521与同批核对结果一致。未发钉钉、未改日更任务。

10月24/25/26三个连续日期均已有真实成功发布回执；同日重试仅计一天。这只确认连续三日运行记录，不自动替代阶段整体验收。证据为当日`Output/ShadowDaily/2026-10-26.json`、本批`publish.log`及`.local/audits/shadow-bi-p5-20261026-manual/`中的`daily.log`、`server-verification.json`和`live-dashboard.png`。

2026-10-26后续：用户明确要求一并执行钉钉推送，已在10时窗口通过服务器固定通知入口发送同批8消息至原5通道。发送回执及持久状态均为8条sent，无失败/unknown；未改日程，同日后续调用继续去重。完整回执见`docs/bi-notification-adapter-20261025.md`末节及本日审计目录。
