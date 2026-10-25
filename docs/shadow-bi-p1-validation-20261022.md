# 影子 BI P1：完整 Superset 与代表交互验证

日期：2026-10-22。施工线程：`01a162e1-579f-7302-b701-0eff8180a661`。状态：**已完成施工，待总线程验收**。总验收线程：`01a162a1-6544-79d2-a38f-2ddbf5aeff3e`。

## 结论

完整 Superset 6.1.0 + DuckDB 已在独立本地环境运行，原生看板实际取数与浏览器操作通过；这次不是驱动测试或静态模拟。所测代表样例没有选型阻塞，建议总线程复验后进入 P2。**活动临时投入需要一个小组件**，其余所测交互使用 Superset 原生能力及冻结投影。未启动 P2，未全量迁移页面，未部署服务器、启用调度或发送消息。

施工限定在 `/Users/akechi/.codex/worktrees/c373/manager -CowH`、分支 `codex/shadow-bi-plan-20261022`。原有6份已修改源码/文档及方案文件保留，没有在 Desktop 原目录/main 施工，没有提交。P0 code、workspace和冻结记录均只读使用；施工前后392份封存文件SHA相同（其中来源/源码冻结224份、Output142份，其余为既有证据）。

## 实际环境与运行

| 项目 | 实测固定值 |
|---|---|
| Python | 3.11.15；P1独立venv，解释器来自本机已有uv管理版本，未修改项目/生产venv |
| Superset / core | 6.1.0 / 0.1.0 |
| SQLAlchemy / duckdb-engine / DuckDB | 1.4.54 / 0.17.0 / 1.5.5 |
| Flask / Flask-Caching / cachelib | 3.1.3 / 2.3.1 / 0.13.0 |
| CLI/驱动发现补充依赖 | rich14.2.0、cachetools6.2.1 |
| 完整依赖 | `dashboard_product/shadow_bi/requirements-p1.lock`，154包；`uv pip check`退出0 |
| 入口 | `http://127.0.0.1:18088/superset/dashboard/shadow-bi-p1/`；`/p1/activity/`为投入组件 |
| 服务/缓存/元数据库 | P1专用loopback Flask开发服务、SimpleCache、SQLite元数据库；均属本地实验，不能据此宣称生产部署通过 |
| 私有路径 | `.local/audits/shadow-bi-p1-20261022/`；账号/密钥只在runtime私有文件，未写入文档、日志或Git |

源码与启动/从空环境复现命令见 [P1源码说明](../dashboard_product/shadow_bi/README.md)。实际服务命令为：

```bash
export SUPERSET_CONFIG_PATH="$PWD/dashboard_product/shadow_bi/superset_config.py"
export SUPERSET_HOME="$PWD/.local/audits/shadow-bi-p1-20261022/runtime/home"
export FLASK_APP=superset
.local/audits/shadow-bi-p1-20261022/runtime/venv/bin/superset run --host 127.0.0.1 -p 18088 --with-threads
```

完成时保留该loopback服务供总线程复验；停止用该前台进程的Ctrl+C，不操作其他服务。`health`实测为200/OK。版本、监听信息、执行退出状态见私有 `runtime-versions.json`、`listener.txt`、`execution-receipts.json`。元数据库不作为未来服务器应用备份/恢复方案。

