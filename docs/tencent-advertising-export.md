# 腾讯广告原生报表采集

## 当前最新：按一级竞价＋品牌核对范围（2026-11-03）

用户最新确认费用范围为一级“竞价推广＋品牌推广”，排除智能投放。菜单名不能当成排他产品字段；正常网页当前账户汇总在不同菜单下可能复用同一账本，必须使用实体级请求中的明确类型筛选，按日期和广告／计划ID去重，再逐日核对原生账户CSV。

本次在一个固定Chrome页面正常设置9/1—11/2、查询并点击导出：展示16条、2278.58元，手动账户CSV与脚本原件SHA完全相同；广告明细为ID123364833236，竞价管理列表也确认该ID和金额，当前已暂停。16天结果不是仅由脚本截断造成，不能因智能停用就剔除这笔竞价展示历史费用。搜索广告625条、12个ID，网页直接下载上限500，已用官方离线任务118002465361取全量，金额21467.16元。两份明细日期-ID无交集，各自逐日对原生账户日报差异为0，合计23745.74元。

抓取必须按本次观测的实体合同核验：V3竞价展示／升级版有 `smart_delivery_platform LESS SMART_DELIVERY_PLATFORM_EDITION_SCENE`，搜索实体有 `CAMPAIGN_TYPE_SEARCH` 与 `BUYINGTYPE_AUCTION`；品牌计划有 `BUYINGTYPE_CONTRACT` 和对应campaign类型。品牌内容是品牌触达合约的子集，不重复累加。广告级品牌触达报404时没有补零，改用官方计划级proxy查询成功取得空列表；品牌搜索、内容计划、实时竞价全部状态、内容助推完整费用窗也取得成功空态。内容助推界面默认近7天“创建时间”筛选不能冒充完整费用窗，独立查询已移除此创建筛选。

费用正式版本已在调查前切为 `daily-20261103_141437`，数值与上述两批原件一致；新范围每日校验及同源专用状态的线上8分支核验已通过，私有scope_review已切为observed_contract，每次采集都重查，范围未验或对账不符阻断费用。日更合同存于`.private/tencent-promotion-query-contracts.json`，不依赖临时审计目录，不复制普通浏览器Cookie。品牌实时竞价／内容助推已补为正常分日报表，v2合同删除旧管理级空态接口；所有品牌分支非空时自动分页采集，分别与自动下载的V3／legacy原生账户CSV逐日对账并随账户账本入仓。不会因为非空本身停下来要求人工处理，也不会额外再加一遍品牌菜单金额。原件、逐日对账、观测契约均在 `.local/audits/bi-orders-full-rebuild-20261103/tencent-manual-batches/` 和 `tencent-promotion-query-contracts.json`。下方为旧阶段记录，旧“仅搜索＋展示”规则不能单独证明新范围完整。

登录恢复先复用专用Cookie和localStorage；仅缺失、明确过期或4501时正常登录一次，账号验证后立即保存会话，再验证两类正常请求；业务／Schema／404等错误不触发登录。最新bi-3已更新这一规则，其他日程不变。

## 当前整批入口

当前广告费用整批采集与候选构建由 `data_acquisition.jobs.prepare_full_daily` 编排；其中腾讯来源每次建立新的上海昨日窗口，采集搜索与展示账户CSV，并以工作区私有配置中的观测合同核验竞价／品牌推广明细与账户账本。默认 `--prepare` 仅生成本地候选；`--publish` 才进入 business-first 发布、日推和费用更新门禁。详见[看板费用与ROI](dashboard-advertising-costs.md)。以下 `tencent_requests` 命令和固定窗口均为旧批次复核入口，不是当前每日窗口配置。

> 2026-10-29阶段进展见[当时的日更记录](archive/shadow-bi-daily-progress-20261029.md)。下文保留各阶段原始验收回执；其中旧范围和旧候选状态不代表当前费用合同。

