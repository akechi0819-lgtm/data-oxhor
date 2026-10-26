# 原始输入固定发布接线（2026-10-26）

用户已批准现HTTPS/token调用固定发布程序；raw worker继续无正式写权。实现从d47da30c构建，未合入e4ce44a3的root完成证明方案，不引入证书/签发系统或可用日期降级发布分支。

## Dot触发合同

先按现合同POST三Excel包到`https://dashboard.apinova.cn/shadow-bi/v1/raw-batches`并GET同路径`/<batch>`，只有status=prepared且父线程已验收本次源任务/输入窗口和质量后，才调用：

```http
POST https://dashboard.apinova.cn/shadow-bi/v1/raw-batches/<batch>/publish-prepared
Authorization: Bearer <现有受保护凭据>
Content-Type: application/json

{}
```

不传命令、路径、SQL、日期、接收人或跳过门禁字段。排队202/status=publish_queued，运行publishing；GET原batch状态优先显示root发布状态：published/release/published=true，或publish_failed/error_code/published=false。未prepared为409；未鉴权401；非空对象400。重复同批请求返回已有状态，不重新构建/发送；原包同hash重放也返回权威发布状态。输入接收/计算成功不等于正式发布成功。

成功后可用现有只读`GET /shadow-bi/v1/notifications/status`交叉核对release_id、as_of_date、data_through；正式验收还包括真实BI身份、页眉及查询，不能只看health。该GET不发送通知，本接线没有新增通知发送能力或收件人配置。

## 固定程序和权限

root-owned固定代码在`/srv/shadow-bi/raw-code`；新增`shadow-bi-raw-publish.path/service`与`/usr/local/sbin/shadow-bi-raw-publish`。shell仅加载既有应用环境并执行固定Python模块，无请求参数拼接。没有新token、账号、密钥、监听或防火墙变更。

- `raw-publish-pending` root:shadowbi 2770，receiver只写固定小marker；共享队列锁660。
- `raw-publish-status` root:shadowbi 2750，状态640/root所有；receiver只读，不能伪写published。
- `raw-publish` root:root 700，私有发布日志/回执；receiver和shadowraw均不可读写。
- shadowraw仍只能计算候选，不能写发布队列/状态/current或代码。receiver命名空间也不能写current/代码或读计算私有区。

root程序只读取固定batch下prepared回执及三Excel/包hash，复核当日/昨日、明确窗口/月份、双Snapshot身份和质量、39表封存清单，冻结JSONL后复用P4类型库构建与激活；server_complete已含radar_people，不重复运行旧P3补表。与旧成品publisher复用`/run/shadow-bi-receiver.lock`，同时持有现raw producer锁，避免并发重构建。请求时记录正式manifest hash，处理前变化则拒绝，不隐式覆盖另一批。

复用P4实际服务启动、页眉/批次/6指标验收，再运行原verify_daily的三范围18指标验收。失败恢复操作开始时current；不删除它，不用不存在的历史previous假装回滚。回滚后清掉指向失败候选的previous链接。成功后才提交新root只读Snapshot基线并更新下一批consumer policy；复制保留完整历史数据的当前两仓及其必要归一历史证据，旧Snapshot实体只从新基线副本中移除，原输入/历史仓不动。基线预检失败发生在切current之前。

新版本验收成功后执行latest-only：只清确认无current、活动FD或Nginx引用的旧release及同名incoming，移除其previous；保留原始历史、通知状态及日志。有活动引用则记录cleanup_pending，不假称已清空。派生的旧daily-raw基线在新基线晋升成功后清理，原初始历史基线不动。

## 验收边界与当前进度

本地完整回归774 passed、10 skipped、198 subtests；包含真实合成39表类型重建、幂等、错源/hash/窗口身份、质量拒绝、互斥、低空间、链接/FIFO/坏marker、失败恢复、旧版验收后清理、基线压缩及晋升顺序。skip仍为9项可选MCP协议和1项锁定Superset认证模块；不把合成测试算作今日真实数据发布。

实际部署已核对receiver UID997、shadowraw UID995权限；root固定服务处理故意错误current hash请求得到publish_failed/formal_changed，未进入release/激活。真实HTTPS未认证发布401、BI/receiver health200，current和manifest hash保持daily-20261025_184644t。两个path在waiting；尚未对真实新batch执行正式激活或发送钉钉。

源没有“完整业务日水位”，本程序不制造root签名证明。可观测验收包括：两源当日ETL成功且导出在刷新后、实际日期字段/时区/窗口、任务完成、UI与文件行数、原字节hash、昨日范围、双仓quality和39表门禁；这些不等于上游绝对完整。昨日有一行或刷新时间本身均不是完整证明。若父线程不能确认用户接受的昨日完整验收标准，就不调用发布，不按可用日期降级。

Mac自动化bi-2“看板每日更新与运行观察”仍为ACTIVE/09:40，本线程未暂停。共同锁只防同时写，不防先后覆盖；本轮正式测试前由父线程协调暂停该生产者。新流程验收后收敛正式入口，不增加旧格式fallback或双跑；没有本轮新建日更任务。施工部署可用Mac，正式采集/上传/计算/发布触发只能Dot与server，Mac SSH代发布不计脱机成功。

服务器回执：`warehouse-validation/raw-fixed-publish-deploy-20261026-task4/`的setup/security/final-receiver结果；本机任务4保存对应JSON与publisher-core-verified.txt。两处旧派生实体可释放，但清理方须先保留质量、指标、全部manifest/hash、输入绑定、查询及日志；本线程没有删除。
