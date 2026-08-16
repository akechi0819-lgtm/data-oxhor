# Education Business Analyst

面向教育机构的对话式业务分析系统。它把脏 Excel 转成可追溯的数据快照，再用教育行业知识和企业语义映射支撑持续追问、自由下钻、图表和交付物生成。

项目不绑定默认 Agent Host。Codex、[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)、Hermes 或其他具备受控 Shell 的宿主负责对话、Session、模型和工具调用；本项目目录封装可跨宿主复用的数据、业务语义、分析证据门禁、输出和学习资产。Data Foundation 通过稳定 Python CLI 暴露，不需要额外 MCP 服务。

## 架构一览

```text
      Codex / DeepSeek Harness / Hermes / 其他 Agent Host
        对话 / Session / 模型 / Skills / 受控 Shell
                               │ CLI / files / JSON
                 Customer Profile（只做选择和装配）
                               │
     ┌──────────────┴──────────────┐
     │                             │
Data Foundation              Pack + Bridge
脏数据/Snapshot              行业 + 企业语义
     │                             │
     └──────────────┬──────────────┘
                    │
        Analysis Record + Evidence Gate
                    │
             Skill + Renderer
                               │
                  学习与质量工作区（宿主无关）
           Memory / Good Case / Bad Case / Eval / Promotion
```

核心边界：

- Data Foundation 不理解教育业务，只做无计划 landing、身份、Snapshot、结构质量和只读查询；
- Business Pack 不伪装成某家企业事实；
- Company Bridge 不与 Pack 合并，即使第一家企业存在少量内容重复；
- Skill 指导模型，确定性工具负责数据权限、身份、计算、结论—证据绑定和文件生成；
- 不保存模型逐 Token 私有思考链；正式资产保存可审计的 Analysis Record；
- 无证据、身份冲突或使用未确认映射的 claim 不得进入正式回答和文件；
- CLI 是 Data Foundation 的唯一公开入口；宿主可替换性不依赖 MCP；
- 只读、Snapshot 不覆盖、unresolved 阻断和文件验收由对应模块的确定性代码承担，不建设独立强化层；
- 宿主 Session 是短期对话记忆，长期业务学习进入独立工作区；
- 交互表格和宿主专属 UI 可以增强体验，但不能成为核心分析能力或静态交付的依赖。

## 已实现

- XLSX 全 Sheet 可选探查和 OOXML 流式读取；
- 所有 Sheet 无 cleaning plan 直接进入 `landing.column_N`，保留源单元格值、源行号和来源身份；
- 不可变 Snapshot、DuckDB 与每 Sheet 一份 Parquet；
- Schema 描述、数据质量问题、受控只读 SQL、保存查询；
- `run_id`、Snapshot 身份、源 SHA-256 绑定和最小 Artifact manifest；源 SHA-256 只作为 inspect/ingest 与 manifest 的内部完整性信息；
- 22 项现行 Python 测试；
- DeepSeek Harness `0.1.0-rc.6` 已作为可选宿主完成真实 headless 验收；Codex 可直接调用同一 CLI，Hermes 尚待真实验收。

尚未实现：Education Business Pack、Company Bridge、Analysis Contract/Evidence Gate、Customer Profile、输出模块和学习与质量工作区。MCP 不在当前开发计划内。

Data Foundation 不再为已知日报维护特定 Sheet/表名映射，也不生成 `semantic.registration_cash`。标题行、矩阵、多行表头和字段漂移不阻塞 landing；Python 不判断空格、编号、数字、日期或文本。模型在入仓后通过 `ingest.sheets` 找到目标表，自主用只读 SQL 清洗、转换类型和组合计算；存在多个合理业务解释或需要长期固化时再请求人工确认。

## 本地检查

```bash
python3 -m interfaces.data_foundation --help
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

`data-foundation` 的完整命令、宿主能力要求和兼容状态见 [接入指南](./docs/integration-guide.md)，本地验证和可选宿主排障见 [运维手册](./docs/operator-runbook.md)。

## 唯一下一步

开始 Education Business Pack 的最小切片，先定义宿主无关的行业概念与指标合同；Pack 稳定后建设当前企业 Company Bridge，再建设 Analysis Contract/Evidence Gate。正式输出前，每个 claim 必须能反查 Snapshot、查询结果和 Pack/Bridge 口径。不得把企业字段映射、表头选择、清洗口径或证据门禁写回 Data Foundation。

## 文档导航

- [权威架构](./docs/architecture.md)
- [开发规则](./开发文档.md)
- [分段施工计划](./分段施工计划.md)
- [接入指南](./docs/integration-guide.md)
- [运维手册](./docs/operator-runbook.md)
- [交接状态](./docs/handoff.md)
- [DeepSeek Harness 调研卡](./research/projects/deepseek-harness.md)
