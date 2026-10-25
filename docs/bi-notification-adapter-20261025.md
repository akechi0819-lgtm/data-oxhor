> 2026-10-25实际部署：通知代码25987199已部署到独立服务器版本，原5通道凭据和本机16条真实发送记录已迁入。服务器8消息/PNG/XLSX不发送验收通过，未发钉钉、未建日程。历史状态仅覆盖10月12—13日，尚未生成就绪证明；不得启用发送。完整回执见通知适配文档末节。

# 正式 BI 到钉钉的服务器适配（离线交验）

2026-10-25。用户已授权影响核查后实施本地可回滚适配。本轮不部署、不发送、不改调度、不读取/配置真实凭据、不迁移外部DeliveryState，也不启动完整原始数仓迁移。Grok全部例行以用户最新说明为已停止；Mac bi-2当前仍ACTIVE，不在此轮停用。

## 已采用的路径

`monitoring_product.release_notifications`从显式BI release的受控查询入口读取5张既有关系：periods、team_periods、facts、personnel_facts、target_roster_references。恢复自然月/绩效月的已计算团队与个人视图、两套逐笔事实和绑定花名册，复用既有`build_notifications`，不从看板截图、聚合人数相加或原始源表再造一套公式。

当前39表可以完整提供本批通知输入。重复登记的参考资料只有内容一致才合并，缺期间、个人事实、花名册或冲突参考时拒绝，不能补默认值。若未来release结构删减这些输入，应在同次权威计算中封存版本化通知产物并重新验收，不回退到旧仓/历史消息。

个人通知的当日新增、个人工单/现金流水与副线流水明确使用personnel_facts；团队指标、团队流水及未分配签约对账仍使用原经营事实。计算入口同时传入person_facts。个人资格、原5通道/8消息及固定自然月/绩效月窗口不变，不扩展收件人或人员名单。

## 版本与发送合同

构建输出为私有不可变通知包：bundle.json、shared_result.json、notifications.json和受控查询证据。绑定release_id、业务batch、双Snapshot、as_of、as_of-1业务截止、业务库摘要、完整来源binding摘要、Pack/Bridge摘要和通知实现/依赖摘要。来源业务规则和本次通知修正规则分别绑定，不伪称修改后的通知源码属于旧release的计算版本。

发送前对照实际current所指release及完整元数据，核验业务库、通知文件和查询结果/回执摘要；旧release、过期数据、规则变化或任一来源不一致时拒绝。每条HTTP尝试前再次检查current指针和manifest，批中切版则余项保留pending。通知只消费正式版本，不消费待验候选。

命令默认只预览：

```bash
python3 -m monitoring_product.release_notifications build \
  --library <明确release>/library --batch-id <明确业务batch> \
  --release-id <明确release_id> --output-dir <新的私有通知包目录>
python3 -m monitoring_product.release_notifications deliver \
  --bundle <通知包>/bundle.json --current-release <正式current指针> \
  --output-dir <新的预览目录> --state-dir <持久状态目录>
```

默认不读取凭据、不上传、不发送、不创建状态；历史通知包只能作预览，真实发送仍必须是上海当天、数据严格截至昨日。构建与预览不是发送成功。`--send`才进入正式投递，且必须通过下述全部门禁；本轮从未对真实来源使用该参数。

## 原状态与幂等

新服务器入口不自动创建空发送历史。必须由后续明确授权的受保护迁移提供：

- imported_state.json：原Grok发送状态的冻结导入副本。
- shared_delivery_state.json：活动状态，初始包含导入记录。
- delivery_origin.json：schema_version为delivery_state_import.v1，source为grok，sha256为冻结导入副本摘要，channels为排序后的原5通道安全标识。

没有这些文件、导入摘要不符，或活动状态丢掉/清除了原sent、sending、unknown记录时禁止发送。门禁在读取真实凭据前执行，并在持有既有状态锁时复核。本模块没有创建迁移证明或导入外部状态的命令；不能用合成测试空状态替代真实历史。

复用现有日期/通道/message_id去重、原子状态写入与锁。已sent同日不因新run再发；上传/资产失败停在pending可续跑；HTTP超时或结果未知停在unknown，崩溃留下sending也阻断重发，其余安全消息分别继续。未知结果需后续人工核实，不能自动清状态。旧shared_delivery仍为兼容底层，不作为新的调度入口；接管必须使用带release与迁移门禁的新入口。

