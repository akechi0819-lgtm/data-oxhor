# 留学线下市场看板交接

> **历史材料（2026-10-02 归档）**：本文中的旧 Snapshot、排期和影子入口仅代表当时状态，不作为当前操作指引。现行看板说明见 [模块 README](../../../dashboard_product/README.md) 与 [部署说明](../../../dashboard_product/DEPLOYMENT.md)；管理共同结果见 [management README](../../../dashboard_product/management/README.md)。

更新时间：2026-09-21
工作区：`customers/bi_operations`
当前 Snapshot：`snapshot_bi_operations_20260920`
正式口径：Company Bridge `bridge_bi_operations` **v1.6.0**
当前指针：`customers/bi_operations/Work/Bridge/reference.json`
归档：`customers/bi_operations/Output/Bridge/1.6.0/`
v1.5.0 只归档，不保留运行兼容。

本文件给下一个看板线程用。口径已锁定。下一步先对齐需求和版式，再写影子数仓、查询和页面。不要改 Pack、V14 主看板 SQL、监控或线上特供页计算。

## 1. 要做什么

做一份**留学线下市场团队特供看板**，对标现有留学线上看板，不并进 V14 主页面的「线下市场」页签。

| 现有产品 | 是什么 | 和本轮关系 |
|---|---|---|
| V14 `full.html` 的「线下市场」 | 语培线下市场（留学预备/高中/大学） | **不要改** |
| `online_market_special.html` | 留学线上特供，影子数仓 | 本轮参照对象 |
| 本轮新页 | 留学线下市场特供 | 独立影子链路 + 独立 HTML |

线上看板链路（只作参照，不要改计算）：

```text
online_market_shadow
  → Work/ShadowOnlineMarket/<run_id>/（不写回 workspace.json 当前 Snapshot）
  → online_market_refresh（saved query: online_market_orders/v1）
  → online_market_render → online_market_special.html
```

本轮应对齐同一模式，另开影子根目录（建议 `Work/ShadowOfflineMarket/`），不要复用线上影子目录，也不要更新 `Work/workspace.json` 的 `current_snapshot_id`。

## 2. 口径已经锁定，不要再猜

权威位置是 Bridge v1.6.0，不是 CRM 现成渠道列，也不是 Excel 线下 1449。

底稿（窗口观察数，**不要写进 Bridge / 不要写进看板 SQL**）：

- `customers/bi_operations/Work/Runs/run_offline_channel_mapping_20260921/unified_market_mapping.md`
- `customers/bi_operations/Work/Runs/run_offline_channel_mapping_20260921/mapping_draft.md`

决策记录：`DEVELOPMENT.md`「2026-09-21：留学线渠道口径写入 Bridge v1.6.0」。

### 2.1 判定顺序

1. 留学：`团队` 为空，且 `ID` 有效。
2. 线上/线下：`咨询方式一级渠道` 第一个 `-` 前的根节点。
3. L1 / L2：按下表。不要用 CRM `一级渠道` / `二级渠道`，不要把线上参考表 `矫正-渠道` 套到线下。

### 2.2 留学线市场部门映射

| 根节点 | 线 | L1 | L2 | 渠道看板 | 市场核算 |
|---|---|---|---|---|---|
| 网络资源 / 新媒体 | 线上 | 根节点 | `咨询方式一级渠道` × `渠道` → 参考表众数 `矫正-渠道`；`新媒体-其他` → SSC；未命中不兜底 | 只取 `资源主被动=被动` | 不走本轮线下边界 |
| 线上运营 / 网络 | 线上 | **网络资源** | 同上 | 同上 | 同上 |
| 市场活动 | 线下 | 市场活动；仅 `市场活动-高校/个人代理` 跨到渠道合作 | 高校活动 / 中学活动 / 地推 / 综合展 / 其他；`市场活动/市场活动` 归高校活动 | 只取被动 | 与看板同一边界 |
| 官方合作高校 | 线下 | 官方合作高校 | **官方合作高校**（同名，不按 `渠道` 再拆） | 只取被动 | 同左 |
| 渠道合作 | 线下 | 渠道合作 | 个人渠道；**对公渠道（三方）** = 分公司对公合作 + 留学监理网整类；异业合作 → 其他。个人代理不并进三方 | 只取被动 | 同左 |
| 新东方学校推荐 | 线下 | 新东方学校推荐 | 部门（国外考试部 / 大学事业部 / 大客服 / 高中部 / 青少部 / 国游营地 / 其他推荐） | **只收市场推荐子集** | **同一子集，不再另切** |
| 校代 / 合作 | 线下其他 | 其他 | 线下校代 / 大学事业部合作 | 不进 | 不进 |
| 口碑 / 电话 / 上门 / 转介绍 / 内部推荐 / 离境客户 等 | 非本市场部门 | — | — | 不进 | 不进 |

综合展并入：综合展、信息收集、现场注册、条线专展、部门展、F活动邀约。  
对公整类里学管续费 / TMK 错填仍留在对公渠道（三方），只作数据质量脚注。

### 2.3 新东方市场推荐（「市场投入 / 小边界」就是这道门）

不是另切一刀。`新东方学校推荐` 下，只有判定为市场推荐的点对点，才算线下市场贡献，才进渠道看板和后续市场核算。其余不进看板、不算市场。L1/L2 仍挂 `新东方学校推荐 / 部门`，不改挂市场活动。

前提：`渠道 = 点对点`。批量推送 / 批量导入 / 取消一律排除。点对点默认非市场。

优先级（命中即停）：

