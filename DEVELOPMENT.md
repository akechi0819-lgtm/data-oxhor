# Data OXHor 开发文档

本文档是当前主模块开发的工作记录和维护入口。它记录已经落地的结构、正在施工的能力和需要遵守的长期边界；客户操作步骤见 `docs/user-guide.md`，CLI 合同见 `docs/integration-guide.md`。

## 当前定位

项目正在从“单一数据分析产品”演进为模块化运营数据中台。数据接入、数据平台、工作区建模、自由分析、固定看板和日常监控各自拥有清晰的代码边界，可以由不同 Agent 独立启动。根目录提供按需读取的轻量板块导航；项目不实现总控 Agent、跨模块调度、Session 管理或模型适配层。

## 模块状态

| 模块 | 目录 | 状态 | 说明 |
|---|---|---|---|
| 数据接入 | `data_acquisition/` | 已落地 | 来源 manifest、BI 下载和仓库重建任务 |
| 数据平台 | `data_platform/` | 已落地 | landing、不可变 Snapshot、schema、quality、受控只读 SQL |
| 工作区建模 | `workspace_modeling/` | 已落地 | Pack、Bridge、对齐向导、首次部署、Casebook、内测反馈 |
| 自由分析交付 | 宿主 Agent + `workspace_modeling.delivery` | 已落地 | 分析编排与文件生成由宿主完成，确定性组包由 `workspace_modeling.delivery` 完成；PPT 调用宿主全局 `ppt-master` |
| 固定看板 | `dashboard_product/` | 已落地/持续增强 | 四分册静态发布、basic auth；人员监控已拆出 |
| 日常监控 | `monitoring_product/` | 已落地 | 人员进度、落后判断、明细证据与钉钉日报；定时由宿主触发 |

## 当前主线

当前架构演进阶段经用户确认在第 2 轮后结束，没有本阶段待完成施工，已完成查询、自由分析交付与 Casebook 证据链。用户确认现有静态看板和简单对账够用，常见差异多在人工录入或口径，因此取消看板、监控最终产物统一改造；当时案例提醒与指标执行关联均待真实需求验证，不再按固定轮次自动施工。此次用户接受新核查后的有限修复：修正来源提取、补分析结束提醒与纯文字保存说明、统一扩展边界；不恢复原六轮计划，指标执行关联继续不排期。最新安排见 [施工计划](./docs/Agent_架构演进施工计划.md)。看板继续按已确认指标和 SQL 生成静态图表，不在刷新时临时改变业务口径。

自由分析主线继续使用 `data_platform` 的显式 `run_id`、`snapshot_id` 和受控查询；表格/图表使用宿主原生能力，PPT 由宿主全局 `ppt-master` 按需选择 Quick 或 Default。项目内置 Quick 编排和固定 PPT Master 副本已拆除。

## 开发原则

- 先让单个模块端到端可运行，再增加跨模块能力。
- 新增需求依次评估：复用已有模块 → 扩展已有接口 → 新增模块 → 新增 Agent。只有前三种方式无法满足，并且职责、权限边界或运行周期确有独立需求时，才新增 Agent 运行说明。
- 本次只补齐已有能力连接，不新增总 Agent、Capability Registry 系统、独立 Metric Layer 或 Artifact 平台。
- 模块之间通过 CLI、JSON、文件和版本化 manifest 交互，不共享宿主内部对象。
- 数据平台不携带企业业务语义；企业字段和口径只进入 Company Bridge。
- 运行状态使用显式身份，不用 `latest`、修改时间或模糊文件名猜测。
- 原始客户数据和运行产物留在客户工作区，不进入 Git。
- 发现旧入口或旧字段时直接删除并同步调用方，不新增兼容层。

## 验证命令

```bash
python3 -m interfaces.workspace_modeling --help
python3 -m interfaces.data_platform --help
python3 -m interfaces.business_pack validate
python3 -m interfaces.company_bridge validate --help
python3 -m interfaces.casebook --help
python3 -m dashboard_product.refresh --help
python3 -m monitoring_product.notify --help
python3 -m unittest discover -s dashboard_product/tests -v
sh tools/run_tests.sh -v
git diff --check
```

