> 历史存档：原路径 `dashboard_product/docs/WANG_YUE_TARGETS_202609_RUN.md`，于 2026-09-18 目录整理时归档。以下状态、命令、版本与凭据配置描述仅代表记录当时，不是当前操作入口。当前项目状态见 [DEVELOPMENT.md](../../archive/DEVELOPMENT-history-202611.md)；看板现行操作见 [DEPLOYMENT.md](../../../dashboard_product/DEPLOYMENT.md)。

# RUN: 王玥 2026-09 目标写入后 refresh 真发（2026-09-09）

## 改了什么
花名册已由前序施工完成，本 RUN **未再改** `people.json`。
- `online_private` / `wang_yue`（高中多途径组）`monthly_targets["2026-09"]` = `{orders: 15, cash: 30000}`
- 备份：`workspace_modeling/operations/people.json.bak-wangyue-targets-20260909`
- 未改口径公式、未动其他人

## 单测
`python3 -m unittest dashboard_product.tests.test_render dashboard_product.tests.test_booklets -v` → 16 tests OK

## refresh
- run_id：`run_dashboard_20260909_wangyue_targets`
- snapshot：`snapshot_bi_operations_20260909`
- as_of：2026-09-09（data_through 2026-09-08）
- artifact：`customers/bi_operations/Output/Dashboard/run_dashboard_20260909_wangyue_targets/artifact.json`

## 验收
`online_private.people` 中 `display_name=王玥` **恰好 1 次**（全看板 people 合计也是 1）。
- group_name：高中多途径组（business_group：高中）
- monthly_targets 2026-09：orders=15，cash=30000
- orders_actual：7
- cash_actual：122180
- `online_private.html` 源码「王玥」亦 1 次，嵌入目标同样是 15 / 30000

## 真发
是。`ARTIFACT_JSON=.../run_dashboard_20260909_wangyue_targets/artifact.json ./dashboard_product/deploy/publish_static_dashboard.sh` **exit 0**
四分册已发：full / online_private / online_platform / offline_market（2026-09-09T03:42:13+00:00）
