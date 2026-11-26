# 腾讯文档留学来源抓取

## 当前下载入口（2026-11-02）

留学表在线下载已统一为官方腾讯文档MCP。与原脚本同时间段导出的8个页签，数据、公式、缓存值、样式和透视表关联一致；验证见`.local/audits/tencent-mcp-export-20261102/`。旧网页Cookie导出连接器及其CLI参数已删除，不保留回退分支。宿主全局Token供留学整本下载与工单反馈追加共同使用；项目只保留一个共享MCP客户端。

工作区`.private/tencent-source.json`仅配置`file_id`与`token_file`，后者指向宿主全局私有Token文件。当前来源为《FY27 前途-市场看板》，不在代码中写入Token。不需要浏览器登录profile、Cookie文件或旧TENCENT_DOC_ID/URL/COOKIE环境变量。Token失效或额度/权限不足时失败退出并报告，不能伪造成功。

## 2026-10-09历史标准化验收

Chrome实抓完整Excel导出流程，并用独立Python重新导出下载成功。用户提供的6—8月腾讯业务历史已一次性标准化并写入本地隔离留学仓，保留9月并接入10月；当时标准历史Snapshot为 `snapshot_study_abroad_cloud_aligned_20261009_v5`。当前Snapshot以工作区 `Work/StudyAbroad/current.json` 为准。这份腾讯资源与签约历史独立于人员产能使用的6—8月确认汇总。BI仓与 `Work/workspace.json` 不变，未激活网页或真实发送。本轮源码与6—9月标准历史已按A/B分包同步Grok，云端本人登录态重新抓取10月：233工单、451,960元现金、人头留学12／小语种10；本机通过同一回传原件已对齐。云端同批看板／人员预览和8空跑／18组包通过，正式网页与通知尚未切换。

历史规则由用户明确确认：6月按颜色及逐笔确认结果归属；6/7月小语种“签约金额”为实收；缺客户／学员编号暂按姓名去重，留学与小语种分域，后补唯一编号时桥接；7月两日期冲突采用完整日期7月7日。8月两条无实缴金额续签保留NULL和缺金额标记，不填0、不计现金完成。

2026-11-26 业务复核确认，签约和实缴无法匹配个人时，来源明确为线上或线下的金额计入团队完成，保留原始人员和组别，只记团队。六月《留学签约》第57行 50,000 元记线下其他，《语培签约》第54、55行 7,000 元和 6,300 元记网络其他；六月留学第54行 13,000 元仍归 SSC。七月《语培签约 (核算)》第53行 6,800 元按同一规则计入线上。

