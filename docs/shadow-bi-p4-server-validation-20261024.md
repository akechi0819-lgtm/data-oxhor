# P4 服务器影子部署与验证回执（交总线程验收）

施工聊天：01a1699d-dc66-77f0-b128-e4fb67cee004；模型GPT-6.1 Sol / Medium。
源目录已实核为c373，分支codex/shadow-bi-plan-20261022。仅P4。本施工回合证据已交付；P4尚未整体验收通过，保留学校P95、冷首屏两项性能例外，以及旧站正常Basic登录后的浏览器呈现待用户操作。未启动P5、未开通真实三人灰度。

## 首次写入前确认范围

2026-10-24以用户授权服务器的SSH实读：Ubuntu24.04、2核、1967MiB内存、无Swap，磁盘剩余21GiB。现有Nginx监听80/8080/8081，旧看板HTTP位于dashboard.apinova.cn、/var/www/dashboard/current，无现成PostgreSQL或容器运行时。

新增独立/srv/shadow-bi源码与环境、/var/lib/shadow-bi私有数据/应用状态、shadow-bi systemd服务、loopback18090；安装独立PostgreSQL元数据库，单Gunicorn worker/三线程并限制DuckDB内存。服务器业务库由明确清单的封存业务表JSONL及类型/来源manifest确定性重建，逐文件SHA、批次及行数校验后发布，不上传整个客户工作区/审计目录。保留源表和构建程序以便重建；P5再接现有原始采集链路。

正常浏览器入口需HTTPS；先测试现有域名的TLS与DNS，按现有主机增加独立TLS入口，不停旧HTTP服务。新数据没有Nginx静态映射。正常发布、切批、失败保持旧版、配置备份恢复及回滚只作用于独立影子服务；不触碰旧任务/钉钉，不启用P5定时任务。

## 当前证据

私有目录：.local/audits/shadow-bi-p4-20261024/。server-inventory.txt为实际配置盘点；packages.log为安装记录。本阶段仅临时测试阅读账号，真实三人开通由总线程后续落实，不发送邀请。

## 施工中发现与修正

- 第一轮Superset CLI缺rich，已按既有requirements-p1补齐；服务器锁定版本会另存pip freeze。
- 普通SQL LIMIT1元数据探测会先展开整份学校数组，256/768/1100MB分别发生OOM或无法落临时文件。现改为仅字段探测时外层WHERE FALSE，完成后恢复真实SQL；业务SQL本身不加空过滤。
- 团队大JSON的查询先裁剪实际引用顶层键，学校父/子源行复用P3.5已验证的select-list UNNEST模式，避免lateral连接反复携带大父JSON。与传输包中的P4前SQL在相同封存库对比45条变更查询、13,651行全默认输出，逐列逐值摘要一致。证据projection-comparison.json；服务器随后原生176请求/90检查、平台113/24、渠道40/16完整回归通过；更晚的学校HTML优化须另作同覆盖回归。
- 只读数据库的临时文件改落应用私有可写目录，设置2GB临时文件上限；业务仓仍只读。未增加Swap或购买资源。
- 实际HTTPS测试已核三范围指标、阅读角色必要元数据访问、SQL Lab/原始facts/编辑拒绝、匿名数据拒绝，共11项；真实BI引擎另对文件读取及写表执行拒绝验证。元数据列表200本身不当作越权，检查不泄露管理员秘密且没有DML/SQL Lab能力。失败的400来源头测试不计通过。
- 总线程指出比例字段被金额通用格式覆盖；已保留已有百分数格式。浏览器看到45.4%/42.3%/57.9%，原始比例不变。原生NULL有dt-is-null标记，样式统一显示—，SQL NULL及数值排序保留。
- 1512px窗口下原CSS隐藏“更多筛选”导致排序不可达，已恢复原生溢出入口，实际能展开ROI及方向选项。无新增前端查询循环。

## 已完成的运行演练与待完成项

