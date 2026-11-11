# 业务 SQL 化与费用建仓：SQL 正式切换记录

## 最新业务组筛选状态（2026-11-07）

正式 release `daily-sql-overview-group-20261107` 已激活。市场总览的业务组筛选为“市场总计／高中／大学／留学预备”；语培按所选业务组汇总线上、线下各渠道产出，留学及小语种固定显示总盘。11 张语培图联动该筛选，语培学校图已补入；其他页面的口径和样式保持不变。

原有 5,508 行指标与旧仓一致，新增 243 行分组指标与明细独立核算一致；40 项测试通过，2 项按条件跳过。费用为 4,041 行、43 个来源，标注截至 2026-11-06；复用同一批数据，不重采业务及费用源表、不触发日报推送。18 项正式指标与 MCP 5 项检查通过。bi-3 只读复查通过，采集、发布及通知回调均为 0；正式站 93 图、270 个业务分页已完成核对，字段、行数及记录集合全部一致；旧版已退役，服务器仅保留 1 份分析仓，投递状态逐字节不变。

证据：[activation.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/activation.json>)、[publication-receipt.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/publication-receipt.json>)；本批审计目录：[overview-group-20261107](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/>).

最终核验：88 张图逐行顺序相同；5 张图（231、320、331、332、333）仅同值并列行换位，93 张图完整记录集合相同。保留原排序规则；图 231 原网页分页现象未作次排序修复，完整 CSV 的 59 条唯一记录与旧版一致。线上曾触发旧 1400M 服务限额 OOM，已持久调至 4G，3 并发与后续全页复验通过；未改数据、线程数或查询内存配置。

最终回执：[completion.json](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/audits/overview-group-20261107/completion.json>)。

## 历史：业务组筛选发布前的链路及费用恢复记录（2026-11-07）

当前正式费用版为 `daily-sql-20261107-153941950641-7520a35133`；语培、留学和费用更新标注均为 2026-11-06，费用受控查询确认 4,041 行、43 个来源。原总入口费用补跑已成功，最终 complete／退出码 0；复用今日双 Snapshot，不重新采集业务。18 条经营指标补跑前后相同，正式单仓、18 项激活指标、MCP 5 表及公网查询通过。

本次费用恢复没有发日报：发送入口调用 0 次，补跑前后全部 96 条投递记录逐值不变；今日此前 8 条 sent 保持原记录。最初业务实测的旧 88 条记录也未变；工单反馈此前新增 15 条且已读回。既有费用覆盖缺口仍如实展示，不补零。

最新证据见[费用补跑结果](</Users/akechi/Desktop/manager -CowH/.local/audits/sql-fee-recovery-20261107/费用补跑结果.md>)。此前[首次业务实测结果](</Users/akechi/Desktop/manager -CowH/.local/audits/sql-daily-e2e-20261107/完整流程实测结果.md>)记录了当时的费用认证失败；该阶段现已恢复。下方迁移首发记录保留当时批次和日期，当前状态以最新回执为准。

## 迁移首发部署记录（2026-11-07）：已切换并完成旧仓清理

正式 current 为 `daily-sql-20261106-cutover-20261107`，业务批次 `run_sql_online_exact_20261107`；绑定 2026-11-06 的原双 Snapshot，语培、留学和费用均截至 2026-11-05。仓库 SHA-256 `155840e6fd3cf348aa42f62ad7b97fc26b36b15283e22c6cd71b9740b1cc4fee`。本地同批核验的 93 份 CSV 字节一致、93 份 XLSX 语义一致；正式切换后 94/94 API 请求及 12 份导出与旧线上一致。

chart 231 保留原有分页表现：网页返回 59 行、58 条唯一记录，跨页重复一行；完整 CSV 含 59 条唯一记录，与旧导出一致，没有完整导出数据丢失。页面覆盖 7 个页签、43 个分区；截图对照不宣称逐像素相同。

bi-3 仍为每天 09:30，原命令、来源和日程不变；提示词仅更新两处 SQL 说明。本次未触发新日更、通知或推送。46 项运行文件哈希、18 项业务指标、MCP 5 项检查及 8 条 dry-run 通知状态均通过／保持不变；DeliveryState 未变，未发送通知。

