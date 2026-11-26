---
name: daily-ops
description: 运行或排查 Data OXHor 日更、人工补全量、独立广告费录入、钉钉投递和腾讯表同步。
---

# 日更运维

先按业务日运行 `python -m ops status --day YYYY-MM-DD`。核对语培、留学截止日、SQL release、通知确认及三张表各自的状态。完整操作参数见[运维手册](../../../docs/operator-runbook.md)。

- 日更用 `ops run business`。自动导出空表或覆盖不足时，保留已验证版本。把经确认的双表原件放进日期对应的人工收件目录，用 `--from-manual` 接续。服务端去重负责日报发送，未知投递保持待核对。
- 独立费用用 `ops ingest-cost`。空额是缺失，零额来自确认声明。费用发布沿用封存合同。
- 用 `ops sync-sheets --job content|dianping|grade9|all` 查看运行结果。缺列暂停时先修复当次源/目标映射，人工列保持只读。部分写入或读回失败先核对回执，再决定后续操作。