正式看板的留学工单、签约和实缴金额、签约人头统一按[留学经营口径](integration-guide.md#22-隔离留学仓与腾讯更新现行)汇总。线上包含虚拟人，各级统计剔除 SSC，总计保留国际市场，留学和小语种人头分别去重。日常增补使用线上腾讯文档和已校正的历史 Snapshot，按明确月份更新，6—9 月一次性历史 Excel 作为核对与追溯原件。

7月资源仅在资源ID、分单日期和已有团队均一致时，以腾讯原表的人工归属补齐空个人归属（565条）；原空值、匹配依据及来源原件保留。少量双意向类型以同资源ID在腾讯表的优化后咨询类型解析，每条资源仍只计一次。6月CRM无业务资源ID的行使用独立技术记录键保留明细，不伪造资源ID。现行资源重复规则按传入来源顺序和源行顺序保留首条非空资源ID记录，后续相同ID无论日期或字段是否冲突均跳过。

2026-10-09 验收时的历史入仓金额为 6月2,781,483.10元、7月3,772,637.35元、8月3,745,488.80元、9月2,347,804.40元。客户/学员姓名仅保存在私有标准表，临时人头键使用摘要。覆盖FY27当前年度，不计算同比；业务确认的官方记分卡及历史人员产能记分结果保持原地，不被明细核算值覆盖。

## 下载合同

唯一在线导出路径：

1. `manage.export_file(file_id)` 创建导出任务，取得`task_id`。
2. `manage.export_progress(task_id)` 每5秒查询一次，`progress=100`后取得临时文件地址。
3. 无Cookie下载腾讯COS文件，校验HTTPS域、HTTP状态、ZIP/CRC、工作簿及工作表关系完整性，保留原件、SHA-256和字节数。

```bash
python3 -m data_acquisition.connectors.tencent_docs \
  --file-id '<腾讯文档file_id>' \
  --token-file '<宿主全局私有Token文件>' \
  --output-dir '<本次唯一run原件目录>'
```

导出目录中的`export-task.json`保存文件身份、任务ID及完成原件的路径/hash，不保存Token和签名URL。同目录中断恢复只查询原任务；创建任务时结果未知则明确报错，不盲目重提。已下载文件仅在hash与XLSX校验通过后复用。系统curl校验TLS，不关闭证书验证、不跟随下载重定向，凭据及签名URL不进入命令行参数或回执。

## 工单反馈追加合同（2026-11-02）

留学整本下载与工单反馈追加共用 `TencentDocsMCPClient` 和私有Token，但属于两个独立操作。追加入口读取本地已导出的BI工单工作簿，按私有配置的 `start_date` 与显式 `--as-of-date` 筛选 `分配时间`，以工单 `ID` 识别已存在记录；只追加远端缺少的ID，重复ID内容冲突则失败。每批写入后回读校验；`素材ID`、`账号来源`、`工单跟进情况`三列由人工维护，追加时不写入、不覆盖。

```bash
python3 -m data_acquisition.jobs.sync_content_work_orders \
  --workspace '<客户工作区>' --source-file '<本批BI工单工作簿>' \
  --as-of-date '<YYYY-MM-DD>' --run-id '<本次唯一run_id>'
```

默认配置为工作区 `.private/content-work-orders.json`，其中绑定目标文件／页签、Token文件、104个目标列和起始日期。成功或失败回执写入 `Work/ContentWorkOrders/Runs/<run_id>/receipt.json`；同一 `run_id` 不可复用。该入口会将新工单实际追加到配置的腾讯文档，不属于只读下载。

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

资源重复按传入来源顺序和各来源中的Excel行顺序处理：保留非空资源ID首次出现的记录，之后同ID记录无论同日、跨日或字段不一致均跳过，并计入现有 `superseded_resource_rows` 诊断；空资源ID行不按业务ID去重。该规则适用于新构建，不回写已生成的Snapshot。留学合同统计月份统一从归档日期生成；来源归档月份为空或与归档日期月份不一致时，仍以归档日期月份核算。

## 标准历史复用与月份更新

一次性原件清洗使用 `--legacy-file` 明确提供六月、七月、八月原件，并以 `--legacy-date-preference full` 采用已确认日期规则。规范源的三张表为 `resources/contracts/languages`，保留日期、金额、归属、团队、客户键、技术记录键及原文件摘要／页签／行号。`--standardized-source` 直接校验并导入已清洗的三表源，适用于Grok的B包，不重新解析旧原件或颜色。

后续通过 `--history-snapshot-id` 从明确的当前留学Snapshot受控读取标准历史，保留非刷新月份；只替换指定月份，空月也明确清空，不逐日追加。历史查询回执、父Snapshot的manifest/lineage摘要及读取器版本均记录到新版本。`normalized_history.warehouse`保留读取时捕获的原机器路径作为历史证据；跨工作区读取时只按`source_run_id`与`source_snapshot_id`在当前`Work/StudyAbroad/Runs/`中定位父Snapshot，并核验本地manifest、lineage及三份受控查询证据，不使用捕获路径定位数据。

一键下载与月份更新入口：

```bash
python3 -m data_acquisition.jobs.update_tencent_study_abroad \
  --workspace '<客户工作区>' \
  --run-id '<本次唯一run_id>' --snapshot-id '<本次新snapshot_id>' \
  --through-date '<明确来源截止日>' --refresh-month '<YYYY-MM>'
```

该入口从 `Work/StudyAbroad/current.json` 获取明确父Snapshot身份，从工作区私有配置读取MCP文档与Token绑定，下载后只刷新指定月份，不再读历史Excel。失败保留上一成功指针。服务器raw接收流程仍可显式提供已验证的本地`source_file`，该模式不联网，也不需要MCP配置；这属于当前原件入仓合同，并非旧Cookie兼容。

看板与人员贡献都消费同一个显式留学Snapshot；人员贡献不再在管理构建中另取九月参考工作簿。跨业务工单由BI工单一级渠道精确为“双分”（留学向语培输出）和腾讯标准行归属组“国际市场”（语培向留学输出）识别，不再读取原资源流转表。旧 `资源流转.xlsx` 及双分流转明细只保留历史追溯，不参与当前计数、姓名覆盖或缺失门禁；6—8月业务确认的留学／小语种人员历史结果继续只读沿用，9月人员表仅作对账。名单与既定共创分摊由人员产能模块处理；腾讯签约／实缴按本行已确认个人或明确团队归属核算，个人不可匹配时明确团队金额只计团队。`update_tencent_study_abroad` 只更新留学资源与签约数据，不抓取广告费用；广告费有独立的 `prepare_full_daily` 采集／候选入口，仍可按明确来源映射登记手工来源，见[看板费用与ROI](dashboard-advertising-costs.md)。留学更新流程不会自动启动广告采集、发布或发送；具体范围遵循对应日更入口。

本轮证据：`.local/audits/study-history-678-20261009/`；前轮抓取证据：`.local/audits/tencent-study-capture-20261009/`。会话与原始请求位于私有忽略目录，不进入Git或公开交付。

## 每日双仓更新与消费者门禁

来源生产者为 `data_acquisition/deploy/run_daily_warehouses.sh`，并列调用现有BI重建与腾讯更新；两源各尝试一次，任一失败即整体失败。保持各自已成功的不可变Snapshot，不回滚或伪造另一仓；`Work/DailyWarehouseRefresh/current.json`记录最新尝试，`last_good.json`保留上一成功配对。刷新期间及失败状态不允许新发布／投递。

看板日常和日推日常不重复抓取来源：前者先校验当天联合回执及两仓当前身份后构建／发布；后者校验同一联合配对与同批通知再投递。腾讯历史从已标准化仓受控读取，只替换上海当天所在月份，不因新月份导出缺旧月而清空历史。月底迟到历史需明确来源另补，不无证推数据。

数仓例行只读取已绑定工作区，MCP来源身份与Token路径来自其私有配置：

```bash
PYTHON='<warehouse虚拟环境Python>' PROJECT_ROOT='<warehouse根>' \
WORKSPACE='<客户工作区>' \
bash data_acquisition/deploy/run_daily_warehouses.sh
```

脚本默认按上海日期与时分秒生成新run和两仓Snapshot身份；也可显式传入AS_OF_DATE、RUN_ID、BI_SNAPSHOT_ID、STUDY_SNAPSHOT_ID。来源任务通过官方MCP直接导出，失败阻断原有消费者门禁，不刷新或读取腾讯文档Cookie。

以下为2026-10-09云端历史回执，不代表当前本地日程；现行本地bi-3每日09:30业务优先流程见[完整日更说明](archive/shadow-bi-full-daily-20261028.md)。当时数仓09:30、看板09:45、日推10:24为三条原例行；本次只更新执行正文，不另建任务、不改时刻／启停／通道。代码和失败门禁已安装云端并通过261项／67subtests回归；三条原Routine均已获得UpdateRoutine回执，原ID／时刻／开关保持，最终提交正文和摘要留在 `.local/sync/inbox/grok-daily-dual-20261009/prompts/`。平台无法完整回读正文，不把提交副本当全文回读。真实联合运行 `run_daily_sources_20261009_210221` 已结束：BI因本人登录超时失败，腾讯在同轮成功更新 `snapshot_study_abroad_20261009_daily_210221`，6—9历史不变。联合failed已阻断下游，未新建生产batch／发布／发送；BI本人扫码后才可验收双源成功及新批预览。失败来源终态状态已修复，不改旧运行收据。

腾讯当前导出不提供删除／回收状态列。个人状态开关保留，只影响源中有明确状态的行；缺状态行不被推断为删除或回收。
