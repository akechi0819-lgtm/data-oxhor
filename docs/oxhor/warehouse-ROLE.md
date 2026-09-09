# warehouse — 数仓管理员（云电脑）

## 职责
本目录是 Data OXHor「数仓」在云电脑上的工作区。真源仍是本机 `/Users/akechi/Desktop/manager -CowH`；私密 GitHub 仓仅中转。

## 激活运行环境
```bash
cd /home/box/oxhor/warehouse
source .venv/bin/activate
# 或直接用：.venv/bin/python ...
```

当前环境：Python 3.13 + `data-oxhor[full]`（含 `duckdb==1.5.5`）。

安装方式：`sh tools/install_runtime.sh full`  
说明：云电脑这份 `pyproject.toml` 里 `package-data` 键已加引号才能装上；本机底稿若同样报错需同步改法。`tools/s4_ppt_preflight.py` 本包未带，安装脚本末尾会报缺文件，依赖其实已装好。

## 常用命令
```bash
# 依赖检查
.venv/bin/python -m interfaces.workspace_modeling doctor --profile full

# 当前 bi_operations 快照（只读）
DB=customers/bi_operations/Work/Runs/run_bi_operations_20260907/data/snapshots/snapshot_bi_operations_20260907/warehouse.duckdb
SID=snapshot_bi_operations_20260907
RID=run_bi_operations_20260907

.venv/bin/python -m interfaces.data_platform describe --warehouse "$DB" --snapshot-id "$SID"
.venv/bin/python -m interfaces.data_platform quality --warehouse "$DB" --snapshot-id "$SID" --run-id "$RID" --output-root /tmp/oxhor-smoke-quality --max-rows 20
```

## 状态补丁：实盘 current_snapshot 以 workspace.json 为准（E2E 后多为 snapshot_bi_operations_20260907_e2e）。

## 阶段 A 结果摘要（2026-09-07）
- doctor `--profile full`：`doctor_passed`（duckdb / pptx / pathops / uharfbuzz / openpyxl / PIL / numpy / fitz / nbconvert / requests / business_pack 均过）
- describe：`passed`（快照 `snapshot_bi_operations_20260907`）
- quality：`passed`（0 行问题；未改数据、未发新 snapshot）

## 红线
不推公开 `data-oxhor`；不擅自迁密钥；dashboard/analysis 另目录另阶段。

## BI 登录态（阶段 B）

主路径（cwd 视为 `customers/bi_operations`）：
- 会话：`customers/bi_operations/data_acquisition/storage/auth_sessions/bi/{cookies.json,localStorage.json}`
- 浏览器档案：`customers/bi_operations/data_acquisition/storage/browser_profiles/bi/`
- 旁路 `data_layer/storage` 勿当主

续期：
1. 云电脑进入 warehouse，激活 `.venv`，确保已装 `playwright` 与系统 Chrome
2. 用项目 `PlaywrightBIExportClient.open()`（或同等探测脚本）打开 `https://bibr.staff.xdf.cn/page/c72ee6c698a5d416ba55733a`
3. 若跳到钉钉扫码：把云电脑桌面交给用户扫码；回到 `bibr.staff.xdf.cn/page/...` 后 `_export_auth_session` 写回主路径
4. **禁止**把 cookies / profile / 登录态推进公开仓 `akechi0819-lgtm/data-oxhor`

阶段 B 结果（2026-09-07）：钉钉扫码后续期成功；cookies 已写回主路径（约 9 条，含 live `uIdToken`）；localStorage 仍为空；下一步可做受控采集（未在本阶段触发大表导出）。


## 同步合同（强制）
全员遵守 `/home/box/oxhor/SYNC.md` §5「各 Bot 必须遵守」：真源本机↔云；分层传；显式 snapshot_id；守目录；日更顺序；禁公开仓经营数据/密钥。
