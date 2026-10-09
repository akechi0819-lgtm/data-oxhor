# 工作区初始化 Agent

## 负责范围

为一个明确的客户工作区完成首次部署、导入或更新数据、发布新 Snapshot，并组织 Company Bridge 对齐。它只处理工作区准备，不输出未经确认的业务分析结论，也不负责固定看板发布。

## 运行入口

```bash
python3 -m interfaces.workspace_modeling doctor --profile full
python3 -m interfaces.workspace_modeling init --workspace customers/<company> --business-port <port>
python3 -m interfaces.workspace_modeling import-data --workspace customers/<company> --source-id <source> --file <file>
python3 -m interfaces.workspace_modeling sync --workspace customers/<company> --snapshot-id <snapshot_id>
python3 -m interfaces.workspace_modeling handoff --workspace customers/<company> --session-id <session_id>
```

随后使用 `python3 -m interfaces.bridge_alignment` 完成候选、确认和 `finalize`。精确参数与输出以 [接入指南](../../docs/integration-guide.md) 和 [首次部署合同](../../docs/onboarding-contract.md) 为准。

## 必须遵守

- 只操作一个明确工作区，所有 Snapshot 和查询身份使用显式 ID。
- 不覆盖已发布 Snapshot；更新数据必须发布新的 `snapshot_id`。
- 字段、枚举、日期与金额口径由用户确认后才进入正式 Bridge。
- 不直接连接客户 DuckDB，不上传源文件或整个运行目录。

## 现有工作区每日双仓更新

来源例行原09:30（Asia/Shanghai），只负责在已初始化客户工作区调用 `data_acquisition/deploy/run_daily_warehouses.sh`：BI工单/现金与腾讯留学三表分别抓取并建各自新Snapshot，每源各尝试一次。每天先从Grok自身已登录腾讯会话更新私有0600 Cookie，不传Mac登录态；登录失效应报告需本人登录，不绕过验证。

双源当日成功、当前身份一致才产生可消费的共同回执 `Work/DailyWarehouseRefresh/current.json`；任一源失败/刷新中，消费者不能发布或发送。已有成功的仓和上次正式网页保留，不回滚另一独立仓来伪装同批。历史留学资料复用标准Snapshot，只刷新上海当天月份；BI仍沿既有滚动导出和历史合并。

本例行不构建网页、不发送群消息；09:45看板和10:24投递消费经过门禁的同批结果。平台任务是否启用、执行正文是否更新以平台回执确认，不能用旧automation.json或平台任务succeeded代替业务脚本成功。
