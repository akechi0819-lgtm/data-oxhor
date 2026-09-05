# Data OXHor 分层迁移状态

更新时间：2026-09-03

本文档是后续模块开发、Codex 任务和验收的对齐入口。迁移在同一 Git 仓库内按目录隔离，直接更新引用，不保留旧路径兼容层。

## 目标边界

| 模块 | 目标职责 | 当前状态 |
|---|---|---|
| `data_platform/` | Snapshot、landing、质量、受控只读查询、saved query | 迁移中 |
| `data_acquisition/` | BI、企业微信、文件同步脚本和 manifest；不是 LLM Agent | 部分完成 |
| `workspace_modeling/` | 工作区初始化、数据验证、Bridge 对齐、Pack、Casebook | 迁移中 |
| `analysis_product/` | 探索分析、异常下钻、结论和 PPT/表格交付编排 | 部分完成 |
| `dashboard_product/` | 固定查询、artifact、渲染、推送；只消费受控结果 | 核心完成 |

## 能力盘点

| 能力 | 当前归属 | 目标归属 | 状态 | 下一步验收 |
|---|---|---|---|---|
| Snapshot / DuckDB / Parquet / landing | `data_platform` | `data_platform` | 已完成，待迁移路径 | 新模块测试通过，旧路径不存在 |
| 受控只读 query / quality / saved query | `interfaces.data_platform` | `interfaces.data_platform` | 已完成，待迁移路径 | CLI 和 JSON 合同通过 |
| Business Pack | `business_pack` | `workspace_modeling/business_pack` | 已完成，待迁移路径 | Pack 校验和导入引用更新 |
| Company Bridge / Bridge 对齐 | `company_bridge`, `bridge_alignment` | `workspace_modeling` | 已完成核心流程，待迁移 | 多轮确认、finalize、Snapshot 兼容性通过 |
| Onboarding / 工作区建模 | `onboarding` | `workspace_modeling` | 已完成核心流程，待重命名 | init/import/sync/handoff 合同通过 |
| Casebook / 反馈 | `casebook`, `pilot_feedback` | `workspace_modeling` | 已完成，待迁移路径 | 证据不替代当前 Snapshot |
| BI 下载连接器 | `tools/connectors`, `data_layer` | `data_acquisition` | 核心连接器已完成，独立 CLI/manifest 未完成 | 下载校验、失败清理、manifest 测试通过 |
| 企业微信连接器 | 无 | `data_acquisition/connectors/wecom` | 未开始 | 认证、分页、限流和原始响应接口明确；未伪造完成 |
| 分析路由 Skill | `.agents/skills/business-analysis-routing` | 宿主 Skill；确定性交付代码归 `analysis_product` | 基础路由已完成，边界已明确 | 查询绑定 run/snapshot 和来源凭据；新增确定性分析代码再补 CLI 合同 |
| PPT Master Quick | `tools/s4_ppt_*` | `analysis_product` | 基础能力已完成，真实性能回归待补 | preflight、文件回查和数字回查通过 |
| 当前 Dashboard | 旧 `dashboard` 原型已移除 | `dashboard_product` | 核心完成：受控查询、artifact、HTML 渲染和季度筛选 | `dashboard_actuals/v6` 刷新、artifact 合同、同比切片和渲染测试通过 |
| Dashboard 生产发布 | 无 | `dashboard_product` | 未开始 | 认证、定时、服务器推送合同通过 |
| Daily Monitor | 无 | `dashboard_product` 或独立任务 | 未开始 | 明确触发和证据合同 |
| 项目级总路由器 | 不建设 | 不建设 | 已否决 | 由宿主或明确 CLI 选择产品能力 |

## 迁移记录

### 2026-09-03

- 决策：同一仓库内建立 `data_platform`、`data_acquisition`、`workspace_modeling`、`analysis_product`、`dashboard_product` 五个物理边界。
- 决策：`data_acquisition` 是脚本/连接器项目，不预建 Agent 或 MCP；企业微信先建接口和待办。
- 决策：Bridge 对话、验证和生成属于工作区建模，文件保存在客户工作区 `Work/` 与 `Output/`。
- 决策：看板独立生命周期，只通过 `data_platform run-saved-query` 取数，不直接连接 DuckDB，不读取 `latest` 指针。
- 影响：所有内部 import、CLI、文档和测试需一次性更新；不建立旧路径 alias。
- 验证命令：迁移完成后执行 `sh tools/run_tests.sh -v` 以及本文档末尾的 `rg` 门禁。

### 2026-09-03 清理补充

- 决策：移除旧 Dashboard 原型的硬编码 Snapshot、landing SQL、`/api/latest` 页面接口、维护 CSV 和源码目录运行产物；它们不满足独立产品的受控查询边界。
- 决策：Bridge 历史扫描保留 `data_layer/...` source locator，仅作为被审计的旧 Super Agent 资料坐标，明确不代表当前运行路径。
- 影响：当前 `dashboard_product` 使用显式 workspace/run，通过 `dashboard_actuals/v6` 受控查询生成 artifact 和静态 HTML；旧原型不保留兼容入口。
- 验证命令：`python3 -m unittest discover -s dashboard_product/tests -v`；刷新链路不得直接连接 DuckDB 或读取 landing 表。

## 禁止越界

- `data_platform` 不加入 BI 登录、企业微信 API、看板指标解释或页面渲染。
- `data_acquisition` 不定义业务口径，只产出原始数据和同步 manifest。
- `workspace_modeling` 不把 Bridge/Casebook 变成全局事实库。
- `analysis_product` 和 `dashboard_product` 不直接连接 DuckDB；必须经过 Data Platform 受控接口。
- 源码不得依赖 `runtime/latest.json`、模糊文件名或硬编码 Snapshot/warehouse 路径。

## 开放阻塞项

- 企业微信 API 权限、字段和业务口径尚未确认。
- Dashboard 生产认证、推送和定时运行尚未实现；当前已使用 confirmed `dashboard_actuals/v6` 和 `attributed_passive_reported_cash/v1`。
- PPT Quick 真实性能回归和 Dashboard 生产认证/推送尚未实现。

## 迁移门禁

```text
旧模块路径不存在；dashboard 不含硬编码 Snapshot/warehouse/landing；
源码不依赖 latest.json；dashboard 不直接 duckdb.connect；
各模块 CLI、退出码、JSON 输出和合同测试齐全。
```
