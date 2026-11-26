# Data OXHor 项目入口

## 按任务加载技能

| 任务 | 入口 |
| --- | --- |
| 日更、补数、费用与腾讯表同步 | [daily-ops](.agents/skills/daily-ops/SKILL.md) |
| 查经营数据、归因对账、导表 | [biz-analysis](.agents/skills/biz-analysis/SKILL.md) |
| 天津市场线上产出、周报或新媒体双周报 | [biweekly-report](.agents/skills/biweekly-report/SKILL.md) |

维护代码时，从[系统架构](docs/architecture.md)定位模块，并按[维护指南](docs/maintainer-guide.md)验证。发布参见[看板部署说明](dashboard_product/DEPLOYMENT.md)。独立的 Grok 工作按 [Grok 工作区](grok_workspace/AGENTS.md)处理。

## 数据与操作边界

- 市场分析绑定 `customers/shadow_bi_daily/`。用 `market_workspace/oxhor status` 获取明确的 release 或 Snapshot 身份，通过 Data Platform 受控只读入口查询。历史案例只提供方法。
- 官方留学记分卡在已明确的口径与覆盖期内优先。看板与查数的差值先核对日期、团队、客户域和口径。负向现金按原值表述，原因由业务核实。
- 原始数据只读，Snapshot 使用唯一 ID 构建并核验后切换。客户数据、运行目录、DuckDB、Parquet 和凭据留在项目授权边界内。
- 发布、对外发送及写回须有当前授权。联调用隔离目录和模拟服务。使用已确认身份与源文件哈希，核验已发送、发布当前版本和目标表读回结果。

## 任务文件与收尾

- 新市场任务用 `workspace/tasks/<YYYYMM-任务名>/{scratch,evidence,deliverables}`，同一任务的修订沿用该目录。显式设置制作和输出路径，共用仓库运行时。现有客户仓、运维入口及历史证据继续使用原路径。
- 开发验收进 `.local/audits/<任务名>/`。交付前打开最终文件、核对证据与依赖，保留人工原稿、正式证据及约定格式，只清理本任务已替代且无引用的暂存。
- 需要 PPT 时使用宿主提供的 PPT 制作技能，输入已核验数字；当期历史数据以本次证据为准。
