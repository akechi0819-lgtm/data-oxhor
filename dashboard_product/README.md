# 固定看板

`dashboard_product/` 负责已确认口径的固定查询、看板 artifact、统一主页面和静态发布。人员绩效监控和钉钉日报已迁至 [monitoring_product](../monitoring_product/README.md)，不再由看板入口计算或发送。

线上团队特供看板是独立链路：留学线上工单先进入 `Work/ShadowOnlineMarket/` 下的影子 Snapshot，不更新主工作区当前 Snapshot；现金目标已配置，现金实际暂不接入。留学线下市场特供同样使用影子 Snapshot（`Work/ShadowOfflineMarket/`），部门完成按团队映射人员加总，不改主仓清洗或 V12「线下市场」页计算。V12 主页面只保留特供页入口，不复用或改写留学计算。

## 运行

```bash
python3 -m dashboard_product.refresh refresh --workspace <workspace> --run-id <run_id>
python3 -m dashboard_product.refresh render --artifact <artifact.json>

# 影子 Snapshot 与留学线上看板
python3 -m dashboard_product.online_market_shadow \
  --workspace customers/bi_operations \
  --shadow-root customers/bi_operations/Work/ShadowOnlineMarket \
  --run-id run_online_market_shadow_<id> \
  --snapshot-id snapshot_online_market_shadow_<id>
python3 -m dashboard_product.online_market_refresh \
  --warehouse <shadow-warehouse.duckdb> \
  --snapshot-id <shadow-snapshot-id> \
  --output-root <output-dir> \
  --run-id run_online_market_<id>
python3 -m dashboard_product.online_market_render \
  --artifact <output-dir>/online_market_artifact.json

# 影子 Snapshot 与留学线下看板
python3 -m dashboard_product.offline_market_shadow \
  --workspace customers/bi_operations \
  --shadow-root customers/bi_operations/Work/ShadowOfflineMarket \
  --run-id run_offline_market_shadow_<id> \
  --snapshot-id snapshot_offline_market_shadow_<id>
python3 -m dashboard_product.offline_market_refresh \
  --warehouse <shadow-warehouse.duckdb> \
  --snapshot-id <shadow-snapshot-id> \
  --output-root <output-dir> \
  --run-id run_offline_market_<id>
python3 -m dashboard_product.offline_market_render \
  --artifact <output-dir>/offline_market_artifact.json
```

当前整体发布基线为 V12：纳入线上影子看板和人员规则更新，主看板事实查询合同为 `dashboard_actuals/v12`。刷新通过 Data Platform 受控查询读取当前 Snapshot；线上影子看板继续使用 `online_market_orders/v1`，作为主页面入口后的独立特供页。市场总计保留全部有效事实；项目、团队、渠道、顾问和人员仅使用严格归属。无法映射业务组的事实标记为“业务组暂无法拆分”；工单 ID 为空或无法精确匹配的现金在渠道与顾问下标记为“渠道/顾问暂无法拆分”，两者都不强行分配给团队或个人。公网只托管 `full.html` 主页面、`online_market_special.html` 和 `offline_market_special.html`，不上传全量 artifact。定时仍由外部宿主调用 `deploy/publish_static_dashboard.sh`。

## 配置与边界

- `config/project_targets.json`：语培团队与业务组目标；线上平台另有《语培目标暂行》月度目标。
- `config/capacity_targets.json`：人员标准产能。
- `config/saved_queries.json`：固定查询合同。
- `config/online_market_targets.json`：留学线上年度/季度网络资源、新媒体工单目标和毛签目标；月度目标、二级渠道目标和现金实际暂不配置。
- `config/online_market_queries/`：影子 Snapshot 使用的留学线上只读查询合同。
- `config/offline_market_targets.json`：留学线下全年工单/毛签目标，按官方记分卡累计 2620 / 660 万元。
- `config/offline_market_people.json`：留学线下团队人员名单；部门完成只加这些映射到的人。
- `config/offline_market_queries/`：影子 Snapshot 使用的留学线下只读查询合同。
- `workspace_modeling/operations/people.json`：与监控共用的人员组织和目标。
- `workspace_modeling/operations/personnel.py`：与监控共用的绩效月及人员匹配规则。

发布权限与静态服务器见 [部署说明](DEPLOYMENT.md)。看板发布不授予监控发送权限，监控也不修改或发布看板。

## 验证

```bash
python3 -m unittest discover -s dashboard_product/tests -v
```

部署迁移须同时同步共享业务目录和新的 `refresh.py`；监控的 SQL、发送命令、凭据输入及云端任务切换见 [监控运行合同](../monitoring_product/README.md)。

## 产品行为与核对边界

- 主页面包含线下市场、线上私域、线上平台、市场总计和市场人员产能；季度筛选作用于团队目标与同比，人员产能使用全年范围。
- 团队目标按留学预备、高中、大学展示；同比与渠道拆分按青少、初中、高中、大学展示。市场总计保留“业务组暂无法拆分”，因此不要求等于三个已分配团队之和。
- 工单指标统计有效被动工单；现金指标使用被动、新生、正向报入现金。现金通过工单 ID 精确关联全量工单，关联不局限于当前绩效月；现金业务组按现金表团队判断。
- “工单是否精确匹配”与“业务组是否明确”是不同条件，未归属事实保留在市场总计，不静默丢弃，也不默认分给线上平台。
- 刷新只消费 `dashboard_actuals/v12`，参数为 `[start_date, end_date]`，第 12 列为 `student_id`。`attributed_passive_reported_cash/v1` 是独立逐笔核对底稿，不替代看板实际归属合同；对账须说明所用查询与口径。
- 个人归属沿用现有活动名、市场人员、资源描述和录入人规则。`TMK激活-平台`、活动含 `校代系统资源` 且市场人员属于线下花名册的归属规则仍在现有实现中；调整人员时须核对共享花名册及监控 SQL，不能只改文档。
- 当前人员展示和归属候选统一使用 `personnel.is_displayable_person`；`vacant`、`departed`、`transferred` 不进入看板或监控花名册，监控 SQL 的线下名单必须同步当前可展示花名册。
- 人员产能使用配置中的标准产能，展示现金、时间进度及六维指标；不因此触发钉钉。看板发布与监控发送权限独立。
- 人员目标和组织配置以当前 `workspace_modeling/operations/people.json` 为准；历史记录中的人员名单、配置完成度、Webhook 状态不代表当前实查结果。
- 发现“员工自报 10 条、图表 9 条”等差异，先按明细检查录入、时间与归属口径，再判断是否为实现缺陷。历史接受的金额差异不作为新 Snapshot 的默认豁免。
- 负向现金按数据事实描述，原因须业务确认；不自动解释为退款。
- 留学线上影子看板：网络资源计入 `资源主被动` 的被动与主动，新媒体只计被动；清洗后的 `主被动` 只作审计。现金目标已配置，现金实际明细仍显示“待接入”。
- 留学线下影子看板：有效工单 ID、团队为空，并映射到 `offline_market_people.json` 名单后才计入部门完成；人员完成按个人加总。现金实际待接入。

本次目录整理只移动材料与调整入口，不修改 SQL、公式或归属计算。过去施工与调查见 [历史目录](../docs/history/dashboard/)；历史文档不是现行操作入口。
