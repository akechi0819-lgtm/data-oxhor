# Data OXHor 同步合同（强制）

> 状态：强制合同（阶段 D，2026-09-07）。全员 Bot 必须遵守。  
> 真源底稿：本机 `/Users/akechi/Desktop/manager -CowH`  
> 云电脑布局：`/home/box/oxhor/{warehouse,dashboard,analysis,monitor}`  
> 本文优先于各 ROLE 里过时的「本轮未拷」叙述；冲突时以本文 + 显式 `snapshot_id` 为准。

---

## 1. 分层（禁止混传）

| 层 | 内容（示例） | 默认同向 | 红线 |
|---|---|---|---|
| **A 代码/合同/配置** | `data_*`、`interfaces`、`tools`、`workspace_modeling`、`dashboard_product`、`agents/*/AGENT.md`、`ROLE.md`、`SYNC.md`、saved query、非密钥 config | 双向可同步；云侧改动日更回本机 | 不经公开仓推经营数据 |
| **B customers 数据** | `customers/*/Work`、`Output`、snapshots、duckdb、采集落地 | **云→本机回写**（日更）；本机→云仅显式迁移/补洞 | 禁 `latest`；冲突以**显式 snapshot_id** 为准 |
| **C 密钥/登录态** | `.env.server`、cookies、localStorage、browser_profiles、token | **单独通道**；默认不进例行全量包 | 禁贴聊天；禁进公开 `data-oxhor`；禁进私密中转仓除非用户显式授权且短期删除 |

分层规则：
- 打包/回写必须分层声明，不得把 C 混进 A/B 常规包。
- B 层回写按 workspace + 显式 `snapshot_id` / `run_id` 对齐；禁止依赖「当前 latest」语义。
- A 层改动（含云上 `pyproject.toml` 热修）应回写本机，避免双底稿漂移。

---

## 2. 方向与频率

| 方向 | 用途 | 频率 / 触发 |
|---|---|---|
| 本机 → 云 | 首次迁移、补洞、代码底稿更新 | 人工 / 赵高派工 |
| **云 → 本机** | 日更回写（仓产物、合同修订、看板薄包非密钥变更） | **每天 00:00 Asia/Shanghai**（例行挂**牛马力工**；赵高不代挂） |
| 私密中转仓 | 仅大包搬运缓冲 | 用完即弃语义；**非新真源** |

冲突裁决：
1. 数据以**显式 `snapshot_id`**（及对应 `run_id`）为准；禁止用 `latest` /「最新文件夹名」猜。
2. `workspace.json` 的 `current_snapshot_id` 必须与选定 snapshot 一致后再回写/发布。
3. 同路径文件冲突：例行回写前比对 mtime/尺寸；不确定则**停手通知用户**，不覆盖本机未知改动。
4. 本机 Codex 旧定时已停；云侧日更勿双刷。

例行回写执行人：牛马力工。首跑或用户另令前**不做全量回写**。

通道注意：本机 ListMachines / CopyToBox 易被 Clash/VPN/系统代理打断；失败记日志并通知用户，不静默重试到损坏。Clash Party 覆写已把 `Grok Bot` / Helper / `CUGrokBotService` / `sand-op-launcher` 设为 `PROCESS-NAME,DIRECT`（TUN 模式才生效）。

---

## 3. 中转与公开仓红线

- **允许**：私密仓 `akechi0819-lgtm/oxhor-warehouse-xfer` **仅中转**本机↔云大包。
- **禁止**：把 `customers/`、经营数据、密钥、登录态推进公开仓 `akechi0819-lgtm/data-oxhor`。
- **禁止**：把私密中转仓当成新主仓或长期真源。
- 公开仓只承载可对外的瘦身代码/文档。

---

## 4. 角色目录边界

| 目录 | 角色 | 可写 | 只读/禁区 |
|---|---|---|---|
| `/home/box/oxhor/warehouse/` | 孙悟空（仓务）+ 牛马力工（环境/迁移） | 仓代码、venv、重建 snapshot、BI 会话写回 | 不发布看板；不改 dashboard `.env.server` |
| `/home/box/oxhor/dashboard/` | 许家印（日刷）+ 牛马力工（接线） | refresh/render；（授权后）publish；读软链 customers | 不改数仓 snapshot 语义；密钥不外泄 |
| `/home/box/oxhor/analysis/` | 弗洛伊德 | 分析产物（落地后） | 未迁完前占位；禁臆造因果当结论 |
| `/home/box/oxhor/monitor/` | 魏忠贤 | 契约化监控（落地后） | 未产品化前不装值守 |

软链约定：`dashboard/customers|interfaces|data_platform` → warehouse 对应路径；看板只读数仓。

日更顺序（已挂）：约 **09:30** 仓重建 → 约 **10:00** 看板 refresh/render/真发。回写本机在 **00:00**，不与上述抢跑。

---

## 5. 各 Bot 必须遵守（可贴进角色描述）

1. 真源：本机底稿 ↔ 云 `/home/box/oxhor/`；私密仓只中转；禁推公开 `data-oxhor` 经营数据/密钥。  
2. 分层传：代码/合同 ≠ customers 数据 ≠ 密钥登录态；C 层不进常规包、不进聊天。  
3. 数据指认只用显式 `snapshot_id`（+`run_id`）；禁 `latest`。  
4. 守目录：warehouse / dashboard / analysis / monitor 各管各的；跨界先经赵高。  
5. 日更：仓→看板顺序固定；云→本机回写默认 00:00 由牛马力工执行，失败必须通知用户。  
6. 赵高策划验收；牛马力工搬砖接线；不擅自全量回写、不擅自真发（除非已授权例行/派工）。

---

## 6. 现状摘要（2026-09-07，便于对账）

- warehouse 已落地 + `.venv` + BI 登录态可用；E2E snapshot=`snapshot_bi_operations_20260907_e2e`。  
- dashboard 薄包 + `.env.server`(600)；真发成功；公网 `http://dashboard.apinova.cn/`。  
- analysis / monitor：占位。  
- 例行：孙悟空仓更新 09:30；许家印看板日更 10:00；牛马力工云→本机回写 00:00（合同已立，全量回写待首跑/另令）。

### 审计黄灯（用户口径：非问题，勿派 P0）
- 云侧尚未全量回写本机（等 00:00 例行首跑或另令）
- 云 e2e snapshot 可暂≠本机底稿（回写对齐）
- 私密 xfer 仓未逐文件核销（中转临时性）

## 7. 派工治理（2026-09-07）
- 模块内小改：用户可直接与模块主对话并派牛马力工，不必经赵高同意。
- 跨角色 / SYNC / 大迁移 / 例行体系 / 排期冲突：经赵高。

## 8. 2026-09-09 补丁（看板钉钉）

- 本机 A 层已含四分册、basic auth 和钉钉人员进度代码。云电脑独立发送钉钉前，必须 C 层同步 `dashboard_product/.env.server`（600）到 `/home/box/oxhor/dashboard/dashboard_product/.env.server`。
- 禁止把 webhook 写入公开 `data-oxhor`、禁止贴聊天、禁止建设本机↔Grok 双向 MCP。
- 2026-09-09 本机已填 `DINGTALK_WEBHOOK_OFFLINE_YOUTH` / `OFFLINE_HIGH_SCHOOL`；`ONLINE_PRIVATE`、`ONLINE_PLATFORM`、`OFFLINE_UNIVERSITY` 仍空，空通道跳过。
- A 层上云继续 overlay + sha256；不要让 Grok 读业务代码重写。