## 决策记录

### 2026-09-18：核查后的最小连接修复

- 决定：删除查询来源识别中的手写正则，复用 DuckDB 原生 SQL AST 与 `get_table_names`，再由现有 `ingest.sheets` 映射来源。实际执行的 SQL、参数和证据协议不变。
- 原因：字符串中的 `--` 被误当注释，使有效查询的来源回执为空；大写、带引号表名也应与登记身份一致。来源提取独立于优化后执行计划，空结果仍保留来源。
- 实现边界：DuckDB 的依赖发现不支持参数绑定及 JOIN USING/NATURAL 列解析，只在来源解析副本中将普通表达式参数置 NULL、将这两种连接规整为保留左右依赖的交叉连接；原 SQL 仍先过只读门禁并原样执行。表函数内部出现参数时，在替换前统一拒绝，包含 CASE 等嵌套表达式，避免参数选择的实际表与回执来源不一致。普通显式来源视图可展开；无法解析的视图依赖、未限定来源关系、缺来源登记均明确报 `QUERY_PROVENANCE_INVALID`，不猜来源、不返回伪空来源。本批不建设完整视图血缘或动态表定位能力。
- 流程：结论与必要交付结束后，宿主最多给一次中性 Casebook 保存提醒；不评分业务价值、不自动创建案例、不改状态机。用户明确验收并同意保存纯文字分析后，原样保存 `answer.md`，复用既有组包与 capture。
- 范围：属于已结束阶段之后的新核查修复，不恢复六轮施工，不改看板、监控、指标层或查询回执字段。新增需求按复用模块、扩展接口、新增模块、新增 Agent 的顺序评估。
- 验收：查询服务 11 项通过；新增回归覆盖注释样式字符串、参数、空结果、CTE、JOIN、大小写、带点及引号表名、简单视图及无法解析时的拒绝。将旧来源函数代入新回归可复现原缺陷。主任务发现并退回修复了 CASE 参数动态选表造成错误来源的反例，补回归后通过。正式 `sh tools/run_tests.sh` 共 180 项全部通过、无跳过（主测试 131、看板 30、监控 19）；独立验证普通查询结果与合成数仓哈希不变，纯文字答复原样保存为候选、删除原输出后仍可验证。文档检查通过，本批未改数据源或执行部署。


### 2026-09-18：公共证据合同与静态能力说明（第 1 轮）

- 决定：区分查询回执、文件身份、业务交付清单，统一引用与校验责任；能力目录扩充现有集成指南，不建注册器。详细设计见 `docs/evidence-contract.md`。
- 原因：查询小结果缺统一留存，现有 Casebook 扁平复制不能保持回执内部引用；需要先固定可验证的最小闭包，再改代码。Pack 已有指标定义，保留其权威，不新建 metrics 库。
- 范围：只更新合同、能力说明及架构边界；第 2 轮实现自由分析链路并同步查询直接读取者，当时计划第 3/4 轮接产品最终产物，后续已取消。不改代码、客户数据、发布、定时或 Project Intelligence 白名单。
- 边界：新路径替代旧路径时同轮更新消费者，不加兼容写入/运行层；已封存案例保留原证据强度、不回写。云端已授权固定任务保留，新增 Agent 需独立职责/权限/运行周期。
- 验收：主任务独立核对代码消费方、文档差异、相对链接与两份 JSON 示例，指定文档 diff 检查通过；87 个相关 Python 文件哈希无变化。收窄了逐次整库重哈希要求，来源绑定只声明受信任不可变 Snapshot 的上下文保证。未运行业务测试，新证据协议尚未实现。


### 2026-09-16：建立市场日常工作入口

