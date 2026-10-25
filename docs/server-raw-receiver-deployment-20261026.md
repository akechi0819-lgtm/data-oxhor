# 固定三Excel接收/受限计算部署回执（2026-10-26）

用户已明确批准现有HTTPS凭据增加原始输入接收、批次状态及受限计算账号/目录权限。本次只部署到prepare；不切BI current、不新增日更、不停Mac bi-2、不恢复Grok，不扩大钉钉或生产发布权限。

## 已部署边界

- 外部POST `https://dashboard.apinova.cn/shadow-bi/v1/raw-batches`；外部GET `https://dashboard.apinova.cn/shadow-bi/v1/raw-batches/<batch>`。Nginx重写为内部`/v1/raw-batches...`，不能省掉外部`/shadow-bi`前缀。裸`/v1/raw-batches`为404。
- 复用现Bearer校验和现443/18091监听，不生成新token、不读打印token、不改SSH/防火墙；凭据文件inode/size/mtime不变。旧成品/通知接口保留。receiver只新增root-owned drop-in的固定代码目录、raw开关和两个收件目录写权限。
- `shadowraw`：UID/GID995、无登录shell`/usr/sbin/nologin`、无home，未加入shadowbi组。固定root代码`/srv/shadow-bi/raw-code`仅可读；服务User/Group均shadowraw、3GiB、2核、无swap、单次1800秒、禁止AF_INET/AF_INET6 socket。每次服务只处理一个计算批次，后续队列由path再触发，避免累计超时。
- `shadow-bi-raw-compute.path`事件监听队列；`shadow-bi-raw-compute.service`固定oneshot消费，只运行离线prepare，不接受请求指定程序、路径、SQL、发布或收件人。不使用新增日更timer。
- root前置步骤`raw_context`只从现current读取截止日与manifest摘要，投影至受控JSON；worker不获得现库/生产配置读取权，也没有current/releases写权。前置程序不接受队列参数，不读取通知或token配置。

| 路径 | 所有者/模式 | 用途 |
|---|---|---|
| `/srv/shadow-bi/raw-code` | root:root；目录755/普通代码644 | 固定代码，receiver/worker均不可写 |
| `/var/lib/shadow-bi/raw-inputs` | shadowbi:shadowraw 2750 | receiver收件；worker只读并冻结到私有区 |
| `/var/lib/shadow-bi/raw-pending` | shadowbi:shadowraw 2770 | 固定marker；锁660、marker640；坏目录只同父目录改隐藏名，不遍历内容 |
| `/var/lib/shadow-bi/raw-compute` | shadowraw:shadowraw 0700 | 私有日志、冻结输入、Snapshot与候选库；receiver不可读 |
| `/var/lib/shadow-bi/raw-status` | shadowraw:shadowbi 2750；状态640 | receiver只读白名单状态，无路径、库、hash、凭据或依赖异常文本 |
| `/var/lib/shadow-bi/raw-control` | root:shadowraw 750 | root策略/context；仅给shadowbi额外目录执行权，使其读取单独root:shadowbi 640的receiver-policy |
| `raw-control/baselines/verified-20261025-task3` | root:shadowraw，目录750/文件640 | 已验150文件基线的只读副本；原历史与原基线未改 |

`/var/lib/shadow-bi`只给shadowraw额外`--x`遍历权。服务命名空间ProtectSystem=strict，worker只允许写队列/候选/状态，receiver只允许写旧receiver区及新收件/队列；原父目录由shadowbi持有的权限不等于服务中可写current。

## 包、日期与幂等

普通未gzip TAR仅四个regular成员，不加目录项：`manifest.json`、`inputs/orders.xlsx`、`inputs/cash.xlsx`、`inputs/tencent.xlsx`。最大128MiB、三份必须齐全，仍有TAR及XLSX内部ZIP的路径/链接/条目/展开大小/hash门禁。

schema_version固定`shadow_raw_inputs.v1`；顶层字段固定`batch_id,company_id,as_of_date,data_through,bi_window,refresh_months,files`及schema_version。files是dict，键orders/cash/tencent；每项必需path/filename/sha256/size_bytes，filename是安全本地别名，不声称是源端建议名。可同时加`source_filename_unknown:true,source_filename:null`诚实声明原名未知；新pack默认如此，旧四字段形式仍兼容但不表示原名已知。下载工具只给UUID时，pack可自动使用安全的`orders.xlsx/cash.xlsx/tencent.xlsx`别名，不改变源字节。

10/26正式入口只接受as_of_date `2026-10-26`，data_through声明计算上限`2026-10-25`，bi_window是`{"start":"2026-04-26","end":"2026-10-26"}`，refresh_months是`["2026-10"]`。上海过午夜后旧10/25包仍拒绝，不能改日期冒充新采。来源最大日期与窗口请求、来源完整性分开：新采最大日期10/24不单独证明10/25完整或缺失；现有质量/业务截止门禁不会因此放宽，接收/排队不等于prepared，更不等于发布。

相同batch/相同TAR字节hash幂等；queued202、已有状态200；不同hash400。最多四个待处理（含活动标记）；满队列仍允许已接收同hash重放，不新增输入/标记。失败/超时/interrupted为终态，不自动重新采集或重构建；同batch重放只报告状态，维护恢复另走私有入口。GET只有已鉴权状态，不提供文件下载或目录浏览。

## 验收与仍待父Dot完成

- 完整核心回归750 passed、10 skipped、198 subtests；skip仍为9项可选MCP及1个认证模块，认证模块已另在固定Superset环境6 tests通过。旧成品/通知HTTP与shared_delivery/release_notifications回归保持。
- 实际服务命名空间：receiver不能读基线/计算私有目录、不能写代码/状态/current；worker能读基线而不可写，不能写代码/策略/current，不能读通知策略/receiver凭据，公网socket创建被拒绝。仅收件区中的上传字节是receiver必要读取范围，计算私有库/工作簿/日志不向receiver开放。
- 实际UID997的独立回环WSGI测试进程（非秘密fixture鉴权）写入真实新队列，实际UID995固定service消费合成坏结构Excel：在历史复制/业务计算前失败；同hash重放不重算，异hash/旧日期/路径脚本包拒绝。
- 真实service在终态落盘、清队列前被停止，删掉该合成批次的公开投影后重启：私有日志hash不变，状态恢复、标记消除，未重复计算。符号链接/FIFO/命令字段/坏目录攻击全部拒绝或隐藏隔离，未执行命令；该测试启动业务重构建数为0。
- 测试发现的跨绑定挂载及外属目录rename权限问题已修复为同父隐藏隔离，未加写权限；日志保留。watcher最终active/waiting，consumer空闲Result=success，未遗留临时暂停状态。
- 正式HTTPS未认证raw请求401、裸路径404、旧健康200及成品/通知未认证边界401均验证。**现Bearer正向上传由父Dot保管凭据执行**，隔离fixture鉴权不冒充现token正向贯通通过。

部署证据在`/var/lib/shadow-bi/warehouse-validation/raw-queue-deploy-20261026-task4/`的setup/activation/recovery-security-result等回执；候选3Excel计算旧批次的39表/612指标及来源/浮点差完整证明仍见前阶段回执。current始终`daily-20261025_184644t`。真实新采三Excel尚待父Dot投送；后续publisher接线、唯一生产者与仅保最新成品清理仍未授权/实施于本worker。
