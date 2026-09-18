# 项目交接状态

> 2026-09-16 模块切换：人员进度与钉钉推送已迁至 `monitoring_product/`，看板不再承担发送。新入口要求 workspace、snapshot-id、run-id、as-of-date、data-through-date；正式发送另需显式 env-file。共享花名册在 `workspace_modeling/operations/people.json`。本地迁移完成不代表云端任务已切换；详见项目根目录 `monitoring_product/README.md`。

本文件面向维护者，记录历史完成度、风险和后续工程事项。它不是客户使用说明，也不替代 `AGENTS.md` 的运行时边界。当前项目定位、模块状态和开发决策见根目录 `DEVELOPMENT.md`。

## 当前状态

2026-09-18 架构演进阶段已结束：公共证据合同及查询 → 自由分析交付 → Casebook 链路完成并验收，正式回归 176 项全部通过。看板保持静态图表定位，原定看板与监控最终产物统一改造已取消；案例提醒、指标关联与 Business MCP 无当前需求，不计为未完成工程。本阶段无待施工任务，正常使用中出现具体问题再另行立项。详见 [阶段计划与验收记录](./Agent_架构演进施工计划.md)。

项目主线已完成 Data Platform、Business Pack、Company Bridge、Bridge 对齐向导、工作区建模、Casebook/内测反馈和双宿主交付验证。业务核心保持宿主无关；调用者按任务选择模块 Agent，分别进入工作区建模、Bridge 对齐、受控分析、案例沉淀、文件交付或看板发布。

PPT Master 已从项目内置改为宿主全局 Skill，项目不再维护 Quick 入口或上游文件树；正式 Bridge 和 reviewed 证据继续作为当前产品基线。

## 当前合同

首次部署引导层 v1 已归入公开入口 `python3 -m interfaces.workspace_modeling`（安装 wheel 后可使用 `workspace-modeling`）：

```text
doctor -> init -> import-data -> sync -> handoff -> 宿主 Agent 对齐 Bridge
```

它负责运行时/Pack 检查、客户 `Input/Work/Output` 初始化、基础 XLSX/XLSM 来源槽位复制、不可变 Snapshot 发布、当前状态检查和 Bridge 会话交接。所有输出为 `onboarding_result.v1` JSON；来源槽位默认不可覆盖，刷新使用新的 `snapshot_id`。`handoff` 可重复读取同一会话。

它不负责模型候选生成、自然语言确认、Bridge 问题回答或正式 Bridge finalize；这些仍由宿主原生 Agent 与 `interfaces.bridge_alignment` 完成。

完整输入、输出和错误语义见 [首次部署引导层合同](./onboarding-contract.md)。

Codex 的自然语言入口见 [首次部署自然语言 Skill](../.agents/skills/first-deployment-onboarding/SKILL.md)。用户可以直接说“帮我首次部署”“导入这批数据”或“建立 Bridge”，由 Skill 调用确定性引导 CLI 并在需要时逐步询问。

- 运行使用显式 `run_id`；查询和恢复使用显式 `snapshot_id`。
- Data Platform 只负责原始 landing、身份、质量和只读查询，不理解教育业务。
- Pack 保存行业通用知识；Bridge 保存企业表头名、枚举和 Override，不保存列位或列序兼容规则。
- 历史扫描只能生成候选；正式 Bridge 只接受人工复核的 `confirmed_review`。
- 向导模型候选始终是 proposed；只有客户决定或显式 optional unresolved 能进入 reviewed，关键歧义必须阻断。
- 客户工作区使用固定 `Input/Work/Output` 并保存相对路径，可整体复制；追加资料持久化到 `Input/Reference`，源码 checkout 的 `customers/` 默认忽略。
- 源文件承担长期归档；向导工作区只保留当前 Snapshot，不维护 `snapshot_history`。`sync-data` 先构建并切换新 Snapshot，再删除旧 Run；失败或存在未完成会话时保留旧状态。仅记录已用 ID，防止删除后复用；已完成会话为只读。
- Data Platform 的 SHA-256 负责导入完整性；向导候选、问题、决定和参考资料身份不使用哈希。PPT 交付必须使用当前 Snapshot 受控查询的真实结果与来源凭据。
- Snapshot 只用于运行兼容性校验，不写入 Bridge；Bridge 不通过 `latest` 或修改时间选择状态。
- Bridge 字段定位直接使用源表实际表头名；禁止使用列序或 `column_n`。重复表头在 landing 中使用 `__2` 等后缀。
- 工单主键 `ID` 与现金 `工单ID` 仅以非空、修剪后的文本精确连接；Saved Query 不做数值化转换。Bridge 不声明未执行的 ID 归一化规则。2026-09-04 已用 `snapshot_bi_work_order_id_20260904` 验证现金-工单精确 ID 连接恢复。
- 真实源工作簿、DuckDB、Parquet 和运行目录不进入 Git。