旧服务器仓清理已完成：分析仓从 37 份收敛为 1 份；旧正式版本 164 个文件已归档本地，旧候选、校验仓及 raw 计算／传输目录已清理。保留必要运行文件、Superset 元数据库、配置密钥、DeliveryState 与有限运维日志。清理后运行检查通过，旧业务发布路径停用，通知路径保留。

完整验收证据已归档到主目录 `.local/archive/business-sql-local-20261111/sql-migration/online-acceptance-20261107/`，详见[上线结果与 bi-3 衔接回执](</Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/sql-migration/online-acceptance-20261107/上线结果与BI3衔接.md>)。原 checkout 的日更基线位于 `.local/sql-daily/candidates/`，显式指针位于 `customers/shadow_bi_daily/Output/ShadowDaily/sql-current.json`；本批验收证据保留在上述主目录归档。以下标明“历史”的未上线描述仅记录其当时状态，不是现行操作指令。

## 历史：切换前本地核验记录（2026-11-07）

当前候选为 `.local/sql-migration/online-acceptance-20261107/candidate-current-lineage/warehouse.duckdb`，批次 `run_sql_online_exact_20261107`，数据库 SHA-256 `155840e6fd3cf348aa42f62ad7b97fc26b36b15283e22c6cd71b9740b1cc4fee`。`candidate.json` 绑定 as-of 2026-11-06、语培与留学业务均截至 11 月 5 日；费用截至 11 月 5 日，共 3,975 行、43 个来源。该候选仍是本地构建结果，不是服务器 release。

- 本批全 93 张图的 CSV 已按字节核对一致；93 份 XLSX 已按工作簿语义核对一致。复核回执为 `.local/sql-migration/online-acceptance-20261107/sql-calibrated-exports-all-final/capture.json`。269 个 API 页正在复验，当前不能宣称 API 全部通过。
- 图表 231 的旧端分页共显示 59 行，其中跨页重复 1 行、因此漏显 1 条独立记录；新端为 59 条唯一记录。该图完整 CSV/XLSX 与旧端导出一致。此例不代表所有 API 页有序一致。
- 43 个分区当前覆盖 41 个完整分区和 2 个自然补拍分区。本地已恢复线上颜色：本期紫 `#454E7C`、同期绿 `#5AC189`；仍在补验 5 个分区，不据此声称所有 DOM／截图像素通过。
- Mac 继续使用既有 bi-3 来源与日程。本工作树的 `p5.daily` 计算发布段改用本地 SQL 建仓、`sql_bundle.prepare_release` 和 P4 SQL activation，不再调用 Python `calculate` 生成 39 张结果表。服务器尚未安装这条链路。
- SQL release 以七个运行文件和单一 `warehouse.duckdb` 交付，由 Superset、MCP 和通知共用同批仓库。费用刷新失败时保留上一批已提交费用及原费用日期，不阻断已通过的业务发布／通知阶段；不把失败费用写成成功刷新。

服务器接线仍待本地同批核验和逐页验收完成后实施。计划入口与待做项如下，不是已执行回执：

| 环节 | 计划接线位置 | 切换要求 |
|---|---|---|
| Superset／数据集／页眉／选项 | `/srv/shadow-bi/code` | 保留 159 个数据集、8 个 options、图表与筛选元数据；切换 URI 到同一个仓库，清理旧查询缓存并 dispose 连接 |
| 旧业务 receiver | `/srv/shadow-bi/raw-code` | SQL candidate 成为唯一来源后退役旧 39 表上传／计算入口；保留通知接收路径 |
| 通知 | `/srv/shadow-bi-notify/current`、`/usr/local/sbin/shadow-bi-notify` | 改读候选通知预览，继承原 `DeliveryState`、去重和 no-backfill；不重发既有消息 |
| Business Data MCP | `/srv/business-data-mcp/venv/lib/python3.12/site-packages`、`/usr/local/libexec/business-data-mcp/acl_sync.py` 及其 venv `ExecStart` drop-in | 让只读查询指向同批单仓并保留 allowlist／ACL 门禁 |

