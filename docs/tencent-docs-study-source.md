# 腾讯文档留学来源抓取

## 当前验收状态（2026-10-09）

Chrome实抓完整Excel导出流程，并用独立Python重新导出下载成功。用户提供的6—8月腾讯业务历史已一次性标准化并写入本地隔离留学仓，保留9月并接入10月；当前标准历史Snapshot为 `snapshot_study_abroad_cloud_aligned_20261009_v5`。这份腾讯资源与签约历史独立于人员产能使用的6—8月确认汇总。BI仓与 `Work/workspace.json` 不变，未激活网页或真实发送。本轮源码与6—9月标准历史已按A/B分包同步Grok，云端本人登录态重新抓取10月：233工单、451,960元现金、人头留学12／小语种10；本机通过同一回传原件已对齐。云端同批看板／人员预览和8空跑／18组包通过，正式网页与通知尚未切换。

历史规则由用户明确确认：6月颜色映射归属、未标色不计市场；6/7月小语种“签约金额”为实收；缺客户／学员编号暂按姓名去重，留学与小语种分域，后补唯一编号时桥接；7月两日期冲突采用完整日期7月7日。8月两条无实缴金额续签保留NULL和缺金额标记，不填0、不计现金完成。

7月资源仅在资源ID、分单日期和已有团队均一致时，以腾讯原表的人工归属补齐空个人归属（565条）；原空值、匹配依据及来源原件保留。少量双意向类型以同资源ID在腾讯表的优化后咨询类型解析，每条资源仍只计一次。6月CRM无业务资源ID的行使用独立技术记录键保留明细，不伪造资源ID；同业务资源ID跨月保留最新分单日，同日冲突仍阻断。

标准历史当前金额：6月2,781,483.10元、7月3,772,637.35元、8月3,745,488.80元、9月2,347,804.40元；各月未归属行不计市场完成。客户/学员姓名仅保存在私有标准表，临时人头键使用摘要。覆盖FY27当前年度，不计算同比；业务确认的官方记分卡及历史人员产能记分结果保持原地，不被明细核算值覆盖。

## 下载合同

`data_acquisition.connectors.tencent_docs` 使用本次实抓的腾讯文档网页接口，不宣称为腾讯公开稳定API：

1. `POST /v1/export/check` 校验导出权限。
2. `POST /v1/export/export_office`，以 `exportType=0` 创建完整Excel导出任务，取得 `operationId`。
3. `GET /v1/export/query_progress` 轮询，完成响应含 `status=Done`、`file_url`、`file_name` 和 `file_size`。
4. 下载腾讯COS返回的临时文件。实抓链接有效期1800秒，每次运行重新建任务，不固定保存下载链接。

Cookie仅发送给 `docs.qq.com`，文件下载请求不带文档Cookie。登录失效、非JSON响应、任务失败、超时、异常下载域、文件大小不符或损坏XLSX均失败退出，原始文件以唯一文件名保留，不覆盖之前导出。会话文件在本机私有忽略目录，权限0600，不随源码包上传。本次Grok已用本人在云端独立登录的腾讯会话完成实抓；长期有效性需后续运行检查，Mac Cookie不传云端。

```bash
python3 -m data_acquisition.connectors.tencent_docs \
  --doc-id '<实抓docId>' --page-url '<腾讯文档页面URL>' \
  --cookie-file '<私有cookies.json>' --output-dir '<本次run原件目录>'
```

Cookie文件接受Chrome抓取的 `{ "cookies": [...] }` 或Cookie数组。TLS证书校验保持启用；环境需要显式CA时使用 `--ca-file <CA文件>`。下载回执只输出原件路径、字节数及SHA-256，不输出Cookie或签名地址。

## 工作簿读取

共用读取器 `workspace_modeling.operations.study_abroad_source` 支持已实读的两套明确页签名称；同类同时出现两个合法候选时拒绝模糊选取：

