# 核心 CLI 接入指南

> 正式 BI 为 Superset 原生界面。服务器 raw receiver、root 只读历史基线、受限双 Snapshot / quality / 共享计算 worker 和固定 publisher 已部署；10月26日真实批次实际运行到39张表，最终因业务截止不匹配以 `failed/published=false` 结束，没有发布新 raw release。Mac `p5.daily` 仍存在并有10月26日手动更新记录，不因此列作长期默认路径。有效新包正式发布、持续日更和唯一生产者收口分别待验收。详见[部署说明](../dashboard_product/DEPLOYMENT.md)。

## 1. 当前公开入口

### 1.1 安装

发布包按能力提供依赖集合：

```bash
python3 -m pip install "data-oxhor[full]"
```

`core` 只安装DuckDB数据运行时；`test`增加工作簿、图片和日期库，支持主测试、看板及监控测试；`full`再加入BI浏览器下载、图片渲染和传输所需的Playwright、pexpect与certifi。源码用户可执行 `sh tools/install_runtime.sh test` 或 `sh tools/install_runtime.sh full`。已删除项目内PPT profile及无调用的文档、音视频、抓取和模型依赖；PPT Master、DeepSeek Harness、Office/字体和模型凭据由宿主管理。

首次部署引导层使用同一 Python 环境：

```bash
python3 -m interfaces.workspace_modeling doctor --profile full
python3 -m interfaces.workspace_modeling init --workspace customers/company_customer --business-port operations
python3 -m interfaces.workspace_modeling import-data --workspace customers/company_customer --source-id cash --file /path/to/cash.xlsx
python3 -m interfaces.workspace_modeling sync --workspace customers/company_customer --snapshot-id snapshot_company_2026_08
python3 -m interfaces.workspace_modeling handoff --workspace customers/company_customer --session-id session_onboarding
```

引导层只编排确定性状态：运行时/Pack 检查、`Input/Work/Output` 初始化、工作簿复制、Snapshot 发布和 Bridge 会话交接。`import-data` 默认拒绝覆盖已有来源槽位，月度更新需显式 `--replace`；`sync` 使用新的显式 `snapshot_id`。引导层不会代替宿主 Agent 生成候选、理解自由回答、确认问题或发布正式 Bridge。所有命令 stdout 均为 `onboarding_result.v1` JSON；`doctor`、初始化、导入、同步和交接完成返回 0，仍需用户/宿主动作返回 2，合同或文件错误返回 1。

完整输入、输出、错误和边界见 [首次部署引导层合同](./onboarding-contract.md)。

Data Platform 的公开入口是 Python CLI：

```bash
python3 -m interfaces.data_platform --help
```

已实现子命令：

| 命令 | 所属模块 / 输入与依赖 | 输出 | 写入范围与外部副作用 |
|---|---|---|---|
| `inspect` | Data Platform；来源 manifest、工作簿、run_id | 结构/源哈希报告，不含明细行 | 显式本地输出；原始来源只读，无网络发送 |
| `ingest` | Data Platform；来源 manifest、新 snapshot_id、run_id | DuckDB/Parquet、Snapshot manifest | 发布新 Snapshot 与本地清单；不覆盖已有 Snapshot |
| `describe` | Data Platform；仓库路径、snapshot_id | schema/字段 JSON | 仓库只读，无外部副作用 |
| `quality` | Data Platform；仓库、snapshot_id、run_id、输出根 | 已登记质量问题的查询结果 | 仓库只读；所有成功结果写本地查询证据包 |
| `query` | Data Platform；仓库、snapshot_id、run_id、SQL/参数、输出根与限制 | 受控查询结果及来源 | 仓库只读；始终写 SQL/参数/完整结果/回执，无网络发送 |
| `promote-query` | Data Platform；仓库、snapshot_id、SQL、查询 ID/版本、确认人、registry_root | 保存查询登记 | 写仓库外新版本目录；不可覆盖版本，无业务确认推理 |
| `run-saved-query` | Data Platform；登记 ID/版本、参数、仓库、snapshot_id、run_id、输出根 | 同 query | 校验登记 SQL 哈希；只读仓库、本地结果写入 |

其他模块仍使用各自入口，不注册为 Data Platform 子命令：

