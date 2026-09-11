# 当前状态

更新时间：2026-09-11

## 已完成

- FY27 看板展示、团队/业务组/人员筛选和本地季度切换已完成。
- 当前工作区 Snapshot 为 `snapshot_bi_operations_20260911_r2`。2026-09-05 的 Q1 对账结论仍是已验收基线；后续发布以当前 Snapshot 新生成的 artifact 为准。
- 四个团队页签：线下市场、线上私域（虚拟人团队）、线上平台、市场总计；并列第五页「市场人员产能」。线下市场个性化配置已完成；线上私域有部分人员；线上平台人员配置仍空。
- 刷新链路固定为一次 `refresh` 生成全量 `artifact.json`，再 `render --all-booklets` 生成四分册 HTML：`full.html` / `online_private.html` / `online_platform.html` / `offline_market.html`。全量 JSON 不上传公网。
- 公网入口 `http://dashboard.apinova.cn` 为 HTTP + basic auth 分册；`/healthz` 匿名。旧单文件 `current.html` 已退出日更。
- 例行「看板日更」每天 10:00（Asia/Shanghai）挂许家印，在云电脑 `/home/box/oxhor/dashboard` 跑 `deploy/publish_static_dashboard.sh`。本机 Codex 定时已停。
- 现金业务组只看现金表团队，不跟工单改口；现金通过工单 ID 左连接工单表只取渠道和人员。口径包含被动、新生、正向报入现金。目标区青少+初中滚成留学预备，渠道/年级同比用青少、初中、高中、大学。
- 无法判断、校区资源无法归属、需要判定和空团队的工单默认不进看板；临时例外：跟进顾问为张艺彤时按留学预备回落，再按年级校正拆青少/初中。
- 未关联工单的现金统一在渠道维度显示为 `暂无归属`；团队归属规则已固化为：工单匹配、虚拟人、线上、TMK、校代、默认线上平台。
- 线下市场个人统计已按工单业务组隔离后再匹配人员。活动名对不上时：SQL 把「市场人员：」抽进 `entry_person`，Python 再用「姓名市场资源」、资源录入人和去掉旧活动串后的资源描述正文兜底。现金用工单 ID 对全量工单数仓连，不限本绩效月。看板 artifact 不含完整资源描述列。
- `market_total` 汇总三个团队且不包含人员。完成进度目标区仍是留学预备/高中/大学；`teams[].yoy_groups` 和渠道/年级下钻改用青少、初中、高中、大学。高中、大学支持学校→年级下钻。业务组同期对比下增加渠道同期对比单表（二级渠道 × 四组同比，含组内现金占比）；右侧合计该渠道全部现金/工单及占总现金占比，按合计现金降序，底行总计。市场总计目标表可展开业务组查看三个团队明细及现金/工单占比。
- 顶部现金和工单汇总卡片均显示当期、同期、同比、目标和完成率。
- 「市场人员产能」页签固定全年。人员表列已产生现金、统一标准产能 80 万、时间进度完成率，按现金从高到低排，可筛线上/线下。六维雷达为工单数、签约量（现金 `学员编号` 去重，共记 `1/N`）、转化率、渠道&校代贡献、TMK贡献、活动贡献；个人框对照本团队均值：线下按留学预备/高中/大学，线上私域整队一个均值。一级渠道含 TMK 计 TMK；一级渠道为市场活动且二级为异业渠道或线下校代计渠道&校代；一级渠道为市场活动的其余二级计活动。平台和未匹配工单现金不进这三块。不进钉钉。
- 人员区支持留学预备/高中/大学业务团队筛选；空白占位保留在配置但不展示。个人工单与现金均可按工单维度的一级、二级渠道下钻。
- Saved Query 只校验 SQL manifest/hash；运行时显式传入的当前 Snapshot 由 Data Platform 校验仓库身份，不再绑定某个历史 Snapshot。
- 钉钉人员进度代码已落地：一次读取同一份 artifact，按五通道生成 `people.png` / `details.xlsx` / markdown。日更脚本不自动群发。
- 线下大学通道播报图展示工单 + 人头；落后仍按工单。人头来自已归属被动新生正向现金的去重 `学员编号`，不含 1500 门槛；同一条现金归属 N 人时每人计 `1/N`。明细表人员进度额外带现金目标/完成/完成率。其余通道仍是工单 + 现金。
- 钉钉人员名单以 `config/people.json` 覆盖 artifact 旧花名册。线上私域小初提能组为潘体学（工单 25、现金 50,000）；历史活动名含杨玉林的记录不再计入潘体学。