| 业务 | 原样本 | 腾讯在线导出 |
|---|---|---|
| 资源 | 资源 | 资源登记表（前途） |
| 留学签约 | 留学签约 | 留学签约看板（市场） |
| 小语种签约 | 小语种签约 | 小语种签约看板（市场） |
| 归属映射 | 筛选项，A:B | 筛选项（前途），C:D |

资源表在前十行唯一定位关键字段表头（本次为第三行），不把说明行当工单。旧样本的“是否退回”“市场活动”与小语种资源ID不作为新导出的必填项；缺失保留为空，不按姓名拼资源ID，不推断删除或回收。金额、日期、合同／学员编号及市场归属仍受校验。资源描述兼容已实读的“91资源描述”。小语种预填公式但无业务日期、金额、学员或工单编号的空模板行排除，真实不完整行仍由后续校验报错。

腾讯导出的样式包含空 `fill`，标准Excel读取库直接加载会失败。读取器仅在内存修复空节点，保留原索引和日期格式；原件字节和摘要不变。隐藏F26页及汇总看板不作为本次三类业务来源。

## 月份保留与建仓

用户确认无法保证在线表保留所有历史，因此按各业务日期月份刷新：历史输入从旧到新，再读取当前导出；后来源整月替换它覆盖的月份，其他月份保留。显式 `--refresh-month` 支持当前月真正清空时移除该月旧行，避免累计追加导致双算。小语种没有稳定缴费流水键，不以相同学员或金额误去重真实记录。

```bash
python3 -m data_acquisition.jobs.build_study_abroad_warehouse \
  --workspace '<客户工作区>' --source-file '<本次下载原件>' \
  --history-file '<已确认历史原件，按从旧到新重复提供>' \
  --refresh-month '<YYYY-MM>' --through-date '<YYYY-MM-DD>' \
  --run-id '<新run_id>' --snapshot-id '<新snapshot_id>'
```

原始历史和当前工作簿、逐行原页签／行号／文件摘要及月保留规则均冻结到留学运行目录。消费者校验所有冻结原件和历史读取器摘要，不能替换旧Snapshot。BI仓与 `Work/workspace.json` 不写入。

用户已确认同一资源ID跨不同分单日期重复时保留最新日期；同日记录冲突仍拒绝，不按Excel行号随意取最后一条。本次两条冲突资源按9月11日记录保留。归档月份为Excel日期时规范为YYYY-MM，仍严格核对归档月份和归档日期一致。

## 标准历史复用与月份更新

一次性原件清洗使用 `--legacy-file` 明确提供六月、七月、八月原件，并以 `--legacy-date-preference full` 采用已确认日期规则。规范源的三张表为 `resources/contracts/languages`，保留日期、金额、归属、团队、客户键、技术记录键及原文件摘要／页签／行号。`--standardized-source` 直接校验并导入已清洗的三表源，适用于Grok的B包，不重新解析旧原件或颜色。

后续通过 `--history-snapshot-id` 从明确的当前留学Snapshot受控读取标准历史，保留非刷新月份；只替换指定月份，空月也明确清空，不逐日追加。历史查询回执、父Snapshot的manifest/lineage摘要及读取器版本均记录到新版本。

一键下载与月份更新入口：

```bash
python3 -m data_acquisition.jobs.update_tencent_study_abroad \
  --workspace '<客户工作区>' --doc-id '<实抓docId>' \
  --page-url '<腾讯文档页面URL>' --cookie-file '<云端私有登录态>' \
  --run-id '<本次唯一run_id>' --snapshot-id '<本次新snapshot_id>' \
  --through-date '<明确来源截止日>' --refresh-month '<YYYY-MM>'
```

该入口从 `Work/StudyAbroad/current.json` 获取明确父Snapshot身份，下载后只刷新指定月份，不再读历史Excel。失败保留上一成功指针，导出任务每次重新创建。Grok使用自己已登录的腾讯浏览器会话，Mac Cookie不随A/B包传输。

