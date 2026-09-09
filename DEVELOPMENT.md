# Data OXHor 开发文档

本文档是当前主模块开发的工作记录和维护入口。它记录已经落地的结构、正在施工的能力和需要遵守的长期边界；客户操作步骤见 `docs/user-guide.md`，CLI 合同见 `docs/integration-guide.md`。

## 当前定位

项目正在从“单一数据分析产品”演进为模块化运营数据中台。数据接入、数据平台、工作区建模、自由分析、固定看板和未来监控各自拥有清晰的代码边界，可以由不同 Agent 独立启动。项目不实现一个总 Agent，也不实现项目侧自然语言路由、Session 管理或模型适配层。

## 模块状态

| 模块 | 目录 | 状态 | 说明 |
|---|---|---|---|
| 数据接入 | `data_acquisition/` | 已落地 | 来源 manifest、BI 下载和仓库重建任务 |
| 数据平台 | `data_platform/` | 已落地 | landing、不可变 Snapshot、schema、quality、受控只读 SQL |
| 工作区建模 | `workspace_modeling/` | 已落地 | Pack、Bridge、对齐向导、首次部署、Casebook、内测反馈 |
| 自由分析交付 | `analysis_product/` | 已落地/持续增强 | Quick PPT 冻结与导出辅助；分析编排由宿主 Agent 完成 |
| 固定看板 | `dashboard_product/` | 已落地/持续增强 | 四分册静态发布、basic auth、钉钉人员进度 |
| 日常监控 | `agents/daily_monitor/` | 预留 | 只有 Agent 合同，尚无运行代码 |

## 当前主线

当前主要施工对象是 `dashboard_product/` 和与其共享的 BI Bridge、saved query 及 Snapshot 合同。看板的设计期由自由分析 Agent 或宿主确认指标和 SQL；运行期由看板发布 Agent 执行固定查询、渲染并发布。看板不得在刷新时调用模型临时改变业务口径。

自由分析主线继续使用 `data_platform` 的显式 `run_id`、`snapshot_id` 和受控查询；需要交付文件时再调用 `analysis_product` 或宿主原生表格/图表能力。当前唯一历史待补事项是 S4 Quick 的真实性能回归，详见 `docs/handoff.md`。

## 开发原则

- 先让单个模块端到端可运行，再增加跨模块能力。
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
python3 -m dashboard_product.notify --help
python3 -m unittest discover -s dashboard_product/tests -v
sh tools/run_tests.sh -v
git diff --check
```

## 决策记录

### 2026-09-07：采用模块 Agent 目录，不建设总路由 Agent

- 决定：在 `agents/` 下按工作区初始化、自由分析、看板发布和日常监控提供独立 Agent 文件；项目不提供一个负责跨模块分派的主 Agent。
- 原因：未来运营中台由多个智能体协作或分别运行，模块边界应由调用者选择，而不是再次形成单体路由上下文。
- 影响：新增业务场景时新增对应模块和 Agent 文件；不要把新场景继续塞入自由分析 Agent 或根目录提示词。
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

### 2026-09-09：删除废弃看板版本与兼容层

- 决定：运行时只保留 `dashboard_actuals/v7`。删除空的 v1–v5 Saved Query 目录、旧业务组分册过滤器和前端空 `yoy_groups` 补丁。`attributed_passive_reported_cash/v1` 仍是现行逐笔底稿。
- 原因：项目不保留向后兼容；旧目录和兼容层会让下一轮误把 v6 或空年段当成现行合同。
- 影响：`liuxue` / `gaozhong` / `daxue` 不再有过滤入口。刷新产物缺少 `yoy_groups` 时同比表为空，不会补四个空年段。
- 验证：`python3 -m unittest discover -s dashboard_product/tests -v`；`python3 -m unittest tests.bridge.test_reviewed_artifact -v`。
