# 市场只读接口

在市场工作区执行 `./oxhor status`。返回当地数据工作区的当前 Snapshot、可用 SQL release 和正式路径。命令需要新的 `run_id`，以 `run_` 开头，使用小写字母、数字、下划线或短横线。

```bash
./oxhor query --release-id <封存版本> --task <YYYYMM-任务名> --run-id run_market_metric_001 --sql-file ../workspace/tasks/<YYYYMM-任务名>/scratch/query.sql
./oxhor describe --snapshot-id <快照> --run-id run_market_schema_001
./oxhor quality --snapshot-id <快照> --run-id run_market_quality_001
./oxhor query --layer raw --snapshot-id <快照> --task <YYYYMM-任务名> --run-id run_market_raw_001 --sql-file ../workspace/tasks/<YYYYMM-任务名>/scratch/raw.sql
./oxhor saved-query --snapshot-id <快照> --run-id run_market_saved_001 --query-id <已确认查询ID> --version <明确版本>
```

语义查询使用 `core`、`mart` 或 `ref` 中已获准关系。指标及证据关系见[经营指标索引](../docs/metrics-reference.md)。旧版看板只用于历史追溯，通过原回执辨认当时的版本。

查询和已保存查询支持 `--params-json`。查询、质量检查及已保存查询支持 `--max-rows`、`--max-result-bytes`，默认 1000 行、1,000,000 字节。新任务的查询会在 `workspace/tasks/<任务>/evidence/<run_id>/` 保存 SQL、参数和结果回执。未使用 `--task` 的入口依然落市场工作区 `Evidence/<run_id>/`，供已登记程序和旧证据使用。Snapshot 或 release 身份不匹配时阻断。
