# 影子 BI P0：旧版基线与覆盖清单

日期：2026-10-22。阶段状态：**总线程复验通过**。施工线程：`01a162c4-c0c8-7760-a5b5-434e61288606`；总验收线程：`01a162a1-6544-79d2-a38f-2ddbf5aeff3e`。

本阶段只冻结本地旧版工作内容、输入、同批构建及验收清单。没有安装 Superset、制作新版页面、部署服务器、变更调度或发送钉钉。旧构建固有的 `notifications.json` 为本地预览，未调用发送入口。本地 HTTP 检查仅绑定 `127.0.0.1`，检查后已停止。

## 1. 基线身份

施工位置为 `/Users/akechi/.codex/worktrees/c373/manager -CowH`，分支 `codex/shadow-bi-plan-20261022`。工作开始已有修改：`DEVELOPMENT.md`、`SYNC.md`、管理看板 README、`flat-tables.js`、Snapshot 导入器及其测试，以及五份未跟踪方案文档。本阶段没有覆盖、提交这些修改；仅更新本阶段记录和阶段表。

代码基线是**本工作树实际工作内容，包括原有未提交变化**，不是 HEAD 的干净版本，也不是已证实的线上部署版。HEAD、初始状态和差异分别保存在 `freeze.json`、`initial-status.txt`、`initial-working.patch`。可执行副本位于私有证据 `code/`，必要目标、花名册及已确认映射也按实际内容冻结；所有文件有 SHA256。业务算法没有为对账修改。

证据根目录：`../.local/audits/shadow-bi-p0-20261022/`。客户输入及详细结果只保留在该私有目录，不进入文档正文或公开目录。

| 输入 | 固定版本与实际覆盖 | 取用方式 |
|---|---|---|
| BI | `snapshot_bi_operations_20261022_full_reexport`；工单60,438行，2025-03-01—2026-10-21；现金70,836行，2024-06-01—2026-10-21 | 从现有影子工作区显式指针复制数据库、manifest及两份Snapshot冻结原件；不重导BI |
| 留学 | `snapshot_study_abroad_20261013_local_103935`；指针截至2026-10-13；构建事实覆盖2026-06-01—2026-10-13 | 从原本机工作区 `Work/StudyAbroad/current.json` 定位，只复制当前run明确引用的原件、规范表、冻结花名册、lineage、数据库及所需父Snapshot和查询证据 |
| Pack / Bridge | Pack 1.0.0 / Bridge 1.7.0 | 影子工作区已确认语义副本；构建向导状态须为 analyze |
| 留学渠道参考 | `Input/Reference/留学-FY26-资源表.xlsx` | 明确文件副本，内容摘要绑定 |
| 官方记分卡 | 同目录 Markdown / JSON | 业务确认范围优先；旧构建仅作为历史对照，未入仓、未写目标 |
| 费用 | `Input/AdvertisingCosts/sources.json` 声明的8份输入，含9月差额声明 | 原样复制清单和明确文件；具体周期、平台、业务组见 `cost-coverage.json`；未提供费用不补0，期间费用不摊日 |
| 人员历史 | `Input/Reference/人员产能/留学人员历史产能.xlsx` | 原样复制；6—8月确认合计保留，未伪造状态或自创拆分 |
| 目标、人员、归属例外 | 原有 `dashboard_product/**/config/` 和 `workspace_modeling/operations/people.json` | 随代码冻结；不重新猜测或分摊目标 |

留学本次未重抓，不能称两仓都截至10月21日。批次固定的是两套明确版本与规则/费用/目标，不是强行裁成统一截止日；共同可比分析另沿旧版窗口。

此前全量重导相对旧仓的同截10月12日差异仍为工单+482、现金−12，证据在 `../.local/audits/shadow-bi-full-reexport-20261022/`。P0不重复导出，也没有把行数变化归因于历史改造。

## 2. 可审查清单

| 文件（均在证据根目录） | 内容 |
|---|---|
| `feature-coverage.csv` | 181项功能；逐项记录旧代码行、旧页面、新版拟放位置、数据字段、筛选作用域、默认值、不受影响项、验证样例及状态 |
| `filter-scopes.csv` | 22项控件作用域；期间、团队、业务组、人员、月模式、四状态、产品范围、搜索、排序、展开等 |
| `business-rules.csv` | 16组业务规则；实现依据、优先级和历史例外 |
| `data-field-catalog.csv` | 完整共同结果及线上投影的7,107个字段路径/类型统计，辅助检查清单遗漏；实际值以同批JSON为准 |
| `static-control-catalog.json` | 原HTML中的控件清单；动态生成控件另由功能与作用域表覆盖 |
| `page-baselines.json` | 七个页面入口对应的静态页/数据、17个经营期间、7个预备高中非空选择及产能月份 |

