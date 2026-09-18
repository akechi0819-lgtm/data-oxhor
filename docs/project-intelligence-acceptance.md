# Project Intelligence 第一阶段验收

验收日期：2026-09-17。本地实盘核验时间为 14:12:49 Asia/Shanghai。结论：本地上下文服务功能与针对性安全测试通过；项目全量回归存在一项未通过的既有业务 SQL 对比测试，不宣称全项目测试全绿。

## 实现范围

新增 `project_intelligence/`：显式允许清单、只读文件读取、文本过滤、来源与哈希、搜索/分页、项目概览、工作区元数据、连接说明及本地 CLI。没有 ChatGPT 接入、MCP 协议服务、网络监听或隧道，没有新增第三方依赖。

本轮修改仅包括新模块、新测试、包入口声明及直接相关导航/文档；没有修改数据接入、Data Platform、Bridge、看板或监控的业务代码，没有修改客户数据、业务配置或已存在 SQL，也没有提交、发布或推送。

## 功能验收

| 项目 | 实测结果 |
|---|---|
| 批准文件 | 55 个实际可读文件；未发现缺失项。敏感过滤可能隐藏部分或全部正文，来源返回 filtered/suppressed，不能以允许读取推断所有正文均会公开 |
| Agent | 四个运行合同均存在：workspace_setup、ad_hoc_analysis、dashboard_publisher、daily_monitor |
| 工作树 | 正确识别有未提交修改；只返回批准路径，其余仅计数 |
| 搜索与读取 | 字面检索、来源行号、分页、预期哈希校验均通过 |
| 查询版本证据 | 运行配置 v10、代码字面量 v10、架构文档当时声明旧版；正确标记差异。2026-09-18 操作说明已统一 v10，历史观察不代表仍支持旧入口 |
| 运营工作区 | 显式 Snapshot 为 snapshot_bi_operations_20260916_fy25；Bridge 1.5.0 合同通过、公司匹配 |
| 运营结构 | 5 张表：ingest.sources、ingest.sheets、2 张 landing、quality.issues；现金 72 列、工单 136 列（均含技术元数据） |
| 教学工作区 | 显式 Snapshot 为 snapshot_teaching_classes_20260821；返回 BRIDGE_NOT_CONFIGURED 和 SCHEMA_CONTRACT_MISMATCH，未选择另一 Snapshot 或尝试修复 |
| 外部连接 | 6 类已声明连接，全部明确 live_status=not_verified；未探测本机服务、云电脑、服务器、BI 或钉钉 |
| 业务可分析性 | 明确 not_evaluated，不把 Bridge 合同通过当成当前业务分析许可；未读取样本/质量明细 |

## 只读验收

对本轮调用涉及的 62 个文件做前后 SHA-256 比较，全部一致。覆盖批准源码/文档、两工作区当前指针、Pack/Bridge 文件和两份当前 DuckDB。哈希在服务外的本机验收脚本中计算，不作为 MCP 输出数据库内容，不读取业务行。

合成工作区测试同时核对整个测试目录的文件集合及内容哈希不变，包含通过真实 Data Platform CLI 执行 describe 的场景。故障测试没有执行 SQL、任意命令或网络操作。

## 测试结果

| 测试组 | 结果 |
|---|---|
| Project Intelligence 定向测试 | 18/18 通过（包含于下方主测试，不重复计入总数） |
| 主测试 tests/ | 114 项，113 通过、1 失败 |
| 看板 dashboard_product/tests/ | 30/30 通过 |
| 监控 monitoring_product/tests/ | 19/19 通过 |
| 合计 | 163 项，162 通过、1 失败 |
| git diff --check | 通过 |

定向覆盖：非批准路径、目录/文件软链、FIFO、敏感行及无缩进多行秘密、搜索泄露、恶意文档仅作为资料、分页/大小上限、旧哈希、Snapshot 不匹配、JSON 元数据并发变化、数据库软链、异常正文过滤、Git hook 禁用、CLI 参数错误不回显、真实 describe 的无写入与无数据行返回。

完整测试脚本在主测试失败后按既有 set -e 停止，因此看板与监控另行执行完成，并非宣称该脚本返回成功。

未通过项：`tests.bridge.test_reviewed_artifact.ReviewedCompanyBridgeArtifactTests.test_dashboard_work_order_ids_stay_text_and_manifest_matches`。该测试在 `tests/bridge/test_reviewed_artifact.py:45` 当时固定读取客户旧版 Saved Query，随后要求它与 `dashboard_product/sql/dashboard_actuals.sql` 完全一致；当前两者不一致。测试与这两份 SQL 均未被本轮修改。为遵守本轮不改业务逻辑的范围，保留失败并记录，未更新 SQL、未改测试断言、未跳过测试。

2026-09-18 后续修复：该测试改为读取当前运行配置声明的查询版本 v10；SQL 内容、工单 ID 类型和 manifest 哈希断言均保留，3 项相关测试通过。本记录保留首次验收时的测试结果。

## 已知边界

- 仅暴露显式批准的文件和工作区，不是通用文件服务器；新来源需要评审允许清单。
- 保守过滤会牺牲部分代码可读性。它不是任意编码秘密识别器，主边界仍是允许清单、字段投影与来源评审。
- Python API/CLI 的只读实现不构成 OS 沙箱；未来常驻部署需只读权限隔离，当前要求可信 checkout。
- Bridge 与 Snapshot 的完整业务兼容性、业务质量、远端在线状态和当前调度任务均未纳入本阶段。
- 本记录是验收时刻的观察，不代替下一次请求时读取实际工作树和显式 Snapshot。
