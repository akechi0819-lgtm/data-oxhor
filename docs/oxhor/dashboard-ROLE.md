# dashboard — 许家印（看板运维）

## 职责
对已确认口径跑固定 saved query：`dashboard_actuals/v7` → refresh **一次**全量 artifact → 按团队板块渲四分册 HTML（`full` / `online_private` / `online_platform` / `offline_market`）→ **真发**到现有服务器（公网 `http://dashboard.apinova.cn/`，basic auth，匿名看不到全量）。

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
python -m dashboard_product.notify send --artifact "$ART" --dry-run

# 日更默认真发（用户已拍板）：一次 refresh + 四分册上传，不传 artifact.json
./dashboard_product/deploy/publish_static_dashboard.sh
```

分册与 htpasswd 操作见 `dashboard_product/docs/AUTH_TEAM_BOOKLETS_RUN.md`。`/healthz` 仍匿名；业务页需登录。**本轮若未上 TLS，HTTP+basic auth 密码在网上裸奔。**

## 状态（2026-09-09）
- 薄包与 `.env.server`(600) 已落地。钉钉独立运行还依赖该文件里的 `DINGTALK_WEBHOOK_*` / `DINGTALK_SECRET_*`，必须走 C 层 CopyToBox，禁止贴聊天。
- 当前工作区 Snapshot 以 warehouse `workspace.json` 为准（2026-09-09 为 `snapshot_bi_operations_20260908`）。
- 分册：按团队板块裁剪（`full` / `online_private` / `online_platform` / `offline_market`）；旧业务组 `liuxue/gaozhong/daxue` 不再日更。C 层 secrets 以密码本重建（600）。**门口变更后需再跑 `install_dashboard_auth.sh`**
- 钉钉五通道代码已在本机落地：`online_private` / `online_platform` / `offline_youth` / `offline_high_school` / `offline_university`。2026-09-09 本机已填线下青少/高中/大学 webhook；线上私域、线上平台仍空。
- 刷新消费 `dashboard_actuals/v7`：目标区仍是留学预备/高中/大学；渠道同比和年级同比用青少/初中/高中/大学。现金跨月按工单 ID 回查全量工单再归属个人。
- 例行「看板日更」每天 **10:00** Asia/Shanghai（挂许家印名下）：refresh→团队板块四分册 render→publish。钉钉需另跑 `notify send`。
- 全量 `artifact.json` 留在本地，不进公网
- 不要建设本机↔Grok 双向 MCP；A 层用 overlay + sha256，C 层单独拷 `.env.server`

## 红线
不推公开 `data-oxhor`；密钥不进聊天；不改数仓 snapshot 语义/入仓代码；跨界经赵高。

## 同步合同（强制）
全员遵守 `/home/box/oxhor/SYNC.md` §5。
