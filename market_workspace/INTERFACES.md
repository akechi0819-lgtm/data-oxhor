# 市场只读接口

在市场工作区内调用 `./oxhor`。这是路径绑定与证据落地入口，实际查询仍由现有 `interfaces.data_platform` 执行，SQL 只读校验继续由 Data Platform 负责。不会启动新的 Agent、模型或路由系统。

## 先检查状态

```bash
./oxhor status
```

仅当 `next_step=analyze` 时继续。用返回的 `snapshot_id` 明确绑定本次命令；每次命令使用新的 `run_id`（`run_` 开头、小写字母/数字/下划线/短横线）。若数据指针已切换或 Bridge 不兼容，命令阻断，不自动换成另一个 Snapshot。

## 查询

```bash
./oxhor describe --snapshot-id <显式ID> --run-id run_market_schema_001
./oxhor quality --snapshot-id <显式ID> --run-id run_market_quality_001
./oxhor query --snapshot-id <显式ID> --run-id run_market_question_001 --sql-file Scratch/<任务名>/query.sql
./oxhor saved-query --snapshot-id <显式ID> --run-id run_market_saved_001 --query-id <已确认查询ID> --version <明确版本>
```

query/saved-query 支持 `--params-json`；quality/query/saved-query 支持 `--max-rows`、`--max-result-bytes`，默认 1000 行／1000000 字节。query 的 SQL 文件必须在市场工作区内，执行时先复制到本次 Evidence 目录，删除 Scratch 不会丢失查询 SQL。

### 复算旧看板

复现当前正式看板时，从同批 SQL release 读取指标，固定批次、期间、业务线及团队筛选，见[部署说明](../dashboard_product/DEPLOYMENT.md)。旧报表按原回执选 `dashboard_actuals` 版本；仅凭报表日期无法确定版本时，先核对原回执。

| 旧版本 | 当时的工单及现金团队归属 |
|---|---|
| v9 | 关联池仅含可识别业务组的被动工单；现金未取得团队时按活动名或渠道推断，最终兜底线上平台。具体启用期缺少回执。 |
| v10、v12 | 两份 SQL 完全相同。全量工单参与关联，被动工单计数；工单业务组缺失时团队留空，现金业务组缺失时现金团队也留空。旧版运行记录分别见 [v10](../docs/history/dashboard/CURRENT_STATUS.md) 和 [v12](../DEVELOPMENT.md)。 |
| v14 | 即使业务组缺失，仍保留匹配到的工单团队，现金也使用匹配工单的团队。见[当时的查询合同](../docs/history/dashboard/DASHBOARD_DEVELOPMENT_PREREQUISITES.md)。 |

## 案例只读

```bash
./oxhor cases --snapshot-id <显式ID> --run-id run_market_cases_001 --category <问题类别>
./oxhor verify-case --snapshot-id <显式ID> --run-id run_market_casecheck_001 --case-id <案例ID>
```

检索绑定当前公司的 marketing 角色，不跨角色自动扩大范围。命中案例不等于当前事实；verify-case 仅校验证据，不确认案例。

## 回执与限制

- 输出固定在 `Evidence/<run_id>/receipt.json`，包含数据工作区、Snapshot、运行编号、退出码和原接口返回；平台大结果文件也位于该目录。
- 手写 SQL 留为 `query.sql`；保存查询由平台记录查询身份、SQL 哈希和来源凭据。
- describe 原接口无需 run_id，本入口为其增加本地证据目录，不改变平台接口。
- 当前所有命令先执行 casebook guide。失败或 Snapshot 不匹配时阻断；平台查询失败的 JSON 回执仍保留，进程返回非零。
- 不接受自定义 warehouse、数据工作区或输出根目录参数；不提供写仓、导入、发布、案例写入和推送接口。
- `./oxhor` 固定使用相邻项目的 `.venv/bin/python`。运行时不可用就明确报错，不退回其他环境。

生成程序需要数据时，调用本入口或读取本次 Evidence；禁止在程序里直接连接数仓。程序依赖建在 `Programs/<任务名>/` 内，不污染共享环境。
