# SEM下载宿主与总入口接线

## 已证实的获取路径

《汇报202610SEM》原入口为 `https://alidocs.dingtalk.com/i/nodes/Obva6QBXJw9lXeeoF7P7GMqqWn4qY5Pr`。先前成功操作由 `mcp__cua_repl` 控制用户已登录的正常网页，走“菜单→表格→下载为→Excel（表格整体）”；服务端任务32377865292最终落地17sheet原件，SHA256 `3eba3b323d41323d273b228506bed1235738324dbc1c9b00b5d6655cd5c9d2cd`。不是已验收的独立HTTP脚本。

请求采样只证实upload_info→临时副本上传→submitExportJob→queryExportJobInfo；响应体丢失，不能猜JSON/序列化并重放。未编辑源表。

## 当前宿主实际依赖

`native_exports.download_sem(page, ...)` 接收调用方正常登录的 Playwright Page，负责整本下载、工作簿叶表校验、SHA-256 和显式完成标识检查。`sem_host` 使用项目现有 Playwright/Chrome 组件，从指定钉钉链接启动全新、不带浏览器 profile 的上下文；显式登录后，只把该文档站点适用的 cookies 和 localStorage 保存到 `dingtalk_sem` 专用 auth service，目录0700、文件0600。采集时在新上下文里读取该状态，不连接已有 Chrome或读取普通浏览器会话，再调用 `download_sem` 和 `sem_candidate.stage_sem`。认证缺失或被页面明确识别为过期时只发起一次正常登录恢复；导出阶段的超时或未知结果不触发重复提交。

单次实采入口：

```sh
.venv/bin/python -m data_acquisition.connectors.advertising.sem_host \
  --mapping-manifest customers/shadow_bi_daily/Input/AdvertisingCosts/sources.json \
  --output .local/audits/sem-one-off-20261029 \
  --start 2026-10-01 --through 2026-10-28
```

首次登录可运行 `sem_host --login-only`；它只打开一次独立窗口、等到指定文档打开后保存专用状态，不导出。若页面要求登录或扫码，请在该窗口正常完成。后续 `--check-auth` 会在另一新进程/上下文检查状态是否可重用，不导出；日常导出再用本节下方的普通入口。成功结果包含原件、校验摘要、完成标识和可供 `prepare_full_daily --sem-receipt` 消费的回执。`completion.complete=false` 表示页面没有提供明确填报完成标记；当前合同仍接受这份最新整本表，并把缺失费用与覆盖状态记录为partial，不因标记缺失单独阻断。

总入口 prepare_full_daily 增加显式 --sem-auto：通过 sem_host.run_one_off 只用已保存的 dingtalk_sem 状态，不在定时运行时打开登录窗口；缺失/过期会阻断并报告，不静默弹扫码。宿主认证根目录固定为运行代码的仓库根目录，SEM映射仍从 `--workspace` 指向的客户工作区读取。--sem-receipt 仍用于显式传入既有回执，两种模式互斥。CUA网页导出先完成了原件验证；随后专用 sem_host 在独立进程中复用了钉钉专用登录态并完成一次新导出。

## 2026-10-29旧样本与文件接线（历史）

新增 `data_acquisition.connectors.advertising.sem_candidate`，把当时明确给定的整本原件、旧样本叶表业务映射接成候选manifest及总入口回执。原件追加复制、SHA核对，沿用当时10个已确认映射，不猜其他叶表归属；不替换正式费用清单。该10叶表样本为历史验收，不代表当前SEM映射范围；当前整本为17张工作表、15张费用叶表。

已有原件实际接入结果：17sheet、10映射叶表、280条已选窗口费用记录。历史样本明确 `status=sample_only`、`captured_at=null`、`completion.complete=false`；可以做工程联跑，不能冒充当天有效采集。测试已证明它无法通过正式capture门禁。

```sh
python3 -m data_acquisition.connectors.advertising.sem_candidate \
  --native '/absolute/path/to/existing-whole-workbook.xlsx' \
  --mapping-manifest customers/shadow_bi_daily/Input/AdvertisingCosts/sources.json \
  --output /absolute/new/isolation-directory \
  --start 2026-10-01 --through 2026-10-28
```

