# 正式原生 BI 模块

正式产品为 Superset 原生 BI；`shadow_bi` 与 P3/P3.5/P4/P5 路径沿用已部署服务及稳定导入。运行状态、部署边界和发布验收见[部署说明](../DEPLOYMENT.md)。

服务器 raw worker 使用 `library.py` 和 `management/calculation.py`，基于 root 只读历史基线更新双 Snapshot，运行 quality 与共享聚合，生成39张封存业务表。P4负责重建、验收和切版；raw receiver、受限consumer、固定root publisher见 `p5/raw_*.py` 和 `p5/deploy/`，输入、队列和发布状态见[raw链路合同](../../docs/server-raw-pipeline-contract.md)。

10月26日真实服务器批次确实完成双 Snapshot、两份 quality 查询并运行到39表，最终因业务截止不匹配以 `failed/published=false` 结束，没有发布该批。raw接收、计算与publisher已部署，不等同于有效新包正式发布、持续日更或唯一生产者切换；这些事项各自待验收。Mac `p5.daily` 仍是可用手动入口，且有10月26日 current 更新记录；它不作为长期默认路径。

当前 `main` 已将受保护来源完整性证明接入计算和固定发布；10月26日服务器部署版本不含此项本地新增门禁，不能推断其已在服务器生效。见[来源完整性合同](../../docs/server-source-completion-candidate.md)。

通知从正式release取数，使用 `monitoring_product.release_notifications` 和 `shared_delivery`；不依赖旧页面，也不独立查询数仓。历史P0—P5“待验收/未上线”只描述当时状态。10月26日当前release和通知记录见[部署说明](../DEPLOYMENT.md)、[日更回执](../../docs/shadow-bi-p5-daily-gray-20261024.md)及[通知修复回执](../../docs/notification-job-receipt-repair-20261026.md)。
