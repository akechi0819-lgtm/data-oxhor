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
                  真实使用中的按需沉淀
               Skill / Template / Pack / Bridge
```

核心边界：

- Data Foundation 不理解教育业务，只负责原始 landing、身份、质量和受控只读查询；
- Business Pack 不伪装成某家企业事实；
- Company Bridge 不与 Pack 合并，即使第一家企业存在少量内容重复；
- Skill 指导模型，确定性工具负责数据权限、身份、计算和文件生成；
- CLI 是 Data Foundation 的唯一公开入口；宿主可替换性不依赖 MCP；
- 只读、Snapshot 不覆盖、unresolved 阻断和文件验收由对应模块的确定性代码承担，不建设独立强化层；
- 宿主 Session 是短期对话记忆，长期业务学习进入独立工作区；
- DeepSeek 专属交互 UI 可以增强体验，但不能成为核心分析能力的唯一入口。

## 已实现

- XLSX 全 Sheet 探查和 OOXML 流式读取；
- 所有 Sheet 无需 cleaning plan 直接进入通用 `landing.column_N`，并发布不可变 DuckDB/Parquet Snapshot；
- Schema 描述、数据质量问题、受控只读 SQL、保存查询；
- `run_id`、Snapshot 身份、源 SHA-256 绑定和最小 Artifact manifest；源 SHA-256 只作为 inspect/ingest 与 manifest 的内部完整性信息；
- Education Business Pack v1：28 个概念、20 个指标、26 个维度、三段客户旅程、3 个漏斗和 7 个诊断 Playbook；
- Pack 的 `validate` / `describe` CLI 与确定性交叉引用校验；
- Company Bridge 1.2.0：3 个当前源合同、10 个字段映射、105 条归一规则和 1 个企业 Override；
- Bridge 对齐向导 v1：提供自包含 `Input/Work/Output` 客户工作区、稳定数据源槽位和月度替换同步；工作区只保留当前 Snapshot，刷新成功后清理旧 Snapshot，宿主原生模型提出候选并收集关键确认，确定性服务自动生成 confirmed_review、build 和 Snapshot validate；
- 项目 Skill `diagnose-source-overlap`：提示模型主动检查全量刷新、日期范围、候选业务键、重复率和冲突；客户确认后用现有保存查询固化去重，不增加专用重叠平台；
- 61 项现行 Python 测试；
- 本机全局 DeepSeek Harness `0.1.0-rc.6`，Web 健康检查通过。
- Harness 真实模型回合可用，并已在项目 Workspace 通过 Shell 执行 Data Foundation `--help`，退出码为 0，发现全部 7 个子命令。

真实三表已在 Harness 与 Data Foundation v2 上完成入仓、描述、质量和查询验证；Bridge 1.2.0 已通过同一 Snapshot 的兼容性校验。向导已用陌生四表 fixture 完成追加数据字典、关键确认和最终 build/validate；三张真实教务表也已由 Harness 原生模型完成陌生结构识别、教务 Bridge、教师课量查询和图表输出。项目不建设正式宿主模型 Adapter、Customer Profile、项目侧 Session 管理或独立输出平台。MCP 不在当前开发计划内。

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

## 下一步

当前进入 S4：先讨论并选定项目需要的最小交付 Skills 组合，重点评估 PPT Master、电子表格和数据可视化能力；确认来源、许可证和宿主兼容性后放入项目，再用现有教务查询完成真实交付物验收。S4 后进入真实使用，重复需求再沉淀 Skill 或模板，不预建后续平台。企业口径继续进入 Bridge，不回填 Pack 或 Data Foundation。

## 文档导航

- [权威架构](./docs/architecture.md)
- [开发规则](./开发文档.md)
- [分段施工计划](./分段施工计划.md)
- [接入指南](./docs/integration-guide.md)
- [Company Bridge v1 合同](./docs/company-bridge-contract.md)
- [Bridge 对齐向导合同](./docs/bridge-alignment-wizard-contract.md)
- [运维手册](./docs/operator-runbook.md)
- [交接状态](./docs/handoff.md)
- [DeepSeek Harness 调研卡](./research/projects/deepseek-harness.md)
