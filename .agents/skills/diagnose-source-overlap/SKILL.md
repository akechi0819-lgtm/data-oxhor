---
name: diagnose-source-overlap
description: 诊断同一 Snapshot 中多张数据表的日期区间重叠、全量刷新、重复导出和跨来源重复记录。用户提供多期现金表、订单表、配课表等可能重叠的数据，或查询结果可能重复计算时使用；通过 Data Foundation 只读查询举证，并在客户确认业务键和来源优先级后保存去重查询。
---

# 数据源重叠诊断

## 边界

- 把重叠识别和查询时去重放在 Data Foundation，不写进 Pack 或 Bridge。
- 不修改 landing、源文件或已发布 Snapshot。
- 模型负责探索和提出方案；Data Foundation CLI 负责只读执行、限制和保存确认后的 SQL。
- 日期区间交集只是风险信号，不足以证明两行重复。

## 工作流

1. 读取显式 `snapshot_id`，调用 `describe` 查看 `ingest.sheets` 与相关 `landing.*`。
2. 先区分：
   - 同一 `source_id` 的全量刷新：当前输入替换后发布新 Snapshot；只查询新 Snapshot，不跨 Snapshot 相加。
   - 当前 Snapshot 内多个 `source_id`/relation 并存：继续重叠诊断。
3. 对每个 relation 用只读 SQL检查：
   - 可用日期字段及解析方式；
   - 最小/最大日期、总行数、日期为空数；
   - 候选业务键的空值率、唯一率和重复分布。
4. 对日期区间有交集的 relation，比较经字段对齐后的候选业务键：
   - 重复键数与重复行数；
   - 同键同内容和同键冲突内容分别计数；
   - 各来源独有键数量。
5. 没有稳定业务键时向客户提问。优先寻找交易号、订单号、流水号等源系统身份；不得默认使用整行哈希、金额+日期或行号作为业务键。
6. 多来源同键冲突时要求客户确认来源优先级或字段级选择；不得按文件名、修改时间或 `latest` 猜测。
7. 用 CTE + `ROW_NUMBER() OVER (PARTITION BY <confirmed_key> ORDER BY <confirmed_priority>)` 生成只读 SELECT，并同时保留 `_source_label` 便于审计。
8. 先用 `query` 验证原始行数、保留行数、删除重复数和冲突样例。客户确认后才用 `promote-query` 保存版本，再用 `run-saved-query` 重用。

## 必须阻断

- 日期角色未确认；
- 候选业务键含空值或在单一来源内对应多条冲突内容；
- 来源优先级存在多种合理解释；
- 字段无法可靠对齐；
- SQL 不是单一只读 SELECT。

## 回答客户

只报告可验证事实：各来源日期范围、交集、重复键、冲突键、预计保留/删除行数、所用业务键和优先级。明确区分“全量刷新替换”与“同 Snapshot 查询去重”，不要笼统称为合并。
