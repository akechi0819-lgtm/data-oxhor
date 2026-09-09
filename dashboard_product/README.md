# Dashboard Product

独立的静态看板生成器。它读取已确认工作区的当前 Snapshot，通过 Data Platform 的受控 Saved Query 生成不可变 `artifact.json`，再从该 artifact 渲染 `artifact.html`。看板不直接连接 DuckDB，不读取 `latest` 指针，也不修改 Bridge。

## 运行

在项目父目录执行：

```bash
cd "/Users/akechi/Desktop/manager -CowH"
python3 -m dashboard_product.refresh refresh \
  --workspace customers/bi_operations \
  --run-id run_dashboard_<yyyymmdd>
python3 -m dashboard_product.refresh render \
  --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<yyyymmdd>/artifact.json \
  --all-booklets
python3 -m dashboard_product.notify send \
  --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<yyyymmdd>/artifact.json \
  --dry-run
```

输出目录为 `customers/bi_operations/Output/Dashboard/<run_id>/`，包含全量 `artifact.json`（**不发布**）和四分册 `full.html` / `online_private.html` / `online_platform.html` / `offline_market.html`。不带 `--booklet` 时仍写 `artifact.html` 以便兼容。发布脚本见 [`DEPLOYMENT.md`](DEPLOYMENT.md)；分册与 htpasswd 见 [`docs/AUTH_TEAM_BOOKLETS_RUN.md`](docs/AUTH_TEAM_BOOKLETS_RUN.md)。

静态服务器发布、四分册原子替换和 Nginx basic auth 见 [`DEPLOYMENT.md`](DEPLOYMENT.md)。刷新、计算、Snapshot 更新和发布准备全部在本地完成，服务器只托管分册 HTML。


## 分团队钉钉推送

一次读取同一份 `artifact.json`，生成虚拟人、线上平台，以及线下青少/高中/大学共五份人员进度图和明细表，再按各自 webhook 分发。截图来自本地 HTML，不上看板网址截。不发市场总计，不贴看板页链接。`--team` 只用于预览；`--team offline_market` 会展开成线下三个群。

```bash
python3 -m dashboard_product.notify send --artifact <artifact.json> --dry-run
python3 -m dashboard_product.notify send --artifact <artifact.json>
```

`--dry-run` 只写本地 `people.png` / `details.xlsx` / `message.md`，不上传、不调钉钉。正式发送把 png/xlsx 传到 `http://dashboard.apinova.cn/notify/<token>/<team_id>/`，再向 `DINGTALK_WEBHOOK_<TEAM>` 发 markdown。密钥写在 `.env.server`，不要进 Git。日更脚本不自动群发；Nginx 需含 `/notify/` 匿名规则后钉钉才能拉图。

## 配置进度

当前看板包含三个团队：`offline_market`（线下市场）、`online_private`（线上私域/虚拟人团队）和 `online_platform`（线上平台）。线下市场个性化配置已完成；线上私域已有部分人员；线上平台人员配置仍空。`config/people.json` 中的 `pending`、`probation` 和 `vacant` 只表示人员编制状态，不代表线下市场团队配置缺失。钉钉五通道里，线下青少/高中/大学 webhook 已在本机 `.env.server`；线上私域、线上平台仍空。

服务器静态部署提供 `http://dashboard.apinova.cn`（HTTP + basic auth 分册；`/healthz` 匿名）。每日 10:00（Asia/Shanghai）由许家印在云电脑 refresh 一次再渲四分册并上传；服务器不执行数据刷新或计算。本机 Codex 定时已停。本轮若未上 TLS，basic auth 密码会在网上裸奔。

## 当前数据口径

- 现金与工单独立计算。现金关联到工单时采用工单业务组，未关联时按现金表 `团队` 映射：青少→留学预备；初中、初中国际学科、ICC、国际学科→高中；大学→大学。未映射业务组不进入正式看板汇总。
- 现金范围为 `渠道属性=被动`、`新老生类型=新生`、`报入现金收入>0`，按现金明细行保留，不去重。
- 工单只统计被动工单并按工单 `ID` 去重。现金通过 `工单ID` 左连接工单表获取一级、二级渠道；无法关联时渠道显示为 `暂无归属`。
- 未匹配工单的现金按顺序归属：市场活动名含“虚拟人”→线上私域；含“线上”→线上平台；渠道含“TMK”→线下；市场活动名含“校代”→线下；其余→线上平台。兜底归属不等于工单匹配成功。
- 业务组和团队按自然月聚合；人员按每月 26 日至次月 25 日的绩效月聚合。
- 个人工单和现金先按工单业务组筛选，再匹配人员。顺序：活动名含花名册姓名 → 资源描述「市场人员：」→ 资源描述「姓名市场资源」→ 资源录入人 → 去掉旧活动串后的资源描述正文。现金通过工单 ID 继承该归属。高中、大学、留学预备同一套规则。
- 同比按月序列切片：FY27 月序列为 2026-06 至 2027-05，FY26 对应为 2025-06 至 2026-05。选择 Q1 时双方都只取 6-8 月。
- 看板提供市场总计页签；同比支持现金/工单渠道下钻、现金/工单年级下钻和高中、大学学校→年级二级下钻。年级按学龄前、年级序列、高中、大学、研究生顺序展示。

## 配置与来源

`config/project_targets.json` 保存 FY27 目标，`config/people.json` 保存人员组织配置。查询合同见 [`config/saved_queries.json`](config/saved_queries.json)；正式 SQL 位于客户工作区的 Saved Query registry：`dashboard_actuals/v6` 供刷新使用，`attributed_passive_reported_cash/v1` 供逐笔对账和后续分析使用。

当前工作区和 Bridge 由 `customers/bi_operations/Work/workspace.json` 指定；当前 Bridge 为 `company_bridge.bi_operations.v1_2_0.json`。

## 验收状态

2026-09-05 已完成核心展示与筛选的验收基线：Q1 对账结果为留学预备 FY27 `2,184,474.60` 元、FY26 `2,145,863.30` 元；高中 FY27 `1,465,735.50` 元；大学 FY27 `4,988,473.20` 元、FY26 数仓 `4,699,695.10` 元。大学 FY26 与线上看板差异 `6,979.90` 元，业务方确认可接受。当前工作区已切换到 `snapshot_bi_operations_20260908`；新快照的数值以其新生成 artifact 为准。

详细状态见 [`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md) 和 [`docs/HANDOFF.md`](docs/HANDOFF.md)。