## 2026-10-28旧范围验收（历史）

2026-10-28已在本机main验收账户74749810（北京新东方前途出国咨询有限公司）的两个产品范围。唯一费用权威是腾讯平台原生CSV，不用集团汇总补齐；两个产品独立保留，尚未相加或登记正式费用。

| 产品范围 | 独立HTTP任务 | 数据行/金额 | 选中窗口与实际日期 | 连续实测 |
|---|---:|---|---|---:|
| 展示/多产品 `display_plus` | 117172083687 | 16行，2278.58元 | 9/1—10/27；实际9/1—9/16，41天无记录 | 1.894秒 |
| 旧搜索 `legacy_search` | 117173583721 | 57行，19761.93元 | 9/1—10/27，57天均有记录 | 2.130秒 |

两次均在浏览器关闭后由独立Python进程完成查询、创建、轮询、授权下载和隔离intake，无前台操作或再次登录。原件SHA分别为 `9f71d7796609280e27593ac30c0c66fe6860a8214caa3804cef35c461f157c4f`、`b2bbe89c763c94c8b84626498e56915704b506886ffa994fbfa40b4a09adca63`，与此前原生文件逐字节一致。

## 品牌非空的每日处理（2026-11-03补齐）

现有两个导出任务是账户分日账本，不是两个排他的菜单。每天仍用原入口自动创建／恢复任务并下载原生CSV；品牌金额在对应账户CSV中只入仓一次。推广明细负责证明账户金额属于用户确认的竞价＋品牌，不能把多个菜单账户汇总再相加。

- 品牌触达合约、品牌搜索合约按计划×日期核对legacy账本；品牌内容合约必须是触达合约的同ID同日期同金额子集，不额外累加。
- 品牌实时竞价使用正常V3报表字段及`group_by=[date,adgroup_id]`，按广告×日期核对V3账本。不带管理状态过滤，避免只查当前未删除状态漏掉历史费用。
- 内容助推使用正常legacy报表的`ADGROUP_REPORT_BY_DATE_AND_ADGROUP`，保留`CONTENT_PROMOTION＋CONTRACT`筛选；不带创建时间限制，按广告×日期核对legacy账本。
- 各分支分页行数及日期／ID必须一致，金额使用Decimal；非空不会触发人工补文件。平台错误、缺金额、字段变化、实体重叠或真实对账差异仍明确阻断费用，不能补零或降级旧合同；基础版和已sent通知保留。

当前私有合同为`tencent_promotion_scope_observed.v2`，只接收分日报表，删除v1管理级空态路径的兼容。实际平台两个新增分日报表查询均code0成功；真实品牌本次为空，因此非空场景另用隔离回归数据验证，不代表今天产生了品牌费用。证据目录`.local/audits/tencent-brand-auto-20261103/`。

## 2026-10-28验收批次的单源复核命令（历史）

```sh
.venv/bin/python -B -m data_acquisition.connectors.advertising.tencent_requests \
  --workspace customers/shadow_bi_daily \
  --contract .local/audits/full-daily-browser-20261028-reconnected/tencent-network-sample/dedicated-network-contract.json \
  --output-dir .local/audits/tencent-http-20261028-display-plus-final \
  --start 2026-09-01 --through 2026-10-27
```

旧搜索用同一入口，将contract改为同目录 `legacy-network-contract.json`，output-dir改为 `.local/audits/tencent-http-20261028-legacy-search`。以上是本次验收批次；同目录重跑只校验完成态及SHA，不发新创建请求。日更宿主必须计算新的上海昨日截止日和新作业目录；不能把历史批次缓存当作新采集。

首次新作业会产生平台导出任务及本地原件/intake；不会修改正式费用manifest、业务库current、看板current、发布、通知或调度。凭据有效时不启动浏览器。

## 实际协议与恢复