| 入口 | 所属模块 / 主要输入与依赖 | 输出与读写范围 | 外部副作用 |
|---|---|---|---|
| `interfaces.workspace_modeling`、`interfaces.bridge_alignment` | Workspace Modeling；显式工作区、来源/Pack、确认决定 | Input/Work/Output、Snapshot 切换、对齐会话、正式 Bridge；详见各合同 | 本地复制与状态写入；不得替用户确认；sync 切换后可能清理旧 Snapshot |
| `interfaces.business_pack` | Workspace Modeling；Pack 文件 | validate/describe JSON，只读 | 无 |
| `interfaces.company_bridge` | Workspace Modeling；Pack、候选/Bridge、可选 Snapshot 画像 | 校验/扫描结果或 build 正式 Bridge；按子命令写显式输出 | 无自动业务确认或发送 |
| `interfaces.casebook` | Workspace Modeling；工作区、角色、用户选择的证据/评价 | guide/search/verify 只读；create/capture/confirm 等写本工作区 Casebook；反馈导出写本地 ZIP | 不自动上传，不自动确认案例 |
| `data_acquisition.jobs.build_study_abroad_warehouse` | Data Acquisition；现有客户工作区、明确的完整资源与签约工作簿、run_id、snapshot_id、截止日 | 整理三张业务表，复用 Data Platform 创建 `Work/StudyAbroad/` 内独立 Snapshot 和指针 | 原文件只读；不修改 BI 工作区指针、工单或现金来源；无网络获取或发布 |
| `dashboard_product.management.study_abroad_query` | Dashboard；显式留学 Snapshot、run_id、日期范围和命名 SQL | 经 Data Platform 受控查询写 `Output/StudyAbroad/` 的 SQL、参数、结果及回执 | 只读独立留学仓；不访问 BI 仓、不刷新页面或发送通知 |
| `dashboard_product.management.study_abroad_channels` | Dashboard；显式留学 Snapshot、日期、当前同公司 Bridge 和渠道参考表 | 受控渠道映射预览、未命中清单、Bridge 候选及已明确确认的独立渠道 Bridge | 只读原 BI Bridge/参考；不切换正式 Bridge 或生产看板 |
| `dashboard_product.management.calculation` | Dashboard；共享业务计算函数，由 `shadow_bi.library` 等调用 | 计算管理事实、汇总和查询所需数据；不是命令行入口 | 写入范围由调用方负责 |
| `dashboard_product.shadow_bi.p5.raw_inputs` | 固定BI工单、BI现金和腾讯三 Excel；显式公司、日期、批次与输出路径 | 生成固定格式输入 TAR，或在服务器接收前验证结构 | 本地封装输入；不运行业务计算或发布 |
| `dashboard_product.shadow_bi.p5.raw_compute` | 服务器固定三Excel队列、root只读历史基线、公司和日期策略 | 新副本内更新双Snapshot、quality、共享计算及39表；状态按回执为 `prepared`、`failed` 等 | 已部署worker；不直接写 current、发布或发送通知 |
| 固定 raw HTTPS API | `POST /shadow-bi/v1/raw-batches`、GET同批状态、prepared后空对象发布请求 | 接收固定输入、返回批次状态；root publisher按P4合同验收并切换 release | 有正式发布副作用；需同批prepared、完整验收与明确授权 |
| `dashboard_product.shadow_bi.p5.daily` | 本机现存手动入口；10月26日日期回执记录其更新的 release | 采集、双Snapshot、共同计算和发布 | 写入并发布；非推荐长期默认路径，使用前核对当前生产状态与授权 |
| `monitoring_product.shared_delivery` | Monitoring；同批 `shared_result.json`、as-of-date、state-dir；正式投递另需 C 层 env-file | dry-run 生成本地预览；正式投递使用共同结果的八条消息与同批附件 | 正式模式上传附件并发送已授权的钉钉通道；逐消息去重 |
| `market_workspace/oxhor` | 市场工作面；固定数据工作区、显式 Snapshot/run | 只读 CLI 调用，写市场 Evidence；不提供导入/发布 | 无 |
| `project_intelligence` CLI / stdio MCP | Project Intelligence；批准代码/文档、工作区结构元数据 | 只读上下文，不返回业务明细、不执行业务 SQL | 服务内无业务写入；远程接入边界见专门文档 |

这是一份静态能力说明，精确参数与写入目录仍以各命令 `--help` 和模块合同为准。自由分析交付由宿主组织，不增加 `analyze` 核心服务或运行时 Capability Registry。

`interfaces.data_platform` 仍是项目受控 SQL 查询的公开 CLI。`dashboard_product/management/calculation.py` 和 `dashboard_product/online_team/build.py` 保留共同计算、查询 helpers；`dashboard_product/refresh.py` 保留来源归属及历史对账 helpers。这些是共享实现，不是独立 CLI。服务器 raw worker 复用共享计算链路；Mac `shadow_bi.p5.daily` 仅说明仍存在的手动入口和10月26日运行记录。有效 raw 发布、持续日更和唯一生产者切换的当前状态见[部署说明](../dashboard_product/DEPLOYMENT.md)。

