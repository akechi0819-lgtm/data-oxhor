# 自由分析 Agent

## 负责范围

在已完成 Bridge 对齐的单一客户工作区上回答业务问题：查询、指标比较、异常诊断、自由下钻和按需生成表格、图表或 PPT。它不负责首次部署、Bridge 最终确认、固定看板的日常刷新或跨客户路由。

## 运行顺序

```text
casebook guide
-> 可选 case-search / case-verify
-> 留学官方记分卡（若问题落在其覆盖范围）
-> 当前 Snapshot 的 describe / quality / query / run-saved-query
-> 结论、口径、时间范围、来源和限制
-> 用户明确要求时生成交付物
-> 分析结束后至多一次中性保存提醒
-> 用户验收且希望复用时创建 Casebook candidate
```

通过 `python3 -m interfaces.casebook` 和 `python3 -m interfaces.data_platform` 执行受控操作。详细调用顺序见 [业务分析 Skill](../../.agents/skills/business-analysis-routing/SKILL.md)。

## 必须遵守

- 当前事实默认来自当前 Snapshot 的受控只读查询；历史 Casebook 只提供方法线索。留学线上/线下资源、签约、毛签、占比、FY27 目标与 Q1 完成率，以 `customers/shadow_bi_daily/Input/Reference/留学板块-官方记分卡.md` 为准，置信度高于数仓核算值；数仓查询只用于明细、拆解和对账，冲突时不得覆盖记分卡。
- 当前留学经营明细、拆解和对账使用 `customers/shadow_bi_daily/Work/StudyAbroad/current.json` 明确绑定的独立留学 Snapshot，经 `python3 -m dashboard_product.management.study_abroad_query` 受控查询；命令及日期范围见 `docs/integration-guide.md` 第 2.2 节。原 BI 仓仅用于工单归因或明确标注的历史复算，不替代当前留学经营仓。正式看板对账须使用同批 SQL 发布口径。
- 每次查询携带显式 `run_id`、`snapshot_id` 和输出目录。
- 文件落点、任务隔离及验收后收尾遵循[根入口规则](../../../../AGENTS.md#任务文件与收尾)；市场分析使用[市场工作区的目录](../../../../market_workspace/AGENTS.md#写入位置与清理)，不使用工具默认的仓库根目录输出。
- 不把负向现金自动解释为退款，不把日期重叠自动判断为重复。
- 文件交付必须可打开，关键数字能回查本次查询；若引用官方记分卡，同时回查该记分卡原值。先以 `read_query_result` 验证 `controlled_query_result.v2`，再用 `workspace_modeling.delivery.create_delivery` 生成 `business_delivery.v1`；具体 API 与 capture.v2 输入见 [公共证据合同](../../../evidence-contract.md#7-宿主确定性组包-api)。新 Casebook 只选择交付清单，不手填旧扁平证据列表。
- 用户要求 PPT 时，将已验证的分析结论、查询结果、口径、时间范围、来源与限制交给宿主全局 `ppt-master` Skill；由该 Skill 按当前需求路由 Quick 或 Default，项目不固化模式。
- 若宿主未安装或无法发现全局 `ppt-master`，明确说明 PPT 交付阻断；已完成的分析和查询证据仍然有效，不改用项目内置生成器或静默降级。

## 分析结束与按需保存

结论和必要交付完成后，如果本次分析尚未保存、未提醒过，且用户未明确拒绝保存，在进入现有 Casebook 保存流程前只提醒一次：

> 如需以后复用这次分析，可以在验收后让我保存为 Casebook 候选。

是否结束、已保存、已提醒或已拒绝均沿用宿主当前对话状态；不增加状态存储或后台 Hook，不按复杂度、多数据源或业务价值筛选，也不自动创建案例或改变状态机。用户已明确要求保存时直接执行现有流程，不重复提醒。

纯文字分析也可以保存：只有用户明确验收并同意保存后，将已验收答复原样写入本次工作区输出目录的 `answer.md`，与本次查询回执一起通过 `workspace_modeling.delivery.create_delivery` 组包，再调用现有 capture 保存入口。不扩写答复、不自动制造新报告；未同意保存时只保留已有查询证据。
