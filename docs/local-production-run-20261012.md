# 本机双仓更新、看板发布与推送（2026-10-12）

## 授权与完成状态

用户因Grok云电脑问题，明确要求从本机执行一版数仓双仓更新、看板刷新和推送。沿用现有工作区、业务口径、源连接、静态发布和8条／5通道投递入口；没有新增自动化或改变Grok例行。

完整链路已完成：两仓成功、当天配对检查passed，管理看板18文件正式激活，八条钉钉消息全部sent，无失败或结果未知。网站与通知展示截止日均为2026-10-11；两仓Snapshot按2026-10-12捕获，不能将捕获日写成展示截止日。

| 阶段 | 明确身份与结果 |
|---|---|
| 来源批次 | `run_daily_sources_local_20261012_1138`；两源success、整体passed |
| BI Snapshot | `snapshot_bi_operations_20261012_local_1138` |
| 留学 Snapshot | `snapshot_study_abroad_20261012_local_1138`；只替换10月，保留标准历史 |
| 管理共同批次 | `run_management_local_20261012_1138`；44455事实、17期间、5005活动 |
| 公开发布 | 18文件，staged→activated，数据截至10月11日 |
| manifest SHA-256 | `35490026f157adf98e460685ac1f59f668c8431eea40cfd6a06fd0c6ec05d273` |
| 正式通知 | `prep.training`、`high.training`、`high.abroad`、`university.training`、`university.abroad`、`virtual.mixed`、`online.training`、`online.abroad` 全部sent |

## 执行与验收

执行顺序为现有 `data_acquisition/deploy/run_daily_warehouses.sh` → 当天 `daily_warehouses check` → `dashboard_product/deploy/run_management_daily.sh` → `monitoring_product/deploy/deliver_management_batch.sh`。看板日常入口先同批构建、八条dry-run、组包再激活；投递入口只消费明确 `Work/ManagementDelivery/batch.json`，不另查仓或重算。

原C层配置和五通道已核对齐全，只输出配置项存在性，不显示凭据。首次受限环境中BI Chrome启动即关闭，SSH出现Permission denied；现有运行说明要求在获准的执行环境外复核，实测原Chrome可以启动、原SSH凭据连接成功，未改密码、网络设置或检查逻辑。新批次独立重试成功，首次 `run_daily_sources_local_20261012_1133` failed回执保留，腾讯已成功的独立Snapshot未回滚。BI导出初始HTTP 500后均进入file_ready，等待终态后导入。

正式发送前，同批身份、引用哈希、新鲜度及8条／5通道合同验证通过。工单35409870的10,800元、35367348的8,400元在大学语培个人附件里均为翟昕羽权重1；大学附件包含15笔“未分配签约”核对行。原始业务资格、人员名单与目标没有另改。

公网验收确认数据截至10月11日、全部／线上／线下三个团队范围可用；各业务组工单、现金、目标、人头逐项与同一发布批次JSON匹配，留学对应两表范围同步。Chrome旧脚本缓存曾隐藏新筛选器，临时禁用该页缓存重载后验证通过，已恢复缓存和调试设置。用户若仍看到旧界面，可在Mac Chrome按⌘⇧R强制刷新一次。公开包不含私有事实、通知结果、查询证据、工作簿或密钥。

## 回执位置

- 综合验收：`.local/audits/local-production-20261012/completion.json`。
- 浏览器对账：`.local/audits/local-production-20261012/browser-verification.json`；截图 `live-overview.jpg`。
- 来源回执：`customers/bi_operations/Work/DailyWarehouseRefresh/Runs/run_daily_sources_local_20261012_1138/receipt.json`。
- 同批结果：`customers/bi_operations/Output/DashboardManagement/run_management_local_20261012_1138/shared_result.json`。
- 激活回执：`customers/bi_operations/Output/DashboardRelease/activation-receipt-run_management_local_20261012_1138.json`。
- 正式投递资产：该管理批次 `delivery/`；逐条持久发送状态：`customers/bi_operations/Work/DeliveryState/shared_delivery_state.json`。

本次只执行一次本机链路，未设置本机每日任务，也未改Grok例行、云端数据指针或收件人。Grok恢复后处理本日批次时，须先对照本机已发八条记录，不能再补发同日同消息；本机成功不能代替云端工作区状态证明。客户原件、DuckDB、Parquet、整份工作区和C层凭据未上传，发布仅现有静态清单，通知仅本次所需PNG／XLSX。
