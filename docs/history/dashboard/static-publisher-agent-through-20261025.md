> 历史说明，仅供追溯；当前入口见[正式部署](../../../dashboard_product/DEPLOYMENT.md)。

# 看板发布 Agent

## 负责范围

使用 `dashboard_product.management.build` 按显式 Snapshot 和 run_id 生成同批共同结果与四页展示数据。示例中的 shell 变量来自当前 routine 环境；`CURRENT_SNAPSHOT_ID` 必须等于工作区 `Work/workspace.json` 当前指针。网页与八条推送必须消费这一份 `shared_result.json`，不重写 SQL、业务归属或版式。高中留学个人简报与原高中语培简报共用高中通道；人员迁移、个人渠道及八条消息门禁须同步同批源码。

```bash
python -m dashboard_product.management.build \
  --workspace "$WORKSPACE" --snapshot-id "$CURRENT_SNAPSHOT_ID" \
  --study-abroad-snapshot-id "$CURRENT_STUDY_ABROAD_SNAPSHOT_ID" \
  --run-id "$RUN_ID" --as-of-date "$AS_OF_DATE"
```

只读检查同批投递预览：

```bash
BATCH_DIR="$WORKSPACE/Output/DashboardManagement/$RUN_ID"
SHARED_RESULT="$BATCH_DIR/shared_result.json"
python -m monitoring_product.shared_delivery \
  --shared-result "$SHARED_RESULT" \
  --output-dir "$BATCH_DIR/delivery_preview" \
  --as-of-date "$AS_OF_DATE" \
  --state-dir "$WORKSPACE/Work/DeliveryState" --dry-run
```

`management.build` 使用 Data Platform 受控查询并写入 `Output/DashboardManagement/<run_id>/`。`dashboard_product.refresh.py` 中被导入的代码只作内部 source helper；它不是受支持的命令行入口。

## 日常入口与门禁

- 原09:45看板例行调用核心 `dashboard_product/deploy/run_management_daily.sh`，不是不存在的根目录wrapper。数仓09:30先通过每日双仓来源入口抓取BI／腾讯；看板本身不重复抓取。
- 看板先核验当天联合回执、两仓身份和共同结果，任一来源失败或仍刷新即停止，不写新生产batch、不发布。门禁通过后才构建、空跑、组包和尝试激活；预览不等于已上线。
- 10:24投递例行只消费对应共同批次，正式调用 `monitoring_product/deploy/deliver_management_batch.sh`，使用原C层凭据，并核验同一双仓配对。
- 2026-10-09平台基线实读三条原任务均启用，09:30／09:45／10:24（Asia/Shanghai）；旧10月3日暂停记录不能覆写现状。任务正文只按本次授权修改，不新建重复任务、不变时刻／启停。原P3/P4/P5属于此前服务上线，具体新批次是否已激活须查相应回执。

发布只组包 manifest 内 18 个静态资源；不上传 `shared_result.json`、通知、明细、查询回执或工作区数据。激活使用显式 `REMOTE_NGINX_CONF=/etc/nginx/sites-available/dashboard`，沿用当前 vhost、认证、healthz 和 `/notify/` 访问边界。旧线上文件未在此步骤删除。

人员进度和钉钉投递由[日常监控 Agent](../../archive/agents/daily_monitor/AGENT.md)负责，不属于页面计算。

## 必须遵守

- 只使用明确的当前 Snapshot 和唯一 run_id。
- 业务口径变更先完成证据核对和人工确认；不重做已验收的本地业务或版式验收。
- 页面和消息必须来自同一批共同结果；禁止恢复独立线上/线下构建、旧通知查询或三份旧发布入口。
- 不上传源文件、数仓、私有共同结果、通知细节、查询证据或密钥。
- 只有真实激活与页面检查回执确认后，才能报告 P5 完成。

部署说明见[看板部署文档](../../../dashboard_product/DEPLOYMENT.md)，批次与指标细节见[管理融合看板说明](../../../dashboard_product/management/README.md)。