切换时停用旧 `shadow-bi-publisher.path`、`shadow-bi-receiver-publish.path` 及 raw 接收／计算／发布入口；保留 `shadow-bi-receiver-notify.path`。仅在所有消费者同批验收后原子切 `current`；失败时恢复原 URI 和 current。首次旧仓先归档到本地，核销 32+4 份旧仓依赖后再收敛为一份正式数仓。旧 SQL release 需成功核验后再通过独立维护回执退役。当前未改服务器、bi-3、正式数据、指针或 DeliveryState。

## v11 历史批次记录

以下各节保留此前 v11 候选的输入、结构、差异与验收细节，便于追溯；不描述当前候选，也不改变上面的当前状态。

### v11 历史验收状态（旧候选）

- 固定同批旧／新看板覆盖 93 张图、97 个放置位置、273 个 DOM 分页和 43 个分区；269 个分页 API 的字段、类型、有序值，以及 186 份 CSV／XLSX 导出均通过。CSV 比字节；XLSX 比单元格值、类型、格式和布局，不要求 ZIP 时间戳相同。COUNT 查询独立处理，不并入业务行。
- v11 全量首发 93/93 HTTP 200，实际浏览器和导出流程未再出现 OOM、400 或 ERROR。核心字段 5,749,651 项、维度字段 7,721,051 项、scope 目标 408 项通过；176 条源码封口 SHA 未变。回归 118 passed、42 subtests passed（110.46 秒，无 skip）。
- 原布局、CSS、93 张图参数、86 个筛选和导出合同保留。实际发现现金图隐式共享配色随返回顺序交换，已在本地显式固定旧版原有五项颜色；不是改选新配色。补拍 13 张相关图及 6 个分区，数据与原色一致。逐项残差见下文，不能据此宣称全部像素相同。
- 本地日期标注已单独核验，仅增加费用日期：`语培截至 2026-11-05 · 留学截至 2026-11-05 · 费用截至 2026-11-04 · 金额单位：元`，其他 Markdown、标题和单位保留。
- 两张表 332／333 的并列工单行序仍不同；旧端同一请求重复执行也换序，原 SQL 没有次排序键。保持原排序规则，不擅自新增排序。另有少量像素／尺寸残差，完整旧截图中大学渠道有一项摄影状态问题；自然视口补拍 349／350 单图与旧版像素相同。尚未达到逐页像素完全一致的验收结论，因此不进入上线。
- 服务器、bi-3、任务日程、正式数据、发布指针及消息均未动。服务器适配尚未施工，本候选不是可直接替换的生产包。

### v11 历史输入与口径

固定同一批 2026-11-06 Snapshot 对：语培 `snapshot_bi_operations_20261106_093634`，留学 `snapshot_study_abroad_20261106_093634`，业务统计截至 11 月 5 日。费用原件以 SHA 核验后复制到冻结输入，日期截至 11 月 4 日。输入绑定和费用复制核验分别在 `.local/sql-migration/input-binding.json`、`fee-freeze.json`。

沿用原有归属、目标、主被动、部门自然月、个人 26—25 日、人员状态开关、跨系统分域和官方记分卡政策。负向现金保持负向现金；缺覆盖、缺费用及未配置仍为空值或原状态。SQL 迁移不借机调整业务口径。

### v11 历史仓库结构

v11 候选 `.local/sql-migration/final-candidate-v11/warehouse.duckdb` 只保留一份仓库。原始事实从受控查询进入 5 张 `landing` 基础表，费用在独立的 `expenses` 表中保存；静态业务映射和目标保存在必要的 `config` 小表。语培来源顺序血缘保留 75,659 个 SQL 来源序号和 3 份封存回执，不恢复旧 39 张逐图 JSON 业务表。

