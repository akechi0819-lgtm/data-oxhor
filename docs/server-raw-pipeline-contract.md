# 原始输入服务器候选链路

本合同属于2026-10-25固定脚本服务器化施工。候选代码不等于生产启用；`raw_receiver.register`没有被正式receiver调用，不新增密钥、不扩大现有token能力，不切current、不发通知、不改Mac bi-2或已停止的Grok。

## 输入与状态

`python -m dashboard_product.shadow_bi.p5.raw_inputs pack`仅接收BI工单、BI现金与腾讯完整工作簿三条明确路径。输出确定性普通TAR（XLSX本身已压缩），包含manifest和三个固定路径；不含DuckDB、39张成品表、配置、凭据或任意命令。dot可用现有采集能力取得Excel后运行该组包入口，服务器完成合并与计算；无需Mac计算39表。

manifest `shadow_raw_inputs.v1`字段固定：batch_id、company_id、as_of_date、data_through、bi_window、refresh_months、files及schema_version。截止日严格as_of-1；BI窗口使用现有`rolling_start_date`六个月规则，腾讯当月完整替换；每个文件绑定原文件名、SHA256、size。初版不开放调用方选择任意月份或更改默认业务窗口。业务端如需历史重放，由受信任维护者离线指定日期，与当天生产验收区分。

接收最多128MiB TAR、4个普通文件、单文件64MiB；拒绝路径穿越、绝对路径、反斜杠、别名、重复成员、链接、额外字段/文件、缺源、损坏hash、旧日期/截止日、跨公司和不符窗口。XLSX内部ZIP预检最多4096条目、每本展开512MiB、三本合计1GiB，并流式校验CRC；拒绝加密与符号链接。manifest最多16KiB、拒绝重复JSON键。完整暂存后原子改名，原件只读封存；同批相同TAR hash幂等，异hash拒绝，已存原件再校验。输入接收成功仅为`received`。

独立启用的HTTP适配只有`POST /v1/raw-batches`和`GET /v1/raw-batches/<batch>`，使用宿主提供的既有鉴权函数、服务器固定company/当前截止日、上海当日；请求不能提供服务器路径、命令、Snapshot ID或publish参数。最多4个待处理批次。响应只含批次/阶段/`published:false`，不暴露路径或配置。生产路由仍未注册。

## 离线服务器入口

`python -m dashboard_product.shadow_bi.p5.raw_compute prepare --received <已收批次> --baseline <明确基线工作区> --root <候选计算根> --company <固定公司> --minimum-cutoff <当前生产截止日>`。

入口对同一计算根持有非阻塞全局锁，冻结并重验TAR到worker私有目录，以独立工作区执行。复用`rebuild_bi_warehouse.rebuild(export_paths=...)`、`update_tencent_study_abroad.update(source_file=...)`和`refresh_daily(input_paths=...)`；原浏览器下载路径仍为默认。已有BI历史合并、腾讯月份替换、双Snapshot与联合回执不另写一套。更新仅发生在新副本；基线及原始封存不覆盖。

两源联合成功后经受控Data Platform读取quality.issues，存在问题即拒绝；再执行原`management.calculation.calculate`、原38关系与原build_radar投影。`library.build(server_complete=True)`一次生成39表及typed业务库，逐表归一化以避免将整个模型再复制为一个巨型JSON；计算和公式不变。门禁检查完整39表、截止日、逐表物理hash、业务库hash/内部批次/物理行数，以及可选同源39表完整逻辑摘要与612项指标对照。

状态写在原件目录外：`running → prepared | failed | timed_out | interrupted`；prepared含manifest hash与基线绑定。默认1500秒deadline，超时终止整个子进程组；上层systemd还应固定3GiB、2核、无swap、1800秒与独立临时空间。每次大落盘前需要至少5GiB可用（4GiB预算+1GiB保留）。prepared仍明确`published:false`；重复prepare重验封存与基线，失败批次不自动执行第二次。维护者可显式`--resume-sources`恢复已通过双源联合门禁的失败批次：重新冻结原TAR、核对基线输入及两源值hash后，只续算业务库，不重复采集或入仓；原失败state另存。源阶段未通过时使用新批次ID。进程异常后running标为interrupted，不猜成功。worker继承生产者锁，supervisor异常退出时仍阻止第二个重构建。

