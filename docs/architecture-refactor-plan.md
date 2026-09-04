# manager-CowH 架构重构方案

**制定日期**: 2026-09-03  
**目标**: 从"单一智能体+模块"改为"独立Agent架构"，支持安全增量扩展  
**原则**: 按业务场景拆分，共享数据层，确定性编排

---

## 一、当前问题诊断

### 1.1 现状
所有功能都挂在"数据分析智能体"下：
- 数据仓库（Data Platform）
- 探索性分析（business-analysis-routing）
- PPT生成（ppt-master，4200+行）
- **看板推送**（正在施工）
- **未来：日常监控固定流推送**（类似Jenny）

### 1.2 核心风险
1. **职责耦合**：看板推送、日常监控、探索性分析混在同一个Agent上下文
2. **调试困难**：一个模块出问题，无法隔离，影响整体
3. **重复super_agent模式**：当前6个阶段，再加看板+监控会变成8+个workflow
4. **PPT模块臃肿**：4200+行固定上游，与业务分析强制共存

### 1.3 触发重构的信号（已出现）
✅ 需要增加第二个场景（看板推送 ≠ 探索性分析）  
✅ 需要增加第三个场景（日常监控 ≠ 探索性分析 ≠ 看板推送）  
✅ 明确意识到"早晚要出事"

---

## 二、新架构设计

### 2.1 总体结构

```
manager-CowH/
├── shared/                          # 共享数据层（所有Agent共用）
│   ├── data_warehouse/              # 数据仓库（原data_platform）
│   │   ├── ingestion/               # 数据导入、Snapshot发布
│   │   ├── query/                   # 受控只读查询
│   │   └── snapshots/               # DuckDB快照存储
│   ├── business_metadata/           # 业务元数据（原Pack + Bridge）
│   │   ├── packs/                   # 行业知识包
│   │   └── bridges/                 # 企业映射
│   └── casebook/                    # 案例库（所有Agent共享）
│
├── agents/                          # 独立Agent（按业务场景拆分）
│   ├── workspace_setup/             # 工作区初始化Agent
│   │   ├── agent.md                 # Agent定义
│   │   ├── tools/                   # 专属工具
│   │   └── skills/                  # 专属Skills
│   ├── ad_hoc_analysis/             # 探索性分析Agent
│   │   ├── agent.md
│   │   ├── tools/                   # 数据查询、SQL生成
│   │   └── skills/
│   │       ├── presentation/        # 交付物生成Skill（PPT/图表/表格）
│   │       │   ├── ppt_master/      # PPT Master工作流
│   │       │   ├── chart_templates/ # 图表模板
│   │       │   └── table_export/    # 表格导出
│   │       └── casebook_integration/ # 案例检索与沉淀
│   ├── dashboard_publisher/         # 看板推送Agent
│   │   ├── agent.md
│   │   ├── tools/
│   │   ├── skills/
│   │   └── web/                     # Web UI资源
│   └── daily_monitor/               # 日常监控Agent（未来）
│       ├── agent.md
│       ├── tools/
│       └── skills/
│
├── orchestration/                   # 编排层（确定性Python代码）
│   ├── harness_integration.py       # 宿主适配（DeepSeek/Codex）
│   └── agent_selector.py            # Agent路由逻辑（确定性）
│
└── customers/                       # 客户工作区（不变）
    └── <company_id>/
        ├── Input/
        ├── Work/
        └── Output/
```

### 2.2 核心设计原则

#### 原则1: 按业务场景拆分Agent，不按技术层
- ❌ 错误：data层、logic层、presentation层
- ✅ 正确：初始化、分析、看板、监控、交付

#### 原则2: 共享数据层，独立业务逻辑
- `shared/` 目录提供统一CLI接口
- 各Agent通过CLI访问，不直连DuckDB
- 数据层不理解业务（保持当前设计）

#### 原则3: 确定性编排，Agent做分析
- `orchestration/` 是Python代码，不是LLM
- 根据用户意图选择Agent（代码逻辑，非自然语言路由）
- Agent内部可以自主探索（需要时）