看板与人员贡献都消费同一个显式留学Snapshot；人员贡献不再在管理构建中另取九月参考工作簿。跨业务工单由BI工单一级渠道精确为“双分”（留学向语培输出）和腾讯标准行归属组“国际市场”（语培向留学输出）识别，不再读取原资源流转表。旧 `资源流转.xlsx` 及双分流转明细只保留历史追溯，不参与当前计数、姓名覆盖或缺失门禁；6—8月业务确认的留学／小语种人员历史结果继续只读沿用，9月人员表仅作对账。名单与既定共创分摊由人员产能模块处理，腾讯签约／实缴归属仍以本行人工归属为准。这里的腾讯导出更新针对留学资源与签约数据，不会自动抓取广告费用；ROI费用由用户手工提供并登记到 `Input/AdvertisingCosts/sources.json`，Grok 端同样如此。既有例行时间、收件人和密钥不因本次更新改变；真实发布或发送须遵循具体任务范围。

本轮证据：`.local/audits/study-history-678-20261009/`；前轮抓取证据：`.local/audits/tencent-study-capture-20261009/`。会话与原始请求位于私有忽略目录，不进入Git或公开交付。

## 每日双仓更新与消费者门禁

来源生产者为 `data_acquisition/deploy/run_daily_warehouses.sh`，并列调用现有BI重建与腾讯更新；两源各尝试一次，任一失败即整体失败。保持各自已成功的不可变Snapshot，不回滚或伪造另一仓；`Work/DailyWarehouseRefresh/current.json`记录最新尝试，`last_good.json`保留上一成功配对。刷新期间及失败状态不允许新发布／投递。

看板日常和日推日常不重复抓取来源：前者先校验当天联合回执及两仓当前身份后构建／发布；后者校验同一联合配对与同批通知再投递。腾讯历史从已标准化仓受控读取，只替换上海当天所在月份，不因新月份导出缺旧月而清空历史。月底迟到历史需明确来源另补，不无证推数据。

数仓例行调用环境（ID、URL取已核验腾讯文档，Cookie使用Grok本人的云端会话）：

```bash
PYTHON='<warehouse虚拟环境Python>' PROJECT_ROOT='<warehouse根>' \
WORKSPACE='<客户工作区>' TENCENT_DOC_ID='<已核验docId>' \
TENCENT_DOC_URL='<已核验页面URL>' TENCENT_COOKIE_FILE='<云端私有0600 Cookie>' \
bash data_acquisition/deploy/run_daily_warehouses.sh
```

脚本默认按上海日期与时分秒生成新run和两仓Snapshot身份；也可显式传入AS_OF_DATE、RUN_ID、BI_SNAPSHOT_ID、STUDY_SNAPSHOT_ID。有必要时通过TENCENT_CA_FILE指定信任CA，证书校验保持开启。来源任务每天先从云端已登录腾讯会话刷新私有Cookie，不上传或显示凭据；登录无法续期时报告需本人登录，来源失败阻断后续消费者。

现有数仓09:30、看板09:45、日推10:24为三条原例行；本次只更新执行正文，不另建任务、不改时刻／启停／通道。代码和失败门禁已安装云端并通过261项／67subtests回归；三条原Routine均已获得UpdateRoutine回执，原ID／时刻／开关保持，最终提交正文和摘要留在 `.local/sync/inbox/grok-daily-dual-20261009/prompts/`。平台无法完整回读正文，不把提交副本当全文回读。真实联合运行 `run_daily_sources_20261009_210221` 已结束：BI因本人登录超时失败，腾讯在同轮成功更新 `snapshot_study_abroad_20261009_daily_210221`，6—9历史不变。联合failed已阻断下游，未新建生产batch／发布／发送；BI本人扫码后才可验收双源成功及新批预览。失败来源终态状态已修复，不改旧运行收据。

腾讯当前导出不提供删除／回收状态列。个人状态开关保留，只影响源中有明确状态的行；缺状态行不被推断为删除或回收。
