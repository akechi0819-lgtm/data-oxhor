# 线上团队融合看板上线说明

2026-09-29 用户已验收 P0/P1，授权替换线上团队特供网页、提交 Git，并同步 Grok Bot，在 2026-09-30 既有看板日更中刷新新版。本次不改变主看板、线下特供的业务计算，也不迁移或新增钉钉发送任务。

## 正式入口

- 代码：`dashboard_product/online_team/`。
- 对外地址仍为 `http://dashboard.apinova.cn/online_market_special.html`；主页面链接文字改为“进入线上团队融合看板”。不把本机 localhost 链接写入远端页面。
- 发布版是一个包含 CSS、JS 和必要展示数据的自包含 HTML。服务器仍只托管静态文件，无需增加 BI 服务、Node 服务或 Nginx 资源目录。
- 多文件 site、共同结果、逐笔明细和查询证据留在工作区 Output，不上传整个输出目录。

## 刷新与导出

```bash
python3 -m dashboard_product.online_team.build \
  --workspace customers/bi_operations \
  --snapshot-id <工作区当前明确Snapshot> \
  --run-id run_online_team_<唯一编号> \
  --as-of-date <上海日期YYYY-MM-DD>

python3 -m dashboard_product.online_team.export \
  --site-dir <workspace>/Output/DashboardOnline/<run_id>/site \
  --output <workspace>/Output/DashboardOnline/<run_id>/online_market_special.html
```

`--as-of-date` 省略时按 Asia/Shanghai 当前日期取值，不固定在验收日期。数据截止日取工单、现金最大日期较早者，并截到 as-of 前一天。Snapshot 必须与该工作区当前指针一致，所有查询保留显式身份和回执。输出受限于工作区 Output；重复使用目录必须匹配同一批次身份及查询参数。

必需资料是当前主 Snapshot、兼容 Bridge、清洗参考 `Input/Reference/留学-FY26-资源表.xlsx`、共享人员规则和现有语培目标。`Input/Reference/留学板块-官方记分卡.json` 仅用于历史对照：存在时读取，缺失时明确显示未载入，不以硬编码历史数字补齐，也不影响已确认目标的计算。名单外的空团队顾问在结果说明中提示数量，不自动归为留学。

## 发布与原任务接入

既有 `deploy/publish_static_dashboard.sh` 继续作为日更入口，现会：

1. 按原流程刷新、校验并渲染主看板。
2. 使用该主看板 artifact 的显式 Snapshot 生成新版线上团队页，并导出单 HTML。
3. 所有本地产物生成成功后上传 `full.html` 和 `online_market_special.html`；校验线上页 SHA-256，先准备临时文件，再逐文件原子替换。

因此应更新原看板日更使用的代码和说明，不另建重复定时任务。数据更新仍先于看板；运行前需确认当天数仓刷新完成，不能为了凑次刷新复用验收 Snapshot。

仅发布线上页时使用：

```bash
SITE_HTML=<本次online_market_special.html> \
  dashboard_product/deploy/publish_online_market_dashboard.sh --dry-run

SITE_HTML=<本次online_market_special.html> \
ENV_FILE=<原C层发布凭据路径> \
  dashboard_product/deploy/publish_online_market_dashboard.sh
```

`--dry-run` 只校验 HTML，不读取发布凭据、不上传。实际发布只安装线上 HTML，不覆盖主/线下页面或发送钉钉；原 `ARTIFACT_JSON` 影子渲染输入已退出此脚本，不保留旧发布分支。

## 已验收口径

- 2026-09-30用户纠正：SSC在所有统计范围统一排除，取消开关；全年工单目标6715，按5315原月度比例拆分。目标差额来源为小语种，不是SSC。
- 当期、同期、趋势、渠道、国家和每日新增使用同一SSC排除范围；不以目标差额补造小语种实际。
- 语培、留学渠道分组，支持局部业务线筛选、搜索和组内排序。
- 语培现金继续按已确认的看板归属；旧通知与看板的差异未借此次网页替换修改通知。
- 留学现金实际待接入，不含SSC现金目标没有提供，保持未配置。
- 原群、发送节奏与当前通知入口保持现状；P3 的共用结果通知接入另行施工。

## 云端安装及回执

Grok 按 A 层明确清单和 SHA-256 收包。现有未知改动先保留并报告差异，不全量覆盖 checkout，不携带 customers、输入、数仓、整个 runs 或凭据。确认 dashboard 的共享依赖能正确导入；缺少 data_acquisition 时按现有共享模块布局接到 warehouse 的实际代码，不能复制客户数据补依赖。

回执至少包括：包/文件哈希、实际安装路径、模块导入位置、合成测试结果、一次不发布的实际刷新/导出、生成 HTML 的 Snapshot/截止日/哈希，以及原日更实际生效的任务 ID、命令、时间和时区。必须回读实际任务配置，不能只修改本地影子任务文件就宣称生效。

本地阶段验收证据和截图留在被忽略的市场 Reports 目录，不进入代码包。生产刷新入口不依赖该本机目录。

## 2026-09-30 交付回执

- 本地代码提交：`9d6f52070673f476325e1d80e2d4fa7270307a28`，未推送公共远端。干净暂存副本完整回归212项通过。
- A层包SHA-256：`5335aa992bc1a7c85d536bfe1b44cf749191a864f64c00bb3ac81efc50f078e5`。Grok已按清单安装23个文件，README保留既有运维说明并合并；共享依赖核对一致。
- 云端17项合成测试通过；使用当前`snapshot_bi_operations_20260929`、明确as-of `2026-09-29`构建`run_online_team_20260930_install`，截止9月28日。9月语培837单/现金1053580.90元，留学不含SSC560/420、含SSC661/531，与验收值一致。
- 新HTML已生成，SHA-256为`4f15bcb965efacccfa18900963a6971808d5cd429514a059c7fa9880eff63582`。即时发布被SSH的`Exceeded MaxStartups`及连接重置阻断，未覆盖公网旧页；不能把代码安装视为网页上线。
- 许家印通过应用读取实际生效例行：`da973a5e-271f-57ef-9037-bedf4c5822d2`，启用，Asia/Shanghai每日10:06，下一次2026-09-30 10:06。旧本地影子`automation-1788756904696`及10:00不作为有效排期。应用未暴露例行正文，已另行交接持久日更运行说明，要求使用更新后的发布入口且禁止旧渲染覆盖。
- 完整安装回执留于`.local/sync/inbox/20260930-online-team-release/RECEIPT.md`（忽略目录）；其中例行段是安装执行者读取的旧影子，调度事实以上述应用回读为准。仍需成功发布后的HTTP/HTML哈希回执。

上述最新SSC规则覆盖旧交付回执的双视图口径；旧回执仅保留历史事实，云端更新须另有发布确认。

## SSC纠正本地验证

新运行 `run_online_team_no_ssc_20260930_final` 使用本地显式 Snapshot `snapshot_bi_operations_20260929_online_push`、as-of 2026-09-29、数据截止2026-09-28。9月留学560/531、全年2258/6715；语培当前完成仍为9月837、全年3600。18项模块测试通过，17期间均不含SSC渠道，新业务明细不含SSC记录，浏览器确认开关移除及年度目标6715。旧范围仅保留为对账基线，未修改原始数仓。本次本地修改尚未同步云端。