#### 原则4: 单一职责，最小上下文
- 每个Agent只理解自己的业务
- 看板推送Agent不需要知道"什么是探索性分析"
- 日常监控Agent不需要加载PPT Master

---

## 三、各Agent职责定义

### Agent 1: workspace_setup（工作区初始化）

**职责**：
- 首次部署引导
- 数据导入与Snapshot发布
- Bridge对齐向导
- 工作区状态检查

**输入**：用户提供数据文件、业务端口
**输出**：初始化完成的工作区 + 可用Snapshot

**工具**：
- `data_warehouse ingest`
- `data_warehouse publish-snapshot`
- `business_metadata align-bridge`

**何时使用**：
- 用户说"首次部署"、"导入数据"、"建立Bridge"
- 工作区不存在或Snapshot缺失时

**已有基础**：
- `onboarding/service.py`
- `.agents/skills/first-deployment-onboarding/`
- `bridge_alignment/service.py`

---

### Agent 2: ad_hoc_analysis（探索性分析）

**职责**：
- 理解自然语言问题
- 检索Casebook历史案例
- 生成SQL并执行查询
- 解释结果（口径、限制、来源）
- **根据需要生成交付物**（PPT/图表/表格，通过内置Skill）

**输入**：用户的自然语言问题 + 可选的交付需求
**输出**：
- 查询结果（JSON）
- 分析结论（markdown）
- 可选：PPT/图表/表格文件
- 可选：保存为saved query

**工具**：
- `data_warehouse describe`
- `data_warehouse query`
- `casebook search`
- `casebook create-candidate`

**内置Skills**：
- `presentation/ppt_master/` - PPT生成工作流（大纲→确认→正文）
- `presentation/chart_templates/` - 图表生成
- `presentation/table_export/` - 表格导出

**何时使用**：
- 用户问"分析一下8月现金流"
- 用户问"为什么校区A下降了并做成PPT"
- 探索性、开放式问题 + 可选的交付需求

**何时不使用**：
- "生成看板"（→ dashboard_publisher）
- "每天推送"（→ daily_monitor）
- 固定报表刷新（→ dashboard_publisher）

**为什么PPT是Skill而非独立Agent**：
- PPT需要结合分析过程生成（例如：发现异常→下钻→总结→生成页面）
- PPT Master工作流需要Agent上下文（大纲阶段已经理解了数据）
- 分离会导致重复查询或上下文丢失

**已有基础**：
- `.agents/skills/business-analysis-routing/` 的分析部分
- `.agents/skills/ppt-master/` 作为Skill
- `casebook/service.py`

---

### Agent 3: dashboard_publisher（看板推送）

**职责**：
- 运行**已确认的固定SQL**
- 生成聚合JSON/HTML
- 推送到服务器
- **不做探索性分析、不调用LLM决定口径**

**输入**：
- 配置文件（哪些saved query、推送地址）
- Snapshot ID

**输出**：
- 看板数据文件（JSON/HTML）
- 推送状态（成功/失败）

**工具**：
- `data_warehouse run-saved-query`（固定SQL）
- `dashboard render`（生成HTML）
- `dashboard push`（推送到服务器）

**何时使用**：
- 用户说"刷新看板"、"推送最新数据"
- 定时任务触发

**何时不使用**：
- 用户问"为什么XX指标变化了"（→ ad_hoc_analysis）
- 第一次创建看板口径（→ ad_hoc_analysis先确认SQL，再保存）

**正在施工**：
- `dashboard_product/` 模块
- `docs/handoff.md:52-59` - 看板施工状态

**设计要点**：
- 设计期：用ad_hoc_analysis探索确认SQL → 保存为saved query
- 日常期：dashboard_publisher只运行saved query，不调用LLM

---

### Agent 4: daily_monitor（日常监控，未来）

**职责**：
- 按固定规则检查异常（类似Jenny）
- 运行诊断SQL
- 生成告警（邮件/消息）
- **不做探索性分析**

**输入**：
- 监控规则配置
- Snapshot ID

**输出**：
- 异常报告
- 告警消息

