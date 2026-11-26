# 核心 CLI 接入指南

## 1. 公开入口

- `python -m ops status` 核对候选、发布版本与完成状态。日更、补数、费用及腾讯同步见[运维手册](operator-runbook.md)。
- `market_workspace/oxhor` 绑定正式经营工作区。受控查询、归因证据和导出见[市场接口](../market_workspace/INTERFACES.md)。
- `python -m interfaces.data_platform --help` 提供 `inspect`、`ingest`、`describe`、`quality`、`query` 及已确认查询等低层入口。输入与输出使用明确路径、独立 run ID 和 Snapshot 身份。
- Business Data MCP 同事安装与验证见[客户端接入](../business_data_mcp/client/接入说明.md)；工作区元数据见[Project Intelligence](project-intelligence.md)。

## 2. 快照、语义和业务口径

### 2.1 可核验查询结果

Snapshot 区分 landing 来源及版本。查询在明确仓与 Snapshot 执行只读 SQL，保留使用的 SQL、参数、源身份和结果哈希。经营语义查询绑定正式封存 SQL release，从准入清单查询 `core`、`mart` 或 `ref`。同一查询的分页和 CSV 使用同一个结果身份。 [指标与证据关系](metrics-reference.md)

### 2.2 隔离留学仓与腾讯更新（现行）

留学仓与原BI工单／现金仓隔离，使用独立 `Work/StudyAbroad/current.json` 和不可变运行目录。业务确认的6—9月历史与腾讯文档当前月份共同构成留学数据。SQL正式看板消费显式双Snapshot，当前批次与覆盖范围见 `Output/ShadowDaily/sql-current.json`。留学仓更新不写入 `Work/workspace.json`、`Input/Data/br_work_orders`、`Input/Data/br_cash`。

日常更新使用 `data_acquisition.jobs.update_tencent_study_abroad`，从明确的当前留学Snapshot受控读取标准历史，下载后只替换指定月份；不用旧颜色表反复计算，不按目录时间猜当前文件。一次性历史清洗、标准三表导入与准确命令见 [腾讯来源说明](./tencent-docs-study-source.md)。下文单工作簿命令保留作该输入方式示例，ID须换成当前任务的新唯一值；不能把九月样本示例误当当前运行指针。

标准行保留原文件SHA、真实页签与Excel行号、归属、客户键和技术记录键。当前输入整体SHA与各历史行原始SHA用途不同；消费者从已通过Snapshot摘要校验的规范表读取合法来源白名单，不把历史行SHA改成当月原件SHA。人员贡献和主看板消费同一个留学Snapshot；跨业务识别直接使用两仓源标记：BI工单一级渠道“双分”表示留学向语培输出，腾讯标准行归属组“国际市场”表示语培向留学输出。旧 `资源流转.xlsx`（双分流转表）只供历史追溯，不再参与当前计数、姓名覆盖或缺失门禁。业务确认的6—8月留学／小语种人员历史结果继续只读沿用；人员产能的9月参考表只作对账。2026-11-26经确认的9月资源与签约原表已用于修订独立留学Snapshot，日常更新继续保留该历史月份。

用户确认口径：

- 资源归属仍按原规则。签约和实缴无法匹配个人时，来源明确标为线上组、线下组或有逐笔业务确认，可计入对应团队，不计个人完成。没有明确团队的空归属及明确非市场标签排除；其他无法映射的非空归属继续留在总盘待核。
- 资源按资源 ID 去重、分单日期统计；部门包含删除、回收、死单。个人默认排除删除／回收、包含死单，个人花名册状态仍遵循现行规则；状态筛选只作用于来源明确提供状态的行，腾讯当前表缺状态列时不推断删除／回收。六月无业务资源ID的CRM行保留技术记录键；非空资源ID按传入来源及源行顺序保留首条，后续同ID记录无论日期或字段是否冲突均跳过。
- 现金只计正向签约／实缴金额：留学采用 `签约金额`、归档日期；小语种采用 `实缴金额`、业务日期。不使用净签金额或服务费收款金额，不把归档日表述为到账日。非正向源金额保留核对，不列为退款。
- 已明确的现金人员归属以签约／实缴 Sheet 的人工归属及已确认映射为准。缺少个人归属时可使用同一签约／实缴行的明确团队。资源关联仅用于来源核对和受控年级维度，不能覆盖签约行的归属。
- 签约客户按留学 `客户ID`、小语种 `学员编号` 各自优先去重；缺编号时按用户确认暂用姓名同域去重，唯一姓名能对应已知编号时桥接，歧义不硬选编号；同一客户多合同的正向金额全部累计，跨团队总盘独立去重，不能加总团队或个人人数。两系统没有确认的身份对照，合并金额可展示，合并唯一人数返回不可用，并同时给出两类人数；不按姓名跨两个业务系统猜合并。
- 正式看板的留学工单、现金和签约人头采用同一团队范围。线上包含线上虚拟人，总计剔除 SSC，SSC 可单独查询。`国际市场`计入留学总计，保留自己的来源归属。线上和总计分别按各自范围重新计算去重人头。
- 独立源SQL不输出同比、同期或缺失月份的伪零值；看板仅复用原已确认目标，显示已覆盖实际范围，不补配目标。人员源投影提供原始归属与“国际市场”标记，人员产能模块结合BI一级渠道“双分”识别双向贡献，再按现有名单和共创规则分摊；不在数据层解释个人绩效，不读取旧流转表。

单工作簿输入示例（旧九月样本，仅作参数说明）：

