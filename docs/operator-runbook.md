# 本地运维手册

使用共享仓库环境运行 `python -m ops`。先用 `ops status --day YYYY-MM-DD` 查看当天状态；测试用 `sh tools/run_tests.sh -v`。现网部署见[看板部署说明](../dashboard_product/DEPLOYMENT.md)。

## 正式 BI、服务器计算与固定发布

Mac 默认运行 `ops run business`，也可在当前 Python 环境运行 `python -m ops run business`。兼容现有调度命令 `data_acquisition.jobs.prepare_full_daily --publish`，该入口不再采集或发布费用。用 `ops status --day YYYY-MM-DD` 查看 `runtime/ops_state.db` 最近一次核验的来源日期、Superset 版本、当日日报与独立费用。若从其他主机执行日更，该主机的台账需单独查看。腾讯表三项读本日运行台账，无运行时显示已验证版本或尚无核验记录。

人工补全量时将 `orders.xlsx`、`cash.xlsx` 放入 `runtime/inbox/manual/YYYY-MM-DD/` 后运行 `ops run business --day YYYY-MM-DD --from-manual`，可同目录附 `tencent.xlsx`。未附腾讯表时仍走现有留学采集。工单及现金会用文件 SHA 写入补数清单并走原门禁。日报由服务器每日键在共享投递锁内判定。若已确认 8 条，则返回 `notify: skipped (already_sent_today)`；传输未知的条目由原服务保持阻塞。只更新看板的操作可用 `--no-notify`。

费用录入使用 `ops ingest-cost --input 费用.csv --platform xhs --confirm-zero 高中=YYYY-MM-DD`，同一命令也支持 XLSX、JSON 以及抖音、腾讯和 SEM。列名为日期、业务组、金额或 `date,business_group,amount`。业务组未出现在记录中的日期保留缺失，空金额仍为缺失，需要明确的业务组与日期声明才能录入零消费。SEM 需指定明细平台，零声明填 `高中/百度=YYYY-MM-DD`。费用独立候选沿用当前业务仓的封存数据与通知预览，经整仓发布更新费用视图，录入过程不调用日报入口。原生费用抓取保留在 `ops fetch-cost-optional`，用于产生本地核验资料。

腾讯历史账户日账以逐日明细为准，表头汇总差额不计入费用。腾讯有投放的业务组在 ROI 看板按缺日 0 元计算，留学预备没有腾讯投放；原始账目仍可区分缺失与已确认零消费。已确认的期间账单保留原周期。历史账单、群报及费用口径见[费用与 ROI](dashboard-advertising-costs.md)。

`runtime/releases` 只跟踪新入口登记的候选。每次成功发布后，保留当前、前一版本、月末与额外登记的引用，将超过 7 天且无引用的候选移至同级 `releases-cold`。需要保留其他候选时，把绝对路径填入 `runtime/release-references.json` 的字符串数组。保留处理结果可在台账查阅。

工单、现金导出按各自声明窗口核验必填列、非空、同窗行数和新表截止日。旧窗口行数减少超过一半，或新表截止日期不足时，先停在临时候选。历史补数按所声明的补数结束日校验，合并后的双表仍须覆盖到昨天。若回执显示 `EMPTY_EXPORT`，确认源系统导出后用同一请求重试，或按已校验的人工输入恢复流程处理。当前 BI 下载和人工清单没有可证明零事件日的来源回执，按实际日期门禁停下。既有保护式完成证明只适用于与证明绑定的来源。

SQL 日更传输前，以当前已验证发布为基线，在同一历史截止日对账。门禁明细写入本批 `sql-attempts/<release>/release-comparison.json`。核对覆盖日、源表行数及 FY27 市场总计的工单、现金和人头，留学与小语种人头分开判断。出现阻断时保留原看板版本，按回执中的来源表或指标排查。

本机看板认证生成器的密码本和输出目录默认位于 `~/.config/cowh-ops/secrets/`，可用 `COWH_SECRETS_DIR` 指定同等私有权限的目录。迁移至新分支前，若需要用旧生成器，可显式提供仓库外的 `--password-book` 和 `--dest`。

## 腾讯表同步

`ops sync-sheets --job content|dianping|grade9|all --day YYYY-MM-DD` 各表独立记录结果。投流沿用客户仓 `.private/content-work-orders.json` 及双仓就绪回执内已核验的工单原件。点评、初三使用显式 BI Snapshot，保持受控查询。可用 `--snapshot-id` 核验操作者所选身份。

点评和初三在客户仓 `.private/` 分别读取 `dianping-sync.json` 和 `grade9-sync.json`。配置包含 `file_id`、`sheet_id`、`token_file`、`start_date`。点评还需现有 `registry_path`，可配置标题行索引 `header_row`、已确认的 `campus_by_team` 和 `group_by_grade`。相对路径以配置文件所在目录解析。点评沿用登记的人工保护格、上次自动写入且读回核验值。表结构不匹配或未提交行需先查明原因。

初三若因源与目标字段集合不同而暂停，查看状态所列列名，核对目标表结构。未经确认的目标列改造留给表负责人。写入失败后先核对已有主键和读回回执再接续。部署切换日程前先按隔离测试验收，避免新旧调度同时写同一张表。

## 资料与清理

历史回执见 [archive](archive/)。现行客户工作区与历史证据继续使用既有路径。已入仓的过期传输原件按[维护指南](maintainer-guide.md)核对引用及权限后清理。
