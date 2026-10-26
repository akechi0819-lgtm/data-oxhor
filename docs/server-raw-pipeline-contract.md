# 原始输入服务器链路合同

本合同以本地 `main` 源码为准。既有接收/受限consumer及固定publisher的服务器部署分别见 [10月26日接收回执](server-raw-receiver-deployment-20261026.md) 和 [固定发布回执](server-raw-fixed-publisher-20261026.md)。来源完整性验证在本轮本地整合，尚未部署；历史数仓基线、双Snapshot与聚合计算已经迁入服务器，并已有真实三Excel批次跑到39表构建。此前该raw批次在截止日门禁失败，不能把该批失败误写成数仓/聚合尚未上服务器。prepare不自动发布，持续日更与唯一生产者安排须按独立回执核对。

## 输入与状态

`python -m dashboard_product.shadow_bi.p5.raw_inputs pack`仅接收BI工单、BI现金与腾讯完整工作簿三条明确路径。输出确定性普通TAR（XLSX本身已压缩），包含manifest和三个固定路径；不含DuckDB、39张成品表、配置、凭据或任意命令。dot可用现有采集能力取得Excel后运行该组包入口，服务器完成合并与计算；无需Mac计算39表。

manifest `shadow_raw_inputs.v1`字段固定：batch_id、company_id、as_of_date、data_through、bi_window、refresh_months、files及schema_version。截止日严格as_of-1；BI窗口使用现有`rolling_start_date`六个月规则，腾讯当月完整替换；每个文件绑定原文件名、SHA256、size。初版不开放调用方选择任意月份或更改默认业务窗口。业务端如需历史重放，由受信任维护者离线指定日期，与当天生产验收区分。

接收最多128MiB TAR、4个普通文件、单文件64MiB；拒绝路径穿越、绝对路径、反斜杠、别名、重复成员、链接、额外字段/文件、缺源、损坏hash、旧日期/截止日、跨公司和不符窗口。XLSX内部ZIP预检最多4096条目、每本展开512MiB、三本合计1GiB，并流式校验CRC；拒绝加密与符号链接。manifest最多16KiB、拒绝重复JSON键。完整暂存后原子改名，原件只读封存；同批相同TAR hash幂等，异hash拒绝，已存原件再校验。输入接收成功仅为`received`。

独立启用的HTTP适配对外只有`POST /shadow-bi/v1/raw-batches`和`GET /shadow-bi/v1/raw-batches/<batch>`（内部Flask为`/v1/raw-batches...`），使用宿主提供的既有鉴权函数、服务器固定company/当前截止日、上海当日；请求不能提供服务器路径、命令、Snapshot ID或publish参数。最多4个待处理批次。响应只含批次/阶段/`published:false`，不暴露路径或配置。部署启用取决于root维护的固定配置；代码合并不启用任何路由。

## 固定队列与计算身份

现有receiver可写 `raw-inputs` 收件与 `raw-pending` 固定batch/hash队列；受限、无登录的 `shadowraw` consumer 从私有冻结副本计算，只读指定基线，仅写候选、日志和白名单状态。receiver仅读取 `raw-status` 脱敏投影，不读取私有工作簿、业务库或审批。公司、目录及基线由root-owned `raw-control/policy.json` 固定，HTTP不能覆盖。固定path/service为队列触发，不是第二套定时日更。

`raw_compute prepare` 在非阻塞生产者锁内重验TAR；来源完整性预检缺失/无效即 `coverage_unverified`、`published:false`，不复制历史、不导入双仓。证明与封存决定的合同见 [来源完整性](server-source-completion-candidate.md)。通过后才复用现有BI六个月历史合并、腾讯当月完整替换、双Snapshot及联合门禁，数据更新仅发生在新副本。

两源联合成功后经Data Platform受控读取quality；存在问题即拒绝。共同业务计算和 `library.build(server_complete=True)` 一次生成39张封存表及typed业务库，含radar_people，不重复旧P3补投影。门禁校验截止日、同一完成证明、39表hash、业务库身份/物理行数，以及可选同源逻辑摘要和指标对照；不修改Pack/Bridge或事实。

状态为 `running → prepared | failed | timed_out | interrupted`，或预检直接 `coverage_unverified`；prepared仍是 `published:false`。默认计算deadline1500秒，超时终止子进程组；固定服务约束3GiB、2核、无swap及1800秒。大落盘前需5GiB可用（4GiB预算+1GiB保留）。worker继承生产者锁，supervisor异常退出不允许第二个计算并行。

同批同hash幂等，异hash拒绝，failed或未验证不因HTTP重放自动重算。维护者可显式 `--resume-sources` 续算已通过双源门禁的失败批次，保留失败state并校验原输入/基线/双仓，不重复采集；必须有当前完成证明。`raw_compute recheck` 仅对已有封存failed候选做离线复验，不重建；缺少原封存decision或相同证明的旧候选不能恢复为prepared。不得调整参考身份来掩盖业务差异。

## 固定发布请求

`POST /shadow-bi/v1/raw-batches/<batch>/publish-prepared` 仅接受空对象 `{}`，沿用既有Bearer，无路径、命令、SQL、日期策略、收件人或跳过门禁参数。只对prepared排队，受限计算账号没有current/releases、服务控制或通知配置写权。发布公开状态为 `publish_queued`、`publishing`、`published` 或 `publish_failed`，最终回执幂等。

root固定publisher与旧成品publisher共用 `/run/shadow-bi-receiver.lock`，同时持有raw生产者锁；锁内核对请求时的正式current hash、上海当日、三输入、双Snapshot、quality、39表及完成证明。本地新合同在P4重建、下一批基线预检后且切current前再次复核证明和manifest，撤销/变化就拒绝激活。然后复用P4原子激活、真实HTTP及三范围18指标验证；失败恢复操作开始时仍存在的current，不承诺已不存在的历史previous。

新版本实际验收成功后才晋升下一批只读基线，清理确认无current、活动FD或Nginx引用的旧release/同名incoming；仍有引用时记录cleanup_pending。原始输入、历史源仓、通知资产/去重状态及日志不属于成品清理范围。原初始历史基线保留，只清已被新基线替代且满足固定范围的派生基线。

## 生产边界

本地整合不安装审批文件或新代码，不改服务器服务、凭据、日程及通知。Mac `p5.daily` 直接SSH发布不受receiver锁保护，共同锁只能防同一锁内并发，不能保证旧生产者不会先后覆盖；唯一生产者安排仍须单独验证。10月26日手动Mac日更成功不算Dot/server全程脱机成功。

正式raw新包仍需真实来源完成证据、服务器新代码/权限验收、同源核对、实际HTTP及失败恢复和唯一生产者切换。严格完整未验收就不更新、不发送旧版，不提供按可用日期降级开关。既有通知日程与BI采集/发布调度分开核对，不从Git合并推断接管完成。
