# 日常监控

当前投递合同为8条消息／原5通道，消费 `management.build` 的同批通知结果，不独立核算留学或语培。腾讯来源、标准历史、大学现金栏及高中留学简报源码已在Grok同步并通过预览；最新 `run_grok_tencent_view_final_20261009` 的8条消息均为空跑，未实际发送，也未切换生产通知批次。2026-10-03的P3/P4/P5属于原版本上线记录，不代表腾讯新版已正式激活或已发送。完整验收边界见 [同步说明](../SYNC.md)。

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

## 个人通知共创权重（2026-10-08）

通知个人当日结果与逐笔流水按管理侧 `co_creation_weights` 的当前有效人员映射分配。个人工单、现金和人头继续使用原资格，人头保留学员去重及同一人员同一学员取最大有效份额；部门总量、去重、指标资格、目标和固定绩效通知窗口不变。通知留学实际来自同批独立留学Snapshot，缺编号按已确认姓名规则在同业务域暂定去重；人员历史确认汇总与流转参考不直接冒充新的通知事实。

旧 `notify`、`digest`、独立通知SQL和旧线上双消息入口已退役；历史部署回执见[历史部署记录](../docs/monitoring-cloud-deployment.md)，不得用于恢复旧命令。