| 内容 | v11 实际保留 | 用途 |
|---|---|---|
| `landing` 基础明细 | 5 张 | 语培工单、语培现金、留学资源、留学签约、小语种现金；来自原 Data Platform 受控查询并保留 Snapshot 身份 |
| `expenses.expense_rows`、`expenses.expense_sources` | 2 张 | 费用自然键、归属、金额、源 SHA、覆盖范围及缺失信息；未报告金额仍为 NULL |
| `config` | 必要静态小表 | 已确认的目标、人员、渠道映射及固定历史基准 |
| `business.fact_cache` | SQL 生成缓存 | 统一业务事实和个人资格标记 |
| `business.contribution_ledger_cache`、`business.contribution_result_cache` | 2 张 SQL 缓存 | 贡献台账与月度产能计算结果 |
| `business.contribution_marker_audit_cache` | 76 行 SQL 缓存 | marker 审计和历史结果呈现 |
| `business.online_daily_cache` | 19,236 行 SQL 缓存 | 三种主被动的平台日汇总，供日趋势、费用与 ROI 共用 |
| `business.scoped_team_periods_channel_cache` | 306 行 SQL 缓存 | 学校及渠道图的三种主被动、期间和团队来源顺序 |
| `business.university_channel_nodes_cache` | 9,832 行、25 列 SQL 缓存 | 大学渠道的 group/school typed nodes；1,531 group、8,301 school，两条业务线共用 |
| `source.training_source_order`、`meta` | 75,659 个来源序号及封存回执 | 重现 SQL 来源遍历顺序并记录批次、Snapshot 和受控来源查询身份 |

以上 7 张共用业务缓存均由 SQL 生成；它们服务跨页面重复计算、大学渠道树 JSON 节点展开和已验证的来源遍历要求，不是逐图 JSON／HTML 结果表。业务关系和 Superset 数据集通过扁平 SQL 视图／表宏提供；`business.dimension_query` 在实际调用中接收期间、团队、主被动和维度参数，避免无关期间的维度聚合。模板只使用 Superset 已支持的 Jinja `where_in`。

旧 `facts/personnel_facts/contributions` 改为共用缓存上的视图；`team_periods/person_periods/selection_team_periods/capacity_people` 改为扁平指标视图；渠道、学校、年级、业务组改为参数化维度表宏，国家、活动、六维、平台、广告费用和日趋势改为 SQL 视图。`people/targets/personnel_history` 等必要固定内容进入 `config`。159 个数据集保持原 key、展示字段及筛选合同，实际关系清单封存在候选的 `relations` 与 `query_relations` 中。

存储层有以下明确变化，页面数据口径保持原值：

- 新 `business.facts` 保存全主被动 69,698 行，对应旧 `acquisition_facts`；原看板默认被动仍为 47,559 行，个人事实仍为 47,870 行。不得把新全量事实直接替换旧默认被动查询而省略筛选。
- 费用新增自然键和来源追溯字段，2,072 条巨量记录从既有已确认映射补全原为空的账户；金额、日期和业务归属不变。
- 金额计算内部使用 `DECIMAL`，最终 159 个数据集恢复旧展示类型、数值精度和字段；原 `50.0` 等文本／导出格式保留。

### 费用更新合同（此前候选说明）

小红书按账户＋日期；巨量按项目＋日期＋投放类型＋营销场景；腾讯按账户＋范围＋日期；SEM 按来源 sheet＋日期；期间费用按自身范围业务键。重复导入和更正覆盖同一业务键。只有来源明确声明完整窗口时才整窗替换，否则只更新确实提供的键，不能因部分文件缺行而删除旧费用。

费用更新独立事务。新业务构建可显式从上一封口候选只继承两张费用表，再尝试新费用。费用失败返回明确的 `status=failed`，保留原已提交费用，继续业务查询和通知编译。未建立任何费用基线时仍保持“未更新／未提供”。不增加费用护栏或推送冻结规则。

本地 SQL clone 已按用户要求在原两项业务日期后、金额单位前增加“费用截至 2026-11-04”，并单独核验只有这一处文案增量。正式适配须每批读取最后已提交的费用日期，不能固定本地 11 月 4 日；无费用基线时显示“费用未更新”。

### v11 历史差异与证据

