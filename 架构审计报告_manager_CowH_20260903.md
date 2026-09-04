# manager-CowH 架构审计报告

**审计日期**: 2026-09-03  
**审计目的**: 对照super_agent的架构问题和Anthropic设计原则，识别manager-CowH项目的架构风险  
**审计方法**: Read-only审计，基于代码结构、文档和设计原则对比

---

## 一、执行摘要

### 1.1 核心发现

manager-CowH项目**在正确的方向上**，但存在**局部过度复杂**和**架构边界模糊**的早期信号：

✅ **做对的部分**（70%）：
- 采用了"宿主Agent + 稳定CLI边界"的分离架构
- Data Foundation/Pack/Bridge三层语义分离清晰
- 使用确定性代码做门禁，而非LLM审计
- 避免了"总路由Agent"模式

⚠️ **风险信号**（30%）：
- `business-analysis-routing` Skill承担了过多职责（状态检查 + Casebook检索 + 分析编排 + 交付路由）
- PPT Master作为4200+行的固定上游，其内部复杂度未被隔离
- 宿主边界的"不要做什么"比"做什么"更长，说明边界容易被误解
- 缺乏独立Agent架构，所有分析仍通过单一"数据分析智能体"完成

### 1.2 与super_agent的对比

| 维度 | super_agent | manager-CowH | 判断 |
|------|-------------|--------------|------|
| 单体路由 | ✗ 8个workflow共享入口 | ✓ 无总路由Agent | 改进 |
| Agent职责 | ✗ 单Agent理解所有业务 | ⚠️ 单Agent + Skill路由 | 风险 |
| 确定性编排 | ✗ 自然语言指令 | ✓ Python CLI | 改进 |
| 共享配置 | ✗ 耦合在Agent内 | ✓ Pack/Bridge分离 | 改进 |
| 数据层 | ✗ 散乱 | ✓ DuckDB Snapshot | 改进 |
| 架构可扩展性 | ✗ 增量修补 | ⚠️ 边界模糊 | 风险 |

**核心判断**：manager-CowH避免了super_agent最严重的单体架构问题，但**正在朝向"单一复杂Agent"的方向演化**。

---

## 二、架构优势（已对齐Anthropic原则的部分）

### 2.1 宿主与业务逻辑分离 ✓

**设计**：
- Agent Host（DeepSeek Harness/Codex）负责对话、Session、模型调用
- 项目代码只暴露CLI、JSON、文件，不依赖特定宿主SDK
- 宿主可替换（已验证Codex和DeepSeek Harness双宿主）

**对照Anthropic原则**：✓ 符合"确定性编排"原则

**证据**：
- `README.md:5` - "两者都使用自身原生的Agent... 本项目不再包装一层Agent"
- `docs/architecture.md:35` - "项目不在宿主之上或之内再建设一层Agent、模型路由或对话调度"

### 2.2 三层语义分离 ✓

**设计**：
- **Data Foundation**: 原始数据、Snapshot、只读查询（不理解业务）
- **Business Pack**: 行业通用知识（不保存客户事实）
- **Company Bridge**: 企业术语映射（不替代Pack）

**对照Anthropic原则**：✓ 符合"单一职责"原则

**证据**：
- `docs/architecture.md:84-94` - 语义边界表
- `AGENTS.md:40-44` - 模块边界定义

### 2.3 确定性门禁 ✓

**设计**：
- 只读查询通过CLI强制执行
- Snapshot不可覆盖
- Bridge未确认映射阻断分析
- 门禁用代码校验，不是LLM审计

**对照Anthropic原则**：✓ 符合"确定性边界控制"原则

**证据**：
- `docs/architecture.md:68-80` - 确定性边界章节
- `AGENTS.md:32-36` - 数据与证据红线

---

## 三、架构风险（正在偏离Anthropic原则的信号）

### 3.1 单一"数据分析智能体"承担过多职责 ⚠️

**问题表现**：

从`README.md:3`的产品定义：
> "面向教育机构的**日常数据分析智能体**...支持持续追问、自由下钻、图表和交付物生成"

这个"日常数据分析智能体"实际上需要：
1. 状态检查（工作区是否初始化、Snapshot是否存在、Bridge是否对齐）
2. Casebook检索（历史案例匹配）
3. SQL生成（理解Pack + Bridge + 用户问题）
4. 数据分析（解释查询结果）
5. 交付路由（表格 vs 图表 vs PPT Quick vs PPT Master）
6. 案例沉淀（决定是否保存、如何保存）

