# 静态看板发布

> 主看板使用 `dashboard_actuals/v14`，所有账号进入 `full.html`；已验收的线上融合看板由 `online_team/` 生成自包含 `online_market_special.html`，留学线下仍输出 `offline_market_special.html`。本地源码更新不会自动更新远端页面。此次线上网页替换不改变钉钉运行链路；完整刷新及云端接入见 [上线说明](../docs/online-team-release.md)。

## 当前数据流

本地保存项目、客户工作区当前 Snapshot、Saved Query registry 和配置；服务器只保存 `full.html`、线上团队特供 HTML 与留学线下特供 HTML。刷新、计算和 Snapshot 更新全部在本地完成，再通过 SCP 上传：

刷新/发布前，需将 `sql/dashboard_actuals.sql` 注册为 `dashboard_actuals/v14`，确保客户工作区 `Work/SavedQueries/` 的 SQL 与本地查询合同一致。

1. `refresh` 通过 Data Platform 运行两次 `dashboard_actuals/v14`（当前与去年同期），生成一份全量 `artifact.json`。
2. `render` 只生成 `full.html`，包含全部团队、市场总计和人员产能。
3. 发布脚本验证主看板回执后，使用同一显式 Snapshot 生成新版线上页，嵌入其 CSS/JS/展示数据。两份本地产物都成功后，再上传 `full.html` 与 `online_market_special.html`，校验线上页哈希并逐文件原子替换。
4. Nginx 使用 basic auth；所有已认证用户的 `/`、`/full.html`、`online_market_special.html` 和 `offline_market_special.html` 都进入完整主页面/特供页。

新版线上团队融合看板直接读取主 Snapshot，按已确认规则归类和重洗留学渠道，不需要影子 Snapshot。正式文件仍是 `online_market_special.html`，不依赖旧语培 iframe 页面；主页面入口文字更新为“进入线上团队融合看板”。

**不要**把 `artifact.json` 放到 `/var/www/dashboard/` 或任何公网目录。服务器不接触 DuckDB、`Input/`、`Work/Runs/`、客户凭据或整个 `customers/` 目录。

钉钉人员进度仍把 `people.png` 和 `details.xlsx` 放到 `/var/www/dashboard/notify/<token>/<team_id>/`；这是监控资产，不是看板分册。日更脚本不自动群发。

## 本地发布

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/bi_operations --run-id run_dashboard_<id>
python3 -m dashboard_product.refresh render --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json
python3 -m dashboard_product.refresh validate-publish-artifact --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json
./dashboard_product/deploy/publish_static_dashboard.sh
```

已有 artifact 可跳过 refresh，但仍必须包含 V14 实际查询回执：

```bash
ARTIFACT_JSON=/abs/path/artifact.json ./dashboard_product/deploy/publish_static_dashboard.sh
```

校验会检查两次 `dashboard_actuals/v14` 受控查询、输出列和查询回执；旧 artifact 直接阻断。

## 线上团队融合看板单独发布

```bash
SITE_HTML=/abs/path/online_market_special.html \
  ./dashboard_product/deploy/publish_online_market_dashboard.sh
```

先按上线说明运行 `online_team.build` 和 `online_team.export`。该脚本只上传自包含线上 HTML；`--dry-run` 只校验不上传、不读凭据。现行日更通过 `publish_static_dashboard.sh` 已包含新版线上页，不再重复调用旧影子网页发布。共享结果、明细和查询回执留在 Output，不能上传。

## 留学线下团队影子看板

```bash
ARTIFACT_JSON=/abs/path/offline_market_artifact.json \
FULL_HTML=/abs/path/full.html \
  ./dashboard_product/deploy/publish_offline_market_dashboard.sh
```

该脚本只上传 `full.html` 和 `offline_market_special.html`，不上传影子 warehouse、工单文件或 artifact。主页面「线下市场」页只加入口链接，不改语培线下计算。

## 鉴权

密码本仍为 C 层文件 `dashboard_product/deploy/secrets/password-book-20260907.xlsx`，凭据不进 Git。生成 htpasswd：

```bash
python3 dashboard_product/deploy/generate_dashboard_auth.py --force
./dashboard_product/deploy/install_dashboard_auth.sh
```

权限字段只保留为密码本输入元数据，生成结果统一按 `all` 处理；不再生成用户→分册映射。

服务器只需 Nginx、htpasswd 文件和 SSH；不执行刷新、计算或 Snapshot 更新。`/healthz` 匿名 200，业务页面需登录。当前访问地址为 `http://dashboard.apinova.cn`；若未上 TLS，HTTP basic auth 仅适合内部试用。

## 历史

过去的团队分册、旧查询版本和发布验收仅在 [历史目录](../docs/history/dashboard/) 留痕，不是当前操作入口。
