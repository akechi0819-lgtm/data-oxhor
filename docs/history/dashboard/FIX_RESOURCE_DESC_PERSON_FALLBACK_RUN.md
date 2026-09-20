> 历史存档：原路径 `dashboard_product/docs/FIX_RESOURCE_DESC_PERSON_FALLBACK_RUN.md`，于 2026-09-18 目录整理时归档。以下状态、命令、版本与凭据配置描述仅代表记录当时，不是当前操作入口。当前项目状态见 [DEVELOPMENT.md](../../../DEVELOPMENT.md)；看板现行操作见 [DEPLOYMENT.md](../../../dashboard_product/DEPLOYMENT.md)。

# RUN：资源描述市场人员兜底（2026-09-09）

> 后续刷新已改 `dashboard_actuals/v7`，仍保留「市场人员：」抽进 `entry_person`。

## Decision
活动名对不上花名册时，不再只认「校代 + 市场人员」。线下大学/高中/留学预备共用：活动名 → `市场人员：` → `姓名市场资源` → 资源录入人 → 去掉 `YYYY.MM.DD-` 旧活动串后的资源描述正文。

## Reason
大学对账：丁槟槟活动名写成「曹恒为玮」；姚志诚活动名为空、描述里是 `杜晓蕾/曹恒玮-线下雅思行`。旧规则漏这 2 条。刘家长描述里的师顺盈在旧活动串中，去掉日期串后仍未归属。

## Impact
钉钉明细 `ledger_attributions` 立刻生效，人员图在 `apply_warehouse_actuals` 后按明细归属重计。

当时 `dashboard_actuals/v6` 已把「市场人员：」抽进 `entry_person`，不另输出资源描述列。现行 `dashboard_actuals/v7` 仍保留该抽取。看板 `refresh` 下一轮 artifact 能用录入人/市场人员兜住丁槟槟；姚志诚依赖「姓名市场资源」或描述正文，只在钉钉明细路径生效。

## Verification
- 单测 `test_resource_desc_fallback_covers_typo_campaign_and_embedded_name`
- 大学明细曹恒玮 = 19（含 34722714、34858734）
- 当时 `dashboard_actuals/v6` sha256 `569576ff9437c1c41603c8e00d2795d6382f1170e7a1e53ab3db1c5eb5a41513`（2026-09-07 20:51）已含 `市场人员` 抽取；`run_dashboard_20260907_101900` 早于该 SQL。现行刷新是 v7。
- snapshot 20260907 大学被动线下 311；当前 20260908 为 340，本地仓不少于 07
