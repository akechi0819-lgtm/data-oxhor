> **10月26日最新运行记录**：raw接收/计算/发布已暂停，保留Mac更新链路与既有成品/通知入口；服务器数仓和聚合代码能力仍保留。以[清理与暂停回执](../../../../docs/server-cleanup-20261026.md)区分能力部署与当前启停。本轮未实读或修改服务器/日程，以下raw说明为代码/已部署能力合同，不是恢复运行指令。

# BI 服务器接收与发布代码说明

本目录同时保留成品表发布、三 Excel raw 计算和通知队列相关服务文件。部署状态以[正式 BI 部署说明](../../../DEPLOYMENT.md)及相应日期回执为准；本轮没有实读服务器或调度平台。

## 成品表接收与固定 P4 发布

`receiver.py` 实现内部 `POST /v1/batches` 与 `GET /v1/batches/<release>`，按manifest声明校验原生BI成品表归档并写入待发布队列（正常正式批次为39张表）；`publish-pending.sh` 再调用 P4 重建、校验并切换 release。它仍是原生 BI 成品表接口，不是旧静态31文件站点，也不负责原始三 Excel 的服务器计算。Mac `p5.daily` 是另一条仍存在的手动路径：它在本地更新并构建表，再经 SSH 传到服务器调用 P4；不代表默认生产入口。

`publish-pending.sh` 中 `write_receiver_state` 现将 `last_published`、`last_published_hash` 与 `last_failed` 原子写为 `root:shadowbi`、模式 `0640`。此前回收说明记录的 UMask 权限缺陷属于历史问题，当前源码已修复；本轮未实读服务器来确认已安装文件状态。

## 三 Excel raw 计算与发布

当前服务器 raw 链路接收固定 BI 工单、BI 现金和腾讯 Excel 包：`POST /shadow-bi/v1/raw-batches` 接收入队，GET 同批状态；worker 基于 root 只读历史基线，在隔离副本更新双 Snapshot、运行 quality 和共享业务计算，封存39张业务表。只有同批状态为 `prepared` 才能请求 `POST /shadow-bi/v1/raw-batches/<batch>/publish-prepared`；该请求不接收命令或路径，root publisher 再按 P4 合同复核并切换 release。`raw_inputs.py`、`raw_receiver.py`、`raw_consumer.py`、`raw_compute.py` 和 `raw_publish.py` 分别实现组包、接收、消费、计算及固定发布。

10月26日部署回执记录服务器真实批次已完成双 Snapshot、quality 并计算到39表，随后因业务截止不匹配以 `failed/published=false` 结束；该批没有发布 release。当前 `main` 的来源完整性证明门禁尚未部署到该服务器版本，不得从本地源码推断门禁已生效。详见[raw 链路合同](../../../../docs/server-raw-pipeline-contract.md)、[接收部署回执](../../../../docs/server-raw-receiver-deployment-20261026.md)、[固定发布回执](../../../../docs/server-raw-fixed-publisher-20261026.md)和[部署说明](../../../DEPLOYMENT.md)。

## 通知任务接口

固定通知接口为 `GET /shadow-bi/v1/notifications/status`、`POST /shadow-bi/v1/notifications/jobs` 和 `GET /shadow-bi/v1/notifications/jobs/<job_id>`。提交只接受 `operation`、`expected_release`、`as_of_date`，以及可选 `retry`；操作限定为 `preview` 或 `send-scheduled`，不接受命令、路径或收件人。正式发送还须满足上海10:00窗口、当天正式 release、截止日及 DeliveryState 门禁。接口合同与任务状态见[通知模块说明](../../../../monitoring_product/README.md)和[10月26日通知作业回执](../../../../docs/notification-job-receipt-repair-20261026.md)；Dot 10:00 日程属于通知，不是 BI 更新调度。