**对照super_agent的教训**：
- super_agent的main agent需要理解8个workflow → 认知负载过大
- manager-CowH的"数据分析智能体"需要理解6个阶段 → **同样的模式**

**证据**：
- `.agents/skills/business-analysis-routing/SKILL.md:12-22` - 6步编排流程
- `AGENTS.md:14-21` - 日常分析路由（所有步骤都在一个流程里）

**为什么这是风险**：
- 当前只有"教育BI"一个业务场景，看起来可控
- 未来增加"教务分析"、"市场分析"、"财务分析"时，这个Agent会变成super_agent的翻版
- Skill的免责声明（"不是第二个Agent"）说明已经感受到了职责过载的压力

### 3.2 PPT Master的"固定上游"策略隐藏了复杂度 ⚠️

**问题表现**：

PPT Master作为4200+行Python文件的"固定上游"被整体引入：
- `.agents/skills/ppt-master/` 包含完整的workflow、scripts、templates
- 项目通过"不修改上游"来维持稳定性
- 但上游本身是一个**多路由、多角色、多阶段**的复杂Agent系统

**对照Anthropic原则**：
- Anthropic强调"给Agent工具，不是给Agent另一个Agent"
- PPT Master的`routing.md`、`generate-pptx.md`、多个profile本身就是一个**嵌套的Agent系统**

**证据**：
- `.agents/skills/ppt-master/SKILL.md:36-45` - 7种路由选择
- `.agents/skills/ppt-master/SKILL.md:55-63` - 8条全局执行规则
- `README.md:9` - "ppt-master v4.7.0 已按固定上游提交装配"

**为什么这是风险**：
- 当前通过"固定版本 + attribution guard"控制风险
- 但当需要扩展PPT能力时（例如教育行业特定模板），会面临：
  - 修改上游 → 破坏固定版本策略
  - 不修改上游 → 无法定制
  - 建第二套PPT流程 → 重复super_agent的"packet协议"问题

### 3.3 "宿主边界"的否定式描述过多 ⚠️

**问题表现**：

`business-analysis-routing` Skill的"宿主边界"章节：
> "本Skill是调用说明，**不是**第二个Agent Loop、**不是**Session管理器、**不是**SQL编译器、**不是**记忆库、**不是**后台任务。"

一口气列了5个"不是"，说明边界容易被误解。

**对照设计原则**：
- 好的接口设计应该是"做什么"清晰，而非"不做什么"冗长
- 需要大量否定式声明通常意味着职责分配不够清晰

**证据**：
- `.agents/skills/business-analysis-routing/SKILL.md:29-31` - 宿主边界章节
- `AGENTS.md:7-10` - 默认职责（也有很多否定式表述）

### 3.4 看板模块决策暴露了扩展路径不明确 ⚠️

**问题表现**：

`docs/handoff.md:45-50`记录了看板模块的决策：
> "看板能力先作为当前项目内的独立`dashboard/`模块开发，不新建数据镜像项目，也不引入MCP"

这个决策本身是合理的，但暴露了一个问题：
- 当需要增加新能力时，决策点是"作为当前项目的模块"还是"独立项目"？
- 为什么dashboard是模块，而不是独立Agent？
- 如果再增加"教务分析"，是模块还是独立Agent？

**对照super_agent的教训**：
- super_agent最初也是"增加模块"，最后演变成8个workflow的单体
- manager-CowH的扩展策略不清晰，容易重蹈覆辙

---

## 四、架构重构建议

### 4.1 核心方向：从"单一Agent + Skill路由"到"独立Agent架构"

**当前模式**（存在风险）：
```
用户 → 宿主 → "数据分析智能体" (+ business-analysis-routing Skill)
                     ↓
         状态检查 → Casebook → SQL生成 → 分析 → 交付路由 → 案例沉淀
```

**推荐模式**（对齐Anthropic原则）：
```
用户 → 宿主 → 人工选择具体Agent
                     ↓
        ┌────────────┼────────────┬────────────┬────────────┐
        ↓            ↓            ↓            ↓            ↓
   工作区初始化    探索性分析    固定报表    交付物生成   案例管理
     Agent         Agent        Agent        Agent       Agent
        ↓            ↓            ↓            ↓            ↓
      共享数据层（DuckDB Snapshot + Pack + Bridge）
```

### 4.2 独立Agent职责划分

#### Agent 1: 工作区初始化Agent
**职责**：
- 引导首次部署
- 导入数据并发布Snapshot
- Bridge对齐向导
- 状态检查与切换

