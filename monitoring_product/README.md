# 日常监控

本地 a224be6 管理产物、共同结果和只读预览已验收；不重做业务或版式验收。P3已在 Grok 现有云电脑完成真实 management.build 与只读投递/发布演练：61个文件 SHA 一致，`run_grok_p3_20261002` 构建成功，7条消息及18个公开文件检查通过。通用 `monitoring_product.shared_delivery`、`monitoring_product.delivery_transport` 与管理发布 `publication` 保留。P4旧源码与生产入口已清理，P5正式页面已于2026-10-03激活；Pawsy 全量迁移和上传前置已取消。Grok运行状态按已切换的新版Routine继续，真实网页已激活，机器与独立HTTP回执见施工计划第32节。封存交接见[历史记录](../docs/dashboard-dot-handoff-20261001.md)。

`monitoring_product.shared_delivery` 是直接消费已验收共同结果的通用投递适配，不独立取数。P3已在 Grok 现有云电脑完成只读演练，两个实际Routine已切到新版daily/deliver入口且无重复任务。只读命令留作复核：

```bash
python3 -m monitoring_product.shared_delivery \
  --shared-result <本批次>/shared_result.json \
  --output-dir <本批次>/delivery_preview \
  --as-of-date <notifications.metadata.as_of_date> \
  --state-dir <客户工作区>/Work/DeliveryState \
  --dashboard-base-url http://dashboard.apinova.cn --dry-run
```

适配器的正式调用需显式加入 `--env-file <C层凭据文件>`，要求当天新Snapshot、昨日数据截止及完整五通道配置。持久 `state-dir` 跨批次复用，按日期/通道/消息去重；已成功不再发送，请求结果未知则阻断该条重发并报告，其他可安全继续的消息分别留回执。同群双消息使用独立图片/附件路径。dry-run不读取凭据、不建投递状态、不上传、不发送，允许封存历史数据演练；历史预览成功不表示正式新鲜度检查通过。P3实际只读投递和发布组包演练已通过；P5页面激活已完成。

## Grok例行接入

生产调用 `deploy/deliver_management_batch.sh`，工作目录设为现有dashboard源码目录，显式传入 `PROJECT_ROOT`、`WORKSPACE`、warehouse虚拟环境 `PYTHON` 和原 `ENV_FILE`。入口读取 `Work/ManagementDelivery/batch.json` 指定的run、Snapshot、日期及结果路径，核对同批身份后投递，不通过目录时间选结果，不重新查仓。

当前原例行每天10:24（Asia/Shanghai），已切换到该入口，**仍保持假期暂停**，本轮没有发送或补发。当前源码合同为8条消息、原5通道；高中、大学和线上各有同群双消息。2026-10-08新增高中留学个人简报，马玥从大学个人名单迁到高中留学，新增简报只展示本人完成、个人渠道及相关工单流水，不生成部门完成。虚拟人工单按已确认混合贡献；原团队自然月、个人固定绩效月等口径由management共同计算，网页选择不改变播报窗口。本次新增简报尚未同步Grok或正式发送。

## 个人通知共创权重（2026-10-08）

通知个人当日结果与逐笔流水按管理侧 `co_creation_weights` 的当前有效人员映射分配。个人工单、现金和人头继续使用原资格，人头保留学员去重及同一人员同一学员取最大有效份额；部门总量、去重、指标资格、目标和固定绩效通知窗口不变。人员产能用的手工留学参考文件不接入通知。

旧 `notify`、`digest`、独立通知SQL和旧线上双消息入口已退役；历史部署回执见[历史部署记录](../docs/monitoring-cloud-deployment.md)，不得用于恢复旧命令。