- 决定：新增 `market_workspace/` 及 AGENTS、路径授权、接口和清理说明。Programs/Scratch 存放可按任务清理的生成程序，Reports/Evidence/Notes 保留成果与证据；内容目录默认不入 Git。
- 原因：用户需要从一个明确目录做市场自由查询、导表与编辑，避免临时程序混入架构代码；启动目录与已有数仓分离，复用数据而不复制。
- 接口：`./oxhor` 固定绑定 bi_operations，调用原受控 CLI；先 guide、显式 Snapshot/run_id、拒绝路径越界及证据覆盖，结果与手写 SQL 留在本地 Evidence。仅提供读取，不提供初始化/发布/推送。
- 范围：保持现有 operations 数据端口、Pack/Bridge 与初始化命令不变；未新增 OS 权限或云端部署。
- 验证：只读入口边界测试、从市场目录执行 status/describe/最小查询、临时 SQL 清除后证据保留，以及 `git diff --check`。

### 2026-09-16：根入口增加轻量板块导航

- 决定：根 `AGENTS.md` 用职责、目录和入口说明的短表定位工作板块，选定后只读取相关内容；直接指定模块时无需再次分流。
- 原因：整体架构维护需要快速找到代码和工作区，但全量加载各模块与 PPT 规则会增加上下文负担。此前“不做路由”约束细化为不建设总控与调度，允许文档级指路。
- 范围：仅修改导航及直接相关的架构表述；未创建新市场工作区、未改初始化行为、未新增路由代码或自动派工，也未修改云端任务。
- 验证：导航路径存在，文档改动通过 `git diff --check`；纯说明变更不运行业务测试。

### 2026-09-16：监控云端部署与权威任务验收

- 结果：A 层已部署；魏忠贤既有每天 10:30 四通道日推原位改用 monitoring_product。孙悟空、许家印职责与排期不变，无第二启用日推。
- 收口：AST 核对证明云 refresh 体积差异只是共享函数未抽取，最终采用包版并删除兼容路径。任务从实际调度器读回，不能把影子文件或角色回复当成配置已落盘的证据。
- 验证：云监控 19/19、看板 27/27；真实 Snapshot 四通道 PNG 与旧通知一致；包版 refresh 无发布验证通过；权威 ID、prompt 和唯一性已核验。本轮无真实群发。
- 记录：`docs/monitoring-cloud-deployment.md`；云 pyproject 保留既有可选依赖差异，回写仅进 inbox，不覆盖本机其他任务修改。

### 2026-09-16：PPT Master 从项目内置改为宿主全局能力

- 决定：删除项目内 `.agents/skills/ppt-master`、S4 Quick 编排代码、PPT 安装 profile 及对应测试/提示词。自由分析只负责将当前 Snapshot 的受控查询证据和分析上下文交给宿主全局 `ppt-master`，由它按需路由 Quick 或 Default。
- 原因：项目固定 Quick 使 PPT 形式受限，并重复了完整 Skill 已有的路由和质量门禁。
- 影响：项目不再安装或验证 PPT 运行时；宿主必须能发现全局 `ppt-master`。缺失时只阻断 PPT 交付，不影响分析、查询证据和其他文件交付。
- 验证：全局 `ppt-master` v4.7.0 attribution guard；项目全量测试；PPT/S4 残留引用扫描。

### 2026-09-16：人员监控从看板独立

- 决定：通知入口、进度计算、渲染、三份 SQL、通道配置、通知部署脚本与测试归入 `monitoring_product/`。旧路径和 `--artifact` 输入删除；新入口要求 workspace、snapshot-id、run-id、as-of-date、data-through-date，发送显式 env-file。
- 原因：人员进度监控已有独立判断和证据链，不应依赖看板先生成 artifact；原有两条计算链已统一，不再恢复旧正文数据路径。
- 影响：绩效月和人员匹配函数原样抽入 `workspace_modeling/operations/personnel.py`，花名册原样移动到同目录供两模块共用。三份 SQL 与迁移前逐字一致。通道合计改从同一受控明细汇总，查询回执和 SQL 均落地；整体查询失败阻断保留。
- 权限：Agent 合同允许所选工作区的受控只读数仓查询、只读看板核对和本次输出写入；不授予写仓/看板发布权限。系统授权与定时触发仍由宿主配置。
- 验证：监控 19 项、看板 29 项、主测试 107 项；合成仓库经真实 CLI 跑通工单、现金和跨月回查、图片及 Excel，数仓哈希不变。安装包包含新模块、三份 SQL 和共享花名册；未发送钉钉。
- 部署：本机代码完成，云端 A 层和通知任务待按 `monitoring_product/README.md` 切换，C 层未移动。测试总入口同时覆盖主模块、看板和监控，并以显式顶级目录避免 `tests/data_acquisition` 遮蔽业务包。


