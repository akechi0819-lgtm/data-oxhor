> 历史说明，仅供追溯；当前入口见[正式部署](../../../dashboard_product/DEPLOYMENT.md)。

# 管理融合看板部署

## 当前状态

2026-10-12用户随后授权语培工单留学边界修正版上线。`run_management_scope_fix_20261012`沿用本机11:38双仓与截至10月11日的数据，18文件已正式激活；公网实读全年8,482、暂无法拆分50，全部/线上/线下范围为50/13/37。manifest SHA-256 `13333f3135938ec052984fd3edc0ad5201c9406245b142678a1068ec7bd61d71`。本次未重发钉钉，Grok五源码已安装，摘要一致、9项云端测试通过，日更脚本和实际import路径加载新版。证据见[工单边界修复与发布](../../dashboard-order-boundary-audit-20261012.md)。

2026-10-12用户授权从本机运行完整链路，双仓来源 `run_daily_sources_local_20261012_1138` 及当天门禁passed，管理批次 `run_management_local_20261012_1138` 的18文件已staged→activated，公网数据截至10月11日。原8条／5通道通知全部sent；线上全部／线上／线下范围已与同批数据逐项核验。Grok运行环境没有由此改动或恢复，现网最新发布来自本机。本轮回执与缓存验收见[本机正式运行](../../local-production-run-20261012.md)。

2026-10-03原管理服务已正式激活；2026-10-09腾讯源最新批次 `run_grok_tencent_view_final_20261009` 仅完成构建、8条空跑及18文件组包，未在本次执行激活或真发。最近回传的生产batch仍为 `run_management_20261009_111619`，回执未提供实时公网current链接，版本状态需实际activation与站点验证。

09:30数仓生产者并列抓取BI与腾讯，09:45看板、10:24投递只消费联合验证成功的两仓／同批结果。三条为原节奏，当前启停以平台实读为准。数仓入口见[腾讯来源与双仓日更](../../tencent-docs-study-source.md)；消费者强制校验当天 `Work/DailyWarehouseRefresh/current.json`。任一源失败或刷新中不会生成新的生产batch、发布或发送；上一正式网页保留。`run_management_daily.sh`本身不抓来源，门禁通过后会发布并激活，手工验证不要直接运行它。平台接入以更新及运行回执验收。

09:45例行若已启用，配置的入口为 `dashboard_product/deploy/run_management_daily.sh`。环境变量指向已有 warehouse Python、dashboard 根目录、whcustomer 工作区和原 C 层凭据文件；Nginx 配置路径使用已核实的 `/etc/nginx/sites-available/dashboard`：

```bash
PYTHON="/path/to/warehouse-venv/bin/python" \
PROJECT_ROOT="/path/to/dashroot" \
WORKSPACE="/path/to/whcustomer" \
ENV_FILE="/path/to/existing-C-env-file" \
REMOTE_NGINX_CONF=/etc/nginx/sites-available/dashboard \
bash /path/to/dashroot/dashboard_product/deploy/run_management_daily.sh
```

脚本以显式当前 Snapshot 和运行编号调用 `dashboard_product.management.build`，再对同一 `shared_result.json` 执行 delivery dry-run、生成批次指针、组包、staging 并调用激活脚本。P5已在2026-10-03完成真实激活和页面检查；回执见[施工计划第32节](../../dashboard-static-rebuild-plan.md)。

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

当前源码投递合同覆盖原 5 个钉钉通道（`offline_youth`、`offline_high_school`、`offline_university`、`online_private`、`online_platform`）和 8 条消息。2026-10-08新增高中留学个人简报；高中、大学与线上平台各有两条消息共用各自原群。高中留学只展示该组留学人员的个人完成、渠道构成与个人流水，不生成部门完成。该变更需与监控投递校验同批同步，旧七条消息批次不用于新合同投递。本部署说明不启停投递例行；实际状态以平台为准。

## 静态发布与激活

`dashboard_product.management.publication` 只组装 manifest 标明的 18 个公开文件，不打包 `shared_result.json`、通知内容、明细或查询回执。`publish_management_dashboard.sh` 将 release 暂存到 `releases/<run_id>`；`activate_management_dashboard.sh` 校验 manifest 和 Nginx 配置，通过 `nginx -t` 后切换 `/var/www/dashboard/current`，并保存激活回执。新配置沿用 `dashboard.apinova.cn`、现有认证与 `/healthz`，通知资产继续从原 `/var/www/dashboard/notify/` 读取。

服务器配置路径必须显式传入 `REMOTE_NGINX_CONF`。旧三页已移出webroot留历史，当前链接指向已校验的release。每次staging成功后仍须取得activated回执，不能把staged状态当作live。

服务入口与用户地址仍由现有 Nginx vhost 提供。C 层 SSH、Webhook 凭据不进入 Git、release 或公网目录。