**工具**：
- `data_warehouse run-saved-query`
- `monitor check-rules`
- `monitor send-alert`

**何时使用**：
- 定时任务（每日/每周）
- 用户说"检查异常"

**何时不使用**：
- 用户问"为什么异常"（→ ad_hoc_analysis）

**与super_agent Jenny的区别**：
- ✓ 独立Agent，不与PPT/分析混在一起
- ✓ 只运行固定规则，不做动态分析
- ✓ 检测到异常后，可以启动ad_hoc_analysis深入调查

---

## 四、Agent间协作模式

### 4.1 典型场景1：探索性分析 + PPT交付

**用户意图**："分析8月现金流并做成PPT"

**流程**：
```
1. 宿主识别意图：探索性分析 + 需要PPT交付
2. 启动ad_hoc_analysis Agent
   - 查询Casebook
   - 生成SQL并执行查询
   - 分析数据，发现关键问题
   - 调用内置presentation Skill
     - PPT Master: 生成大纲 → 用户确认 → 生成正文
     - 在生成过程中可以动态调整分析深度（下钻/上卷）
   - 输出：cash_flow_202608.pptx + analysis_metadata.json
3. 交付给用户
```

**关键点**：
- 单一Agent完成整个任务，保持上下文连贯
- PPT生成过程中可以引用前面的分析结果
- 大纲阶段Agent已经理解了数据特征，不需要重新分析

### 4.2 典型场景2：看板刷新

**用户意图**："刷新语培看板"

**流程**：
```
1. 宿主识别意图：固定报表
2. 启动dashboard_publisher Agent
   - 读取配置：saved_queries/dashboard_training.yaml
   - 执行固定SQL（通过data_warehouse CLI）
   - 生成dashboard.html
   - 推送到服务器
3. 返回状态：成功
```

**关键点**：
- 不经过ad_hoc_analysis（不需要LLM）
- SQL已经在设计期确认并保存
- 日常期只是执行器

### 4.3 典型场景3：日常监控 + 深度分析

**意图**：每日异常检测 + 人工介入调查

**流程**：
```
1. 定时任务触发daily_monitor Agent
   - 执行监控规则（saved queries）
   - 发现：校区A现金环比下降30%
   - 输出告警：alerts/20260903_campus_a.json
2. 用户收到告警，询问："为什么校区A下降了？做成分析报告"
3. 宿主启动ad_hoc_analysis Agent
   - 读取告警上下文（campus_a的基础数据）
   - 下钻分析：年级/渠道/顾问维度
   - 发现关键原因
   - 调用presentation Skill生成PPT报告
4. 输出：campus_a_analysis.pptx
```

**关键点**：
- daily_monitor只检测，不分析原因
- ad_hoc_analysis可以利用monitor的上下文
- PPT生成在分析过程中完成（不是分析后再生成）
- 两者职责清晰分离

### 4.4 典型场景4：仅分析不交付

**用户意图**："快速看一下8月现金流情况"

**流程**：
```
1. 宿主识别意图：探索性分析，无交付需求
2. 启动ad_hoc_analysis Agent
   - 生成SQL并执行
   - 输出文本结论
   - 不调用presentation Skill
3. 返回文本结果
```

**关键点**：
- presentation Skill是可选的
- 用户明确要"PPT/图表"时才调用
- 默认只输出文本分析

---

## 五、共享数据层设计

### 5.1 目录结构

```
shared/
├── data_warehouse/
│   ├── cli.py                       # 统一CLI入口
│   ├── ingestion/
│   │   ├── inspect.py
│   │   ├── ingest.py
│   │   └── snapshot.py
│   ├── query/
│   │   ├── service.py               # 受控只读查询
│   │   ├── saved_queries.py
│   │   └── quality.py
│   └── snapshots/
│       └── <snapshot_id>/
│           ├── metadata.json
│           └── data.duckdb
│
├── business_metadata/
│   ├── cli.py
│   ├── packs/
│   │   └── education_training_cn/
│   │       └── pack.json
│   └── bridges/
│       └── <company_id>/
│           └── bridge_v1.json
│
└── casebook/
    ├── cli.py
    ├── cases/
    │   └── <company_id>/
    │       ├── candidate/
    │       └── confirmed/
    └── feedback/
```

