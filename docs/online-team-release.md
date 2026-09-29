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

- 留学默认不含 SSC：年度目标5315及原月拆；包含SSC开关打开后：年度6715，按5315原比例拆月并取整，全年合计不变。
- 开关选择同批预计算的实际、目标、同比、趋势、渠道和国家拆解，不在浏览器重新判定业务归属。
- 语培、留学渠道分组，支持局部业务线筛选、搜索和组内排序。
- 语培现金继续按已确认的看板归属；旧通知与看板的差异未借此次网页替换修改通知。
- 留学现金实际待接入，不含SSC现金目标没有提供，保持未配置。
- 原群、发送节奏与当前通知入口保持现状；P3 的共用结果通知接入另行施工。

## 云端安装及回执

Grok 按 A 层明确清单和 SHA-256 收包。现有未知改动先保留并报告差异，不全量覆盖 checkout，不携带 customers、输入、数仓、整个 runs 或凭据。确认 dashboard 的共享依赖能正确导入；缺少 data_acquisition 时按现有共享模块布局接到 warehouse 的实际代码，不能复制客户数据补依赖。

回执至少包括：包/文件哈希、实际安装路径、模块导入位置、合成测试结果、一次不发布的实际刷新/导出、生成 HTML 的 Snapshot/截止日/哈希，以及原日更实际生效的任务 ID、命令、时间和时区。必须回读实际任务配置，不能只修改本地影子任务文件就宣称生效。

本地阶段验收证据和截图留在被忽略的市场 Reports 目录，不进入代码包。生产刷新入口不依赖该本机目录。
