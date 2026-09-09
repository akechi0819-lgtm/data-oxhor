# 看板运行合同

更新时间：2026-09-09

本文档记录当前可运行边界，不再列未实施的架构计划。

## 运行边界

- 运行输入是客户工作区路径和新的 `run_id`；工作区提供当前 Snapshot 与 warehouse 路径。
- 事实查询只能通过 Data Platform `run-saved-query`，当前刷新调用 `dashboard_actuals/v7`。
- 源码不直接连接 DuckDB、不读取 landing 表、不使用 `latest` 指针。
- 运行产物只写客户工作区 `Output/Dashboard/<run_id>/`。

## CLI

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/<workspace> --run-id run_<id>
python3 -m dashboard_product.refresh render --artifact customers/<workspace>/Output/Dashboard/run_<id>/artifact.json --all-booklets
python3 -m dashboard_product.notify send --artifact customers/<workspace>/Output/Dashboard/run_<id>/artifact.json --dry-run
```

`refresh` 创建不可变 artifact；`render --all-booklets` 只读取显式 artifact 并写出四分册。当前发布由 `deploy/publish_static_dashboard.sh` 完成。钉钉发送是独立命令，不并入日更脚本。

## 当前进度

- 三个团队已纳入看板：线下市场、线上私域（虚拟人团队）、线上平台。
- 线下市场团队个性化配置已完成；线上私域有部分人员；线上平台仍空。
- 服务器静态部署已完成：四分册 HTML + basic auth；刷新、计算、Snapshot 更新和 HTML 发布准备在本机或云电脑执行。
- 例行日更每天 10:00（Asia/Shanghai）挂许家印，跑 `deploy/publish_static_dashboard.sh`。公开入口为 `http://dashboard.apinova.cn`。钉钉五通道代码已落地，线下青少/高中/大学 webhook 已填；线上私域、线上平台仍空。

## Artifact

`dashboard_artifact.v1` 顶层字段为 `schema_version`、`artifact_id`、`run_id`、`snapshot_id`、`created_at`、`query_results`、`errors`、`dashboard`。

`dashboard` 输出 FY27 的 `months`、FY26 的 `prior_months`、团队/业务组/人员聚合和目标。`groups` 是留学预备/高中/大学目标区；`yoy_groups` 是青少/初中/高中/大学同比区。`drilldowns` 的业务组键是这四组同比，高中/大学支持学校→年级。`market_total` 合计三个团队且 `people` 为空。渲染器以相同索引切季度同比。缺少目标写 `null` 并显示“未配置”。

个人实际归属先按工单团队和业务组筛选，再匹配人员。顺序：活动名含花名册姓名 → SQL 已抽进 `entry_person` 的「市场人员：」或资源录入人 → Python 侧再用「姓名市场资源」和去掉旧活动串后的资源描述正文。现金用工单 ID 对全量工单数仓连，不限本绩效月；连上继承该工单归属，连不上再退回现金表市场活动名。看板 artifact 只有 11 列，不含完整资源描述；「姓名市场资源」和描述正文兜底主要在钉钉明细路径生效。

人员对象可包含 `business_group`、`monthly_targets` 和 `monthly_drilldowns`。人员目标按绩效月保存，现金或工单目标缺失时显示“未配置”；大学人头目标折算后的现金目标由配置直接登记。`monthly_drilldowns` 按绩效月和指标保存一级/二级渠道完成值；现金下钻的渠道必须来自现金按 `工单ID` 左连接后的工单维度，未匹配时为“暂无归属”，不能改用现金表原始渠道。`vacant` 占位人员保留在人员配置中，但不写入展示 artifact。

## Saved Query 与业务口径

查询合同登记在 `config/saved_queries.json`。刷新使用 `dashboard_actuals/v7`，参数 `[start_date, end_date]`；逐笔对账使用 `attributed_passive_reported_cash/v1`，同样按业务日期使用半开区间。

现金范围为被动、新生、正向报入现金。现金业务组只看现金表团队，不跟工单改口。工单 ID 左连接只取渠道和人员；未关联时渠道为 `暂无归属`。团队再按虚拟人、线上、TMK、校代、默认线上平台顺序归属。团队兜底和工单关联状态必须分开报告。

## 验收

从项目父目录运行：

```bash
python3 -m unittest discover -s dashboard_product/tests -v
python3 -m interfaces.company_bridge validate \
  --bridge artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
```