### 5.2 CLI接口（保持稳定）

所有Agent通过CLI访问，不直接导入Python模块：

```bash
# Data Warehouse
python3 -m shared.data_warehouse ingest --source cash.xlsx --snapshot-id snap_001
python3 -m shared.data_warehouse query --snapshot-id snap_001 --sql "SELECT ..."
python3 -m shared.data_warehouse run-saved-query --query-id dashboard_training

# Business Metadata
python3 -m shared.business_metadata validate-pack
python3 -m shared.business_metadata align-bridge --workspace customers/acme

# Casebook
python3 -m shared.casebook search --workspace customers/acme --query "现金下降"
python3 -m shared.casebook create-candidate --analysis-id analysis_001
```

### 5.3 为什么共享层重要

1. **版本稳定**：CLI是契约，Agent可以独立演化
2. **权限控制**：只读查询、Snapshot不覆盖等规则在CLI层强制执行
3. **测试隔离**：可以单独测试data_warehouse，不需要启动Agent
4. **宿主无关**：CLI不依赖DeepSeek/Codex SDK

---

## 六、实施路线图

### Phase 1: 重组目录结构（1周）

**目标**：物理隔离，不改功能

**步骤**：
1. 创建`shared/`目录
   - 移动`data_platform/` → `shared/data_warehouse/`
   - 移动`business_pack/` + `company_bridge/` → `shared/business_metadata/`
   - 移动`casebook/` → `shared/casebook/`

2. 创建`agents/`目录
   - 创建`agents/workspace_setup/`
     - 移动`onboarding/` + `bridge_alignment/`
   - 创建`agents/ad_hoc_analysis/`
     - 移动`.agents/skills/business-analysis-routing/`
   - 创建`agents/presentation/`
     - 移动`.agents/skills/ppt-master/`
   - 创建`agents/dashboard_publisher/`
     - 移动`dashboard_product/`

3. 更新导入路径
   - 运行测试确保没有破坏现有功能

4. 更新文档
   - `README.md` - 新的架构图
   - `docs/architecture.md` - 新的模块边界

**验收**：
- 所有现有测试通过
- CLI命令正常工作
- DeepSeek/Codex宿主能正常调用

---

### Phase 2: 重构ad_hoc_analysis（2周）

**目标**：整合分析与交付能力，作为单一Agent

**步骤**：
1. 在`agents/ad_hoc_analysis/`创建独立Agent定义
   - `agent.md` - 职责、输入、输出
   - `tools/` - SQL生成、Casebook检索、数据查询
   - `skills/presentation/` - 交付能力（PPT/图表/表格）
     - `ppt_master/` - PPT Master工作流（保持固定版本）
     - `chart_templates/` - 图表生成模板
     - `table_export/` - 表格导出工具

2. 实现分析主流程
   - Casebook检索
   - SQL生成与执行
   - 结果分析

3. 集成presentation Skill
   - 用户明确需要交付物时调用
   - PPT Master: 大纲生成 → 用户确认 → 正文生成
   - 图表/表格按需生成

4. 定义输出规范
   - 文本分析：`outputs/<analysis_id>/conclusion.md`
   - 交付物：`outputs/<analysis_id>/deliverable.pptx`
   - 元数据：`outputs/<analysis_id>/metadata.json`

5. 测试
   - 仅分析场景（无交付）
   - 分析+PPT场景
   - 分析+图表场景

**验收**：
- 能独立完成"分析+交付"任务
- PPT生成过程保持Agent上下文
- 可选择性调用presentation Skill
- PPT Master完整性测试通过

**关键设计**：
- presentation作为内置Skill，不是独立Agent
- 避免"分析完成→传递JSON→重新理解"的割裂
- PPT大纲生成时Agent已经理解了数据特征

---

### Phase 3: 独立dashboard_publisher（1周）

**目标**：完成看板推送Agent，验证架构

