# BI 服务器接收与发布代码说明

现行日更在 Mac 通过 `prepare_full_daily --publish --business-only` 构建 SQL 单仓并调用 P4 发布。正式部署和当前批次核验见[正式 BI 部署说明](../../../DEPLOYMENT.md)；留学经营口径见[集成指南](../../../../docs/integration-guide.md#22-隔离留学仓与腾讯更新现行)。本文件下方的旧 raw 和 Foundation 记录只用于理解历史实现。

## 历史：业务组筛选状态（2026-11-07）

正式 release `daily-sql-overview-group-20261107` 已激活。市场总览的业务组筛选为“市场总计／高中／大学／留学预备”；语培按所选业务组汇总线上、线下各渠道产出，留学及小语种固定显示总盘。11 张语培图联动该筛选，语培学校图已补入；其他页面的口径和样式保持不变。

原有 5,508 行指标与旧仓一致，新增 243 行分组指标与明细独立核算一致；40 项测试通过，2 项按条件跳过。费用为 4,041 行、43 个来源，标注截至 2026-11-06；复用同一批数据，不重采业务及费用源表、不触发日报推送。18 项正式指标与 MCP 5 项检查通过。bi-3 只读复查通过，采集、发布及通知回调均为 0；正式站 93 图、270 个业务分页已完成核对，字段、行数及记录集合全部一致；旧版已退役，服务器仅保留 1 份分析仓，投递状态逐字节不变。

证据：[activation.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/activation.json>)、[publication-receipt.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/publication-receipt.json>)；本批审计目录：[overview-group-20261107](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/>).

最终核验：88 张图逐行顺序相同；5 张图（231、320、331、332、333）仅同值并列行换位，93 张图完整记录集合相同。保留原排序规则；图 231 原网页分页现象未作次排序修复，完整 CSV 的 59 条唯一记录与旧版一致。线上曾触发旧 1400M 服务限额 OOM，已持久调至 4G，3 并发与后续全页复验通过；未改数据、线程数或查询内存配置。

最终回执：[completion.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/completion.json>)。

## 历史：云端基础仓日更（2026-11-04）

当时日更由 Mac 采集配对基础 Snapshot，服务器执行受控 SQL 和共享计算后发布 Superset。费用使用单批表格快照。验版成功后只保留当前版本。该流程为历史记录；现行发布与排查见[正式 BI 部署说明](../../../DEPLOYMENT.md)。

> **10月26日最新运行记录**：raw接收/计算/发布已暂停，保留Mac更新链路与既有成品/通知入口；服务器数仓和聚合代码能力仍保留。以[清理与暂停回执](../../../../docs/archive/server-cleanup-20261026.md)区分能力部署与当前启停。本轮未实读或修改服务器/日程，以下raw说明为代码/已部署能力合同，不是恢复运行指令。

本目录同时保留历史成品表发布、三 Excel raw 计算和通知队列相关服务文件。部署状态以[正式 BI 部署说明](../../../DEPLOYMENT.md)及相应日期回执为准。

## 历史：成品表接收与固定 P4 发布

`receiver.py` 实现内部 `POST /v1/batches` 与 `GET /v1/batches/<release>`，按 manifest 声明校验历史原生 BI 成品表归档并写入待发布队列；`publish-pending.sh` 再调用历史 P4 重建、校验并切换 release。当前 Mac `p5.daily` 进入 SQL 单仓构建与 P4 发布，见[正式 BI 部署说明](../../../DEPLOYMENT.md)。

`publish-pending.sh` 中 `write_receiver_state` 现将 `last_published`、`last_published_hash` 与 `last_failed` 原子写为 `root:shadowbi`、模式 `0640`。此前回收说明记录的 UMask 权限缺陷属于历史问题，当前源码已修复；本轮未实读服务器来确认已安装文件状态。

## 历史：三 Excel raw 计算与发布

历史服务器 raw 链路接收固定 BI 工单、BI 现金和腾讯 Excel 包：`POST /shadow-bi/v1/raw-batches` 接收入队，GET 同批状态；worker 基于 root 只读历史基线，在隔离副本更新双 Snapshot、运行 quality 和共享业务计算，封存39张业务表。只有同批状态为 `prepared` 才能请求 `POST /shadow-bi/v1/raw-batches/<batch>/publish-prepared`；该请求不接收命令或路径，root publisher 再按 P4 合同复核并切换 release。`raw_inputs.py`、`raw_receiver.py`、`raw_consumer.py`、`raw_compute.py` 和 `raw_publish.py` 分别实现组包、接收、消费、计算及固定发布。

10月26日部署回执记录服务器真实批次已完成双 Snapshot、quality 并计算到39表，随后因业务截止不匹配以 `failed/published=false` 结束；该批没有发布 release。当前 `main` 的来源完整性证明门禁尚未部署到该服务器版本，不得从本地源码推断门禁已生效。详见[raw 链路合同](../../../../docs/server-raw-pipeline-contract.md)、[接收部署回执](../../../../docs/archive/server-raw-receiver-deployment-20261026.md)、[固定发布回执](../../../../docs/archive/server-raw-fixed-publisher-20261026.md)和[部署说明](../../../DEPLOYMENT.md)。

## 历史：同批 Foundation 候选构建

`foundation_candidate.py` 是历史 Mac 日更调用的固定服务器构建入口，不启用 raw HTTP 接收或新增常驻服务。它只读取 `/var/lib/shadow-bi/foundation-inputs/<batch>/payload.tar`，逐项校验清单摘要、当前双 Snapshot、同批刷新回执和 quality，再在 `/var/lib/shadow-bi/releases/<release>/foundation` 保存本批可查询工作区，并在相邻 `library/` 通过共享 `dashboard_product.shadow_bi.library.build(..., server_complete=True)` 生成业务库。业务截止和留学来源截止必须都是请求日期的前一天；DuckDB 表计数和库身份通过后，释放再生 JSONL，只保留可查询的 DuckDB 与表元数据。`foundation/` 为 root 私有，`library/` 可由 `shadowbi` 读取。

入口只准备候选，不切换 `current`。Mac 在验收准备回执后调用现有 P4 `activate.py`；P5 原生看板验收通过后，再以 `foundation_candidate cleanup` 显式指定当前版和待清理版，移除前一版本及 `previous`。清理预检失败时旧版仍保留；旧目录原子移出正式命名后若文件删除失败，返回 `retired_cleanup_incomplete`，当前新版保持有效。代码同步与实际服务器安装状态以[正式 BI 部署说明](../../../DEPLOYMENT.md)及对应回执为准；本文件记录的是当前源码合同，不是服务器实时状态。

## 通知任务接口

固定通知接口为 `GET /shadow-bi/v1/notifications/status`、`POST /shadow-bi/v1/notifications/jobs` 和 `GET /shadow-bi/v1/notifications/jobs/<job_id>`。提交只接受 `operation`、`expected_release`、`as_of_date`，以及可选 `retry`；操作限定为 `preview` 或 `send-scheduled`，不接受命令、路径或收件人。正式发送还须满足上海10:00窗口、当天正式 release、截止日及 DeliveryState 门禁。接口合同与任务状态见[通知模块说明](../../../../monitoring_product/README.md)和[10月26日通知作业回执](../../../../docs/archive/notification-job-receipt-repair-20261026.md)；Dot 10:00 日程属于通知，不是 BI 更新调度。
