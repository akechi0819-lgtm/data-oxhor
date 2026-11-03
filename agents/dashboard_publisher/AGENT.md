> **当前 Mac 日更入口**：`data_acquisition.jobs.prepare_full_daily --publish` 按业务基础发布→立即通知→广告费用采集与发布执行；默认模式（含 `--prepare`）只生成隔离候选。11/3回执记录云端127个源文件SHA与本机一致，并记载次日 bi-3 由本机09:30采集；该日期回执不是当前实时调度核验。服务器 raw 接收/计算/发布 path 仍 inactive；10/26暂停与失败批次保留为历史。

# 看板发布 Agent

## Mac 日更总入口与服务器链路状态

正式 BI 产品为 Superset 原生看板，稳定代码路径为 `dashboard_product.shadow_bi`。Mac 日更使用 `prepare_full_daily --publish`：先发布业务基础看板，再立即经固定入口通知；仅在8条消息均确认后继续费用采集和 ROI 发布。业务、通知、费用阶段分别写入 `batch-dir/pipeline-result.json`，费用失败保留已成功的基础 current 和日报。未指定 `--publish` 时默认为隔离候选，`--prepare` 同样不发布或发送。

11/3完成回执记录正式代码目录与独立通知 current 的127个源文件 SHA 均与本机一致；本次代码同步验收未伴随业务数据发布或通知重发。回执记载 bi-3 次日仍由 Mac 本机09:30执行，但它是有日期的验收记录，不是实时调度状态查询。腾讯文档下载统一走官方 MCP，旧 Cookie 下载器已从两个现行代码目录退役。

费用采集不是仅靠人工上传：已配置来源由总入口采集并执行来源门禁。腾讯广告品牌非空数据可自动分页、对账与入仓，无需人工补品牌明细；这项自动流程不覆盖所有来源。腾讯语培费用源尚未接入，SEM 完成标记缺失及226条空金额仍如实缺失，不能补零或把缺口说成完整。

10/26清理回执记录服务器 raw 接收/计算/发布暂停；11/3完成回执仍记载该路径未启用。10/26 Dot raw 批次因业务截止不匹配以 `failed/published=false` 结束，没有生成 raw release。此前 `received`、`prepared`、`failed`、`published` 状态机和固定 raw publisher合同仅用于该服务器路径；不得据此恢复未启用路径。正式部署状态及历史操作边界见[部署说明](../../dashboard_product/DEPLOYMENT.md)、[接收回执](../../docs/server-raw-receiver-deployment-20261026.md)和[publisher回执](../../docs/server-raw-fixed-publisher-20261026.md)。

本地 `main` 另加入受保护来源完成证明门禁，要求计算、候选复用和固定发布校验同一证明。10月26日服务器部署回执对应版本尚不含此项新门禁，不能把本地整合说成服务器已安装。合同见[raw链路](../../docs/server-raw-pipeline-contract.md)和[来源完整性](../../docs/server-source-completion-candidate.md)。

## 共享计算与通知

`management/calculation.py` 保留为共享业务计算，供 raw worker、本地已有生产逻辑及原生 BI 库构建复用。`online_team/build.py` 提供共享计算和受控查询 helpers；`dashboard_product/refresh.py` 提供来源映射、归属和历史对账 helpers。人员规则及花名册归 `workspace_modeling/operations/`。

正式通知入口为 `monitoring_product.server_notify`，由 `release_notifications` 从固定正式 release 构建通知包，再调用 `shared_delivery` 去重投递；通知不独立查询或重算数仓。10月26日历史通知批次有8条 `sent` 记录，关联HTTP job仍为 `unknown`，只读对账不等于该job自身发送成功；不得据此重发或清空 DeliveryState。详见[通知作业回执](../../docs/notification-job-receipt-repair-20261026.md)。

数据查询遵循已确认工作区、Snapshot、Pack、Bridge、来源和参考资料边界。不得读取或复制凭据，不将客户输入、整个工作区或运行产物加入Git。未来MCP权限不由BI上线自动授予。
