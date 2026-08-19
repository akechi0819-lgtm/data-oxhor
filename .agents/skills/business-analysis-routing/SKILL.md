---
name: business-analysis-routing
description: 将已完成首次部署和 Bridge 对齐的自然语言分析请求路由到 Casebook 线索、当前 Snapshot 的受控只读查询和可选文件交付；不替代宿主 Agent 的推理、Session 或模型调用。
---

# 业务分析路由

当用户在一个已经初始化并完成 Bridge 对齐的客户工作区中提出指标查询、环比/同比、异常诊断、下钻或“做成 PPT/表格”的请求时使用。首次部署、导入文件、Snapshot 发布和 Bridge 多轮确认仍分别使用 `first-deployment-onboarding` 与 Bridge 对齐流程；明显的数据源重叠问题使用 `diagnose-source-overlap`。

## 核心顺序

每次分析先执行一次确定性状态检查，再由宿主 Agent 负责问题理解和 SQL 编排：

1. 调用 `casebook-pilot guide --workspace <workspace>`。
   - `next_step` 不是 `analyze` 时，停止分析并把用户带到返回的初始化、同步或 Bridge 对齐步骤。
   - `next_step` 为 `analyze` 时，只使用返回的显式 `snapshot_id`，并读取工作区中的当前 Pack、Bridge 和 Snapshot 指针。
2. 根据用户角色和问题类别调用 `casebook-pilot case-search`。没有匹配案例也可以继续；不要为了填充案例而扩大搜索范围或跨公司/角色读取。
3. 命中案例时，将其当作方法线索（问题结构、关键查询、限制和交付形式），需要时先执行 `case-verify` 检查证据哈希。案例中的旧数字、旧 Snapshot 或旧文件都不能直接回答当前问题。
4. 结合当前 Pack 的指标/诊断定义和当前 Bridge 的物理字段映射，由宿主 Agent 生成本次只读 SQL。通过 Data Foundation 的 `describe`/`quality` 和 `query`（或已确认的 `run-saved-query`）执行；每次查询都必须显式携带当前 `snapshot_id`、`run_id` 和输出目录。不得直接用 DuckDB 客户端绕过入口，也不得按 `latest`、修改时间或模糊文件名选数据。
5. 只基于当前查询结果回答，并说明时间范围、口径、来源和已知限制。Casebook 的命中信息可在运行证据中作为方法引用记录，但不替代当前查询证据。
6. 用户明确要求文件交付时，再使用宿主原生表格/图表能力或现有 PPT 入口。S4 Quick 需先冻结本次分析证据，再按 [S4 Quick 提示词](../../../docs/s4-ppt-quick-prompt.md) 调用 `tools/s4_ppt_quick.py`；复杂模板或视觉交付才进入 `ppt-master` Default。交付物必须能回查到本次受控查询。

## 保存与沉淀

- 只有用户明确表示该分析已验收、以后需要复用时，才调用现有 `case-create` 保存最小证据包；默认创建 `candidate`，不要自动确认、发布或修改 Pack/Bridge/Skill。
- 保存时至少提供本次问题、规范化问题、关键查询、查询结果或 SQL 文件、来源凭据、结论限制和已验收的交付物（如有）。当前 Snapshot/Pack/Bridge 身份由 CLI 从当前工作区自动绑定，不在 `casebook_capture.v1` manifest 中重复传入。使用 `case-verify` 检查哈希，再由用户明确决定 `case-confirm`。
- `repeat-candidates` 只用于用户或内测回收明确要求检查重复模式时。它只返回候选，不生成或发布 Skill；跨客户可复用的方法由人工审核后沉淀为项目 Skill、模板或 Pack。

## 宿主边界

本 Skill 是调用说明，不是第二个 Agent Loop、Session 管理器、SQL 编译器、记忆库或后台任务。宿主 Agent 负责自然语言理解、候选 SQL、向用户提问和交付编排；项目 CLI 只负责确定性状态检查、受控查询、证据哈希和文件验收。

## 参考

- [S5 Casebook 合同](../../../docs/casebook-pilot-contract.md)
- [项目接入指南](../../../docs/integration-guide.md)
- [S4 Quick PPT 提示词](../../../docs/s4-ppt-quick-prompt.md)