- 展示查询：POST `/api/v3.0/integrated_list_multiaccount/get`。已独立验证可以省略易过时的nonce/timestamp；业务账户、窗口、指标及分日参数保持实际观察值。
- 旧搜索查询：POST `/ap/integrated_list/get_user_integrated_list`，保留实际breakdown和params；三页查询57条。两者不是同一查询模板，不猜转换系数。
- 创建：POST `/ap/async_task/create`。展示使用实际 `TASK_TYPE_INTEGRATED_DATA_V3`，旧搜索使用 `TASK_TYPE_INTEGRATED_DATA`。
- 状态：POST `/bff/contract/trpc.dp.dpbff.task_cgi.task_cgi/GetAsyncRequestDetail`，按精确task_id核验。只把实际观察到的完成且成功状态作为可下载，其他状态有界等待。
- 下载：POST `/ap/async_task/download`，使用平台实际表单qzreferrer、task_id、file_id、format。format原值为`xls`，实际返回原生CSV，保持原协议。**不直连响应中的内部CDN file_url**：该地址实测401，已停止；本站授权下载200并已独立验证。不会将Cookie发给CDN。
- 未知创建先GET `/ap/async_task/get_list`，按创建前ID集合、账户、任务类型、完整窗口名称和时间匹配唯一新任务。无匹配保留pending，多匹配拒绝，不选择“最新”或盲目重发。
- 下载中断先检查本次partial，必须与查询行数、日期及费用一致才采用；不完整文件追加隔离后，只恢复同一已知任务的下载，不重建任务。

## 状态保护与边界

真实状态仅保存在工作区 `data_acquisition/storage/auth_sessions/tencent_ads/`，目录0700、文件0600；Cookie和localStorage沿原项目写入器格式。额外必要的已观察请求认证参数只保存在同一受保护目录，不进入代码、Git、聊天或日志；下载链接只在进程内存中使用。

默认先用保存状态。只有缺失、明确过期或HTTP401才正常登录一次、刷新状态并恢复同一作业；403、业务错误和超时不触发登录。初次协议初始化未完成时明确阻断，不猜认证参数。登录恢复及日期切换有隔离验证，真实Cookie过期恢复与下一自然日执行尚未实测。

日更只对本次已观察到的响应 `code=ret=4501` 输出固定错误码和“登录状态需要恢复”提示，不保存任意响应文本；未知业务码仍按通用业务拒绝处理。登录刷新只读取专用正常页面查询中实际观察到的 `g-tk`/`mp-tk` 请求头或 `g_tk`/`mp_tk` URL参数，并只更新 auth 文件中已存在的对应字段。`mp_tk`按原请求路径精确刷新，不从一个接口推断另一个接口的参数。日更 collector 不因4501自动打开登录窗口。

## 旧范围验收证据和未完成项（截至2026-10-28）

- 两源总回执：`.local/audits/full-daily-browser-20261028-reconnected/tencent-network-sample/two-scopes-http-verification.json`。
- 每批目录含 `state.json`、`independent-verification.json`、`native.csv`、原始查询页、`evidence.json`、`raw_inventory.json`和`intake/intake-receipt.json`。
- 每批创建次数均为1；同目录重跑不创建任务。正式manifest/current最终摘要不变。
- 展示41天无原生记录不能补0。品牌等其他产品未核验、腾讯语培未接入，因此两批均保持whole_account_complete=false。
- 腾讯原生费用尚未并入完整费用候选计算。现行业务规则将微信/视频号与“腾讯广告”分桶；不能为接原生费用而擅改ROI分子归属。后续须沿候选路径核对映射及单信源冲突，生产默认口径保持不动。
- 巨量仍缺两账户且扩展拒绝路径已停止；SEM昨日15叶原始消费仍空。全源候选未通过，未发布或启用09:30定时。周清理、表格同步和巡检未改。

最终核心回归612 passed、1 skipped、130 subtests passed；git diff --check通过。日志位于展示最终验收目录core-tests.txt。