**步骤**：
1. 在`agents/dashboard_publisher/`实现
   - `agent.md`
   - `tools/render.py` - 生成HTML
   - `tools/push.py` - 推送服务器
   - `config/dashboard_training.yaml` - 看板配置

2. 实现固定SQL执行流程
   - 读取saved query ID
   - 调用`shared.data_warehouse run-saved-query`
   - 渲染HTML
   - 推送

3. 实现Web UI
   - 季度筛选
   - 页面刷新
   - 本地预览（127.0.0.1:8787）

4. 集成测试
   - 端到端：刷新看板 → 生成HTML → 推送成功

**验收**：
- 能独立运行（不需要ad_hoc_analysis）
- 不调用LLM（完全确定性）
- 输出可回查到saved query

**已有基础**：
- `docs/handoff.md:52-59` - 看板口径已确认
- 现金明细和工单数据已准备

---

### Phase 4: orchestration层（1周）

**目标**：确定性Agent路由

**步骤**：
1. 在`orchestration/`实现Agent选择器
   ```python
   def select_agent(user_intent: str, workspace_state: dict) -> Agent:
       # 工作区未初始化
       if not workspace_state.get("initialized"):
           return workspace_setup
       
       # 固定报表刷新
       if "刷新看板" in user_intent or "推送数据" in user_intent:
           return dashboard_publisher
       
       # 探索性分析（可选交付）
       if "分析" in user_intent or "为什么" in user_intent or "下钻" in user_intent:
           return ad_hoc_analysis  # 内部决定是否调用presentation Skill
       
       # 日常监控
       if "检查异常" in user_intent or "监控" in user_intent:
           return daily_monitor
       
       # 默认：探索性分析
       return ad_hoc_analysis
   ```

2. 实现宿主适配
   - DeepSeek Harness集成
   - Codex集成
   - 统一调用接口

3. 实现Agent间数据传递
   - 通过文件系统（outputs/目录）
   - metadata.json记录依赖关系

4. 测试
   - 多Agent协作场景
   - 错误恢复

**验收**：
- 宿主能正确选择Agent
- Agent间能正确传递数据
- 失败时能定位到具体Agent

---

### Phase 5: 增加daily_monitor（2周，未来）

**目标**：验证架构可扩展性

**步骤**：
1. 创建`agents/daily_monitor/`
2. 定义监控规则配置
3. 实现告警逻辑
4. 测试与ad_hoc_analysis协作

**验收**：
- 不影响现有Agent
- 可以独立部署/测试
- 与super_agent的Jenny相比，职责更单一

---

## 七、迁移策略

### 7.1 向后兼容

**Phase 1-2期间**：
- 保留旧的CLI路径作为alias
- 例如：`python3 -m interfaces.data_platform` → `python3 -m shared.data_warehouse`
- 在README中标记deprecated

**Phase 3后**：
- 移除旧路径
- 更新所有文档

### 7.2 数据迁移

**客户工作区**：
- `customers/`目录不变
- Snapshot格式不变
- Bridge/Pack不变

**只需要迁移**：
- 代码位置（目录重组）
- 导入路径（Python imports）

### 7.3 测试策略

**每个Phase后**：
1. 运行完整测试套件
2. 手工测试主要流程（DeepSeek + Codex）
3. 检查CLI命令
4. 更新相关文档

**Phase 5后**：
- 端到端回归测试
- 性能测试（S4 Quick PPT）

---

## 八、风险控制

### 8.1 已知风险

**风险1**：重构期间可能破坏现有功能
- **缓解**：Phase 1只移动文件，不改逻辑；每个Phase独立测试

**风险2**：PPT Master固定版本可能与新结构冲突
- **缓解**：Phase 4专门处理PPT，保持attribution guard

**风险3**：宿主适配可能需要额外工作
- **缓解**：Phase 5专门处理orchestration，提前验证宿主接口

### 8.2 回滚计划

**每个Phase有独立Git分支**：
- `refactor/phase1-restructure`
- `refactor/phase2-ad-hoc-analysis`
- ...

**如果Phase N失败**：
- 回退到Phase N-1的分支
- 重新评估Phase N的方案
- 不影响已完成的Phase

