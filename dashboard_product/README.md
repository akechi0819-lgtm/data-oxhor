# 正式原生 BI 看板

Superset 原生看板使用同批 SQL release。部署、身份和运行状态见[部署说明](DEPLOYMENT.md)。

## 代码职责

- `shadow_bi/sql_warehouse/` 构建经营事实、汇总、看板数据集和通知预览。
- `shadow_bi/p4/` 执行 SQL release 激活与验证；`shadow_bi/p5/sql_daily.py` 对接本机日更。
- `monitoring_product/sql_release_notifications.py` 读取同批封存通知，`shared_delivery` 负责已授权投递和去重。
- `workspace_modeling/operations/` 提供共用人员规则。历史发布回执见 `docs/archive/`。
