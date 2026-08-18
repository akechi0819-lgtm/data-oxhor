# Education Business Analyst

面向教育机构的对话式业务分析系统。它把脏 Excel 转成可追溯的数据快照，再用教育行业知识和企业语义映射支撑持续追问、自由下钻、图表和交付物生成。

默认客户运行宿主是 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)，Codex 是直接运行与验证宿主。两者都使用自身原生的 Agent、模型、Session、Skills、记忆清理、工具和文件交付系统；本项目不再包装一层 Agent，而是通过 CLI、Pack、Bridge、对齐向导和项目级 Skills 补充教育业务能力。Data Foundation、Business Pack 和 Company Bridge 均通过稳定 Python CLI 暴露，不需要额外 MCP 服务。

## 架构一览

```text
      DeepSeek Harness（默认）/ Codex / 其他 Agent Host
        原生 Agent / 对话 / Session / 模型 / Skills / 受控 Shell
                               │ CLI / files / JSON
                 客户工作区 + 项目 Skills
                               │
     ┌──────────────┬──────────┴─────────┐
     │              │                    │
Data Foundation  业务语义组          宿主原生交付
脏数据/Snapshot  Pack + Bridge       项目 Skills
     │              │                    │
     └──────────────┴──────────┬─────────┘
                               │
             本地案例与内测反馈的按需沉淀
     Casebook / Feedback / Skill / Template / Pack / Bridge
```

核心边界：

- Data Foundation 不理解教育业务，只负责原始 landing、身份、质量和受控只读查询；
- Business Pack 不伪装成某家企业事实；
- Company Bridge 不与 Pack 合并，即使第一家企业存在少量内容重复；
- Skill 指导模型，确定性工具负责数据权限、身份、计算和文件生成；
- CLI 是 Data Foundation 的唯一公开入口；宿主可替换性不依赖 MCP；
- 只读、Snapshot 不覆盖、unresolved 阻断和文件验收由对应模块的确定性代码承担，不建设独立强化层；
- 宿主 Session 是短期对话记忆；客户工作区的 Casebook 保存已确认、可回查的业务案例；
- DeepSeek 专属交互 UI 可以增强体验，但不能成为核心分析能力的唯一入口。

## 已实现

- XLSX 全 Sheet 探查和 OOXML 流式读取；
- 所有 Sheet 无需 cleaning plan 直接进入通用 `landing.column_N`，并发布不可变 DuckDB/Parquet Snapshot；
- Schema 描述、数据质量问题、受控只读 SQL、保存查询；
- `run_id`、Snapshot 身份、源 SHA-256 绑定和最小 Artifact manifest；受控查询结果会记录实际引用的 landing 关系和 `referenced_source_ids`，供冻结分析交付校验；
- Education Business Pack v1：28 个概念、20 个指标、26 个维度、三段客户旅程、3 个漏斗和 7 个诊断 Playbook；
- Pack 的 `validate` / `describe` CLI 与确定性交叉引用校验；
- Company Bridge 1.2.0：3 个当前源合同、10 个字段映射、105 条归一规则和 1 个企业 Override；
- Bridge 对齐向导 v1：提供自包含 `Input/Work/Output` 客户工作区、稳定数据源槽位和月度替换同步；工作区只保留当前 Snapshot，刷新成功后清理旧 Snapshot，宿主原生模型提出候选并收集关键确认，确定性服务自动生成 confirmed_review、build 和 Snapshot validate；
- 项目 Skill `diagnose-source-overlap`：提示模型主动检查全量刷新、日期范围、候选业务键、重复率和冲突；客户确认后用现有保存查询固化去重，不增加专用重叠平台；
- 项目 Skill `ppt-master` v4.7.0 已按固定上游提交装配到 `.agents/skills/ppt-master`，保留 MIT 许可证、模板、脚本、工作流和 notices；旁边的 `ppt-master.upstream.json` 记录来源与完整树摘要，并有离线完整性回归测试；
- 短数据 PPT 通过 `tools/run_s4_local.sh quick-ppt prepare|finalize` 走共同 Quick 路线：冻结分析身份校验、官方最终 checker 与 Quick exporter；不建设第二套 Renderer、确认或 Spec 流程；
- 本机全局 DeepSeek Harness `0.1.0-rc.6`，Web 健康检查通过。
- Harness 真实模型回合可用，并已在项目 Workspace 通过 Shell 执行 Data Foundation `--help`，退出码为 0，发现全部 7 个子命令。

真实三表已在 Harness 与 Data Foundation v2 上完成入仓、描述、质量和查询验证；主线 Bridge 1.2.0 对应现金明细与工单数据，S4 不再增加教务端口数据。教务跨端口 Bridge 验收是已完成的 S3.5 历史验证，不作为当前 PPT 交付输入。向导已用陌生四表 fixture 完成追加数据字典、关键确认和最终 build/validate。项目不建设正式宿主模型 Adapter、Customer Profile、项目侧 Session 管理或独立输出平台。MCP 不在当前开发计划内。

Data Foundation 不再保存企业 Sheet 白名单、业务列名或 `semantic.registration_cash`。企业表头与 `column_N` 的对应关系、枚举和清洗口径只进入 Company Bridge。

## 本地检查

```bash
python3 -m interfaces.data_foundation --help
python3 -m interfaces.business_pack validate
python3 -m interfaces.business_pack describe
python3 -m interfaces.company_bridge validate \
  --bridge artifacts/company_bridge/bridges/company_bridge.v1_2_0.json \
  --pack business_pack/packs/education_training_operations_cn/pack.json
python3 -m interfaces.bridge_alignment_wizard --help
python3 -m unittest discover -s tests -p 'test_*.py' -v
/Users/akechi/.local/bin/dsh --version
```

`data-foundation` 的完整命令和输入合同见 [接入指南](./docs/integration-guide.md)，Harness 启动与排障见 [运维手册](./docs/operator-runbook.md)。

## 当前状态

S5「Casebook、内测回收与引导路由」已完成：客户工作区支持案例候选/确认/检索/证据校验、版本化内测评价、默认脱敏反馈 ZIP、用户授权证据和本地引导。入口为 `python3 -m interfaces.casebook_pilot --help`，完整边界见 [S5 合同](./docs/casebook-pilot-contract.md)。

S4 Quick 的真实主线性能回归仍暂时挂起：代码、预检和自动化回归已具备，但新版冻结分析的双宿主 Quick 端到端验收尚未补齐。该项恢复时继续使用主线 Bridge 的现金明细与工单输入，不引入教务数据。

## 文档导航

- [权威架构](./docs/architecture.md)
- [开发规则](./开发文档.md)
- [分段施工计划](./分段施工计划.md)
- [接入指南](./docs/integration-guide.md)
- [Company Bridge v1 合同](./docs/company-bridge-contract.md)
- [Bridge 对齐向导合同](./docs/bridge-alignment-wizard-contract.md)
- [运维手册](./docs/operator-runbook.md)
- [S4 Quick PPT 宿主提示词](./docs/s4-ppt-quick-prompt.md)
- [S5 Casebook、内测回收与引导路由合同](./docs/casebook-pilot-contract.md)
- [交接状态](./docs/handoff.md)
- [DeepSeek Harness 调研卡](./research/projects/deepseek-harness.md)
