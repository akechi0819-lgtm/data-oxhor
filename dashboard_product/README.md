# 正式原生 BI 看板

正式用户界面为 Superset 原生看板，见[正式入口](https://dashboard.apinova.cn/superset/dashboard/shadow-bi-native/?standalone=1)。沿用原18个账号和已授权只读范围；用户身份及权限边界见[正式基线](../docs/bi-production-baseline-20261025.md)。

## 当前生产能力

- 服务器 raw receiver、root 只读历史基线、受限双 Snapshot / quality / 共享计算 worker 和 root 固定 publisher 已部署。
- raw worker 在服务器执行历史合并、双仓 Snapshot、质量查询及共同聚合计算，生成39张封存业务表。10月26日真实批次实际运行到39表，但最终因 `data_through` 业务截止不匹配以 `failed/published=false` 结束；该批没有发布新 release。
- root 固定 publisher 已独立部署。只有通过来源、Snapshot、quality、39表及正式身份校验并进入 `prepared` 的候选，才能按明确授权进入 P4 和 release 切换。
- 服务器数仓与聚合计算能力已落地。有效新 raw 包正式发布、持续日更安排及唯一生产者收口尚待各自验收；本轮未实读服务器或调度平台。
- 日期回执记录 Superset current `daily-20261026_094052`（数据截止10-25）由 Mac `shadow_bi.p5.daily` 手动入口更新。该入口仍存在并有该次生产记录，不作为长期推荐默认路径。

## 代码职责

- 共享业务计算：`management/calculation.py`，供本地日更、服务器 raw worker 和原生 BI 数据库构建复用。
- Superset 数据库与投影：`shadow_bi/library.py`、`shadow_bi/p3/`、`shadow_bi/p35/`。
- 服务器构建与验证：`shadow_bi/p4/`；raw 接收、受限计算和固定发布：`shadow_bi/p5/raw_*.py` 与 `shadow_bi/p5/deploy/`。
- `online_team/build.py` 保留为共享计算、查询 helper；`dashboard_product/refresh.py` 保留来源映射、归属及历史对账 helpers。它们是实现模块，不是静态页面运行入口。
- 通知使用正式 release 和 `monitoring_product.release_notifications`，由 `shared_delivery` 去重投递；通知本身不独立查询或计算数仓。

10月26日服务器部署、39表计算结果、截止门禁及当前待验收项见[部署与运行说明](DEPLOYMENT.md)、[raw接收回执](../docs/server-raw-receiver-deployment-20261026.md)和[固定publisher回执](../docs/server-raw-fixed-publisher-20261026.md)。本地新增来源完整性门禁尚未部署到服务器，见[来源完整性合同](../docs/server-source-completion-candidate.md)。
