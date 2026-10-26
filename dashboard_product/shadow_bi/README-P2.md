# P2：从源输入重建业务库

> 本文记录 P2 的历史施工与验收路径；下面的审计目录、批次 ID 和快照 ID 都属于当时的证据样例，不是当前生产操作指令。当前原生 BI 部署、raw 计算和发布入口见[正式 BI 部署说明](../DEPLOYMENT.md)。

P2 阶段实现的 `library.py` 仍作为共享业务库实现供当前服务器 raw worker 调用；阶段验收构建30张实际消费者表，`verify_library.py`通过 Data Platform 受控入口逐表读库对账，只有它读取P0旧输出。`audit_command.py`记录实际子进程命令、工作目录、开始/结束和退出码，不生成成功观察。P1历史证据见[P1验证记录](../../docs/shadow-bi-p1-validation-20261022.md)，不再表示P1实验源代码仍在当前 `main`。

规则、查询合同及同批回执分别见[P2规则清单](../../docs/shadow-bi-p2-rules-20261022.md)、[业务库合同](../../docs/shadow-bi-p2-query-contract.md)、[P2施工记录](../../docs/shadow-bi-p2-validation-20261022.md)。从空目录复建：

```bash
python3 -B -m dashboard_product.shadow_bi.library copy-inputs \
  --frozen-workspace .local/audits/shadow-bi-p0-20261022/workspace \
  --workspace .local/audits/<新实验>/workspace
python3 -B -m dashboard_product.shadow_bi.library build \
  --workspace .local/audits/<新实验>/workspace \
  --snapshot-id snapshot_bi_operations_20261022_full_reexport \
  --study-abroad-snapshot-id snapshot_study_abroad_20261013_local_103935 \
  --run-id run_shadow_p2_<新批次> --as-of-date 2026-10-22
```

输出位于该副本 `Output/ShadowBI/<新批次>/library`。拒绝覆盖已有批次，不能把 `calculated/` 验收辅助JSON当新的来源输入。查询示例：将 `SELECT fact_id,event_date,value FROM queries.facts WHERE business_line = ? ORDER BY fact_id LIMIT ? OFFSET ?` 保存为本地SQL，运行 `python3 -B -m interfaces.business_library query --library <库目录> --batch-id <批次> --sql-file <SQL> --params-json '["training",50,0]' --run-id run_inspect_p2 --output-root <证据目录>`。
