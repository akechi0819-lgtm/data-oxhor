# 影子 BI P2：业务规则与可重建查询库

日期：2026-10-22。施工线程：`01a162fc-6cc5-7270-9ac2-e199d21c43d3`。状态：**已完成施工，待总线程独立验收**。只在 `/Users/akechi/.codex/worktrees/c373/manager -CowH`、分支 `codex/shadow-bi-plan-20261022` 施工，未提交。未启动P3。

## 实际交付

从P0同批源输入经现有受控入口重算，建立30张业务关系；不是读取P0页面JSON建立投影。`management/calculation.py`集中现有编排，继续调用已验证的事实、人员、留学、费用函数及SQL；旧 `management/build.py`改为计算后打包页面，原重复编排已移除。没有新规则引擎、通用指标平台或客户DuckDB直连程序。

最终批次：`run_shadow_p2_20261022_final4`。库：`.local/audits/shadow-bi-p2-20261022/workspace/Output/ShadowBI/run_shadow_p2_20261022_final4/library/business.duckdb`（364,392,448字节）。同目录 `library_manifest.json`绑定56份源输入/明确历史证据、95份源码/SQL/配置文件、两仓身份、实际覆盖和19份源查询回执。输入/规则在计算前后和封口时核对。表粒度和受控回执见[查询合同](../shadow-bi-p2-query-contract.md)，业务优先级及消费者见[规则清单](shadow-bi-p2-rules-20261022.md)，从空目录重建见[源码说明](../../dashboard_product/shadow_bi/README-P2.md)。没有安装新依赖；Python3.12、DuckDB1.5.5、openpyxl3.1.5沿用现有环境。

| 主要表/消费者 | 本批实际行数 |
|---|---:|
| 规范事实（完整fact_id与原始来源/状态/身份域） | 44,620 |
| 原精度人员贡献 | 3,956 |
| 语培受控源查询结果 / 工单受控源查询结果 | 45,576 / 59,954 |
| 总盘独立工单范围 / 特殊分母输入 | 27,106 / 404 |
| 累计活动 | 5,049 |
| 期间 / 期间×管理单元 | 17 / 102 |
| 个人×期间×管理单元×月模式×状态 | 6,256 |
| 业务组选择×期间 | 119（7×17） |
| 产能个人状态视图 / 年度六维轴 | 380 / 138 |
| 线上业务线 / 日明细 / 平台 / 业务组 | 34 / 429 / 205 / 51 |
| 费用原粒度行 / 覆盖来源 / 同窗费用结果 | 676 / 32 / 1,464 |
| 人员 / 学校 / 渠道 / 日历 | 23 / 2,249 / 22 / 873 |

全部30表的行数与字段类型在manifest中。原始BI Snapshot仍为60,438工单、70,836现金，以上“受控源查询结果”沿原SQL业务范围，不冒称完整landing行数；没有10000行截断或默默截断结果。`facts`保留完整事实及来源回查，工单和现金分粒度保存；`market_orders`与normalized training指标不能互换。贡献Decimal权重/源值/credited值保存原文本精度，最终展示沿原规则处理。费用和历史来源的路径规范为工作区相对路径，摘要不变。

官方记分卡只绑定外部文件摘要，不导入业务表、不补齐事实、不自动回写目标。数仓计算不能覆盖官方已确认范围；原两项Q1留学对照继续为 `not_comparable`。

## 实际构建与核对

以下命令的工作目录均为指定工作树，完整argv、开始/结束、真实退出码见私有 `execution-receipts.jsonl`；日志另存，不由验证程序生成“构建成功”。

```bash
python3 -B -m dashboard_product.shadow_bi.library build \
  --workspace .local/audits/shadow-bi-p2-20261022/workspace \
  --snapshot-id snapshot_bi_operations_20261022_full_reexport \
  --study-abroad-snapshot-id snapshot_study_abroad_20261013_local_103935 \
  --run-id run_shadow_p2_20261022_final4 --as-of-date 2026-10-22

python3 -B -m dashboard_product.shadow_bi.verify_library \
  --library .local/audits/shadow-bi-p2-20261022/workspace/Output/ShadowBI/run_shadow_p2_20261022_final4/library \
  --batch-id run_shadow_p2_20261022_final4 \
  --p0 .local/audits/shadow-bi-p0-20261022 \
  --evidence .local/audits/shadow-bi-p2-20261022/verification-final4
```