1. 强信号：原 CRM `一级渠道` = 市场活动，或活动名/资源描述含「市场人员 /【市场活动】/【市场人员】/ 市场双分」
2. 讲座 / 展会 / 问卷 / 会销
3. 确认人员 haystack（活动名 + 资源描述 + 资源录入人 + 其他转介绍人）命中：邓睿 / 杨芸聿 / 孙伟 / 王洪霞 / 吴子玄

未扩入：王衡利、马永鋆。不要用花名册子串当正规则。

当前窗口观察数（清洗未改前，只作底稿）：线下被动合法三类约 655；新东方市场推荐 71。渠道看板大约是这两块，**不是** Excel 线下 1449，也**不是**新东方 790 全量。

## 3. 现有清洗还没接到这套口径

`data_acquisition/jobs/work_order_cleaning.py` 仍是 2026-09-20 线上交接范围：

- 只清洗根节点 `网络资源` / `新媒体`
- `渠道合作` / `市场活动` 标「线下范围外」，不改原值
- **没有**实现：官方合作高校、新东方市场推荐、`线上运营`/`网络` 别名、线下 L2 overlay

线上影子看板目前吃的就是这套清洗后的 `一级渠道` / `二级渠道`。  
线下看板**不能**直接复用那两列，也不能复用 `矫正-渠道`。

实现时二选一，先和用户对齐，不要偷偷改主仓清洗：

1. **推荐**：影子数仓专用清洗 / saved query 按 Bridge v1.6.0 现算 L1/L2，主仓 `work_order_cleaning.py` 先不动。
2. 若必须改主仓清洗，另立项，且不得破坏线上已清洗字段。

Bridge 只存映射判断，不存 SQL、窗口计数或工单样例。该板块调用频率不高；接到看板时直接用 v1.6.0，不要给 v1.5.0 做兼容层。

## 4. 线上看板可复用什么

参照这些文件，复制模式而不是复制渠道枚举：

- `dashboard_product/online_market_shadow.py`
- `dashboard_product/online_market_refresh.py`
- `dashboard_product/online_market_render.py`
- `dashboard_product/config/online_market_queries/online_market_orders/v1/query.sql`
- `dashboard_product/config/online_market_targets.json`
- `dashboard_product/tests/test_online_market.py`
- `dashboard_product/deploy/publish_online_market_dashboard.sh`

线上看板已定行为（线下默认对齐，有差异先问）：

- 范围：有效 `ID` + `团队` 空 + 合法根节点 + `资源主被动=被动`
- 清洗后的 `主被动` 只作审计
- 现金目标可配置，现金实际显示「待接入」
- 月度目标未配时写「月度目标待确认」，不要编数字
- 未命中二级渠道不兜底成前途推荐 / 平台 / 其他
- 影子 Snapshot 不写回当前工作区指针
- 公网只托管 HTML，不上传 warehouse / artifact
- 国家、条线是独立维度，不从渠道名反推

线下和线上的结构差异，必须在版式里单独处理：

- 线上 L1 只有网络资源 / 新媒体；L2 是平台（小红书、大众、SSC…）
- 线下 L1 是市场活动 / 官方合作高校 / 渠道合作 / 新东方学校推荐
- 线下 L2 是活动类型、同名高校、个人/对公三方、新东方部门
- 新东方有「是否市场推荐」这道门，线上没有对应物

## 5. 本轮先对齐、后实现

新线程**第一件事不是写代码**。先和用户确认下面这些，再开工：

1. 页面定位：独立特供 HTML，还是线上特供里加「留学线下」页签？
2. 筛选：L1 四类是否都做切换？新东方是否单独开关？
3. 目标：有没有线下工单/毛签目标？按 L1 还是 L2？没有就显式「未配置」。
4. 现金：是否先和线上一样「待接入」？
5. 国家/条线：线下要不要同样下钻？
6. 新东方：看板里只出现市场推荐 71 这一路，还是另外给审计入口看被排除的点对点？（默认：不进看板、不做审计页）
7. 发布：是否新文件（如 `offline_market_special.html`），主页面如何入口，是否动 nginx / 发布脚本。
8. 实现落点：影子专用查询 vs 改主仓清洗。

未确认前不要改 `dashboard_actuals/v14`、`people.json`、监控 SQL、线上 `online_market_orders/v1`。

## 6. 不要做的事

- 不要把 V14「线下市场」改成留学渠道看板
- 不要用 Excel 归类团队=线下的 1449 当看板范围
- 不要把新东方 790 全量进看板或进市场核算
- 不要把个人代理并进对公渠道（三方）
- 不要把校代 / 合作算进合法市场渠道
- 不要用花名册人名子串当新东方正规则，也不要扩入王衡利、马永鋆
- 不要把线上 `矫正-渠道` 映射到线下路径（参考表会把线下路径矫正成百度/抖音/大众）
- 不要保存 Casebook、不要改 Pack、不要 wizard finalize
- 不要给 Bridge v1.5.0 加兼容层

## 7. 启动时必读

- `dashboard_product/README.md`
- `docs/history/dashboard/DASHBOARD_DEVELOPMENT_PREREQUISITES.md`
- `agents/dashboard_publisher/AGENT.md`
- 本文件
- `customers/bi_operations/Work/Runs/run_offline_channel_mapping_20260921/unified_market_mapping.md`
- Bridge：`customers/bi_operations/Work/Bridge/reference.json` 中
  `cand_override_study_abroad_channel_scope`
  `cand_override_newdongfang_market_contribution`
  以及 8 条 `cand_norm_*` 留学规则

启动提示词：`docs/history/dashboard/LIUXUE_OFFLINE_MARKET_START_PROMPT_20260921.md`
