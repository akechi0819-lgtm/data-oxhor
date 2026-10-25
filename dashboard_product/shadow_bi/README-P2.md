# P2：从源输入重建业务库

P1文件及证据保持原用途。P2新增 `library.py`，复用 `management/calculation.py` 从源Snapshot计算，构建30张实际消费者表；`verify_library.py`通过Data Platform受控入口逐表读库对账，只有它读取P0旧输出。`audit_command.py`记录实际子进程命令、工作目录、开始/结束和退出码，不生成成功观察。

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
