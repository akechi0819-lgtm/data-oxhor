# Education Business Analyst

面向教育机构的对话式业务分析系统。它把脏 Excel 转成可追溯的数据快照，再用教育行业知识和企业语义映射支撑持续追问、自由下钻、图表和交付物生成。

默认客户运行宿主是 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)。Harness 负责对话、Session、模型、Skills 和插件装配；本项目建设可跨宿主复用的数据、业务语义、输出和学习资产。Data Foundation 通过稳定 Python CLI 暴露，Codex、DeepSeek Harness 或其他具备受控 Shell 的宿主调用同一入口，不需要额外 MCP 服务。

## 架构一览

```text
      DeepSeek Harness（默认）/ Codex / 其他 Agent Host
        对话 / Session / 模型 / Skills / 受控 Shell
                               │ CLI / files / JSON
                 Customer Profile（只做选择和装配）
                               │
     ┌──────────────┬──────────┴─────────┐
     │              │                    │
Data Foundation  业务语义组          输出与交付
脏数据/Snapshot  Pack + Bridge       Skill + Renderer
     │              │                    │
     └──────────────┴──────────┬─────────┘
                               │
                  学习与质量工作区（宿主无关）
           Memory / Good Case / Bad Case / Eval / Promotion
```

核心边界：

- Data Foundation 的目标边界是不理解教育业务；当前代码中的特定语义视图已在下文明确标为边界债务；
- Business Pack 不伪装成某家企业事实；
- Company Bridge 不与 Pack 合并，即使第一家企业存在少量内容重复；
- Skill 指导模型，确定性工具负责数据权限、身份、计算和文件生成；
- CLI 是 Data Foundation 的唯一公开入口；宿主可替换性不依赖 MCP；
- 只读、Snapshot 不覆盖、unresolved 阻断和文件验收由对应模块的确定性代码承担，不建设独立强化层；
- Harness Session 是短期对话记忆，长期业务学习进入独立工作区；
- DeepSeek 专属交互 UI 可以增强体验，但不能成为核心分析能力的唯一入口。

## 已实现

- XLSX 全 Sheet 探查和 OOXML 流式读取；
- 技术表头规范化、不可变 Snapshot、DuckDB 与 Parquet 入仓；
- Schema 描述、数据质量问题、受控只读 SQL、保存查询；
- `run_id`、Snapshot 身份、源 SHA-256 绑定和最小 Artifact manifest；源 SHA-256 只作为 inspect/ingest 与 manifest 的内部完整性信息；
- 21 项现行 Python 测试；
- 本机全局 DeepSeek Harness `0.1.0-rc.6`，Web 健康检查通过。

尚未实现：Education Business Pack、Company Bridge、Customer Profile、输出插件和学习与质量工作区。真实 Harness 模型回合、CLI 调用、Session 恢复和 Deliverables 也尚未验收，因为本机没有配置模型 API Key。MCP 不在当前开发计划内。

当前代码仍为已确认脏数据语料保留了特定源表映射和 `semantic.registration_cash` 视图；这是已实现事实，不代表 Data Foundation 已完成通用教育语义层。

## 本地检查

```bash
python3 -m interfaces.data_foundation --help
python3 -m unittest discover -s tests -p 'test_*.py' -v
/Users/akechi/.local/bin/dsh --version
```

`data-foundation` 的完整命令和输入合同见 [接入指南](./docs/integration-guide.md)，Harness 启动与排障见 [运维手册](./docs/operator-runbook.md)。

## 唯一下一步

直接用现有 CLI 完成宿主接入验证：先确认 Codex 能调用 `python3 -m interfaces.data_foundation`，再在用户配置模型 Provider 后验证 DeepSeek Harness 的真实多轮调用、Session 恢复和小型文件交付。当前不增加 MCP、独立强化插件或统一 SHA-256 传播层，也不并行开发 Pack、Bridge 或 PPT。

## 文档导航

- [权威架构](./docs/architecture.md)
- [开发规则](./开发文档.md)
- [分段施工计划](./分段施工计划.md)
- [接入指南](./docs/integration-guide.md)
- [运维手册](./docs/operator-runbook.md)
- [交接状态](./docs/handoff.md)
- [DeepSeek Harness 调研卡](./research/projects/deepseek-harness.md)