当前网页采集已由 `sem_host.run_one_off` 调用 `download_sem` 并通过 `sem_candidate.stage_sem` 生成回执；整批入口可用 `--sem-auto` 执行采集，或用 `--sem-receipt <output/capture.json>` 接收已有回执。`sem_candidate --collector-capture <source-dict.json>` 仍用于把明确给定的来源dict与本地SEM原件绑定，不负责网页采集，也不自行发明采集时间或填报完成声明。

## 独立宿主验证结果

用户已明确授权仅为给定 SEM 文档保存钉钉专用登录态。状态已通过项目现有写入器保存到 `data_acquisition/storage/auth_sessions/dingtalk_sem/`：目录权限0700，`cookies.json` 与 `localStorage.json` 权限0600；该目录被 Git 忽略。脚本只加载该服务的状态，不借用 BI 会话，也不输出认证内容。

新进程 --check-auth 曾返回 auth_reused=true、workbook_accessible=true、exported=false。之后唯一一次脚本实跑在 workbook_readiness 等待到超时，诊断码为 sem_workbook_not_ready_editor_menu_ambiguous。同一文档的只读 DOM 检查发现 iframe 内精确文本“菜单”匹配共2项：1项隐藏且无交互后代，另1项可见、enabled且边界框非空；旧门禁把隐藏项也算成歧义。修复后门禁保留总匹配数和可见匹配数，只接受目标 iframe 内唯一的可见精确文本；不选 first/nth，并把可见计数与安全诊断码写入 attempt 日志。

早期旧版本的一次运行在点击前失败；依据当时的调用顺序和缺少 export-state.json，确认没有提交远端任务。修复日志后的本轮尝试 attempt_id=c59feab25c8249c08a2c4e97798d147c 在 workbook_readiness 失败，状态 pre_submit_failed，没有 submit 事件、remote_task_id 或输出目录，因此没有待查任务。该失败由隐藏菜单文本重复造成；修复后独立采集已成功，见下文。

已捕获的钉钉请求契约记录：`POST /core/api/document/submitExportJob` 返回HTTP200，实际请求体字段为 `exportType` 和 `storagePath`；只读查询是 `GET /core/api/document/queryExportJobInfo?jobId=…`。原提交响应体已不可取，脚本没有任务号，因此不能用查询接口查该次运行；也没有重放或猜测接口请求。当前脚本会被动观察页面这两个已捕获路径，只记HTTP状态和可识别的 `jobId`，不保存响应体；启动阶段另写原子去敏attempt日志，最终点击前再原子写入待定状态和attempt ID。意外异常只保存异常类型与代码文件/函数/行号，不记录异常文本、URL查询、局部变量或认证内容。若新任务点击后下载状态不明，先按日志任务号查询，绝不盲目重提。

完整性标签仍只接受钉钉页面明确显示的“数据更新至/填报完成至”等日期；原件最后编辑时间或预填日期不能代替填报完成证明。

