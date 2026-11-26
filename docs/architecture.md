# 系统架构

Data OXHor 通过同一组可核验 Snapshot 生产经营看板、报告和腾讯表写回。操作者从 `ops` 管理日更、补数、费用和同步，市场分析从 `market_workspace/oxhor` 进入只读查询。

## 日更与发布

1. `ops run business` 通过 BI 与腾讯文档取得语培、留学输入。语培在落盘、窗口合并及发布前校验表头、行数、日期与跨版本回撤。人工原件以文件 SHA 绑定，经相同门禁。
2. Data Platform 生成不可变 Snapshot。SQL 构建将明确的语培、留学 Snapshot 组装为同一 release，旧 `business.*` 数据集与 Superset 发布合同继续由既有验证器核验。
3. Mac 同步基础行增量，云端以固定 SQL 隔离构建候选并核对历史可比窗口。激活后更新正式指针，Mac 共用 `runtime/releases/<发布号>/library` 作为日更基线和只读查询仓。版本比对可查 `release-comparison.json`。
4. 日报使用当次通知结果。服务端在共享投递锁下对每条消息去重，无法确认的发送留待核对。
5. 费用独立按日录入和发布。事务替换的费用候选沿用核验的业务版本及通知预览。空额保留缺失，零额须有确认。

## 经营语义

- `raw` 对应来源 landing。原始对账走显式 Snapshot。
- `core` 按期间、范围及维度提供归因证据。语培经营人头在各自范围汇总到学员班级后判断阈值，再按学员去重。留学客户与小语种学员分列。
- `mart` 提供和发布相同的经营及维度汇总。留学各级统计排除 SSC，线上包含虚拟人。筛选项和补充卡片按同一范围发布。
- `ref` 保存带版本和哈希的官方记分卡。每个财年从 6 月 1 日至次年 5 月 31 日，依次按 6–8 月、9–11 月、12 月至次年 2 月、3–5 月分季。经业务确认的可比口径放在同一参考目录的 `留学板块-官方记分卡-对账口径.json`。源文件哈希、期间、范围、定义及单位匹配且数仓完整覆盖时计算差额。2026 年 6–8 月的留学资源按发生日期及非空资源 ID 去重，毛签按纯留学正向签约金额换算万元。Snapshot 只保存来源事实。

指标与证据关系见[经营指标索引](metrics-reference.md)。查询接口见[接入指南](integration-guide.md)。

## 腾讯表与客户端

`ops sync-sheets` 分别运行投流、大众点评和初三适配器。各表保留来源、保护列和写入策略。列头核对与提交读回复用公共逻辑，失败原因写入 `runtime/ops_state.db`。

Business Data MCP 为同一个 result ID 固定查询范围、期间及可比指标。服务端分页和 CSV 继续使用原结果，附带结构化说明。MCP 客户端说明见 [Business Data MCP](../business_data_mcp/client/接入说明.md)。

## 任务、维护与权限

三个项目技能从[根入口](../AGENTS.md)加载。新市场任务在 `market_workspace/tasks/` 保存草稿、证据和交付物。正式数据、运维程序与历史证据沿用已登记的位置。

运行与检查入口见[运维手册](operator-runbook.md)，部署看[看板合同](../dashboard_product/DEPLOYMENT.md)，开发与回滚看[维护指南](maintainer-guide.md)。
