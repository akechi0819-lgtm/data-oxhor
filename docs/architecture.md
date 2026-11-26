# 系统架构

Data OXHor 通过同一组可核验 Snapshot 生产经营看板、报告和腾讯表写回。操作者从 `ops` 管理日更、补数、费用和同步，市场分析从 `market_workspace/oxhor` 进入只读查询。

## 日更与发布

1. `ops run business` 通过 BI 与腾讯文档取得语培、留学输入。语培在落盘、窗口合并及发布前校验表头、行数、日期与跨版本回撤。人工原件以文件 SHA 绑定，经相同门禁。
2. Data Platform 生成不可变 Snapshot。SQL 构建将明确的语培、留学 Snapshot 组装为同一 release，旧 `business.*` 数据集与 Superset 发布合同继续由既有验证器核验。
3. SQL 候选在本地隔离构建并封存。激活后才更新 Current。当前版本比对可查 `release-comparison.json`。
4. 日报使用当次通知结果。服务端在共享投递锁下对每条消息去重，无法确认的发送留待核对。
5. 费用独立按日录入和发布。事务替换的费用候选沿用核验的业务版本及通知预览。空额保留缺失，零额须有确认。

## 经营语义

- `raw` 对应来源 landing。原始对账走显式 Snapshot。
- `core` 按期间、范围及维度提供归因证据。语培经营人头在各自范围汇总到学员班级后判断阈值，再按学员去重。留学客户与小语种学员分列。
- `mart` 提供和发布相同的经营及维度汇总。留学团队总计排除 SSC，线上包含虚拟人。
- `ref` 保存带版本和哈希的官方记分卡。只有口径与日期均可比时才计算差额。输入文件在原始参考目录，Snapshot 仅含来源事实。

指标与证据关系见[经营指标索引](metrics-reference.md)。查询接口见[接入指南](integration-guide.md)。

## 腾讯表与客户端

`ops sync-sheets` 分别运行投流、大众点评和初三适配器。各表保留来源、保护列和写入策略。列头核对与提交读回复用公共逻辑，失败原因写入 `runtime/ops_state.db`。

Business Data MCP 为同一个 result ID 固定查询范围、期间及可比指标。服务端分页和 CSV 继续使用原结果，附带结构化说明。MCP 客户端说明见 [Business Data MCP](../business_data_mcp/client/接入说明.md)。

## 任务、维护与权限

三个项目技能从[根入口](../AGENTS.md)加载。新市场任务在 `workspace/tasks/` 保存草稿、证据和交付物。正式数据、运维程序与历史证据沿用已登记的位置。

Project Intelligence 提供本地只读上下文。运行与检查入口见[运维手册](operator-runbook.md)，部署看[看板合同](../dashboard_product/DEPLOYMENT.md)，开发与回滚看[维护指南](maintainer-guide.md)。
