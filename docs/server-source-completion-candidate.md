# 来源完整覆盖与最大记录日分离（本地候选，未部署）

基线为`d47da30c`。本候选在独立分支`codex/raw-coverage-evidence`，不合入main、不上传服务器、不修改当前failed批次或生产通知/BI current，也不执行整批重构建。

## 已确认的语义错位与本次证据

原`management/sql/coverage.sql`在当前Snapshot上取工单分配时间、现金业务日期的MAX，`management.calculation.calculate`再取两者和昨日的最小值，写入metadata.data_through。该值是原计算口径下的可用记录截止日，不是上游业务日完整性证明。raw manifest的昨日data_through是声明，daily双仓receipt的cutoff_date来自调用参数、captured_at是服务端导入完成时刻；都不能替代上游水位。

本次实际三Excel hash、双Snapshot、quality、39表完整性及失败回执已在部署回执留存。父Dot补到的两页UI：工单/智能ETL更新时间2026-10-25 09:20:30，现金前台日报拼接表/智能ETL更新时间2026-10-25 04:22:28，10/25单日均无数据且无完成业务日/分区水位。现金完整窗口UI15524行与文件一致。这只支持“尚无10/25完整证明”，不能推出源站漏数、完整零业务或必然待晨更。刷新时刻本身不被此候选认可为完整覆盖证据。

## 候选行为

- 默认CLI/旧管理计算不传完成证据，仍返回原有min(MAX日期,昨日)，不添加虚假的完整性声明；现通知合同及发送入口源码不改。
- raw新批次先做轻量证据预检。缺失或无效时落盘`coverage_unverified`、published=false，不启动历史复制/双仓导入/业务构建。公开状态只有原白名单身份、该状态和published=false；私有原因仅evidence_missing/evidence_invalid。该状态表示未验证，不表示业务缺行。
- 正常零业务日无需虚构一条昨日记录：受保护完成证据通过后，计算使用经验证的昨日截止；原facts/金额/去重/Pack/Bridge不改、不补记录。观察到的两张表最大日期仍写入metadata.observed_dates；metadata.source_completion绑定证据摘要，和data_through分开。人员产能收到同一经验证计算截止，避免一处25一处24。
- 原个人26日至次月25日、线上平台自然月规则继续复用现函数。新raw计算在child重读相同证据，封口门禁核对metadata中的相同证明；prepared重验/维护recheck也校验同一证明。证据改变/消失不会被静默接受。
- 同批同hash重放仍幂等。既有failed和新coverage_unverified均不被HTTP重放复活，不自动重构建；本候选没有增加恢复路由或自动补发。证据后来到达的受控恢复流程仍需单独安排；无需重复下载不变的源文件来制造“昨日有行”。
- 不实现“按可用日期发布”开关或用户字段，不替业务方选择这一政策。

## 完成证据的信任边界（候选协议）

固定目录`/var/lib/shadow-bi/raw-control/source-completion/<batch>/`，由后续受控运维审阅流程安装。当前没有安装脚本、HTTP路由、token新权限或自动签发器；业务用户不需手写JSON。本轮未创建服务器目录或文件。

`approval.json`以及两份固定名`orders.evidence`/`cash.evidence`须root所有、非组/全局可写；root-control、source-completion、batch目录也须如此。reader用目录FD、O_NOFOLLOW、O_NONBLOCK及fstat读取，拒绝链接/FIFO、超限文件、错误所有者/权限，审批JSON上限16KiB、每份证据2MiB，不执行或渲染内容。worker/receiver无安装或改写审批能力。未来目录建议root:shadowraw 750、文件640，继续沿现只读访问边界，无新凭据或开放命令。

