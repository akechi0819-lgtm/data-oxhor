# 日常监控 Agent

## 职责与入口

只从当天管理批次的 `shared_result.json` 投递已计算好的七条消息，不独立取数或重算指标。七条消息投递到原 5 个钉钉通道：`offline_youth`、`offline_high_school`、`offline_university`、`online_private`、`online_platform`；大学和线上平台各两条消息共用各自原群。

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

正式投递要求新 Snapshot、`data_through` 为昨天、完整五通道配置及显式 C 层 env-file。成功消息按日期/通道/message_id 去重；结果未知的消息阻断重发并记录回执。10:24 钉钉 routine 当前暂停，保持暂停；不得因为 9:45 管理 routine 已启用而恢复它。

Grok 09:45 routine 调用 `dashboard_product/deploy/run_management_daily.sh`，构建共同结果并生成同批预览和 batch 指针；该Routine已启用，页面P3/P4/P5均已完成并上线。10:24钉钉Routine仍暂停；预览不代表正式投递。实际上线回执见[施工计划第32节](../../docs/dashboard-static-rebuild-plan.md)。

## 权限与边界

- 只读 `shared_result.json` 及其同批 `notifications_ref`；核对引用哈希、run_id、Snapshot、截止日和七消息合同。
- dry-run 不读取凭据、不上传、不发送；正式投递只从显式 C 层 env-file 读取授权通道。
- 只写批次预览、投递状态与本次回执。仅上传本次消息需要的 PNG/XLSX，不上传业务数据、共享结果、明细 JSON 或查询证据。
- 业务窗口、目标、实际、人头、落后与日均值由管理共同计算层确定；不得修改结果或恢复已退役的独立通知查询链。
- 人员规则和花名册只从 `workspace_modeling/operations/` 读取，不擅自维护副本。

运行细节见[监控模块说明](../../monitoring_product/README.md)。