每个子命令的精确参数以 `--help` 为准，例如：

```bash
python3 -m interfaces.data_platform inspect --help
python3 -m interfaces.data_platform ingest --help
python3 -m interfaces.data_platform query --help
```

输入源由 manifest 绑定；不要把真实客户工作簿复制进仓库。运行产物应写入项目代码目录之外的显式工作区。

## 2. 已实现合同

- `inspect` 输出 schema `data_foundation_inspection.v2`；
- `ingest` 输出 schema `data_foundation_ingest.v2`，Snapshot manifest 为 `warehouse_snapshot.v2`；
- `inspect`、`ingest`、`quality`、`query` 和 `run-saved-query` 要求显式 `run_id`；`describe` 与 `promote-query` 按当前 CLI 参数不要求 `run_id`；
- Snapshot 发布后不可原地覆盖；
- 查询拒绝写操作、外部 reader、系统目录和绕过形式；
- 查询限制最大返回行数和结果字节数；
- Snapshot 登记到最小 `artifact_manifest.jsonl`；查询使用各自独立的回执目录，不再追加该账本；
- 保存查询写在 Snapshot 外部，不修改 DuckDB 文件。

源 SHA-256 用于 inspect/ingest 的 manifest 绑定和 Snapshot/Artifact manifest。它不需要成为每次查询、Session 或交付物都传播的公共身份字段。

这组能力不是完整 Run/Artifact 平台。所有 Sheet 按实际表头名进入 landing，`ingest.sheets.target_table` 给出实际关系名。业务表头、字段含义和清洗口径必须从 Company Bridge 获取，不能在 Data Platform 中硬编码。

### 2.1 公共证据合同（查询与自由分析已实现）

合同区分查询回执、文件身份、业务交付清单，完整字段责任与样例见 [公共证据合同](./evidence-contract.md)。该文档本轮未加入 Project Intelligence 读取白名单；通过本节仍可获取关键边界，未扩大只读服务权限。

- 当前 `controlled_query_result.v2`：成功查询始终保存 SQL、参数、完整结果和 `query_receipt.v1`；stdout 提供回执文件身份，小结果另有内联副本。读取使用 `read_query_result` 验证证据；看板与监控仍保留各自最终业务 artifact。
- 每次成功查询都保存实际 SQL、参数、完整结果与可验证回执；run/Snapshot、独立执行身份、时间/生产版本、来源与文件 SHA-256 必须可追溯。数据层不承担 Pack/Bridge/metric 语义。
- 业务清单由宿主/产品生成，绑定所选工作区配置和实际仓库/Snapshot 来源、角色、Pack/Bridge，引用同 Snapshot 的一份或多份子查询及交付文件；不能只凭同名 Snapshot 或自填公司字段接受外来证据。正式指标定义沿用 Pack.metrics；当前交付包的 metric_refs 为空，指标执行关联不排期，待具体口径问题证明需要后再评估。
- 文件路径限制在显式证据包根内；Casebook 复制明确选择的最小引用闭包并保留包内相对目录，复制后重验，删源后仍可验证。新写入不沿用扁平复制回执而丢失内部引用；已封存案例不回写，不能宣称旧证据已满足新协议。
- 看板、监控、市场 CLI 已使用新查询校验读取；看板与监控最终产物保持现状，原定统一改造已取消。现有查询证据校验保留，不增加兼容运行分支。

