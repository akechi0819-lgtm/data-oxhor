# 看板发布 Agent

## 正式产品与服务器链路

正式 BI 产品为 Superset 原生看板，稳定代码路径为 `dashboard_product.shadow_bi`。服务器已部署 raw receiver、root 只读历史基线、受限 worker 和 root 固定 publisher；worker 已实际运行双 Snapshot、quality 与39张业务表的共同计算。2026-10-26真实批次因业务截止不匹配以 `failed/published=false` 结束，没有生成raw release。正式部署状态及操作边界见[部署说明](../../dashboard_product/DEPLOYMENT.md)和对应[接收回执](../../docs/server-raw-receiver-deployment-20261026.md)、[publisher回执](../../docs/server-raw-fixed-publisher-20261026.md)。

有效新 raw 包正式发布、持续日更及唯一生产者收口仍需分别验收。Mac `dashboard_product.shadow_bi.p5.daily` 仍是现存手动入口，10月26日有一次更新记录；按用户要求，这只作为已存在入口和有日期的生产事实，不作为长期默认操作路径。外部任务启停须实读调度平台，本地提交或回执摘要不能替代当前核验。

处理生产更新请求时，先按明确授权核对来源任务、原始输入、日期窗口和 raw 批次状态；区分 `received`、`prepared`、`failed` 与 `published`。只有同批状态为 `prepared` 且身份、Snapshot、quality 与业务截止已核验，才可按明确授权调用固定 publisher。`failed/published=false` 保留并如实报告，不通过改日期、重算或降低门禁发布。

本地 `main` 另加入受保护来源完成证明门禁，要求计算、候选复用和固定发布校验同一证明。10月26日服务器部署回执对应版本尚不含此项新门禁，不能把本地整合说成服务器已安装。合同见[raw链路](../../docs/server-raw-pipeline-contract.md)和[来源完整性](../../docs/server-source-completion-candidate.md)。

## 共享计算与通知

`management/calculation.py` 保留为共享业务计算，供 raw worker、本地已有生产逻辑及原生 BI 库构建复用。`online_team/build.py` 提供共享计算和受控查询 helpers；`dashboard_product/refresh.py` 提供来源映射、归属和历史对账 helpers。人员规则及花名册归 `workspace_modeling/operations/`。

正式通知入口为 `monitoring_product.server_notify`，由 `release_notifications` 从固定正式 release 构建通知包，再调用 `shared_delivery` 去重投递；通知不独立查询或重算数仓。10月26日有8条 `sent` 记录，关联HTTP job仍为 `unknown`，只读对账不等于该job自身发送成功；不得重复发送或清空 DeliveryState。详见[通知作业回执](../../docs/notification-job-receipt-repair-20261026.md)。

数据查询遵循已确认工作区、Snapshot、Pack、Bridge、来源和参考资料边界。不得读取或复制凭据，不将客户输入、整个工作区或运行产物加入Git。未来MCP权限不由BI上线自动授予。