旧基线固定为 `.local/sql-migration/page-fidelity/comparison/v10-final-20261107/legacy/capture.json`，来自实际旧 `business.duckdb`（SHA `9006f6a6237d4cfe38601835d0ed69e6c03cd32bd35792ec5df436ce474e0fd1`），不使用 `legacy-ui`。新全量记录为 `comparison/v11-final-20261107/sql/capture.json`；本节比较路径均相对 `.local/sql-migration/page-fidelity/`。所有原始失败与阶段回执保留，不改写为成功。

| 检查 | 结果与限制 |
|---|---|
| 分页 API 与导出 | 93 图／269 页有序字段、类型、值一致；186 份导出一致。首次浏览器数据 91/93 有序一致，332／333 只有并列行序变化，实体及值多重集相同 |
| 原始完整呈现比较 | `comparison/v11-final-20261107/strict-comparison.json`：placement 67/97 相符、30 有差异；section 27/43 相符、16 有差异。这是配色修复前的完整记录，不冒充修复后全量通过 |
| 共享配色修复 | 五个旧标签原色显式固定：同期现金／留学及小语种 `#454E7C`、本期现金 `#5AC189`、目标现金／语培 `#1FA8C9`。三项颜色的中间试验曾影响业务线颜色，已保留失败记录并由五项修复取代 |
| 修复后 13 图补验 | `comparison/v11-five-label-restored-20261107/sql/`：13/13 首发数据一致，13 项图例颜色一致，26 导出由完整 v11 哈希链复用；9/13 单图像素完全相同。285 尚有 2,228 像素、286 与 289 各 11 像素边缘、290 有 4,536 像素残差，未豁免 |
| 六分区补拍 | `sql-section-v2-corrected/final-presentation-difference-summary.json` 保留逐项差异；21/21 分区内图响应及加载状态核验通过，6/6 摄影帧稳定、缺图 0。六分区像素残差依次为总览 1,396、虚拟人 42,887、线上现金 44,052、线上日趋势 1,399、留预 31,448、大学 19,029，未豁免 |
| 大学渠道 | `diagnostics-v11-university-camera-20261107/university-camera-receipt.json`：349／350 自然视口补拍像素相同，全部层级展开、业务行 29／16 保留；不将旧 full-page 摄影状态失败改写为通过 |
| 日期与内部配置 | `diagnostics-v11-fee-preview-20261107/fee-date-preview-v11-receipt.json` 及 `diagnostics-v11-color-restoration-20261107/five-key-shared-label-color-receipt.json`；仅费用日期新增可见文案及原色固定，其他布局／筛选／权限等核验不变 |

HTML 表 327／272 的定向诊断中，可见文字、Range 位置、完整样式、字体等相符，但仍有光栅残差，未将其强行归因或用图片容差抹平。332／333 保留原按工单排序，不以静态行序或新次键掩盖旧端自身的不稳定。现有数据、组件、展开与导出覆盖证据完整；上述像素和并列行序限制仍需在上线验收中明确处理。最终综合差异清单为 `comparison/v11-five-label-restored-20261107/sql-section-v2-corrected/final-presentation-difference-summary.json`（SHA `02efdb42069904d861ee71175137e7f2618ecc8be0b3dc789fcee7069e2c95f5`），包含逐图／逐区列表与源文件哈希。

普通测试、字段及受控回查的完整回执在 `.local/sql-migration/final-candidate-v11/`。本轮保留 75,659 个 training source ordinal 和 3 份封存来源回执，它们只对应 2026-11-06 输入，不能复用于新批次。七张共用 SQL 缓存包含新大学 typed nodes 9,832 行，消除了 v10 全页流程曾实际触发的大学查询 OOM；最终结论仅覆盖本轮 v11 真实全量流程，不推定服务器已通过。

### v11 历史本地性能实测

建库对照均为两线程／512MB：旧版 225.23 秒、801,124,352 字节；v11 76.64 秒、134,230,016 字节。旧额外 Foundation 未计入，新版受控来源顺序回执的上游获取未计入。建库更快、仓库更小，但实际查询较旧物化结果更慢：

