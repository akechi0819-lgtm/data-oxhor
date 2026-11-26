# Data OXHor

Data OXHor 更新天津市场的语培和留学 Snapshot，构建正式 Superset 看板和业务查询库，并从同批数据生成日报通知。

| 工作 | 入口 |
| --- | --- |
| 日更、人工补数、同步腾讯表、独立录入费用 | [运维手册](docs/operator-runbook.md) |
| 查经营指标、追溯归因、导表 | [市场接口](market_workspace/INTERFACES.md) |
| 新媒体及各项目周报 | [双周报技能](.agents/skills/biweekly-report/SKILL.md) |
| 架构、测试和发布维护 | [架构](docs/architecture.md) · [维护指南](docs/maintainer-guide.md) · [部署](dashboard_product/DEPLOYMENT.md) |

市场数据工作区为 `customers/shadow_bi_daily/`。新任务在 `workspace/tasks/<YYYYMM-任务名>/` 留存草稿、证据和交付。查询绑定明确的 Snapshot 或 SQL release。官方留学记分卡在已确认的口径和覆盖期内优先。

Mac 日更运行 `python -m ops run business`。现行定时任务调用 `python -m data_acquisition.jobs.prepare_full_daily --publish --business-only`，转入同一业务链。费用由 `ops ingest-cost` 独立处理。看板、MCP 和通知读取同批封存 release。

开发回归使用 `sh tools/run_tests.sh -v`。当前进度见 [DEVELOPMENT](DEVELOPMENT.md)，历史见 [归档](docs/archive/)。
