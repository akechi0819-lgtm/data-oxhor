# 管理融合看板部署

## 当前状态

Grok 云电脑上的 9:45 routine 已启用，10:24 钉钉投递 routine 保持暂停。P3、P4、P5已完成：2026-10-03正式激活 `run_grok_release_20261003`，18文件哈希与独立HTTP检查通过，旧页面退出。初始Snapshot为 `snapshot_bi_operations_20261002`、数据截至2026-10-01；后续09:45在当天数仓就绪后日更。10:24投递仍暂停。

9:45 routine 运行 `dashboard_product/deploy/run_management_daily.sh`。环境变量指向已有 warehouse Python、dashboard 根目录、whcustomer 工作区和原 C 层凭据文件；Nginx 配置路径使用已核实的 `/etc/nginx/sites-available/dashboard`：

```bash
PYTHON="/path/to/warehouse-venv/bin/python" \
PROJECT_ROOT="/path/to/dashroot" \
WORKSPACE="/path/to/whcustomer" \
ENV_FILE="/path/to/existing-C-env-file" \
REMOTE_NGINX_CONF=/etc/nginx/sites-available/dashboard \
bash /path/to/dashroot/dashboard_product/deploy/run_management_daily.sh
```

脚本以显式当前 Snapshot 和运行编号调用 `dashboard_product.management.build`，再对同一 `shared_result.json` 执行 delivery dry-run、生成批次指针、组包、staging 并调用激活脚本。P5已在2026-10-03完成真实激活和页面检查；回执见[施工计划第32节](../docs/dashboard-static-rebuild-plan.md)。

## 同批结果和投递

`management.build` 在 `Output/DashboardManagement/<run_id>/` 生成共同结果、四页展示资源及私有通知引用。页面只由共同结果投影；`monitoring_product.shared_delivery` 只消费同批通知，不独立查询业务数据。

同批只读预览：

```bash
BATCH_DIR="$WORKSPACE/Output/DashboardManagement/$RUN_ID"
SHARED_RESULT="$BATCH_DIR/shared_result.json"
python -m monitoring_product.shared_delivery \
  --shared-result "$SHARED_RESULT" \
  --output-dir "$BATCH_DIR/delivery_preview" \
  --as-of-date "$AS_OF_DATE" \
  --state-dir "$WORKSPACE/Work/DeliveryState" \
  --dashboard-base-url http://dashboard.apinova.cn --dry-run
```

经授权的批次投递使用显式 batch 指针与原 C 层凭据：

```bash
PYTHON="/path/to/warehouse-venv/bin/python" \
PROJECT_ROOT="/path/to/dashroot" WORKSPACE="/path/to/whcustomer" ENV_FILE="/path/to/existing-C-env-file" \
bash /path/to/dashroot/monitoring_product/deploy/deliver_management_batch.sh
```

当前源码投递合同覆盖原 5 个钉钉通道（`offline_youth`、`offline_high_school`、`offline_university`、`online_private`、`online_platform`）和 8 条消息。2026-10-08新增高中留学个人简报；高中、大学与线上平台各有两条消息共用各自原群。高中留学只展示该组留学人员的个人完成、渠道构成与个人流水，不生成部门完成。该变更需与监控投递校验同批同步，旧七条消息批次不用于新合同投递。10:24 routine 仍暂停，不在部署中恢复它。

## 静态发布与激活

`dashboard_product.management.publication` 只组装 manifest 标明的 18 个公开文件，不打包 `shared_result.json`、通知内容、明细或查询回执。`publish_management_dashboard.sh` 将 release 暂存到 `releases/<run_id>`；`activate_management_dashboard.sh` 校验 manifest 和 Nginx 配置，通过 `nginx -t` 后切换 `/var/www/dashboard/current`，并保存激活回执。新配置沿用 `dashboard.apinova.cn`、现有认证与 `/healthz`，通知资产继续从原 `/var/www/dashboard/notify/` 读取。

服务器配置路径必须显式传入 `REMOTE_NGINX_CONF`。旧三页已移出webroot留历史，当前链接指向已校验的release。每次staging成功后仍须取得activated回执，不能把staged状态当作live。

服务入口与用户地址仍由现有 Nginx vhost 提供。C 层 SSH、Webhook 凭据不进入 Git、release 或公网目录。
