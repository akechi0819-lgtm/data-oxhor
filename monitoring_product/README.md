# 日常监控

> 状态依据截至 2026-10-26 的日期回执：固定服务器通知适配已部署，8条消息／原5通道从固定正式 release 构建并经 `shared_delivery` 去重投递，不独立查询数仓。10-26人工触发有8条 `sent` 记录；另一个HTTP job保留 `unknown`，只读对账确认它们来自此前发送且 `no_send_performed=true`，不得把job本身记为sent或重发。正式BI为Superset原生界面；服务器raw worker已实际运行到39张业务表，但10-26候选因截止门禁失败、未发布release。Dot日程自10-26起的每日上海10:00记录用于通知，不是BI采集／刷新调度。本次没有读取调度平台当前状态。回执见[通知作业修复记录](../docs/notification-job-receipt-repair-20261026.md)和[BI部署说明](../dashboard_product/DEPLOYMENT.md)。

`monitoring_product.server_notify` 是服务器固定入口：`status` 报告固定服务状态，不读取外部日程状态；`preview` 默认不发送；`send-scheduled` 只允许上海 10:00 且要求当天正式 release 和已导入 DeliveryState。模块本身不安装调度器；外部日程与 BI 更新日程分别管理。正式通知包由 `release_notifications` 从固定的正式 BI release 构建，绑定来源、规则和查询回执；`shared_delivery` 保持逐消息去重和传输。大学与线上平台各两条消息分别共用原群。人员规则及花名册仍共用 `workspace_modeling/operations/`。

本地需要复核已有 `shared_result.json` 时，可用以下 dry-run；它只渲染预览，不是服务器定时发送入口：

```bash
python3 -m monitoring_product.shared_delivery \
  --shared-result <本批次>/shared_result.json \
  --output-dir <本批次>/delivery_preview \
  --as-of-date <上海通知日期YYYY-MM-DD> \
  --state-dir <客户工作区>/Work/DeliveryState \
  --dashboard-base-url 'https://dashboard.apinova.cn/superset/dashboard/shadow-bi-native/?standalone=1' --dry-run
```

本地离线预览不读取凭据、不写投递状态、不上传或发送。服务器正式触发必须使用固定入口及当天 release，需满足新 Snapshot、`data_through` 为昨日、完整五通道配置和导入的原始 DeliveryState；已成功或结果未知的消息都不能盲目重发。

## 历史本机与Grok验收记录

2026-10-12 用户授权的本机批次 `run_management_local_20261012_1138` 使用当天两仓、数据截至 10-11，8 条消息全部取得 sent 回执，无失败／unknown；当时持久状态位于工作区 `Work/DeliveryState/shared_delivery_state.json`。这是历史批次，不能用于推断当前云端状态或触发补发。运行证据见[本机正式运行](../docs/local-production-run-20261012.md)。2026-10-09 的 `run_grok_tencent_view_final_20261009` 是更早的空跑，不代表当时已发送。

2026-10-09 大学语培推送曾保留原工单与人头栏，追加“现金完成（元）”，取同批个人实际现金；HTML、PNG、Markdown 显示一致，Excel 原现金字段保留。该版本的预览和源码同步记录不代表当前通知部署或日程状态。

## 已停用的 Grok 例行（历史合同）

旧Grok 09:30／09:45／10:24运行时刻及7条消息合同均属于历史版本，不是当前服务器通知入口。用户已要求停止Grok例行；日期回执提供的是停止安排，不构成本页编辑期间的云端实时检查。历史通知部署记录见[监控模块旧部署](../docs/monitoring-cloud-deployment.md)。

ROI 费用不属于双仓更新或通知投递的数据抓取范围。构建需要费用时，由用户手工提供原表，登记到客户 `Input/AdvertisingCosts/sources.json` 后由管理构建读取；其他宿主同样只使用用户提供的费用表，不自动抓取。腾讯留学导出可作为留学资源和签约数据来源，具体刷新安排以当前授权的数据任务为准，本页不宣称仍有 Grok 例行。详见[费用与 ROI 输入说明](../docs/dashboard-advertising-costs.md)。

## 个人通知分配与未分配签约（2026-10-12）

通知个人当日结果与逐笔流水按管理侧共享 `activity_co_creation_weights` 分配。实际业务是主办方本业务时，括号内跨业务接收人不稀释主办方；真实跨业务成果才按明确双方各半、各侧内部均分。未识别或学科人员不补入花名册；留学人工归属不因活动文字自动扩展。同业务共创及虚拟人独立全计沿用现规则。个人工单、现金和人头继续使用原资格，人头保留学员去重及同一人员同一学员取最大有效份额；部门总量、去重、指标资格、目标和固定绩效通知窗口不变。通知留学实际来自同批独立留学Snapshot，缺编号按已确认姓名规则在同业务域暂定去重；人员历史确认汇总与流转参考不直接冒充新的通知事实。

非线上平台、非个人专报的附件在有记录时新增“未分配签约”：取同部门／业务线的个人绩效窗现金事实，扣除已有正权重个人贡献的记录，保留原始字段与未分配原因（未匹配当前人员、渠道推断团队、归属人员不在本消息名单或不满足个人资格）。这些记录只供对账，不计入个人业绩；“现金明细”仍为个人流水，线上平台维持团队流水。

本地 `run_management_fix_20261012` 为同仓修正空跑，数据截至10月8日，不用于正式投递。2026-10-12 10:40云端源码安装及145项／8子测试通过；随后本机当天双仓门禁passed，正式新批次 `run_management_local_20261012_1138` 的8条消息已全部发送，实际两笔语培现金在同批附件中均保持权重1；大学附件保留15笔未分配签约核对记录。Grok的失败批次和本机成功批次分别保留，不混写宿主状态。[同仓回归记录](../docs/dashboard-allocation-regression-20261012.md)保留最初复现，[正式运行](../docs/local-production-run-20261012.md)记录当天真实发送。

旧 `notify`、`digest`、独立通知SQL和旧线上双消息入口已退役；历史部署回执见[历史部署记录](../docs/monitoring-cloud-deployment.md)，不得用于恢复旧命令。