### 2026-09-16：钉钉进度统一结果与查询失败阻断

- 决定：先为全部选中通道完成花名册更新、同一 Snapshot 明细查询和人员实际计算，再生成文件并发送；正文、图片、Excel 共用最终 digest。查询失败、子进程非零退出或查询结果缺失均阻断，预览模式同样执行，不回退到旧看板数字。
- 原因：原文件生成函数只在局部更新 digest，正式正文仍消费旧值；查询异常被吞掉后，新花名册可能呈现零完成并继续发送。
- 影响：失败时 CLI 非零退出，整批不上传、不发送；保留本地查询证据。本次未迁移模块或修改业务口径，云端需同步 `monitoring_product/notify.py` 后生效。
- 验证：修复前新增回归测试复现问题；修复后 `.venv/bin/python -m unittest discover -s dashboard_product/tests -v` 共 50 项通过，上传与钉钉发送均使用 mock，无实际群发。

### 2026-09-07：采用模块 Agent 目录，不建设总路由 Agent

- 决定：在 `agents/` 下按工作区初始化、自由分析、看板发布和日常监控提供独立 Agent 文件；项目不提供一个负责跨模块分派的主 Agent。
- 原因：未来运营中台由多个智能体协作或分别运行，模块边界应由调用者选择，而不是再次形成单体路由上下文。
- 影响：新需求依次评估复用已有模块、扩展已有接口、新增模块、新增 Agent；只有前三者不能满足且职责、权限边界或运行周期确有独立需求时，才评估新增 Agent 说明，不按每个业务需求自动增加 Agent，也不把运行逻辑塞入根目录。
- 验证：目录结构与 `data_acquisition`、`data_platform`、`workspace_modeling`、`analysis_product`、`dashboard_product` 现有代码边界一致。

### 2026-09-07：根目录文档分层

- 决定：根 `README.md` 只介绍产品定位、模块结构和入口；`DEVELOPMENT.md` 记录开发状态与决策；详细合同继续放在 `docs/`。
- 原因：产品说明、开发记录和客户操作属于不同受众，不能继续混在旧版数据分析 README 中。
- 影响：维护状态先更新 `DEVELOPMENT.md`，对外行为变化再同步相应合同和测试。

### 2026-09-09：看板四分册、钉钉人员进度、Saved Query 不再绑历史 Snapshot

- 决定：公网发布按团队板块四分册 + htpasswd；钉钉人员进度作为独立命令，不并入日更脚本。Saved Query 运行时只校验 SQL hash，由 Data Platform 校验当前仓库 Snapshot 身份，不再把确认时的 `source_snapshot_id` 当作运行绑定。
- 原因：日更宿主已从本机 Codex 改为许家印云电脑；匿名全量 `current.html` 不再符合内部分册权限。钉钉 webhook 是 C 层密钥，不能和 HTML 发布混进同一公开合同。
- 影响：云电脑独立运行必须单独同步 `.env.server`。缺 webhook 的通道跳过。不建设本机↔Grok 双向 MCP。
- 验证：`python3 -m unittest discover -s dashboard_product/tests -v`；`tests/platform/test_query_service.py` 覆盖 Saved Query 可在另一合法 Snapshot 上运行。

### 2026-09-09：同比四组与现金跨月个人归属

- 决定：刷新改消费 `dashboard_actuals/v7`。目标区仍按留学预备/高中/大学；渠道同比和年级同比拆成青少、初中、高中、大学。现金业务组只看现金表团队。钉钉现金归属按工单 ID 回查全量工单，不限本绩效月。
- 原因：签约月和开单月经常错开；留学预备目标不能再混进同比年段。
- 影响：云端 overlay 必须带 v7 SQL 和 `notify_work_orders_by_ids.sql`。刷新产物必须带 `yoy_groups`，渲染器不再给旧 artifact 补空年段，也不能把留学预备当同比行。
- 验证：`python3 -m unittest discover -s dashboard_product/tests -v`。

