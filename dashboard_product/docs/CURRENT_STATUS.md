# 当前状态

更新时间：2026-09-09

## 已完成

- FY27 看板展示、团队/业务组/人员筛选和本地季度切换已完成。
- 当前工作区 Snapshot 为 `snapshot_bi_operations_20260908`。2026-09-05 的 Q1 对账结论仍是已验收基线；后续发布以当前 Snapshot 新生成的 artifact 为准。
- 三个团队已纳入看板：线下市场、线上私域（虚拟人团队）、线上平台。线下市场个性化配置已完成；线上私域有部分人员；线上平台人员配置仍空。
- 刷新链路固定为一次 `refresh` 生成全量 `artifact.json`，再 `render --all-booklets` 生成四分册 HTML：`full.html` / `online_private.html` / `online_platform.html` / `offline_market.html`。全量 JSON 不上传公网。
- 公网入口 `http://dashboard.apinova.cn` 为 HTTP + basic auth 分册；`/healthz` 匿名。旧单文件 `current.html` 已退出日更。
- 例行「看板日更」每天 10:00（Asia/Shanghai）挂许家印，在云电脑 `/home/box/oxhor/dashboard` 跑 `deploy/publish_static_dashboard.sh`。本机 Codex 定时已停。
- 现金关联到工单时采用工单业务组，未关联时回退现金表团队；现金通过工单 ID 左连接工单表获取渠道，口径包含被动、新生、正向报入现金。
- 未关联工单的现金统一在渠道维度显示为 `暂无归属`；团队归属规则已固化为：工单匹配、虚拟人、线上、TMK、校代、默认线上平台。
- 线下市场个人统计已按工单业务组隔离后再匹配人员；校代系统资源在活动名未携带人员时使用资源描述「市场人员：」归属，现金通过工单 ID 继承该归属。
- `market_total` 汇总三个团队且不包含人员；同比支持渠道、年级和高中/大学学校→年级下钻，年级按固定学龄顺序排序。
- 顶部现金和工单汇总卡片均显示当期、同期、同比、目标和完成率。
- 人员区支持留学预备/高中/大学业务团队筛选；空白占位保留在配置但不展示。个人工单与现金均可按工单维度的一级、二级渠道下钻。
- Saved Query 只校验 SQL manifest/hash；运行时显式传入的当前 Snapshot 由 Data Platform 校验仓库身份，不再绑定某个历史 Snapshot。
- 钉钉人员进度代码已落地：一次读取同一份 artifact，按五通道生成 `people.png` / `details.xlsx` / markdown。日更脚本不自动群发。

## 钉钉通道

| 通道 | 群 | 本机 `.env.server` |
|---|---|---|
| `online_private` | 线上私域 / 虚拟人 | 空，发送时跳过 |
| `online_platform` | 线上平台 | 空，发送时跳过 |
| `offline_youth` | 线下青少 | 已填 webhook/secret |
| `offline_high_school` | 线下高中 | 已填 webhook/secret |
| `offline_university` | 线下大学 | 空，发送时跳过 |

密钥只在 C 层 `.env.server`（mode 600）。云电脑独立运行必须单独 CopyToBox 该文件，禁止进公开 Git、禁止贴聊天。

## 个性化配置进度

- 已完成：`offline_market`（线下市场）。`pending`、`probation` 和 `vacant` 只表示人员编制状态，不是团队配置缺口。
- 部分完成：`online_private`（线上私域/虚拟人团队）已有人员，尚未宣称配置完成。
- 待完成：`online_platform`（线上平台）人员配置仍空。

## 当前合同

刷新必须在父目录执行：

```bash
python3 -m dashboard_product.refresh refresh --workspace customers/bi_operations --run-id run_dashboard_<id>
python3 -m dashboard_product.refresh render --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json --all-booklets
python3 -m dashboard_product.notify send --artifact customers/bi_operations/Output/Dashboard/run_dashboard_<id>/artifact.json --dry-run
```

`dashboard_actuals/v6` 是刷新唯一消费的 Saved Query，参数为 `[start_date, end_date]`。`attributed_passive_reported_cash/v1` 是逐笔对账底稿，不被刷新自动调用。

artifact 的业务组字段包括 `monthly_actuals`（FY27 12 个月）和 `prior_monthly_actuals`（FY26 对应 12 个月）；同比渲染按所选季度切同一索引段。旧的 `prior_totals`、`metrics` 和 `bus_monthly` 结构已废弃。

## 已知边界

- 未映射业务组不进入正式看板汇总；若底层快照重新出现此类记录，需先完成 Bridge 对齐。
- 团队兜底归属是业务分配，不代表工单关联成功。
- 生产发布使用 `deploy/publish_static_dashboard.sh`；钉钉使用 `python3 -m dashboard_product.notify send`，二者分开。
- 负向现金仍按数据事实保留为负向现金，原因需业务确认。
- 本轮未上 TLS：HTTP + basic auth 会把密码以 Base64 传输。

## 关键路径

- 代码：`refresh.py`、`render_template.py`、`booklets.py`、`digest.py`、`notify.py`、`notify_render.py`
- 配置：`config/project_targets.json`、`config/people.json`、`config/saved_queries.json`、`config/dingtalk.json`
- 密钥：`dashboard_product/.env.server`、`deploy/secrets/`（C 层，不进 Git）
- 已验收看板基线：`customers/bi_operations/Output/Dashboard/run_dashboard_newstudent_final_20260905/`
- 当前 Bridge：`artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json`