审批结构为shadow_source_completion.v1，包含完整binding、带时区且当日的reviewed_at，以及orders/cash两条上游完成水位。binding逐项精确绑定实际TAR hash、全部三Excel hash、batch、company、as_of、声明昨日、BI窗口和腾讯替换月份。reader自己计算输入hash，不信请求自报hash。每条来源限定source_id、kind=upstream_completion_watermark、complete_through=昨日及对应证据字节hash。`etl_refresh_timestamp`、`export_completed`、`observed_max_date`不能冒充此kind，另一文件/窗口/日期/月/公司/批次的审批不能重用。raw HTTP合同仍严格拒绝额外source_completion等字段。

root审批不是来源数字签名。根本信任点是受信任运维审阅者已经核对真实上游“完成业务日/完整分区水位”及其与该次导出、窗口、文件的关系；仅把任意截图保存到root目录、改个kind标签或只提供刷新时间，并不构成独立来源证明。此候选不会从本次无水位UI自动签发审批。证明范围仅BI工单/现金；绑定腾讯文件防止混批，不把此审批冒称为腾讯每日完整性证明，腾讯仍走原月替换/双Snapshot/quality及来源范围规则。

## 明早可执行计划（仅计划，不创建任务）

1. 建议上海10/26约09:30、现10点通知前，先只读检查两数据集ETL最后成功刷新、失败/运行中状态及最新完整业务日/分区水位；09:30是检查建议，不承诺源一定按昨日09:20/04:22刷新。刷新仍旧或未完成则等待实际更新，不反复整批下载。
2. 若来源更新，再确认日期字段/时区/端点包含规则，按当日明确窗口4/26..10/26采集工单、现金，腾讯仍整本与明确2026-10替换。保留导出任务身份、实际过滤条件、完成状态、行数和文件hash关联。一次新采文件不等于完整性证明。
3. 上游若能给出10/25完成证据，走选项A审阅绑定；没有水位则继续未验证，交业务选择选项B，不把“最近刷新已是今天”当水位。当前候选未部署，实际POST前仍由主线程协调候选部署/验收，不重放旧failed批次假装新成功。
4. 只有当天新批次通过完整性、双仓、39表及发布验收，且唯一生产者安排清楚后，才让既有通知触发消费该新正式版。10点前未验收则不调用旧版send-scheduled、不补发旧数。现通知合同要求as_of为当天且data_through为昨日，旧current会被拒绝；本地候选尚未约束现Mac生产者，需父线程协调任何实际生产接线，不能宣称已经自动拦住所有未来不完整批次。本轮不新建定时、不停Mac bi-2、不恢复Grok。

## 待主线程集中确认的两个选项

A. 使用显式、可信并绑定导出文件的源完成证据；完整但零记录的昨日可计算为零，通知仍必须满足当天新正式版及完整昨日。

B. 业务接受按实际可用记录日期显示，并醒目标记“完整性未验证/未完成”。这不是完整昨日成功，默认不触发现有昨日完整通知；看板标签、发布及通知政策需另行明确后实现。当前未选择、未实现此分支。

## 验证范围

新增测试使用明确标识的合成审批/数据；本机UID模拟只用于测试，生产reader固定要求UID0。覆盖准确绑定与伪造字段、错hash/window/day/month/company/batch、单源缺失、仅刷新/导出完成/max日期、审批日期时区、权限/链接/FIFO/大小、源文件改动、缺证据不启动重构建、原failed幂等不复活、公开状态不泄私有证据。合成39表用真实类型库和受控查询执行物理COUNT门禁，并验证缺失/变化证明拒绝。真实aggregate与build_notifications合成零事实的八张卡验证10/25收口和10/26转下一绩效月、线上平台仍按自然月，未发送消息。

不包含本候选真实源正向完成证明、不包含真实39表全量重算/新同源612对账、不包含服务器部署或生产发布，不能把合成测试说成当前failed批次已恢复。

最终完整回归：794 passed、10 skipped、198 subtests，20.32秒；相对部署基线新增44个测试案例。10个skip保持为9项可选MCP协议依赖和1个需锁定Superset运行时的认证模块；本轮没有在服务器重跑认证或通知发送。日志保留于任务4目录`coverage-tests-verified.txt`。