这些状态代表“旧源码已定位、旧基准已生成”，**不代表新版功能已实现或通过**。P1/P3继续沿每项检查。尤其保留：活动本次页面即时投入且搜索翻页后不丢、独立个人月份/产能自然月/年度六维、市场团队只作用目标区、现金特殊分母、高中个人留学本人分母、线上条线国家层级、目标差额与时间差额、人员资格和历史汇总例外。

旧线上业务组表实际显示目标与目标差额；完成率和时间差额存在于业务组工单数据，但该表未显示两列。清单保留方案要求，不能把“数据已带出”说成“旧页面已显示”。旧卡片确实显示完成率、目标差额和时间差额。P1须按已确认方案验证所需展示。

## 3. 同批旧逻辑构建

工作目录为证据根目录下 `code/`，实际成功命令：

```bash
python3 -m dashboard_product.management.build \
  --workspace '/Users/akechi/.codex/worktrees/c373/manager -CowH/.local/audits/shadow-bi-p0-20261022/workspace' \
  --snapshot-id snapshot_bi_operations_20261022_full_reexport \
  --study-abroad-snapshot-id snapshot_study_abroad_20261013_local_103935 \
  --run-id run_shadow_p0_20261022 --as-of-date 2026-10-22
```

构建退出0，输出在 `workspace/Output/DashboardManagement/run_shadow_p0_20261022/`。四份自包含HTML及 `site/` 已生成（线上页嵌入数据，原投影还在 `packages/online/data.json`），七个导航页面都有同批数据。`shared_result.json`、`online_shared_result.json`、`details.json`、人员产能/活动与 `_query/` 一并保留。留学查询在独立副本的 `Output/StudyAbroad/`，也已纳入完整产物摘要。

`execution-receipt.json` 保存命令、工作目录、退出状态；`build-retry2.log` 是成功回执。最初冻结副本漏了 `pyproject.toml`，前两次失败日志原样保留，补齐项目元数据后成功，未调整算法。首次已有测试运行缺两份测试辅助文件，补齐后通过；这属于冻结依赖收集修正。

`code/` 是后续同输入对账应读取的封存版本，不得随P1/P2工作变化；变更规则使用新的副本和批次，不覆盖此基线。Python及依赖版本见 `runtime-versions.json`；文件内容、原位置及副本位置见 `freeze.json`。

## 4. 已做验证与边界

- 冻结代码运行既有管理看板回归：`python3 -m unittest discover -s dashboard_product/management/tests`，**162项通过**，最终见 `tests-final.log`（TMPDIR显式限定在证据目录）。
- `verify.py` 检查输入及副本摘要未变、三份Snapshot的完整manifest引用、历史记录封存摘要、四页/数据非空、事实ID唯一、四状态视图齐全、7个业务组预计算选择、双仓截止日及原日志身份；当前结果只写 `verification-check.json`。`baseline-verification.json` 是首轮历史检查，不再改写。
- 旧构建自带同数据V14对照：**80项 matched，2项 not_comparable**。后两项是Q1线上/线下留学与官方历史覆盖不同的对照，不能当成漏单或对账通过。此对照不等于外部观远页面已核对通过。
- 经Chrome实读七个本地入口。市场团队切到线上，顶部全文不变而目标区变化；活动现金11,883.3填投入1,000即时显示11.88×，翻到第二页再返回、按活动名称搜索后仍保留1,000；高中渠道页可见马玥本人渠道。默认状态及页面信息见 `ui-checks.json`。
- 没有遍历全部有限交互组合或进行新版验收；本阶段提供其完整基线。暂按方案的5人并发、15分钟、筛选p95≤3秒和首屏≤5秒作为后续试用目标，本阶段未检查服务器资源或测量性能，不把目标写成实测结果。

## 5. 外部页面核对结果与待解决项

两个指定观远入口均通过已登录Chrome实际访问，没有登录阻塞，未获取凭据。可见值及本地受控查询按渠道拆解保存在 `online-reference-review.json`。

