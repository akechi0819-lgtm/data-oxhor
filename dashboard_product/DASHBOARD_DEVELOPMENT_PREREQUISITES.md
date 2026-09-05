# 看板运行合同

更新时间：2026-09-06

本文档记录当前可运行边界，不再列未实施的架构计划。

## 运行边界

- 运行输入是客户工作区路径和新的 `run_id`；工作区提供当前 Snapshot 与 warehouse 路径。
- 事实查询只能通过 Data Platform `run-saved-query`，当前刷新调用 `dashboard_actuals/v6`。
- 源码不直接连接 DuckDB、不读取 landing 表、不使用 `latest` 指针。
- 运行产物只写客户工作区 `Output/Dashboard/<run_id>/`。

## CLI

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/<workspace> --run-id run_<id>
python3 -m dashboard_product.refresh render --artifact customers/<workspace>/Output/Dashboard/run_<id>/artifact.json
```

`refresh` 创建不可变 artifact；`render` 只读取显式 artifact。当前发布由 `deploy/publish_static_dashboard.sh` 完成；CLI 的 `push` 不是发布入口。

## 当前进度

- 三个团队已纳入看板：线下市场、线上私域（虚拟人团队）、线上平台。
- 线下市场团队个性化配置已完成。
- 线上私域和线上平台仍待完成个性化配置。
- 服务器静态部署已完成；刷新、计算、Snapshot 更新和 HTML 发布准备均在本地执行。
- Codex 唯一自动化每天 10:00（Asia/Shanghai）发布全量看板；服务器仅通过 Nginx 托管 `/var/www/dashboard/current.html`。

## Artifact

`dashboard_artifact.v1` 顶层字段为 `schema_version`、`artifact_id`、`run_id`、`snapshot_id`、`created_at`、`query_results`、`errors`、`dashboard`。

`dashboard` 输出 FY27 的 `months`、FY26 的 `prior_months`、团队/业务组/人员聚合和目标，并包含 `drilldowns`（现金/工单的渠道、年级、大学学校→年级）。`market_total` 是三个团队的合计对象，`people` 固定为空。业务组同时包含 `monthly_actuals` 与 `prior_monthly_actuals` 两组 12 个月数组；渲染器以相同索引切季度同比。顶部现金和工单汇总显示当期、同期、同比、目标和完成率。缺少目标写 `null` 并显示“未配置”。

个人实际归属先按工单团队和业务组筛选，再匹配活动名称中的人员姓名；活动名称含“校代”且未匹配姓名时使用工单 `资源录入人`，现金通过 `工单ID` 继承工单个人归属。

人员对象可包含 `business_group`、`monthly_targets` 和 `monthly_drilldowns`。人员目标按绩效月保存，现金或工单目标缺失时显示“未配置”；大学人头目标折算后的现金目标由配置直接登记。`monthly_drilldowns` 按绩效月和指标保存一级/二级渠道完成值；现金下钻的渠道必须来自现金按 `工单ID` 左连接后的工单维度，未匹配时为“暂无归属”，不能改用现金表原始渠道。`vacant` 占位人员保留在人员配置中，但不写入展示 artifact。

## Saved Query 与业务口径

查询合同登记在 `config/saved_queries.json`。刷新使用 `dashboard_actuals/v6`，参数 `[start_date, end_date]`；逐笔对账使用 `attributed_passive_reported_cash/v1`，同样按业务日期使用半开区间。

现金范围为被动、新生、正向报入现金。现金通过 `工单ID` 左连接工单表获取渠道和关联业务组；未关联时业务组回退现金团队，渠道固定为 `暂无归属`，团队再按虚拟人、线上、TMK、校代、默认线上平台顺序归属。团队兜底和工单关联状态必须分开报告。

## 验收

从项目父目录运行：

```bash
python3 -m unittest discover -s dashboard_product/tests -v
python3 -m interfaces.company_bridge validate \
  --bridge artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
```
