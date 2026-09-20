# 留学线上工单清洗 → 看板开发交接

更新时间：2026-09-20
当前 Snapshot：`snapshot_bi_operations_20260920`
当前 Bridge：`bridge_bi_operations` v1.5.0
当前 Snapshot 未因本次交接文档或对照表生成而改写。

## 1. 本轮目标

将团队字段为空的留学工单在入仓前做外挂清洗，让看板可以使用与语培一致的 `主被动` 计算口径，并使用标准一级、二级渠道；国家和条线作为独立维度保留。

本轮看板开发只接入线上留学工单。线下留学暂不清洗。

## 2. 清洗范围

目标行同时满足：

1. 有有效工单 `ID`；
2. 原始 `团队` 为空；
3. `咨询方式一级渠道` 的根节点为 `网络资源` 或 `新媒体`。

以下范围暂不进入本轮清洗：

- 根节点为 `渠道合作` 或 `市场活动` 的线下留学工单；标记为封存，不改原始字段；
- 根节点为其他值或为空的留学工单；标记为当前规则未命中；
- `团队` 已有值的语培工单；保持原值。

## 3. 入仓外挂脚本

脚本：[data_acquisition/jobs/work_order_cleaning.py](/Users/akechi/Desktop/manager -CowH/data_acquisition/jobs/work_order_cleaning.py)

接入点：[data_acquisition/jobs/bi_window_merge.py](/Users/akechi/Desktop/manager -CowH/data_acquisition/jobs/bi_window_merge.py) 以及 [data_acquisition/jobs/rebuild_bi_warehouse.py](/Users/akechi/Desktop/manager -CowH/data_acquisition/jobs/rebuild_bi_warehouse.py)。

独立运行方式：

```bash
python3 -m data_acquisition.jobs.work_order_cleaning \
  --input <merged_orders.xlsx> \
  --output <cleaned_orders.xlsx> \
  --mapping customers/bi_operations/Input/Reference/留学-FY26-资源表.xlsx
```

标准刷新流程会自动读取：

`customers/bi_operations/Input/Reference/留学-FY26-资源表.xlsx`

## 4. 字段口径

### 4.1 渠道

- `咨询方式一级渠道` 是源路径语义，例如 `网络资源-店铺类`、`新媒体-欧亚总部在线`；
- 参考表的 `一级获取渠道` 写入工单数仓的 `一级渠道`；
- `渠道` 与源路径组合后，按参考表样本中的 `矫正-渠道` 主值写入工单数仓的 `二级渠道`；
- 如果组合没有稳定命中参考样本，不兜底成其他渠道，标记为“当前规则未命中”，保留原值供后续人工确认。

### 4.2 主被动

对线上留学目标行：

`主被动 = 资源主被动`

原始 `主被动` 不再作为留学线上工单的有效判断依据；它仍保留在原始字段列中用于审计。

### 4.3 国家和条线

- `意向国家` 优先取数仓 `意向国家/地区`；缺失时从 `资源描述` 中的意向国家文本提取；
- `矫正条线` 独立由国家映射，不使用渠道推断条线；
- 特殊规则：`咨询方式一级渠道` 含 `欧亚总部在线` 时，`矫正条线` 直接归 `欧亚条线`，即使国家字段为空；
- 国家无法取得或无法形成唯一条线时，标记未命中，不强行猜测。

## 5. 2026 年 6 月对照结果

对照文件：[2026年6月线上被动工单清洗对照及映射规则.xlsx](/Users/akechi/Desktop/manager -CowH/outputs/june_work_order_cleaning_review_20260920/2026年6月线上被动工单清洗对照及映射规则.xlsx)

本文件只包含资源主被动为被动、团队为空、且属于网络资源/新媒体的线上留学工单：

- 线上被动工单：497 条；
- 主被动覆盖：281 条；
- 一级渠道更新：497 条；
- 二级渠道更新：438 条；
- 意向国家已取得：326 条；
- 矫正条线已取得：421 条；
- 当前规则未命中渠道：10 条。

文件的 `映射规则` Sheet 是看板开发的口径说明，`6月清洗明细` Sheet 是清洗前后对照。

## 6. 看板开发要求

看板 SQL/计算应优先使用清洗后的字段：

- `主被动`：用于统一被动工单筛选；
- `一级渠道`、`二级渠道`：用于渠道下钻；
- `意向国家`、`矫正条线`：作为留学独立维度；
- `资源主被动`：只作为来源审计字段，不再替代清洗后的 `主被动`。

不要：

- 用原始 `主被动` 判断留学线上工单是否被动；
- 把 `矫正条线` 从渠道名称反推；
- 把 `渠道合作`、`市场活动`线下留学工单混入本轮线上清洗；
- 把“当前规则未命中”兜底成 `前途推荐`、`线上平台`或其他渠道。

## 7. 验证

当前相关单元测试：9 passed。

下一步发布新 Snapshot 时，需要：

1. 使用网页素材刷新流程；
2. 确认合并前参考文件仍是客户工作区内的映射表；
3. 发布新 Snapshot；
4. 对新 Snapshot 重新做 Bridge/字段兼容性校验；
5. 再刷新看板，使用本文件第 6 节字段口径。
