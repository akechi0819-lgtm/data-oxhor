# Data OXHor

Data OXHor 是面向教育运营团队的模块化运营数据中台。它把数据接入、数据仓库、业务口径、客户工作区、分析交付和固定看板拆成可独立使用的产品模块，供外部 Agent Host 或人工运维流程调用。

项目本身不承担一个总 Agent，也不在项目内做跨模块自然语言路由。使用者可以从 `agents/` 选择所需的模块 Agent，在对应客户工作区中运行；Agent 通过稳定 CLI 调用确定性代码。

## 项目结构

```text
data_acquisition/    数据来源接入、认证和导入任务
data_platform/       landing、Snapshot、质量检查和受控只读查询
workspace_modeling/  Business Pack、Company Bridge、工作区、Casebook 和首次部署
analysis_product/    分析交付的确定性辅助代码，目前包含 Quick PPT
dashboard_product/   固定口径看板的刷新、四分册发布和可选钉钉人员进度
interfaces/          对外 CLI 边界
customers/           按公司隔离的 Input/Work/Output 工作区
agents/              可单独选择的模块 Agent 说明，不含总路由 Agent
docs/                合同、架构、接入、运维和用户文档
```

模块关系如下：

```text
客户数据源 -> data_acquisition -> data_platform Snapshot
                                      |
                         workspace_modeling Pack + Bridge
                                      |
              ┌───────────────────────┴───────────────────────┐
              |                                               |
       ad_hoc_analysis Agent                         dashboard_publisher Agent
       查询、诊断和按需交付                         固定查询、看板刷新和发布
              |                                               |
       analysis_product / Casebook                    dashboard_product
```

## 如何使用

先根据任务选择一个独立 Agent：

- [工作区初始化 Agent](./agents/workspace_setup/AGENT.md)：首次部署、导入数据、发布 Snapshot、对齐 Bridge。
- [自由分析 Agent](./agents/ad_hoc_analysis/AGENT.md)：当前 Snapshot 上的业务查询、诊断、下钻和按需交付。
- [看板发布 Agent](./agents/dashboard_publisher/AGENT.md)：运行已确认的固定查询、生成 HTML 并发布看板。
- [日常监控 Agent](./agents/daily_monitor/AGENT.md)：监控场景的预留合同，当前尚未实现运行代码。

这些文件是模块使用说明和启动提示，不是项目内的 Agent Loop。宿主仍负责会话、模型、权限和文件交付。

## 主要边界

- `data_platform` 只处理结构、身份、质量和只读查询，不解释教育业务。
- Business Pack 保存跨企业行业知识；Company Bridge 保存单一公司的字段、枚举和口径。
- 当前事实必须来自当前 Snapshot 的受控查询；Casebook 只能提供已确认的方法线索。
- 看板只运行已确认的 saved query，不由模型临时决定公式或筛选。
- 原始工作簿、DuckDB、Parquet、`runs/` 和客户工作区数据不进入 Git，也不自动上传。
- 项目不建设总路由 Agent、项目侧 Session 管理器或 MCP 服务。

## 常用入口

```bash
python3 -m interfaces.workspace_modeling --help
python3 -m interfaces.data_platform --help
python3 -m interfaces.business_pack validate
python3 -m interfaces.company_bridge validate --help
python3 -m interfaces.casebook --help
python3 -m dashboard_product.refresh --help
sh tools/run_tests.sh -v
```

首次部署、CLI 合同和运维步骤见 [接入指南](./docs/integration-guide.md)、[用户指南](./docs/user-guide.md) 和 [运维手册](./docs/operator-runbook.md)。当前开发状态、主模块施工记录和决策见 [开发文档](./DEVELOPMENT.md)。系统边界见 [架构说明](./docs/architecture.md)。
