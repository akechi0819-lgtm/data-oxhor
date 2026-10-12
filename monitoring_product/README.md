# 日常监控

当前投递合同为8条消息／原5通道，消费 `management.build` 的同批通知结果，不独立核算留学或语培。2026-10-12用户授权从本机执行一次双仓更新、看板刷新和推送：`run_management_local_20261012_1138` 使用当天两仓、数据截至10月11日，8条消息全部取得sent回执，无失败／unknown，持久去重状态位于本机工作区 `Work/DeliveryState/shared_delivery_state.json`。Grok例行及云端指针未改；不能从本机成功倒推云端已恢复，也不能在恢复后重复补发本日同8条消息。运行证据见[本机正式运行](../docs/local-production-run-20261012.md)。2026-10-09的 `run_grok_tencent_view_final_20261009` 是早期空跑记录，不代表当时已发送；完整同步边界见 [同步说明](../SYNC.md)。

`monitoring_product.shared_delivery` 是直接消费已验收共同结果的通用投递适配，不独立取数。现有daily/deliver入口继续复用，平台例行当前启停需实读。只读命令留作复核：

```bash
python3 -m monitoring_product.shared_delivery \
  --shared-result <本批次>/shared_result.json \
  --output-dir <本批次>/delivery_preview \
  --as-of-date <notifications.metadata.as_of_date> \
  --state-dir <客户工作区>/Work/DeliveryState \
  --dashboard-base-url http://dashboard.apinova.cn --dry-run
```

适配器的正式调用需显式加入 `--env-file <C层凭据文件>`，要求当天新Snapshot、昨日数据截止及完整五通道配置。持久 `state-dir` 跨批次复用，按日期/通道/消息去重；已成功不再发送，请求结果未知则阻断该条重发并报告，其他可安全继续的消息分别留回执。同群双消息使用独立图片/附件路径。dry-run不读取凭据、不建投递状态、不上传、不发送，允许封存历史数据演练；历史预览成功不表示正式新鲜度检查通过。预览与组包不等于正式发送或激活；正式状态需对应批次的发送／activation回执。

2026-10-09大学语培推送保留原工单与人头栏，追加“现金完成（元）”，取同批个人实际现金。HTML、PNG、Markdown显示一致，Excel原现金字段保留；大学留学现金仍沿同批来源。图片画布随列宽扩展，不因新增现金列裁切。此修改已同步Grok并进入同批预览；本次验收未发送，不调整既有接收渠道。

## Grok例行接入

生产调用 `deploy/deliver_management_batch.sh`，工作目录设为现有dashboard源码目录，显式传入 `PROJECT_ROOT`、`WORKSPACE`、warehouse虚拟环境 `PYTHON` 和原 `ENV_FILE`。入口先核验当天双仓共同回执，再读取 `Work/ManagementDelivery/batch.json` 指定的run、Snapshot、日期及结果路径，核对同批身份后投递，不通过目录时间选结果，不重新查仓。

原投递节奏为每天10:24（Asia/Shanghai）；10月3日的假期暂停是历史状态，不能据它断言现在仍暂停。平台启停、实际发送和构建预览分别核对，本文不改变例行。当前源码合同为8条消息、原5通道；高中、大学和线上各有同群双消息。高中留学简报消费本组个人完成、渠道及流水，不生成部门留学完成；虚拟人工单按已确认混合贡献。网页期间选择不改变固定通知窗口。腾讯版已经源码同步／预览通过，本次未真实发送；这不意味着当天其他任务未曾发送。

ROI费用不属于双仓更新或投递例行的数据抓取范围。构建需要费用时，由用户手工提供原表，登记到客户 `Input/AdvertisingCosts/sources.json` 后由管理构建读取；Grok 同样只使用用户手工提供的费用表，不自动抓取。腾讯留学仓的例行导出仍用于留学资源和签约数据。详见[费用与ROI输入说明](../docs/dashboard-advertising-costs.md)。

## 个人通知分配与未分配签约（2026-10-12）

通知个人当日结果与逐笔流水按管理侧共享 `activity_co_creation_weights` 分配。实际业务是主办方本业务时，括号内跨业务接收人不稀释主办方；真实跨业务成果才按明确双方各半、各侧内部均分。未识别或学科人员不补入花名册；留学人工归属不因活动文字自动扩展。同业务共创及虚拟人独立全计沿用现规则。个人工单、现金和人头继续使用原资格，人头保留学员去重及同一人员同一学员取最大有效份额；部门总量、去重、指标资格、目标和固定绩效通知窗口不变。通知留学实际来自同批独立留学Snapshot，缺编号按已确认姓名规则在同业务域暂定去重；人员历史确认汇总与流转参考不直接冒充新的通知事实。

非线上平台、非个人专报的附件在有记录时新增“未分配签约”：取同部门／业务线的个人绩效窗现金事实，扣除已有正权重个人贡献的记录，保留原始字段与未分配原因（未匹配当前人员、渠道推断团队、归属人员不在本消息名单或不满足个人资格）。这些记录只供对账，不计入个人业绩；“现金明细”仍为个人流水，线上平台维持团队流水。

本地 `run_management_fix_20261012` 为同仓修正空跑，数据截至10月8日，不用于正式投递。2026-10-12 10:40云端源码安装及145项／8子测试通过；随后本机当天双仓门禁passed，正式新批次 `run_management_local_20261012_1138` 的8条消息已全部发送，实际两笔语培现金在同批附件中均保持权重1；大学附件保留15笔未分配签约核对记录。Grok的失败批次和本机成功批次分别保留，不混写宿主状态。[同仓回归记录](../docs/dashboard-allocation-regression-20261012.md)保留最初复现，[正式运行](../docs/local-production-run-20261012.md)记录当天真实发送。

旧 `notify`、`digest`、独立通知SQL和旧线上双消息入口已退役；历史部署回执见[历史部署记录](../docs/monitoring-cloud-deployment.md)，不得用于恢复旧命令。
