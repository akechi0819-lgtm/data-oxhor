# Analysis Product

## 产品边界

`analysis_product/` 是自由分析未来可扩展的确定性代码边界。当前不包含 PPT 生成器、PPT 路由器或交付编排代码；开放式分析由宿主 Agent 编排，PPT 交付由宿主全局 `ppt-master` Skill 负责。

开放式分析的自然语言入口仍是宿主 Skill：

```text
.agents/skills/business-analysis-routing/SKILL.md
```

该 Skill 负责告诉宿主如何检查工作区、检索 Casebook、向用户确认问题、生成候选 SQL，并调用 `interfaces.data_platform` 的受控查询。它不是本目录的 Python 子模块，也不执行 Agent Loop、Session 管理、模型路由或 SQL 编译。

## 调用关系

```text
宿主 Agent
  -> business-analysis-routing Skill（自然语言路由和对话边界）
  -> interfaces.data_platform（当前 Snapshot 的受控查询）
  -> 宿主原生交付能力 / 全局 ppt-master（按需）
  -> 客户工作区 Output/（带身份的交付物）
```

因此，分析入口“在 Skill 中”是有意的宿主边界，不代表存在第二个 Agent。未来增加确定性分析代码时，应放在本目录，并由 Skill 通过明确 CLI 或脚本调用；不要把宿主提示词复制成另一套路由器。

## 当前状态

- 开放式分析路由：由 `.agents/skills/business-analysis-routing` 提供；
- PPT：项目不再内置 Quick 实现或 PPT Master 副本，宿主根据需求调用全局 `ppt-master` 的 Quick 或 Default 路由；
- 独立分析 CLI、异常下钻编排和通用分析 artifact：尚未开始，避免在没有稳定合同前提前抽象。