**已有基础**：
- `onboarding/service.py`
- `.agents/skills/first-deployment-onboarding/`
- `bridge_alignment/service.py`

**重构方向**：
- 当前已经相对独立，继续保持
- 考虑独立成`.agents/onboarding-agent/`

#### Agent 2: 探索性分析Agent
**职责**：
- 理解自然语言问题
- 检索Casebook线索
- 生成SQL并执行查询
- 解释结果（口径、限制、来源）
- **不负责交付物生成**

**重构方向**：
- 从`business-analysis-routing`中拆分出"分析"部分
- 工具：`data_platform query`、`casebook-pilot case-search`
- 输出：查询结果 + 分析结论（文本/JSON）

#### Agent 3: 固定报表Agent
**职责**：
- 运行已确认的saved query
- 按固定格式输出
- 看板刷新
- **不做探索性分析**

**已有基础**：
- `dashboard/`模块（正在建设）
- `data_platform run-saved-query`

**重构方向**：
- 独立成`.agents/dashboard-agent/`
- 只读取配置，不调用LLM

#### Agent 4: 交付物生成Agent
**职责**：
- 接收已完成的分析结果（查询结果 + 结论）
- 根据需求生成表格/图表/PPT
- **不做数据分析**

**重构方向**：
- PPT Master可以作为这个Agent的一个"工具包"
- 或者拆分为：
  - Quick PPT Agent（简单、快速）
  - Master PPT Agent（复杂、定制）

#### Agent 5: 案例管理Agent
**职责**：
- 创建案例候选
- 验证证据哈希
- 确认案例
- 检索与推荐

**已有基础**：
- `casebook/service.py`
- `pilot_feedback/service.py`

**重构方向**：
- 当前嵌入在`business-analysis-routing`中
- 独立成`.agents/casebook-agent/`

### 4.3 重构后的用户体验

**当前**（所有请求都进同一个Agent）：
```
用户: "分析一下8月的现金流"
→ 宿主启动"数据分析智能体"
→ business-analysis-routing Skill
→ 状态检查 → Casebook → SQL → 分析 → 可选交付 → 可选案例
```

**重构后**（用户/宿主选择具体Agent）：
```
用户: "分析一下8月的现金流"
→ 宿主: "这需要探索性分析，启动分析Agent"
→ 探索性分析Agent
→ 输出查询结果 + 文本结论

用户: "做成PPT"
→ 宿主: "启动交付Agent"
→ 交付物生成Agent（读取上一个Agent的输出）
→ 生成PPT

用户: "这个分析以后要经常用"
→ 宿主: "启动案例管理Agent"
→ 案例管理Agent（保存查询 + 结论）
```

**优势**：
- 每个Agent职责单一，上下文干净
- 增加新业务场景（教务、市场、财务）只需增加新的"分析Agent"，不影响其他Agent
- PPT复杂度被隔离在"交付Agent"中，不污染分析Agent

### 4.4 共享数据层保持不变

**当前设计已经正确**：
- DuckDB Snapshot作为共享只读数据源
- Pack + Bridge提供语义层
- 所有Agent通过CLI访问，不直连DuckDB

**保持**：
```
所有Agent
   ↓
CLI边界（data_platform/business_pack/company_bridge/casebook）
   ↓
DuckDB Snapshot + Pack + Bridge
```

---

## 五、对比super_agent的改进验证

### 5.1 是否避免了单体路由？

| super_agent | manager-CowH当前 | manager-CowH重构后 |
|-------------|------------------|---------------------|
| ✗ main agent理解8个workflow | ⚠️ "数据分析智能体"理解6个阶段 | ✓ 5个独立Agent，人工/宿主路由 |
| ✗ AGENTS.md是路由表 | ⚠️ business-analysis-routing是编排 | ✓ 无中央路由 |

### 5.2 是否实现了确定性编排？

| super_agent | manager-CowH当前 | manager-CowH重构后 |
|-------------|------------------|---------------------|
| ✗ 自然语言指令编排 | ✓ Python CLI编排 | ✓ 保持 |
| ✗ packet协议让Agent理解 | ✓ 直接传递数据 | ✓ 保持 |

### 5.3 是否实现了Agent自主探索（需要时）？

| super_agent | manager-CowH当前 | manager-CowH重构后 |
|-------------|------------------|---------------------|
| ✗ 固定packet流程 | ✓ 探索性分析Agent有SQL生成能力 | ✓ 保持并增强（独立Agent） |
| - | ⚠️ 但探索能力与交付路由耦合 | ✓ 探索与交付分离 |

