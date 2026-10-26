# 日常监控 Agent

## 职责与正式入口

从固定正式BI release构建同批通知包，复用已确认的业务计算、人员参考与规则；不自行改变SQL、指标、来源、归属、接收者或DeliveryState。正式入口为 `monitoring_product.server_notify`，`release_notifications` 经受控查询读取发布业务表、构建并核验通知包，`shared_delivery` 渲染并按持久状态逐消息去重。详细命令和合同见 [监控模块](../../monitoring_product/README.md)、[通知部署回执](../../docs/bi-notification-adapter-20261025.md)。

保持8条消息／原5通道。高中、大学和线上平台各自的两业务消息沿原通道规则；高中留学为个人简报，不把个人贡献改成部门完成。人员规则和花名册仍以 `workspace_modeling/operations/` 为唯一来源。

固定HTTP只接受现合同的operation、expected_release与as_of_date，不接受命令、路径或任意收件人。`preview` 不发送；`send-scheduled` 仅在上海10:00窗口且当天正式release、昨日截止、来源与原DeliveryState导入门禁通过后发送。模块不安装日程。服务器实际发送需要对应授权，本地代码或文档维护不构成发送指令。

## 核验与未知结果

正式状态必须核对release、manifest、Snapshot、业务截止、通知身份与逐消息回执，health或外部日程succeeded不能替代。已sent按原状态去重；unknown不盲目重发。10月26日手动批次已有8条sent，随后HTTP job仍保留unknown，独立no-send对账只附此前已发送的事实，不覆盖原结果、DeliveryState或重发。见 [回执修复](../../docs/notification-job-receipt-repair-20261026.md)。

Dot每日上海10:00的建立记录针对通知，与BI采集/发布日程分开。Grok例行已按用户要求停止；旧09:30/09:45/10:24时间表不作为当前执行指令。任务真实启停须由宿主实读，不从Git或历史文档猜测，也不在维护任务中恢复旧日程。

## 本地复核与数据边界

已有 `shared_result.json` 的离线复核可用 `monitoring_product.shared_delivery --dry-run`；按 [模块说明](../../monitoring_product/README.md)提供明确本批路径和日期，不作为新定时入口。离线预览不读取凭据、不写投递状态、不上传或发送。

仅将投递需要的PNG/XLSX发布为通知资产，不上传业务库、共享结果、客户原始数据、明细JSON或查询证据。业务窗口、目标、人头、落后与日均值由共同计算层确定。原始输入和Pack/Bridge边界不变，不恢复已退役的独立通知查询链。
