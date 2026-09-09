# 看板交接

更新时间：2026-09-09

## 产品边界

`dashboard_product` 是静态看板生成器。它不直接访问 DuckDB，不修改 Bridge，不依赖 `latest` 指针；所有事实来自当前工作区 Snapshot 的 Data Platform Saved Query 结果。

当前看板包含三个团队。线下市场团队个性化配置已完成；线上私域已有部分人员，线上平台仍待完成个性化配置。人员配置中的 `pending`、`probation` 和 `vacant` 是编制状态，不改变上述团队配置完成度。

## 运行合同

从 `/Users/akechi/Desktop/manager -CowH` 执行：

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/bi_operations --run-id run_dashboard_<id>
python3 -m dashboard_product.refresh render --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json --all-booklets
python3 -m dashboard_product.notify send --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json --dry-run
```

刷新读取 `customers/bi_operations/Work/workspace.json` 的 `current_snapshot_id`，调用 `dashboard_actuals/v6` 两次：当前窗口和上一财年对应窗口。输出写入 `customers/bi_operations/Output/Dashboard/<run_id>/`。云电脑等价根目录是 `/home/box/oxhor/dashboard`，customers 软链到 warehouse。

## Artifact 合同

顶层字段：`schema_version`、`artifact_id`、`run_id`、`snapshot_id`、`created_at`、`query_results`、`errors`、`dashboard`。

`dashboard` 至少包含：

- `months`: `2026-06` 至 `2027-05`
- `prior_months`: `2025-06` 至 `2026-05`
- `teams[].groups[].monthly_actuals`: FY27 现金/工单数组
- `teams[].groups[].prior_monthly_actuals`: FY26 对应现金/工单数组
- `teams[].groups[].quarter_targets`、`annual_targets`
- `teams[].people[].monthly_actuals`: 绩效月数组
- `teams[]` 包含 `market_total` 合计团队，`market_total.people` 为空；`dashboard.drilldowns` 提供现金/工单的渠道、年级和高中/大学学校→年级聚合。
- `teams[].people[]` 可包含 `business_group`、`monthly_targets` 和 `monthly_drilldowns`；人员页面按业务团队筛选，`vacant` 占位不进入 artifact，现金与工单均支持工单维度的一级/二级渠道下钻。现金渠道来自 `工单ID` 左连接工单表，未匹配时为“暂无归属”。
- 顶部现金、工单汇总卡片显示当期、同期、同比、目标和完成率。

渲染器只接受当前结构；旧 `metrics`、`prior_totals`、`bus_monthly` 结构不再兼容。Q1 是 FY27 的 2026-06 至 2026-08，FY26 同比取 2025-06 至 2025-08。

## 业务口径

现金和工单独立计算。现金筛选 `渠道属性=被动`、`新老生类型=新生`、`报入现金收入>0`；现金通过 `工单ID` 左连接工单表，关联时采用工单业务组、一级/二级渠道和资源录入人，未关联时回退现金表团队，并在渠道维度显示 `暂无归属`。团队归属仍按“工单匹配→虚拟人→线上→TMK→校代→默认线上平台”顺序处理。

个人归属口径：先以工单的市场团队和业务组筛选人员，再以活动名称中的人员姓名归属。活动名称含“校代”且未命中人员姓名时，才使用资源描述中「市场人员：」（允许值携带如 `-校代`、`-渠道` 后缀）匹配同一业务组人员；现金经工单 ID 继承相同归属。未归属个人的记录保留在团队统计，不计入个人。

看板当前以 `dashboard_actuals/v6` 的实际 SQL 行为为准；正式 Bridge 为 `artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json`，但刷新不直接执行 Bridge 的现金业务组 Override。可复用逐笔底稿为 `attributed_passive_reported_cash/v1`。Saved Query 不再把确认时的 Snapshot 写成运行时绑定。

## 发布与钉钉

生产发布是四分册静态 HTML + Nginx basic auth，不是单文件 `current.html`。刷新、计算、Snapshot 更新和发布准备在云电脑或本机完成；服务器只保存分册 HTML 和钉钉匿名素材。完整流程见 [`DEPLOYMENT.md`](../DEPLOYMENT.md)，分册门口见 [`AUTH_TEAM_BOOKLETS_RUN.md`](AUTH_TEAM_BOOKLETS_RUN.md)。

钉钉五通道：`online_private`、`online_platform`、`offline_youth`、`offline_high_school`、`offline_university`。截图来自本地 HTML，不上看板网址截；不发市场总计，不贴看板页链接。Webhook 只在 `.env.server`。日更不自动群发。2026-09-09 本机已填线下青少/高中 webhook；线上私域、线上平台、线下大学仍空，缺密钥的通道会被跳过。

公开入口为 `http://dashboard.apinova.cn`。例行日更 10:00 Asia/Shanghai 挂许家印。本轮未上 TLS。

## 验收与限制

2026-09-05 已完成核心看板和 FY26/FY27 Q1 对账基线：留学预备 FY27 `2,184,474.60` 元、FY26 `2,145,863.30` 元；高中 FY27 `1,465,735.50` 元；大学 FY27 `4,988,473.20` 元、FY26 数仓 `4,699,695.10` 元。大学差异 `6,979.90` 元，业务方确认可接受。当前工作区已切换到 `snapshot_bi_operations_20260908`；任何新发布都必须从该当前 Snapshot 重新生成 artifact。

未关联工单的现金仍保留在总量中，并仅在渠道维度标记为 `暂无归属`；负向现金不自动解释为退款。

## 验证

```bash
cd "/Users/akechi/Desktop/manager -CowH"
python3 -m unittest discover -s dashboard_product/tests -v
python3 -m interfaces.company_bridge validate \
  --bridge artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
```
