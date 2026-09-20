> 历史存档：原路径 `dashboard_product/docs/HANDOFF.md`，于 2026-09-18 目录整理时归档。以下状态、命令、版本与凭据配置描述仅代表记录当时，不是当前操作入口。当前项目状态见 [DEVELOPMENT.md](../../../DEVELOPMENT.md)；看板现行操作见 [DEPLOYMENT.md](../../../dashboard_product/DEPLOYMENT.md)。

# 看板交接

> 2026-09-16 模块切换：人员进度与钉钉推送已迁至 `monitoring_product/`，看板不再承担发送。新入口要求 workspace、snapshot-id、run-id、as-of-date、data-through-date；正式发送另需显式 env-file。共享花名册在 `workspace_modeling/operations/people.json`。本地迁移完成不代表云端任务已切换；详见项目根目录 `monitoring_product/README.md`。

更新时间：2026-09-14

## 产品边界

`dashboard_product` 是静态看板生成器。它不直接访问 DuckDB，不修改 Bridge，不依赖 `latest` 指针；所有事实来自当前工作区 Snapshot 的 Data Platform Saved Query 结果。

当前看板四个团队页签为线下市场、线上私域（虚拟人）、线上平台和市场总计，并并列第五页「市场人员产能」。线下市场团队个性化配置已完成；线上私域已有部分人员，线上平台仍待完成个性化配置。人员配置中的 `pending`、`probation` 和 `vacant` 是编制状态，不改变上述团队配置完成度。

## 运行合同