## 唯一待办

看板侧剩余事项是线上平台人员配置，以及线上私域/线上平台/线下大学钉钉 webhook；不在本文件展开，见 `dashboard_product/docs/PENDING_ISSUES.md`。PPT 不再有项目内 Quick 性能回归待办；之后的生成验收跟随宿主全局 `ppt-master` 版本。

不要增加 MCP、独立强化插件、完整 Artifact 平台或通用工作流编排；新增治理必须对应可复现失败或明确客户要求。

## Bridge 与数仓口径收口（2026-09-05）

- 决定：当前正式 Bridge 升级为 `bridge_bi_operations` v1.2.0；字段只按实际表头名定位，删除全部列序、`column_N`、ID 数值化和未执行的 ID 归一化声明，并固化被动新生正向报入现金口径。
- 原因：历史 SQL 使用列序及 `DOUBLE`/`BIGINT` 处理工单 ID，造成科学计数法与错行风险，并会误导后续工程。
- 影响：工单表 `ID` 与现金表首个 `工单ID` 只以修剪后的文本精确关联；现金金额以 `DECIMAL(38,2)` 汇总。旧对齐和旧被动现金 Run、临时渠道 SQL 已删除，不提供兼容入口。
- 验证：Bridge 在 `snapshot_bi_work_order_id_20260904` 兼容校验通过；当时 `dashboard_actuals/v6` 受控运行成功并只引用现金、工单两张 landing 表；桥接回归测试覆盖 ID 文本和 SQL 清单哈希。该验证针对当时的 v6，不是现行刷新合同。

## 市场归属现金资产化（2026-09-05）

- 决定：将已验收的被动新生正向报入现金口径正式登记为 `attributed_passive_reported_cash/v1`，并把字段语义、业务组映射、文本工单关联和未匹配团队归属政策写入 `bridge_bi_operations` v1.2.0。
- 原因：该口径不仅服务当前看板，也用于后续市场团队贡献、自由探索和异常分析；可执行 SQL 与企业语义必须各自有唯一归属。
- 影响：Saved Query 是逐笔现金底稿，保留来源行号、工单关联状态和归属规则；Bridge 不保存 SQL。当时看板仍消费 `dashboard_actuals/v6`，该次没有改动其刷新链路。现行刷新已改 `dashboard_actuals/v7`。
- 验证：Saved Query 在 `snapshot_bi_work_order_id_20260904` 运行成功，5,030 条现金源明细；Bridge v1.2.0 Pack 合同校验通过。Q1 汇总与现有看板查询现金汇总均为 `12,748,539.70` 元。

## 看板模块决策（2026-09-02）

- 决定：看板能力先作为当前项目内的独立 `dashboard_product/` 模块开发，不新建数据镜像项目，也不引入 MCP。
- 设计期：由宿主直接调用 Data Platform 的 `describe`、`quality`、`query`、`run-saved-query` 只读 CLI 探索当前 DuckDB Snapshot，确认公式和筛选后保存看板 SQL/规格。
- 日常期：只运行已确认的固定刷新脚本，读取明确 `snapshot_id`，生成聚合 JSON/HTML 并推送服务器；不调用模型或 MCP 临时决定口径，不上传 DuckDB、原始工作簿或明细数据。
- 原因：当前主要使用者为单人，未来主要增加看板复杂度而非接入宿主；CLI 已足够，减少 MCP 维护层。若未来出现多宿主或多人复用，再评估把只读 CLI 包装为 MCP。

## 语培完成进度看板施工状态（2026-09-09 更新）