构建真实退出0。验收辅助程序仅通过Data Platform读取派生库：**203次受控查询、85项匹配检查通过**。完整SQL、参数、分页结果和回执位于 `verification-final4/queries`，结果见 `verification-final4/verification.json`。这属于施工自检，不代替总线程验收。

核对包括：44,620个事实的唯一身份集合及全部字段、逐日/团队/业务组金额与学员身份域、逐工单不跨线重复、3,956条原精度贡献、待核/跨线marker诊断、全部活动累计、17期间×6管理单元（嵌套包含所有既有个人双月模式/四状态、学校/渠道/年级/国家/固定分母/团队作用域）、7业务组选择×17期间、全部产能与年度六维、全部线上期间/平台/费用共同窗口及历史汇总。事实集合比较保留重复信息，不把SQL物理返回顺序当业务定义。没有为匹配外部页面改口径。

从新的 `rebuild4/workspace`只复制源Work/Input及历史查询证据目录，再用不同run-id `run_shadow_p2_20261022_rebuild4`重算；未复制旧看板输出、P2第一次计算结果或查询缓存。两次输入与规则摘要相同，30张表的行数及完整逻辑内容由 `verify_rebuild.py`通过344次受控分页查询读回核对；结果见 `rebuild-verification4/verification.json`，真实命令见 `copy-rebuild-r4.log`、`build-rebuild-r4.log`、`verify-rebuild-r4.log`。库二进制和批次/时间信息不要求相同，业务行集合及重复次数必须相同。

最终影响范围回归：**188项测试、108项子测试通过**，日志 `final-tests.log`。其中管理既有规则172项/69子测试，派生查询及原查询门禁16项/39子测试；覆盖只读/外部读取/系统schema/多语句拒绝、身份、限额、分页金额、证据篡改、嵌套完整行及未舍入贡献。最终测试TMPDIR显式在P2目录。另在P2输入副本运行旧 `management.build`，退出0并生成旧式页面包/共同JSON，见 `old-build-smoke.log`；这是本地打包冒烟，没有发布或浏览器产品验收。

## 保留边界与失败记录

- BI截至10月21日，留学仍截至10月13日。活动沿各来源有效累计；跨源比较/比例沿原共同窗口；没有为了“同批”裁掉较新有效记录。
- 观远160/23/20差额继续 **open**。同批算法一致不等于外部观远业务对账通过。P0官方两项非同口径对照不升级为matched。
- `pending_contributions`为0，但仍有49条未匹配跨线marker诊断，均保留来源/人员/原因。不能把0待核数描述成所有归属问题已解决。
- 初轮漏复制lineage父Snapshot历史查询证据而失败，按原明确引用补齐；不是用旧页面结果计算。随后修正花名册集合序列化、完整行JSON双重编码、关系摘要误含SQL物理顺序、费用来源绝对路径。一次复建在施工修正源码期间被“封口前规则变化”门禁拒绝。一次SQL原始JSON文本摘要尝试因数字文本表达差异失败，最终按读回JSON对象的统一规范摘要比较；没有修改业务数值。原失败日志/回执及试制批次保留，最终交验只用final4/rebuild4，不覆盖旧批次或历史失败。
- P0/P1封存检查见 `integrity-final.json`：P0的392份既有封存文件、P1的11份源码及136份证据摘要全部相同。P0历史验证器未运行、原记录未改写；P1原README按原字节保留，P2说明另存。当前业务库的56输入/95规则与现文件摘要一致。
- 未改生产指针、服务器、旧版部署、Canvas/Teedy、调度、钉钉或费用口径，未付费、未新增账号/收件人、未进行P3页面迁移。P4文件隔离与真实负载仍另验；本地计算和查询通过不代表生产性能通过。

## 总线程交验入口

先读本文件、规则清单和查询合同，再核对 `execution-receipts.jsonl`、最终manifest、`verification-final4/verification.json`与实际query receipts、`rebuild-verification4/verification.json`、`final-tests.log`、`old-build-smoke.log`、`integrity-final.json`。可用新的证据目录重跑verify，不覆盖已有证据。

施工到P2停止。阶段表只记录施工完成/待验收，不自填总线程通过，不启动P3。
