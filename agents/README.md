# 模块 Agent

这里的每个目录都对应一个可独立选择的 Agent 工作面。调用者根据当前任务直接打开相应的 `AGENT.md`，在同一客户工作区中执行其约束和入口。

根目录 `AGENTS.md` 提供轻量板块导航，只指向对应说明，不预加载全部 Agent。本目录不定义总控 Agent、跨模块调度、共享 Session 或模型选择规则。多个 Agent 协作时，由外部宿主或操作者决定顺序和上下文传递。

| Agent | 适用任务 | 依赖模块 |
|---|---|---|
| `workspace_setup` | 首次部署、导入、Snapshot、Bridge 对齐 | `data_acquisition`、`data_platform`、`workspace_modeling` |
| `ad_hoc_analysis` | 自由查询、诊断、下钻、按需文件交付 | `data_platform`、`workspace_modeling`、`analysis_product` |
| `dashboard_publisher` | 固定查询刷新、四分册发布 | `data_platform`、`dashboard_product` |
| `daily_monitor` | 人员进度监控和钉钉日报 | `data_platform`、`monitoring_product` |
