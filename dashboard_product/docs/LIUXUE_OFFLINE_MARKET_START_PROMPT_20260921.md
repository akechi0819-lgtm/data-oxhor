# 留学线下市场看板 · 新线程启动提示词

把下面「可粘贴正文」原样贴到新线程。本文件只是备份，不要当运行入口改口径。

---

## 可粘贴正文

你在 Data OXHor 仓库 `/Users/akechi/Desktop/manager -CowH` 工作。本线程只做 **dashboard_product：留学线下市场团队特供看板**。先读交接，再和我对齐需求与版式；未确认前不要写清洗、SQL、HTML 或发布脚本。

先读：

1. `AGENTS.md`
2. `dashboard_product/README.md`
3. `dashboard_product/DASHBOARD_DEVELOPMENT_PREREQUISITES.md`
4. `agents/dashboard_publisher/AGENT.md`
5. `dashboard_product/docs/LIUXUE_OFFLINE_MARKET_HANDOFF_20260921.md`（本轮主交接）
6. `customers/bi_operations/Work/Runs/run_offline_channel_mapping_20260921/unified_market_mapping.md`

口径已经锁定在 Company Bridge `bridge_bi_operations` **v1.6.0**：

- 当前指针：`customers/bi_operations/Work/Bridge/reference.json`
- 归档：`customers/bi_operations/Output/Bridge/1.6.0/`
- v1.5.0 只归档，不要做兼容层或回退

工作区：`customers/bi_operations`  
当前 Snapshot：`snapshot_bi_operations_20260920`  
不要更新 `Work/workspace.json` 的当前 Snapshot。

### 产品边界

- 做留学线下市场特供看板，对标 `online_market_special.html` 的影子数仓模式。
- **不要改** V12 主页面 `full.html` 里的「线下市场」页签；那是语培线下市场，不是留学渠道看板。
- **不要改** Pack、监控、`dashboard_actuals/v12`、线上 `online_market_orders/v1` 的计算。
- 现有 `work_order_cleaning.py` 只清洗线上 `网络资源`/`新媒体`；线下映射还没进清洗。本轮默认在影子链路里按 Bridge 现算，不要偷偷改主仓。

### 已锁定口径（不要再猜，不要再让我逐条核 1449）

留学 = `团队` 空 + 有效 `ID`。  
线上/线下和 L1 根节点 = `咨询方式一级渠道` 第一个 `-` 前的 token。  
不要用 CRM `一级渠道`/`二级渠道` 当看板 L1/L2。不要把线上参考表 `矫正-渠道` 套到线下。

线下渠道看板范围：

- 被动合法三类：市场活动、官方合作高校、渠道合作
- 加上 `新东方学校推荐` 的**市场推荐子集**
- 校代 / 合作 / 口碑 / 电话 / 上门 / 转介绍等不进

L2 规则：

- 官方合作高校：L2 同名
- 市场活动：高校活动 / 中学活动 / 地推 / 综合展 / 其他；`市场活动/市场活动` 归高校活动；`市场活动-高校/个人代理` 跨到渠道合作/个人渠道
- 渠道合作：个人渠道；分公司对公合作 + 留学监理网 **整类** → 对公渠道（三方）；个人代理不要并进三方
- 新东方：L2 按部门；点对点默认非市场；批量推送/导入/取消排除；只有强信号 / 讲座展会问卷 / 确认人员（邓睿、杨芸聿、孙伟、王洪霞、吴子玄）才算市场推荐，才进看板和市场核算。未扩入王衡利、马永鋆。这就是「新东方市场投入 / 小边界」，不再另切一刀。L1/L2 仍挂新东方/部门。

窗口观察数只作底稿：被动合法三类约 655 + 新东方市场推荐 71。不是 1449，也不是新东方 790 全量。

### 本线程第一回合必须做的事

用中文简短回复，只对齐需求，不写代码：

1. 用自己的话复述看板范围和 L1/L2，确认你不会动 V12 线下市场页。
2. 列出需要我拍板的版式/需求问题（建议覆盖：独立 HTML 还是线上特供加页签、L1 筛选、目标有无、现金是否待接入、国家/条线要不要、新东方被排除的点对点是否露审计入口、发布文件名）。
3. 给出你建议的默认版式（尽量靠近线上看板：目标带、L1 切换、L2 进度、可选国家/条线），并标明和线上不同的地方。

确认之前不要创建文件、不要改 SQL、不要发布。
