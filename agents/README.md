# 模块 Agent

这里的每个目录都对应一个可独立选择的 Agent 工作面。调用者根据当前任务直接打开相应的 `AGENT.md`，在同一客户工作区中执行其约束和入口。

本目录不定义主 Agent、跨模块路由器、共享 Session 或模型选择规则。多个 Agent 协作时，由外部宿主或操作者决定顺序和上下文传递。

| Agent | 适用任务 | 依赖模块 |
|---|---|---|
| `workspace_setup` | 首次部署、导入、Snapshot、Bridge 对齐 | `data_acquisition`、`data_platform`、`workspace_modeling` |
| `ad_hoc_analysis` | 自由查询、诊断、下钻、按需文件交付 | `data_platform`、`workspace_modeling`、`analysis_product` |
| `dashboard_publisher` | 固定查询刷新、四分册发布、可选钉钉人员进度 | `data_platform`、`dashboard_product` |
| `daily_monitor` | 定期监控和异常推送 | 预留，尚无运行模块 |
