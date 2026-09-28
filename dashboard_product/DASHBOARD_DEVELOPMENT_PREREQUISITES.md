# 看板运行合同

更新时间：2026-09-09

本文档记录当前可运行边界，不再列未实施的架构计划。

## 运行边界

- 待发布基线（2026-09-23）：主看板源码使用 V14，实际查询为 `dashboard_actuals/v14`；完成客户 Saved Query registry 同步和静态页发布后，线上团队影子数据仍使用 `online_market_orders/v1`，作为主页面的特供入口，不再发布团队分册。
- 运行输入是客户工作区路径和新的 `run_id`；工作区提供当前 Snapshot 与 warehouse 路径。
- 事实查询只能通过 Data Platform 受控只读查询；发布刷新调用 `dashboard_actuals/v14`，本地规则预览可对显式 Snapshot 执行相同 SQL 文件。
- 源码不直接连接 DuckDB、不读取 landing 表、不使用 `latest` 指针。
- 运行产物只写客户工作区 `Output/Dashboard/<run_id>/`。
- 线上团队特供看板例外使用显式影子根目录 `Work/ShadowOnlineMarket/<run_id>/`；影子 Snapshot 不写回 `Work/workspace.json` 的 `current_snapshot_id`，新页面只消费显式 `--warehouse` 与 `--snapshot-id`。

## CLI

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/<workspace> --run-id run_<id>
python3 -m dashboard_product.refresh render --artifact customers/<workspace>/Output/Dashboard/run_<id>/artifact.json
python3 -m monitoring_product.notify send --workspace <workspace> --snapshot-id <snapshot_id> --run-id <run_id> --as-of-date <YYYY-MM-DD> --data-through-date <YYYY-MM-DD> --dry-run
```

`refresh` 创建不可变 artifact；`render` 只读取显式 artifact 并写出 `full.html` 主页面。当前发布由 `deploy/publish_static_dashboard.sh` 完成。线上团队影子看板由独立脚本发布为 `online_market_special.html`；留学线下影子看板发布为 `offline_market_special.html`。钉钉发送是独立命令，不并入日更脚本。

影子看板使用 `online_market_shadow` → `online_market_refresh` → `online_market_render`，网络资源计入 `资源主被动` 的被动与主动、新媒体只计被动，清洗后的 `主被动` 只作审计；现金目标已配置，现金实际明细为空，工单目标包含 FY27 网络资源 5708、新媒体 1007、合计 6715。留学线下影子看板使用 `offline_market_shadow` → `offline_market_refresh` → `offline_market_render`，部门完成只加 `offline_market_people.json` 映射到的人；工单/毛签目标按官方记分卡 2620 / 660 万元，现金实际待接入。

## 当前进度

- 四个团队页签加第五页「市场人员产能」：线下市场、线上私域（虚拟人团队）、线上平台、市场总计、市场人员产能。
- 线下市场团队个性化配置已完成；线上私域有部分人员；线上平台仍空。
- 服务器静态部署已完成：`full.html` 主页面 + basic auth；刷新、计算、Snapshot 更新和 HTML 发布准备在本机或云电脑执行。
- 例行日更每天 10:00（Asia/Shanghai）挂许家印，跑 `deploy/publish_static_dashboard.sh`。公开入口为 `http://dashboard.apinova.cn`。钉钉五通道代码已落地，线下青少/高中/大学和线上私域 webhook 已填；线上平台仍空。

## Artifact

`dashboard_artifact.v1` 顶层字段为 `schema_version`、`artifact_id`、`run_id`、`snapshot_id`、`created_at`、`query_results`、`errors`、`dashboard`。

