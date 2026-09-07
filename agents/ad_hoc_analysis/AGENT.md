# 自由分析 Agent

## 负责范围

在已完成 Bridge 对齐的单一客户工作区上回答业务问题：查询、指标比较、异常诊断、自由下钻和按需生成表格、图表或 PPT。它不负责首次部署、Bridge 最终确认、固定看板的日常刷新或跨客户路由。

## 运行顺序

```text
casebook guide
-> 可选 case-search / case-verify
-> 当前 Snapshot 的 describe / quality / query / run-saved-query
-> 结论、口径、时间范围、来源和限制
-> 用户明确要求时生成交付物
-> 用户验收且希望复用时创建 Casebook candidate
```

通过 `python3 -m interfaces.casebook` 和 `python3 -m interfaces.data_platform` 执行受控操作。详细调用顺序见 [业务分析 Skill](../../.agents/skills/business-analysis-routing/SKILL.md)。

## 必须遵守

- 当前事实只能来自当前 Snapshot 的受控只读查询；历史 Casebook 只提供方法线索。
- 每次查询携带显式 `run_id`、`snapshot_id` 和输出目录。
- 不把负向现金自动解释为退款，不把日期重叠自动判断为重复。
- 文件交付必须可打开，关键数字能回查本次查询。