| 请求计时 | 旧中位数／P95 | v11 中位数／P95 |
|---|---:|---:|
| 浏览器首发数据请求，93 图 | 0.353／1.268 秒 | 1.066／4.259 秒 |
| 分页 API，269 页 | 0.088／0.825 秒 | 0.426／3.270 秒 |
| CSV，93 份 | 本轮未重测 | 0.978／5.322 秒 |
| XLSX，93 份 | 本轮未重测 | 0.637／3.681 秒 |

两端均一线程，旧库内存上限 2GB，新库 1100MB，资源不同；Superset 结果缓存关闭，但数据库／系统缓冲可能已热。这些是请求计时，不是页面可交互时间或 SLA。旧导出按已封存哈希复用，不伪造本轮时延。全量新流程 1,268 个 HTTP 状态均 200，无 OOM／Traceback／ERROR，详见 `comparison/v11-final-20261107/final-evidence-audit.json`。完整采集还包含翻页、下载和摄影，其总耗时不能充当页面加载时间。

### v11 历史本地复现入口

在该隔离工作树中使用既有 Python 运行时。复现 v11 冻结输入时显式传入 3 份来源顺序回执：

```sh
python -m dashboard_product.shadow_bi.sql_warehouse \
  --workspace .local/sql-migration/workspace \
  --output-dir .local/sql-migration/final-candidate-v11-reproduction \
  --batch-id run_sql_local_v11_20261106_reproduction \
  --training-snapshot snapshot_bi_operations_20261106_093634 \
  --abroad-snapshot snapshot_study_abroad_20261106_093634 \
  --as-of-date 2026-11-06 \
  --source-order-receipt "/Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/sql-migration/workspace/Output/ShadowBI/run_sql_legacy_full_local/_query/run_sql_legacy_full_local_training_0/data/query_results/evidence_0974c388feea4d7d8695b8b83cd0ddb8/receipt.json" \
  --source-order-receipt "/Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/sql-migration/workspace/Output/ShadowBI/run_sql_legacy_full_local/_query/run_sql_legacy_full_local_training_1/data/query_results/evidence_b00c9b6f310044e180dcd574a7fe9f99/receipt.json" \
  --source-order-receipt "/Users/akechi/Desktop/manager -CowH/.local/archive/business-sql-local-20261111/sql-migration/workspace/Output/ShadowBI/run_sql_legacy_full_local/_query/run_sql_legacy_full_local_training_2/data/query_results/evidence_6048b95007034f8899a53204c484f79d/receipt.json"
```

三条路径来自 `.local/sql-migration/precision-scratch/school-existing-cache-final-result.json` 的 `lineage.source_order_receipts`。它们只对应当前冻结的 2026-11-06 输入，用于复现同一批次；不得挪用到新业务批次。服务器运行时须从切换当批受控查询重新取得并绑定 current-batch source-order lineage receipts。每次本地复现使用新的输出目录和批次，不覆盖封口候选。`--expense-baseline` 和 `--advertising-manifest` 仍按显式输入设置；命令没有部署、发布或发送选项。`notification-preview.json` 仅为本地编译预览。


普通回归不依赖客户 `.local` 数据。目录级真实库集成测试须同时显式设置 `SHADOW_BI_CATALOG_WAREHOUSE` 和 `SHADOW_BI_CATALOG_LEGACY_WAREHOUSE`：未配置时明确跳过，若只给一项或路径不存在则失败。FY27 市场总盘目标另有不含客户明细的内存回归。

受控查询使用 `data_platform.sql_candidate.query_candidate`，核验批次和库 SHA，只允许登记的 business 关系及维度宏，不允许外部文件读取、系统函数或写入。查询限行、限字节并留下显式回执；原 Snapshot 查询合同不变。

### v11 阶段服务器切换清单（历史，不代表当前执行计划）

以下是尚未实施的服务器接线事项。v11 本地数据与导出已核对；呈现差异已列明，不能宣称逐页像素完全通过。本清单不是施工授权。源码入口已只读定位，完整文件／函数及依赖见 `.local/sql-migration/server-cutover-owners.json`：