### 2026-09-10：大学钉钉人头与线上私域花名册

- 决定：钉钉 `offline_university` 第二列改为人头完成，落后仍按工单。人头按已归属被动新生正向现金的非空 `学员编号` 去重，不含 1500 门槛；同一条现金归属 N 人时每人计 `1/N`。钉钉花名册以 `workspace_modeling/operations/people.json` 覆盖 artifact。线上私域小初提能组由杨玉林替换为潘体学（工单 25、现金 50,000）。线上私域 webhook 已填，仍不进 Git。
- 原因：大学下的是人头目标；1500 是留学预备校区分析门槛，不进 Bridge，也不能套到大学推送。杨玉林离岗，潘体学按新人入册。
- 影响：云端 A 层 overlay 必须含 `digest.py`、`notify_render.py`、`people.json`。C 层 `.env.server` 必须重新 CopyToBox，否则云电脑发不出虚拟人/大学群。看板 HTML 要等下一次 refresh 才会换名。
- 验证：`python3 -m unittest discover -s dashboard_product/tests -v`。

### 2026-09-09：删除废弃看板版本与兼容层

- 决定：运行时只保留 `dashboard_actuals/v7`。删除空的 v1–v5 Saved Query 目录、旧业务组分册过滤器和前端空 `yoy_groups` 补丁。`attributed_passive_reported_cash/v1` 仍是现行逐笔底稿。
- 原因：项目不保留向后兼容；旧目录和兼容层会让下一轮误把 v6 或空年段当成现行合同。
- 影响：`liuxue` / `gaozhong` / `daxue` 不再有过滤入口。刷新产物缺少 `yoy_groups` 时同比表为空，不会补四个空年段。
- 验证：`python3 -m unittest discover -s dashboard_product/tests -v`；`python3 -m unittest tests.bridge.test_reviewed_artifact -v`。


### 2026-09-14：TMK 激活的校代资源临时打回线下市场

- 决定：临时补丁。一级渠道为 `TMK激活-平台`、活动名含 `校代系统资源`、资源描述 `市场人员：` 能命中线下市场花名册的工单，从线上平台改回线下市场后再做个人归属。原生「平台」投放不改。
- 原因：TMK 激活石仁达小表单校代资源时，`线上线下=线上` 把单划进线上平台；石仁达只在线下大学花名册，个人完成和线下大学合计少算。
- 影响：刷新在 `refresh.py` 聚合层改 `team_id`；钉钉明细在 `notify_work_orders.sql` / `notify_cash.sql` 同步同一规则。该次 Saved Query 未改（历史记录；当前入口为 `dashboard_actuals/v10`）。云端 A 层 overlay 必须带这三处。SQL 的花名册 `IN` 名单与 `workspace_modeling/operations/people.json` 线下成员耦合，加人时要一起改。
- 验证：`python3 -m unittest discover -s dashboard_product/tests -v`；`run_dashboard_20260914_172915` 石仁达 9 月工单 42→48，全年 156→163。

### 2026-09-11：产能页、渠道合计与张艺彤回落（历史记录）

- 决定：当时升级看板查询，增加第 12 列现金 `student_id` 并删除前代运行入口。当前运行版本已统一为 `dashboard_actuals/v10`。全量页并列第五页签「市场人员产能」：全年现金对照统一 80 万标准产能，六维雷达为工单数、签约量、转化率、渠道&校代/TMK/活动贡献，均值按团队算。渠道同期对比增加合计列与总计行。无法判断/空团队且跟进顾问为张艺彤时按留学预备回落。大学钉钉明细表人员进度额外输出现金目标/完成。
- 原因：产能页需要去重人头；张艺彤名下无法判断工单此前被整段丢掉；大学群既看人头也要在明细里对现金。
- 影响：该次历史部署 overlay 包含当时的 SQL、`capacity.py`、`config/capacity_targets.json`。产能页不进钉钉。平台现金不计入三类贡献轴。
- 验证：`python3 -m unittest discover -s dashboard_product/tests -v`。

