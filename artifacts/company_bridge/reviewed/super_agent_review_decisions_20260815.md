# Super Agent Company Bridge 审核决定

## Date/Stage

2026-08-15，基于 `scan_super_agent_20260814_v6` 的 `confirmed_review` 晋升。

## Decision

- 扫描候选中的客观源结构、字段映射、产品/校区/渠道归一化和日报现金规则，按当前业务确认进入 reviewed 候选集。
- 付款人不作为独立企业身份维护；付款人相关统计沿用学员身份。Bridge 用 `customer.payer` 的 Override 指向 `customer.student`，不把不存在的独立付款人列伪造成事实。
- 净现金保留现金金额的正负并直接求和；负数本身不等于退款。
- 只有明确的退班退费、储值账户退费、返款退费等退款业务形式/原因才归为退款；转班、退班重报、转出转入、放储值等归为资金调整，退款信号优先于调整信号。
- `剑五` 在 `班型` 为 `KET`/`PET` 时二次归一为对应产品；其他班型保留基础产品并告警。

## Impact

- `customer.payer` 不再作为本企业首版 Bridge 的 unresolved 阻断项。
- 扫描结果仍保留在历史候选文件中，不改写历史扫描入口；本文件只记录本次人工确认和企业选择。
- 默认“看新生”、4KET 对应 4～6 年级工单池、产品与工单年级联动、周度结论和 1500 有效人头规则仍属于分析侧或拒收内容，不进入 Bridge。

## Verification

- 当前 reviewed 输入：`artifacts/company_bridge/reviewed/super_agent_confirmed_review_20260816_v3.json`。
- 当前正式 Bridge：`artifacts/company_bridge/bridges/company_bridge.v1_2_0.json`。
- 2026-08-16 使用三份真实工作簿验证 Data Foundation v2，所有 Sheet 进入 `landing.column_N`；Bridge 将业务字段定位迁移到实际 `landing` 关系和列位，业务决定不变。
- 正式 `company_bridge.v1` 不绑定某一批数据；运行兼容性校验时再提供 Data Foundation 输出的 `warehouse_description.v1` 和 `controlled_query_result.v1`。

## Landing Contract

- `br_cash/现金明细表` → `landing.br_cash__sheet_39b8dee2e4b3`；
- `current_work_orders/新表区域` → `landing.current_work_orders__sheet_717cac52ce22`；
- `fy27_frontdesk_daily/FY27-汇总` → `landing.fy27_frontdesk_daily__fy27`。
