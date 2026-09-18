# dashboard — 许家印（看板运维）

> 2026-09-16 模块切换：人员进度与钉钉推送已迁至 `monitoring_product/`，看板不再承担发送。新入口要求 workspace、snapshot-id、run-id、as-of-date、data-through-date；正式发送另需显式 env-file。共享花名册在 `workspace_modeling/operations/people.json`。本地迁移完成不代表云端任务已切换；详见项目根目录 `monitoring_product/README.md`。

## 职责
对已确认口径跑固定 saved query：`dashboard_actuals/v10` → refresh **一次**全量 artifact → 按团队板块渲四分册 HTML（`full` / `online_private` / `online_platform` / `offline_market`）→ **真发**到现有服务器（公网 `http://dashboard.apinova.cn/`，basic auth，匿名看不到全量）。

## 路径
- 根：`/home/box/oxhor/dashboard/`
- 代码：`dashboard_product/`（含 `deploy/` `config/` `docs/`）
- 合同：`agents/dashboard_publisher/AGENT.md`
- 密钥：`dashboard_product/.env.server`（mode 600，禁止进公开仓、禁止贴聊天）
- 分册门口：`dashboard_product/deploy/secrets/`（htpasswd / map / 初始密码，600；禁止进仓、禁止贴聊天）
- 数仓指路（合同只读）：`/home/box/oxhor/warehouse/customers/bi_operations`（本目录 `customers` → warehouse 软链；同用户 FS 可写，靠 SYNC/审计约束，非 OS 只读挂载）

## 环境
复用数仓 venv：
```bash
export PATH=/home/box/oxhor/warehouse/.venv/bin:$PATH
cd /home/box/oxhor/dashboard
```

## 常用命令
```bash
export PATH=/home/box/oxhor/warehouse/.venv/bin:$PATH
cd /home/box/oxhor/dashboard
RUN_ID=run_dashboard_$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)

python -m dashboard_product.refresh refresh --workspace customers/bi_operations --run-id "$RUN_ID"
ART=/home/box/oxhor/warehouse/customers/bi_operations/Output/Dashboard/$RUN_ID/artifact.json
python -m dashboard_product.refresh render --artifact "$ART" --all-booklets

# 钉钉人员进度：日更不自动群发。缺 webhook 的通道会被跳过。
python3 -m monitoring_product.notify send --workspace <workspace> --snapshot-id <snapshot_id> --run-id <run_id> --as-of-date <YYYY-MM-DD> --data-through-date <YYYY-MM-DD> --dry-run

# 日更默认真发（用户已拍板）：一次 refresh + 四分册上传，不传 artifact.json
./dashboard_product/deploy/publish_static_dashboard.sh
```

分册与 htpasswd 操作见 `dashboard_product/docs/AUTH_TEAM_BOOKLETS_RUN.md`。`/healthz` 仍匿名；业务页需登录。**本轮若未上 TLS，HTTP+basic auth 密码在网上裸奔。**

## 状态（2026-09-14）
- 薄包与 `.env.server`(600) 已落地。钉钉独立运行还依赖该文件里的 `DINGTALK_WEBHOOK_*` / `DINGTALK_SECRET_*`，必须走 C 层 CopyToBox，禁止贴聊天。旧 C 层包不含大学和线上私域密钥，发这两路前必须重拷。
- 当前工作区 Snapshot 以 warehouse `workspace.json` 为准。
- 分册：按团队板块裁剪（`full` / `online_private` / `online_platform` / `offline_market`）；旧业务组 `liuxue/gaozhong/daxue` 不再日更。C 层 secrets 以密码本重建（600）。**门口变更后需再跑 `install_dashboard_auth.sh`**
- 钉钉五通道：`online_private` / `online_platform` / `offline_youth` / `offline_high_school` / `offline_university`。本机已填线下青少/高中/大学和线上私域；线上平台仍空。
- 大学通道播报图展示工单 + 人头（去重 `学员编号`，不含 1500），落后仍按工单；明细表人员进度另带现金目标/完成。其余通道工单 + 现金。花名册以 `workspace_modeling/operations/people.json` 覆盖 artifact；小初提能组现员潘体学（工单 25、现金 50,000）。A 层 overlay **必须带 people.json**，不要沿用排除花名册的旧包。
- 刷新消费 `dashboard_actuals/v10`：目标区仍是留学预备/高中/大学；同比区青少/初中/高中/大学。查询第 12 列为现金 `student_id`。无法判断/空团队且跟进顾问为张艺彤时按留学预备回落。全量页第五页签「市场人员产能」不进钉钉。
- 临时补丁：`TMK激活-平台` + 活动名含 `校代系统资源` + 线下花名册市场人员，从线上平台打回线下。overlay 必须带 `refresh.py` 和 notify SQL。不要读业务代码重写。
- 例行「看板日更」每天 **10:00** Asia/Shanghai（挂许家印名下）：refresh→团队板块四分册 render→publish。钉钉需另跑 `notify send`。
- 全量 `artifact.json` 留在本地，不进公网
- 不要建设本机↔Grok 双向 MCP；A 层用 overlay + sha256，C 层单独拷 `.env.server`。不要读业务代码重写。

## 红线
不推公开 `data-oxhor`；密钥不进聊天；不改数仓 snapshot 语义/入仓代码；跨界经赵高。

## 同步合同（强制）
全员遵守 `/home/box/oxhor/SYNC.md` §5。