## 资产、链接和凭据

新入口使用明确的服务器本地资产目录，验证原5通道/PNG/XLSX白名单后原子安装到独立随机路径，不再要求服务器SSH自己，因而无需为通知任务配置SERVER_PASSWORD。原SSH运输仍留给历史兼容调用。

通知中的看板链接改为统一原生BI地址，不附加失效的旧HTML页面或未经验证的团队定位参数。当前不承诺自动选中团队标签；消息、图片、表格和流水内容不因链接变化改变。

后续服务器需补齐monitoring_product及其受控查询/既有规则依赖、中文字体，设置私有通知包目录、持久状态目录及原notify资产目录的最小写权限。PNG/XLSX和不可猜路径沿用现有发布边界；不新开匿名业务明细接口。

原5群webhook与可选签名secret只能在受保护配置中按原映射交接，不能贴到聊天、Git或普通报告。Dot只保留采集/投送凭据，不需钉钉凭据。当前真实群映射、原DeliveryState及服务器通知权限尚未交接，本轮没有因此形成持续访问。

## 离线验证与限制

真实离线样本为daily-20261025_184644t，对应BI snapshot_bi_operations_20261025_114521、留学snapshot_study_abroad_20261025_184644，业务截至2026-10-24。查询库摘要与现网该版上游数据库摘要一致；查询有显式batch/run和回执，不直连客户原始仓。

用冻结calculated/public.json、原绑定花名册和同批受控事实，运行保留的旧通知实现作为参考；新适配重组已封存的期间/团队视图，8条消息逐字段比较均无差异。当前两套事实在通知窗口恰好相同，因此另用合成“只在个人源存在的合资格工单”证明个人当日/流水正确补入且团队、原群范围不扩大。

8份真实PNG均经Pillow打开校验，8份XLSX均经openpyxl打开校验，看板链接均指向原生BI，预览未创建状态。新合成回归覆盖缺旧状态/导入摘要错、过期、来源或规则不一致、通知/查询结果损坏、重复调用、资产失败续跑、未知HTTP不重试、部分成功继续及批中切版；发送层全mock，HTTP被禁止。

仅一个真实日期样本；未实际向钉钉发送，未验证群机器人IP/签名/接收行为，未做服务器实际渲染/磁盘权限或2GiB环境负载验收，也未完成每日调度/第三日观察。不能把本轮离线通过写成自动推送已上线。

启用前仍需原群映射与受保护凭据配置、原状态迁移及目录权限授权；用户目标为每天推送，具体时点和周末是否沿用同消息规则待启用前确认。先验证Dot→服务器发布及通知闭环，再切换Mac bi-2；不恢复Grok旧任务。

## 最终本地结果

- 全量核心回归646 passed、180 subtests passed；11 skipped为9项缺可选MCP SDK协议测试和2份Superset专用测试模块。后两模块在既有固定Superset环境另外执行认证6项、receiver5项，共11项全部通过；9项MCP协议测试本轮未补测。
- 新服务器适配12项合成测试全部通过，没有将导入的旧测试重复计数。现有管理/监控初查203项、77子测试通过。
- 最终隔离包offline-bundle-v2由最终实现摘要构建，八消息逐字段对比均0差异；8组真实PNG/XLSX可打开，统一原生看板链接存在，dry-run状态目录未创建。
- 本地证据位置：本任务工作目录notification-adaptation/，包含backup、final-tests.log、superset-tests.log、adapter-tests.log、eight-message-parity-v2.json、asset-verification-v2.json、verify_offline_v2.py及隔离通知包。客户通知产物和查询证据不进入Git或Library。
- 恢复基线为eb3fd387，四份原代码另有逐文件备份。本轮提交只在c373施工分支保留，main与现网正式基线未因通知适配再次推进。
- Mac bi-2仍ACTIVE且指向c373：后续执行会读取该树源码，但本轮没有触发它或新增通知调度；P5尚未调用新的服务器通知入口，不会因本次源码提交自动发钉钉。

## 2026-10-25 用户批准后的部署约束

用户已批准从本机同一项目迁移原5通道凭据及真实发送记录，设置最小目录权限，并计划每日北京时间10:00含周末；日程由主线程统一创建，本模块不安装cron或timer，不临时试发。凭据来源为本机主工作树的既有受保护文件，不从Grok读取。

