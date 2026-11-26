# 正式原生 BI 模块

正式产品为 Superset 原生 BI；`shadow_bi` 与 P3/P3.5/P4/P5 路径沿用既有服务及稳定导入。运行与发布以[部署说明](../DEPLOYMENT.md)、[完整日更说明](../../docs/archive/shadow-bi-full-daily-20261028.md)和[SQL 切换记录](../../docs/shadow-bi-sql-local-migration.md)为准，历史回执不用于推断实时版本或调度状态。

## 当前代码链路

日更入口为 `python -m ops run business`。现行调度以 `prepare_full_daily --publish --business-only` 转入同一业务链，发布正式 SQL release 后核验通知。费用通过 `ops ingest-cost` 独立录入，`ops fetch-cost-optional` 可生成隔离采集证据。

本地 SQL 基线由 `customers/shadow_bi_daily/Output/ShadowDaily/sql-current.json` 显式指定；服务器使用正式 `current`。通知沿用 DeliveryState、去重和 no-backfill 门禁，具体消费逻辑见 `monitoring_product/sql_release_notifications.py` 与 `shared_delivery`。

## 历史 raw 链路

10 月 26 日的 raw worker 曾运行到业务表计算，截止日期不匹配导致该批未发布。11 月 7 日已切换 SQL 日更，历史回执位于 `docs/archive/`。