2026-10-29 Playwright 实跑在 Chrome 启动阶段失败，返回 `TargetClosedError`；`channel="chrome"` 指向已安装的 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`，启动时访问 `~/Library/Application Support/Google/Chrome/Crashpad/settings.dat` 得到 `Operation not permitted`。当前 `.venv` 使用 Playwright 1.62.0，期望缓存 Chromium 修订版1234 / Chrome for Testing 151.0.7922.34；缓存里已有旧版145.0.7632.6与148.0.7778.96。单独启动148版生成 `~/Library/Logs/DiagnosticReports/Google Chrome for Testing-2026-10-29-134458.ips`：`EXC_CRASH/SIGABRT`，主线程栈到 `TransformProcessType → ChromeMain`；报告进程由 ChatGPT 启动。报告没有足够信息证明是 TCC 或某项用户系统设置导致。

## 2026-10-29本机整本导出与候选（历史）

用户手动启动 Chrome for Testing 148 并完成系统提示后，另一浏览器线程通过已登录钉钉普通页面完成一次“菜单→表格→下载为→Excel（表格整体）”导出。新原件 `/Users/akechi/Downloads/汇报202610SEM (3).xlsx` 为47,300字节、17张表，SHA-256 `2ca690953a1fa1a8413761a2ecc192a49a897075dd7833de31a229b4abe51611`。旧任务32377865292已完成且未复用；这次交接没有新任务ID。原件经 `adopt_download_path` 追加复制并哈希核对，原下载文件未改动。

10张映射叶表都覆盖2026-10-01至10-28日期行，共280条解析记录；每张叶表10-28均有日期行，其中一张费用为469.49元，其余解析为0。网页交接只提供最近编辑时间13:51，没有“已更新至/填报完成至”字段，故回执保留 `completion.complete=false`；正式完整性门禁实际返回 `native_completion_missing:sem`，不能据此把已预填行或空白视作整本已填完。原件与接入证据见 `.local/audits/full-daily-20261029-sem-cua-combined-v6/adoption-result.json`、`ui-export-evidence.json`。

用新原件替换隔离候选中的历史SEM样本后，统一候选成功构建39张表、3,372条费用行；腾讯账户74749810按用户确认合并：搜索19,965.62元 + 展示2,278.58元 = 22,244.20元。候选位于 `.local/audits/full-daily-20261029-sem-cua-combined-v6/candidate-build/presentation`，结果见同目录父级 `engineering-result.json`。这是候选计算，未刷新来源、未改正式费用清单或看板current，未发布、未启日程；完整财务范围和SEM填报完整性仍未验收。

此前一次 CUA 下载证明原网页导出可用；另有 --check-auth 在独立进程复用专用状态并打开目标工作簿。现在 sem_host.run_one_off 的独立整本导出也已实跑成功，详见本节末的最新结果。状态仍只对应 dingtalk_sem，保存在 Git 忽略目录，使用项目0700/0600写入器；不借用 BI 会话。

## 钉钉专用登录态验证

Chrome for Testing 148 的本机二进制已核验位于 `/Users/akechi/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`。不用 `channel=chrome` 触碰普通Chrome配置；以下命令显式使用已存在的浏览器，不安装软件或创建持久浏览器profile。

```sh
.venv/bin/python -m data_acquisition.connectors.advertising.sem_host \
  --workspace "$PWD" \
  --mapping-manifest customers/shadow_bi_daily/Input/AdvertisingCosts/sources.json \
  --login-only --executable-path '/Users/akechi/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'

# 新进程、新上下文，只核验登录态；不触发导出。
.venv/bin/python -m data_acquisition.connectors.advertising.sem_host \
  --workspace "$PWD" \
  --mapping-manifest customers/shadow_bi_daily/Input/AdvertisingCosts/sources.json \
  --check-auth --executable-path '/Users/akechi/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'

# 再由独立进程使用专用状态采集一次整本原件。
python3 -m data_acquisition.connectors.advertising.sem_host \
  --workspace "$PWD" \
  --mapping-manifest customers/shadow_bi_daily/Input/AdvertisingCosts/sources.json \
  --output .local/audits/sem-cross-process-$(date +%Y%m%d-%H%M%S) \
  --start 2026-10-01 --through 2026-10-28 \
  --executable-path '/Users/akechi/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'
