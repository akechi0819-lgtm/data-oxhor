# 正式原生 BI 模块

正式产品为 Superset 原生 BI；`shadow_bi` 与 P3/P3.5/P4/P5 路径沿用既有服务及稳定导入。运行与发布以[部署说明](../DEPLOYMENT.md)、[完整日更说明](../../docs/shadow-bi-full-daily-20261028.md)和[SQL 切换记录](../../docs/shadow-bi-sql-local-migration.md)为准，历史回执不用于推断实时版本或调度状态。

## 当前代码链路

Mac 总入口 `data_acquisition.jobs.prepare_full_daily --publish` 按业务发布→立即通知→广告费用发布执行。`business_first_daily` 调用 `p5.daily` / `p5.sql_daily`，从受控来源构建 SQL 单仓并通过 P4 激活；Superset、Business Data MCP 与通知读取同批 release。双 Snapshot 是语培、留学来源身份，不再发布旧39表业务结果仓。默认模式（含 `--prepare`）仅准备隔离候选。

本地 SQL 基线由 `customers/shadow_bi_daily/Output/ShadowDaily/sql-current.json` 显式指定；服务器使用正式 `current`。通知沿用 DeliveryState、去重和 no-backfill 门禁，具体消费逻辑见 `monitoring_product/sql_release_notifications.py` 与 `shared_delivery`。

## 历史 raw 链路

10月26日 raw worker 曾完成双 Snapshot、quality 和39表计算，但因截止不匹配失败，未发布。11月7日 SQL 切换记录已记载旧业务发布路径停用、旧 raw 计算／传输目录清理，通知路径保留。仓库中的 `library.py`、`management/calculation.py`、`p5/raw_*.py` 及旧 raw 合同供历史验证和仍有消费者的工具使用，不是当前日更启动说明，也不表示服务器仍部署同一版本。