新增固定入口`monitoring_product.server_notify`和root固定脚本`deploy/run_server_notify.sh`。专用无登录账号读取明确current的两个派生库文件；包、渲染及状态写入隔离目录，notify资产目录仅授予创建所需权限。每次由固定入口启动有内存/CPU限制的临时进程，不创建重复任务。模式为status、preview、send-scheduled；只有上海10时窗口、当天正式release、完整状态门禁通过才允许发送，默认preview不读凭据也不发送。

本机找到16条真实sent记录（10月12日、13日各8条），10月13日的8条与原发送回执日期、通道、状态及run一致；该回执未保存逐消息摘要，不能声明独立核验了摘要。已知记录不覆盖10月14日以后的切换历史，原状态仅可作为待补证迁移，不得因此创建ready的delivery_origin.json。状态来源合同新增local-project，保留旧grok标识兼容；本次不访问Grok。

本机5个规范通道均有互不相同的官方DingTalk端点及签名配置，迁移时只复制这些字段与既有notify域名，不复制SSH口令或其他配置。实际群显示名/机器人当前状态未通过只读接口反查，不能把变量名当成新的群身份核验。

整合到main的是已验收本地代码，实际服务器部署使用独立版本目录，既有BI源码、current数据、认证、SSH及防火墙保持原状。部署回执和资源/状态门禁结果以本轮最终交付为准；有状态覆盖缺口时禁止主线程启用日程。

首轮真实服务器preview在专用768MiB cgroup内OOM，现网BI未重启/current未变。根因为Data Platform证据file_ref/resolve_file整读约802MB数据库后算摘要；已改为1MiB分块流式校验，仍逐字节验证SHA和大小，并拒绝哈希期间文件变化。补充大文件禁止整读、等长篡改和流中修改回归；修复后全量652项/180子测试通过。没有扩大内存限制、增加Swap或放宽证据门禁。服务器重试及结果单独留回执。

## 服务器实际交付回执

代码版本259871999d57652a389bd75e6747519ba886afda，纯源码归档SHA256 c1be1fb802160c36880ce813b994c1b8d2a55bbb2b491f03f9e3d54872ca7e0c；部署到/srv/shadow-bi-notify/releases/对应版本，current仅为通知代码指针。main/c373代码已对齐，后续此回执提交仅改文档，不改变已部署实现摘要。先前1d8429db版本保留作为通知代码回滚点，源备份在/var/lib/shadow-bi/backups/notify-migration-20261025。

使用无登录shadowbi-notify专用账号；只读当前派生业务库，不能写库、不能读BI/receiver凭据及原htpasswd；notify目录只授予创建权限，不能列目录。通知配置为root:专用组0640，原5通道与签名字段来自本机指定项目，未迁入SSH口令。真实群显示名和机器人在线签名行为未独立验证，未临时试发。

原状态16条（10/12、10/13各8条）逐字节迁入，SHA核验与本机原件一致，active副本在dry-run后仍完全相同；未创建delivery_origin.json，不得将两天记录当成10/14以后的完整覆盖。需要补齐本机后续记录；若无记录，须用户另行明确切换日起点与历史缺口处理，不自动补造就绪证明。

服务器实际preview：180.268秒业务耗时，/usr/bin/time总耗时181.71秒、峰值RSS298048KiB，768MiB限制不变。8消息与冻结参考逐字段摘要一致；8份XLSX所有表/单元格逻辑摘要一致；8张PNG可打开，链接均指统一原生BI。源/双Snapshot/current完全一致。第一次整文件读造成的通知cgroup OOM保留为失败证据；现网BI NRestarts=0、ActiveState=active，数据current仍daily-20261025_184644t。

最终代码核心回归652 passed/180 subtests，11 skipped与独立Superset11项覆盖关系保持前述说明。没有服务器临时真实发送、机器人验签、计划触发或云端可达性验收。未安装cron/timer，专用systemd进程均为按需临时作业。

安全调用入口：/usr/local/sbin/shadow-bi-notify status（当前预期blocked，退出2）、preview（不发）、send-scheduled（仅上海10时窗口、当天正式数据及迁移门禁均通过才发送）。使用既有受保护连接调用，不在参数里传webhook或密码。并发忙退出75；partial/blocked退出2；成功preview/sent退出0。状态不完整前主线程不得启用日程。云端日程到此入口的安全触发通路尚未验收，不能把Mac SSH成功当成Dot直连成功。

