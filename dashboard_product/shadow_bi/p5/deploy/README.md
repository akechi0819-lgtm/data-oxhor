# BI 服务器接收与发布代码说明

日更入口为 `python -m ops run business`。现行调度以 `prepare_full_daily --publish --business-only` 转入同一业务链，发布正式 SQL release 后核验通知。费用通过 `ops ingest-cost` 独立录入，`ops fetch-cost-optional` 可生成隔离采集证据。

## 历史：业务组筛选状态（2026-11-07）

正式 release `daily-sql-overview-group-20261107` 已激活。市场总览的业务组筛选为“市场总计／高中／大学／留学预备”；语培按所选业务组汇总线上、线下各渠道产出，留学及小语种固定显示总盘。11 张语培图联动该筛选，语培学校图已补入；其他页面的口径和样式保持不变。

原有 5,508 行指标与旧仓一致，新增 243 行分组指标与明细独立核算一致；40 项测试通过，2 项按条件跳过。费用为 4,041 行、43 个来源，标注截至 2026-11-06；复用同一批数据，不重采业务及费用源表、不触发日报推送。18 项正式指标与 MCP 5 项检查通过。bi-3 只读复查通过，采集、发布及通知回调均为 0；正式站 93 图、270 个业务分页已完成核对，字段、行数及记录集合全部一致；旧版已退役，服务器仅保留 1 份分析仓，投递状态逐字节不变。

证据：[activation.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/activation.json>)、[publication-receipt.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/publication-receipt.json>)；本批审计目录：[overview-group-20261107](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/>).

最终核验：88 张图逐行顺序相同；5 张图（231、320、331、332、333）仅同值并列行换位，93 张图完整记录集合相同。保留原排序规则；图 231 原网页分页现象未作次排序修复，完整 CSV 的 59 条唯一记录与旧版一致。线上曾触发旧 1400M 服务限额 OOM，已持久调至 4G，3 并发与后续全页复验通过；未改数据、线程数或查询内存配置。

最终回执：[completion.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/completion.json>)。

## 历史：云端基础仓日更（2026-11-04）

当时日更由 Mac 采集配对基础 Snapshot，服务器执行受控 SQL 和共享计算后发布 Superset。费用使用单批表格快照。验版成功后只保留当前版本。该流程为历史记录；现行发布与排查见[正式 BI 部署说明](../../../DEPLOYMENT.md)。

## 退役发布链路

旧成品表接收、三 Excel raw 计算和 Foundation 候选的运行入口已删除。历史运行与当时的状态见 [raw 接收回执](../../../../docs/archive/server-raw-receiver-deployment-20261026.md)、[固定发布回执](../../../../docs/archive/server-raw-fixed-publisher-20261026.md)及[历史部署记录](../../../DEPLOYMENT.md)。

## 通知任务接口

固定通知接口为 `GET /shadow-bi/v1/notifications/status`、`POST /shadow-bi/v1/notifications/jobs` 和 `GET /shadow-bi/v1/notifications/jobs/<job_id>`。提交只接受 `operation`、`expected_release`、`as_of_date`，以及可选 `retry`；操作限定为 `preview` 或 `send-scheduled`，不接受命令、路径或收件人。正式发送还须满足上海10:00窗口、当天正式 release、截止日及 DeliveryState 门禁。接口合同与任务状态见[通知模块说明](../../../../monitoring_product/README.md)和[10月26日通知作业回执](../../../../docs/archive/notification-job-receipt-repair-20261026.md)；Dot 10:00 日程属于通知，不是 BI 更新调度。
