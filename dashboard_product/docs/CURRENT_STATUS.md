# 当前状态

更新时间：2026-09-05

## 已完成

- FY27 看板展示、团队/业务组/人员筛选和本地季度切换已完成。
- 刷新链路已固定为 `refresh` 生成 artifact、`render` 生成 HTML；输出文件为 `artifact.json` 与 `artifact.html`。
- 现金按现金表团队独立映射业务组，工单只在同组内拆分渠道；口径包含被动、新生、正向报入现金。
- 未匹配归属规则已固化为：虚拟人、线上、TMK、校代、默认线上平台；同时保留工单关联状态的逐笔 Saved Query。
- FY26/FY27 Q1 对账已完成。留学预备差异约 24,400 元、大学线上看板差异约 6,980 元，业务方均确认可接受。

## 当前合同

刷新必须在父目录执行：

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/bi_operations --run-id run_dashboard_<id>
python3 -m dashboard_product.refresh render --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json
```

`dashboard_actuals/v6` 是刷新唯一消费的 Saved Query，参数为 `[start_date, end_date]`。`attributed_passive_reported_cash/v1` 是逐笔对账底稿，不被刷新自动调用。

artifact 的业务组字段包括 `monthly_actuals`（FY27 12 个月）和 `prior_monthly_actuals`（FY26 对应 12 个月）；同比渲染按所选季度切同一索引段。旧的 `prior_totals`、`metrics` 和 `bus_monthly` 结构已废弃。

## 已知边界

- 当前看板输出不再保留空的 `暂无法匹配` 团队入口；若底层快照重新出现未映射业务组，需先完成 Bridge 对齐后再纳入正式看板。
- 团队兜底归属是业务分配，不代表工单关联成功。
- `push` 尚未实现，仅返回 `not_started`。
- 负向现金仍按数据事实保留为负向现金，原因需业务确认。

## 关键路径

- 代码：`refresh.py`、`render_template.py`
- 配置：`config/project_targets.json`、`config/people.json`、`config/saved_queries.json`
- 最终看板：`customers/bi_operations/Output/Dashboard/run_dashboard_newstudent_final_20260905/`
- 当前 Bridge：`artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json`
