---
name: biz-analysis
description: 在 Data OXHor 查询经营指标、核对看板与行级归因、导表或诊断来源覆盖及重叠。
---

# 经营查数

1. 先用 `market_workspace/oxhor status` 核对业务数据身份。汇总和归因读取 `query --release-id <版本>` 的封存语义层。读取原始数据时使用 `--layer raw --snapshot-id <版本>`。每次查询带独立 run ID 和证据。操作参数见[接入指南](../../../docs/integration-guide.md)。
2. 读取[经营指标索引](../../../docs/metrics-reference.md)。先明确期间、截止、范围和指标。留学官方记分卡只覆盖明确口径，缺乏可比性时分别展示。
3. 用同一版本的归因行复核异常。人头按各自范围和期间去重；来源日期重叠只是核对线索。导出的数字与证据须同口径，原件保留只读。
