---
name: business-analysis-routing
description: 将已完成首次部署和 Bridge 对齐的自然语言分析请求路由到 Casebook 线索、当前 Snapshot 的受控只读查询和可选文件交付；不替代宿主 Agent 的推理、Session 或模型调用。
---

# 业务分析路由

当用户在一个已经初始化并完成 Bridge 对齐的客户工作区中提出指标查询、环比/同比、异常诊断、下钻或“做成 PPT/表格”的请求时使用。首次部署、导入文件、Snapshot 发布和 Bridge 多轮确认仍分别使用 `first-deployment-onboarding` 与 Bridge 对齐流程；明显的数据源重叠问题使用 `diagnose-source-overlap`。

## 核心顺序

每次分析先执行一次确定性状态检查，再由宿主 Agent 负责问题理解和 SQL 编排：

1. 调用 `python3 -m interfaces.casebook guide --workspace <workspace>`。
   - `next_step` 不是 `analyze` 时，停止分析并把用户带到返回的初始化、同步或 Bridge 对齐步骤。
   - `next_step` 为 `analyze` 时，只使用返回的显式 `snapshot_id`，并读取工作区中的当前 Pack、Bridge 和 Snapshot 指针。
2. 根据用户角色和问题类别调用 `python3 -m interfaces.casebook case-search`。没有匹配案例也可以继续；不要为了填充案例而扩大搜索范围或跨公司/角色读取。
3. 命中案例时，将其当作方法线索（问题结构、关键查询、限制和交付形式），需要时先执行 `case-verify` 检查证据哈希。案例中的旧数字、旧 Snapshot 或旧文件都不能直接回答当前问题。
4. 若问题涉及留学线上/线下资源、签约、毛签、板块占比、FY27 目标或 Q1 完成率，先读取工作区 `Input/Reference/留学板块-官方记分卡.md` 与 `.json`。该记分卡是业务确认事实，覆盖范围内置信度高于现行数仓；不要 ingest 进 Snapshot，也不写入 Bridge。
5. 结合当前 Pack 的指标/诊断定义和当前 Bridge 的物理字段映射，由宿主 Agent 生成本次只读 SQL。通过 Data Platform 的 `describe`/`quality` 和 `query`（或已确认的 `run-saved-query`）执行；每次查询都必须显式携带当前 `snapshot_id`、`run_id` 和输出目录。不得直接用 DuckDB 客户端绕过入口，也不得按 `latest`、修改时间或模糊文件名选数据。数仓结果用于明细、拆解、诊断和与官方记分卡对账；冲突时报告差异，不得用数仓覆盖记分卡。
6. 只基于官方记分卡（若适用）和当前查询结果回答，并说明时间范围、口径、来源和已知限制。Casebook 的命中信息可在运行证据中作为方法引用记录，但不替代当前查询证据或官方记分卡。
7. 用户明确要求文件交付时，表格/图表使用宿主原生能力；PPT 将已验证的分析结论、查询结果、口径、时间范围、来源和限制交给宿主全局 `ppt-master` Skill。路由选择由该 Skill 的当前规则决定：用户明确要求快速/轻量时可进入 Quick，其他情况按 Default 及对应路由执行；项目不自行复制路由规则。交付物必须可打开、内容非空，关键数字能回查到本次受控查询或对应官方记分卡。如果全局 `ppt-master` 不可用，明确阻断 PPT 交付，但保留已完成的分析和证据；不回退到项目内置生成器。

## 分析结束提醒

结论和必要交付完成后，若本次尚未保存、未提醒过，且用户未明确拒绝保存，只提醒一次：

> 如需以后复用这次分析，可以在验收后让我保存为 Casebook 候选。

这些条件只使用宿主当前对话状态，不增加状态存储或后台 Hook；不按复杂度、多数据源或业务价值判断是否提醒，不自动创建案例或修改状态机。用户已明确要求保存时直接进入下述流程，不重复提醒。

## 保存与沉淀

- 只有用户明确表示该分析已验收、以后需要复用时，才调用现有 `case-create` 保存最小证据包；默认创建 `candidate`，不要自动确认、发布或修改 Pack/Bridge/Skill。
- 保存时通过 `workspace_modeling.delivery.create_delivery` 将本次受控查询回执和已验收的自包含交付文件组为 `business_delivery.v1` 证据包，再用 `casebook_capture.v2` 的 `evidence_sources=[{"path":"工作区相对的delivery.json路径"}]` 调用现有保存入口；问题、规范化问题、关键查询和结论限制仍须提供。CLI 将包内 Snapshot、Pack/Bridge、公司和角色与所选工作区逐项核对，不给历史或外来证据自动贴当前身份。使用 `case-verify` 检查完整引用与哈希，再由用户明确决定 `case-confirm`。纯文字分析在用户明确验收并同意保存后，将已验收答复原样写入本次工作区输出目录的 `answer.md`，再与查询回执一起走相同的 `create_delivery` 与 capture 流程；不扩写答复、不自动制造新报告。未同意保存时继续保留已有查询证据。
- `repeat-candidates` 只用于用户或内测回收明确要求检查重复模式时。它只返回候选，不生成或发布 Skill；跨客户可复用的方法由人工审核后沉淀为项目 Skill、模板或 Pack。

## 宿主边界

本 Skill 是调用说明，不是第二个 Agent Loop、Session 管理器、SQL 编译器、记忆库或后台任务。宿主 Agent 负责自然语言理解、候选 SQL、向用户提问和交付编排；项目 CLI 只负责确定性状态检查、受控查询、证据哈希和文件验收。

## 参考

- [S5 Casebook 合同](../../../docs/casebook-pilot-contract.md)
- [项目接入指南](../../../docs/integration-guide.md)
