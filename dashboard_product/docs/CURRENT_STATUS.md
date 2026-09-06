# 当前状态

更新时间：2026-09-06

## 已完成

- FY27 看板展示、团队/业务组/人员筛选和本地季度切换已完成。
- 当前工作区 Snapshot 为 `snapshot_bi_operations_20260906`；2026-09-05 的 Q1 对账结论是已验收基线，后续发布以当前 Snapshot 新生成的 artifact 为准。
- 三个团队已纳入看板：线下市场、线上私域（虚拟人团队）、线上平台；线下市场团队的个性化配置已完成。
- 刷新链路已固定为 `refresh` 生成 artifact、`render` 生成 HTML；输出文件为 `artifact.json` 与 `artifact.html`。
- 现金关联到工单时采用工单业务组，未关联时回退现金表团队；现金通过工单 ID 左连接工单表获取渠道，口径包含被动、新生、正向报入现金。
- 未关联工单的现金统一在渠道维度显示为 `暂无归属`；团队归属规则已固化为：工单匹配、虚拟人、线上、TMK、校代、默认线上平台。
- 线下市场个人统计已按工单业务组隔离后再匹配人员；校代系统资源在活动名未携带人员时使用工单 `资源录入人` 归属，现金通过工单 ID 继承该归属。
- `market_total` 汇总三个团队且不包含人员；同比支持渠道、年级和高中/大学学校→年级下钻，年级按固定学龄顺序排序。
- 顶部现金和工单汇总卡片均显示当期、同期、同比、目标和完成率。
- 人员区支持留学预备/高中/大学业务团队筛选；状态列已移除，空白占位保留在配置但不展示。个人工单与现金均可按工单维度的一级、二级渠道下钻；现金先按 `工单ID` 左连接工单表，未匹配现金显示“暂无归属”。个人月度目标写入人员配置，高中现金目标允许为空，大学人头目标按 13,000 元/人头折算现金目标。
- FY26/FY27 Q1 对账已完成。留学预备差异约 24,400 元、大学线上看板差异约 6,980 元，业务方均确认可接受。
- 服务器静态部署已完成。刷新、计算、Snapshot 更新和发布准备在本地执行，服务器仅托管最终 HTML；Codex 唯一自动化每天 10:00（Asia/Shanghai）发布全量看板。公开入口为 `http://dashboard.apinova.cn`，目前按内部使用需求提供 HTTP。

## 个性化配置进度

- 已完成：`offline_market`（线下市场）。配置文件中的 `pending`、`probation` 和 `vacant` 仅表示人员编制状态，不是团队配置缺口。
- 待完成：`online_private`（线上私域/虚拟人团队）、`online_platform`（线上平台）。

## 当前合同

刷新必须在父目录执行：

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/bi_operations --run-id run_dashboard_<id>
python3 -m dashboard_product.refresh render --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json
```

`dashboard_actuals/v6` 是刷新唯一消费的 Saved Query，参数为 `[start_date, end_date]`。`attributed_passive_reported_cash/v1` 是逐笔对账底稿，不被刷新自动调用。

artifact 的业务组字段包括 `monthly_actuals`（FY27 12 个月）和 `prior_monthly_actuals`（FY26 对应 12 个月）；同比渲染按所选季度切同一索引段。旧的 `prior_totals`、`metrics` 和 `bus_monthly` 结构已废弃。

## 已知边界

- 未映射业务组不进入正式看板汇总；若底层快照重新出现此类记录，需先完成 Bridge 对齐。
- 团队兜底归属是业务分配，不代表工单关联成功。
- 生产发布使用 `deploy/publish_static_dashboard.sh`，由 Codex 自动化调用。
- 负向现金仍按数据事实保留为负向现金，原因需业务确认。

## 关键路径

- 代码：`refresh.py`、`render_template.py`
- 配置：`config/project_targets.json`、`config/people.json`、`config/saved_queries.json`
- 已验收看板基线：`customers/bi_operations/Output/Dashboard/run_dashboard_newstudent_final_20260905/`
- 当前 Bridge：`artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json`