`dashboard` 输出 FY27 的 `months`、FY26 的 `prior_months`、团队/业务组/人员聚合和目标。团队页 `groups` 是留学预备/高中/大学目标区；团队与市场总计的 `yoy_groups` 是青少/初中/高中/大学同比区。`drilldowns` 的业务组键是这四组同比，高中/大学支持学校→年级。`market_total.groups` 按线下市场、线上市场、虚拟人和“暂时无法识别团队”汇总；`market_total.business_group_groups` 按留学预备、高中、大学和“业务组暂无法拆分”汇总。两种口径在市场总计页并列显示，`market_total.people` 为空。现金团队/渠道兜底由 `cash_channel_fallback_rules.json` 驱动；渠道下钻展示现有工单组合或标准映射结果，不用原始现金渠道冒充标准一级/二级渠道。渲染器仍以相同索引切季度同比，并用现有渠道下钻在业务组同期对比下画渠道同期对比（二级渠道 × 四组，组内现金占比=该渠道内该业务组份额；右侧合计占总现金占比，按合计现金降序，底行总计）。缺少目标写 `null` 并显示“未配置”。

个人实际归属先按工单团队和业务组筛选，再匹配人员。顺序：活动名含花名册姓名 → SQL 已抽进 `entry_person` 的「市场人员：」或资源录入人 → Python 侧再用「姓名市场资源」和去掉旧活动串后的资源描述正文。现金用工单 ID 对全量工单数仓连，不限本绩效月；连上继承该工单归属，连不上再使用独立的团队/渠道兜底规则；兜底分配不自动落到个人。

人员对象可包含 `business_group`、`monthly_targets`、`monthly_drilldowns`、`heads_actual`、`annual_cash_capacity`、`line` 和 `cash_contributions`。产能页全员标准产能为 80 万，不进钉钉。线下人员目标与明细按绩效月保存，线上私域和线上平台按自然月保存；现金或工单目标缺失时显示“未配置”。大学人头目标折算后的现金目标由配置直接登记，看板 HTML 仍展示现金。钉钉大学通道播报图改展示人头完成，不把 1500 校区门槛套进来；明细表人员进度额外带现金目标/完成。钉钉花名册以 `workspace_modeling/operations/people.json` 覆盖 artifact；2026-09-10 线上私域小初提能组为潘体学（工单 25、现金 50,000）。`monthly_drilldowns` 按各团队月份口径和指标保存一级/二级渠道完成值；现金下钻优先用工单一级/二级渠道，缺少组合时用已确认的标准映射，仍无法识别则单列渠道暂无法识别。现金表原始渠道仅作为规则输入，不直接当作标准渠道展示。`vacant`、`departed`、`transferred` 人员保留在配置中用于状态追踪，但不写入展示 artifact，也不进入当前监控名单。

## Saved Query 与业务口径

查询合同登记在 `config/saved_queries.json`。刷新使用 `dashboard_actuals/v14` 两次（当前及去年同期），参数为 `[start_date, end_date]`；第 12 列为 `student_id`，第 13–15 列保留现金来源渠道、匹配工单主被动和现金原始活动名。逐笔对账使用 `attributed_passive_reported_cash/v1`，同样按业务日期使用半开区间。产能页人员标准产能见 `config/capacity_targets.json`。

现金范围为被动、新生、正向报入现金。现金业务组只看现金表团队，不跟工单改口；团队归属先继承精确关联工单，现金未归属时按 `config/cash_channel_fallback_rules.json` 逐项匹配，空白和“12”不限制，最低优先级序号胜出。若现有工单为被动而规则判主动，渠道状态归入“自然无法判定”；工单/渠道匹配状态与现金表“被动”属性分开保留。TMK 归线下市场；“河北工业大学国际学院集训营”系列的二级渠道按用户确认覆盖为“讲座”。无法识别的团队在团队表单列为“暂时无法识别团队”。

## 验收

从项目父目录运行：

```bash
python3 -m unittest discover -s dashboard_product/tests -v
python3 -m interfaces.company_bridge validate \
  --bridge /absolute/path/to/confirmed-workspace-bridge.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
```