| 核对项 | 观远可见值 | 本地同窗旧逻辑 | 当前结论 |
|---|---:|---:|---|
| 工单看板，被动小计，当期2026-06-01—10-21 | 8,639 | normalized training.orders = 8,639；顶部 market_orders = 8,799 | 规范化值相同，顶部差160；不能互换指标或宣称全部通过 |
| 同期上年同窗 | 9,465 | normalized training.orders = 9,485；顶部 market_orders = 9,488 | 分别差20与23，保留差异，尚未逐ID核对 |
| 【留学预备】综合看板 | 团队为初中/初中国际学科/青少；可见日期10-01—10-21，显示净现金、净人头、报名现金/人头及单笔 | 本项目市场现金为被动新生正向报入；工单另有团队边界 | 可见区域口径不等同，不作通过依据；如需用于工单校验，须定位对应工单卡片和公式 |

工单页面另提示签约日期不随分配日期动态联动，默认截止昨日，同期对齐去年今日；不得把签约指标与分配工单当成同一日期窗口。P0只封存可见状态和本地查询，不推断观远隐藏过滤、去重和人员边界，也不为消除差额改旧逻辑。

待总线程判定的后续问题：外部参考与顶部总盘的160/23差异及规范化同期20差异；留学晚于10月13日的更新需要另列腾讯范围；业务组数据中已有而旧表未显示的完成率/时间差额按方案验证。当前没有缺失输入导致整页无法构建，来源覆盖不足已保留状态，未补造事实。

## 6. 总验收入口

依次读取 `freeze.json` / `integrity-after.json`、`execution-receipt.json`、完整输出与受控查询、三份CSV清单、`verification-check.json`、历史 `baseline-verification.json`、`ui-checks.json` 和 `online-reference-review.json`。可从工作树显式运行 `python3 .local/audits/shadow-bi-p0-20261022/verify.py` 复核摘要与结构。`output-manifest.json` 绑定所有本次工作区Output产物；源码和输入另由 `freeze.json` 绑定。

本线程到P0结束。阶段表为“待总线程验收”；不自动进入P1、不建立其他施工线程、不向其他线程主动发消息。


## 7. P0 首次验收返修（2026-10-22）

总线程首次验收指出Snapshot引用闭包缺件和验证脚本改写历史证据两项缺口。本次只修正证据完整性，没有重导、重建业务结果、改变算法或进入P1。

1. 按原 `freeze.json` 内三份manifest的**原位置**定位13个缺件：BI两份landing及一份quality parquet；两个留学Snapshot各三份landing、一份quality parquet及一份规范源工作簿。原件全部可用，大小与SHA256均匹配原manifest，复制到对应副本后再次核验。冻结文件从211增至224，三份manifest共18个artifact全部闭合，原manifest字节不变。修复明细见 `closure-repair.json`。总线程的 `parent-manifest-gaps.json` 原样保留，仍是首轮缺件记录，不被清空。
2. `verify.py` 不再重写 `ui-checks.json`、`execution-receipt.json`、`runtime-versions.json`，也不再重写首轮检查、状态视图清单或费用覆盖记录。它只读现有证据，核对首轮构建日志中的built及批次身份、原测试日志的162项和OK，并写自身 `verification-check.json`；失败时写failed并退出1。日志一致性是对原记录的核查，不代表重新构建或重新测试。
3. 上述历史文件及原日志共15份已按返修前**原有字节**封存在 `historical-evidence-manifest.json`；`freeze-initial.json`、`verify-initial.py` 保留返修前清单与脚本。由于旧验证器以前会改写运行时文件，不能补称现存 `runtime-versions.json` 一定就是第一次写入的版本；初始Python路径与duckdb/openpyxl版本仍以原 `freeze-initial.json` 为依据。本次未重新采集运行时或改动已有观察值。
4. 当前验证完整遍历 `shared_result`，包括 `prep_high_selections`，共2,747个四状态对象；首轮1,659计数未包含这些选择视图，保留其历史值，不是数据被重建。44,620事实唯一、142份Output摘要、224份来源及副本摘要核对通过。
5. 连续执行两次验证脚本，15份历史记录摘要均未变；独立临时夹具验证“缺件”和“等大小但摘要变化”均被拒绝，未触碰冻结Snapshot。命令和结果见 `repair-validation.json`。本次未重跑业务测试；总线程已独立用 `python3 -m pytest dashboard_product/management/tests -q -p no:cacheprovider` 验证 **172 tests、69 subtests通过**，记录为 `parent-acceptance-checks.json`。该pytest覆盖比首轮unittest162更多，两者分别保留，不替换成一次施工执行记录。

当前仍为**待总线程验收**。观远160/23/20差异继续open；P0复验仅确认可复用基线及证据完整性，不代表外部业务对账通过。留学仍截至10月13日，性能与全部有限交互组合尚待后续阶段验证。

总线程于2026-10-22独立复验通过，详见阶段验收记录及 `parent-reacceptance.json`；以上施工时点的待验收表述保留为过程记录。
