> 2026-10-25最新边界：Grok全部例行保持停止，不按下方历史时间表恢复。新接管入口为monitoring_product.release_notifications，默认离线预览，必须验证正式release及原DeliveryState迁移后才允许发送。当前仅本地离线交验，未部署/授权新凭据权限，详见[交验](../../docs/bi-notification-adapter-20261025.md)。下方shared_result入口用于兼容和历史复核，不作为新调度入口。

# 日常监控 Agent

## 职责与入口

只从当天管理批次的 `shared_result.json` 投递已计算好的八条消息，不独立取数或重算指标。八条消息投递到原 5 个钉钉通道：`offline_youth`、`offline_high_school`、`offline_university`、`online_private`、`online_platform`；高中、大学和线上平台各两条消息共用各自原群。高中留学为个人简报，消费 `high.abroad` 的个人完成、渠道及个人流水，不把个人贡献改写成部门完成。

只读预览使用当前批次的 `WORKSPACE`、`RUN_ID` 和通知 `AS_OF_DATE`：

```bash
python -m monitoring_product.shared_delivery \
  --shared-result "$WORKSPACE/Output/DashboardManagement/$RUN_ID/shared_result.json" \
  --output-dir "$WORKSPACE/Output/DashboardManagement/$RUN_ID/delivery_preview" \
  --as-of-date "$AS_OF_DATE" \
  --state-dir "$WORKSPACE/Work/DeliveryState" \
  --dashboard-base-url http://dashboard.apinova.cn --dry-run
```

正式批次入口读取 `Work/ManagementDelivery/batch.json`，校验 run_id、Snapshot、截止日与通知身份后投递：

```bash
PYTHON="/path/to/warehouse-venv/bin/python" \
PROJECT_ROOT="/path/to/dashroot" WORKSPACE="/path/to/whcustomer" ENV_FILE="/path/to/existing-C-env-file" \
bash /path/to/dashroot/monitoring_product/deploy/deliver_management_batch.sh
```

正式投递要求新 Snapshot、`data_through` 为昨天、完整五通道配置及显式 C 层 env-file。成功消息按日期/通道/message_id 去重；结果未知的消息阻断重发并记录回执。2026-10-09平台实读日推例行已启用，保留原10:24时刻／开关；不能用旧暂停描述改变现状。只有当天双仓来源成功配对、生产批次与配对一致时才允许投递，不在本例行抓取或重建。

Grok 09:30来源日常并列更新BI与腾讯，09:45看板日常在联合门禁通过后构建并发布，10:24投递读取同批结果；三条原任务的时刻、群与凭据不变。平台例行succeeded不等于业务成功，须核对脚本退出值、共同回执和发送回执；缺配对或不新鲜则停止，不补发旧批次。

## 权限与边界

- 只读 `shared_result.json` 及其同批 `notifications_ref`；核对引用哈希、run_id、Snapshot、截止日和八条／五通道合同。
- dry-run 不读取凭据、不上传、不发送；正式投递只从显式 C 层 env-file 读取授权通道。
- 只写批次预览、投递状态与本次回执。仅上传本次消息需要的 PNG/XLSX，不上传业务数据、共享结果、明细 JSON 或查询证据。
- 业务窗口、目标、实际、人头、落后与日均值由管理共同计算层确定；不得修改结果或恢复已退役的独立通知查询链。
- 人员规则和花名册只从 `workspace_modeling/operations/` 读取，不擅自维护副本。

运行细节见[监控模块说明](../../monitoring_product/README.md)。
