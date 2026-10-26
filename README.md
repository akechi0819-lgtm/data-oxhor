# Data OXHor

Data OXHor 是面向教育运营团队的模块化运营数据中台。它把数据接入、数据仓库、业务口径、客户工作区、分析交付、固定看板和日常监控拆成可独立使用的产品模块，供外部 Agent Host 或人工运维流程调用。

根目录 `AGENTS.md` 提供轻量板块导航，帮助整体架构调整时定位目录和模块说明，选定后按需读取。项目不实现总控 Agent 或跨模块调度。使用者可以从 `agents/` 选择所需的模块 Agent，在对应客户工作区中运行；Agent 通过稳定 CLI 调用确定性代码。

## 项目结构

```text
data_acquisition/    数据来源接入、认证和导入任务
data_platform/       landing、Snapshot、质量检查和受控只读查询
workspace_modeling/  Business Pack、Company Bridge、工作区、Casebook 和首次部署
dashboard_product/   正式原生 Superset BI、共同业务计算、固定发布及通知兼容
monitoring_product/  同批结果预览、钉钉投递和传输
market_workspace/    市场日常启动入口：自由分析、导表、程序和临时脚本
interfaces/          对外 CLI 边界
project_intelligence/ 项目级只读上下文服务（Python API / CLI / stdio MCP）
customers/           按公司隔离的 Input/Work/Output 工作区
agents/              可单独选择的模块 Agent 说明，不含总路由 Agent
docs/                现行合同和指南；history/ 保存历史记录
grok_workspace/      Grok Bot 隔离工作面，角色与自主积累材料不进入核心模块
.local/              本地日志、同步中转和历史运行材料，不进入 Git
```

管理看板与通知绑定同一正式 BI release。管理构建和服务器通知包均通过 Data Platform 受控只读入口读取数据；`monitoring_product` 只执行固定通知规则和投递，不承担自由分析或任意 SQL。共享人员规则位于 `workspace_modeling/operations/`。

模块关系如下：

```text
客户数据源 -> data_acquisition -> data_platform Snapshot
                                      |
                         workspace_modeling Pack + Bridge
               |                                |
       ad_hoc_analysis Agent          dashboard_publisher Agent
       查询、诊断和按需交付          固定 SQL、管理批次构建
               |                                |
       workspace_modeling             管理批次结果
       delivery / Casebook                |
                             Mac p5.daily → Superset release
                                            |
                                     daily_monitor Agent
                                            |
                     release_notifications → monitoring_product 投递
```

## 如何使用

市场日常查询、导表和生成小程序，直接打开 [市场工作区](market_workspace/README.md)，从 `./oxhor status` 开始；该目录复用已有数仓。

其他场景根据任务选择一个独立 Agent：

- [工作区初始化 Agent](./agents/workspace_setup/AGENT.md)：首次部署、导入数据、发布 Snapshot、对齐 Bridge。
- [自由分析 Agent](./agents/ad_hoc_analysis/AGENT.md)：当前 Snapshot 上的业务查询、诊断、下钻和按需交付。
- [看板发布 Agent](./agents/dashboard_publisher/AGENT.md)：运行已确认的固定 SQL、构建同批管理结果并更新原生 BI；当前入口与切换状态见 [部署说明](./dashboard_product/DEPLOYMENT.md)。
- [日常监控 Agent](./agents/daily_monitor/AGENT.md)：管理批次消息预览与钉钉投递；运行模块为 `monitoring_product/`，消费看板生成的共同结果。

这些文件是模块使用说明和启动提示，不是项目内的 Agent Loop。宿主仍负责会话、模型、权限和文件交付。

## 主要边界

- `data_platform` 只处理结构、身份、质量和只读查询，不解释教育业务。
- Business Pack 保存跨企业行业知识；Company Bridge 保存单一公司的字段、枚举和口径。
- 当前事实必须来自当前 Snapshot 的受控查询；Casebook 只能提供已确认的方法线索。
- 管理看板使用已确认并纳入版本控制的固定 SQL，经 Data Platform 受控只读入口执行；原生 BI 页面与投递绑定同一正式 release。
- 原始工作簿、DuckDB、Parquet、`runs/` 和客户工作区数据不进入 Git，也不自动上传。
- 项目不建设总路由 Agent 或项目侧 Session 管理器。Project Intelligence 提供独立的本地只读上下文服务；现提供独立 stdio MCP 适配器，已通过官方 Secure MCP Tunnel 接入 ChatGPT Developer Mode，运行说明见 `docs/project-intelligence-tunnel.md`。

## 阶段状态

2026-09-18架构阶段的查询证据、自由分析交付和 Casebook 验证已完成，历史记录见 [施工计划与验收](./docs/history/agent-architecture-plan-20260918.md)。截至 2026-10-26 的记录，正式 BI 更新仍使用 Mac `dashboard_product.shadow_bi.p5.daily`；服务器 raw 固定接收和发布服务虽已部署，10/26 Dot 批次因业务截止门禁失败而未发布，尚未切换生产入口。服务器通知适配已部署；记录中自 10/26 起的 Dot 10:00 日程是通知日程，与 BI 采集刷新分开。Grok 例行已按用户要求停止。各项均以日期回执为依据，本次未作调度平台实时核验；详见 [部署说明](./dashboard_product/DEPLOYMENT.md)、[日常监控](./monitoring_product/README.md) 和 [同步记录](./SYNC.md)。

## 常用入口

```bash
python3 -m interfaces.workspace_modeling --help
python3 -m interfaces.data_platform --help
python3 -m interfaces.business_pack validate
python3 -m interfaces.company_bridge validate --help
python3 -m interfaces.casebook --help
python3 -B -m project_intelligence --help
python3 -m dashboard_product.management.build --help
python3 -m dashboard_product.shadow_bi.p5.daily --help
python3 -m monitoring_product.shared_delivery --help
sh tools/run_tests.sh -v
```

首次部署、CLI 合同和运维步骤见 [接入指南](./docs/integration-guide.md)、[用户指南](./docs/user-guide.md) 和 [运维手册](./docs/operator-runbook.md)。当前开发状态、主模块施工记录和决策见 [开发文档](./DEVELOPMENT.md)。系统边界见 [架构说明](./docs/architecture.md)。