官方安装说明建议兼容Python及独立venv，故没有沿项目Python3.12直接安装。[Superset安装说明](https://superset.apache.org/user-docs/6.0.0/installation/pypi/)。实际PyPI依赖解析出现三项缺口：CLI缺rich、默认Flask-Caching2.5.1的签名与Superset不兼容、驱动发现缺cachetools。保留原失败日志，缓存组合按[6.1.0官方依赖锁](https://github.com/apache/superset/blob/6.1.0/requirements/base.txt)固定；没有修改上游Superset代码。

## 数据与范围

仅从P0的 `shared_result.json`、`details.json`建立P1独立只读投影：44,620条冻结事实、5,049条活动、17条期间总盘、204条团队目标/特殊分母、2,208条个人月份/月模式/状态视图、12条单人年度六维记录。输入SHA及表行数见 `projection.json`。没有打开客户原始DuckDB，没有重导BI、重抓腾讯或覆盖任何Snapshot。

个人筛选选择的是P0已计算结果；两个状态列只是把原四态编码拆成两个原生控件。业务规则重新组织/按事实重算属于P2，本阶段没有另写规则引擎。学校去重在代表事实投影上由Superset生成 `COUNT(DISTINCT 学员ID)`，只证明所测维度的正确聚合能力，不把全历史技术样例当新的正式业务指标。

BI原始输入仍为工单60,438、现金70,836，截至10月21日；留学截至10月13日。观远160/23/20差异继续open，未调整算法消除差额，未声称外部对账通过。

## 逐项实际验证

| 顺序与功能 | 分类/实测结果 | 主要证据（均在私有evidence目录） |
|---|---|---|
| 1 最小语培工单/现金页 | **原生通过**。Superset登录、完整前后端、DuckDB数据源实际运行；FY27显示工单8,639、现金17,858,997.4及日期2026-10-21，回查P0相同值 | `bootstrap.json`、`p1-dashboard-initial.txt/png`、`api-final/api-01-top.json` |
| 中文、日期、金额 | **原生通过**。中文列反射、DATE、DECIMAL(20,6)/(20,2)查询与浏览器显示；日期谓词与金额聚合实际下推DuckDB | `projection-build.log`、`api-final/api-15-date-amount.json`、原生明细页面 |
| 2 活动搜索/分页 | **原生通过**。5,049项实际服务端分页，第二页LIMIT10 OFFSET10，只回10行，计数接口只回1个计数；原生搜索为前缀匹配 | `p1-native-page2.txt`、`chart-requests.jsonl`、`api-final/api-02/03*` |
| 活动临时投入、即时倍数、搜索/翻页保留 | **需最小组件，已实测通过**。现金11,883.3填投入1,000显示11.88×，到第二页返回与关键词搜索均保留。投入只在本标签页sessionStorage，不发到服务器；组件关键词采用包含匹配。没有持久化写回接口、服务或数据库补丁 | `p1-activity-input.txt`、`p1-activity-page2.txt`、`p1-activity-search.txt/png`、组件真实查询日志 |
| 3 团队只影响目标区、特殊分母固定 | **原生通过**。团队all→online只刷新目标图；大学分子7,392,250.3→2,269,184.3，分母始终12,777,455.1；顶部/活动/个人不广播 | `p1-team-online.txt`、`api-final/api-06/07*`、实际native请求 |
| 部门期间、活动累计与独立个人月份 | **原生通过**。部门FY27→2026-09仅作用总盘和目标；活动累计仍5,049项，个人仍10月；个人再改9月单独作用个人图。年度六维也不随部门月变化 | `p1-period-september.txt`、`p1-person-september.txt`、`native-final-config.json` |
| 绩效月/自然月 | **原生通过**。10月刘彬绩效窗9/26起、自然月10/1起；工单20.833333333333332→17.833333333333332，显示原精度，未先舍入 | `p1-person-calendar.txt`、`api-final/api-08*` |
| 两个独立状态控件与固定指标 | **原生通过**。默认不含删除回收(0)、含死单(1)；7月四态工单00=6、01=13、10=7、11=14，与P0四态逐一相等；现金/人数/目标保持不变。浏览器独立切两个控件留证 | `p1-final-state01/00/10.txt`、`api-final/api-16*`及最终summary |
| 4 学校→年级层级 | **原生通过**。父级学校表右键Drill by→年级，弹窗面包屑学校(天津大学)/年级，实际查询带学校过滤；也验证学校×年级平表 | `p1-school-grade-drill.txt/png`、native slice0请求、`api-final/api-09/10*` |
| 升降序、缺失值后置 | **原生通过**。表头点击在SQL中切换ORDER BY学校ASC/DESC；学校第93页LIMIT10 OFFSET920返回8项，NULL/N/A最后。API对两种方向均核对NULL最后 | `p1-school-asc/desc/null-last.txt`、native请求、`api-final/api-12*` |
| 独立人数 | **原生通过**。全历史语培现金投影去重6,445人，而学校×年级分组人头相加6,485，未用分组相加冒充独立总人数 | `api-final/api-10/11*`、最终summary；此为技术样例窗口 |
| 必需明细下钻与分页 | **原生通过**。Drill to detail by天津大学得到365条现金记录，每页50，第二页SQL LIMIT50 OFFSET50，只返回50行；下钻字段来自既有明细投影 | `p1-drill-school/page2.txt`、`/datasource/samples`原请求与SQL |
| 5 年度六维与同组均值 | **原生通过**。Radar实际渲染6轴、本人/同组均值两组。各轴按P0原scale归一，原值/上限/年度/截止日另在原生表展示，没有重新定义指标或把混合单位直接同轴 | `p1-radar.png`、`api-final/api-14-radar.json`、P0来源SHA |

原生Table没有用户临时编辑单元格及会话输入计算机制，不能把它记为原生通过。补充组件目前为同源独立实验页，可返回原生页；它验证投入交互，未制作完整市场活动产品页。P3须把完整活动字段、缺失/partial状态与这一输入能力合在最终页面中。

## 发现的限制及处置

1. Superset全页图表cross-filter会把学校等过滤广播到其他区域，与业务作用域冲突；实际试验出现了该行为，最终配置关闭 `cross_filters_enabled`，保留显式排除图表的native filter。旧试验请求保留，未从证据中抹去；最终作用域由验证脚本逐控件检查。
2. 原生Table的服务端分页在本版本标为experimental。实际LIMIT/OFFSET及下钻均通过，不等于所有图表和全部组合通过。辅助“必需字段明细”样例仍保留10,000行上限并显示警告；它不是完整明细导出入口，不能据此认定全历史明细已完整迁移。按学校下钻365条的样例没有截断。P3应按真实消费者配置完整计数/必要上限及可见提示。
3. `read_only=True`实际拒绝CREATE TABLE，但同一Superset连接仍能读取它可见的合成CSV，见 `connector-boundary.json`。没有读取同机其他业务文件。P4必须通过最小挂载/文件权限限制非业务文件，并另验网络能力；应用角色权限不能替代此项。
4. 本地使用管理员实验账号；没有验证生产普通账号/行列权限、5人并发15分钟、缓存p95/首屏SLA、服务器容量、重启/换版/恢复。SQLite、SimpleCache、Flask开发服务不作为这些验收的依据。
5. 初轮19次API回归通过；增加双开关后，一次测试错误假设10月四态数值应全部不同而失败。10月没有对应删除回收变化，00=10、01=11是P0事实；改用7月真实样例并逐态比对P0，最终23次通过。失败日志与响应单独保留，业务值未修改。

## 总线程复验入口

- 先读 `evidence/execution-receipts.json`、`runtime-versions.json`、`projection.json`、`dependency-check.log`。
- `verify_api.py`实际向运行服务查询，当前最终23请求通过；结果在 `evidence/api-final/`。回归只涉及P1新模块，没有改核心算法，不以全项目重写/全套重复测试代替本阶段验证。
- `verify_evidence.py`核对保存的真实native请求、活动输入观察、层级/明细分页和P0摘要，结果在 `verification.json`。它不会创建UI、构建或命令成功记录。
- 查看真实浏览器截图/DOM及 `chart-requests.jsonl`，封存副本为 `chart-requests-captured.jsonl`；`chart-requests.jsonl`和`server-restart.log`随服务继续追加，不纳入不可变摘要。核对分页查询LIMIT/OFFSET、返回行数和仅计数的子请求。没有整表拉入前端冒充服务端分页。
- P0摘要由 `p0-before.json` 与 `p0-integrity-after.json`核对。P0历史验证器未运行，P0文件未覆盖。
- 源码静态检查、JavaScript语法和Git空白检查见 `source-checks.log`、`diff-check.log`；内容摘要见 `source-manifest.json`、`evidence-manifest.json`（不包含runtime凭据）。

建议：P1代表样例满足进入P2的技术条件，但阶段状态保留为**待总线程验收**；由总线程独立复验后决定是否创建P2。P2继续沿已确认范围整理业务规则与可重建查询库，不能将本实验投影当成该阶段已完成。
