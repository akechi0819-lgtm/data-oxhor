# 静态看板发布

> 下一版主看板采用 V14：使用 `dashboard_actuals/v14`，所有账号进入同一份 `full.html`；线上影子看板单独输出 `online_market_special.html`，留学线下影子看板单独输出 `offline_market_special.html`。本地源码更新不会自动更新客户 Saved Query registry 或线上页面。人员进度和钉钉推送由 `monitoring_product/` 负责。

## 当前数据流

本地保存项目、客户工作区当前 Snapshot、Saved Query registry 和配置；服务器只保存 `full.html`、线上团队特供 HTML 与留学线下特供 HTML。刷新、计算和 Snapshot 更新全部在本地完成，再通过 SCP 上传：

刷新/发布前，需将 `sql/dashboard_actuals.sql` 注册为 `dashboard_actuals/v14`，确保客户工作区 `Work/SavedQueries/` 的 SQL 与本地查询合同一致。

1. `refresh` 通过 Data Platform 运行两次 `dashboard_actuals/v14`（当前与去年同期），生成一份全量 `artifact.json`。
2. `render` 只生成 `full.html`，包含全部团队、市场总计和人员产能。
3. 发布脚本先验证两份查询回执、查询列和 V14 版本，再把 `full.html` 原子替换到服务器，并删除已退役的团队分册。
4. Nginx 使用 basic auth；所有已认证用户的 `/`、`/full.html`、`online_market_special.html` 和 `offline_market_special.html` 都进入完整主页面/特供页。

线上团队特供看板读取显式影子 Snapshot，输出 `online_market_special.html`。它不依赖已退役的 `online_private.html`、`online_platform.html` 或 `offline_market.html`。

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

## 线上团队影子看板

```bash
ARTIFACT_JSON=/abs/path/online_market_artifact.json \
FULL_HTML=/abs/path/full.html \
  ./dashboard_product/deploy/publish_online_market_dashboard.sh
```

该脚本只上传 `full.html` 和 `online_market_special.html`，不上传影子 warehouse、工单文件或 artifact，并清理旧团队 HTML。

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
