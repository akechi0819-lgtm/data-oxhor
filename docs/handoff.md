# 项目交接状态

## 截止 2026-08-15 已完成

- 确定 DeepSeek Harness 为默认客户运行宿主，同时冻结宿主可替换原则；
- 全局安装并静态验证 DeepSeek Harness `0.1.0-rc.6`；
- 在 Harness 机器级设置中配置模型 Provider/API Key，未将凭据写入仓库；
- 验证 Harness 真实模型回合、项目 Workspace 和受控 Shell；模型成功执行 Data Foundation 顶层 `--help`，退出码 0，并发现全部 7 个子命令；
- 完成 Data Foundation 的 XLSX 探查、不可变 Snapshot、DuckDB/Parquet、质量问题、只读 SQL 和保存查询；
- Data Foundation 使用 `run_id`、显式 Snapshot 身份和最小 Artifact manifest；源 SHA-256 保留在 inspect/ingest 与 manifest 内部，不作为跨 Session 强制字段；
- 确定 CLI 是 Data Foundation 唯一公开入口，Codex、DeepSeek Harness 等具备受控 Shell 的宿主直接调用同一 CLI；
- 确定当前不建设 MCP 或独立 Harness Reinforcement 插件，确定性约束由对应业务模块直接实现；
- 删除已废弃的 Codex→Hermes handoff schema、validator 和 5 项相关测试；
- 完成 Education Business Pack `education_training_operations_cn` v1.0.0，覆盖行业概念、指标、维度、三段客户旅程、漏斗和诊断 Playbook；
- 完成 Pack `validate` / `describe` CLI 与稳定 ID、交叉引用校验；
- 完成 `company_bridge.v1` / `company_bridge_candidates.v1` 合同、确定性校验器、宿主无关 CLI 和合同测试；
- 完成 `/Users/akechi/Desktop/super_agent` 只读历史扫描，当前产出 136 个候选和 851 条拒收记录；扫描结果与 Super Agent 物理隔离，未修改其现有未提交改动；产品 `剑五` 按 `班型` 拆分 KET/PET 的二次归一规则已作为 proposed 候选保留，日报有符号净现金、明确退款/调整识别和并归渠道优先均作为 proposed 候选保留；默认新生筛选、新生/老生到新签/续费的偷换、工单项目到最终购买产品的映射和 1500 付款人阈值均被拒收；
- 已将上述扫描结果整理为 `artifacts/company_bridge/reviewed/super_agent_confirmed_review_20260815_v1.json`（135 个 confirmed 候选）：付款人统计沿用学员身份；净现金按有符号金额求和；明确退款和转班/重报调整分开；剑五按 KET/PET 班型二次归一；用户确认和理由记录在 `artifacts/company_bridge/reviewed/super_agent_review_decisions_20260815.md`；
- 已用现金明细、FY27 报名系统操作明细、工单表三份真实工作簿在 DeepSeek Harness 中完成 Data Foundation `inspect → ingest → describe → quality → query`，Snapshot 为 `snapshot_super_agent_inputs_20260815_v2`；Bridge 1.1.0 已在该 Snapshot 上兼容性通过，退出码 0、错误 0；
- 46 项现行 Python 测试通过；
- 明确 Pack 与 Bridge 从第一家企业起物理分离；
- 明确 Customer Profile 只是薄装配；
- 明确长期业务学习进入独立学习与质量工作区，而不是宿主 Session；
- 项目 Git 仓库当前基线提交为 `8992e8a2dd07b00cb17ca4e166e702003b3c69c`；当前工作树包含未提交施工改动。

## 尚未完成

- Harness 的 Session 恢复、项目 Skill 和 Deliverables 验收；
- 首个 Customer Profile；
- 输出插件和确定性 Renderer；
- 学习与质量工作区。

## 下一步

真实 Snapshot 与 Bridge 的兼容性校验已完成，下一步是 Harness Session 恢复、项目 Skill 和 Deliverables 验收。后续运行仍须使用显式 `run_id` / `snapshot_id`；Snapshot 不写回 Bridge，Pack 不接收企业字段、SQL、阈值或单次分析结论；历史扫描结果不能直接进入正式入口。

Data Foundation 宿主侧仍需补充验收：

1. 已用真实三表在 DeepSeek Harness 中调用 `inspect/ingest/describe/quality/query`，确认 JSON、退出码和产物路径可直接消费；
2. 保持现有只读拒绝、Snapshot 身份和错误测试通过，不复制 Python 核心；
3. 在同一 Session 连续追问后重启恢复，并用显式 `run_id`/`snapshot_id` 继续；
4. 完成小型 Deliverable 验收。

不要开发 MCP、独立强化插件、PPT 或完整 Run/Artifact 平台。当前数据调用链只依赖 CLI、显式 `run_id` 和 `snapshot_id`；源 SHA-256 继续作为源绑定和 manifest 的内部完整性信息。

## 已知阻塞与风险

- 当前没有已知的外部阻塞；完整数据链路、Session 恢复和 Deliverables 仍需实际验证；
- DeepSeek Harness 是 Developer Preview，插件接口可能破坏兼容；
- 尚未确认可直接复用的官方 PPT/图表市场能力；
- 当前 `data_foundation/` 对 `br_cash`、FY25/FY27 前台明细和工单表保留显式源表映射，并按实际可用的 FY25/FY27 输入创建 `semantic.registration_cash`；这不是通用企业语义层，新增源仍需显式输入合同和测试；
- 当前 Bridge、扫描产物和文档仍是未提交施工改动；交接时应以工作树和测试结果为准，不把基线提交误认为包含本次改动。

## 技术依据

- [DeepSeek Harness 调研卡](../research/projects/deepseek-harness.md)
