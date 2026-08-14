# DeepSeek Harness 调研卡

## 基本信息

- Repository: https://github.com/deepseek-ai/deepseek-harness
- Checked at: 2026-08-14
- Source review commit: `47f943859bef60e4160492346772ded9b24f765a`
- Installed npm version: `0.1.0-rc.6`
- npm integrity: `sha512-brpZfED7ieRa2PQ5tUxMhHrM1pb2CmKFVM/f6yMULBDMicahk+Z2OsHgTwTDnoiZm23Ftu9rQz0NN4pflaoJcg==`
- Global command: `/Users/akechi/.local/bin/dsh`
- Shared runtime home: `/Users/akechi/.dsh`
- License: MIT
- Status: Developer Preview；上游明确提示未来会有破坏兼容的变更

## 对应能力

- Web 对话与持续 Session；
- Cordis 插件生命周期和 `ctx.<service>` 服务装配；
- Skills、Tools、MCP Client、模型 Provider；
- Session JSONL/SQLite、压缩、查询和投影；
- 文件交付 UI、自定义 Conversation Node 和 Client Plugin；
- Profile/Bundle 级部署组合。

## 采用决策

作为 Education Business Analyst 的目标 Agent 运行宿主，替代自建通用 Agent Loop、对话 UI、插件生命周期和多数工作流编排。

选择理由不是安装包体积小，而是运行时职责中性、插件能力可裁剪。相比自带长期记忆和固定工作习惯的成型智能体，它更容易只承担 Session、对话和工具装配，避免与本项目的 Memory、Cases、Eval 和 Promotion 形成双重长期事实来源。

项目业务模块保持独立：

- Data Foundation 通过受控 Shell 直接调用现有 Python CLI；不建设 MCP 服务；
- Education Business Pack 独立插件；
- 每家企业使用独立 Company Bridge 插件；
- Customer Profile 组合 Pack、Bridge、Data 和 Skills；
- 需要 Harness 生命周期或自定义 UI 时才编写原生 TypeScript 插件。

## 不采用

- 不把 DeepSeek Harness Session 当作完整业务 Artifact Registry；
- 不把 Business Pack 与 Company Bridge 合并；
- 不预设存在官方 PPT、Spreadsheet 或图表插件市场；
- 不在验证期修改上游源码或把业务逻辑写入上游 checkout；
- 不因宿主是 TypeScript 而重写成熟 Python 数据代码。

## 验证项目

1. Web UI 启动和本地访问；
2. Session 创建、持久化和重启恢复；
3. 项目 `.agents/skills` / `.dsh/skills` 发现；
4. Python CLI 的模型侧调用、超时和错误处理；
5. 文件生成和 Deliverables 展示；
6. Customer Profile 装配 Pack、Bridge 和 Data 插件；
7. 连续追问中 Snapshot、Pack 和 Bridge 身份保持稳定。

## 2026-08-14 部署验证

- `dsh --version` 返回 `0.1.0-rc.6`；
- `dsh web --host 127.0.0.1 --port 3080` 启动成功；
- `http://127.0.0.1:3080` 返回 HTTP 200；
- 首次初始化和中文 Web UI 正常；
- 插件管理页识别 133 个条目；
- Session JSONL、Session Query SQLite、Storage、Sandbox、Approval、Workspace、Deliverables、Skill、Subagent、Plan、Trajectory 等服务已观察到装载；
- 未选择 Workspace 时，文件和 Skill consumer 等依赖能力保持停用，未出现半初始化假成功；
- 尚未配置模型 API Key，真实模型回合、Session 恢复、项目 Skill 调用和 Deliverable 生成待验证。

## 开放风险

- 无正式稳定 Tag，升级可能破坏插件接口；
- 真实模型通过受控 Shell 调用项目 CLI 的能力尚未验收；
- 间接生成的文件可能需要原生工具展示元数据才能进入 Deliverables；
- 交互图表需要验证或开发 Client Plugin。

## 当前使用边界

- DeepSeek Harness 是默认宿主，不是业务核心；
- Data Foundation、Pack、Bridge、Renderer 和学习资产必须保持宿主无关；
- 当前唯一接入工作是让 Codex 与 DeepSeek Harness 调用同一 Data Foundation CLI；不建设 MCP 或 echo 插件；
- `0.1.0-rc.6` 的部署结果不能代替真实模型、Session、CLI 调用和 Deliverables 验收。