## 钉钉通道

| 通道 | 群 | 本机 `.env.server` |
|---|---|---|
| `online_private` | 线上私域 / 虚拟人 | 已填 webhook/secret |
| `online_platform` | 线上平台 | 空，发送时跳过 |
| `offline_youth` | 线下青少 | 已填 webhook/secret |
| `offline_high_school` | 线下高中 | 已填 webhook/secret |
| `offline_university` | 线下大学 | 已填 webhook/secret |

密钥只在 C 层 `.env.server`（mode 600）。云电脑独立运行必须单独 CopyToBox 该文件，禁止进公开 Git、禁止贴聊天。

## 个性化配置进度

- 已完成：`offline_market`（线下市场）。`pending`、`probation` 和 `vacant` 只表示人员编制状态，不是团队配置缺口。
- 部分完成：`online_private`（线上私域/虚拟人团队）已有人员。小初提能组现员为潘体学，工单目标 25、现金目标 50,000；尚未宣称整队配置完成。
- 待完成：`online_platform`（线上平台）人员配置仍空。

## 当前合同

刷新必须在父目录执行：

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/bi_operations --run-id run_dashboard_<id>
python3 -m dashboard_product.refresh render --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json --all-booklets
python3 -m dashboard_product.notify send --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json --dry-run
```

`dashboard_actuals/v9` 是刷新唯一消费的 Saved Query，参数为 `[start_date, end_date]`。本地 Saved Query 目录只保留 v9；v1–v8 已删除，没有兼容入口。输出第 12 列为 `student_id`。`attributed_passive_reported_cash/v1` 是逐笔对账底稿，不被刷新自动调用。

目标区 `groups` 仍是留学预备/高中/大学；同比区 `yoy_groups` 是青少/初中/高中/大学。两边都带 FY27 `monthly_actuals` 和 FY26 `prior_monthly_actuals`，渲染按所选季度切同一索引段。旧的 `prior_totals`、`metrics` 和 `bus_monthly` 结构已废弃。

## 已知边界

- 未映射业务组不进入正式看板汇总；若底层快照重新出现此类记录，需先完成 Bridge 对齐。
- 团队兜底归属是业务分配，不代表工单关联成功。
- 生产发布使用 `deploy/publish_static_dashboard.sh`；钉钉使用 `python3 -m dashboard_product.notify send`，二者分开。
- 负向现金仍按数据事实保留为负向现金，原因需业务确认。
- 本轮未上 TLS：HTTP + basic auth 会把密码以 Base64 传输。

## 关键路径

- 代码：`refresh.py`、`render_template.py`、`capacity.py`、`booklets.py`、`digest.py`、`notify.py`、`notify_render.py`、`sql/dashboard_actuals.sql`、`sql/notify_work_orders.sql`
- 配置：`config/project_targets.json`、`config/people.json`、`config/capacity_targets.json`、`config/saved_queries.json`、`config/dingtalk.json`
- 密钥：`dashboard_product/.env.server`、`deploy/secrets/`（C 层，不进 Git）
- 已验收看板基线：`customers/bi_operations/Output/Dashboard/run_dashboard_newstudent_final_20260905/`
- 当前 Bridge：`artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json`