```bash
python3 -m data_acquisition.jobs.build_study_abroad_warehouse \
  --workspace customers/shadow_bi_daily \
  --source-file 'customers/shadow_bi_daily/Input/Reference/人员产能/资源与签约.xlsx' \
  --run-id run_study_abroad_sample_20261008_final \
  --snapshot-id snapshot_study_abroad_sample_20260930_v1 \
  --through-date 2026-09-30
```

受控查询（左闭右开，自动限制在明确来源截止日以内）：

```bash
python3 -m dashboard_product.management.study_abroad_query \
  --workspace customers/shadow_bi_daily \
  --snapshot-id snapshot_study_abroad_sample_20260930_v1 \
  --run-id run_study_abroad_monthly_20261008_final \
  --start-date 2026-06-01 --end-date 2026-10-01 --query-name monthly
```

命名 SQL 位于 `dashboard_product/management/sql/study_abroad/`：`facts` 为逐行事实，`monthly` 为源数据口径的自然月汇总，`people` 为按人工归属人的个人源投影，`checks` 为排除与源质量核对。这里的 `monthly` 用于来源对账，其 total 包括 SSC，线上按来源团队，不套用正式看板的虚拟人归类。核对正式看板应查询同批 SQL release 的 `business.team_values` 或 `business.team_metrics`。月汇总和个人 SQL 由入口展开公共事实 CTE；每份查询回执保存完整可重放 SQL 和参数。所有业务查询只引用独立来源 `landing.study_abroad_market__*`，通过现有 Data Platform 执行，输出根为 `Output/StudyAbroad`。6—9月历史已标准化入仓，日常按明确月份更新腾讯来源；额外补历史须提供明确来源并发布新版本，缺资料不外推。

留学渠道归因消费 FY26 渠道参考及 `dashboard_product/config/study_abroad_channel_decisions.json` 中已确认的同源三层规则。来源团队与经营范围分别核算，未命中保留证据。渠道人数不能相加代替总盘去重。

2026-10-08用户已确认的精确三层规则统一保存于 `dashboard_product/config/study_abroad_channel_decisions.json`，SQL 构建读取已确认决定。包括三层均为市场活动→市场活动/高校活动、小红书品牌号→网络资源/小红书、本地生活的高德门店/大众点评→网络资源/高德或大众、欧亚总部在线的知乎付费/B站免费→新媒体/SSC、异业合作其他→渠道合作/个人渠道、线下校代→其他/线下校代、无终端后缀百度搜索乐语→网络资源/百度、带推荐备注的已确认高德店铺→网络资源/高德。不使用品牌通配扩大到未确认组合。

用户进一步明确：原一二三级渠道只作参考，输出沿用看板既定口径；能确定一级是市场活动而高校/中学二级尚不明确时，以对应工单年级映射。大学学段归高校活动，初中/高中学段归中学活动；已有明确细分、精确用户规则、其他渠道以及人员团队归属不改。

年级辅助模块为 `dashboard_product.management.study_abroad_grade`：只对需要分流的资源编号，按主 BI 工作区当前显式 Snapshot、manifest 的 `br_work_orders` 关系和真实表头，通过 Data Platform 查询资源键/工单ID/四个年级字段。不读姓名、电话、学校或金额，不导入原工单、现金事实，不改两个仓的指针或 Snapshot。年级缺失或同资源的有效工单年级冲突时，保留市场活动一级及待核二级；不从意向学历或顾问/人员推年级。复核批次 `review.json.grade_evidence` 同时记录 BI Snapshot、维度查询回执和解析结果，业务金额/资源仍来自独立留学 Snapshot，两个来源身份分别回查。样本中的高一资源197265843自动归中学活动，不依赖写死资源编号。


```bash
python3 -m dashboard_product.management.study_abroad_channels \
  --workspace customers/shadow_bi_daily \
  --snapshot-id snapshot_study_abroad_sample_20260930_v1 \
  --run-id run_study_abroad_channels_20261008_final \
  --start-date 2026-06-01 --end-date 2026-10-01
```

正式 SQL 看板通过受控来源查询读取独立留学 Snapshot，保留来源产品、资源编号、客户键、来源行及本 Sheet 归属；BI事实与留学事实保持各自来源身份。线上经营汇总纳入虚拟人，总计排除SSC并保留国际市场及待确认归属。团队和总计分别对留学、小语种签约人头去重，SSC可单列。旧 raw 管理计算与该 SQL 汇总具有不同的历史实现，现行看板以 SQL 发布口径为准。

人员产能与上述主看板归属分别核算：它从同一留学Snapshot的标准行读取“国际市场”作为语培向留学的跨业务输出，并从BI工单一级渠道“双分”读取反向输出；双方按现有人员名单、源归属与共创规则分摊。此改动不把国际市场改归语培总盘或线上／线下留学团队，不改变主看板个人与通知口径。

服务器 raw 链路在10/26已接收固定三Excel、执行双Snapshot、quality和39表计算；该批被截止门禁拦截，状态 `failed/published=false`。11/3完成回执仍记载 raw 计算/发布 path inactive。该链路的历史合同与本机当前总入口分开维护；10/26服务器部署不含当前 main 的来源完整性证明门禁。详见[raw合同](server-raw-pipeline-contract.md)和[来源完整性合同](server-source-completion-candidate.md)。

### 2.3 广告费用

以可核验的费用或零额声明独立录入。可选来源采集只生成审计证据。费用与 ROI 的日期和口径见[费用说明](dashboard-advertising-costs.md)。
