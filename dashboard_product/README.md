# 固定看板

`dashboard_product/` 负责已确认口径的固定查询、看板 artifact、四分册 HTML 与静态发布。人员绩效监控和钉钉日报已迁至 [monitoring_product](../monitoring_product/README.md)，不再由看板入口计算或发送。

## 运行

```bash
python3 -m dashboard_product.refresh refresh --workspace <workspace> --run-id <run_id>
python3 -m dashboard_product.refresh render --artifact <artifact.json> --all-booklets
```

刷新消费 `dashboard_actuals/v10`，通过 Data Platform 受控查询读取当前 Snapshot。市场总计保留全部有效事实；项目、团队、渠道、顾问和人员仅使用严格归属。无法映射业务组的事实标记为“业务组暂无法拆分”；工单 ID 为空或无法精确匹配的现金在渠道与顾问下标记为“渠道/顾问暂无法拆分”，两者都不强行分配给团队或个人。生成 `full.html`、`online_private.html`、`online_platform.html`、`offline_market.html`；公网仅托管分册 HTML，不上传全量 artifact。定时仍由外部宿主调用 `deploy/publish_static_dashboard.sh`。

## 配置与边界

- `config/project_targets.json`：团队与业务组目标。
- `config/capacity_targets.json`：人员标准产能。
- `config/saved_queries.json`：固定查询合同。
- `workspace_modeling/operations/people.json`：与监控共用的人员组织和目标。
- `workspace_modeling/operations/personnel.py`：与监控共用的绩效月及人员匹配规则。

看板页签、同比拆分、人员归属和当前业务限制见 [当前状态](docs/CURRENT_STATUS.md)；发布权限与静态服务器见 [部署说明](DEPLOYMENT.md)。看板发布不授予监控发送权限，监控也不修改或发布看板。

## 验证

```bash
python3 -m unittest discover -s dashboard_product/tests -v
```

部署迁移须同时同步共享业务目录和新的 `refresh.py`；监控的 SQL、发送命令、凭据输入及云端任务切换见 [监控运行合同](../monitoring_product/README.md)。