从 `/Users/akechi/Desktop/manager -CowH` 执行：

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/bi_operations --run-id run_dashboard_<id>
python3 -m dashboard_product.refresh render --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json --all-booklets
python3 -m monitoring_product.notify send --workspace <workspace> --snapshot-id <snapshot_id> --run-id <run_id> --as-of-date <YYYY-MM-DD> --data-through-date <YYYY-MM-DD> --dry-run
```

刷新读取 `customers/bi_operations/Work/workspace.json` 的 `current_snapshot_id`，调用 `dashboard_actuals/v10` 两次：当前窗口和上一财年对应窗口。输出写入 `customers/bi_operations/Output/Dashboard/<run_id>/`。云电脑等价根目录是 `/home/box/oxhor/dashboard`，customers 软链到 warehouse。

## Artifact 合同

顶层字段：`schema_version`、`artifact_id`、`run_id`、`snapshot_id`、`created_at`、`query_results`、`errors`、`dashboard`。

`dashboard` 至少包含：

- `months`: `2026-06` 至 `2027-05`
- `prior_months`: `2025-06` 至 `2026-05`
- `teams[].groups[]`: 目标区留学预备/高中/大学，含 `monthly_actuals`、`prior_monthly_actuals`、`quarter_targets`、`annual_targets`
- `teams[].yoy_groups[]`: 同比区青少/初中/高中/大学，只含当期和去年同期月数组，不含目标
- `teams[].people[].monthly_actuals`: 绩效月数组
- `teams[]` 包含 `market_total` 合计团队，`market_total.people` 为空；`teams[].yoy_groups` 是青少/初中/高中/大学四组同比；`dashboard.drilldowns` 的业务组键是这四组，不是留学预备。
- `teams[].people[]` 可包含 `business_group`、`monthly_targets`、`monthly_drilldowns`、`heads_actual`、`annual_cash_capacity`、`line` 和 `cash_contributions`；人员页面按业务团队筛选，`vacant` 占位不进入 artifact，现金与工单均支持工单维度的一级/二级渠道下钻。现金渠道来自 `工单ID` 左连接工单表，未匹配时标记为“渠道/顾问暂无法拆分”。产能页用全年现金对照 80 万标准产能，六维为工单数、签约量、转化率、渠道&校代、TMK、活动贡献；均值按团队算，线下留学预备/高中/大学分开，线上私域整队一个均值。
- 顶部现金、工单汇总卡片显示当期、同期、同比、目标和完成率。
- 渲染器在业务组同期对比下增加渠道同期对比：用现有 `drilldowns` 按二级渠道透视青少/初中/高中/大学；组内现金占比仍是该渠道内该业务组份额。右侧合计该渠道全部现金、工单及占总现金占比，按合计现金降序，底行总计。市场总计目标表可展开业务组，下钻三个团队并显示该组内现金/工单占比。

渲染器只接受当前结构；旧 `metrics`、`prior_totals`、`bus_monthly` 结构不再兼容。刷新产物必须带 `teams[].yoy_groups`，渲染器不会给旧 artifact 补四个空年段。Q1 是 FY27 的 2026-06 至 2026-08，FY26 同比取 2025-06 至 2025-08。

## 业务口径

现金和工单独立计算。现金筛选 `渠道属性=被动`、`新老生类型=新生`、`报入现金收入>0`。现金业务组只看现金表 `团队`（青少/初中滚留学预备，ICC/国际学科进高中），不跟工单业务组改口。工单 ID 左连接只取渠道和人员；连不上时保留市场总计，渠道标记为 `渠道/顾问暂无法拆分`，不再默认归入线上平台。

个人归属口径：先以工单的市场团队和业务组筛选人员。活动名含花名册姓名时用活动名；否则依次用资源描述「市场人员：」、「姓名市场资源」、资源录入人、去掉 `YYYY.MM.DD-` 旧活动串后的资源描述正文。现金用工单 ID 对全量工单数仓连，不限本绩效月；连上且业务组明确时继承该工单归属，连不上不据现金表活动名恢复旧团队兜底。未归属个人的记录保留在团队统计，不计入个人。无法明确业务组的有效被动工单保留在市场总计，标记为“业务组暂无法拆分”，不进入项目、团队或人员；跟进顾问为张艺彤时按留学预备回落，再按年级校正拆青少/初中。临时补丁：`TMK激活-平台` 且活动名含 `校代系统资源`、市场人员为线下花名册成员时，先把 team_id 从线上平台改回线下市场，再按原规则匹配个人。

看板当前以 `dashboard_actuals/v10` 的实际 SQL 行为为准；正式 Bridge 为 `artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json`，但刷新不直接执行 Bridge 的现金业务组 Override。可复用逐笔底稿为 `attributed_passive_reported_cash/v1`。Saved Query 不再把确认时的 Snapshot 写成运行时绑定。

## 发布与钉钉

生产发布是四分册静态 HTML + Nginx basic auth，不是单文件 `current.html`。刷新、计算、Snapshot 更新和发布准备在云电脑或本机完成；服务器只保存分册 HTML 和钉钉匿名素材。完整流程见 [`DEPLOYMENT.md`](../../../dashboard_product/DEPLOYMENT.md)，分册门口见 [`AUTH_TEAM_BOOKLETS_RUN.md`](AUTH_TEAM_BOOKLETS_RUN.md)。

钉钉五通道：`online_private`、`online_platform`、`offline_youth`、`offline_high_school`、`offline_university`。截图来自本地 HTML，不上看板网址截；不发市场总计，不贴看板页链接。Webhook 只在 `.env.server`。日更不自动群发。本机已填线下青少/高中/大学和线上私域 webhook；线上平台仍空，缺密钥的通道会被跳过。线下大学播报图第二列是人头不是现金，落后仍按工单；明细表人员进度另带现金目标/完成。钉钉花名册以 `people.json` 为准：线上私域小初提能组为潘体学（工单 25、现金 50,000），不再保留杨玉林。

公开入口为 `http://dashboard.apinova.cn`。例行日更 10:00 Asia/Shanghai 挂许家印。本轮未上 TLS。

## 验收与限制

2026-09-05 已完成核心看板和 FY26/FY27 Q1 对账基线：留学预备 FY27 `2,184,474.60` 元、FY26 `2,145,863.30` 元；高中 FY27 `1,465,735.50` 元；大学 FY27 `4,988,473.20` 元、FY26 数仓 `4,699,695.10` 元。大学差异 `6,979.90` 元，业务方确认可接受。当前工作区 Snapshot 以 `customers/bi_operations/Work/workspace.json` 为准（本机 2026-09-11 为 `snapshot_bi_operations_20260911_r2`）；任何新发布都必须从该当前 Snapshot 重新生成 artifact。

未关联工单的现金仍保留在市场总量中，渠道标记为 `渠道/顾问暂无法拆分`，不默认分配团队或人员；负向现金不自动解释为退款。

## 验证

```bash
cd "/Users/akechi/Desktop/manager -CowH"
python3 -m unittest discover -s dashboard_product/tests -v
python3 -m interfaces.company_bridge validate \
  --bridge artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
```
