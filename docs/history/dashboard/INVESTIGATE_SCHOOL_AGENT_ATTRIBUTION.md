> 历史存档：原路径 `dashboard_product/docs/INVESTIGATE_SCHOOL_AGENT_ATTRIBUTION.md`，于 2026-09-18 目录整理时归档。以下状态、命令、版本与凭据配置描述仅代表记录当时，不是当前操作入口。当前项目状态见 [DEVELOPMENT.md](../../archive/DEVELOPMENT-history-202611.md)；看板现行操作见 [DEPLOYMENT.md](../../../dashboard_product/DEPLOYMENT.md)。

> **已废止/被取代（2026-09-07）**：校代兜底改为资源描述「市场人员：」。见 `FIX_SCHOOL_AGENT_MARKET_PERSON_RUN.md`。

# 排查：校代 → 资源录入人 个人归属兜底

派工：牛马力工（grok build）
验收：许家印
触发：用户反馈新刷新看板里，工单个人核定时好像只剩「市场活动名找人名」，看不到「活动名含校代且未带人名时按资源录入人归属」的兜底。

## 合同口径（已写在 README / CURRENT_STATUS）
1. 先按工单业务组筛人员候选；
2. 优先：市场活动名称中命中人员姓名；
3. 兜底：活动名含「校代」且未命中姓名时，用工单 `资源录入人`（可带 `-校代` 等后缀）匹配同业务组人员；
4. 现金经工单 ID 继承同一归属。

## 初扫（许家印只指路，不施工）
- `dashboard_product/refresh.py` `matched_people()`：代码里**已有**校代→`entry_person` 分支（约 61–70 行）。
- 单测 `tests/test_render.py::test_person_attribution_filters_business_group_then_uses_entry_person_for_school_agent` 覆盖该路径。
- 当时 `dashboard_actuals/v6` SQL 已输出 `entry_person`（工单 `资源录入人`；现金经 LEFT JOIN 工单继承）。现行刷新是 v7。

因此问题更可能是：**线上未生效 / 被前置条件挡掉 / 数据侧 entry_person 空**，而不是文档完全没写。请用 grok build 实证排查，不要只看文档。

## 请查清
1. 跑现有单测是否通过。
2. 对当前 workspace 显式 `snapshot_id`，抽样含「校代」的工单行：`campaign_name`、`entry_person`、是否被记到人员。
3. 核对是否被这些条件挡死：
   - 活动名已误命中其他人名（先 return campaign_matches）；
   - `entry_person` 为空或姓名对不上 `people.json`；
   - `add_row` 要求 `campaign` 非空才做个人归属；
   - 现金未挂上工单导致 `entry_person` 为空。
4. 若属实现/接线 bug：修并补测，说明是否需重跑日更发布。
5. 若属口径要改（改公式）：停手回许家印/赵高，勿擅自改口径。

## 交付
写短 RUN（无经营明细可贴汇总）：结论（规则在/不在、为何用户看不到、是否已修）、证据（测试、抽样计数）、是否需要我改日更例程或重发分册。