- 模块：`dashboard_product/` 已实现 artifact 刷新、四分册静态发布、basic auth 和钉钉人员进度。日更 10:00 挂许家印云电脑；本机 Codex 定时已停。钉钉不并入日更脚本。
- 当前 Snapshot：工作区 `workspace.json` 为准（本机 2026-09-09 仍为 `snapshot_bi_operations_20260908`；云端日更为 `snapshot_bi_operations_20260909`）。使用现金明细 `landing.br_cash__sheet_39b8dee2e4b3` 与工单 `landing.br_work_orders__sheet_1f0596db9f25`。查询仍经 Data Platform 受控只读入口；原始工作簿、DuckDB 与运行结果不进 Git。
- 工单口径：按工单表 `ID` 去重，按 `分配时间` 落在查询窗口；正式 SQL 输出字段为 `event_date, team_id, business_group, first_channel, second_channel, campaign_name, entry_person, school_name, grade_name, metric, actual_value`。
- 被动现金口径：现金底稿 `渠道属性=被动`、`新老生类型=新生` 且 `报入现金收入>0`；负向不纳入。现金业务组只看现金表 `团队`：青少、初中、高中、大学（ICC/国际学科进高中）。目标区再把青少+初中滚成留学预备；同比区保留四组年段。
- 毛签口径（2026-09-16 用户确认）：`毛签 = SUM(报入现金收入)`，只纳入 `报入现金收入 > 0` 的明细；零值和负值排除，且毛签不等同于净现金。新签毛签限定 `新签&续费=新签`；项目毛签限定 `新签&续费 IN (新签,续费)`，并按已确认现金业务组映射拆分留学预备、高中、大学；被动项目占比为累计被动除以项目毛签。FY27 总体目标约束为：三项目合计被动占整体新签毛签49%，被动收入占新签+续费项目毛签29%。单项目不得直接套49%/29%；分别取该项目FY26与FY27-Q1实际比例均值，再对三项目统一缩放，使合计精确回到49%/29%，同时保留项目间历史差异。已写入 `bridge_bi_operations` v1.5.0。
- 现金业务组与渠道团队分两层计算：业务组总额只由现金表 `团队` 映射决定；工单 ID 连接只用于在业务组内部拆分线下市场、线上平台和线上私域。未匹配工单按“活动名含虚拟人→活动名含线上→渠道含 TMK→活动名含校代→其余线上”顺序归属渠道团队。
- 看板运行从项目父目录执行 `python3 -m dashboard_product.refresh refresh --workspace customers/bi_operations --run-id <id>`，再用 `render --artifact .../artifact.json --all-booklets` 生成四分册 HTML。刷新消费 `dashboard_actuals/v7`：目标区留学预备/高中/大学，同比区青少/初中/高中/大学。当前 Snapshot 以工作区 `workspace.json` 为准（本机 2026-09-09 仍为 `snapshot_bi_operations_20260908`；云端日更为 `snapshot_bi_operations_20260909`）。
- 新生报名校区口径：团队为初中、初中国际学科、青少且新老生类型为新生；同一学员编号+班级编码在窗口内的报入现金净额绝对值 `>=1500`、报名人次大于零时，按学员编号去重计人头。新生报入现金仅汇总正向报入现金收入，单笔为该金额除以合格去重人头。
- 已核验：留学预备新生现金与线上当期报表对齐。人头按同一公式复算时与当时截图相差 1 人，定位为国金来源版本差异，非门槛、去重或单笔公式差异；下次使用同源 Snapshot 时复核。

## 已知风险

- DeepSeek Harness 仍是 Developer Preview，升级可能破坏插件接口；
- 当前 landing 关系名由 `source_id + sheet_name` 确定，源 Sheet 改名后必须重新做 Bridge 兼容性校验；
- fake adapter 只用于候选合同测试；正式推理由 Codex 或 DeepSeek Harness 的原生 Agent 承担，不建设宿主 Adapter；
- 宿主全局 `ppt-master` 的版本、完整性和升级由宿主环境管理；项目回归不再检查其文件树。
- S5 不能以自动上传、自动打包 `runs/`、跨客户检索、宿主 Session 复制、向量库或自动发布 Skill 作为捷径；反馈证据只在用户明确授权时导出。

## 技术依据

- [系统架构](./architecture.md)
- [接入指南](./integration-guide.md)
- [Company Bridge v1 合同](./company-bridge-contract.md)
- [Bridge 对齐向导 v1 合同](./bridge-alignment-wizard-contract.md)
- [Casebook、内测回收与引导路由合同](./casebook-pilot-contract.md)

## BI 日更滚动合并（2026-09-16）

- 日更导出改为近 6 个日历月滚动窗口；与上一 current snapshot landing 合并窗外历史后再 import/sync。
- 工单按 `ID` 近窗覆盖；现金按 `业务日期` 窗口替换（保留窗外重复行，不造硬主键）。
- 实现：`data_acquisition/jobs/bi_window_merge.py` + `rebuild_bi_warehouse.py`；说明见根目录 `ROLE.md`。不改看板。