确定性组包 API 为 `workspace_modeling.delivery.create_delivery`；完整可调用示例见 [公共证据合同第 7 节](./evidence-contract.md#7-宿主确定性组包-api)。Bridge 的 `--snapshot-quality` 指向实际 quality 查询回执文件，而非 stdout JSON。

### 2.2 隔离留学仓与腾讯更新（现行）

留学仓与原BI工单／现金仓隔离，使用独立 `Work/StudyAbroad/current.json` 和不可变运行目录。腾讯完整Excel导出、6—9月标准历史及10月实抓已验证并在Grok入仓；最新预览已构建，此前腾讯数据批次未手动激活；本次日常接入以平台更新及真实双仓回执验收。原 `Work/workspace.json`、`Input/Data/br_work_orders`、`Input/Data/br_cash` 不写入。

日常更新使用 `data_acquisition.jobs.update_tencent_study_abroad`，从明确的当前留学Snapshot受控读取标准历史，下载后只替换指定月份；不用旧颜色表反复计算，不按目录时间猜当前文件。一次性历史清洗、标准三表导入与准确命令见 [腾讯来源说明](./tencent-docs-study-source.md)。下文单工作簿命令保留作该输入方式示例，ID须换成当前任务的新唯一值；不能把九月样本示例误当当前运行指针。

标准行保留原文件SHA、真实页签与Excel行号、归属、客户键和技术记录键。当前输入整体SHA与各历史行原始SHA用途不同；消费者从已通过Snapshot摘要校验的规范表读取合法来源白名单，不把历史行SHA改成当月原件SHA。人员贡献和主看板消费同一个留学Snapshot；跨业务识别直接使用两仓源标记：BI工单一级渠道“双分”表示留学向语培输出，腾讯标准行归属组“国际市场”表示语培向留学输出。旧 `资源流转.xlsx`（双分流转表）只供历史追溯，不再参与当前计数、姓名覆盖或缺失门禁。业务确认的6—8月留学／小语种人员历史结果继续只读沿用；9月表只作对账，不覆盖当前计算。

用户确认口径：

- 空市场归属不计市场完成，原行仍保留在私有 landing 供核对；明确非市场标签同样排除。非空但无法映射的归属保留总盘单独未映射项，不静默漏算。
- 资源按资源 ID 去重、分单日期统计；部门包含删除、回收、死单。个人默认排除删除／回收、包含死单，个人花名册状态仍遵循现行规则；状态筛选只作用于来源明确提供状态的行，腾讯当前表缺状态列时不推断删除／回收。六月无业务资源ID的CRM行保留技术记录键；同业务ID跨日期保留最新分单日，同日冲突拒绝。
- 现金只计正向签约／实缴金额：留学采用 `签约金额`、归档日期；小语种采用 `实缴金额`、业务日期。不使用净签金额或服务费收款金额，不把归档日表述为到账日。非正向源金额保留核对，不列为退款。
- 用户确认现金归属以签约／实缴 Sheet 的人工“市场资源归属人”为准，即使与资源 Sheet 同编号的归属不同，也不由资源页覆盖现金人员或团队。资源关联仅用于来源核对和受控年级维度；缺少当月资源或资源ID不漏计已有明确现金归属的金额，不按姓名硬补资源编号。
- 签约客户按留学 `客户ID`、小语种 `学员编号` 各自优先去重；缺编号时按用户确认暂用姓名同域去重，唯一姓名能对应已知编号时桥接，歧义不硬选编号；同一客户多合同的正向金额全部累计，跨团队总盘独立去重，不能加总团队或个人人数。两系统没有确认的身份对照，合并金额可展示，合并唯一人数返回不可用，并同时给出两类人数；不按姓名跨两个业务系统猜合并。
- `国际市场`直接计入留学总完成，界面不单列；即使人员在语培或虚拟人花名册，也不进入语培、线上或线下团队。SSC在界面单列，未映射归属留在总盘和私有核对明细，线上、线下团队只消费各自明确归属。
- 独立源SQL不输出同比、同期或缺失月份的伪零值；看板仅复用原已确认目标，显示已覆盖实际范围，不补配目标。人员源投影提供原始归属与“国际市场”标记，人员产能模块结合BI一级渠道“双分”识别双向贡献，再按现有名单和共创规则分摊；不在数据层解释个人绩效，不读取旧流转表。

单工作簿输入示例（旧九月样本，仅作参数说明）：

```bash
python3 -m data_acquisition.jobs.build_study_abroad_warehouse \
  --workspace customers/bi_operations \
  --source-file 'customers/bi_operations/Input/Reference/人员产能/资源与签约.xlsx' \
  --run-id run_study_abroad_sample_20261008_final \
  --snapshot-id snapshot_study_abroad_sample_20260930_v1 \
  --through-date 2026-09-30
```

受控查询（左闭右开，自动限制在明确来源截止日以内）：

```bash
python3 -m dashboard_product.management.study_abroad_query \
  --workspace customers/bi_operations \
  --snapshot-id snapshot_study_abroad_sample_20260930_v1 \
  --run-id run_study_abroad_monthly_20261008_final \
  --start-date 2026-06-01 --end-date 2026-10-01 --query-name monthly
```

命名 SQL 位于 `dashboard_product/management/sql/study_abroad/`：`facts` 为逐行事实，`monthly` 为总盘/分团队/单独项自然月汇总，`people` 为按人工归属人的个人源投影，`checks` 为排除与源质量核对。月汇总和个人 SQL 由入口展开公共事实 CTE；每份查询回执保存完整可重放 SQL 和参数。所有业务查询只引用独立来源 `landing.study_abroad_market__*`，通过现有 Data Platform 执行，输出根为 `Output/StudyAbroad`。当前6—9月历史已标准化入仓，10月按腾讯最新实抓刷新；额外补历史须提供明确来源并发布新版本，缺资料不外推。

留学渠道适配与原 BI Bridge 隔离：`study_abroad_channels` 读取当前同公司 Bridge（本次实读为1.7.0）和 FY26 渠道参考，复用既有规范渠道名；新表一级/二级合成旧路径、三级作为旧低层渠道信号的绑定先作为候选核对。原始三层与人工渠道来源均保留，人工归属人决定团队，渠道映射不重分人员、不套旧渠道准入删除市场明细。未命中与原旧渠道范围外数据保留在对应单独项；资源和金额加总必须与未映射前相同，渠道人数不能相加替代总盘独立去重。

2026-10-08用户已确认的精确三层规则统一保存于 `dashboard_product/config/study_abroad_channel_decisions.json`，使用现有 `confirmed_review` 合同，运行时优先消费该决定并生成独立 `confirmed_channel_bridge.json` v1.1.0。包括三层均为市场活动→市场活动/高校活动、小红书品牌号→网络资源/小红书、本地生活的高德门店/大众点评→网络资源/高德或大众、欧亚总部在线的知乎付费/B站免费→新媒体/SSC、异业合作其他→渠道合作/个人渠道、线下校代→其他/线下校代、无终端后缀百度搜索乐语→网络资源/百度、带推荐备注的已确认高德店铺→网络资源/高德。不使用品牌通配扩大到未确认组合，不修改原 BI Bridge。

用户进一步明确：原一二三级渠道只作参考，输出沿用看板既定口径；能确定一级是市场活动而高校/中学二级尚不明确时，以对应工单年级映射。大学学段归高校活动，初中/高中学段归中学活动；已有明确细分、精确用户规则、其他渠道以及人员团队归属不改。通用策略作为 `confirmed_review` 的语义 override 进入独立渠道 Bridge v1.2.0；此前临时单资源覆盖代码和配置已删除，不维护两条路径。

年级辅助模块为 `dashboard_product.management.study_abroad_grade`：只对需要分流的资源编号，按主 BI 工作区当前显式 Snapshot、manifest 的 `br_work_orders` 关系和真实表头，通过 Data Platform 查询资源键/工单ID/四个年级字段。不读姓名、电话、学校或金额，不导入原工单、现金事实，不改两个仓的指针或 Snapshot。年级缺失或同资源的有效工单年级冲突时，保留市场活动一级及待核二级；不从意向学历或顾问/人员推年级。复核批次 `review.json.grade_evidence` 同时记录 BI Snapshot、维度查询回执和解析结果，业务金额/资源仍来自独立留学 Snapshot，两个来源身份分别回查。样本中的高一资源197265843自动归中学活动，不依赖写死资源编号。

其他未确认的新来源绑定仍为 `bridge_candidates.json` 中的 proposed，不自动建成正式映射。候选沿用现有合同的未确认角色 `historical_scan`；不扩展合同角色或修改 Pack。渠道参考、原 Bridge、确认决定、年级维度证据、映射预览、完整 SQL 和回执均留在同一私有核对批次。确认文件及年级来源必须与工作区公司身份一致；重复或冲突决定阻断。

```bash
python3 -m dashboard_product.management.study_abroad_channels \
  --workspace customers/bi_operations \
  --snapshot-id snapshot_study_abroad_sample_20260930_v1 \
  --run-id run_study_abroad_channels_20261008_final \
  --start-date 2026-06-01 --end-date 2026-10-01
```

管理计算继续复用 `study_abroad_facts.py` 及 `management/calculation.py`：从独立仓显式 Snapshot 读取工单、正向现金和人头管理事实，保留来源产品、资源编号、客户键、来源行及本Sheet归属。BI事实与留学事实保持各自来源身份。总盘／线上／线下、渠道现金、个人现金、活动及通知所需汇总按已确认口径计算；国际市场／SSC／待确认归属仅计留学总盘，留学和小语种客户去重结果分别保留。上述业务口径由服务器raw计算链路复用，不提供原管理构建命令。

人员产能与上述主看板归属分别核算：它从同一留学Snapshot的标准行读取“国际市场”作为语培向留学的跨业务输出，并从BI工单一级渠道“双分”读取反向输出；双方按现有人员名单、源归属与共创规则分摊。此改动不把国际市场改归语培总盘或线上／线下留学团队，不改变主看板个人与通知口径。

当前服务器raw链路接收固定三Excel，在root只读历史基线副本上建立双Snapshot、运行quality和共享计算至39表，再由固定publisher按P4合同发布。10月26日真实批次实际跑到39表后被截止门禁拦截，状态 `failed/published=false`；因此有效raw新包正式发布、持续日更和唯一生产者收口仍待分别验收。Mac `shadow_bi.p5.daily` 仍存在并有10月26日手动运行记录，不作为长期默认入口。10月26日服务器部署不含当前main新增的来源完整性证明门禁；见[raw合同](server-raw-pipeline-contract.md)和[来源完整性合同](server-source-completion-candidate.md)。

### 2.3 投放费用手工输入

广告费用只通过用户手工提供的原表进入计算：将本批文件放在客户工作区 `Input/AdvertisingCosts/files/`，在 `Input/AdvertisingCosts/sources.json` 中登记相对路径、业务线、业务组、平台、来源期间及文件 SHA-256。共享计算只读取清单声明的文件；没有清单时费用状态为“未提供”。费用随服务器raw双Snapshot计算链路进入原生BI。

本节仅说明ROI费用输入。腾讯留学仓的定期导出更新继续服务留学资源与签约数据，不会自动补入广告费用。支持格式、期间差额和费用共同覆盖窗口见[线上看板费用与ROI](./dashboard-advertising-costs.md)。

## 3. Agent Host 接入

CLI 是宿主无关边界。Codex、DeepSeek Harness 和其他具备受控 Shell 的 Agent Host 都在项目工作区直接执行：

```bash
python3 -m interfaces.data_platform <command> ...
```

宿主侧只需要：

- 把项目目录设置为受控工作区；
- 使用宿主原生 Agent、模型、Session 和工具系统；
- 允许调用项目 Python 环境和 Data Platform CLI；
- 用 Skill 或项目说明告诉模型子命令、参数和输出约定；
- 读取 stdout JSON、进程退出码和显式产物路径；
- 把 API Key、客户路径和源数据留在机器或客户工作区，不提交仓库。

当前业务操作使用 CLI，不要求不同宿主安装同一协议插件，也不把 Codex 或 DeepSeek Harness 再封装成项目内 Agent。已存在的 Project Intelligence stdio MCP 只读项目上下文，不开放业务 SQL。Business MCP 后置评估，必须复用工作区/语义检查与 Data Platform 受控入口，不直连 DuckDB。

### Codex

Codex 已通过项目 Shell 完成 CLI 命令链和错误处理验证，不增加新的数据服务。日常直接在对应客户工作区调用同一 CLI；换公司或角色时使用 Codex 原生新任务/记忆清理并切换工作区。

### DeepSeek Harness

计划链路为：

```text
DeepSeek Harness → controlled shell → Python CLI → Data Platform
```

Harness 全局安装、Web、真实模型回合、项目 Workspace、受控 Shell、真实三表 `inspect → ingest → describe → quality → query`、项目 Skill `diagnose-source-overlap` 调用，以及三张真实教务表的陌生结构识别、Bridge 生成、教师课量查询和图表输出均已通过。主线现金明细与工单分析、可打开 PPTX 生成及渲染回查也已通过。该流程直接使用 Harness 原生 Agent，不依赖正式 `CandidateAdapter`。

### 重叠与清洗

同一端口全量文件更新时替换同一 `Input/Data/<source_id>` 当前文件并发布新 Snapshot，不跨 Snapshot 合并。当前 Snapshot 内多来源可能重叠时，宿主使用项目 Skill `diagnose-source-overlap`，通过现有 `describe/query` 自主检查日期范围、候选业务键、重复和冲突；客户确认业务键与来源优先级后，再用 `promote-query` / `run-saved-query` 固化只读 SQL。该逻辑不进入 Bridge，也不修改 landing。

## 4. Education Business Pack

首版 Pack 可通过同一 Python 环境调用：

```bash
python3 -m interfaces.business_pack validate
python3 -m interfaces.business_pack describe
```

`validate` 校验 manifest schema、稳定 ID、重复项以及概念、指标、维度、旅程、漏斗和 Playbook 的交叉引用；失败返回结构化 JSON 和非零退出码。`describe` 返回版本、范围和精简清单，不展开全部知识正文。两条命令都可用 `--pack PATH` 指向待校验的 Pack。

内置 Pack 为 `education_training_operations_cn` v1.0.0。它不接收 `snapshot_id`，也不包含当前企业字段、枚举、SQL 或清洗选择。

## 5. Company Bridge

Company Bridge 通过同一 Python 环境调用：

```bash
python3 -m interfaces.company_bridge --help
python3 -m interfaces.company_bridge validate-candidates \
  --input /path/to/confirmed_candidates.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json \
  --require-role confirmed_review
python3 -m interfaces.company_bridge validate \
  --bridge /absolute/path/to/confirmed-workspace-bridge.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
```

当前 BI 工作区实读 Bridge 为 `bridge_bi_operations` v1.7.0。它引用当前 `landing.*` 关系，直接使用源表头名定位字段；在 v1.6.0 留学渠道映射基础上增加线上主动网络资源补充完成口径。具体运行时可额外传入同一 Snapshot 的 `--snapshot-description` 与 `--snapshot-quality` 做兼容性校验。旧清洗脚本和看板尚未完整消费所有渠道规则，例如根别名和市场活动细分仍存在实现差异；隔离留学渠道核对按第2.2节处理，不原地修改旧来源契约。

历史扫描使用 `scan-history`，但输出角色是 `historical_scan`，不能直接构建正式 Bridge。只有人工复核后的 `confirmed_review` 可以传给 `build`；未确认项必须保留为 `unresolved` 或拒收，不能静默选择。完整合同见 [Company Bridge v1 合同](./company-bridge-contract.md)。

## 6. Bridge 对齐向导

首次部署优先使用上面的 `workspace-modeling` 入口：用户只需选择业务端口，工作区路径会自动生成内部 `company_id`。下面是需要直接编排 Bridge 向导时的低层 CLI 示例，其中 `--company-id` 仅是机器身份字段，不是用户需要填写的公司名称。

公开入口：

```bash
python3 -m interfaces.bridge_alignment --help
python3 -m interfaces.bridge_alignment init \
  --workspace customers/company_customer \
  --company-id company_customer \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
python3 -m interfaces.bridge_alignment sync-data \
  --workspace customers/company_customer \
  --snapshot-id snapshot_customer_2026_08
```

`init` 创建 `Input/Work/Output`，并把 Pack 与可选同公司 Bridge 复制进工作区。客户把当前文件分别放进 `Input/Data/<source_id>/`；每个稳定来源槽位只放一个 XLSX/XLSM。七月换八月时直接替换当前文件，再用新的显式 `snapshot_id` 执行 `sync-data`；向导先发布并切换新 Snapshot，再删除旧 Snapshot，工作区只保留当前 Snapshot。导入失败或当前 Snapshot 尚有未完成会话时不会切换。

`start` 从当前 Snapshot 建立一个对齐会话目录及其 `session.json`；同公司的旧 Bridge 仅作为企业口径参考，不代表已适配当前 Snapshot。宿主原生 Agent 负责读取画像、调用自己的模型、向客户提问，并通过 CLI 提交确定性决定与 `finalize`。现有 `propose --adapter module:attribute` 是程序化候选注入入口，供合同测试或批处理集成使用；它不是需要建设的 Harness/Codex Adapter 服务。`add-evidence` 把 U 盘/目录资料复制进 `Input/Reference`；`finalize` 写入 `Output/Bridge/<version>`。新公司不得传上一家 Bridge。

CLI 完成当前阶段且无需客户输入时退出 `0`，等待确认或被关键问题阻断时退出 `2`，合同、身份、候选注入、文件或验证错误退出 `1`。stdout JSON 是宿主机器接口，客户不需要查看或编写。测试 fake adapter 只验证模型候选合同；生产运行由当前宿主原生 Agent 主控。精确合同见 [Bridge 对齐向导 v1 合同](./bridge-alignment-wizard-contract.md)。

## 7. Casebook、内测回收与引导路由（S5 已实现）

S5 通过单一宿主无关 CLI 提供 Casebook、内测评价与本地引导：

```bash
python3 -m interfaces.casebook --help
python3 -m interfaces.casebook guide --workspace customers/company_customer
```

`runs/` 保持本地原始证据，不能作为长期记忆被整目录读取或自动上传。Casebook 使用 `case-create` 逐项指定证据，或使用 `case-capture --manifest Work/analysis_capture.json` 读取一个由宿主 Agent 明确整理的 `casebook_capture.v2` manifest；确认后用 `case-confirm`，检索使用 `case-search`。两种入口都复制最小查询证据、SQL、哈希、版本和限制，后续只能在同一客户与角色范围内检索；涉及当前事实时仍须查询当前 Snapshot。`case-verify` 校验归档引用闭包及封存身份，删除原运行目录后仍可验证。

本地部署的内测用户用 `test-pack-import`、`evaluation-start`、`evaluation-record-card` 和 `evaluation-complete` 执行版本化测试包，主动用 `feedback-export --export-type metrics-only` 导出默认脱敏反馈；用户可用 `evaluation-attach-evidence` 显式选择附加证据，再导出 `evidence-approved`。`feedback-verify` 只校验 ZIP 清单和哈希，不联网。项目不自动上传客户工作簿、DuckDB、Parquet 或 `runs/`。引导路由只提示工作区初始化、数据同步、Bridge 对齐、分析或 `repeat-candidates` 候选沉淀，既不取代宿主 Session，也不自动发布 Skill。实现接口与目录合同以 [S5 合同](./casebook-pilot-contract.md) 为准。

已完成 Bridge 对齐后，宿主 Agent 可使用项目级 [业务分析路由 Skill](../.agents/skills/business-analysis-routing/SKILL.md) 处理日常问题。它只规定最小调用顺序：先用 `guide` 检查当前工作区状态，再按角色/问题类别用 `case-search` 找同公司确认案例；案例只提供方法线索，当前数字必须通过 Data Platform 以显式 `snapshot_id`、`run_id` 的只读 `describe`/`quality`/`query`（或确认后的 `run-saved-query`）重新取得。用户明确验收后才用 `case-create` 保存 candidate，交付物需回查本次查询；保存时逐项核对交付清单与当前工作区 Snapshot/Pack/Bridge 身份，`casebook_capture.v2` manifest 不重复传入这些字段；`repeat-candidates` 只提出人工审核候选，不自动生成或发布 Skill。该 Skill 不实现 Agent Loop、Session、SQL 编译器或额外存储。

## 8. 宿主交付能力

项目不新增通用输出平台，也不内置 PPT Master。电子表格和数据可视化先使用宿主原生能力；PPTX 由宿主全局 `ppt-master` Skill 负责，项目不固化 Quick/Default 分流。

自由分析将当前 Snapshot 的受控查询结果、分析结论、口径、时间范围、来源和限制作为 PPT 输入。全局 Skill 按它的当前路由规则选择 Quick 或 Default；项目不复制其 SVG、模板、Renderer、依赖或质量门禁。无论选择哪种模式，交付文件都必须可打开、内容非空，关键数字能回查到同一受控查询。全局 Skill 不可用时，只阻断 PPT 交付，不使已完成的分析或证据失效。

## 9. 固定看板与钉钉

服务器正式看板链路由固定服务执行：三Excel输入进入raw receiver，受限worker读取root只读历史基线，在隔离副本更新双Snapshot并运行quality和共享计算，生成39张业务表；达到 `prepared` 后，固定root publisher按P4合同重建、验收并切换 Superset release。通知包再由 `release_notifications` 从正式release构建，`shared_delivery` 按DeliveryState逐消息去重投递。接收、计算完成、准备发布和正式发布分别读取同批状态回执。

当前服务器正式通知使用 `server_notify` 固定入口与 `release_notifications` 同批包；HTTP只接受operation、expected_release和as_of_date，不接受任意路径或接收者。八条消息投递至原五通道，高中留学简报保持个人完成与个人流水。10月26日已有8条sent；后续HTTP job仍保留unknown，只读对账不等于该job自身成功发送。见[通知修复回执](notification-job-receipt-repair-20261026.md)。

10月26日人工触发有8条 `sent`；相应HTTP job仍为 `unknown`，只读对账不等于该job自身成功。Dot 10:00建立记录针对通知，不代表BI采集发布已持续运行。Grok例行已按用户要求停止。有效raw包正式发布、持续日更和唯一生产者收口仍待分别验收，任务实时状态须由宿主实读，不从本地Git更新推断。部署与publisher边界见[部署说明](../dashboard_product/DEPLOYMENT.md)，通知合同见[监控模块](../monitoring_product/README.md)。Webhook属于C层，不在本指南展开。

## BI 派生查询库（沿用P2受控查询合同）

业务批次不是原始Snapshot。Agent读取已封口的派生库使用 `python3 -B -m interfaces.business_library describe|query --library <明确目录> --batch-id <明确批次>`；查询必须带run-id及输出目录，不直接连接DuckDB。来源绑定、表粒度、限制和 `business_query_receipt.v1` 见[业务查询库合同](shadow-bi-p2-query-contract.md)。现有Snapshot查询入口与生产发布/推送保持原合同。