### 8.3 验收标准

**每个Phase的验收**：
- [ ] 所有现有测试通过
- [ ] 新增测试覆盖新逻辑
- [ ] CLI命令正常工作
- [ ] DeepSeek/Codex双宿主验证
- [ ] 文档更新完成

**整体验收**（Phase 5后）：
- [ ] 架构图清晰反映实际结构
- [ ] 每个Agent可以独立测试
- [ ] 增加新Agent不需要修改现有Agent
- [ ] 开发日志中"跨模块协调"< 20%

---

## 九、成功指标

### 9.1 短期（Phase 1-4完成后）

**代码结构**：
- 4个独立Agent目录
- 共享层与Agent层清晰分离
- ad_hoc_analysis包含presentation Skill
- 每个Agent < 500行核心代码（不含PPT Master）

**测试隔离**：
- 每个Agent有独立测试套件
- 共享层有独立测试套件
- presentation Skill可以单独测试
- 总测试覆盖率 > 80%

**文档清晰**：
- 每个Agent有明确的职责描述（< 30字）
- 输入/输出格式文档化
- Skill与Agent的关系清晰
- 架构图反映实际结构

### 9.2 中期（增加daily_monitor后）

**可扩展性验证**：
- 增加新Agent不需要修改现有Agent
- 增加新Agent < 3天开发时间
- 新Agent能立即与现有Agent协作

**调试效率**：
- 问题能精准定位到具体Agent
- 单Agent测试覆盖80%场景
- 减少"不知道哪里出问题"的情况

### 9.3 长期（持续运行6个月后）

**维护成本**：
- 开发日志中"跨模块协调"< 20%
- Bad cases能清晰归因到具体Agent
- 无需"大重构"（小的优化是正常的）

**对比super_agent**：
- ✅ 无单体路由
- ✅ 无上下文污染
- ✅ 可以独立部署/测试每个Agent
- ✅ 增加功能不影响现有Agent

---

## 十、总结

### 10.1 核心改变

| 维度 | 当前 | 重构后 |
|------|------|--------|
| **结构** | 单一智能体 + 模块 | 4个独立Agent + 共享层 |
| **职责** | 1个Agent理解所有场景 | 每个Agent理解1个场景 |
| **PPT定位** | 嵌入在分析流程中 | 作为ad_hoc_analysis的Skill |
| **扩展** | 增加功能 → 修改主Agent | 增加功能 → 增加新Agent |
| **调试** | 问题难以定位 | 精准定位到Agent |
| **测试** | 整体测试 | 独立测试每个Agent |

### 10.2 关键原则（再次强调）

1. **按业务场景拆分Agent，不按技术层**
2. **共享数据层，独立业务逻辑**
3. **确定性编排，Agent做分析**
4. **PPT等交付能力作为分析Agent的Skill，不是独立Agent**
5. **每个Agent职责< 30字描述**

### 10.3 4个独立Agent

1. **workspace_setup**: 工作区初始化、Bridge对齐
2. **ad_hoc_analysis**: 探索性分析 + 交付生成（通过内置presentation Skill）
3. **dashboard_publisher**: 固定SQL执行 + 看板推送
4. **daily_monitor**: 异常检测 + 告警（未来）

### 10.4 下一步行动

**立即开始**：
- [ ] Review这份方案，确认方向
- [ ] 创建`refactor/phase1-restructure`分支
- [ ] 开始Phase 1：重组目录结构

**里程碑**：
- Week 1: Phase 1完成（目录重组）
- Week 2-3: Phase 2完成（ad_hoc_analysis + presentation Skill）
- Week 4: Phase 3完成（dashboard_publisher实现）
- Week 5: Phase 4完成（orchestration层）
- Week 6+: Phase 5（daily_monitor，未来）

---

**方案制定日期**: 2026-09-03  
**预计完成时间**: 5周（Phase 1-4）  
**核心修正**: PPT作为ad_hoc_analysis的内置Skill，保持分析上下文连贯  
**参考文档**: `/Users/akechi/Desktop/super_agent/架构审计报告_20260903.md`
