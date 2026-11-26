# 市场工作区

市场工作绑定正式工作区 `customers/shadow_bi_daily/`。先运行 `./oxhor status`，以显式 release 或 Snapshot 执行受控查询。留学记分卡、口径和同比范围见[经营分析技能](../.agents/skills/biz-analysis/SKILL.md)。

新任务文件放在本目录的 `tasks/<YYYYMM-任务名>/{scratch,evidence,deliverables}`。历史正式成果继续留在 `Reports/`，原查询证据和参考分别留在 `Evidence/` 与 `Notes/`。交付和清理见[根入口](../AGENTS.md#任务文件与收尾)。

在本目录执行查询时，每次提供新的 `run_` ID。语义查询只允许 `core`、`mart` 和 `ref` 中明确准入的关系。新任务用 `--task` 将回执写入任务的 `evidence` 子目录。

```bash
./oxhor status
./oxhor query --release-id RELEASE --task 202611-经营分析 --run-id run_market_metric_001 --sql-file tasks/202611-经营分析/scratch/query.sql
./oxhor query --layer raw --snapshot-id SNAPSHOT --task 202611-经营分析 --run-id run_market_raw_001 --sql-file tasks/202611-经营分析/scratch/raw.sql
./oxhor describe --snapshot-id SNAPSHOT --run-id run_market_schema_001
./oxhor quality --snapshot-id SNAPSHOT --run-id run_market_quality_001
./oxhor saved-query --snapshot-id SNAPSHOT --run-id run_market_saved_001 --query-id ID --version VERSION
```

查询和已保存查询可传 `--params-json`。两者及质量检查默认上限为 1,000 行、1,000,000 字节，可用 `--max-rows` 和 `--max-result-bytes` 调整。`query` 不传 `--task` 时，以及工作区级查询工具，沿用 `Evidence/<run_id>`。数据选择和字段见[经营指标索引](../docs/metrics-reference.md)。

周报、项目套图与新媒体双周报使用[双周报技能](../.agents/skills/biweekly-report/SKILL.md)。看板、腾讯表和钉钉按当前任务授权执行。