- 两份真实不同截止数据：A语培截至10月21日/留学10月22日；B由已有原始输入按10月19日截止重新构建。A→B、B→A均比较真实应用引擎批次、页面日期和三指标当期/同期六数；旧A浏览器在切B后原生请求被409拒绝并自动重载到B。不是复制改名，也不计作P5连续日更。
- 无效校验和预检在停服务之前失败，指针/进程不变；发布后主动模拟烟测失败，自动恢复A，六数重新比较一致。
- 独立元数据库与配置实际改动后从备份恢复，环境文件摘要和仪表盘描述均还原，恢复19.580秒；服务重启恢复16.739秒，复核批次和六数。仅验证服务重启和开机启用，未重启整台主机。
- 首轮有效三会话：903.279秒、733次真实图表请求、0失败、OOM和服务重启增量均0；P95=3.942秒、最大5.280秒，内存峰值1,445,007,360字节。稳定性通过，3秒性能目标未达；完整原始记录另存load-3-clients-baseline.json，不能用0错误代替性能通过。
- 慢请求集中在学校树。第一候选改为list_transform拼装HTML，15组合内容一致，但完整回归与双panel页同时执行时内存失败，触发服务重启；已回退旧HTML拼装，失败记录vector-full-regression-final.log、总线程parent-school-vector-oom.txt/png，不能用内容一致宣称该候选可用。
- 第二候选保留旧HTML拼装，裁剪父学校/团队JSON、提早按固定业务线过滤；原生176/90、平台113/24、渠道40/16通过，真实学校双panel/年级展开及排序经过总线程复验。但完整903.247秒负载738请求仍P95=3.623秒，学校单视图P95=4.122秒，峰值1,306,537,984字节，OOM/重启增量0；有1次401（Token has expired），按失败保留在load-3-clients-pruned.json，未剔除。
- 当前第三候选在上述裁剪基础上，使用DuckDB已有json_transform一次解码学校/年级指标，再用数组操作拼装相同HTML，不增加业务表或基础设施。原始父/子列12组合17,012行、完整HTML15组合7,171行均同批逐值/多重集一致，明确回执见typed-source-comparison.json、school-typed-vector-comparison.json。固定业务线先过滤使3组隐藏名次重新编号，默认父工单值序列一致，实际各字段升降序另验。此前仅数组拼装的OOM不作为当前组合通过依据；当前组合已新做真实双panel和双重展开（server-school-typed-expanded.png、server-school-typed-grades.txt）。
- 负载客户端发现900秒JWT令牌到期边界；仅测试客户端改为每600秒同阅读账号续登录，服务器令牌与权限不变，原401记录保留。真实浏览器本轮继续使用已有cookie做筛选/展开，未重新登录；不能把API令牌到期等同于浏览器cookie失效。新报告明确记录续登录次数、四视图请求形状、force/初始与稳态策略及每视图P95；任何单视图超过3秒仍判失败。
- 服务器冷页面实测：计时从新开/p3/前开始，到17,858,997.40和14,591,849.65两条主经营现金DOM同时可见结束；已有阅读者cookie、浏览器静态资源缓存保留，服务重启后仅health探测。原10.384秒，批量元数据加载后8.488秒，最终轻量选项来源版8.385秒（first-screen-cold-options.json），未达到5秒目标。结果不能由API最大耗时替代，也不声称全空浏览器缓存。deferred-data和HTTP2没有证实收益，均已撤回。
- 元数据实测88个数据集原生序列化285条SQL/2.555秒，现有SQLAlchemy selectinload批量关系加载26条/1.195秒，序列化内容SHA完全相同（metadata-prefetch-profile.json）。局部装载钩子位于p4/extension.py，只改变装载方式，原生DAO鉴权和序列化保留，不改site-packages或增加缓存。期间/管理单元/目标团队三个下拉框改读现有维度列/原有限枚举，17/3/3个选项与原经营SQL逐项一致；p35/bootstrap_native.py可重复建立，修改仅target datasetId，scope/default等不改（overview-option-targets.json）。真实9月市场总计1714单/3,469,973.80元/230人、线上虚拟人38单/64,819元/4人与同批查询一致；目标团队线上不改变经营主表，见server-options-*.txt/png。
- 当前候选受影响原生176请求/90检查与11项读者边界通过（api-20261023T191906.990531Z、typed-regressions/）；当前读者允许集141个数据集，原始facts仍禁止。总线程独立复验本候选学校双panel、双层展开、排序及三个轻量选项控件通过。
- 最终完整负载902.897529秒、752次业务请求、0失败，3次同用户续登录，OOM/服务重启增量均0，内存峰值968,482,816字节；整体P95=2.535563秒、最大3.878558秒。四视图各188请求，P95分别为经营1.489049、平台1.497778、学校3.031601、产能0.785389秒；每视图3秒门槛下学校仍超31.6ms，脚本按预期exit1，没有四舍五入宣布通过。完整原始记录load-3-clients-typed.json，汇总load-typed-summary.json，服务端同名副本和load-progress-typed.jsonl保留。
- 覆盖仅上述四个默认视图、既有筛选/真实排序/50行请求，三独立会话共用临时阅读账号，不等同真实三人试用或所有筛选组合压测。每会话首次四次强制查询，此后每四次强制一次、其余沿用60秒原生缓存，三秒思考间隔；请求形状、force次数、初始/稳态标记及所有错误均保存。额外登录请求不计业务请求数，计入900秒实际墙钟。
- [DuckDB JSON函数](https://duckdb.org/docs/1.5/data/json/json_functions)提供现有单次解码能力；缺失/失败数值转NULL的既有语义已由同批17,012行源值比较另证，不增加业务规则。仅由总线程决定是否接受学校P95=3.031601秒及冷首屏8.385秒的明确例外；未自行开始P5。

## 运行入口与恢复范围

- 新看板入口：https://dashboard.apinova.cn/p3/；旧HTTP静态入口及401认证保留，旧Nginx主进程仍为413196。原HTTP vhost唯一P4差异是ACME验证路径；最后TLS路由修正时其SHA再次确认未变。
- 收尾真实浏览器发现默认一年HSTS会使旧HTTP链接进入HTTPS/Superset404；已发max-age=0撤销本次默认策略，仍有客户端自动升级行为，未绕过浏览器保护或追查其受限内部状态，无法确认缓存/父域/HTTPS-first细分。最终在HTTPS严格镜像原18个静态文件、原root/Basic realm/htpasswd及两条既有通知token规则，旧root/healthz优先，新应用只代理已确认路径；没有扩大旧文件白名单、创建或发送通知。旧HTTP配置与master未变。配置源p4/nginx.conf、p4/config.py，差异和部署记录nginx-legacy-candidate.diff、install-legacy-routes.log。
- 18文件HTTP/HTTPS/源文件SHA全部相等，凭既有C账号认证200、匿名401，manifest/.env/业务库/任意私有路径404；证据legacy-http-https-content.json。HTTP认证探测通过SSH在loopback+原Host完成，不把旧密码以HTTP发过公网，不上传密码本/改认证。浏览器旧HTTP healthz即使升级HTTPS也实际显示ok（old-health-restored.txt）；新p3仍显示两主经营现金且静态资源正常（new-after-legacy-routing.txt/png）。旧四页浏览器因工具不能完成正常Basic对话框，呈现须用户用原账号正常登录后确认；合法凭据的HTTP正文一致性不能替代这项实际浏览器验收。新增HTTPS vhost在/etc/nginx/sites-available/shadow-bi。
- 最终900秒后仅修复响应升级头、Nginx旧入口路由及受保护资源的既有登录跳转，未改业务SQL、角色或数据；code-sha256-benchmark.json保留负载时源码摘要。相对负载版本实际变化为p4/config.py、p4/nginx.conf、p4/extension.py三文件。
- 源码/srv/shadow-bi/code，Python环境/srv/shadow-bi/venv，独立PostgreSQL库/角色shadowbi（Unix socket peer），应用用户shadowbi。配置/etc/shadow-bi.env为0600，密钥在服务器生成；读者登录测试凭据仅在私有audit中，不写本文。
- systemd shadow-bi：一个Gunicorn worker、三线程，loopback18090、MemoryMax1400M；真实业务只读、外部文件读取关闭，临时溢出仅落/var/lib/shadow-bi/app/home/duckdb-tmp，上限2GB。原始封存表仅root可读，业务库无静态目录映射。
- 数据目录/var/lib/shadow-bi/releases，current/previous为明确版本链接。rebuild.py从显式表清单与类型重建39张表，核验每表文件SHA/字节数/行数；数据库物理SHA重新登记，保留上游SHA与来源合同，不伪称物理文件逐字节相同。
- activate.py在预检后通过/run/shadow-bi-maintenance暂停外部请求，排空旧进程，切链接，刷新页眉，启动新服务；内网真实应用引擎验批次、读取页眉及三指标当期/同期共六数，成功后开放外部入口。失败自动恢复旧链接、旧页眉、进程并再次对旧批次比较六数。不是仅/health通过。
- 页面将固定版本写入原生请求头；旧页跨版本请求返回409并自动重载，避免新旧多图混用。停接期间HTTPS实读503；旧HTTP health仍200。仅为版本门禁，没有另建业务取数循环。
- backup.sh保存独立元数据库dump、env/systemd/Nginx配置和当前版本身份与SHA清单；restore.sh只恢复这些独立资源，并还原current指向。恢复及重启后仍须运行capture/verify_server验证实际数据。维护失败后若标记仍在，不可盲删；先恢复独立服务并验版再解除标记。
- configure_host.py为首次角色、目录、密钥配置；initialize.py创建操作管理员；bootstrap_native.py建立原生配置；readers.py仅创建临时测试阅读者。三位真实用户不在本阶段创建，由总线程按已确认名单落实。


## 交付与剩余决定

- 最终收尾核对：匿名访问/p3/assets/01-avatar.png现为302转既有/login/、登录页200；正常表单登录沿用next回到原生看板，已登录/p3/及受保护PNG均200。修正为login_view=AuthDBView.login，未放开资源鉴权。回执authenticated-entry-assets-check.json，不含登录凭据。
- 最终32文件本地与服务器逐项SHA一致，different=[]；p4-source-final.tar.gz内32文件亦逐项匹配，包SHA256为97ae76d5ed2dc082a12386bd3b3d2f4e30047a3e46869a3cf0ade30e25430201。code-sha256.json与code-sha256-verification.json已刷新，负载原摘要不动。最后配置/元数据库备份为/var/lib/shadow-bi/backups/20261023T202346Z（UTC目录时间），服务active、NRestarts=0、current仍为sealed-20261024-a；本次收尾未重跑负载或恢复演练。

- 同批数据：业务run_p35_personal_final_20261023、呈现run_p35_personal_ui_20261023；当前sealed-20261024-a，语培10月21日/留学10月22日。另一真实截止版本cutoff-20261019仍保留供回滚，非P5日更计数。
- 源码/环境：p4/、受影响p3/p35源与32文件摘要、p4-source-final.tar.gz、requirements-server.lock。服务器封存库39表重建已完成，尚未接原始BI每日采集/业务重算。日更、扫码提醒、三人真实账号及替换静态入口属于后续经授权阶段。
- 已交验但待总线程/用户决定：学校P95略超3秒、冷首屏超5秒；旧站正常Basic登录后的真实页面。不能据0请求失败或API回归替代这三项，不自行整体验收/扩大试用/正式切换。