| 环节 | 现有 owner | 切换时替换的依赖 |
|---|---|---|
| 入库与激活 | `p4/rebuild.py`、`p4/activate.py` | 39 份 JSONL、旧 `business.duckdb` 和激活验版查询；改为单仓及显式批次／Snapshot 身份门禁 |
| 看板数据与日期 | `p3/bootstrap.py`、`p35/bootstrap_native.py`、`p4/refresh_header.py` | 旧 `queries.*` 数据集、动态筛选来源和旧 manifest 页头；接到平面 SQL 视图与日期摘要 |
| 版本与门禁 | `p4/extension.py`、`p5/raw_publish.py` | `queries.batch`、39 表数量及旧 library 摘要；替换为新仓身份、关系与核对回执 |
| 通知与去重 | `monitoring_product/server_notify.py`、`release_notifications.py`、`shared_delivery.py` | producer 改读 SQL 预览；继承原 DeliveryState，不重发既有通知 |
| 受控查询／MCP | `business_data_mcp/query.py` | 双 Foundation resolver 与旧表 allowlist；接到同仓公开基础明细及显式 Snapshot 对 |

表中 `p3/p35/p4/p5` 路径均位于 `dashboard_product/shadow_bi/`。本工作树对 `p35/bootstrap_native.py` 的纯 `coverage_note` 提取是本地源码调整，不代表服务器已接线。

1. 等 bi-3 当前批次结束，核验切换时服务器版本、运行时、内存及任务状态；本地旧版元数据不能替代切换时核验。
2. 为切换当次显式 Snapshot 重新取得并绑定 current-batch source-order lineage receipts。本文复现命令中的三份 receipt 仅对应 2026-11-06 冻结输入，不得挪用到新批次。固定配置、人员历史及 Bridge 映射应随新仓封存，并解除服务器日更入口对 FY26 参考工作簿和旧工作区路径的依赖；不能先复制本地 CLI 再删除来源。
3. 保留 Superset 原对象和数据集 ID、93 张图、97 个放置位置、86 个筛选、权限、CSS 及导出设置，固定已核验的五项原共享标签颜色，改用新 `warehouse.duckdb` 和本轮审定的 159 个 SQL 数据集。首次切换及后续每次新批次激活，都须清除旧查询结果缓存并 dispose 旧数据库连接／engine，确保看板、受控查询／MCP 与日期读取同一显式批次；同批 shadow 验证 API 行值／类型／顺序、筛选翻页、CSV、XLSX、DOM 和截图像素。
4. 将业务查询／MCP 入口改为同仓公开基础明细别名与显式 Snapshot 身份，逐条保持旧默认主被动范围，避免以全量 `business.facts` 扩大旧默认被动范围；再解除对旧 `foundation/Work/...` 和 `library/business.duckdb` 的依赖。消费者未切换前不能删除旧基础库。
5. 日更以 SQL 建仓，业务成功即可发布和推送；费用刷新单独提交，失败时沿用已提交费用和原日期并记录失败。继承原 `DeliveryState`，不得重发既有通知；bi-3 来源采集、日程和业务不受切换影响。
6. 只有同批 shadow 全页 API、导出、DOM 和像素验收通过后才原子切换 `current`。正式服务器最终保留一份分析仓库，以及必要运行时、元数据、固定配置、密钥、DeliveryState 和限量日志；旧双基础库、39 表业务库、JSONL、临时文件和旧发布目录仅在依赖核销后移除。

最终呈现保留原布局、字段、筛选、图表、分页、展开层级和导出；仅新增已授权的费用日期。原并列排序及尚存像素差异如上，不自动视为通过。具体本地配置增量封存在 `.local/sql-migration/review/dashboard-presentation-delta.json`；源码差异包与清单同目录。服务器 wiring 与上线均待用户审阅并确认；当前未接线、未切换 `current`。服务器最终一份数仓加看板，原件与正式证据留本地；必要运行元数据、密钥、投递去重状态和限量日志不属于重复数仓。