### 2026-09-17：Project Intelligence 第一阶段本地只读上下文

- 背景：用户确认建设用于架构讨论和项目评审的只读 MCP，先实现本地上下文服务，不接入 ChatGPT。
- 实现：独立 `project_intelligence/` Python 服务及 CLI，显式文件允许清单、搜索/分段读取、Git 工作树状态、Agent/模块与连接说明、当前工作区结构元数据、看板查询版本差异证据。无网络监听、MCP 协议依赖或模型调用。
- 边界：业务模块不依赖该服务；客户内容仅投影身份和 schema，不执行业务 SQL。复用 describe，不调用 casebook guide，因为后者内部 profile 会取样本。Bridge 合同校验通过不等同于 Snapshot 业务可用，响应明确未评估完整兼容性。
- 安全：拒绝任意文件路径和越界软链，过滤敏感文本，元数据指针固定约束，JSON 证据变化时失败，原始 SQL/进程异常不出边界。仍需可信 checkout；不声称 OS 沙箱或任意编码秘密检测能力。
- 验收：见 `docs/project-intelligence-acceptance.md`；接口合同见 `docs/project-intelligence.md`。

### 2026-09-17：Project Intelligence stdio MCP 适配

- 用户授权：先完成本机 MCP 握手、工具发现与调用，不配置 Secure MCP Tunnel，不改现有服务或业务代码。
- 实现：独立 `project_intelligence/mcp_server.py`，官方可选 SDK `mcp==2.2.0`；从原五个方法签名生成严格输入 Schema，原响应作为结构化结果与文本内容返回，稳定错误码与 partial 语义保留。
- 决策：使用 SDK low-level Server 回调控制安全错误输出，协议与传输仍全部由 SDK 实现；没有自建 JSON-RPC、兼容层或 HTTP 服务。独立进程不记录原始参数/异常。
- 验证：原服务 18 项 + 新协议 9 项全部通过；真进程 initialize、tools/list、tools/call、非法请求及 EOF 验证通过；实盘五工具成功、130 个既有受保护文件哈希不变。没有 ChatGPT 接入或隧道配置。
- 说明：`docs/project-intelligence-mcp.md` 提供准确启动命令、本轮验收及后续账号/隧道配置要求。

### 2026-09-17：ChatGPT Developer Mode 通过 Secure MCP Tunnel 接入验收

- 范围：只配置连接与运行文档，原五个工具、MCP 服务、只读允许清单和业务代码均未修改。
- 配置：官方 tunnel-client v0.0.14 ARM64，release SHA-256 校验通过；安装到项目外专用目录。专用 Tunnel 关联 Personal 组织与个人 ChatGPT 工作区，运行凭据 Restricted，仅 Tunnels Read/Use，有效期 30 天；以私有文件引用使用，不交给 MCP 子进程。
- 运行：官方 runtimes connect 托管进程保持运行，status 实读 process_running/healthy/ready 均为 true；回环管理端口动态分配，无公网 MCP 监听，无开机启动配置。
- 验收：ChatGPT 6-Pro 实际调用 overview、search、read、workspace、integrations，逐项工具面板回执均为 ok，当前 Snapshot 为 snapshot_bi_operations_20260916_fy25；本机 dispatcher 有对应五次转发。原 5 个 MCP 源文件及 130 个受保护业务/数据文件哈希不变。
- 说明：完整身份、命令、私有测试对话与回执时间见 `docs/project-intelligence-tunnel.md`。运行密钥内容未进入项目或聊天。


### 2026-09-18：第 2 轮自由分析证据闭环

