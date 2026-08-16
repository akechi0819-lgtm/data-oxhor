# 项目交接状态

## 截止 2026-08-14 已完成

- 确定项目不设默认宿主：版本化项目目录是可移植核心，Codex、DeepSeek Harness、Hermes 等具备受控 Shell 的宿主按部署选择；
- 全局安装并静态验证 DeepSeek Harness `0.1.0-rc.6`；
- 完成 Data Foundation 的可选 XLSX 探查、所有 Sheet 无计划原始 landing、不可变 DuckDB/Parquet Snapshot、结构质量、只读 SQL 和保存查询；
- Data Foundation 使用 `run_id`、显式 Snapshot 身份和最小 Artifact manifest；源 SHA-256 保留在 inspect/ingest 与 manifest 内部，不作为跨 Session 强制字段；
- 确定 CLI 是 Data Foundation 唯一公开入口，Codex、DeepSeek Harness 等具备受控 Shell 的宿主直接调用同一 CLI；
- 明确宿主切换不影响 Data Foundation、Pack/Bridge、静态输出和学习质量资产；交互表格、Session、审批和文件展示属于可选宿主体验；
- 确定当前不建设 MCP 或宿主专属强化插件，确定性约束由对应业务模块直接实现；
- 删除已废弃的 Codex→Hermes handoff schema、validator 和 5 项相关测试；
- 删除特定源表映射和 `semantic.registration_cash`，ingest 不再接收或依赖 cleaning plan；
- 22 项现行 Python 测试通过；
- DeepSeek Harness 真实 headless 模型已在不运行 inspect、不生成 cleaning plan 的条件下，将 3 个跨部门真实 XLSX 的 6 个 Sheet、47,087 个有内容行直接 landing，并在入仓后自主识别表头、转换数值和完成汇总；
- 模型入仓后通过项目 query CLI 查询 `ingest.sheets`、预览 6 张 landing 表，并准确汇总四张排课表的行数与课时/分钟；
- 明确 Pack 与 Bridge 从第一家企业起物理分离；
- 明确 Customer Profile 只是薄装配；
- 明确长期业务学习进入独立学习与质量工作区，而不是宿主 Session；
- 在项目根初始化 Git 仓库，默认分支为 `main`，尚无首个提交。

## 尚未完成

- Education Business Pack；
- 当前企业 Company Bridge，包括疑似字段人工确认、结构化口径固化和不可变规范层发布；
- Analysis Contract、Analysis Record 和 Evidence Gate；
- 首个 Customer Profile；
- 输出模块和确定性 Renderer；
- 学习与质量工作区。

## 唯一下一步

开始 Education Business Pack 的最小切片：定义行业概念、指标、漏斗和适用条件，不引用当前企业表名或 `column_N`。Pack 合同稳定后建设 Company Bridge，让模型在 landing 后自主判断清洗和类型；只有合理歧义或长期固化才进入“人工确认 → Bridge 固化 → 确定性转换 → 不可变规范层发布”。Bridge 之后建设 Analysis Contract/Evidence Gate，再进入 Customer Profile 和输出。不要在 Data Foundation 恢复表头选择、cleaning plan、业务语义视图或结论门禁。

## 已冻结的必备改动（2026-08-14 / Stage 3）

- 决定：空格、编号、数字、日期、文本和候选字段由模型在 landing 后自主判断并生成受控 SQL；证据明确的查询级清洗无需逐项确认。存在多个合理业务解释或需要长期固化时，才用自然语言向用户确认并将结果结构化、版本化写入 Company Bridge。
- 原因：企业口径需要可追溯和复用，不能让模型每次重新猜，也不能只保存在宿主 Session。
- 影响：转换由确定性 SQL/Python 执行并发布新的不可变规范表或 Snapshot；原始 landing 不覆盖，未确认项保持 `unresolved`。
- 验收：至少用一个多候选字段 Golden Case 精确比对 Bridge 记录、转换 SQL、规范字段值和未确认阻断行为。
- 当前状态：合同已记录，尚未实现；不影响 Data Foundation 数据接入模块已经验收成功的结论。

## 已冻结的必备改动（2026-08-14 / Stage 4）

- 决定：新增宿主无关的 Analysis Contract 和确定性 Evidence Gate，位于 Pack/Bridge 之后、Customer Profile 和输出之前。
- 原因：现有 Data Foundation 只能证明数据与查询可追溯，不能阻止模型发布没有证据绑定的业务结论。
- 影响：Analysis Skill/Pack Playbook 指导问题拆解、假设、替代解释和反证；模型提交可审计推理摘要。正式 claim 必须绑定 Snapshot、查询/结果、Pack 指标和 Bridge 映射。门禁返回 `supported / conditional / blocked`，Renderer 不得消费 `blocked`。
- 隐私边界：不保存或要求模型逐 Token 私有思考链，只保存结论、方法、证据、假设、反证和限制。
- 验收：用合法/非法 Golden Case 验证无证据、身份冲突、未确认映射和证据冲突的阻断行为。
- 当前状态：合同已记录，尚未实现；现有模型汇总是 Data Foundation 接入证据，不代表已经通过结论证据门禁。

## 已知阻塞与风险

- DeepSeek Harness 是 Developer Preview，其插件风险只影响选择该宿主的部署，不阻塞项目核心；
- Hermes 尚未做本项目真实端到端验收，只能声明接口结构兼容；
- 各宿主的交互表格和文件展示能力不同，静态 Renderer 必须保持独立可用；
- landing 保留源布局但不解释表头、日期序列、时间小数或矩阵块；这些必须由入仓后 SQL、Pack/Bridge 处理；
- 当前还没有 Analysis Record/Evidence Gate，正式回答和 Renderer 暂无“结论必须绑定证据”的确定性阻断；
- 当前结构质量只报告 XLSX/Sheet 级可复现问题，不把“矩阵看起来复杂”误报为数据质量错误；
- Git 仓库尚无首个提交，因此当前仍没有可引用的项目 commit hash。

## 技术依据

- [DeepSeek Harness 调研卡](../research/projects/deepseek-harness.md)