恢复时先保持发送停用；只切通知代码指针/固定入口，保留全部原状态、后续sent/unknown及已发布资产，不清空去重，不恢复Grok旧任务、不回退BI数据。专用目录/账号和ACL的恢复只作用于本轮新增范围，原现网配置及源文件保留。

数据迁移分工：本线程只完成过本地源体积/指针只读盘点，没有创建数仓候选目录、没有原始仓上传。独立数仓线程负责。最后一次只读磁盘余量5654388736 bytes（约5.27GiB），是该核验时点，不代替另线程传输前实查。

证据保存在本任务notification-deployment目录：server-preview-streaming.log、server-verification.json、verification-summary.json、migration-audit.json、streaming-fix-tests.log、superset-tests.log。凭据临时传输副本已清理，原本机配置/状态及受保护服务器副本保留；未上传Library。


## 原 HTTPS 接口固定通知扩展（用户已批准，部署验收另记）

用户确认沿用原五通道标签，并批准为现有 receiver 与现有凭据增加固定通知能力；从2026-10-26起、北京时间每天10时（含周末），不补2026-10-25及更早消息。原16条真实发送记录保留；10月14—25日历史仍有缺口，不声明历史完整。切换证明明确history_complete=false及no_backfill=true。证明与冻结原件位于root拥有的state-origin目录，通知进程只读；活动状态继续原子更新，不能清空sent/unknown。

复用https://dashboard.apinova.cn及原18091 receiver/Bearer摘要校验，无新密钥/监听端口/任意SSH命令。Nginx仅增加同一服务的通知前缀；通知事件.path消费固定队列，不是日历调度，不安装timer/cron。新功能启用旗标为SHADOW_RECEIVER_NOTIFY_ENABLED=1，缺少受保护切换策略时失败关闭。批次发布队列及数据回滚独立，通知失败不回退已发布数据。

- GET /shadow-bi/v1/notifications/status：返回正式release、as_of_date、data_through及切换策略，不读机器人凭据、不发送。
- POST /shadow-bi/v1/notifications/jobs：仅JSON operation（preview或send-scheduled）、expected_release、as_of_date，可选retry布尔。拒绝命令、路径、收件人及未知字段；请求上限2048字节。
- GET /shadow-bi/v1/notifications/jobs/<job_id>：查询异步固定任务回执，无消息正文、凭据或内部资产路径。

示例请求（Authorization由调用端既有受保护文件注入，不写入脚本/日志）：

```json
{"operation":"preview","expected_release":"daily-20261025_184644t","as_of_date":"2026-10-25"}
```

接受返回202及{job_id,status:queued,deduplicated:false}；相同操作/release/日期具有相同SHA256 job_id，重复不执行。查询返回queued/running/dry_run/sent/partial/blocked/unknown，含attempt、retryable、源批次/双Snapshot、截止日及计数。401无有效鉴权；400合同字段错误；403起点前或上海10时外发送；409旧release/日期/截止日或不允许重试；413超限；423缺少迁移证明；429队列满；503功能或控制文件不可用。仅partial中pending>0且无unknown/sending可显式retry:true，最多3次；preview失败也可明确安全重试。进程异常时可能已发送的任务记unknown，禁止自动重放。底层逐消息仍持久去重，部分发送的sent保留。

两层独立复核当前release、上海日期、昨日完整截止日及切换起点；实际发送继续校验双Snapshot、Pack/Bridge及规则摘要，逐消息重新检查时间和current。构建跨出10时窗口也不能发送。固定执行器参数只有枚举、受限release和ISO日期，不接收外部命令/路径。资源限制768MiB、CPU75%、最长600秒；独立根执行器只承担预定义ACL与身份切换。

原last_published/last_published_hash/last_failed状态文件最小修正为root:shadowbi0640，并由固定发布脚本原子写入；不放宽receiver摘要凭据、BI认证或数据写权限。主线程待Dot用已有受保护token完成真实鉴权GET/preview/拒绝验证后再建立每日10:00自动化；Mac SSH成功不能代替该验收。本线程不临时真实发送。