- 查询升级 `controlled_query_result.v2`：小、大、空结果均保存实际 SQL、参数、完整结果和独立 `query_receipt.v1`。Snapshot 绑定 manifest 字节摘要与登记仓库摘要，检查路径、大小和库内身份；不逐次全库重哈希。
- 增加 `data_platform.query.evidence` 验证函数和 `workspace_modeling.delivery` 确定性组包 API；交付文件与回执闭包共同验证，拒绝篡改、越界和错 Snapshot。看板、监控、市场查询读取同步改用验证函数；最终产品清单保持本轮范围外。
- Casebook 新写入使用 delivery 包和 capture.v2，先临时复制闭包再发布 candidate。封存验证不依赖原输出或数仓；四态保持，旧封存不升级重写。Bridge 只读画像独立为 snapshot_quality_profile.v1，CLI quality 输入读取真实查询回执。
- 新合成端到端回归以正式 Snapshot 和 Bridge 跑实际 CLI 查询→自包含 HTML→组包→capture→verify→删除原输出/数仓→verify；不访问客户数仓、不发布发送。主任务独立验收：`sh tools/run_tests.sh` 176 项全部通过且无跳过（主测试 127、看板 30、监控 19），另有独立查询 5 项、真实 CLI 归档验证和 6 项入口冒烟通过。

- 旧入口清理：运行与操作说明统一 `dashboard_actuals/v10`；旧版本测试改按配置声明核对，保留 SQL 与 manifest 哈希断言，删除无用旧 Casebook fixture。历史记录不再充当旧运行说明。
- 范围核对：看板核心聚合和监控发送/明细计算函数 AST 未变；本轮只接入查询证据读取，当时后置的最终产品改造已在后续需求复核中取消。


### 2026-09-18：按真实需求收口后续施工

- 依据：用户明确看板是静态图表，现有简单对账足够；实际差异常见于人工录入和口径，尚无复杂对账能力缺口。技术格式统一不能作为独立施工收益。
- 决定：保留第 1、2 轮成果，取消原第 3、4 轮；原第 5 轮案例提醒和第 6 轮指标贯通改为待需求验证、无排期。Business MCP 同样不预排轮次，不用新的对账工具替代被取消任务。
- 方法：差异先用现有明细定位，区分录入、口径和实现问题；只有证据指向代码问题或反复显现的工具缺口，才提出最小改动与验收目标。代码实施仍交子智能体，当前任务独立验收。
- 范围：本次仅同步施工计划、架构、公共证据合同和集成指南；不修改运行代码、客户数据或已完成的证据链。文档检查不替代或重报历史业务测试。

- 阶段结论：用户已确认本阶段结束。未实施的案例提醒、指标关联与 Business MCP 是未来需求方向，不属于本阶段未完成工程；后续新需求另行立项。


### 2026-09-18：阶段结束与本地提交验收

- 统一 README、交接状态和施工计划：本阶段已结束，没有待施工欠账；未实施设想不计为未完成工程。
- 提交包含证据链和阶段文档，以及当前运行所依赖的监控拆分、共享人员规则、市场入口与只读项目上下文模块；独立 BI 下载/窗口合并改动及其测试、两份人员目标工作记录保留未提交。
- 工作区完整回归 176 项通过；从暂存区构造独立副本后，实际提交范围的 172 项全部通过（主测试 123、看板 30、监控 19），无跳过。差额 4 项属于未纳入本次提交的 BI 窗口合并测试。
- 客户数据与生成报告不入库，outputs 已加入忽略规则。本次仅创建本地 Git 提交，不推送或部署。


### 2026-09-18：查询证据与最小来源修复同步云端

- 已提交代码 `d09a228`，通过现有 Grok Bot 通道将本次修复及前置证据链成套同步；不包含本机未提交的独立 BI 下载/窗口合并改动。
- 云端最终 39/39 文件哈希与已提交包一致；7 份旧文档在本机审查后按精确处理清单替换，无剩余跳过。分析角色已获知共享合同路径。
- 云端验收 105 项通过（warehouse 56、监控 19、看板 30），CLI 与导入路径通过；未修改业务 SQL/花名册/例行或 B/C，未进行生产刷新发布发送。
- 完整证据及限制见 [云端同步验收](docs/evidence-cloud-deployment.md)。本条是同步记录，不恢复先前取消的架构施工。
