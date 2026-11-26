# P2 复用规则清单

> 本文记录 2026-10-22 的 P2 阶段口径与验收。留学线上、SSC 及总计的现行范围已于 2026-11-26 更新，使用[集成指南](integration-guide.md#22-隔离留学仓与腾讯更新现行)和正式 SQL 查询结果；本表保留历史内容以便追溯。

规则不是新配置平台：下列模块继续是业务定义，`calculation.py`只集中编排。每条规则的P0同批对账见P2验证记录，不以外部页面差额倒推新口径。

| 规则与优先顺序 | 输入→输出/消费 | 源码与核对 |
|---|---|---|
| 日期/清洗/来源行 | 显式Snapshot受控SQL→语培订单、现金及覆盖；保留原始状态和来源键 | management/sql/{orders,training_details,coverage}.sql；facts.normalize_facts；事实集合全字段核对 |
| 市场总盘范围 | 已确认留学边界先排除，空团队已确认留学顾问同样排除；总盘工单与normalized training独立 | sql/market_orders.sql、market_totals.attach_market_orders；不能调平观远160/23/20 |
| 团队归属 | 原团队→已确认顾问映射/学校代理修正→精确已确认现金覆盖；保留原团队及理由 | facts.py、fallback_mapping.py、confirmed_cash_team_overrides.json；逐事实比较 |
| 人员资格及匹配 | 当前花名册、历史资格、虚拟人活动允许条件和姓名匹配；不以当前在职条件改掉历史团队完成 | operations/personnel.py、people.json、aggregate._roster/_personal_weighted_facts；全部期间个人视图 |
| 共创、接收、输出 | 原来源标记优先；BI“双分”、留学国际市场、明确创造/接收人员及括号规则→贡献桶/原Decimal权重 | personnel_contribution._events/_allocation/build_contribution；逐贡献、未归属marker回查 |
| 工单状态 | 四态由两个开关组成，默认排除删除/回收、包含死单；仅影响既定个人工单及相关率 | personnel.order_status_allowed；现金、人头、目标、资格不随工单过滤；全部四态核对 |
| 期间与自然/绩效月 | 团队自然期间；个人上月26日至本月25日与自然月并存；产能自然月；年度六维独立 | aggregate._calendar_month_window/_people_for_period、personnel.date_to_perf_month、capacity_radar；有限窗口全比 |
| 人头/比例 | 原学员编号去重、同人多人份额取最大；留学/小语种及跨系统不随意合并；固定本人或全渠道分母 | aggregate._personal_actual、cash_share.py、breakdowns.py；事实身份及预计算视图比较 |
| 团队作用域 | 总盘和活动不随目标区团队变化；被动现金占比分子随团队，分母固定 | team_scopes.attach_team_scope_views、cash_share；全部期间目标区嵌套结果核对 |
| 业务组选择 | 青少/初中/高中现有7组合，仅影响既定区域 | enhancements.selection_views；7×17期间完整核对 |
| 留学事实与归属 | 本sheet归属权威；渠道已确认决策及关联BI年级证据补齐；现金不被资源行覆盖归属；SSC/unassigned留总盘 | study_abroad_facts/channels/grade/query；事实来源行及全部团队/国家视图核对 |
| 留学覆盖与历史 | 独立仓截至10/13，无同比；活动保留各来源自己的有效累计；6—8月已有汇总不生成明细 | personnel_history.load_history/apply_history；coverage与历史原表、视图核对 |
| 官方记分卡 | 官方确认覆盖内优先；绑定文件但不入仓，不自动回写目标；与数仓不同时保留差异 | Input/Reference/留学板块-官方记分卡.md/json；既有两条not_comparable保留 |
| 目标与汇总 | 现有目标配置及缺失状态；大学另一业务线10%按原规则，2026年11月语培线下人员留学目标优先采用花名册显式确认值；缺配置不补0 | aggregate.py、project_targets/offline_market_targets/study_abroad_targets/capacity_targets；全部期间目标比较 |
| 线上平台与费用 | 业务事实先按原线上范围/平台匹配；费用保留来源粒度；共同业务组/平台/覆盖窗口算ROI，期间费不摊日 | platforms.py、advertising_sources/costs.py、sql/advertising_rollup.sql；全部线上期间、费用及匹配依据核对 |
| 活动/学校/渠道 | 活动独立累计；学校×年级、渠道×业务组各自人数与分母，不加总分组人数冒充总数 | aggregate/breakdowns；活动5049项、各期间分析全比；P3再验页面交互 |

边界：人员待核数组为空只代表既有affected_people待核范围内无记录；仍有49条未匹配跨线marker诊断，不得据此称所有归属已解决。负向现金只称负向现金，原因不自动解释成退款。库里保留原始行和未匹配信息，P3不能凭展示省略它们。
