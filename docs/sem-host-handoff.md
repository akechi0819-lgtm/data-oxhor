# SEM下载宿主与总入口接线

## 当前入口：Cookie注入与请求式整本导出（2026-11-04）

`sem_host.run_one_off` 在后台独立会话注入已有 `dingtalk_sem` Cookie／localStorage，只打开已批准工作簿，使用当前编辑器模型的官方 `loadAllSheets()` 与 `serialize({compatible:"excel"})` 生成本次上传内容。随后直接执行下载权限检查、`upload_info`、临时副本PUT、`submitExportJob`、`queryExportJobInfo` 和整本原件下载；没有菜单定位、点击或菜单回退。浏览器只用于当前模型读取、官方序列化与同源鉴权，不能把它称为完全不使用浏览器的HTTP客户端。

请求实现位于 `sem_requests.py`；已验证前端版本为 `flex-table-app 2.72.0`。序列化与鉴权接口的运行时入口改变会明确失败，不猜参数或回退旧菜单。仅缺失或明确过期的专用授权触发一次原正常登录恢复，权限／业务错误不触发登录。

任务状态保存在输出目录 `native.request-state.json`（0600）：提交前先写结果未知标记；取得 `job_id` 后持久保存，同目录恢复只查原任务，不重新创建。未知结果且没有任务号时阻断，不盲目重提。已下载原件校验SHA后复用；既有 `export-state.json`、attempt、`sem-candidate/capture.json` 和 `--sem-receipt` 合同保持。

11/4独立新进程已真实全自动创建任务 `32358779316`，提交1次，后台下载17个页签、15个费用叶表，原件SHA `b99fd9147fb28098d30b5a3cabe3a651d78773354608fdb3a9ddd19d1bfe8c65`；与当天手动原件全部页签的值和公式一致。第二个进程同目录运行复用同一任务，`exported=false`，没有新建任务。此验收未发布BI、未推送消息、未采集其他平台。证据 `.local/audits/sem-request-automation-20261104/live-auto-1/` 和 `live-native-comparison.json`。

`prepare_full_daily --sem-auto` 仍调用这个SEM宿主，现改用其已有 `run_authenticated` Cookie优先恢复入口。其余来源与业务→基础看板→8条通知→费用顺序没有改变。最新整本表仍不等于填报完成证明，缺完成标记／空金额继续如实保留。

## 日常入口与恢复

唯一总入口为 `data_acquisition.jobs.prepare_full_daily --sem-auto`。继续使用同一个 `--batch-dir`；SEM产物位于其 `sem` 子目录。其他业务来源、通知和费用阶段不单独另起发布链路。业务双仓成功后发布基础看板，确认原5通道8条日报，再采集全部费用并通过原门禁补发费用及ROI；SEM失败只阻断费用。

需要独立验证SEM时使用已有宿主：

```sh
.venv/bin/python -m data_acquisition.connectors.advertising.sem_host \
  --mapping-manifest customers/shadow_bi_daily/Input/AdvertisingCosts/sources.json \
  --output /absolute/new/sem-output \
  --start YYYY-MM-DD --through YYYY-MM-DD
```

`--login-only` 只打开一次专用正常登录窗口并保存授权；`--check-auth` 检查专用状态，不创建导出。状态固定在仓库 `data_acquisition/storage/auth_sessions/dingtalk_sem/`，目录0700、文件0600且不进Git，不借用其他平台或普通浏览器会话。采集后台上下文显式直连（`--no-proxy-server`）。

成功输出包括 `native.xlsx`、SHA校验、`export-state.json`、独立attempt日志及 `sem-candidate/capture.json`；已有回执仍可用 `prepare_full_daily --sem-receipt` 显式接入，与 `--sem-auto` 互斥。同目录完整验收结果在认证及浏览器启动前直接复用；已知任务仅续查原ID；无ID的未知提交必须核查现场。权限、业务、Schema及未知任务错误不触发新登录或重提。

`native_exports.download_sem` 只委托 `sem_requests.download_sem_requests`，再沿用原整本验证和 `sem_candidate.stage_sem` 封包。运行不依赖前端源码dump、历史抓包文件或观察器。旧菜单实现及仅观察请求的 `dingtalk_contract` 已删除；原始下载和历史请求回执仍是证据，不是可执行接口合同。历史菜单验收详情可查Git历史及 `docs/shadow-bi-full-daily-20261028.md` 对应历史小节。

## 当前费用口径

最新整本覆盖旧SEM表，按当前manifest的15张已确认叶表入仓，不累加多次导出。明确语培项目保留语培，已确认业务归属不明项目计入留学。消费空白及由空白推导出的公式缓存零保留 `amount=null`，不补零、不推断停投或员工未填；已取得的非空费用正常汇总。

保留原始消费、现金消费缓存及公式、实际日期、缺日期和缺金额日期等覆盖证据。缺少“填报完成至”标记不单独阻断最新整本入仓，`completion.complete=false` 如实保留；最新编辑时间、预填日期不构成填报完成证明。其他广告平台原有账户、日期、完整性、SHA和排重门禁保持。

## 11月4日清理审计

验收后的前端静态分析dump已核销，逐文件SHA和清理结果见 `.local/audits/sem-cleanup-audit-20261104/`；原件、请求任务状态、验收证据、专用授权、当前Snapshot和正式发布保持。失败CSV转换原表仍被历史工单回执引用，暂保留；本次临时CSV不改BI永久导出链路。其他来源和所有日程未修改。
