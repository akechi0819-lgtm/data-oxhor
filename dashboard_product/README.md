# Dashboard Product

看板是独立产品，消费已确认的工作区状态与 Data Platform 的受控查询结果；它不直接连接 DuckDB、不解释企业字段、不修改 Bridge，也不读取 `latest` 指针。

## 当前状态

目前只实现显式身份的 artifact 生命周期：

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/<workspace> --run-id run_<id>
python3 -m dashboard_product.refresh render --artifact customers/<workspace>/Output/Dashboard/run_<id>/artifact.json
python3 -m dashboard_product.refresh push --artifact customers/<workspace>/Output/Dashboard/run_<id>/artifact.json
```

`refresh` 从工作区读取当前 Snapshot 身份并创建不可变 artifact；`render` 只渲染指定 artifact；`push` 明确返回 `not_started`。服务器、定时任务和推送均未开始。刷新仍须先定义 confirmed saved query 合同，再由 Data Platform 执行。

## 静态页面投影

`render` 不读取工作区、项目目标 JSON、人员 JSON 或任何数仓文件。刷新流程必须把已确认 saved query 的结果整理为 artifact 内的 `dashboard` 投影，并把对应来源凭据保留在 `query_results`。缺少个人或组目标必须以 `null` 写入，页面显示“未配置”，绝不当作零。页面同时区分自然月项目目标与每月 26 日至次月 25 日人员绩效月。

## Saved Query 归属

看板项目只登记查询合同，不复制业务 SQL。查询清单见 [`config/saved_queries.json`](./config/saved_queries.json)，SQL 正文由客户工作区的 Data Platform saved-query registry 持有，并通过 `run-saved-query` 绑定显式 `run_id` 和 `snapshot_id` 执行。

当前实际口径：工单只统计被动工单并按工单 `ID` 去重；团队按 `线下`、`线上私域（虚拟人）`、`线上平台` 归属，业务团队只保留 `留学预备`、`高中`、`大学`；人员层另按人员 JSON 的青少、初中、高中、大学等组织组展示，个人工单按“市场活动名称包含姓名”归属。现金只统计现金表 `渠道属性=被动` 且 `报入现金收入>0` 的记录。

## 看板配置

[`config/project_targets.json`](./config/project_targets.json) 是看板侧维护的项目目标配置。当前录入 FY27 语培的高中、留学预备、大学三组季度目标：按总被动现金和总被动工单拆分，线上平台占 55%，线下市场占 45%，线上私域（虚拟人）额外占 6%。

[`config/people.json`](./config/people.json) 是当前人员与组织结构配置：线下市场、线上私域（虚拟人）已录入，线上平台暂不配置人员。它保留空缺占位、状态备注和一人多组关系；数仓只提供事实数据，不维护这些配置。

客户运行产物仅写入客户工作区的 `Output/Dashboard/<run_id>/`，不放在源码目录。

下一阶段开发前置条件见 [`DASHBOARD_DEVELOPMENT_PREREQUISITES.md`](./DASHBOARD_DEVELOPMENT_PREREQUISITES.md)。