```

真实专用状态已保存，独立进程登录态复用已验证。2026-10-29 解锁后唯一一次初始脚本运行在 workbook_readiness 失败；没有提交事件或任务号。按 DOM 实测调整为唯一可见精确菜单匹配后，新进程再次运行成功：attempt 06f7e9ec4c8245a0b9a6192b2fe9751f，远端任务 32197951827，17-sheet 原件 47,555 字节，SHA-256 8866d2311a90bef6d40ca52a6912d346636f8ca7807a8b1681e6257384e70be4。已生成 sem-candidate/capture.json 和隔离 manifest；completion.complete=false，因此只证明原件已下载/封包，不证明 SEM 已填报到 10/28。正式看板未变更、未发布、未启用日程。

## 2026-10-29独立脚本实跑与新候选（历史验收）

修复“菜单”检查只统计目标 iframe 内可见且唯一的精确文本后，独立进程使用 dingtalk_sem 专用状态完成真实整本导出：attempt 06f7e9ec4c8245a0b9a6192b2fe9751f，远端任务 32197951827，提交与只读查询均为 HTTP 200，auth_reused=true。原件为17张表、47,555字节，SHA-256 8866d2311a90bef6d40ca52a6912d346636f8ca7807a8b1681e6257384e70be4；验证回执位于 .local/audits/full-daily-20261029-sem-independent-verify-3/。

该回执只证明已下载，completion.complete=false、basis为download_only，不能证明所有SEM叶表已填至10月28日，正式完整性门禁继续阻断。将这份回执接入同批其他已验收文件后，隔离候选在 .local/audits/full-daily-20261029-sem-script-combined-v7/ 成功构建39张表、3,372条费用行，SEM十个已映射叶表解析280行。候选保留1份小红书、6份巨量和2份腾讯原生来源；腾讯两入口按用户确认原样相加，19,965.62 + 2,278.58 = 22,244.20元，引用用户确认文件SHA-256 9545adae395b5f02c511f94c8192593c662949d6a515f66d209a7ffa92e8e158。这是业务范围授权，不是技术互斥证明。

本次没有重新采集其他来源，没有刷新BI/留学快照，没有改正式费用清单或任何current指针；候选报告记录 production_ready=false、published=false、schedule_enabled=false。候选只用于工程验算，完整财务范围和SEM填报完整性仍未验收。详情见该目录的 engineering-result.json、candidate-build/prepared-candidate.json 和 README.md。

## 总入口与同作业恢复验收（2026-10-29记录）

总入口选项 `--sem-auto` 让采集器以同批目录下的 `sem` 子目录作为本次SEM输出，日期窗口取 `full-daily-sources.json` 配置的开始日到上海昨天。成功输出可直接复用为capture receipt。当前SEM合同不要求页面提供填报完成日期；缺失的费用保留为空，并由覆盖信息标记partial。其余来源的账号、窗口、导出完成和费用验证门禁不变。2026-10-29的真实任务 `completion.complete=false` 是页面没有完成标记的历史回执，不是当前整批门禁失败条件。

同一输出目录的新 Python 进程复用测试已真实运行：返回原任务32197951827与原attempt 06f7e9ec4c8245a0b9a6192b2fe9751f，reused_existing=true、exported=false；唯一attempt日志与 export-state 字节摘要前后相同。此路径在校验verified状态、双份attempt一致、窗口/工作簿/映射、manifest与原件SHA后立即返回，不读取认证状态、不启动浏览器。存在未知提交状态、多个未解决attempt或摘要不匹配时拒绝复用，不创建新任务。

总入口示例（需要真实刷新其他广告源，今日未执行）：

~~~~sh
.venv/bin/python -m data_acquisition.jobs.prepare_full_daily \
  --workspace customers/shadow_bi_daily \
  --batch-dir .local/audits/full-daily-20261029-run \
  --source-contracts .local/audits/full-daily-browser-20261028-reconnected \
  --xhs-scope .local/audits/xhs-request-authorization-20261028/verified-source.json \
  --sem-auto \
  --sem-executable-path '/Users/akechi/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'
~~~~

同一运行恢复时保持相同的 batch-dir，SEM仅在其中复用已校验成功的 sem 输出；未知状态先停下核查。今天没有执行该总入口，以免刷新小红书、巨量和腾讯来源。跨日无人值守、锁屏下浏览器启动及整体来源采集的端到端稳定性仍未实测；也没有启用09:30定时。

## 2026-10-29 SEM空白值最新口径

用户最新确认按整份最新SEM表覆盖，有多少使用多少；空白可能是停投，也可能是数据滞后，不作确认零、不归责员工。解析保留消费原值、现金消费缓存值及其公式，空白或由空白消费推导出的公式缓存零值写为`amount=null`；已取得的非空现金费用仍参与汇总。来源元数据保留请求窗口、实际日期、缺日期、缺金额日期和计数。候选计算可继续并把未覆盖日期标为partial，不要求页面“填报完成至”标记；其他平台原有完整性、账户、SHA和排重门禁不变。

本批原件`.local/audits/full-daily-20261029-automatic-validation-01/sem/sem-candidate/native.xlsx`含10张映射叶表、280条实际日期行；10月28日有4张叶表的现金消费公式缓存为0，但依赖的消费单元为空。新解析按缺失处理，未改原件。下次采集以完整新SEM表替换本批原表并从新表重算，不累加历史导出。
