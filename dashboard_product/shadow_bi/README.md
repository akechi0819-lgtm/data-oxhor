# 正式原生 BI 模块

正式产品为Superset原生BI，模块名 `shadow_bi` 与P3/P3.5/P4/P5路径沿用现有服务和导入。正式运行、部署及恢复入口见 [部署说明](../DEPLOYMENT.md)；P1实验复现见 [README-P1](README-P1.md)，不作为生产安装说明。

`library.py` 复用 `management/calculation.py`；`p3/build_projection.py` 和 `p35/` 提供原生界面；`p4/` 装载封存表并原子切版；`p5/daily.py` 为现行Mac日更入口。raw receiver、受限consumer和固定root publisher见 `p5/raw_*.py` 及 `p5/deploy/`，详细输入、队列和发布边界见 [raw合同](../../docs/server-raw-pipeline-contract.md)。

10月26日本地已将来源完整性验证整合进计算及固定发布：缺受保护完成证明不构建，证明变化不发布，P4重建后且切current前再次复核。见 [完整性合同](../../docs/server-source-completion-candidate.md)。本地整合不等于服务器已经安装；现网真实raw新包正式激活与唯一生产者切换仍待验收，服务器及日程本轮未变。

通知使用正式release及 `monitoring_product.release_notifications`，不从旧静态页恢复日常投递入口。历史P0—P5“待验收/未上线”仅描述当时状态；10月26日手动日更与8条通知的事实见 [日更回执](../../docs/shadow-bi-p5-daily-gray-20261024.md)、[通知修复回执](../../docs/notification-job-receipt-repair-20261026.md)。