---

## 六、实施建议

### 6.1 不要立即重构

**原因**：
- 当前系统刚完成S5（Casebook + 内测反馈）
- 核心数据流已经稳定（Data Foundation + Pack + Bridge）
- 单业务场景（教育BI）下，当前架构的问题还未充分暴露

**建议**：
- 先完成S4 Quick PPT性能回归（handoff中的唯一待办）
- 观察dashboard模块的施工过程，看是否出现职责冲突

### 6.2 设立架构健康检查点

**触发重构的信号**：
- [ ] 需要增加第二个业务场景（教务/市场/财务分析）
- [ ] `business-analysis-routing` Skill超过200行
- [ ] 用户反馈"Agent理解错了我的意图"（上下文污染）
- [ ] 开发日志中"跨模块协调"问题 > 50%
- [ ] 需要修改PPT Master上游才能支持业务需求

**检查频率**：
- 每增加一个新功能后
- 每季度回顾一次

### 6.3 渐进式迁移路径

**第一步**（当需要第二个业务场景时）：
1. 复制`business-analysis-routing`为`bi-analysis-agent`
2. 创建新的`teaching-analysis-agent`（教务分析）
3. 让两者共享同一个数据层和Casebook
4. 观察是否出现代码重复 → 提取共享工具

**第二步**（当交付需求多样化时）：
1. 从分析Agent中拆出`delivery-agent`
2. 分析Agent只输出JSON（查询结果 + 结论）
3. 交付Agent读取JSON生成文件

**第三步**（当PPT需求与上游冲突时）：
1. 评估是fork PPT Master还是建立教育行业专用交付Agent
2. 如果fork，按Anthropic原则重构为独立工具集

### 6.4 文档先行

**在重构前**，先写清楚：
- 每个未来Agent的职责边界（30字以内描述）
- Agent间的数据流（输入/输出格式）
- 哪些是确定性编排，哪些是Agent自主探索
- 共享层（数据/配置）的访问协议

**参考super_agent审计报告**的"新架构方向"章节，写一份`docs/future-architecture.md`

---

## 七、证据索引

### 7.1 当前架构的正确部分
- `README.md:5-6` - 宿主与业务分离
- `docs/architecture.md:84-94` - 三层语义边界
- `docs/architecture.md:68-80` - 确定性门禁
- `AGENTS.md:40-44` - 模块边界清晰

### 7.2 风险信号
- `.agents/skills/business-analysis-routing/SKILL.md:12-22` - 单Agent 6步编排
- `.agents/skills/ppt-master/SKILL.md:36-45` - 嵌套Agent系统
- `.agents/skills/business-analysis-routing/SKILL.md:29-31` - 5个"不是"声明
- `docs/handoff.md:45-50` - 扩展策略不明确

### 7.3 Anthropic设计原则参考
- [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)
- super_agent审计报告：`/Users/akechi/Desktop/super_agent/架构审计报告_20260903.md`

---

## 八、总结

### 8.1 核心判断

manager-CowH项目**在正确的轨道上**，已经避免了super_agent最严重的架构问题（单体路由、自然语言编排、配置耦合）。

但**存在早期预警信号**，显示系统正在朝"单一复杂Agent"方向演化：
- 当前的"数据分析智能体"承担过多职责
- PPT Master的复杂度被"固定上游"策略隐藏，未真正隔离
- 扩展策略不清晰，容易重蹈super_agent的"增量修补"陷阱

### 8.2 行动建议

**短期**（1-2个月）：
- 不要立即重构，先完成S4 Quick PPT回归
- 设立架构健康检查点
- 写`docs/future-architecture.md`，明确未来扩展路径

**中期**（3-6个月，当需要第二个业务场景时）：
- 按"独立Agent架构"重构
- 拆分：探索性分析 / 固定报表 / 交付物生成 / 案例管理
- 共享数据层保持不变

**长期**（持续）：
- 对照Anthropic原则定期审计
- 避免"增量修补"陷阱
- 换Agent做架构审计（不要让维护者自己审计）

### 8.3 关键原则（来自super_agent教训）

1. **按业务场景拆分Agent，不是按技术层**
2. **人工/宿主做路由，不是LLM**
3. **确定性代码做编排，Agent做分析**
4. **给工具不限路径（探索时），用框架控制边界**
5. **门禁用代码不是LLM**
6. **定期切换Agent做审计**

---

**报告完成日期**: 2026-09-03  
**下一步**: 观察dashboard模块施工，决定是否启动独立Agent架构重构
