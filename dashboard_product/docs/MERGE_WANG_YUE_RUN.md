# RUN: 合并虚拟人重复「王玥」后刷新真发（2026-09-08）

## 改了什么
花名册已由前序施工完成，本 RUN **未再改** `people.json`。
- `online_private` / `wang_yue`（王玥）只保留在「高中多途径组」
- 「国际学校择校组」members 为空
- 备份：`workspace_modeling/operations/people.json.bak-wangyue-20260908`
- 未改口径公式

## 单测
`python3 -m unittest dashboard_product.tests.test_render dashboard_product.tests.test_booklets -v` → 16 tests OK

## refresh
- run_id：`run_dashboard_20260908_merge_wangyue`
- snapshot：`snapshot_bi_operations_20260908`
- as_of：2026-09-08（data_through 2026-09-07）
- artifact：`customers/bi_operations/Output/Dashboard/run_dashboard_20260908_merge_wangyue/artifact.json`

## 验收
`online_private.people` 中 `display_name=王玥` **恰好 1 次**（全看板 people 合计也是 1）。
- group_name：高中多途径组（business_group：高中）
- orders_actual：7
- cash_actual：122180
- `online_private.html` 源码「王玥」亦 1 次

## 真发
是。`ARTIFACT_JSON=.../run_dashboard_20260908_merge_wangyue/artifact.json ./dashboard_product/deploy/publish_static_dashboard.sh` **exit 0**
四分册已发：full / online_private / online_platform / offline_market（2026-09-08T09:32:12+00:00）
