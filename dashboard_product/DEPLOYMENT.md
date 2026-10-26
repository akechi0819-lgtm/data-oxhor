> **状态依据：2026-10-26 日期回执；本轮未实读服务器或调度平台。** 正式产品为 Superset 原生 BI。已部署服务器 raw receiver、root 只读历史基线、受限双 Snapshot / quality / 共享计算 worker 和固定 publisher。10月26日真实 Dot 批次已在服务器实际完成双 Snapshot、两份 quality 查询并运行到39张表，最终因业务截止不匹配以 `failed/published=false` 结束，没有发布 raw release。Mac `p5.daily` 是仍存在的手动入口；日期回执记录它更新了 `daily-20261026_094052`（数据截至10-25），不代表长期默认路径。有效新 raw 包正式发布、持续日更和唯一生产者收口仍待分别验收。

# 正式 BI 部署与运行

正式用户界面为 Superset 原生看板。稳定代码路径保留 `dashboard_product.shadow_bi`，与已部署服务和导入路径一致。用户入口、账号及权限见[正式基线](../docs/bi-production-baseline-20261025.md)；本文件记录当前部署边界。

## 当前服务器能力

- Superset、`shadow-bi.service`、代码 `/srv/shadow-bi/code`、环境 `/srv/shadow-bi/venv` 和私有数据 `/var/lib/shadow-bi` 已部署；`current/library/business.duckdb` 为正式 BI 的业务库，PostgreSQL 保存 Superset 元数据。
- 服务器 raw 链路已部署：外部接收写入固定队列；受限 worker 读取 root 只读历史基线，在新副本内合并历史、建立双 Snapshot、运行 quality 和共享业务计算，生成39张封存业务表；root 固定 publisher 使用 P4 重建、校验和原子切版。
- **真实计算已在服务器运行。** `raw-20261026-dot-001` 三源/TAR hash 与输入一致，双 Snapshot、两份 quality 查询及39个 JSONL 文件/类型库完整性核验有回执。最终候选 `data_through=2026-10-24`，低于当日要求的 `2026-10-25`，在最终业务截止门禁失败，状态 `failed/published=false`；该批没有发布或切换 current。截止门禁先于物理库 COUNT 门禁，因此不能称为全门禁通过或正式发布。
- 固定 publisher 已独立部署并通过权限、负例及HTTP边界验证；worker 不能写生产 current/releases。publisher 只处理明确为 `prepared` 的同批候选，失败后保留开始时 current 并记录结果。10月26日失败候选未达到 `prepared`，没有调用它发布该批。
- 该日期的 BI current 记录为 `daily-20261026_094052`（数据截止10-25）；回执记录由 Mac `dashboard_product.shadow_bi.p5.daily` 手动更新。该模块仍存在，但本文件不把它定义为长期默认生产入口。当前实时 current 应在需要操作时按服务器 manifest 核验；本轮未实读。
- 服务器计算与发布能力已落地；尚待验收的是有效新 raw 包正式发布、持续日更安排及唯一生产者收口。来源完整性证明门禁已进入本地 `main`，10月26日部署的服务器版本不含该新门禁，不能据此声称服务器已启用。

详细服务权限、基线和批次证据见[raw接收部署回执](../docs/server-raw-receiver-deployment-20261026.md)、[固定publisher回执](../docs/server-raw-fixed-publisher-20261026.md)及[raw链路合同](../docs/server-raw-pipeline-contract.md)。

## Dot raw 接收、计算与发布边界

固定外部接口为 `POST /shadow-bi/v1/raw-batches` 与 `GET /shadow-bi/v1/raw-batches/<batch>`。只接收合同规定的三 Excel 包；请求不能指定服务器路径、命令、SQL、Snapshot ID 或发布参数。接收、入队、计算、prepare 和正式发布是不同状态；超时或HTTP错误后按同一批次ID查询状态，不盲目重传。

发布使用同批固定请求 `POST /shadow-bi/v1/raw-batches/<batch>/publish-prepared`，请求体只能是空对象 `{}`。只有 `prepared` 且来源任务、输入窗口、Snapshot 身份和质量已经核实后，才按明确授权触发；该请求不支持跳过门禁、指定路径或任意命令。状态以 GET 回执为准。received/queued 或计算达到39表都不等于 prepared，更不等于 published。

10月26日真实批次 `raw-20261026-dot-001` 的候选业务覆盖实际到10月24日，低于入口要求的10月25日。未改日期、未重算；候选和失败日志保留，既有 current 未被该批修改。新有效包到来后按`raw-20261026`部署代码对应的合同验收完整输入、双 Snapshot、quality、39表、业务身份、实际查询和页面；对本地新增的来源完成证明门禁也须先完成服务器部署验收，不能从旧回执推断它已生效。

服务器使用 `shadow_bi/p4/rebuild.py` 重建候选库，并由固定publisher在持锁状态下完成 manifest、页面/业务查询、失败恢复和切换。P4用于发布已验收批次；它不是把任意候选或失败批次提升为正式数据的绕行入口。历史切版演练不授权正常发布倒退截止日。

## 通知与自动化现状

服务器通知适配已部署：`monitoring_product.release_notifications` 从正式 BI release 构建同批通知包，`shared_delivery` 执行状态去重与传输；通知不独立查询或重算数仓。2026-10-26 人工触发有8条 `sent` 记录。HTTP job `9cbbb2…` 仍保留 `unknown/retryable=false`；独立只读对账回执将它关联到此前已发送的8条消息，`no_send_performed=true`，不表示该job自身成功发送。不得重发这些消息或清空 DeliveryState。详见[通知作业修复回执](../docs/notification-job-receipt-repair-20261026.md)。

记录中自2026-10-26起的 Dot 上海10:00日程用于通知触发，和 BI 采集/刷新分开管理；Grok 例行按用户要求停止。日期回执曾记录 Mac `bi-2` 为 ACTIVE/09:40，但本轮未读取调度平台实时状态，不据此推断当前任务启停。持续日更和唯一生产者切换须分别留下验收回执，不从代码合并、通知日程或单次计算推断完成。