如业务库已完整封存、仅同源参考身份需要显式重绑，可由维护者离线调用`raw_compute recheck`：仅接受failed状态，核对原TAR/三源hash、基线输入、双仓配对、现有库/39表/612项指标后改为prepared，保留原失败state；不会重建。参考快照身份的调整必须单独记明字段和受控查询证据，不忽略业务字段，不改写原参考。

## 发布及仅保最新成品

候选library可以复用P4现有typed库/验版/激活能力，但本轮不调用生产activate。生产接线前必须完成：同源对账、实际隔离失败恢复、唯一生产者切换授权。所有生产发布须共用既有`/run/shadow-bi-receiver.lock`，锁内重新核对上海当日、正式current截止日与候选输入/双仓/39表身份，避免旧的成品上传与新原始输入抢占current。

失败只保证保住**当时仍存在的current**。现网历史成品及previous已按用户指令清理，不承诺不存在的历史版本回滚。拟接线时沿用P4“预检→暂停请求→原子切current→重新连接/更新页眉→真实业务烟测→失败切回切换前current”的过程。新版本验收成功且原子切换后，才能按明确无引用清单清理旧成品；原始历史、通知资产/去重状态、日志不在成品清理范围。不得按mtime猜保留对象，也不在此候选代码中自动删除历史。

## 集中确认的最小权限差异

现有token只允许固定成品接收及已批准通知。拟增加的仅为：向现有receiver注册上述两个固定raw路由；允许其写指定raw收件/队列目录；安装固定root-owned worker从队列读取三份Excel并在指定私有候选根计算至prepared。无需读取token、发新密钥、任意SSH、修改防火墙、任意shell/路径或自动通知权限。该扩权尚未执行；应由主协调线程集中向用户确认。自动生产切换及停用Mac旧生产者另需完成发布验收和明确协调，不能由raw接收成功自动推定获准。

### 拟申请的具体部署差异（未执行）

| 能力 | 固定范围 | 不授予 |
|---|---|---|
| HTTPS鉴权扩展 | 既有receiver及同一Bearer校验增加`POST /v1/raw-batches`、`GET /v1/raw-batches/<batch>`；现有HTTPS反代白名单仅补这两个路径 | 新token、新端口、任意SSH/命令/路径、文件下载接口 |
| 原始收件 | `/var/lib/shadow-bi/raw-inputs`：receiver可创建暂存/封存批次，worker只读；worker先冻结至私有区再解析 | receiver修改基线、计算代码、通知状态或current |
| 固定队列 | `/var/lib/shadow-bi/raw-pending`：receiver写固定batch/hash标记，worker读并消费；最多4批 | 客户端指定程序、工作区、日期策略、Snapshot、发布或通知参数 |
| 计算服务身份 | 程序安装至root-owned `/srv/shadow-bi/raw-code`；拟使用独立无登录服务身份，限定只读已批准的基线闭包、只写`/var/lib/shadow-bi/raw-compute`与`/run/shadow-bi-raw`；3GiB/2核/无swap/deadline | root shell、生产配置及通知凭据读取；不扩大现有BI Web进程对原始数据的权限 |
| 受信任策略 | root维护`/var/lib/shadow-bi/raw-control/policy.json`及明确基线指针，固定公司、当前截止日、基线与目录；receiver只得到日期/公司判断，不能从请求覆盖 | 调用方编辑Pack/Bridge、公式、月份替换策略或基线 |
| worker触发 | 安装一个固定队列consumer服务/触发器，只运行收件校验及`raw_compute prepare`至prepared | 自动切current、清理旧成品或发送钉钉 |

上述目录与独立服务身份的最小读写权限也属于需确认的扩展；本轮没有创建生产服务账号、ACL、路由或队列consumer。当前候选只提供适配函数和离线入口，并未安装常驻原始输入自动化。正式接线时需单独确认唯一生产者方案；Mac bi-2仍启用，Grok仍停用。


部署前尚须补齐并测试固定队列consumer（当前代码仅有路由适配和离线prepare入口），再安装一对固定raw队列path/service单元；不增加第二套定时日更。正式非root服务身份和目录ACL尚未创建/验证，不能把候选维护身份运行当作降权权限已验收。receiver只需读取`raw-compute/<batch>/state.json`状态，不应取得工作簿、库或私有日志读取权限；该精确状态文件权限须随consumer原子写状态一并补测。worker不授予生产current/releases、原成品发布队列或通知目录的写权限。
